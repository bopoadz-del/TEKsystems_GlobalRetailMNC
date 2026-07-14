"""Store exception pattern detector — deterministic frequency and risk scoring."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from app.retailops.learning.common import (
    SEVERITY_WEIGHTS,
    confidence_label,
    parse_dt,
    period_bounds,
    round4,
)

KNOWN_EXCEPTION_TYPES = (
    "inventory_discrepancy",
    "shrinkage",
    "spoilage",
    "safety_incident",
    "promotion_non_compliance",
    "supplier_failure",
    "missing_evidence",
    "customer_complaint",
    "operational_breach",
)


class StoreExceptionPatternDetector:
    module = "store_exceptions"
    entity_type = "store"

    def validate_payload(self, payload: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        for key in ("store", "exception_type", "severity", "occurrence_date"):
            if payload.get(key) is None or payload.get(key) == "":
                errors.append(f"missing:{key}")
        et = payload.get("exception_type")
        if et and et not in KNOWN_EXCEPTION_TYPES:
            errors.append(f"unknown_exception_type:{et}")
        sev = str(payload.get("severity") or "").lower()
        if sev and sev not in SEVERITY_WEIGHTS:
            errors.append(f"unknown_severity:{sev}")
        return errors

    def entity_key_from_payload(self, payload: Dict[str, Any]) -> str:
        return str(payload.get("store") or "unknown")

    def calculate(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        payloads = [e.get("event_payload") or {} for e in events]
        by_type: Counter = Counter()
        by_region: Counter = Counter()
        by_root: Counter = Counter()
        by_category: Counter = Counter()
        weighted = 0.0
        trend: Dict[str, int] = defaultdict(int)

        for p in payloads:
            et = str(p.get("exception_type") or "unknown")
            by_type[et] += 1
            region = str(p.get("region") or "unknown")
            by_region[region] += 1
            root = str(p.get("root_cause") or "unspecified")
            by_root[root] += 1
            category = str(p.get("category") or "general")
            by_category[category] += 1
            sev = str(p.get("severity") or "low").lower()
            weighted += SEVERITY_WEIGHTS.get(sev, 1.0)
            when = parse_dt(p.get("occurrence_date") or p.get("period_start"))
            if when:
                bucket = when.strftime("%Y-%m")
                trend[bucket] += 1

        sample_count = len(payloads)
        top_patterns = [
            {"exception_type": k, "count": v}
            for k, v in by_type.most_common(5)
        ]
        recurring_root_causes = [
            {"root_cause": k, "count": v} for k, v in by_root.most_common(5)
        ]
        highest_risk_category = by_category.most_common(1)[0][0] if by_category else None
        start, end = period_bounds(payloads)
        risk_score = round4(weighted / max(sample_count, 1))

        return {
            "top_exception_patterns": top_patterns,
            "frequency_by_store": {self.entity_key_from_payload(payloads[0]) if payloads else "unknown": sample_count},
            "frequency_by_region": dict(by_region),
            "severity_weighted_risk_score": risk_score,
            "severity_weights": dict(SEVERITY_WEIGHTS),
            "recurring_root_causes": recurring_root_causes,
            "highest_risk_category": highest_risk_category,
            "trend_by_period": dict(sorted(trend.items())),
            "sample_count": sample_count,
            "confidence": confidence_label(sample_count),
            "source_period_start": start.isoformat() if start else None,
            "source_period_end": end.isoformat() if end else None,
        }
