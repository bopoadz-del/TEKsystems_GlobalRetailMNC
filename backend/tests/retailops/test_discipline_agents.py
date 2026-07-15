"""Discipline-agent manifests (base + hats) — catalog and reasoner wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.retailops.agents import get_agent_catalog, load_manifests_from_dir, reset_agent_catalog
from app.retailops.agents.catalog import AgentCatalogError
from app.retailops.agents.models import AgentManifest
from app.retailops.kit.contract import ActionContext
from app.retailops.reasoning import RetailOperationsReasoner
from app.retailops.service import build_registry

MANIFEST_DIR = Path(__file__).resolve().parents[2] / "app" / "retailops" / "agents" / "manifests"


@pytest.fixture(autouse=True)
def _fresh_catalog():
    reset_agent_catalog()
    yield
    reset_agent_catalog()


def _ctx() -> ActionContext:
    return ActionContext(
        user_id="u_ops_manager",
        tenant_id="northstar",
        organisation_id="northstar",
        project_id="prj_test",
        permissions=["retail:read", "retail:analyse"],
        allowed_domains=["retail"],
    )


def test_catalog_loads_base_and_all_hats():
    catalog = load_manifests_from_dir(MANIFEST_DIR)
    assert len(catalog.bases()) == 1
    assert catalog.bases()[0].agent_id == "retail.base"
    hat_ids = {h.agent_id for h in catalog.hats()}
    expected = {
        "retail.hat.inventory",
        "retail.hat.accounting",
        "retail.hat.marketing",
        "retail.hat.hr",
        "retail.hat.workforce_roster",
        "retail.hat.supplier",
        "retail.hat.compliance",
        "retail.hat.store_operations",
        "retail.hat.customer_experience",
        "retail.hat.reporting",
    }
    assert hat_ids == expected


def test_compose_base_plus_roster_hat():
    catalog = get_agent_catalog()
    composed = catalog.compose("retail.hat.workforce_roster")
    assert composed["agent_id"] == "retail.hat.workforce_roster"
    assert composed["composed_from"] == ["retail.base", "retail.hat.workforce_roster"]
    assert "fixtures/northstar/**" in composed["allowed_paths"]
    assert any(s.get("key") == "confirmed_coverage_rule" for s in composed["memory"]["save"])
    assert composed["activation"]["default_enabled"] is True


def test_compose_unknown_hat_raises():
    catalog = get_agent_catalog()
    with pytest.raises(AgentCatalogError):
        catalog.compose("retail.hat.does_not_exist")


def test_manifest_json_round_trip_validates():
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        data = path.read_text(encoding="utf-8")
        import json

        AgentManifest.model_validate(json.loads(data))


def test_put_off_disables_roster_hat():
    catalog = get_agent_catalog()
    active = catalog.enabled_hats(
        question="Check evening shift roster coverage",
        intent="workforce",
        disabled=["disable:roster"],
    )
    assert all(h.agent_id != "retail.hat.workforce_roster" for h in active)


def test_reasoner_attaches_roster_hat_and_handoffs():
    reasoner = RetailOperationsReasoner()
    plan = reasoner.reason(
        question="What is the staffing gap on tonight's roster?",
        registry=build_registry(),
        context=_ctx(),
    )
    assert plan.route == "rag"
    assert plan.primary_agent_id == "retail.hat.workforce_roster"
    assert "retail.hat.workforce_roster" in plan.active_agent_ids
    targets = {h["to_agent_id"] for h in plan.handoff_tips}
    assert "retail.hat.hr" in targets
    assert "retail.hat.store_operations" in targets or "retail.hat.inventory" in targets


def test_reasoner_accounting_keyword_selects_accounting_hat():
    reasoner = RetailOperationsReasoner()
    plan = reasoner.reason(
        question="Explain the shrink margin impact for chilled dairy",
        registry=build_registry(),
        context=_ctx(),
    )
    assert plan.primary_agent_id == "retail.hat.accounting"
    assert any(n.startswith("discipline_hat:") for n in plan.notes)


def test_reasoner_respects_disabled_agents():
    reasoner = RetailOperationsReasoner()
    plan = reasoner.reason(
        question="What is the staffing gap on tonight's roster?",
        registry=build_registry(),
        context=_ctx(),
        disabled_agents=["disable:roster", "disable:retail.hat.workforce_roster"],
    )
    assert "retail.hat.workforce_roster" not in plan.active_agent_ids
    assert plan.primary_agent_id != "retail.hat.workforce_roster"


def test_memory_save_requires_confirmation_on_teachable_hats():
    catalog = get_agent_catalog()
    for hat_id in (
        "retail.hat.inventory",
        "retail.hat.accounting",
        "retail.hat.workforce_roster",
        "retail.hat.supplier",
    ):
        hat = catalog.get(hat_id)
        assert hat is not None
        assert hat.memory.save
        assert all(rule.requires_confirmation for rule in hat.memory.save)
        assert "unverified_claims" in hat.memory.never_persist or "secrets" in hat.memory.never_persist


def test_every_hat_has_formulas_standards_procedures():
    catalog = get_agent_catalog()
    for hat in catalog.hats():
        pb = hat.playbook
        assert pb.formulas, f"{hat.agent_id} missing formulas"
        assert pb.standards, f"{hat.agent_id} missing standards"
        assert pb.procedures, f"{hat.agent_id} missing procedures"
        for proc in pb.procedures:
            assert proc.steps, f"{hat.agent_id}.{proc.id} has empty steps"
            assert [s.step for s in proc.steps] == list(range(1, len(proc.steps) + 1))


def test_compose_inherits_base_playbook_formulas():
    catalog = get_agent_catalog()
    composed = catalog.compose("retail.hat.inventory")
    ids = {f["id"] for f in composed["playbook"]["formulas"]}
    assert "base.grounding_gate" in ids
    assert "inventory.recommended_reorder_point" in ids


def test_reasoner_emits_playbook_refs_for_roster():
    reasoner = RetailOperationsReasoner()
    plan = reasoner.reason(
        question="What is the staffing gap on tonight's roster?",
        registry=build_registry(),
        context=_ctx(),
    )
    assert plan.playbook_refs.get("agent_id") == "retail.hat.workforce_roster"
    assert "roster.coverage_ratio" in plan.playbook_refs.get("formula_ids", [])
    assert plan.playbook_refs.get("procedure_count", 0) >= 1


def test_playbook_formula_ids_unique_within_hat():
    catalog = get_agent_catalog()
    for agent in catalog.all():
        ids = [f.id for f in agent.playbook.formulas]
        assert len(ids) == len(set(ids)), f"duplicate formula ids in {agent.agent_id}"
