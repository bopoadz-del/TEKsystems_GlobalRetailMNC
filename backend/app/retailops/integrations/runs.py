"""Sync/test run history for integration connectors.

Pilot persistence note (documented, not hidden): RetailOps already has a
Postgres-backed audit trail for *actions* (``action_runs`` / ``app.retailops
.audit``). Reusing that table for integration runs would require a schema
migration and a foreign key to a domain (action_id) that doesn't apply here.
For the pilot, integration test/sync runs are kept in a lightweight
**in-process, in-memory** ring buffer per (tenant, project, connector) —
identical in shape to an audit record, so it can be swapped for a real
``integration_runs`` table (with an Alembic migration) later without changing
the API contract. This means run history does **not** survive a process
restart; that limitation is called out in the README.
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

_MAX_RUNS_PER_CONNECTOR = 200

# Keyed by (tenant_id, project_id, connector_id) -> deque of run records
# (most recent last). Process-lifetime only; see module docstring.
_RUNS: Dict[Tuple[str, str, str], Deque[Dict[str, Any]]] = defaultdict(
    lambda: deque(maxlen=_MAX_RUNS_PER_CONNECTOR)
)


@dataclass
class RunRecord:
    run_id: str
    connector_id: str
    tenant_id: str
    project_id: str
    user_id: str
    kind: str  # "test" | "sync"
    status: str  # "success" | "error"
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    detail: Dict[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "connector_id": self.connector_id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "kind": self.kind,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_ms": self.duration_ms,
            "detail": self.detail,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


def record_run(
    *,
    connector_id: str,
    tenant_id: str,
    project_id: str,
    user_id: str,
    kind: str,
    status: str,
    started_at: datetime,
    detail: Optional[Dict[str, Any]] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    completed_at = datetime.now(timezone.utc)
    duration_ms = max(0, int((completed_at - started_at).total_seconds() * 1000))
    run = RunRecord(
        run_id=f"irun_{uuid.uuid4().hex}",
        connector_id=connector_id,
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        kind=kind,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        detail=detail or {},
        error_code=error_code,
        error_message=error_message,
    )
    key = (tenant_id, project_id, connector_id)
    _RUNS[key].append(run.to_dict())
    return run.to_dict()


def list_runs(
    *, tenant_id: str, project_id: str, connector_id: Optional[str] = None, limit: int = 50
) -> List[Dict[str, Any]]:
    if connector_id is not None:
        key = (tenant_id, project_id, connector_id)
        runs = list(_RUNS.get(key, ()))
    else:
        runs = []
        for (t, p, _cid), bucket in _RUNS.items():
            if t == tenant_id and p == project_id:
                runs.extend(bucket)
    runs.sort(key=lambda r: r["started_at"], reverse=True)
    return runs[:limit]


def last_run(*, tenant_id: str, project_id: str, connector_id: str, kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
    runs = list_runs(tenant_id=tenant_id, project_id=project_id, connector_id=connector_id, limit=_MAX_RUNS_PER_CONNECTOR)
    for run in runs:
        if kind is None or run["kind"] == kind:
            return run
    return None


def reset_runs() -> None:
    """Clear all in-memory run history (used by tests)."""
    _RUNS.clear()
