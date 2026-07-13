"""HTTPS acquisition with checksums, size limits, and policy gates."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.retailops.packs.retail_core_open_v1.registry import (
    SourcePolicyError,
    get_source,
    validate_source_record,
)

DEFAULT_CACHE = Path(
    os.getenv("RETAILOPS_PACK_CACHE", "/tmp/retail_core_open_v1_cache")
)
MAX_BYTES = int(os.getenv("RETAILOPS_ACQUIRE_MAX_BYTES", str(200 * 1024 * 1024)))
TIMEOUT_S = int(os.getenv("RETAILOPS_ACQUIRE_TIMEOUT", "120"))

# FDA Food Code 2022 full PDF (official FDA media).
_FDA_PDF = "https://www.fda.gov/media/164194/download"
# UCI Online Retail II Excel (CC BY 4.0).
_UCI_XLSX = (
    "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_dir() -> Path:
    DEFAULT_CACHE.mkdir(parents=True, exist_ok=True)
    return DEFAULT_CACHE


def _download(url: str, dest: Path, *, accept: Optional[str] = None) -> Dict[str, Any]:
    """Download url to dest with HTTPS, size limit, and redirect to https only."""
    if not url.startswith("https://"):
        raise ValueError("only HTTPS acquisition is allowed")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "RetailOps-retail_core_open_v1/1.0",
            **({"Accept": accept} if accept else {}),
        },
        method="GET",
    )
    tmp: Optional[Path] = None
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            final = resp.geturl()
            if not final.startswith("https://"):
                raise ValueError(f"redirect to non-HTTPS rejected: {final}")
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            # Stream to tempfile then rename.
            fd, name = tempfile.mkstemp(prefix="acquire_", dir=str(cache_dir()))
            os.close(fd)
            tmp = Path(name)
            total = 0
            with open(tmp, "wb") as out:
                while True:
                    block = resp.read(1024 * 256)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_BYTES:
                        raise ValueError(f"download exceeds size limit ({MAX_BYTES})")
                    out.write(block)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp.replace(dest)
            return {
                "resolved_download_url": final,
                "content_type": ctype,
                "file_size": total,
                "content_checksum": _sha256(dest),
                "path": str(dest),
            }
    except urllib.error.HTTPError as exc:
        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)
        raise RuntimeError(f"HTTP {exc.code} acquiring {url}") from None
    except Exception:
        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def acquire_source(
    source_id: str,
    *,
    fixture_path: Optional[Path] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Acquire one approved source; return acquisition record.

    When ``fixture_path`` is set (tests / offline), use that file instead of
    network download and still run policy validation.
    """
    meta = get_source(source_id)
    if not meta:
        raise SourcePolicyError(f"unknown source_id: {source_id}")

    record: Dict[str, Any] = {
        **{k: meta.get(k) for k in meta},
        "release_id": "retail_core_open_v1",
        "rag_pack_id": "retail_core_rag",
        "collection_id": "prebuilt_retail_core",
        "domain": "retail",
        "knowledge_layer": "platform_prebuilt"
        if meta.get("structured_or_text") == "text"
        else "structured_public_eval",
        "acquired_at": _utcnow(),
        "acquisition_method": "fixture" if fixture_path else "https",
        "ingestion_status": "acquired",
        "warnings": [],
        "last_error": None,
    }
    validate_source_record(record)

    dest = cache_dir() / f"{source_id}.bin"
    sidecar = cache_dir() / f"{source_id}.acquisition.json"

    if fixture_path is not None:
        data = Path(fixture_path).read_bytes()
        dest.write_bytes(data)
        record.update(
            {
                "resolved_download_url": f"fixture://{fixture_path}",
                "content_type": "application/octet-stream",
                "file_size": len(data),
                "content_checksum": hashlib.sha256(data).hexdigest(),
                "path": str(dest),
                "status": "ok",
            }
        )
    else:
        url = _resolve_download_url(source_id, meta)
        if dest.exists() and sidecar.exists() and not force:
            prev = json.loads(sidecar.read_text(encoding="utf-8"))
            if prev.get("content_checksum") == _sha256(dest):
                prev["status"] = "ok"
                prev["warnings"] = list(prev.get("warnings") or []) + ["idempotent_cache_hit"]
                return prev
        try:
            info = _download(url, dest)
            record.update(info)
            record["status"] = "ok"
        except Exception as exc:
            record["status"] = "failed"
            record["last_error"] = str(exc)[:500]
            record["ingestion_status"] = "acquire_failed"
            sidecar.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
            raise

    sidecar.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return record


def _resolve_download_url(source_id: str, meta: Dict[str, Any]) -> str:
    if source_id == "fda_food_code_2022":
        return _FDA_PDF
    if source_id == "osha_retail_grocery_2009":
        return str(meta["original_url"])
    if source_id == "ftc_advertising_faqs":
        return str(meta["original_url"])
    if source_id == "uci_online_retail_ii":
        return _UCI_XLSX
    if source_id == "freshretailnet_50k":
        # Prefer parquet shard via HF resolve URL for pilot; full dataset later.
        return (
            "https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K"
            "/resolve/main/README.md"
        )
    return str(meta.get("original_url"))


def acquire_all_text(
    *, fixture_map: Optional[Dict[str, Path]] = None, force: bool = False
) -> List[Dict[str, Any]]:
    out = []
    for sid in ("fda_food_code_2022", "osha_retail_grocery_2009", "ftc_advertising_faqs"):
        fp = (fixture_map or {}).get(sid)
        out.append(acquire_source(sid, fixture_path=fp, force=force))
    return out
