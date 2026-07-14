"""Integration connector registry, mock pull/normalize, status machine, routes.

Unit-level tests (registry, status machine, mock generators) run without a
database. The HTTP route tests reuse the ``client`` / ``loaded_projects``
fixtures from ``conftest.py`` and are skipped (not failed) when the RetailOps
test Postgres database is unreachable, matching the rest of this suite.
"""

from __future__ import annotations

import base64

import pytest

from app.retailops.integrations import ConnectorError, ConnectorStatus, get_connector, list_connectors
from app.retailops.integrations.connectors.inventory_wms import to_inventory_risk_rows
from app.retailops.integrations.runs import list_runs, reset_runs

MOCK_FUNCTIONAL_IDS = {"pos", "inventory_wms", "supplier_edi", "power_bi"}
STUB_IDS = {"sap_erp", "crm_loyalty", "store_digital_twin", "entra_id"}
ALL_IDS = MOCK_FUNCTIONAL_IDS | STUB_IDS

TENANT = "retail"


def _headers(user, project_id):
    return {"X-User-Id": user, "X-Tenant-Id": TENANT, "X-Project-Id": project_id}


@pytest.fixture(autouse=True)
def _clear_runs():
    reset_runs()
    yield
    reset_runs()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_registry_exposes_exactly_eight_pilot_connectors():
    connectors = list_connectors()
    ids = {c.connector_id for c in connectors}
    assert ids == ALL_IDS
    assert len(connectors) == 8


def test_registry_resolves_by_id_and_unknown_is_none():
    assert get_connector("pos") is not None
    assert get_connector("does_not_exist") is None


def test_four_mock_functional_and_four_stub_connectors():
    for connector in list_connectors():
        if connector.connector_id in MOCK_FUNCTIONAL_IDS:
            assert connector.mock_functional is True
        else:
            assert connector.mock_functional is False
    assert {c.connector_id for c in list_connectors() if c.mock_functional} == MOCK_FUNCTIONAL_IDS


def test_public_dict_never_leaks_credentials(monkeypatch):
    monkeypatch.setenv("RETAILOPS_SAP_BASE_URL", "https://sap.example.internal")
    monkeypatch.setenv("RETAILOPS_SAP_CLIENT_ID", "client-123")
    monkeypatch.setenv("RETAILOPS_SAP_API_KEY", "super-secret-key")
    connector = get_connector("sap_erp")
    dumped = str(connector.public_dict())
    assert "super-secret-key" not in dumped


# ---------------------------------------------------------------------------
# Status machine — closed vocabulary, honest without credentials
# ---------------------------------------------------------------------------

def test_status_values_are_in_closed_vocabulary():
    allowed = {
        ConnectorStatus.DISABLED, ConnectorStatus.MOCK, ConnectorStatus.CONFIGURED,
        ConnectorStatus.CONNECTED, ConnectorStatus.DEGRADED, ConnectorStatus.ERROR,
    }
    for connector in list_connectors():
        assert connector.status() in allowed


def test_mock_functional_connectors_default_to_mock_without_credentials(monkeypatch):
    for var in [
        "RETAILOPS_POS_BASE_URL", "RETAILOPS_POS_API_KEY",
        "RETAILOPS_WMS_BASE_URL", "RETAILOPS_WMS_API_KEY",
        "RETAILOPS_EDI_BASE_URL", "RETAILOPS_EDI_API_KEY",
        "RETAILOPS_POWERBI_TENANT_ID", "RETAILOPS_POWERBI_CLIENT_ID",
        "RETAILOPS_POWERBI_CLIENT_SECRET", "RETAILOPS_POWERBI_WORKSPACE_ID",
    ]:
        monkeypatch.delenv(var, raising=False)
    for cid in MOCK_FUNCTIONAL_IDS:
        assert get_connector(cid).status() == ConnectorStatus.MOCK


def test_stub_connectors_default_to_disabled_without_credentials(monkeypatch):
    for var in [
        "RETAILOPS_SAP_BASE_URL", "RETAILOPS_SAP_CLIENT_ID", "RETAILOPS_SAP_API_KEY",
        "RETAILOPS_CRM_BASE_URL", "RETAILOPS_CRM_API_KEY",
        "RETAILOPS_DIGITAL_TWIN_BASE_URL", "RETAILOPS_DIGITAL_TWIN_API_KEY",
        "RETAILOPS_ENTRA_TENANT_ID", "RETAILOPS_ENTRA_CLIENT_ID", "RETAILOPS_ENTRA_CLIENT_SECRET",
    ]:
        monkeypatch.delenv(var, raising=False)
    for cid in STUB_IDS:
        assert get_connector(cid).status() == ConnectorStatus.DISABLED


