"""Retail Outcome Learning Engine — verified-only, deterministic, tenant-scoped."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.retailops.learning.common import MODULES, parse_dt, utcnow
from app.retailops.learning.demand_calibrator import DemandReorderCalibrator
from app.retailops.learning.exception_detector import StoreExceptionPatternDetector
from app.retailops.learning.promotion_learner import PromotionEffectivenessLearner
from app.retailops.learning.supplier_learner import SupplierFulfilmentLearner
from app.retailops.models import RetailLearningEvent, RetailLearningProfile

_MODULES = {
    DemandReorderCalibrator.module: DemandReorderCalibrator(),
    SupplierFulfilmentLearner.module: SupplierFulfilmentLearner(),
    PromotionEffectivenessLearner.module: PromotionEffectivenessLearner(),
    StoreExceptionPatternDetector.module: StoreExceptionPatternDetector(),
}


def _id(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return "rl_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class RetailOutcomeLearningEngine:
    """Persist verified events and recalculate advisory profiles."""

    def module_names(self) -> Tuple[str, ...]:
        return MODULES

    def get_module(self, name: str):
        return _MODULES.get(name)

    def validate_module_payload(self, module: str, payload: Dict[str, Any]) -> List[str]:
        mod = self.get_module(module)
        if mod is None:
            return [f"unknown_module:{module}"]
        return list(mod.validate_payload(payload or {}))

    def record_verified_outcome(
        self,
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        module: str,
        payload: Dict[str, Any],
        verified_by: str,
        deduplication_key: str,
        event_type: Optional[str] = None,
        source_document_id: Optional[str] = None,
        source_action_run_id: Optional[str] = None,
        source_reference: Optional[str] = None,
        verification_status: str = "verified",
    ) -> Dict[str, Any]:
        if not tenant_id or not project_id:
            raise ValueError("tenant_id and project_id are mandatory")
        if verification_status != "verified":
            # Unverified events may be stored but must not update profiles.
            event = self._insert_event(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                module=module,
                payload=payload,
                verified_by=verified_by,
                deduplication_key=deduplication_key,
                event_type=event_type,
                source_document_id=source_document_id,
                source_action_run_id=source_action_run_id,
                source_reference=source_reference,
                verification_status=verification_status,
                skip_if_duplicate=True,
            )
            return {
                "event_id": event.id if event else None,
                "profile_updated": False,
                "reason": "verification_status_not_verified",
                "idempotent": event is not None,
            }

        errors = self.validate_module_payload(module, payload)
        if errors:
            raise ValueError("payload_invalid:" + ",".join(errors))

        existing = session.execute(
            select(RetailLearningEvent).where(
                RetailLearningEvent.tenant_id == tenant_id,
                RetailLearningEvent.project_id == project_id,
                RetailLearningEvent.deduplication_key == deduplication_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            profile = self._get_profile(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                module=module,
                entity_type=existing.entity_type,
                entity_key=existing.entity_key,
            )
            return {
                "event_id": existing.id,
                "module": module,
                "profile_key": existing.entity_key,
                "profile_version": profile.version if profile else None,
                "sample_count": profile.sample_count if profile else 0,
                "confidence": profile.confidence if profile else "low",
                "changed_metrics": {},
                "idempotent": True,
                "profile_updated": False,
                "warnings": ["duplicate_deduplication_key"],
            }

        event = self._insert_event(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            module=module,
            payload=payload,
            verified_by=verified_by,
            deduplication_key=deduplication_key,
            event_type=event_type,
            source_document_id=source_document_id,
            source_action_run_id=source_action_run_id,
            source_reference=source_reference,
            verification_status="verified",
            skip_if_duplicate=False,
        )
        assert event is not None
        before = self._get_profile(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            module=module,
            entity_type=event.entity_type,
            entity_key=event.entity_key,
        )
        before_metrics = dict(before.metrics or {}) if before else {}
        profile = self.recalculate_profile(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            module=module,
            entity_type=event.entity_type,
            entity_key=event.entity_key,
            last_event_id=event.id,
        )
        changed = {
            k: profile.metrics.get(k)
            for k in sorted(set(profile.metrics) | set(before_metrics))
            if profile.metrics.get(k) != before_metrics.get(k)
        }
        return {
            "event_id": event.id,
            "module": module,
            "profile_key": profile.entity_key,
            "profile_version": profile.version,
            "sample_count": profile.sample_count,
            "confidence": profile.confidence,
            "changed_metrics": changed,
            "idempotent": False,
            "profile_updated": True,
            "warnings": [],
            "evidence": {
                "source_document_id": event.source_document_id,
                "source_action_run_id": event.source_action_run_id,
                "source_reference": event.source_reference,
                "verified_by": event.verified_by,
                "verified_at": event.verified_at.isoformat() if event.verified_at else None,
            },
        }

    def recalculate_profile(
        self,
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        module: str,
        entity_type: str,
        entity_key: str,
        last_event_id: Optional[str] = None,
    ) -> RetailLearningProfile:
        mod = self.get_module(module)
        if mod is None:
            raise ValueError(f"unknown_module:{module}")
        events = session.execute(
            select(RetailLearningEvent)
            .where(
                RetailLearningEvent.tenant_id == tenant_id,
                RetailLearningEvent.project_id == project_id,
                RetailLearningEvent.module == module,
                RetailLearningEvent.entity_type == entity_type,
                RetailLearningEvent.entity_key == entity_key,
                RetailLearningEvent.verification_status == "verified",
            )
            .order_by(RetailLearningEvent.event_time.asc())
        ).scalars().all()
        rows = [
            {
                "event_payload": dict(e.event_payload or {}),
                "event_time": e.event_time,
            }
            for e in events
        ]
        metrics = mod.calculate(rows)
        sample_count = int(metrics.get("sample_count") or len(rows))
        confidence = str(metrics.get("confidence") or "low")
        start = parse_dt(metrics.get("source_period_start"))
        end = parse_dt(metrics.get("source_period_end"))

        profile = self._get_profile(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            module=module,
            entity_type=entity_type,
            entity_key=entity_key,
        )
        now = utcnow()
        if profile is None:
            profile = RetailLearningProfile(
                id=_id(tenant_id, project_id, module, entity_type, entity_key),
                tenant_id=tenant_id,
                project_id=project_id,
                module=module,
                entity_type=entity_type,
                entity_key=entity_key,
                metrics=metrics,
                sample_count=sample_count,
                confidence=confidence,
                source_period_start=start,
                source_period_end=end,
                version=1,
                last_event_id=last_event_id,
                last_calculated_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(profile)
        else:
            profile.metrics = metrics
            profile.sample_count = sample_count
            profile.confidence = confidence
            profile.source_period_start = start
            profile.source_period_end = end
            profile.version = int(profile.version or 0) + 1
            profile.last_event_id = last_event_id or profile.last_event_id
            profile.last_calculated_at = now
            profile.updated_at = now
        session.flush()
        return profile

    def list_profiles(
        self,
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        module: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_key: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[RetailLearningProfile]:
        stmt = select(RetailLearningProfile).where(
            RetailLearningProfile.tenant_id == tenant_id,
            RetailLearningProfile.project_id == project_id,
        )
        if module:
            stmt = stmt.where(RetailLearningProfile.module == module)
        if entity_type:
            stmt = stmt.where(RetailLearningProfile.entity_type == entity_type)
        if entity_key:
            stmt = stmt.where(RetailLearningProfile.entity_key == entity_key)
        stmt = stmt.order_by(RetailLearningProfile.module, RetailLearningProfile.entity_key)
        stmt = stmt.offset(max(0, offset)).limit(min(max(limit, 1), 500))
        return list(session.execute(stmt).scalars().all())

    def get_demand_profile(
        self,
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        sku: str,
        store: Optional[str] = None,
        region: Optional[str] = None,
    ) -> Optional[RetailLearningProfile]:
        loc = store or region
        if not loc:
            return None
        key = f"{sku}|{loc}"
        return self._get_profile(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            module=DemandReorderCalibrator.module,
            entity_type=DemandReorderCalibrator.entity_type,
            entity_key=key,
        )

    def _get_profile(
        self,
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        module: str,
        entity_type: str,
        entity_key: str,
    ) -> Optional[RetailLearningProfile]:
        return session.execute(
            select(RetailLearningProfile).where(
                RetailLearningProfile.tenant_id == tenant_id,
                RetailLearningProfile.project_id == project_id,
                RetailLearningProfile.module == module,
                RetailLearningProfile.entity_type == entity_type,
                RetailLearningProfile.entity_key == entity_key,
            )
        ).scalar_one_or_none()

    def _insert_event(
        self,
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        module: str,
        payload: Dict[str, Any],
        verified_by: str,
        deduplication_key: str,
        event_type: Optional[str],
        source_document_id: Optional[str],
        source_action_run_id: Optional[str],
        source_reference: Optional[str],
        verification_status: str,
        skip_if_duplicate: bool,
    ) -> Optional[RetailLearningEvent]:
        if skip_if_duplicate:
            existing = session.execute(
                select(RetailLearningEvent).where(
                    RetailLearningEvent.tenant_id == tenant_id,
                    RetailLearningEvent.project_id == project_id,
                    RetailLearningEvent.deduplication_key == deduplication_key,
                )
            ).scalar_one_or_none()
            if existing:
                return existing

        mod = self.get_module(module)
        entity_type = getattr(mod, "entity_type", "entity") if mod else "entity"
        entity_key = (
            mod.entity_key_from_payload(payload) if mod else str(uuid.uuid4())
        )
        event_time = (
            parse_dt(payload.get("event_time"))
            or parse_dt(payload.get("occurrence_date"))
            or parse_dt(payload.get("period_end"))
            or utcnow()
        )
        now = utcnow()
        event = RetailLearningEvent(
            id=_id(tenant_id, project_id, deduplication_key),
            tenant_id=tenant_id,
            project_id=project_id,
            module=module,
            event_type=event_type or module,
            entity_type=entity_type,
            entity_key=entity_key,
            event_time=event_time,
            period_start=parse_dt(payload.get("period_start")),
            period_end=parse_dt(payload.get("period_end")),
            planned_value=_as_float(payload.get("forecast_quantity") or payload.get("ordered_quantity") or payload.get("baseline_units")),
            actual_value=_as_float(payload.get("actual_sales_quantity") or payload.get("delivered_quantity") or payload.get("promoted_units")),
            unit=payload.get("unit"),
            event_payload=dict(payload),
            source_document_id=source_document_id,
            source_action_run_id=source_action_run_id,
            source_reference=source_reference,
            verification_status=verification_status,
            verified_by=verified_by if verification_status == "verified" else None,
            verified_at=now if verification_status == "verified" else None,
            deduplication_key=deduplication_key,
            created_at=now,
        )
        session.add(event)
        session.flush()
        return event


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def profile_to_dict(profile: RetailLearningProfile) -> Dict[str, Any]:
    return {
        "id": profile.id,
        "tenant_id": profile.tenant_id,
        "project_id": profile.project_id,
        "module": profile.module,
        "entity_type": profile.entity_type,
        "entity_key": profile.entity_key,
        "metrics": profile.metrics or {},
        "sample_count": profile.sample_count,
        "confidence": profile.confidence,
        "source_period_start": profile.source_period_start.isoformat()
        if profile.source_period_start
        else None,
        "source_period_end": profile.source_period_end.isoformat()
        if profile.source_period_end
        else None,
        "version": profile.version,
        "last_event_id": profile.last_event_id,
        "last_calculated_at": profile.last_calculated_at.isoformat()
        if profile.last_calculated_at
        else None,
        "advisory_only": True,
    }
