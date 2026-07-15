"""POS connector — NCR / Toshiba / D365 Commerce / Generic.

Mock-functional: deterministic fictional transactions, sales by SKU, returns,
discounts, store/till/timestamp/payment-type — no real vendor API calls.

If ``RETAILOPS_POS_BASE_URL`` + ``RETAILOPS_POS_API_KEY`` are configured, the
connector reports ``configured`` and *would* use the generic REST adapter for
a real pull; this pilot does not ship vendor-specific (NCR/Toshiba/D365)
client code, so real pulls still raise :class:`ConnectorError` honestly
rather than pretending to fetch live data.
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
from app.retailops.integrations.mock_data import pos_transactions

VENDORS = ["ncr", "toshiba", "d365_commerce", "generic"]


class PosConnector(GenericRestMixin, RetailConnector):
    connector_id = "pos"
    display_name = "POS"
    category = "point_of_sale"
    vendor_examples = ["NCR", "Toshiba", "D365 Commerce", "Generic"]
    capabilities = [
        "transactions", "sales_by_sku", "returns", "discounts",
        "store", "till", "timestamp", "payment_type",
    ]
    read_only = True
    mock_functional = True
    description = (
        "Point-of-sale transaction feed: sales, returns and discounts by SKU, "
        "store and till, with payment type and timestamp."
    )

    def __init__(self) -> None:
        self.vendor = os.getenv("RETAILOPS_POS_VENDOR", "generic").lower()
        self.base_url = os.getenv("RETAILOPS_POS_BASE_URL", "")
        self.api_key = os.getenv("RETAILOPS_POS_API_KEY", "")

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
                return {"ok": True, "status": ConnectorStatus.CONNECTED, "message": "Generic REST POS endpoint reachable."}
            except ConnectorError as exc:
                return {"ok": False, "status": ConnectorStatus.ERROR, "message": str(exc)}
        return {
            "ok": True,
            "status": ConnectorStatus.MOCK,
            "message": (
                "No POS endpoint configured — running in deterministic mock mode. "
                "Set RETAILOPS_POS_BASE_URL and RETAILOPS_POS_API_KEY to test a real "
                "generic REST endpoint."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        if self.rest_available():
            try:
                data = await self.rest_get_json("transactions", params={"cursor": cursor, "since": since})
                return {"records": data.get("records", []), "next_cursor": data.get("next_cursor"), "source": "rest"}
            except ConnectorError:
                raise
        seed_key = cursor or since or "default"
        records = pos_transactions(seed_key)
        return {"records": records, "next_cursor": f"pos-{seed_key}-next", "source": "mock"}

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for rec in records:
            qty = rec.get("qty", 0)
            unit_price = rec.get("unit_price", 0.0)
            discount = rec.get("discount", 0.0)
            amount = round(qty * unit_price - discount, 2)
            normalized.append(
                {
                    "transaction_id": rec.get("txn_id"),
                    "store": rec.get("store_id"),
                    "till": rec.get("till_id"),
                    "timestamp": rec.get("ts"),
                    "sku": rec.get("sku"),
                    "quantity": qty,
                    "unit_price": unit_price,
                    "discount": discount,
                    "amount": amount,
                    "payment_type": rec.get("payment_type"),
                    "record_type": rec.get("type", "sale"),
                }
            )
        return normalized

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "POS connector is read-only in this pilot; push is not supported.",
            error_code="read_only",
        )


def build() -> PosConnector:
    return PosConnector()
