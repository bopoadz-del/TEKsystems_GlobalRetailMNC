"""Demand and reorder calibrator — deterministic advisory learning."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.retailops.learning.common import (
    confidence_label,
    mean,
    parse_dt,
    period_bounds,
    round4,
    safe_div,
)


class DemandReorderCalibrator:
    """Learn forecast bias and advisory reorder/safety-stock adjustments."""

    module = "demand_reorder"
    entity_type = "sku_store"

    def validate_payload(self, payload: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        for key in ("sku", "forecast_quantity", "actual_sales_quantity"):
            if payload.get(key) is None or payload.get(key) == "":
                errors.append(f"missing:{key}")
        if payload.get("store") is None and payload.get("region") is None:
            errors.append("missing:store_or_region")
        return errors

    def entity_key_from_payload(self, payload: Dict[str, Any]) -> str:
        loc = payload.get("store") or payload.get("region") or "unknown"
        return f"{payload.get('sku')}|{loc}"

    def calculate(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        ratios: List[float] = []
        biases: List[float] = []
        abs_errors: List[float] = []
        stockouts = 0
        reorder_points: List[float] = []
        safety_stocks: List[float] = []
        payloads = [e.get("event_payload") or {} for e in events]

        for p in payloads:
            forecast = float(p.get("forecast_quantity") or 0)
            actual = float(p.get("actual_sales_quantity") or 0)
            ratio = safe_div(actual, forecast)
            if ratio is not None:
                ratios.append(ratio)
            biases.append(actual - forecast)
            abs_errors.append(abs(actual - forecast))
            if bool(p.get("stockout_occurrence")):
                stockouts += 1
            if p.get("current_reorder_point") is not None:
                reorder_points.append(float(p["current_reorder_point"]))
            if p.get("safety_stock") is not None:
                safety_stocks.append(float(p["safety_stock"]))

        sample_count = len(payloads)
        avg_ratio = mean(ratios)
        avg_bias = mean(biases)
        avg_abs_error = mean(abs_errors)
        current_rop = mean(reorder_points)
        current_safety = mean(safety_stocks)

        # Advisory reorder: scale current ROP by average actual/forecast ratio.
        # Cap adjustment between 0.5x and 2.0x of current value.
        learned_adjustment = None
        recommended_rop = None
        if current_rop is not None and avg_ratio is not None:
            factor = max(0.5, min(2.0, avg_ratio))
            recommended_rop = round4(current_rop * factor)
            learned_adjustment = round4(recommended_rop - current_rop)

        # Safety-stock adequacy: if stockouts frequent, recommend +20%.
        stockout_frequency = safe_div(stockouts, sample_count, 0.0) or 0.0
        recommended_safety = None
        safety_adequate = None
        if current_safety is not None:
            safety_adequate = stockout_frequency < 0.25
            if not safety_adequate:
                recommended_safety = round4(current_safety * 1.2)
            else:
                recommended_safety = round4(current_safety)

        start, end = period_bounds(payloads)
        confidence = confidence_label(sample_count)

        return {
            "actual_to_forecast_ratio": round4(avg_ratio),
            "forecast_bias": round4(avg_bias),
            "forecast_absolute_error": round4(avg_abs_error),
            "current_reorder_point": round4(current_rop),
            "recommended_reorder_point": recommended_rop,
            "learned_reorder_adjustment": learned_adjustment,
            "current_safety_stock": round4(current_safety),
            "recommended_safety_stock": recommended_safety,
            "safety_stock_adequacy": safety_adequate,
            "stockout_frequency": round4(stockout_frequency),
            "sample_count": sample_count,
            "confidence": confidence,
            "source_period_start": start.isoformat() if start else None,
            "source_period_end": end.isoformat() if end else None,
            "assumptions": [
                "advisory_only_does_not_overwrite_source_systems",
                "recommended_reorder_point = current_reorder_point * clamp(avg(actual/forecast), 0.5, 2.0)",
                "safety_stock +20% when stockout_frequency >= 0.25",
                "high confidence requires >= 8 verified samples",
            ],
        }

    def recommend(
        self,
        *,
        profile_metrics: Optional[Dict[str, Any]],
        current_reorder_point: Optional[float] = None,
        current_safety_stock: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not profile_metrics:
            return {
                "status": "dependency_required",
                "reason": "no_verified_learning_profile",
            }
        current_rop = (
            current_reorder_point
            if current_reorder_point is not None
            else profile_metrics.get("current_reorder_point")
        )
        current_ss = (
            current_safety_stock
            if current_safety_stock is not None
            else profile_metrics.get("current_safety_stock")
        )
        recommended_rop = profile_metrics.get("recommended_reorder_point")
        recommended_ss = profile_metrics.get("recommended_safety_stock")
        if current_reorder_point is not None and profile_metrics.get("actual_to_forecast_ratio") is not None:
            factor = max(0.5, min(2.0, float(profile_metrics["actual_to_forecast_ratio"])))
            recommended_rop = round4(current_reorder_point * factor)
        return {
            "status": "ok",
            "current_reorder_point": current_rop,
            "recommended_reorder_point": recommended_rop,
            "learned_reorder_adjustment": round4(
                (recommended_rop - current_rop)
                if recommended_rop is not None and current_rop is not None
                else None
            ),
            "current_safety_stock": current_ss,
            "recommended_safety_stock": recommended_ss,
            "sample_count": profile_metrics.get("sample_count"),
            "confidence": profile_metrics.get("confidence"),
            "source_period_start": profile_metrics.get("source_period_start"),
            "source_period_end": profile_metrics.get("source_period_end"),
            "assumptions": profile_metrics.get("assumptions") or [],
            "advisory_only": True,
        }
