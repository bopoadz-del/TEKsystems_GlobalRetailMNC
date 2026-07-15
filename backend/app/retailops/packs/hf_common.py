"""Shared helpers for Hugging Face retail RAG content packs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
TIMEOUT_S = int(os.getenv("RETAILOPS_ACQUIRE_TIMEOUT", "300"))
MAX_BYTES = int(os.getenv("RETAILOPS_ACQUIRE_MAX_BYTES", str(250 * 1024 * 1024)))
DEFAULT_CACHE = Path(os.getenv("RETAILOPS_PACK_CACHE", "/tmp/retailops_hf_packs_cache"))

CHUNK_SIZE = 900
CHUNK_OVERLAP = 120


def cache_dir() -> Path:
    DEFAULT_CACHE.mkdir(parents=True, exist_ok=True)
    return DEFAULT_CACHE


def hf_resolve_url(repo: str, path: str) -> str:
    return f"https://huggingface.co/datasets/{repo}/resolve/main/{path}"


def download_https(url: str, dest: Path) -> Dict[str, Any]:
    if not url.startswith("https://"):
        raise ValueError("only HTTPS acquisition is allowed")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Accept": "*/*"},
        method="GET",
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="hf_pack_", dir=str(cache_dir()))
    os.close(fd)
    tmp = Path(name)
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            final = resp.geturl()
            if not final.startswith("https://"):
                raise ValueError(f"redirect to non-HTTPS rejected: {final}")
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            with open(tmp, "wb") as out:
                while True:
                    block = resp.read(1024 * 256)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_BYTES:
                        raise ValueError(f"download exceeds size limit ({MAX_BYTES})")
                    out.write(block)
        tmp.replace(dest)
        checksum = sha256_file(dest)
        return {
            "resolved_download_url": final,
            "content_type": ctype,
            "file_size": total,
            "content_checksum": checksum,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "path": str(dest),
        }
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canon_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _window_chunks(text: str) -> List[str]:
    text = _canon_text(text)
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]
    out: List[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        chunk = text[start:end].strip()
        if len(chunk) >= 40:
            out.append(chunk)
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return out


def _doc_id(release_id: str, source_id: str, checksum: str) -> str:
    return "doc_" + hashlib.sha256(f"{release_id}|{source_id}|{checksum}".encode()).hexdigest()[:20]


def _chunk_id(document_id: str, ordinal: int, text: str) -> str:
    return "ch_" + hashlib.sha256(f"{document_id}|{ordinal}|{text[:200]}".encode()).hexdigest()[:24]


def upsert_pack_source(
    session,
    *,
    release_id: str,
    source_id: str,
    rag_pack_id: str,
    collection_id: str,
    source_name: str,
    licence: Optional[str],
    publisher: Optional[str],
    content_checksum: str,
    resolved_url: Optional[str],
    acquisition: Dict[str, Any],
    document_count: int,
    chunk_count: int,
    status: str = "ingested",
) -> None:
    from app.retailops.models import RetailPackSource

    pk = "r_" + hashlib.sha256(f"{release_id}|{source_id}|src".encode()).hexdigest()[:24]
    payload = dict(
        id=pk,
        release_id=release_id,
        source_id=source_id,
        rag_pack_id=rag_pack_id,
        collection_id=collection_id,
        knowledge_layer="platform_prebuilt",
        source_name=source_name,
        source_class="open_license",
        authority_level="public_research_dataset",
        licence=licence,
        publisher=publisher,
        content_checksum=content_checksum,
        resolved_download_url=resolved_url,
        acquisition_record=acquisition,
        document_count=document_count,
        chunk_count=chunk_count,
        status=status,
    )
    row = session.get(RetailPackSource, pk)
    if row:
        for k, v in payload.items():
            setattr(row, k, v)
    else:
        session.add(RetailPackSource(**payload))


def ingest_text_documents(
    session,
    *,
    release_id: str,
    rag_pack_id: str,
    collection_id: str,
    source_id: str,
    source_name: str,
    licence: Optional[str],
    publisher: Optional[str],
    records: Sequence[Dict[str, Any]],
    force: bool = False,
    acquisition: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Ingest a list of {title, text, meta?} records into the platform corpus."""
    from sqlalchemy import select

    from app.retailops.embeddings import get_embedder
    from app.retailops.models import Document, DocumentChunk
    from app.retailops.packs.retail_core_open_v1 import (
        PLATFORM_PROJECT_CANONICAL,
        PLATFORM_TENANT_ID,
    )
    from app.retailops.packs.retail_core_open_v1.loaders.ingest_text import (
        ensure_platform_project,
    )

    project_id = ensure_platform_project(session)
    embedder = get_embedder()
    embedding_model = getattr(embedder, "model_name", None) or embedder.__class__.__name__
    batch_size = min(int(getattr(embedder, "batch_size", 32) or 32), 32)

    if force:
        prior = session.execute(
            select(Document).where(
                Document.tenant_id == PLATFORM_TENANT_ID,
                Document.project_id == project_id,
            )
        ).scalars().all()
        for doc in prior:
            meta_doc = doc.meta or {}
            if meta_doc.get("release_id") == release_id and meta_doc.get("source_id") == source_id:
                session.delete(doc)
        session.flush()

    docs_added = 0
    chunks_added = 0
    corpus_hash = hashlib.sha256()

    for rec in records:
        title = str(rec.get("title") or source_id).strip()
        body = _canon_text(str(rec.get("text") or ""))
        if len(body) < 40:
            continue
        combined = f"{title}\n\n{body}" if title else body
        checksum = sha256_text(combined)
        corpus_hash.update(checksum.encode())
        document_id = _doc_id(release_id, f"{source_id}:{checksum[:12]}", checksum)
        existing = session.get(Document, document_id)
        if existing and not force:
            docs_added += 1
            chunks_added += int(existing.chunk_count or 0)
            continue
        if existing:
            session.delete(existing)
            session.flush()

        extra_meta = dict(rec.get("meta") or {})
        lineage = {
            "release_id": release_id,
            "rag_pack_id": rag_pack_id,
            "collection_id": collection_id,
            "source_id": source_id,
            "source_name": source_name,
            "knowledge_layer": "platform_prebuilt",
            "content_checksum": checksum,
            "embedding_model": embedding_model,
            **extra_meta,
        }
        filename = f"{source_id}_{checksum[:8]}.txt"
        doc = Document(
            id=document_id,
            tenant_id=PLATFORM_TENANT_ID,
            project_id=project_id,
            filename=filename,
            content_type="text/plain",
            source_uri=extra_meta.get("source_uri") or f"hf://{release_id}/{source_id}",
            status="processing",
            page_count=None,
            chunk_count=0,
            meta=lineage,
        )
        session.add(doc)
        session.flush()

        units = _window_chunks(combined)
        pending_texts: List[str] = []
        pending_meta: List[Dict[str, Any]] = []
        ordinal = 0

        def _flush() -> None:
            nonlocal pending_texts, pending_meta, ordinal, chunks_added
            if not pending_texts:
                return
            vectors = embedder.embed_batch(pending_texts)
            for text, vector, umeta in zip(pending_texts, vectors, pending_meta):
                session.add(
                    DocumentChunk(
                        id=_chunk_id(document_id, ordinal, text),
                        tenant_id=PLATFORM_TENANT_ID,
                        project_id=project_id,
                        document_id=document_id,
                        chunk_ordinal=ordinal,
                        text=text,
                        embedding=vector,
                        source_filename=filename,
                        page=None,
                        meta={
                            **lineage,
                            **umeta,
                            "section": text.split("\n", 1)[0][:120],
                            "embedding_dimension": embedder.dim,
                        },
                    )
                )
                ordinal += 1
                chunks_added += 1
            pending_texts = []
            pending_meta = []
            session.flush()
            session.expire_all()

        for unit in units:
            pending_texts.append(unit)
            pending_meta.append({})
            if len(pending_texts) >= batch_size:
                _flush()
        _flush()
        doc = session.get(Document, document_id)
        if doc:
            doc.status = "processed"
            doc.chunk_count = ordinal
            doc.meta = {**(doc.meta or {}), **lineage}
        docs_added += 1

    acq = dict(acquisition or {})
    acq.update(
        {
            "embedding_model": embedding_model,
            "embedding_dimension": embedder.dim,
            "record_count": len(records),
            "profile_note": acq.get("profile_note"),
        }
    )
    content_checksum = corpus_hash.hexdigest()
    upsert_pack_source(
        session,
        release_id=release_id,
        source_id=source_id,
        rag_pack_id=rag_pack_id,
        collection_id=collection_id,
        source_name=source_name,
        licence=licence,
        publisher=publisher,
        content_checksum=content_checksum,
        resolved_url=acq.get("resolved_download_url"),
        acquisition=acq,
        document_count=docs_added,
        chunk_count=chunks_added,
    )
    session.flush()
    return {
        "source_id": source_id,
        "document_count": docs_added,
        "chunk_count": chunks_added,
        "project_id": project_id,
        "status": "ingested",
        "embedding_model": embedding_model,
        "tenant_id": PLATFORM_TENANT_ID,
        "canonical_project": PLATFORM_PROJECT_CANONICAL,
    }


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
