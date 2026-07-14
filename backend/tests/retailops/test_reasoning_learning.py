"""Reasoning layer + outcome learning proofs for the RetailOps pilot."""

from __future__ import annotations

import pytest

from app.retailops import bootstrap
from app.retailops.db import session_scope
from app.retailops.kit.contract import ActionContext, ActionRegistry, ActionStatus, execute_action
from app.retailops.kit.contract.models import ActionSpec
from app.retailops.kit.domains.retail.actions import ACTION_SPECS
from app.retailops.learning import (
    DemandReorderCalibrator,
    PromotionEffectivenessLearner,
    RetailOutcomeLearningEngine,
    StoreExceptionPatternDetector,
    SupplierFulfilmentLearner,
)
from app.retailops.learning.common import confidence_label
from app.retailops.models import RetailLearningEvent, RetailLearningProfile
from app.retailops.orchestrator import reset_graph, run_orchestrator
from app.retailops.reasoning import RetailOperationsReasoner
from app.retailops.service import build_registry
from sqlalchemy import select

MANAGER = "u_ops_manager"
VIEWER = "u_viewer"
TENANT = "northstar"


def _headers(user, project_id):
    return {"X-User-Id": user, "X-Tenant-Id": TENANT, "X-Project-Id": project_id}


def _ctx(project_id: str, *, perms=None) -> ActionContext:
    return ActionContext(
        user_id=MANAGER,
        tenant_id=TENANT,
        organisation_id=TENANT,
        project_id=project_id,
        permissions=perms
        or ["retail:read", "retail:analyse", "retail:learning_write"],
        allowed_domains=["retail"],
    )


@pytest.fixture()
def registry():
    reset_graph()
    return build_registry()


# ---------------------------------------------------------------------------
# Reasoner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoner_factual_question_routes_rag(db, loaded_projects, registry):
    pid = loaded_projects["Northstar Riyadh Region"]
    out = await run_orchestrator(
        session=db,
        context=_ctx(pid),
        question="What is the stock discrepancy escalation process?",
        registry=registry,
    )
    assert out["route"] == "rag"
    assert out["execution_plan"]["primary_intent"] in {"inventory", "store_operations", "unknown", "compliance"}


@pytest.mark.asyncio
async def test_reasoner_explicit_action_routes_action(db, loaded_projects, registry):
    pid = loaded_projects["Northstar Riyadh Region"]
    out = await run_orchestrator(
        session=db,
        context=_ctx(pid),
        question="Please run action:retail.analyse_inventory_risk now",
        registry=registry,
    )
    assert out["route"] == "action"
    assert out["action_id"] == "retail.analyse_inventory_risk"


@pytest.mark.asyncio
async def test_reasoner_action_topic_question_stays_rag(db, loaded_projects, registry):
    pid = loaded_projects["Northstar Riyadh Region"]
    out = await run_orchestrator(
        session=db,
        context=_ctx(pid),
        question="What inputs are needed to analyse inventory risk?",
        registry=registry,
    )
    assert out["route"] == "rag"


def test_reasoner_inventory_command_recommends_registered_only(registry):
    reasoner = RetailOperationsReasoner()
    plan = reasoner.reason(
        question="Analyse inventory risk for chilled SKUs",
        registry=registry,
        context=_ctx("prj_test"),
    )
    assert plan.route == "action"
    assert plan.recommended_action_ids
    assert all(registry.resolve(a) for a in plan.recommended_action_ids)
    assert "supplier" in plan.related_domains or "store_operations" in plan.related_domains


def test_reasoner_unknown_does_not_fabricate_action(registry):
    reasoner = RetailOperationsReasoner()
    plan = reasoner.reason(
        question="Teleport all forklifts to mars immediately",
        registry=registry,
        context=_ctx("prj_test"),
    )
    # Imperative with no registered action → unsupported (not RAG).
    assert plan.route == "unsupported"
    assert plan.recommended_action_ids == []


def test_reasoner_unsupported_imperative_book_flight(registry):
    reasoner = RetailOperationsReasoner()
    plan = reasoner.reason(
        question="Please book me a flight to the moon.",
        registry=registry,
        context=_ctx("prj_test"),
    )
    assert plan.route == "unsupported"
    assert plan.recommended_action_ids == []


