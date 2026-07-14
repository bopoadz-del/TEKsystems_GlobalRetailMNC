"""Supplier / EDI connector — Ariba / EDI 850/856/810 / Portal.

Mock-functional: deterministic fictional purchase orders with promised vs.
actual delivery, quantities, short/damaged/rejected counts, and notices.
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
from app.retailops.integrations.mock_data import edi_supplier_orders

VENDORS = ["ariba", "edi_850", "edi_856", "edi_810", "portal", "generic"]


class SupplierEdiConnector(GenericRestMixin, RetailConnector):
    connector_id = "supplier_edi"
    display_name = "Supplier / EDI"
    category = "supply_chain"
    vendor_examples = ["Ariba", "EDI 850", "EDI 856", "EDI 810", "Portal"]
    capabilities = [
        "orders", "promised_delivery", "actual_delivery", "quantities",
        "short", "damaged", "rejected", "notices",
    ]
    read_only = True
    mock_functional = True
    description = (
        "Supplier order and delivery feed: purchase orders, promised vs. "
        "actual delivery dates, quantities and short/damaged/rejected notices."
    )

    def __init__(self) -> None:
        self.vendor = os.getenv("RETAILOPS_EDI_VENDOR", "generic").lower()
        self.base_url = os.getenv("RETAILOPS_EDI_BASE_URL", "")
        self.api_key = os.getenv("RETAILOPS_EDI_API_KEY", "")

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
                return {"ok": True, "status": ConnectorStatus.CONNECTED, "message": "Generic REST EDI endpoint reachable."}
            except ConnectorError as exc:
                return {"ok": False, "status": ConnectorStatus.ERROR, "message": str(exc)}
        return {
            "ok": True,
            "status": ConnectorStatus.MOCK,
            "message": (
                "No supplier/EDI endpoint configured — running in deterministic "
                "mock mode. Set RETAILOPS_EDI_BASE_URL and RETAILOPS_EDI_API_KEY to "
                "test a real generic REST endpoint."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        if self.rest_available():
            try:
                data = await self.rest_get_json("orders", params={"cursor": cursor, "since": since})
                return {"records": data.get("records", []), "next_cursor": data.get("next_cursor"), "source": "rest"}
            except ConnectorError:
                raise
        seed_key = cursor or since or "default"
        records = edi_supplier_orders(seed_key)
        return {"records": records, "next_cursor": f"edi-{seed_key}-next", "source": "mock"}

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for rec in records:
            normalized.append(
                {
                    "order_id": rec.get("po_number"),
                    "supplier_id": rec.get("supplier_id"),
                    "sku": rec.get("sku"),
                    "quantity_ordered": rec.get("qty_ordered"),
                    "promised_delivery": rec.get("promised_date"),
                    "actual_delivery": rec.get("actual_date"),
                    "quantity_received": rec.get("qty_received"),
                    "quantity_short": rec.get("qty_short", 0),
                    "quantity_damaged": rec.get("qty_damaged", 0),
                    "quantity_rejected": rec.get("qty_rejected", 0),
                    "notice_type": rec.get("notice_type"),
                    "notice_text": rec.get("notice_text"),
                }
            )
        return normalized

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "Supplier / EDI connector is read-only in this pilot; push is not supported.",
            error_code="read_only",
        )


def build() -> SupplierEdiConnector:
    return SupplierEdiConnector()
