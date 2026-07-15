"""Power BI connector — export, publish/refresh stubs, embed placeholder.

Mock-functional (per the pilot scope): the KPI dataset pull and CSV/XLSX
export are real, working code paths — no fabricated files, just genuinely
generated CSV/XLSX bytes from deterministic fictional KPI rows (or caller
-supplied rows). "Publish dataset" and "refresh semantic model" stay honest
stubs (Power BI dataset/refresh APIs are not implemented in this pilot); the
embed dashboard URL is an explicit placeholder, never a fabricated real link.

If ``RETAILOPS_POWERBI_TENANT_ID`` / ``_CLIENT_ID`` / ``_CLIENT_SECRET`` /
``_WORKSPACE_ID`` are all configured, :meth:`test_connection` performs a real
Azure AD client-credentials token request + a real Power BI REST call to
verify workspace access. No credentials are hardcoded; nothing is attempted
without them.
"""

from __future__ import annotations

import base64
import csv
import io
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.retailops.integrations.base import (
    ConnectorBadge,
    ConnectorError,
    ConnectorStatus,
    RetailConnector,
)
from app.retailops.integrations.mock_data import power_bi_kpi_rows

_AAD_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_POWERBI_API = "https://api.powerbi.com/v1.0/myorg"
_POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"


class PowerBiConnector(RetailConnector):
    connector_id = "power_bi"
    display_name = "Power BI"
    category = "analytics_export"
    vendor_examples = ["Microsoft Power BI"]
    capabilities = [
        "export_csv", "export_xlsx", "kpi_dataset_pull",
    ]
    planned_capabilities = ["publish_dataset", "refresh_semantic_model", "embed_dashboard"]
    read_only = False
    mock_functional = True
    description = (
        "KPI export to Power BI: deterministic KPI dataset, real CSV/XLSX "
        "download. Dataset publish, semantic-model refresh and dashboard "
        "embed are documented stubs — not implemented against a live "
        "workspace in this pilot."
    )

    def __init__(self) -> None:
        self.tenant_id = os.getenv("RETAILOPS_POWERBI_TENANT_ID", "")
        self.client_id = os.getenv("RETAILOPS_POWERBI_CLIENT_ID", "")
        self.client_secret = os.getenv("RETAILOPS_POWERBI_CLIENT_SECRET", "")
        self.workspace_id = os.getenv("RETAILOPS_POWERBI_WORKSPACE_ID", "")

    def available(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret and self.workspace_id)

    def status(self) -> str:
        if self.available():
            return ConnectorStatus.CONFIGURED
        return ConnectorStatus.MOCK

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label="Publish/refresh: stub", tone="neutral"))
        badges.append(ConnectorBadge(label="Embed URL: placeholder", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "status": self.status(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _acquire_token(self) -> str:
        import httpx

        url = _AAD_TOKEN_URL.format(tenant=self.tenant_id)
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": _POWERBI_SCOPE,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, data=data)
                resp.raise_for_status()
                token = resp.json().get("access_token")
                if not token:
                    raise ConnectorError("Azure AD token response missing access_token")
                return token
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"Azure AD token request failed: {exc}", error_code="auth_failed") from exc

    async def test_connection(self) -> Dict[str, Any]:
        if not self.available():
            return {
                "ok": True,
                "status": ConnectorStatus.MOCK,
                "message": (
                    "No Power BI workspace configured — CSV/XLSX export works in "
                    "mock mode. Set RETAILOPS_POWERBI_TENANT_ID/_CLIENT_ID/"
                    "_CLIENT_SECRET/_WORKSPACE_ID for a real connectivity test."
                ),
            }
        import httpx

        try:
            token = await self._acquire_token()
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{_POWERBI_API}/groups/{self.workspace_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
            return {"ok": True, "status": ConnectorStatus.CONNECTED, "message": "Power BI workspace reachable."}
        except ConnectorError as exc:
            return {"ok": False, "status": ConnectorStatus.ERROR, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": ConnectorStatus.ERROR, "message": f"Power BI request failed: {exc}"}

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        seed_key = cursor or since or "default"
        rows = power_bi_kpi_rows(seed_key)
        return {"records": rows, "next_cursor": f"powerbi-{seed_key}-next", "source": "mock"}

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "date": rec.get("date"),
                "store": rec.get("store_id"),
                "total_sales": rec.get("total_sales"),
                "transaction_count": rec.get("transaction_count"),
                "stockout_events": rec.get("stockout_events"),
                "supplier_delay_events": rec.get("supplier_delay_events"),
            }
            for rec in records
        ]

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if operation == "export_csv":
            return self._export_csv(payload)
        if operation == "export_xlsx":
            return self._export_xlsx(payload)
        if operation == "publish_dataset":
            return {
                "ok": False,
                "status": "not_implemented",
                "message": (
                    "Publishing a KPI dataset to a live Power BI workspace is not "
                    "implemented in this pilot. This is an honest stub."
                ),
            }
        if operation == "refresh_semantic_model":
            return {
                "ok": False,
                "status": "not_implemented",
                "message": (
                    "Triggering a semantic model refresh is not implemented in "
                    "this pilot. This is an honest stub."
                ),
            }
        if operation == "get_embed_url":
            return {
                "ok": True,
                "status": "placeholder",
                "embed_url": "https://app.powerbi.com/reportEmbed?reportId=PLACEHOLDER",
                "message": "Placeholder embed URL — no live dashboard is provisioned in this pilot.",
            }
        raise ConnectorError(f"unsupported Power BI operation: {operation}", error_code="unsupported_operation")

    def _rows_for_export(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = payload.get("rows")
        if isinstance(rows, list) and rows:
            return rows
        return power_bi_kpi_rows(payload.get("cursor") or "export")

    def _export_csv(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        rows = self._rows_for_export(payload)
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return {
            "ok": True,
            "status": "exported",
            "filename": "retailops-kpi-export.csv",
            "content_type": "text/csv",
            "content_base64": base64.b64encode(buf.getvalue().encode("utf-8")).decode("ascii"),
            "row_count": len(rows),
        }

    def _export_xlsx(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        rows = self._rows_for_export(payload)
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "RetailOps KPI"
        if rows:
            headers = list(rows[0].keys())
            ws.append(headers)
            for row in rows:
                ws.append([row.get(h) for h in headers])
        buf = io.BytesIO()
        wb.save(buf)
        return {
            "ok": True,
            "status": "exported",
            "filename": "retailops-kpi-export.xlsx",
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "content_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "row_count": len(rows),
        }


def build() -> PowerBiConnector:
    return PowerBiConnector()