def test_reasoner_unregistered_action_unsupported(registry):
    reasoner = RetailOperationsReasoner()
    plan = reasoner.reason(
        question="action:retail.no_such_action",
        registry=registry,
        context=_ctx("prj_test"),
    )
    assert plan.route == "unsupported"


def test_reasoner_new_action_available_without_router_edits():
    async def _handler(context, arguments):
        from app.retailops.kit.contract.models import ActionOutcome

        return ActionOutcome.success({"ok": True})

    reg = ActionRegistry()
    reg.register_all(ACTION_SPECS)
    extra = ActionSpec(
        action_id="retail.pilot_probe",
        domain="retail",
        name="Pilot Probe",
        description="Probe action for registry extensibility",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        permissions=["retail:read"],
        handler=_handler,
    )
    reg.register(extra)
    reasoner = RetailOperationsReasoner()
    plan = reasoner.reason(
        question="action:retail.pilot_probe",
        registry=reg,
        context=_ctx("prj_test", perms=["retail:read"]),
    )
    assert plan.route == "action"
    assert plan.recommended_action_ids == ["retail.pilot_probe"]


# ---------------------------------------------------------------------------
# Learning events / isolation
# ---------------------------------------------------------------------------

def test_verified_event_persisted_and_idempotent(db, loaded_projects):
    pid = loaded_projects["Northstar Riyadh Region"]
    engine = RetailOutcomeLearningEngine()
    payload = {
        "sku": "TEST-1",
        "store": "Riyadh Olaya",
        "forecast_quantity": 10,
        "actual_sales_quantity": 12,
        "current_reorder_point": 5,
        "safety_stock": 2,
        "stockout_occurrence": False,
        "period_start": "2024-01-01",
        "period_end": "2024-01-07",
    }
    r1 = engine.record_verified_outcome(
        db,
        tenant_id=TENANT,
        project_id=pid,
        module="demand_reorder",
        payload=payload,
        verified_by=MANAGER,
        deduplication_key="unit-test-demand-1",
    )
    assert r1["profile_updated"] is True
    r2 = engine.record_verified_outcome(
        db,
        tenant_id=TENANT,
        project_id=pid,
        module="demand_reorder",
        payload=payload,
        verified_by=MANAGER,
        deduplication_key="unit-test-demand-1",
    )
    assert r2["idempotent"] is True
    events = db.execute(
        select(RetailLearningEvent).where(
            RetailLearningEvent.deduplication_key == "unit-test-demand-1"
        )
    ).scalars().all()
    assert len(events) == 1


def test_unverified_event_does_not_update_profile(db, loaded_projects):
    pid = loaded_projects["Northstar Riyadh Region"]
    engine = RetailOutcomeLearningEngine()
    before = engine.list_profiles(db, tenant_id=TENANT, project_id=pid, module="demand_reorder")
    before_n = len(before)
    result = engine.record_verified_outcome(
        db,
        tenant_id=TENANT,
        project_id=pid,
        module="demand_reorder",
        payload={
            "sku": "UNVER-1",
            "store": "Riyadh Olaya",
            "forecast_quantity": 1,
            "actual_sales_quantity": 1,
            "period_start": "2024-02-01",
            "period_end": "2024-02-07",
        },
        verified_by=MANAGER,
        deduplication_key="unit-test-unverified",
        verification_status="unverified",
    )
    assert result["profile_updated"] is False
    after = engine.list_profiles(db, tenant_id=TENANT, project_id=pid, module="demand_reorder")
    assert len(after) == before_n
    keys = {p.entity_key for p in after}
    assert "UNVER-1|Riyadh Olaya" not in keys


@pytest.mark.asyncio
async def test_record_outcome_requires_confirmation_and_permission(db, loaded_projects, registry):
    pid = loaded_projects["Northstar Riyadh Region"]
    spec = registry.resolve("retail.record_verified_outcome")
    args = {
        "module": "demand_reorder",
        "deduplication_key": "perm-check-1",
        "payload": {
            "sku": "X",
            "store": "Riyadh Olaya",
            "forecast_quantity": 1,
            "actual_sales_quantity": 1,
            "period_start": "2024-01-01",
            "period_end": "2024-01-07",
        },
        "tenant_id": "evil",
        "project_id": "hijack",
    }
    denied = await execute_action(
        spec,
        _ctx(pid, perms=["retail:read"]),
        args,
        confirmed=True,
    )
    assert denied.status == ActionStatus.PERMISSION_DENIED

    unconfirmed = await execute_action(spec, _ctx(pid), args, confirmed=False)
    assert unconfirmed.status == ActionStatus.VALIDATION_ERROR
    assert unconfirmed.error_code == "confirmation_required"

    ok = await execute_action(spec, _ctx(pid), args, confirmed=True)
    assert ok.status == ActionStatus.SUCCESS
    assert "evil" not in str(ok.output)


