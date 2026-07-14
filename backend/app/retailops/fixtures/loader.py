"""Load the fictional Northstar fixture pack into the operational store.

Two canonical projects are created and their documents ingested with document
roles (used by schema-driven context enrichment). Verified learning outcomes
are loaded idempotently into PostgreSQL learning tables.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from sqlalchemy.orm import Session

from app.retailops import bootstrap
from app.retailops.ingestion import ingest_document
from app.retailops.learning import RetailOutcomeLearningEngine

_HERE = Path(__file__).resolve().parent / "northstar"
_LEARNING = _HERE / "learning" / "verified_outcomes.json"

TENANT_ID = "northstar"
TENANT_NAME = "Northstar Global Retail"

# Canonical project name -> fixture subdirectory. Stable canonical names let
# tests resolve generated project IDs by name.
PROJECTS: Dict[str, str] = {
    "Northstar Riyadh Region": "riyadh",
    "Northstar Melbourne Region": "melbourne",
}

# Default pilot principals with retail permissions.
MANAGER_ID = "u_ops_manager"
VIEWER_ID = "u_viewer"


def _role_for(filename: str) -> str:
    name = filename.lower()
    if name.startswith("sop") or "sop_" in name:
        return "policy"
    if "promotion_rules" in name:
        return "promotion_rules"
    if "promotion_evidence" in name or "evidence" in name:
        return "promotion_evidence"
    if "supplier" in name:
        return "supplier"
    if "incident" in name:
        return "incident"
    if "inventory" in name:
        return "inventory"
    return "document"


def load_learning_fixtures(
    session: Session,
    *,
    tenant_id: str,
    project_ids: Dict[str, str],
    verified_by: str = MANAGER_ID,
) -> int:
    """Load verified outcomes. Returns number of newly written events."""
    if not _LEARNING.exists():
        return 0
    data = json.loads(_LEARNING.read_text(encoding="utf-8"))
    target_canonical = data.get("project_canonical") or "Northstar Riyadh Region"
    project_id = project_ids.get(target_canonical)
    if not project_id:
        return 0
    engine = RetailOutcomeLearningEngine()
    written = 0
    for item in data.get("events") or []:
        result = engine.record_verified_outcome(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            module=item["module"],
            payload=item.get("payload") or {},
            verified_by=verified_by,
            deduplication_key=item["deduplication_key"],
            source_reference=f"fixtures://learning/{item['deduplication_key']}",
            verification_status="verified",
        )
        if not result.get("idempotent"):
            written += 1
    return written


def load_fixtures(session: Session, tenant_id: str = TENANT_ID) -> Dict[str, str]:
    """Ingest the fixture pack. Returns {canonical_name: project_id}."""
    bootstrap.ensure_tenant(session, tenant_id, TENANT_NAME)
    bootstrap.ensure_user(
        session,
        MANAGER_ID,
        tenant_id,
        name="Ops Manager",
        permissions=["retail:read", "retail:analyse", "retail:learning_write"],
    )
    bootstrap.ensure_user(
        session, VIEWER_ID, tenant_id, name="Viewer", permissions=["retail:read"],
    )

    project_ids: Dict[str, str] = {}
    for canonical_name, subdir in PROJECTS.items():
        project = bootstrap.ensure_project(
            session, tenant_id=tenant_id, canonical_name=canonical_name
        )
        project_ids[canonical_name] = project.id
        folder = _HERE / subdir
        for path in sorted(folder.iterdir()):
            if not path.is_file():
                continue
            data = path.read_bytes()
            doc = ingest_document(
                session,
                tenant_id=tenant_id,
                project_id=project.id,
                filename=path.name,
                data=data,
                source_uri=f"fixtures://{subdir}/{path.name}",
            )
            meta = dict(doc.meta or {})
            meta["doc_role"] = _role_for(path.name)
            doc.meta = meta
        session.flush()

    load_learning_fixtures(session, tenant_id=tenant_id, project_ids=project_ids)
    session.flush()
    return project_ids
