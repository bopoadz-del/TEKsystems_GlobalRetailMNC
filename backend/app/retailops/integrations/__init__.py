"""RetailOps enterprise integration connectors (pilot).

Eight visible connector cards behind one shared, provider-abstraction-style
contract (see ``app.retailops.providers`` for the analogous LLM pattern):

    POS · SAP / ERP · Inventory & WMS · Supplier / EDI ·
    CRM & Loyalty · Store Digital Twin · Power BI · Microsoft Entra ID

Four are mock-functional (deterministic fictional data, no real vendor
calls): POS, Inventory & WMS, Supplier / EDI, Power BI export.
Four are honest stubs (not connected; planned capability; never fabricate
vendor data): SAP / ERP, CRM & Loyalty, Store Digital Twin, Microsoft Entra
ID.

Public surface:

* :class:`RetailConnector`  – the connector contract
* :class:`ConnectorStatus`  – closed status vocabulary
* :class:`ConnectorError`   – safe, non-fabricating failure signal
* :func:`list_connectors` / :func:`get_connector` – registry access
"""

from app.retailops.integrations.base import ConnectorError, ConnectorStatus, RetailConnector
from app.retailops.integrations.registry import build_registry, get_connector, list_connectors

__all__ = [
    "RetailConnector",
    "ConnectorStatus",
    "ConnectorError",
    "build_registry",
    "list_connectors",
    "get_connector",
]
