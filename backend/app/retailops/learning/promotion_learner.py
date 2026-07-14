"""Promotion effectiveness learner — deterministic commercial impact metrics."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.retailops.learning.common import (
    confidence_label,
    mean,
    period_bounds,
    round4,
    safe_div,
)


class PromotionEffectivenessLearner:
    module = "promotion_effectiveness"
    entity_type = "campaign"

    def validate_payload(self, payload: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        for key in ("campaign", "baseline_units", "promoted_units"):
            if payload.get(key) is None or payload.get(key) == "":
                errors.append(f"missing:{key}")
        return errors

    def entity_key_from_payload(self, payload: Dict[str, Any]) -> str:
        loc = payload.get("store") or payload.get("region") or "all"
        return f"{payload.get('campaign')}|{loc}"

    def calculate(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        payloads = [e.get("event_payload") or {} for e in events]
        unit_uplifts: List[float] = []
        revenue_uplifts: List[float] = []
        margin_changes: List[float] = []
        compliance_vals: List[float] = []
        stockouts = 0
        invalid_baseline = 0

        for p in payloads:
            base_u = float(p.get("baseline_units") or 0)
            promo_u = float(p.get("promoted_units") or 0)
            base_r = p.get("baseline_revenue")
            promo_r = p.get("promoted_revenue")
            base_m = p.get("baseline_margin")
            promo_m = p.get("promoted_margin")

            if base_u <= 0:
                invalid_baseline += 1
            else:
                unit_uplifts.append((promo_u - base_u) / base_u)

            if base_r is not None and promo_r is not None:
                base_r_f = float(base_r)
                promo_r_f = float(promo_r)
                if base_r_f <= 0:
                    invalid_baseline += 1
                else:
                    revenue_uplifts.append((promo_r_f - base_r_f) / base_r_f)

            if base_m is not None and promo_m is not None:
                margin_changes.append(float(promo_m) - float(base_m))

            if p.get("compliance_percentage") is not None:
                compliance_vals.append(float(p["compliance_percentage"]))
            if bool(p.get("promotion_related_stockout")):
                stockouts += 1

        sample_count = len(payloads)
        unit_uplift = mean(unit_uplifts)
        revenue_uplift = mean(revenue_uplifts)
        margin_change = mean(margin_changes)
        compliance = mean(compliance_vals)
        stockout_frequency = safe_div(stockouts, sample_count, 0.0) or 0.0

        # Effectiveness score: reward uplift/margin, penalise stockouts and low compliance.
        score_components: List[float] = []
        if unit_uplift is not None:
            score_components.append(max(-1.0, min(1.0, unit_uplift)))
        if revenue_uplift is not None:
            score_components.append(max(-1.0, min(1.0, revenue_uplift)))
        if margin_change is not None:
            score_components.append(max(-1.0, min(1.0, margin_change / 100.0)))
        effectiveness = mean(score_components)
        if effectiveness is not None:
            if compliance is not None:
                effectiveness *= max(0.0, min(1.0, compliance / 100.0))
            effectiveness -= stockout_frequency * 0.25

        start, end = period_bounds(payloads)
        return {
            "unit_uplift_percentage": round4((unit_uplift or 0) * 100) if unit_uplift is not None else None,
            "revenue_uplift_percentage": round4((revenue_uplift or 0) * 100) if revenue_uplift is not None else None,
            "margin_change": round4(margin_change),
            "compliance_percentage": round4(compliance),
            "compliance_relationship": (
                "positive" if (compliance or 0) >= 80 and (unit_uplift or 0) > 0 else "weak_or_negative"
            ),
            "stockout_frequency": round4(stockout_frequency),
            "effectiveness_score": round4(effectiveness),
            "invalid_baseline_count": invalid_baseline,
            "fabricated_uplift": False,
            "sample_count": sample_count,
            "confidence": confidence_label(sample_count),
            "source_period_start": start.isoformat() if start else None,
            "source_period_end": end.isoformat() if end else None,
            "notes": [
                "zero_or_missing_baselines_excluded_from_uplift",
                "effectiveness_score_is_advisory",
            ],
        }
