"""Cross-tenant / cross-project isolation certification.

Retrieval isolation (docs/citations) is already covered by
``test_db_retrieval.py`` (``test_project_isolation`` / ``test_tenant_isolation``)
and ``test_api_orchestrator.py`` (``test_cross_project_cannot_retrieve_other_evidence``).
Learning-profile isolation is covered by
``test_reasoning_learning.py::test_tenant_isolation_profiles``.

This module closes the remaining release-gate categories: **actions/audit**,
**discipline-hat memory**, and **integration run history** never leak across
tenant or project boundaries.
"""

from __future__ import annotations

import pytest

from app.retailops import bootstrap
from app.retailops.agents.memory import list_memory, save_memory
from app.retailops.audit import list_action_runs, persist_action_run
from app.retailops.integrations.runs import list_runs, reset_runs

TENANT_A = "retail"
TENANT_B = "isotest_otherco"


def _other_tenant_project(session, *, project_name="Isolation Other Co"):
    bootstrap.ensure_tenant(session, TENANT_B, "Isolation Other Co")
    bootstrap.ensure_user(
        session, "u_isotest", TENANT_B, name="Iso Tester",
        permissions=["retail:read", "retail:analyse"],
    )
    project = bootstrap.ensure_project(session, tenant_id=TENANT_B, canonical_name=project_name)
    return project.id


def _headers(user, tenant, project_id):
    return {"X-User-Id": user, "X-Tenant-Id": tenant, "X-Project-Id": project_id}


# ---------------------------------------------------------------------------
# Project must exist under the caller's tenant
# ---------------------------------------------------------------------------

def test_invented_project_id_rejected(client, db, loaded_projects):
    """Same tenant + known user, but a project id that does not exist → 403."""
    resp = client.get(
        "/v1/overview",
        headers=_headers("u_ops_manager", TENANT_A, "prj_does_not_exist_zzzz"),
    )
    assert resp.status_code == 403
    assert "unknown project" in resp.json()["detail"].lower()


def test_cross_tenant_project_id_rejected(client, db, loaded_projects):
    """User in tenant A cannot use a real project id that belongs to tenant B."""
    pid_b = _other_tenant_project(db)
    db.commit()

    resp = client.get(
        "/v1/overview",
        headers=_headers("u_ops_manager", TENANT_A, pid_b),
    )
    assert resp.status_code == 403
    assert "unknown project" in resp.json()["detail"].lower()


