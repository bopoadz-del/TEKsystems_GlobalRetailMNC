"""Inventory & WMS connector — Manhattan / Blue Yonder / RELEX / Generic.

Mock-functional: deterministic fictional on-hand/available/reserved by
warehouse, reorder/safety thresholds, transfers, receipts and adjustments.

Soft-wired to the existing ``retail.analyse_inventory_risk`` action: the
canonical field names produced by :meth:`normalize` (``sku``, ``on_hand``,
``reorder_point``, ``safety_stock``, ``average_daily_sales``, ``store``) match
``app.retailops.kit.domains.retail.schemas.INVENTORY_ALIASES`` exactly, so a
caller can feed ``to_inventory_risk_rows(normalized)`` straight into that
action's ``rows`` input without any extra mapping.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.retailops.integrations.base import (
    ConnectorBadge,
    ConnectorError,
    ConnectorStatus,
    GenericRestMixin,
    RetailConnector,
)
from app.retailops.integrations.mock_data import wms_inventory_events

VENDORS = ["manhattan", "blue_yonder", "relex", "generic"]


class InventoryWmsConnector(GenericRestMixin, RetailConnector):
    connector_id = "inventory_wms"
    display_name = "Inventory & WMS"
    category = "inventory"
    vendor_examples = ["Manhattan", "Blue Yonder", "RELEX", "Generic"]
    capabilities = [
        "on_hand", "available", "reserved", "warehouse",
        "reorder_point", "safety_stock", "transfers", "receipts", "adjustments",
    ]
    read_only = True
    mock_functional = True
    description = (
        "Warehouse/inventory feed: on-hand, available and reserved stock by "
        "warehouse and SKU, with reorder/safety thresholds and movement events."
    )

    def __init__(self) -> None:
        self.vendor = os.getenv("RETAILOPS_WMS_VENDOR", "generic").lower()
        self.base_url = os.getenv("RETAILOPS_WMS_BASE_URL", "")
        self.api_key = os.getenv("RETAILOPS_WMS_API_KEY", "")

    def status(self) -> str:
        if self.rest_available():
            return ConnectorStatus.CONFIGURED
        return ConnectorStatus.MOCK

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label=f"vendor: {self.vendor}", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "status": self.status(),
            "vendor": self.vendor,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def test_connection(self) -> Dict[str, Any]:
        if self.rest_available():
            try:
                await self.rest_get_json("health")
                return {"ok": True, "status": ConnectorStatus.CONNECTED, "message": "Generic REST WMS endpoint reachable."}
            except ConnectorError as exc:
                return {"ok": False, "status": ConnectorStatus.ERROR, "message": str(exc)}
        return {
            "ok": True,
            "status": ConnectorStatus.MOCK,
            "message": (
                "No WMS endpoint configured — running in deterministic mock mode. "
                "Set RETAILOPS_WMS_BASE_URL and RETAILOPS_WMS_API_KEY to test a real "
                "generic REST endpoint."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        if self.rest_available():
            try:
                data = await self.rest_get_json("inventory", params={"cursor": cursor, "since": since})
                return {"records": data.get("records", []), "next_cursor": data.get("next_cursor"), "source": "rest"}
            except ConnectorError:
                raise
        seed_key = cursor or since or "default"
        records = wms_inventory_events(seed_key)
        return {"records": records, "next_cursor": f"wms-{seed_key}-next", "source": "mock"}

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for rec in records:
            normalized.append(
                {
                    "warehouse": rec.get("warehouse_id"),
                    "store": rec.get("store_id"),
                    "sku": rec.get("sku"),
                    "on_hand": rec.get("on_hand"),
                    "available": rec.get("available"),
                    "reserved": rec.get("reserved"),
                    "reorder_point": rec.get("reorder_point"),
                    "safety_stock": rec.get("safety_stock"),
                    "average_daily_sales": rec.get("average_daily_sales"),
                    "event_type": rec.get("event_type"),
                    "quantity_delta": rec.get("qty_delta", 0),
                    "timestamp": rec.get("ts"),
                }
            )
        return normalized

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "Inventory & WMS connector is read-only in this pilot; push is not supported.",
            error_code="read_only",
        )


def to_inventory_risk_rows(normalized_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map normalized WMS records to ``retail.analyse_inventory_risk`` rows.

    Field names already match ``INVENTORY_ALIASES`` canonical keys, so this is
    a pass-through projection — documented here so the mapping is explicit and
    doesn't silently drift if either schema changes.
    """
    rows: List[Dict[str, Any]] = []
    for rec in normalized_records:
        rows.append(
            {
                "sku": rec.get("sku"),
                "on_hand": rec.get("on_hand"),
                "reorder_point": rec.get("reorder_point"),
                "safety_stock": rec.get("safety_stock"),
                "average_daily_sales": rec.get("average_daily_sales"),
                "store": rec.get("store"),
            }
        )
    return rows


def build() -> InventoryWmsConnector:
    return InventoryWmsConnector()
