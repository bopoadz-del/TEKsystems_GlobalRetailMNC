"""Store Digital Twin connector — honest stub with a documented data shape.

UI label is deliberately "Store Digital Twin" (not "retail BIM"). No live
digital-twin/planogram service is integrated in this pilot. The planogram
record *shape* is documented below (``PLANOGRAM_RECORD_SHAPE``) so a future
real adapter has a stable contract to target, but ``pull()``/``push()`` never
fabricate planogram or fixture data — they raise :class:`ConnectorError`.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.retailops.integrations.base import ConnectorBadge, ConnectorError, ConnectorStatus, RetailConnector

VENDORS = ["generic_digital_twin"]

# Documented target shape for a future real adapter — not populated with data.
PLANOGRAM_RECORD_SHAPE: Dict[str, str] = {
    "store_id": "string",
    "planogram_id": "string",
    "fixture": "string",
    "zone": "string",
    "sku": "string",
    "facings": "integer",
    "position": "string",
    "effective_date": "date",
}


class StoreDigitalTwinConnector(RetailConnector):
    connector_id = "store_digital_twin"
    display_name = "Store Digital Twin"
    category = "digital_twin"
    vendor_examples = ["Generic Digital Twin"]
    capabilities = []
    planned_capabilities = ["planogram_sync", "fixture_layout", "zone_mapping"]
    read_only = True
    mock_functional = False
    description = (
        "Store digital twin / planogram integration. Not connected in this "
        "pilot — the planogram data shape is documented and ready, but no "
        "live adapter is implemented."
    )

    def __init__(self) -> None:
        self.base_url = os.getenv("RETAILOPS_DIGITAL_TWIN_BASE_URL", "")
        self.api_key = os.getenv("RETAILOPS_DIGITAL_TWIN_API_KEY", "")

    def available(self) -> bool:
        return bool(self.base_url and self.api_key)

    def status(self) -> str:
        return ConnectorStatus.CONFIGURED if self.available() else ConnectorStatus.DISABLED

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label="Planogram shape documented", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "status": self.status(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "planogram_record_shape": PLANOGRAM_RECORD_SHAPE,
        }

    async def test_connection(self) -> Dict[str, Any]:
        if not self.available():
            return {
                "ok": False,
                "status": ConnectorStatus.DISABLED,
                "message": (
                    "Store Digital Twin credentials are not configured. This "
                    "connector is a planned-capability stub — the planogram data "
                    "shape is documented but no live adapter exists yet."
                ),
            }
        return {
            "ok": False,
            "status": ConnectorStatus.CONFIGURED,
            "message": (
                "Credentials detected, but a real digital-twin adapter is not "
                "implemented in this pilot. No connection was attempted."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        raise ConnectorError(
            "Store Digital Twin pull is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return []

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "Store Digital Twin push is not implemented in this pilot (planned capability).",
            error_code="not_implemented",
        )


def build() -> StoreDigitalTwinConnector:
    return StoreDigitalTwinConnector()
