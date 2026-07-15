"""Generic enterprise-integration connector contract + shared adapter helpers.

Mirrors the LLM provider abstraction in ``app.retailops.providers``: a
domain-neutral interface, an optional "real" adapter that speaks to a
configurable REST endpoint, and a deterministic mock/fake fallback used for
the credential-free pilot. No credentials are hardcoded anywhere in this
package — every secret is read from the environment at call time, and a
missing/invalid credential degrades honestly (``disabled`` / ``configured``
/ ``error``) rather than fabricating vendor data.

Every connector implements the same async contract regardless of whether it
is "mock-functional" (deterministic fictional data, safe for demos) or an
"honest stub" (no vendor adapter implemented yet for this pilot):

    connector_id / display_name / capabilities / read_only
    health() / test_connection() / pull() / normalize() / push()
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConnectorStatus(str):
    """Closed set of connector statuses (plain str subclass constants).

    Kept as string constants (not an ``enum.Enum``) so connector code can
    return them directly as JSON-safe values without an extra ``.value``.
    """

    DISABLED = "disabled"
    MOCK = "mock"
    CONFIGURED = "configured"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    ERROR = "error"


ALL_STATUSES = frozenset(
    {
        ConnectorStatus.DISABLED,
        ConnectorStatus.MOCK,
        ConnectorStatus.CONFIGURED,
        ConnectorStatus.CONNECTED,
        ConnectorStatus.DEGRADED,
        ConnectorStatus.ERROR,
    }
)


class ConnectorError(RuntimeError):
    """Raised on connector misconfiguration or upstream failure.

    Connector failures always raise ``ConnectorError`` — they never cause a
    handler to fabricate pull/push output. Callers (the API layer) turn this
    into an honest, non-2xx-free response and an audit run record.
    """

    def __init__(self, message: str, *, error_code: str = "connector_error") -> None:
        super().__init__(message)
        self.error_code = error_code


class ConnectorBadge(BaseModel):
    """A short, honest UI badge (e.g. ``Credentials required``, ``Read-only``)."""

    label: str
    tone: str = "neutral"  # neutral | positive | warning | info


class RetailConnector:
    """Base class for every RetailOps enterprise integration connector.

    Subclasses set the class-level metadata attributes and implement the
    five async methods. ``mock_functional=True`` connectors must produce
    deterministic fictional data from :meth:`pull`/:meth:`normalize` with no
    outbound network calls when no real credentials are configured. Stub
    connectors must never fabricate vendor data — they raise
    :class:`ConnectorError` with an honest, actionable message instead.
    """

    connector_id: str = "base"
    display_name: str = "Base Connector"
    category: str = "generic"
    vendor_examples: List[str] = []
    capabilities: List[str] = []
    read_only: bool = True
    mock_functional: bool = False
    planned_capabilities: List[str] = []
    description: str = ""

    def status(self) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def badges(self) -> List[ConnectorBadge]:
        """Honest UI badges. Subclasses may override; default is status-derived."""
        status = self.status()
        badges: List[ConnectorBadge] = []
        if status == ConnectorStatus.DISABLED:
            badges.append(ConnectorBadge(label="Not connected", tone="neutral"))
            badges.append(ConnectorBadge(label="Credentials required", tone="warning"))
        elif status == ConnectorStatus.MOCK:
            badges.append(ConnectorBadge(label="Mock available", tone="info"))
        elif status == ConnectorStatus.CONFIGURED:
            badges.append(ConnectorBadge(label="Configured", tone="info"))
        elif status == ConnectorStatus.CONNECTED:
            badges.append(ConnectorBadge(label="Connected", tone="positive"))
        elif status == ConnectorStatus.DEGRADED:
            badges.append(ConnectorBadge(label="Degraded", tone="warning"))
        elif status == ConnectorStatus.ERROR:
            badges.append(ConnectorBadge(label="Error", tone="warning"))
        if self.read_only:
            badges.append(ConnectorBadge(label="Read-only", tone="neutral"))
        if self.planned_capabilities:
            badges.append(ConnectorBadge(label="Planned capability", tone="neutral"))
        return badges

    async def health(self) -> Dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    async def test_connection(self) -> Dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    async def pull(
        self, *, cursor: Optional[str] = None, since: Optional[str] = None
    ) -> Dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    async def normalize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:  # pragma: no cover - interface
        raise NotImplementedError

    async def push(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    def public_dict(self) -> Dict[str, Any]:
        """Deterministic, JSON-safe card summary for the ``/v1/integrations`` list."""
        return {
            "connector_id": self.connector_id,
            "display_name": self.display_name,
            "category": self.category,
            "description": self.description,
            "vendor_examples": list(self.vendor_examples),
            "capabilities": list(self.capabilities),
            "planned_capabilities": list(self.planned_capabilities),
            "read_only": self.read_only,
            "mock_functional": self.mock_functional,
            "status": self.status(),
            "badges": [b.model_dump() for b in self.badges()],
        }


# ---------------------------------------------------------------------------
# Shared helpers for building mock-functional + generic-REST connectors
# ---------------------------------------------------------------------------


def deterministic_rng(*parts: str) -> random.Random:
    """A ``random.Random`` seeded deterministically from the given parts.

    Used by mock-functional connectors so the same connector/cursor always
    produces the same fictional dataset — required by "deterministic
    fictional data" (never random-per-call, never fabricated per real facts).
    """
    seed_material = "|".join(parts).encode("utf-8")
    seed = int(hashlib.sha256(seed_material).hexdigest(), 16)
    return random.Random(seed)


class GenericRestMixin:
    """Optional real adapter: a minimal, generic authenticated REST GET/POST.

    This mirrors ``OpenAICompatibleProvider`` in ``app.retailops.providers``:
    a single generic, vendor-agnostic real HTTP path used only when a base
    URL + API key are configured via environment variables. It is never
    required — connectors fall back to their deterministic mock generator
    when it is absent or the call fails, and always raise
    :class:`ConnectorError` rather than silently returning fabricated data
    labelled as real.
    """

    base_url: str = ""
    api_key: str = ""

    def rest_available(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def rest_get_json(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self.rest_available():
            raise ConnectorError("generic REST adapter is not configured", error_code="not_configured")
        import httpx

        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    url, params=params, headers={"Authorization": f"Bearer {self.api_key}"}
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"generic REST request failed: {exc}", error_code="upstream_error") from exc

    async def rest_post_json(self, path: str, *, json_body: Optional[Dict[str, Any]] = None) -> Any:
        if not self.rest_available():
            raise ConnectorError("generic REST adapter is not configured", error_code="not_configured")
        import httpx

        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url, json=json_body or {}, headers={"Authorization": f"Bearer {self.api_key}"}
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"generic REST request failed: {exc}", error_code="upstream_error") from exc
