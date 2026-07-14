"""Ingest FDA / OSHA / FTC into the platform-prebuilt corpus (not tenant fixtures)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.retailops import bootstrap
from app.retailops.embeddings import get_embedder
from app.retailops.ingestion import ParsedUnit, parse_bytes
from app.retailops.models import Document, DocumentChunk, RetailPackSource
from app.retailops.packs.retail_core_open_v1 import (
    COLLECTION_ID,
    PLATFORM_PROJECT_CANONICAL,
    PLATFORM_TENANT_ID,
    RAG_PACK_ID,
    RELEASE_ID,
)
from app.retailops.packs.retail_core_open_v1.loaders.acquire import acquire_source, cache_dir
from app.retailops.packs.retail_core_open_v1.registry import get_source

CHUNK_SIZE = 900
CHUNK_OVERLAP = 120


def ensure_platform_project(session: Session) -> str:
    bootstrap.ensure_tenant(session, PLATFORM_TENANT_ID, "Platform Prebuilt Knowledge")
    bootstrap.ensure_user(
        session,
        "u_platform",
        PLATFORM_TENANT_ID,
        name="Platform Reader",
        permissions=["retail:read", "retail:analyse"],
    )
    project = bootstrap.ensure_project(
        session,
        tenant_id=PLATFORM_TENANT_ID,
        canonical_name=PLATFORM_PROJECT_CANONICAL,
        project_id=f"prj_{COLLECTION_ID}",
    )
    return project.id


def _canon_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _section_chunks(text: str, *, page: Optional[int] = None) -> List[ParsedUnit]:
    """Split on markdown/HTML-ish headings when present; else sliding window."""
    text = _canon_text(text)
    if not text:
        return []
    parts = re.split(r"(?m)^(#{1,3}\s+.+|[A-Z][A-Z0-9 .-/]{8,}\n)$", text)
    # Fallback: plain windowing over full text.
    blocks: List[Tuple[str, Optional[str]]] = []
    if len(parts) <= 1:
        blocks = [(text, None)]
    else:
        buf = ""
        title: Optional[str] = None
        for part in parts:
            if not part or not part.strip():
                continue
            if re.match(r"^#{1,3}\s+", part) or (
                part.isupper() or (len(part) < 80 and part.endswith("\n") and part.isupper())
            ):
                if buf.strip():
                    blocks.append((buf.strip(), title))
                title = part.strip().lstrip("#").strip()
                buf = ""
            else:
                buf += part
        if buf.strip():
            blocks.append((buf.strip(), title))

    units: List[ParsedUnit] = []
    for block, section in blocks:
        start = 0
        while start < len(block):
            end = min(len(block), start + CHUNK_SIZE)
            chunk = block[start:end].strip()
            if len(chunk) >= 40:
                units.append(
                    ParsedUnit(
                        text=chunk if not section else f"{section}\n\n{chunk}",
                        page=page,
                        unit_type="text",
                    )
                )
            if end >= len(block):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
    return units


def _doc_id(source_id: str, checksum: str) -> str:
    return "doc_" + hashlib.sha256(f"{RELEASE_ID}|{source_id}|{checksum}".encode()).hexdigest()[:20]


def _chunk_id(document_id: str, ordinal: int, text: str) -> str:
    return "ch_" + hashlib.sha256(f"{document_id}|{ordinal}|{text[:200]}".encode()).hexdigest()[:24]


def ingest_text_source(
    session: Session,
    source_id: str,
    *,
    fixture_path: Optional[Path] = None,
    force: bool = False,
    prefer_network: bool = False,
) -> Dict[str, Any]:
    meta = get_source(source_id)
    if not meta or meta.get("structured_or_text") != "text":
        raise ValueError(f"not a text source: {source_id}")

    project_id = ensure_platform_project(session)

    # Mini fixtures are for offline/tests only. Full profile acquires from network
    # (or seed/) so official PDF/HTML checksums enter the platform corpus.
    if fixture_path is None and not prefer_network:
        mini = Path(__file__).resolve().parents[1] / "fixtures_min" / "text"
        for ext in (".txt", ".md", ".html", ".pdf"):
            candidate = mini / f"{source_id}{ext}"
            if candidate.exists():
                fixture_path = candidate
                break

    try:
        acq = acquire_source(source_id, fixture_path=fixture_path, force=force)
    except Exception as exc:
        if prefer_network and fixture_path is None:
            # Last resort: mini fixture for resilience, tagged as degraded.
            mini = Path(__file__).resolve().parents[1] / "fixtures_min" / "text"
            for ext in (".txt", ".md", ".html", ".pdf"):
                candidate = mini / f"{source_id}{ext}"
                if candidate.exists():
                    fixture_path = candidate
                    break
            if fixture_path is not None:
                acq = acquire_source(source_id, fixture_path=fixture_path, force=force)
                acq["warnings"] = list(acq.get("warnings") or []) + [
                    f"network_acquire_failed_fallback_mini:{exc}"
                ]
            else:
                raise RuntimeError(f"acquire failed for {source_id}: {exc}") from exc
        else:
            raise RuntimeError(f"acquire failed for {source_id}: {exc}") from exc

    path = Path(acq["path"])
    data = path.read_bytes()
    checksum = acq["content_checksum"]

    # Infer filename for parser from fixture/original suffix / magic bytes.
    if fixture_path is not None:
        filename = f"{source_id}{fixture_path.suffix or '.txt'}"
    else:
        url = (acq.get("resolved_download_url") or "").lower()
        ctype = (acq.get("content_type") or "").lower()
        if data[:4] == b"%PDF" or "pdf" in ctype or url.endswith(".pdf"):
            filename = f"{source_id}.pdf"
        elif b"<html" in data[:800].lower() or "html" in ctype or url.endswith((".html", ".htm")):
            filename = f"{source_id}.html"
        else:
            filename = f"{source_id}.txt"

    # Normalize HTML to text units + section chunks.
    if filename.endswith(".html") or b"<html" in data[:500].lower():
        text = data.decode("utf-8", errors="replace")
        text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
        text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
        text = re.sub(r"(?is)<[^>]+>", "\n", text)
        text = _canon_text(text)
        units = _section_chunks(text)
    else:
        parsed = parse_bytes(data, filename)
        units = []
        for u in parsed:
            units.extend(_section_chunks(u.text, page=u.page))

    document_id = _doc_id(source_id, checksum)
    existing = session.get(Document, document_id)
    if existing and not force:
        return {
            "source_id": source_id,
            "document_id": document_id,
            "chunk_count": existing.chunk_count,
            "status": "idempotent_skip",
        }

    # Drop prior embeddings for this source_id under the release (e.g. mini → full).
    if force:
        prior = session.execute(
            select(Document).where(
                Document.tenant_id == PLATFORM_TENANT_ID,
                Document.project_id == project_id,
            )
        ).scalars().all()
        for doc in prior:
            meta_doc = doc.meta or {}
            if meta_doc.get("release_id") == RELEASE_ID and meta_doc.get("source_id") == source_id:
                session.delete(doc)
        session.flush()
    elif existing:
        session.delete(existing)
        session.flush()

    lineage = {
        "release_id": RELEASE_ID,
        "rag_pack_id": RAG_PACK_ID,
        "collection_id": COLLECTION_ID,
        "source_id": source_id,
        "source_name": meta.get("source_name"),
        "publisher": meta.get("publisher"),
        "jurisdiction": meta.get("jurisdiction"),
        "authority_level": meta.get("authority_level"),
        "source_class": meta.get("source_class"),
        "edition": meta.get("edition"),
        "knowledge_layer": "platform_prebuilt",
        "content_checksum": checksum,
        "not_universal_law": meta.get("not_universal_law"),
        "advisory_only": meta.get("advisory_only"),
        "doc_role": {
            "fda_food_code_2022": "food_safety",
            "osha_retail_grocery_2009": "worker_safety",
            "ftc_advertising_faqs": "advertising_guidance",
        }.get(source_id, "official_guidance"),
    }

    embedder = get_embedder()
    texts = [u.text for u in units]
    vectors = embedder.embed_batch(texts) if texts else []

    doc = Document(
        id=document_id,
        tenant_id=PLATFORM_TENANT_ID,
        project_id=project_id,
        filename=filename,
        content_type=acq.get("content_type") or "application/octet-stream",
        source_uri=acq.get("resolved_download_url"),
        status="processed",
        page_count=max((u.page or 0) for u in units) if units else None,
        chunk_count=len(units),
        meta=lineage,
    )
    session.add(doc)
    for i, (unit, vector) in enumerate(zip(units, vectors)):
        session.add(
            DocumentChunk(
                id=_chunk_id(document_id, i, unit.text),
                tenant_id=PLATFORM_TENANT_ID,
                project_id=project_id,
                document_id=document_id,
                chunk_ordinal=i,
                text=unit.text,
                embedding=vector,
                source_filename=filename,
                page=unit.page,
                meta={
                    **lineage,
                    "section": unit.text.split("\n", 1)[0][:120],
                    "embedding_model": getattr(embedder, "model_name", None)
                    or embedder.__class__.__name__,
                    "embedding_dimension": embedder.dim,
                },
            )
        )
    session.flush()

    # Governance row
    pk = "r_" + hashlib.sha256(f"{RELEASE_ID}|{source_id}|src".encode()).hexdigest()[:24]
    src_row = session.get(RetailPackSource, pk)
    payload = dict(
        id=pk,
        release_id=RELEASE_ID,
        source_id=source_id,
        rag_pack_id=RAG_PACK_ID,
        collection_id=COLLECTION_ID,
        knowledge_layer="platform_prebuilt",
        source_name=str(meta.get("source_name")),
        source_class=str(meta.get("source_class")),
        authority_level=str(meta.get("authority_level")),
        licence=meta.get("licence"),
        publisher=meta.get("publisher"),
        content_checksum=checksum,
        resolved_download_url=acq.get("resolved_download_url"),
        acquisition_record=acq,
        document_count=1,
        chunk_count=len(units),
        status="ingested",
    )
    if src_row:
        for k, v in payload.items():
            setattr(src_row, k, v)
    else:
        session.add(RetailPackSource(**payload))
    session.flush()
    return {
        "source_id": source_id,
        "document_id": document_id,
        "chunk_count": len(units),
        "status": "ingested",
        "project_id": project_id,
    }


def ingest_all_text(
    session: Session,
    *,
    fixture_map: Optional[Dict[str, Path]] = None,
    force: bool = False,
    prefer_network: bool = False,
) -> List[Dict[str, Any]]:
    out = []
    for sid in ("fda_food_code_2022", "osha_retail_grocery_2009", "ftc_advertising_faqs"):
        fp = (fixture_map or {}).get(sid)
        out.append(
            ingest_text_source(
                session,
                sid,
                fixture_path=fp,
                force=force,
                prefer_network=prefer_network and fp is None,
            )
        )
    return out
