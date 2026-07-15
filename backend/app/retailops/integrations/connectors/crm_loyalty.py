"""CRM & Loyalty connector — honest stub with a small illustrative sample.

No CRM/loyalty vendor adapter is implemented in this pilot. Unlike the other
three stubs, ``pull()`` does not hard-error: it returns a small, clearly
labelled *illustrative* fictional read-only sample (a handful of loyalty
records) rather than nothing, so the card is not entirely inert when a user
presses "Sync" — but this remains a stub, not a mock-functional connector:
there is no real vendor adapter, no pagination/cursor semantics, and the
sample is intentionally tiny and documented as illustrative only.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.retailops.integrations.base import (
    ConnectorBadge,
    ConnectorError,
    ConnectorStatus,
    deterministic_rng,
    RetailConnector,
)

VENDORS = ["salesforce_loyalty", "generic_crm"]

_TIERS = ["bronze", "silver", "gold", "platinum"]


class CrmLoyaltyConnector(RetailConnector):
    connector_id = "crm_loyalty"
    display_name = "CRM & Loyalty"
    category = "crm"
    vendor_examples = ["Salesforce Loyalty", "Generic CRM"]
    capabilities = ["loyalty_profile_sample"]
    planned_capabilities = ["customer_360", "campaign_membership", "loyalty_ledger"]
    read_only = True
    mock_functional = False
    description = (
        "Customer relationship + loyalty program integration. Not connected "
        "in this pilot; a tiny illustrative read-only sample is available on "
        "sync, but there is no live vendor adapter."
    )

    def __init__(self) -> None:
        self.base_url = os.getenv("RETAILOPS_CRM_BASE_URL", "")
        self.api_key = os.getenv("RETAILOPS_CRM_API_KEY", "")

    def available(self) -> bool:
        return bool(self.base_url and self.api_key)

    def status(self) -> str:
        return ConnectorStatus.CONFIGURED if self.available() else ConnectorStatus.DISABLED

    def badges(self) -> List[ConnectorBadge]:
        badges = super().badges()
        badges.append(ConnectorBadge(label="Illustrative sample only", tone="info"))
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
                    "CRM & Loyalty credentials are not configured. This connector "
                    "is a stub — sync returns a tiny illustrative read-only sample, "
                    "not a live feed."
                ),
            }
        return {
            "ok": False,
            "status": ConnectorStatus.CONFIGURED,
            "message": (
                "Credentials detected, but a real CRM/loyalty adapter is not "
                "implemented in this pilot. No connection was attempted."
            ),
        }

    async def pull(self, *, cursor: Optional[str] = None, since: Optional[str] = None) -> Dict[str, Any]:
        rng = deterministic_rng("crm_loyalty", cursor or since or "sample")
        records = [
            {
                "customer_id": f"CUST-{4000 + i}",
                "loyalty_tier": rng.choice(_TIERS),
                "points_balance": rng.randint(0, 5000),
                "email_opt_in": rng.random() < 0.7,
                "last_purchase_date": f"2026-06-{(i % 28) + 1:02d}",
            }
            for i in range(5)
        ]
        return {
            "records": records,
            "next_cursor": None,
            "source": "illustrative_sample",
            "note": "Tiny fictional sample for UI demonstration only — not a live CRM feed.",
        }

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "customer_id": rec.get("customer_id"),
                "loyalty_tier": rec.get("loyalty_tier"),
                "points_balance": rec.get("points_balance"),
                "email_opt_in": rec.get("email_opt_in"),
                "last_purchase_date": rec.get("last_purchase_date"),
            }
            for rec in records
        ]

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise ConnectorError(
            "CRM & Loyalty connector is read-only in this pilot; push is not supported.",
            error_code="read_only",
        )


def build() -> CrmLoyaltyConnector:
    return CrmLoyaltyConnector()