def test_valid_project_under_tenant_accepted(client, db, loaded_projects):
    pid_a = loaded_projects["Global Region"]
    resp = client.get(
        "/v1/overview",
        headers=_headers("u_ops_manager", TENANT_A, pid_a),
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Actions / audit isolation
# ---------------------------------------------------------------------------

def test_audit_runs_isolated_across_tenants(db, loaded_projects):
    pid_a = loaded_projects["Global Region"]
    pid_b = _other_tenant_project(db)
    db.commit()

    from app.retailops.kit.contract import ActionContext, ActionResult, ActionStatus
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    ctx = ActionContext(
        user_id="u_ops_manager",
        tenant_id=TENANT_A,
        organisation_id=TENANT_A,
        project_id=pid_a,
        permissions=["retail:read", "retail:analyse"],
        allowed_domains=["retail"],
    )
    persist_action_run(
        db,
        result=ActionResult(
            request_id=f"act_{uuid.uuid4().hex}",
            action_id="retail.generate_operations_brief",
            status=ActionStatus.SUCCESS,
            started_at=now,
            completed_at=now,
            duration_ms=1,
        ),
        context=ctx,
        arguments={},
    )
    db.commit()

    runs_a = list_action_runs(db, tenant_id=TENANT_A, project_id=pid_a)
    runs_b = list_action_runs(db, tenant_id=TENANT_B, project_id=pid_b)
    assert len(runs_a) >= 1
    assert runs_b == []


def test_audit_route_isolated_across_tenants(client, db, loaded_projects):
    pid_a = loaded_projects["Global Region"]
    pid_b = _other_tenant_project(db)
    db.commit()

    exec_resp = client.post(
        "/v1/actions/retail.analyse_inventory_risk/execute",
        headers=_headers("u_ops_manager", TENANT_A, pid_a),
        json={
            "arguments": {
                "rows": [
                    {"SKU": "ISO-1", "Product": "Iso widget", "On Hand": 1,
                     "Reorder Point": 10, "Avg Daily Sales": 5, "Store": "Iso Store"}
                ]
            },
            "auto_context": False,
        },
    )
    assert exec_resp.status_code == 200

    audit_a = client.get("/v1/audit", headers=_headers("u_ops_manager", TENANT_A, pid_a))
    audit_b = client.get("/v1/audit", headers=_headers("u_isotest", TENANT_B, pid_b))
    assert audit_a.status_code == 200 and audit_b.status_code == 200
    assert len(audit_a.json()["runs"]) >= 1
    assert audit_b.json()["runs"] == []


# ---------------------------------------------------------------------------
# Discipline-hat memory isolation
# ---------------------------------------------------------------------------

def test_agent_memory_isolated_across_tenants(db, loaded_projects):
    pid_a = loaded_projects["Global Region"]
    pid_b = _other_tenant_project(db)
    db.commit()

    save_memory(
        db,
        tenant_id=TENANT_A,
        project_id=pid_a,
        user_id="u_ops_manager",
        agent_id="retail.hat.workforce_roster",
        key="confirmed_coverage_rule",
        value={"store": "Global HQ", "min_heads": 2},
        confirmed=True,
    )
    db.commit()

    own = list_memory(db, tenant_id=TENANT_A, project_id=pid_a, agent_id="retail.hat.workforce_roster")
    foreign = list_memory(db, tenant_id=TENANT_B, project_id=pid_b, agent_id="retail.hat.workforce_roster")
    assert any(r.key == "confirmed_coverage_rule" for r in own)
    assert foreign == []


def test_agent_memory_route_isolated_across_projects(client, db, loaded_projects):
    pid_a = loaded_projects["Global Region"]
    pid_c = loaded_projects["Australia Region"]

    headers_a = _headers("u_ops_manager", TENANT_A, pid_a)
    headers_c = _headers("u_ops_manager", TENANT_A, pid_c)

    saved = client.post(
        "/v1/agents/memory",
        headers=headers_a,
        json={
            "agent_id": "retail.hat.inventory",
            "key": "confirmed_reorder_override",
            "value": {"sku": "ISO-42", "reorder_point": 12},
            "confirm": True,
        },
    )
    assert saved.status_code == 200, saved.text

    listed_same_project = client.get(
        "/v1/agents/memory?agent_id=retail.hat.inventory", headers=headers_a
    )
    listed_other_project = client.get(
        "/v1/agents/memory?agent_id=retail.hat.inventory", headers=headers_c
    )
    assert listed_same_project.json()["count"] >= 1
    assert listed_other_project.json()["count"] == 0


# ---------------------------------------------------------------------------
# Integration run-history isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_runs():
    reset_runs()
    yield
    reset_runs()


def test_integration_runs_isolated_across_tenants(client, db, loaded_projects):
    pid_a = loaded_projects["Global Region"]
    pid_b = _other_tenant_project(db)
    db.commit()

    synced = client.post(
        "/v1/integrations/pos/sync",
        headers=_headers("u_ops_manager", TENANT_A, pid_a),
        json={"cursor": "iso-cursor"},
    )
    assert synced.status_code == 200

    runs_a = list_runs(tenant_id=TENANT_A, project_id=pid_a, connector_id="pos")
    runs_b = list_runs(tenant_id=TENANT_B, project_id=pid_b, connector_id="pos")
    assert len(runs_a) >= 1
    assert runs_b == []

    route_b = client.get(
        "/v1/integrations/pos/runs", headers=_headers("u_isotest", TENANT_B, pid_b)
    )
    assert route_b.status_code == 200
    assert route_b.json()["runs"] == []