def test_tenant_isolation_profiles(db, loaded_projects):
    pid = loaded_projects["Northstar Riyadh Region"]
    bootstrap.ensure_tenant(db, "otherco", "Other Co")
    other = bootstrap.ensure_project(
        db, tenant_id="otherco", canonical_name="Other Region"
    )
    engine = RetailOutcomeLearningEngine()
    foreign = engine.list_profiles(db, tenant_id="otherco", project_id=other.id)
    assert foreign == []
    own = engine.list_profiles(db, tenant_id=TENANT, project_id=pid)
    assert own  # fixtures populated profiles


# ---------------------------------------------------------------------------
# Calibrator math
# ---------------------------------------------------------------------------

def test_demand_calibration_math_and_confidence():
    cal = DemandReorderCalibrator()
    events = []
    for i in range(8):
        events.append(
            {
                "event_payload": {
                    "forecast_quantity": 100,
                    "actual_sales_quantity": 120,
                    "current_reorder_point": 20,
                    "safety_stock": 10,
                    "stockout_occurrence": False,
                    "period_start": f"2024-01-{i+1:02d}",
                    "period_end": f"2024-01-{i+1:02d}",
                }
            }
        )
    metrics = cal.calculate(events)
    assert metrics["actual_to_forecast_ratio"] == 1.2
    assert metrics["forecast_bias"] == 20.0
    assert metrics["forecast_absolute_error"] == 20.0
    assert metrics["confidence"] == "high"
    assert metrics["recommended_reorder_point"] == 24.0
    assert confidence_label(2) == "low"
    assert confidence_label(3) == "medium"
    assert confidence_label(8) == "high"
    rec = cal.recommend(profile_metrics=None)
    assert rec["status"] == "dependency_required"
    rec2 = cal.recommend(profile_metrics=metrics, current_reorder_point=20)
    assert rec2["current_reorder_point"] == 20
    assert rec2["recommended_reorder_point"] == 24.0


def test_supplier_learning_math():
    learner = SupplierFulfilmentLearner()
    events = [
        {
            "event_payload": {
                "promised_date": "2024-01-10",
                "actual_delivery_date": "2024-01-10",
                "ordered_quantity": 100,
                "delivered_quantity": 100,
                "rejected_quantity": 0,
                "damaged_quantity": 0,
            }
        },
        {
            "event_payload": {
                "promised_date": "2024-01-10",
                "actual_delivery_date": "2024-01-13",
                "ordered_quantity": 100,
                "delivered_quantity": 50,
                "rejected_quantity": 10,
                "damaged_quantity": 5,
            }
        },
    ]
    metrics = learner.calculate(events)
    assert metrics["average_delay_days"] == 1.5
    assert metrics["fill_rate"] == 0.75
    assert metrics["on_time_percentage"] == 0.5
    assert metrics["otif_percentage"] == 0.5
    assert metrics["reliability_classification"] in {"watch", "at_risk", "reliable"}
    assert metrics["sample_count"] == 2


def test_promotion_learning_zero_baseline_safe():
    learner = PromotionEffectivenessLearner()
    metrics = learner.calculate(
        [
            {
                "event_payload": {
                    "baseline_units": 0,
                    "promoted_units": 10,
                    "baseline_revenue": 0,
                    "promoted_revenue": 50,
                    "baseline_margin": 0,
                    "promoted_margin": 5,
                    "compliance_percentage": 80,
                    "promotion_related_stockout": False,
                    "period_start": "2024-01-01",
                    "period_end": "2024-01-31",
                }
            },
            {
                "event_payload": {
                    "baseline_units": 100,
                    "promoted_units": 150,
                    "baseline_revenue": 1000,
                    "promoted_revenue": 1400,
                    "baseline_margin": 100,
                    "promoted_margin": 150,
                    "compliance_percentage": 90,
                    "promotion_related_stockout": True,
                    "period_start": "2024-02-01",
                    "period_end": "2024-02-28",
                }
            },
        ]
    )
    assert metrics["fabricated_uplift"] is False
    assert metrics["invalid_baseline_count"] >= 1
    assert metrics["unit_uplift_percentage"] == 50.0
    assert metrics["stockout_frequency"] == 0.5
    assert metrics["sample_count"] == 2


