"""Microsoft Entra ID connector — honest stub for SSO / roles / group mapping.

No SSO federation, role or group-mapping sync is implemented in this pilot.
RetailOps itself is not registered as an Entra ID application. If tenant /
client credentials are set, the connector reports ``configured`` (detected,
not attempted) — it never calls Microsoft Graph or performs a token exchange
in this pilot, and never fabricates roles/groups/users.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.retailops.integrations.base import ConnectorBadge, ConnectorError, ConnectorStatus, RetailConnector


class EntraIdConnector(RetailConnector):
    connector_id = "entra_id"
    display_name = "Microsoft Entra ID"
    category = "identity"
    vendor_examples = ["Microsoft Entra ID"]
    capabilities = []
    planned_capabilities = ["sso", "role_mapping", "group_mapping"]
    read_only = True
    mock_functional = False
    description = (
        "SSO, role and group-mapping integration with Microsoft Entra ID. "
        "Not connected in this pilot — planned capability for a future "
        "release; RetailOps uses server-resolved X-User-Id/X-Tenant-Id/"
        "X-Project-Id headers today."
    )

    def __init__(self) -> None:
        self.tenant_id = os.getenv("RETAILOPS_ENTRA_TENANT_ID", "")
        self.client_id = os.getenv("RETAILOPS_ENTRA_CLIENT_ID", "")
        self.client_secret = os.getenv("RETAILOPS_ENTRA_CLIENT_SECRET", "")

    def available(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret)

    def status(self) -> str:
        return ConnectorStatus.CONFIGURED if self.available() else ConnectorStatus.DISABLED

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label="SSO / roles / groups: planned", tone="neutral"))
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
                    "Microsoft Entra ID credentials are not configured. SSO, role "
                    "and group mapping are planned capabilities in this pilot."
                ),
            }
        return {
            "ok": False,
            "status": ConnectorStatus.CONFIGURED,
            "message": (
                "Credentials detected, but SSO/role/group-mapping sync is not "
                "implemented in this pilot. No connection was attempted."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        raise ConnectorError(
            "Microsoft Entra ID pull (roles/groups) is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return []

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "Microsoft Entra ID push is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )


def build() -> EntraIdConnector:
    return EntraIdConnector()
