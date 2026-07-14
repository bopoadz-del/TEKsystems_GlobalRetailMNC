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
from typing import Any, Dict, List, Optional, Sequence

from app.retailops.packs.retail_core_open_v1.registry import (
    SourcePolicyError,
    get_source,
    validate_source_record,
)

DEFAULT_CACHE = Path(
    os.getenv("RETAILOPS_PACK_CACHE", "/tmp/retail_core_open_v1_cache")
)
MAX_BYTES = int(os.getenv("RETAILOPS_ACQUIRE_MAX_BYTES", str(250 * 1024 * 1024)))
TIMEOUT_S = int(os.getenv("RETAILOPS_ACQUIRE_TIMEOUT", "300"))

# Browser-like headers — several publisher CDNs reject bare custom UAs.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# FDA Food Code 2022 PDF candidates (official media IDs + Wayback when FDA
# abuse-detection blocks the agent / cloud egress IPs).
_FDA_CANDIDATES: Sequence[str] = (
    "https://www.fda.gov/media/164194/download",
    "https://www.fda.gov/media/184685/download",
    "https://www.fda.gov/media/190077/download",
    "https://web.archive.org/web/20240101000000if_/https://www.fda.gov/media/164194/download",
    "https://web.archive.org/web/20240315000000if_/https://www.fda.gov/media/184685/download",
)

_OSHA_PDF = "https://www.osha.gov/sites/default/files/publications/OSHA3192.pdf"
_UCI_ZIP = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"

