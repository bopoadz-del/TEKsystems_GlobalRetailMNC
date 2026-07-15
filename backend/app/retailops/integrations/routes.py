"""HTTP API for the RetailOps enterprise integration connectors.

Endpoints (auth headers match the rest of the app — X-User-Id / X-Tenant-Id /
X-Project-Id, resolved server-side via the same trusted context dependency
used by ``/v1/actions`` etc.):

    GET  /v1/integrations
    GET  /v1/integrations/{connector_id}
    POST /v1/integrations/{connector_id}/test
    POST /v1/integrations/{connector_id}/sync
    GET  /v1/integrations/{connector_id}/runs

Connector failures never raise an unhandled 500 or fabricate data: they are
caught and reported as ``{"ok": false, ...}`` with an audit-style run record
(see ``app.retailops.integrations.runs``), mirroring how ``/v1/actions``
reports business-level failure statuses in a 200 body rather than as an
uncontrolled exception.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.retailops.api import get_context
from app.retailops.integrations.base import ConnectorError
from app.retailops.integrations.registry import get_connector, list_connectors
from app.retailops.integrations.runs import last_run, list_runs, record_run
from app.retailops.kit.contract import ActionContext

router = APIRouter()


class SyncRequest(BaseModel):
    cursor: Optional[str] = None
    since: Optional[str] = None
    operation: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


def _card(connector, context) -> Dict[str, Any]:
    card = connector.public_dict()
    last_test = last_run(
        tenant_id=context.tenant_id, project_id=context.project_id,
        connector_id=connector.connector_id, kind="test",
    )
    last_sync = last_run(
        tenant_id=context.tenant_id, project_id=context.project_id,
        connector_id=connector.connector_id, kind="sync",
    )
    card["last_test"] = last_test
    card["last_sync"] = last_sync
    return card


@router.get("/v1/integrations")
async def list_integrations(context: ActionContext = Depends(get_context)) -> Dict[str, Any]:
    return {"integrations": [_card(c, context) for c in list_connectors()]}


@router.get("/v1/integrations/{connector_id}")
async def get_integration(connector_id: str, context: ActionContext = Depends(get_context)) -> Dict[str, Any]:
    connector = get_connector(connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail={"status": "unsupported", "connector_id": connector_id})
    card = _card(connector, context)
    card["health"] = await connector.health()
    return card


@router.post("/v1/integrations/{connector_id}/test")
async def test_integration(connector_id: str, context: ActionContext = Depends(get_context)) -> Dict[str, Any]:
    connector = get_connector(connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail={"status": "unsupported", "connector_id": connector_id})

    started_at = datetime.now(timezone.utc)
    try:
        result = await connector.test_connection()
        record_run(
            connector_id=connector_id, tenant_id=context.tenant_id, project_id=context.project_id,
            user_id=context.user_id, kind="test", status="success" if result.get("ok") else "error",
            started_at=started_at, detail=result,
        )
        return {**result, "connector_id": connector_id, "status_after": connector.status()}
    except ConnectorError as exc:
        record_run(
            connector_id=connector_id, tenant_id=context.tenant_id, project_id=context.project_id,
            user_id=context.user_id, kind="test", status="error", started_at=started_at,
            error_code=exc.error_code, error_message=str(exc),
        )
        return {
            "ok": False, "connector_id": connector_id, "status_after": connector.status(),
            "error_code": exc.error_code, "message": str(exc),
        }


@router.post("/v1/integrations/{connector_id}/sync")
async def sync_integration(
    connector_id: str, body: SyncRequest, context: ActionContext = Depends(get_context)
) -> Dict[str, Any]:
    connector = get_connector(connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail={"status": "unsupported", "connector_id": connector_id})

    started_at = datetime.now(timezone.utc)
    try:
        if body.operation:
            result = await connector.push(body.operation, body.payload)
            detail: Dict[str, Any] = {"operation": body.operation, "result": result}
            record_run(
                connector_id=connector_id, tenant_id=context.tenant_id, project_id=context.project_id,
                user_id=context.user_id, kind="sync", status="success", started_at=started_at, detail=detail,
            )
            return {"ok": True, "connector_id": connector_id, "operation": body.operation, "result": result}

        pulled = await connector.pull(cursor=body.cursor, since=body.since)
        records = pulled.get("records", [])
        normalized = await connector.normalize(records)
        detail = {
            "record_count": len(records),
            "normalized_count": len(normalized),
            "next_cursor": pulled.get("next_cursor"),
            "source": pulled.get("source"),
        }
        record_run(
            connector_id=connector_id, tenant_id=context.tenant_id, project_id=context.project_id,
            user_id=context.user_id, kind="sync", status="success", started_at=started_at, detail=detail,
        )
        return {
            "ok": True,
            "connector_id": connector_id,
            "record_count": len(records),
            "next_cursor": pulled.get("next_cursor"),
            "source": pulled.get("source"),
            "records": normalized,
        }
    except ConnectorError as exc:
        record_run(
            connector_id=connector_id, tenant_id=context.tenant_id, project_id=context.project_id,
            user_id=context.user_id, kind="sync", status="error", started_at=started_at,
            error_code=exc.error_code, error_message=str(exc),
        )
        return {
            "ok": False, "connector_id": connector_id,
            "error_code": exc.error_code, "message": str(exc),
        }


@router.get("/v1/integrations/{connector_id}/runs")
async def integration_runs(connector_id: str, context: ActionContext = Depends(get_context)) -> Dict[str, Any]:
    connector = get_connector(connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail={"status": "unsupported", "connector_id": connector_id})
    runs = list_runs(tenant_id=context.tenant_id, project_id=context.project_id, connector_id=connector_id)
    return {"connector_id": connector_id, "runs": runs}
