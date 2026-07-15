"""Embedding-space safety: refuse mixed model/dim corpora.

Documents and chunks persist ``embedding_model`` + ``embedding_dim`` in
metadata. Query/embed paths refuse to continue when the active embedder does
not match an existing project fingerprint — no silent re-embedding into a
different space.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.retailops.config import EMBED_DIM
from app.retailops.embeddings import EmbeddingProvider, get_embedder
from app.retailops.models import Document


class EmbeddingSpaceError(RuntimeError):
    """Active embedder is incompatible with vectors already stored for a project."""


def fingerprint(embedder: Optional[EmbeddingProvider] = None) -> Dict[str, Any]:
    """Return the model id + dim that will be stamped onto new embeddings."""
    emb = embedder or get_embedder()
    return {
        "embedding_model": getattr(emb, "model_name", None) or emb.__class__.__name__,
        "embedding_dim": int(getattr(emb, "dim", EMBED_DIM)),
    }


def _meta_fingerprint(meta: Optional[Dict[str, Any]]) -> Optional[Tuple[str, int]]:
    if not meta:
        return None
    model = meta.get("embedding_model")
    if model is None:
        return None
    dim_raw = meta.get("embedding_dim")
    dim = int(dim_raw) if dim_raw is not None else EMBED_DIM
    return str(model), dim


def project_fingerprint(
    session: Session,
    *,
    tenant_id: str,
    project_id: str,
) -> Optional[Tuple[str, int]]:
    """Return the first persisted (model, dim) for this tenant+project, if any."""
    rows = session.execute(
        select(Document.meta)
        .where(
            Document.tenant_id == tenant_id,
            Document.project_id == project_id,
            Document.status == "processed",
        )
        .limit(50)
    ).scalars()
    for meta in rows:
        fp = _meta_fingerprint(meta if isinstance(meta, dict) else None)
        if fp is not None:
            return fp
    return None


def assert_compatible(
    session: Session,
    *,
    tenant_id: str,
    project_id: str,
    embedder: Optional[EmbeddingProvider] = None,
) -> Dict[str, Any]:
    """Raise ``EmbeddingSpaceError`` when active embedder ≠ project stamp."""
    active = fingerprint(embedder)
    existing = project_fingerprint(session, tenant_id=tenant_id, project_id=project_id)
    if existing is None:
        return active
    model, dim = existing
    if model != active["embedding_model"] or dim != active["embedding_dim"]:
        raise EmbeddingSpaceError(
            "embedding space mismatch for "
            f"tenant={tenant_id} project={project_id}: "
            f"stored={model!r}/{dim}, active={active['embedding_model']!r}/"
            f"{active['embedding_dim']}. Re-ingest under a single backend or "
            "set RETAILOPS_EMBED_BACKEND to match the stored model."
        )
    return active
