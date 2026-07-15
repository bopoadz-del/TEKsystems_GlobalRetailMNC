"""Shared helpers for deterministic retail outcome learning."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

MODULES = (
    "demand_reorder",
    "supplier_fulfilment",
    "promotion_effectiveness",
    "store_exceptions",
)

# Confidence thresholds documented in the pilot contract.
CONFIDENCE_LOW_MAX = 2          # fewer than 3 → low
CONFIDENCE_MEDIUM_MAX = 7       # 3..7 → medium
# 8+ → high

SEVERITY_WEIGHTS = {
    "critical": 5.0,
    "high": 3.0,
    "medium": 2.0,
    "low": 1.0,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def confidence_label(sample_count: int) -> str:
    n = int(sample_count or 0)
    if n < 3:
        return "low"
    if n <= CONFIDENCE_MEDIUM_MAX:
        return "medium"
    return "high"


def safe_div(numerator: float, denominator: float, default: Optional[float] = None) -> Optional[float]:
    if denominator == 0:
        return default
    return numerator / denominator


def mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def round4(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 4)


def parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def entity_key(*parts: Any) -> str:
    return "|".join(str(p).strip() for p in parts if p is not None and str(p).strip() != "")


def period_bounds(payloads: Iterable[Dict[str, Any]]) -> tuple[Optional[datetime], Optional[datetime]]:
    starts: List[datetime] = []
    ends: List[datetime] = []
    for p in payloads:
        ps = parse_dt(p.get("period_start") or p.get("promised_date") or p.get("occurrence_date"))
        pe = parse_dt(p.get("period_end") or p.get("actual_delivery_date") or p.get("occurrence_date"))
        if ps:
            starts.append(ps)
        if pe:
            ends.append(pe)
    return (min(starts) if starts else None, max(ends) if ends else None)