def test_stub_connector_reports_configured_when_credentials_present_but_never_calls_out(monkeypatch):
    monkeypatch.setenv("RETAILOPS_SAP_BASE_URL", "https://sap.example.internal")
    monkeypatch.setenv("RETAILOPS_SAP_CLIENT_ID", "client-123")
    monkeypatch.setenv("RETAILOPS_SAP_API_KEY", "k")
    assert get_connector("sap_erp").status() == ConnectorStatus.CONFIGURED


@pytest.mark.asyncio
async def test_sap_erp_stub_never_fabricates_pull_data():
    connector = get_connector("sap_erp")
    with pytest.raises(ConnectorError):
        await connector.pull()


@pytest.mark.asyncio
async def test_store_digital_twin_stub_never_fabricates_pull_data():
    connector = get_connector("store_digital_twin")
    with pytest.raises(ConnectorError):
        await connector.pull()


@pytest.mark.asyncio
async def test_entra_id_stub_never_fabricates_pull_data():
    connector = get_connector("entra_id")
    with pytest.raises(ConnectorError):
        await connector.pull()


@pytest.mark.asyncio
async def test_crm_loyalty_stub_returns_small_illustrative_sample_not_error():
    connector = get_connector("crm_loyalty")
    result = await connector.pull()
    assert result["source"] == "illustrative_sample"
    assert 1 <= len(result["records"]) <= 10


@pytest.mark.asyncio
async def test_all_read_only_connectors_reject_push():
    for cid in ["pos", "inventory_wms", "supplier_edi", "crm_loyalty"]:
        connector = get_connector(cid)
        assert connector.read_only is True
        with pytest.raises(ConnectorError):
            await connector.push("anything", {})


# ---------------------------------------------------------------------------
# Mock pull/normalize — deterministic fictional data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pos_mock_pull_is_deterministic_and_normalizes():
    connector = get_connector("pos")
    a = await connector.pull(cursor="c1")
    b = await connector.pull(cursor="c1")
    assert a["records"] == b["records"]
    assert a["source"] == "mock"
    normalized = await connector.normalize(a["records"])
    assert normalized
    for rec in normalized:
        assert {"transaction_id", "store", "till", "timestamp", "sku", "quantity", "amount", "payment_type"} <= rec.keys()


@pytest.mark.asyncio
async def test_pos_mock_pull_varies_by_cursor():
    connector = get_connector("pos")
    a = await connector.pull(cursor="c1")
    b = await connector.pull(cursor="c2")
    assert a["records"] != b["records"]


@pytest.mark.asyncio
async def test_inventory_wms_mock_pull_normalizes_and_maps_to_risk_rows():
    connector = get_connector("inventory_wms")
    pulled = await connector.pull(cursor="wms-1")
    normalized = await connector.normalize(pulled["records"])
    for rec in normalized:
        assert {"sku", "on_hand", "reorder_point", "safety_stock", "average_daily_sales"} <= rec.keys()
    rows = to_inventory_risk_rows(normalized)
    assert rows
    assert all("sku" in r and "on_hand" in r for r in rows)

    # The mapped rows feed directly into the existing inventory-risk normalizer.
    from app.retailops.kit.domains.retail.schemas import normalize_inventory_row

    for row in rows:
        canon = normalize_inventory_row(row)
        assert canon.get("sku") == row["sku"]
        if row.get("on_hand") is not None:
            assert canon.get("on_hand") == float(row["on_hand"])


@pytest.mark.asyncio
async def test_supplier_edi_mock_pull_normalizes():
    connector = get_connector("supplier_edi")
    pulled = await connector.pull(cursor="edi-1")
    normalized = await connector.normalize(pulled["records"])
    assert normalized
    for rec in normalized:
        assert {
            "order_id", "supplier_id", "sku", "quantity_ordered",
            "promised_delivery", "actual_delivery", "quantity_received",
        } <= rec.keys()


@pytest.mark.asyncio
async def test_power_bi_pull_and_csv_export_real_and_deterministic():
    connector = get_connector("power_bi")
    pulled = await connector.pull(cursor="pbi-1")
    assert pulled["records"]
    result = await connector.push("export_csv", {"rows": pulled["records"]})
    assert result["ok"] is True
    assert result["content_type"] == "text/csv"
    csv_text = base64.b64decode(result["content_base64"]).decode("utf-8")
    header = csv_text.splitlines()[0]
    assert "date" in header and "store_id" in header
    assert result["row_count"] == len(pulled["records"])


