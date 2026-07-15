"""Confirmed discipline-hat memory (teachable overrides)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.retailops.agents import get_agent_catalog
from app.retailops.models import RetailAgentMemory

_DENIED_VALUE_KEYS = frozenset(
    {
        "llm_raw_text",
        "raw_llm",
        "password",
        "secret",
        "token",
        "ssn",
        "employee_name",
        "guest_name",
        "card_number",
    }
)


class AgentMemoryError(ValueError):
    """Raised when a memory write is refused."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def list_memory(
    session: Session,
    *,
    tenant_id: str,
    project_id: str,
    agent_id: Optional[str] = None,
    key: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[RetailAgentMemory]:
    stmt = select(RetailAgentMemory).where(
        RetailAgentMemory.tenant_id == tenant_id,
        RetailAgentMemory.project_id == project_id,
    )
    if agent_id:
        stmt = stmt.where(RetailAgentMemory.agent_id == agent_id)
    if key:
        stmt = stmt.where(RetailAgentMemory.key == key)
    stmt = stmt.order_by(RetailAgentMemory.updated_at.desc()).offset(offset).limit(limit)
    return list(session.execute(stmt).scalars().all())


def memory_to_dict(row: RetailAgentMemory) -> Dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "project_id": row.project_id,
        "agent_id": row.agent_id,
        "key": row.key,
        "value": dict(row.value or {}),
        "description": row.description,
        "confirmed_by": row.confirmed_by,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "version": row.version,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "advisory_only": True,
    }


def _validate_against_manifest(agent_id: str, key: str) -> str:
    catalog = get_agent_catalog()
    agent = catalog.get(agent_id)
    if agent is None:
        raise AgentMemoryError(f"unknown agent '{agent_id}'")
    allowed = {rule.key: rule for rule in agent.memory.save}
    if key not in allowed:
        raise AgentMemoryError(
            f"key '{key}' is not a declared memory.save entry for '{agent_id}'"
        )
    rule = allowed[key]
    if not rule.requires_confirmation:
        # Defensive: all save rules should require confirmation.
        pass
    return rule.description


def _sanitize_value(value: Dict[str, Any], never_persist: List[str]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentMemoryError("value must be a JSON object")
    blocked = set(never_persist) | _DENIED_VALUE_KEYS
    clean: Dict[str, Any] = {}
    for k, v in value.items():
        lk = str(k).lower()
        if lk in blocked or any(b.replace("_", "") in lk.replace("_", "") for b in blocked):
            raise AgentMemoryError(f"value key '{k}' is denied by memory policy")
        if isinstance(v, str) and len(v) > 2000:
            raise AgentMemoryError(f"value for '{k}' exceeds 2000 characters")
        clean[k] = v
    # Reject free-text dumps that look like LLM answers.
    blob = " ".join(str(v) for v in clean.values()).lower()
    if re.search(r"\bas an ai\b|\bas a language model\b", blob):
        raise AgentMemoryError("LLM free text is not allowed in memory values")
    return clean


def save_memory(
    session: Session,
    *,
    tenant_id: str,
    project_id: str,
    user_id: str,
    agent_id: str,
    key: str,
    value: Dict[str, Any],
    confirmed: bool,
) -> RetailAgentMemory:
    if not confirmed:
        raise AgentMemoryError("confirmation required to save agent memory")
    description = _validate_against_manifest(agent_id, key)
    catalog = get_agent_catalog()
    agent = catalog.get(agent_id)
    assert agent is not None
    clean = _sanitize_value(value, list(agent.memory.never_persist))

    existing = session.execute(
        select(RetailAgentMemory).where(
            RetailAgentMemory.tenant_id == tenant_id,
            RetailAgentMemory.project_id == project_id,
            RetailAgentMemory.agent_id == agent_id,
            RetailAgentMemory.key == key,
        )
    ).scalar_one_or_none()

    now = _utcnow()
    if existing is None:
        row = RetailAgentMemory(
            id=f"mem_{uuid.uuid4().hex}",
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
            key=key,
            value=clean,
            description=description,
            confirmed_by=user_id,
            confirmed_at=now,
            version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return row

    existing.value = clean
    existing.description = description
    existing.confirmed_by = user_id
    existing.confirmed_at = now
    existing.version = int(existing.version or 1) + 1
    existing.updated_at = now
    session.flush()
    return existing