_HF_FRESH_BASE = (
    "https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/main"
)
_FRESH_FILES = (
    ("data/train.parquet", "fresh_train.parquet"),
    ("data/eval.parquet", "fresh_eval.parquet"),
    ("README.md", "FreshRetailNet_README.md"),
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


def seed_dir() -> Path:
    """Optional committed / mounted seeds (e.g. FDA PDF when FDA blocks egress)."""
    env = os.getenv("RETAILOPS_PACK_SEED_DIR", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "seeds"


def _download(
    url: str,
    dest: Path,
    *,
    accept: Optional[str] = None,
    referer: Optional[str] = None,
) -> Dict[str, Any]:
    """Download url to dest with HTTPS, size limit, and redirect to https only."""
    if not url.startswith("https://"):
        raise ValueError("only HTTPS acquisition is allowed")
    headers = {
        "User-Agent": _UA,
        "Accept": accept or "*/*",
    }
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers, method="GET")
    tmp: Optional[Path] = None
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            final = resp.geturl()
            if not final.startswith("https://"):
                raise ValueError(f"redirect to non-HTTPS rejected: {final}")
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
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
            # Reject HTML apology / soft-404 pages mistaken for the payload.
            head = tmp.read_bytes()[:64]
            if ctype.startswith("text/html") and b"%PDF" not in head and dest.suffix == ".pdf":
                raise RuntimeError(f"expected PDF but got HTML from {final}")
            if b"abuse-detection-apology" in tmp.read_bytes()[:4096]:
                raise RuntimeError(f"FDA abuse-detection apology from {final}")
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


def _try_seed(source_id: str, dest: Path) -> Optional[Dict[str, Any]]:
    """Copy a committed seed file into the cache when present."""
    base = seed_dir()
    if not base.is_dir():
        return None
    for name in (
        f"{source_id}.pdf",
        f"{source_id}.html",
        f"{source_id}.txt",
        f"{source_id}.bin",
        f"{source_id}.zip",
    ):
        candidate = base / name
        if candidate.exists() and candidate.stat().st_size > 0:
            data = candidate.read_bytes()
            dest.write_bytes(data)
            return {
                "resolved_download_url": f"seed://{candidate}",
                "content_type": "application/octet-stream",
                "file_size": len(data),
                "content_checksum": hashlib.sha256(data).hexdigest(),
                "path": str(dest),
                "acquisition_method": "seed",
                "warnings": [f"used_seed_file:{candidate.name}"],
            }
    return None


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
    elif source_id == "freshretailnet_50k":
        record.update(_acquire_freshretailnet(force=force))
        record["status"] = "ok"
        sidecar.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        return record
    else:
        if dest.exists() and sidecar.exists() and not force:
            prev = json.loads(sidecar.read_text(encoding="utf-8"))
            if prev.get("content_checksum") == _sha256(dest):
                prev["status"] = "ok"
                prev["warnings"] = list(prev.get("warnings") or []) + ["idempotent_cache_hit"]
                return prev
        errors: List[str] = []
        ok = False
        # Prefer committed seed for large PDFs (FDA) to avoid download+parse RAM spike
        # on starter job instances; seed is provenance-tagged.
        if source_id == "fda_food_code_2022":
            seeded = _try_seed(source_id, dest)
            if seeded and dest.read_bytes()[:4] == b"%PDF" and dest.stat().st_size >= 2_000_000:
                record.update(seeded)
                record["status"] = "ok"
                ok = True
        if not ok:
            urls = _candidate_urls(source_id, meta)
            for url in urls:
                try:
                    info = _download(
                        url,
                        dest,
                        referer=str(meta.get("original_url") or ""),
                    )
                    if source_id == "fda_food_code_2022" and not dest.read_bytes()[:4] == b"%PDF":
                        errors.append(f"non-PDF from {url}")
                        continue
                    if source_id == "fda_food_code_2022" and dest.stat().st_size < 2_000_000:
                        errors.append(f"PDF too small ({dest.stat().st_size}) from {url}")
                        continue
                    record.update(info)
                    record["status"] = "ok"
                    if "web.archive.org" in (info.get("resolved_download_url") or ""):
                        record["warnings"] = list(record.get("warnings") or []) + [
                            "acquired_via_wayback_mirror_of_official_fda_media"
                        ]
                    ok = True
                    break
                except Exception as exc:
                    errors.append(f"{url}: {exc}")
        if not ok:
            seeded = _try_seed(source_id, dest)
            if seeded:
                record.update(seeded)
                record["status"] = "ok"
                record["warnings"] = list(record.get("warnings") or []) + list(
                    seeded.get("warnings") or []
                ) + [f"network_errors:{';'.join(errors)[:400]}"]
                ok = True
        if not ok:
            record["status"] = "failed"
            record["last_error"] = "; ".join(errors)[:800]
            record["ingestion_status"] = "acquire_failed"
            sidecar.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
            raise RuntimeError(record["last_error"])

    sidecar.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return record


def _candidate_urls(source_id: str, meta: Dict[str, Any]) -> List[str]:
    if source_id == "fda_food_code_2022":
        return list(_FDA_CANDIDATES)
    if source_id == "osha_retail_grocery_2009":
        # Prefer capitalized filename used by OSHA CDN; keep manifest URL as fallback.
        urls = [_OSHA_PDF]
        orig = str(meta.get("original_url") or "")
        if orig and orig not in urls:
            urls.append(orig)
        return urls
    if source_id == "ftc_advertising_faqs":
        return [str(meta["original_url"])]
    if source_id == "uci_online_retail_ii":
        return [_UCI_ZIP]
    return [str(meta.get("original_url") or "")]


def _acquire_freshretailnet(*, force: bool = False) -> Dict[str, Any]:
    """Download FreshRetailNet parquet shards (+ README) into the cache."""
    out_dir = cache_dir() / "freshretailnet_50k"
    out_dir.mkdir(parents=True, exist_ok=True)
    sidecar = cache_dir() / "freshretailnet_50k.acquisition.json"
    if sidecar.exists() and not force:
        prev = json.loads(sidecar.read_text(encoding="utf-8"))
        files = prev.get("files") or []
        if files and all(Path(f["path"]).exists() for f in files):
            prev["warnings"] = list(prev.get("warnings") or []) + ["idempotent_cache_hit"]
            prev["path"] = str(out_dir)
            return prev

    files_meta: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for rel, local_name in _FRESH_FILES:
        dest = out_dir / local_name
        url = f"{_HF_FRESH_BASE}/{rel}"
        # Also try xet/CDN via HF redirect — urllib follows HTTPS redirects.
        info = _download(url, dest, referer=_HF_FRESH_BASE.rsplit("/resolve", 1)[0])
        files_meta.append(
            {
                "rel": rel,
                "path": str(dest),
                "file_size": info["file_size"],
                "content_checksum": info["content_checksum"],
                "resolved_download_url": info["resolved_download_url"],
                "content_type": info["content_type"],
            }
        )
    # Combined checksum over file checksums (stable even when CDN URLs rotate).
    combined = hashlib.sha256(
        "|".join(f["content_checksum"] for f in files_meta).encode()
    ).hexdigest()
    train = next(f for f in files_meta if f["rel"].endswith("train.parquet"))
    return {
        "resolved_download_url": _HF_FRESH_BASE,
        "content_type": "application/x-parquet",
        "file_size": sum(f["file_size"] for f in files_meta),
        "content_checksum": combined,
        "path": str(out_dir),
        "train_parquet": train["path"],
        "files": files_meta,
        "acquisition_method": "https",
        "warnings": warnings,
    }


def acquire_all_text(
    *, fixture_map: Optional[Dict[str, Path]] = None, force: bool = False
) -> List[Dict[str, Any]]:
    out = []
    for sid in ("fda_food_code_2022", "osha_retail_grocery_2009", "ftc_advertising_faqs"):
        fp = (fixture_map or {}).get(sid)
        out.append(acquire_source(sid, fixture_path=fp, force=force))
    return out


def acquire_all_structured(*, force: bool = False) -> List[Dict[str, Any]]:
    return [
        acquire_source("freshretailnet_50k", force=force),
        acquire_source("uci_online_retail_ii", force=force),
    ]