@pytest.mark.asyncio
async def test_power_bi_xlsx_export_is_a_real_workbook():
    from io import BytesIO

    from openpyxl import load_workbook

    connector = get_connector("power_bi")
    pulled = await connector.pull(cursor="pbi-2")
    result = await connector.push("export_xlsx", {"rows": pulled["records"]})
    assert result["content_type"].endswith("spreadsheetml.sheet")
    wb = load_workbook(BytesIO(base64.b64decode(result["content_base64"])))
    ws = wb.active
    assert ws.max_row == len(pulled["records"]) + 1  # header + rows


@pytest.mark.asyncio
async def test_power_bi_publish_and_refresh_are_honest_stubs():
    connector = get_connector("power_bi")
    publish = await connector.push("publish_dataset", {})
    refresh = await connector.push("refresh_semantic_model", {})
    assert publish["ok"] is False and publish["status"] == "not_implemented"
    assert refresh["ok"] is False and refresh["status"] == "not_implemented"


@pytest.mark.asyncio
async def test_power_bi_embed_url_is_an_explicit_placeholder():
    connector = get_connector("power_bi")
    result = await connector.push("get_embed_url", {})
    assert result["status"] == "placeholder"
    assert "PLACEHOLDER" in result["embed_url"]


@pytest.mark.asyncio
async def test_power_bi_unsupported_operation_raises():
    connector = get_connector("power_bi")
    with pytest.raises(ConnectorError):
        await connector.push("delete_everything", {})


# ---------------------------------------------------------------------------
# In-memory run history
# ---------------------------------------------------------------------------

def test_run_history_starts_empty_after_reset():
    assert list_runs(tenant_id=TENANT, project_id="p1", connector_id="pos") == []


# ---------------------------------------------------------------------------
# HTTP API routes (require Postgres; skip gracefully like the rest of the suite)
# ---------------------------------------------------------------------------

MANAGER = "u_ops_manager"


def test_list_integrations_route_returns_all_eight(client, loaded_projects):
    pid = loaded_projects["Global Region"]
    r = client.get("/v1/integrations", headers=_headers(MANAGER, pid))
    assert r.status_code == 200
    ids = {c["connector_id"] for c in r.json()["integrations"]}
    assert ids == ALL_IDS


def test_get_integration_route_unknown_connector_is_404(client, loaded_projects):
    pid = loaded_projects["Global Region"]
    r = client.get("/v1/integrations/does_not_exist", headers=_headers(MANAGER, pid))
    assert r.status_code == 404


def test_test_connection_route_records_a_run(client, loaded_projects):
    pid = loaded_projects["Global Region"]
    r = client.post("/v1/integrations/pos/test", headers=_headers(MANAGER, pid))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "mock"

    runs = client.get("/v1/integrations/pos/runs", headers=_headers(MANAGER, pid)).json()["runs"]
    assert any(run["kind"] == "test" for run in runs)


def test_sync_route_pull_normalize_for_mock_functional_connector(client, loaded_projects):
    pid = loaded_projects["Global Region"]
    r = client.post(
        "/v1/integrations/inventory_wms/sync", headers=_headers(MANAGER, pid), json={"cursor": "wms-x"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["record_count"] > 0
    assert body["records"][0]["sku"]

    runs = client.get("/v1/integrations/inventory_wms/runs", headers=_headers(MANAGER, pid)).json()["runs"]
    assert any(run["kind"] == "sync" and run["status"] == "success" for run in runs)


def test_sync_route_honest_stub_reports_error_not_fabricated_data(client, loaded_projects):
    pid = loaded_projects["Global Region"]
    r = client.post("/v1/integrations/sap_erp/sync", headers=_headers(MANAGER, pid), json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "not implemented" in body["message"].lower()

    runs = client.get("/v1/integrations/sap_erp/runs", headers=_headers(MANAGER, pid)).json()["runs"]
    assert any(run["kind"] == "sync" and run["status"] == "error" for run in runs)


def test_sync_route_push_operation_for_power_bi_export(client, loaded_projects):
    pid = loaded_projects["Global Region"]
    r = client.post(
        "/v1/integrations/power_bi/sync",
        headers=_headers(MANAGER, pid),
        json={"operation": "export_csv", "payload": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["result"]["content_type"] == "text/csv"


def test_get_integration_route_includes_health(client, loaded_projects):
    pid = loaded_projects["Global Region"]
    r = client.get("/v1/integrations/power_bi", headers=_headers(MANAGER, pid))
    assert r.status_code == 200
    assert "health" in r.json()
