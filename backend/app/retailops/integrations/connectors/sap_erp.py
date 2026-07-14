"""SAP / ERP connector — honest stub.

No SAP/ERP vendor adapter is implemented in this pilot. The connector never
fabricates financial, order or master-data records: without real credentials
it reports ``disabled``; with credentials present it reports ``configured``
but still declines to pull/push, since no vendor client exists yet.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.retailops.integrations.base import ConnectorBadge, ConnectorError, ConnectorStatus, RetailConnector

VENDORS = ["sap_s4hana", "sap_ecc", "generic_erp"]


class SapErpConnector(RetailConnector):
    connector_id = "sap_erp"
    display_name = "SAP / ERP"
    category = "erp"
    vendor_examples = ["SAP S/4HANA", "SAP ECC", "Generic ERP"]
    capabilities = ["general_ledger", "purchase_orders", "vendor_master", "cost_centers"]
    planned_capabilities = ["general_ledger", "purchase_orders", "vendor_master", "cost_centers"]
    read_only = True
    mock_functional = False
    description = (
        "Enterprise resource planning integration (financials, purchasing, "
        "vendor master data). Not connected in this pilot — planned capability."
    )

    def __init__(self) -> None:
        self.base_url = os.getenv("RETAILOPS_SAP_BASE_URL", "")
        self.client_id = os.getenv("RETAILOPS_SAP_CLIENT_ID", "")
        self.api_key = os.getenv("RETAILOPS_SAP_API_KEY", "")

    def available(self) -> bool:
        return bool(self.base_url and self.client_id and self.api_key)

    def status(self) -> str:
        return ConnectorStatus.CONFIGURED if self.available() else ConnectorStatus.DISABLED

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label="Planned: general ledger, purchase orders", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "status": self.status(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def test_connection(self) -> Dict[str, Any]:
        if not self.available():
            return {
                "ok": False,
                "status": ConnectorStatus.DISABLED,
                "message": (
                    "SAP / ERP credentials are not configured. This connector is a "
                    "planned-capability stub for the pilot — no vendor adapter is "
                    "implemented yet."
                ),
            }
        return {
            "ok": False,
            "status": ConnectorStatus.CONFIGURED,
            "message": (
                "Credentials detected, but a real SAP/ERP adapter is not "
                "implemented in this pilot. No connection was attempted."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        raise ConnectorError(
            "SAP / ERP pull is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return []

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "SAP / ERP push is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )


def build() -> SapErpConnector:
    return SapErpConnector()
