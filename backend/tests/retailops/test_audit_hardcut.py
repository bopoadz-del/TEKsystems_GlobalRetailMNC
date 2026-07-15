"""Hard-cut wiring: memory API, allowed_actions enforcement, formula metadata."""

from __future__ import annotations

import pytest

from app.retailops.agents.formulas import (
    allowed_actions_for_hat,
    formulas_applied_by_action,
)
from app.retailops.agents.memory import AgentMemoryError, list_memory, save_memory
from app.retailops.kit.contract import ActionContext, ActionStatus, execute_action
from app.retailops.kit.domains.retail.fixtures import EVALUATION_FIXTURES, get_evaluation_fixture
from app.retailops.reasoning import RetailOperationsReasoner
from app.retailops.service import build_registry


def _ctx(project_id: str = "prj_wire") -> ActionContext:
    return ActionContext(
        user_id="u_ops_manager",
        tenant_id="northstar",
        organisation_id="northstar",
        project_id=project_id,
        permissions=["retail:read", "retail:analyse"],
        allowed_domains=["retail"],
    )


def test_evaluation_fixtures_cover_all_action_spec_names():
    registry = build_registry()
    missing = []
    for spec in registry.all():
        for name in spec.evaluation_fixtures or []:
            if name not in EVALUATION_FIXTURES:
                missing.append(name)
    assert missing == []
    assert get_evaluation_fixture("export_document_custom_pdf")["format"] == "pdf"


def test_allowed_actions_composed_for_inventory_includes_risk():
    allowed = allowed_actions_for_hat("retail.hat.inventory")
    assert "retail.analyse_inventory_risk" in allowed
    assert "retail.export_document" in allowed


def test_reasoner_blocks_action_outside_hat_allowlist():
    """Putting off the inventory hat blocks inventory risk commands."""
    reasoner = RetailOperationsReasoner()
    plan = reasoner.reason(
        question="Analyse inventory risk for chilled SKUs",
        registry=build_registry(),
        context=_ctx(),
        disabled_agents=["disable:inventory", "disable:retail.hat.inventory"],
    )
    assert plan.route == "unsupported"
    assert "retail.analyse_inventory_risk" not in plan.recommended_action_ids
    assert any("hat_put_off" in n or "unsupported_preferred_hat_put_off" in n for n in plan.notes)


def test_playbook_refs_include_executable_and_memory_keys():
    reasoner = RetailOperationsReasoner()
    plan = reasoner.reason(
        question="What is the staffing gap on tonight's roster?",
        registry=build_registry(),
        context=_ctx(),
    )
    assert plan.primary_agent_id == "retail.hat.workforce_roster"
    refs = plan.playbook_refs
    assert "confirmed_coverage_rule" in (refs.get("memory_save_keys") or [])
    assert "allowed_actions" in refs
    assert isinstance(refs.get("executable_formula_ids"), list)


def test_applied_formulas_on_inventory_action():
    rows = formulas_applied_by_action("retail.analyse_inventory_risk")
    ids = {r["id"] for r in rows}
    assert "inventory.days_of_cover" in ids


@pytest.mark.asyncio
async def test_inventory_action_emits_applied_formulas():
    registry = build_registry()
    spec = registry.resolve("retail.analyse_inventory_risk")
    result = await execute_action(
        spec,
        _ctx(),
        get_evaluation_fixture("inventory_risk_happy"),
    )
    assert result.status == ActionStatus.SUCCESS
    assert result.output.get("applied_formulas")


def test_memory_save_requires_confirmation(db):
    with pytest.raises(AgentMemoryError, match="confirmation"):
        save_memory(
            db,
            tenant_id="northstar",
            project_id="prj_wire",
            user_id="u_ops_manager",
            agent_id="retail.hat.workforce_roster",
            key="confirmed_coverage_rule",
            value={"store": "Riyadh Olaya", "min_heads": 3},
            confirmed=False,
        )


def test_memory_save_and_list(db):
    row = save_memory(
        db,
        tenant_id="northstar",
        project_id="prj_wire",
        user_id="u_ops_manager",
        agent_id="retail.hat.workforce_roster",
        key="confirmed_coverage_rule",
        value={"store": "Riyadh Olaya", "role": "cashier", "min_heads": 3},
        confirmed=True,
    )
    db.commit()
    assert row.version == 1
    listed = list_memory(
        db, tenant_id="northstar", project_id="prj_wire", agent_id="retail.hat.workforce_roster"
    )
    assert any(r.key == "confirmed_coverage_rule" for r in listed)


def test_memory_rejects_undeclared_key(db):
    with pytest.raises(AgentMemoryError, match="not a declared"):
        save_memory(
            db,
            tenant_id="northstar",
            project_id="prj_wire",
            user_id="u_ops_manager",
            agent_id="retail.hat.workforce_roster",
            key="random_secret_key",
            value={"x": 1},
            confirmed=True,
        )


def test_memory_api(client, db, loaded_projects):
    pid = loaded_projects["Global Region"]
    headers = {
        "X-User-Id": "u_ops_manager",
        "X-Tenant-Id": "retail",
        "X-Project-Id": pid,
    }
    denied = client.post(
        "/v1/agents/memory",
        headers=headers,
        json={
            "agent_id": "retail.hat.inventory",
            "key": "confirmed_reorder_override",
            "value": {"sku": "BEV-2201", "reorder_point": 55},
            "confirm": False,
        },
    )
    assert denied.status_code == 400

    ok = client.post(
        "/v1/agents/memory",
        headers=headers,
        json={
            "agent_id": "retail.hat.inventory",
            "key": "confirmed_reorder_override",
            "value": {"sku": "BEV-2201", "reorder_point": 55},
            "confirm": True,
        },
    )
    assert ok.status_code == 200, ok.text
    listed = client.get(
        "/v1/agents/memory?agent_id=retail.hat.inventory", headers=headers
    )
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1


def test_no_dangling_packs_paths():
    from pathlib import Path
    import json

    root = Path(__file__).resolve().parents[2] / "app" / "retailops" / "agents" / "manifests"
    for path in root.glob("*.json"):
        raw = path.read_text()
        assert "packs/retail_core_open_v1" not in raw, path.name
