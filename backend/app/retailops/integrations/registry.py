"""Integration connector registry — discovery for the 8 pilot cards.

Mirrors ``app.retailops.service.build_registry`` (the action registry): a
single, ordered, discoverable list built from small builder functions so
adding a 9th connector never requires touching the API routes.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.retailops.integrations.base import RetailConnector
from app.retailops.integrations.connectors import (
    crm_loyalty,
    entra_id,
    inventory_wms,
    pos,
    power_bi,
    sap_erp,
    store_digital_twin,
    supplier_edi,
)

# Fixed pilot order — matches the card order in the product brief.
_BUILDERS = [
    pos.build,
    sap_erp.build,
    inventory_wms.build,
    supplier_edi.build,
    crm_loyalty.build,
    store_digital_twin.build,
    power_bi.build,
    entra_id.build,
]


def build_registry() -> Dict[str, RetailConnector]:
    """Instantiate every connector fresh (env vars are read at call time)."""
    connectors = [builder() for builder in _BUILDERS]
    return {c.connector_id: c for c in connectors}


def list_connectors() -> List[RetailConnector]:
    return list(build_registry().values())


def get_connector(connector_id: str) -> Optional[RetailConnector]:
    return build_registry().get(connector_id)
