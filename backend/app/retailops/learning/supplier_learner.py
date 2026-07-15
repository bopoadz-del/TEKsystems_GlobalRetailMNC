"""Supplier fulfilment learner — deterministic reliability metrics."""

from __future__ import annotations

from typing import Any, Dict, List

from app.retailops.learning.common import (
    confidence_label,
    mean,
    parse_dt,
    period_bounds,
    round4,
    safe_div,
)


def _reliability_class(*, on_time_pct: float, otif_pct: float, fill_rate: float) -> str:
    """Documented deterministic reliability bands."""
    if on_time_pct >= 0.9 and otif_pct >= 0.85 and fill_rate >= 0.95:
        return "reliable"
    if on_time_pct >= 0.75 and otif_pct >= 0.7 and fill_rate >= 0.85:
        return "watch"
    return "at_risk"


class SupplierFulfilmentLearner:
    module = "supplier_fulfilment"
    entity_type = "supplier"

    def validate_payload(self, payload: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        for key in (
            "supplier",
            "promised_date",
            "actual_delivery_date",
            "ordered_quantity",
            "delivered_quantity",
        ):
            if payload.get(key) is None or payload.get(key) == "":
                errors.append(f"missing:{key}")
        return errors

    def entity_key_from_payload(self, payload: Dict[str, Any]) -> str:
        return str(payload.get("supplier") or "unknown")

    def calculate(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        payloads = [e.get("event_payload") or {} for e in events]
        delays: List[float] = []
        on_time = 0
        fill_rates: List[float] = []
        otif = 0
        rejected = 0.0
        damaged = 0.0
        ordered_total = 0.0

        for p in payloads:
            promised = parse_dt(p.get("promised_date"))
            actual = parse_dt(p.get("actual_delivery_date"))
            ordered = float(p.get("ordered_quantity") or 0)
            delivered = float(p.get("delivered_quantity") or 0)
            rejected_q = float(p.get("rejected_quantity") or 0)
            damaged_q = float(p.get("damaged_quantity") or 0)
            ordered_total += ordered
            rejected += rejected_q
            damaged += damaged_q
            if promised and actual:
                delay_days = (actual - promised).total_seconds() / 86400.0
                delays.append(delay_days)
                if delay_days <= 0:
                    on_time += 1
            fill = safe_div(delivered, ordered, 0.0) or 0.0
            fill_rates.append(fill)
            if promised and actual and (actual - promised).total_seconds() <= 0 and fill >= 0.999:
                otif += 1

        sample_count = len(payloads)
        on_time_pct = safe_div(on_time, sample_count, 0.0) or 0.0
        fill_rate = mean(fill_rates) or 0.0
        otif_pct = safe_div(otif, sample_count, 0.0) or 0.0
        rejection_rate = safe_div(rejected, ordered_total, 0.0) or 0.0
        damage_rate = safe_div(damaged, ordered_total, 0.0) or 0.0
        avg_delay = mean(delays) or 0.0
        reliability = _reliability_class(
            on_time_pct=on_time_pct, otif_pct=otif_pct, fill_rate=fill_rate
        )
        start, end = period_bounds(payloads)

        return {
            "average_delay_days": round4(avg_delay),
            "on_time_percentage": round4(on_time_pct),
            "fill_rate": round4(fill_rate),
            "otif_percentage": round4(otif_pct),
            "rejection_rate": round4(rejection_rate),
            "damage_rate": round4(damage_rate),
            "reliability_classification": reliability,
            "reliability_bands": {
                "reliable": "on_time>=0.9 and otif>=0.85 and fill_rate>=0.95",
                "watch": "on_time>=0.75 and otif>=0.7 and fill_rate>=0.85",
                "at_risk": "otherwise",
            },
            "sample_count": sample_count,
            "confidence": confidence_label(sample_count),
            "source_period_start": start.isoformat() if start else None,
            "source_period_end": end.isoformat() if end else None,
        }