def test_exception_detection_severity_and_ranking():
    det = StoreExceptionPatternDetector()
    metrics = det.calculate(
        [
            {
                "event_payload": {
                    "store": "Riyadh Olaya",
                    "region": "Riyadh",
                    "exception_type": "inventory_discrepancy",
                    "severity": "high",
                    "root_cause": "count miss",
                    "category": "chilled",
                    "occurrence_date": "2024-03-01",
                }
            },
            {
                "event_payload": {
                    "store": "Riyadh Olaya",
                    "region": "Riyadh",
                    "exception_type": "inventory_discrepancy",
                    "severity": "high",
                    "root_cause": "count miss",
                    "category": "chilled",
                    "occurrence_date": "2024-03-08",
                }
            },
            {
                "event_payload": {
                    "store": "Riyadh Olaya",
                    "region": "Riyadh",
                    "exception_type": "safety_incident",
                    "severity": "critical",
                    "root_cause": "wet floor",
                    "category": "ops",
                    "occurrence_date": "2024-03-02",
                }
            },
        ]
    )
    assert metrics["top_exception_patterns"][0]["exception_type"] == "inventory_discrepancy"
    assert metrics["recurring_root_causes"][0]["root_cause"] == "count miss"
    assert metrics["highest_risk_category"] == "chilled"
    assert metrics["severity_weighted_risk_score"] == pytest.approx((3 + 3 + 5) / 3, abs=1e-3)
    assert "2024-03" in metrics["trend_by_period"]


# ---------------------------------------------------------------------------
# API / actions
# ---------------------------------------------------------------------------

def test_learning_summary_api(client, loaded_projects):
    pid = loaded_projects["Northstar Riyadh Region"]
    r = client.get("/v1/learning/summary", headers=_headers(MANAGER, pid))
    assert r.status_code == 200
    body = r.json()
    assert body["advisory_only"] is True
    assert body["count"] >= 1
    modules = {p["module"] for p in body["profiles"]}
    assert "demand_reorder" in modules


def test_recommend_reorder_api(client, loaded_projects):
    pid = loaded_projects["Northstar Riyadh Region"]
    r = client.post(
        "/v1/actions/retail.recommend_reorder_parameters/execute",
        headers=_headers(MANAGER, pid),
        json={
            "arguments": {
                "sku": "BEV-2201",
                "store": "Riyadh Olaya",
                "current_reorder_point": 20,
            },
            "confirm": False,
        },
    )
    body = r.json()
    assert body["status"] == "success"
    assert body["output"]["advisory_only"] is True
    assert body["output"]["confidence"] == "high"
    assert body["output"]["recommended_reorder_point"] is not None


def test_recommend_reorder_missing_profile_dependency(client, loaded_projects):
    pid = loaded_projects["Northstar Riyadh Region"]
    r = client.post(
        "/v1/actions/retail.recommend_reorder_parameters/execute",
        headers=_headers(MANAGER, pid),
        json={"arguments": {"sku": "NO-PROFILE", "store": "Nowhere"}, "confirm": False},
    )
    assert r.json()["status"] == "dependency_required"


def test_fixture_confidence_bands(db, loaded_projects):
    pid = loaded_projects["Northstar Riyadh Region"]
    engine = RetailOutcomeLearningEngine()
    profiles = {
        p.entity_key: p
        for p in engine.list_profiles(db, tenant_id=TENANT, project_id=pid, module="demand_reorder")
    }
    assert profiles["BEV-2201|Riyadh Olaya"].confidence == "high"
    assert profiles["FOOD-1001|Riyadh Olaya"].confidence == "medium"
    assert profiles["HOME-55|Riyadh Olaya"].confidence == "low"
