"""Acquire + ingest SOPBench sop.txt documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.retailops.packs import hf_common
from app.retailops.packs.retail_ops_sops_v1 import (
    COLLECTION_ID,
    DOMAINS,
    HF_REPO,
    LICENCE,
    PUBLISHER,
    RAG_PACK_ID,
    RELEASE_ID,
    SOURCE_ID,
)

PACK_ROOT = Path(__file__).resolve().parents[1]
MINI_PATH = PACK_ROOT / "fixtures_min" / "sample.jsonl"


def acquire_full(cache: Optional[Path] = None) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cache = cache or hf_common.cache_dir()
    records: List[Dict[str, Any]] = []
    urls: List[str] = []
    for domain in DOMAINS:
        rel = f"data/{domain}/sop.txt"
        dest = cache / "sopbench" / domain / "sop.txt"
        url = hf_common.hf_resolve_url(HF_REPO, rel)
        acq = hf_common.download_https(url, dest)
        urls.append(acq["resolved_download_url"])
        text = dest.read_text(encoding="utf-8", errors="replace")
        records.append(
            {
                "title": f"SOPBench SOP — {domain.replace('_', ' ')}",
                "text": text,
                "meta": {
                    "sop_domain": domain,
                    "hf_repo": HF_REPO,
                    "source_uri": f"hf://{HF_REPO}/{rel}",
                },
            }
        )
    return records, {
        "profile_note": "hf_full_sop_txt",
        "resolved_download_url": urls[0] if urls else None,
        "downloaded_urls": urls,
        "content_checksum": hf_common.sha256_text("|".join(r["text"] for r in records)),
    }


def load_records(*, profile: str = "mini") -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if profile == "mini":
        rows = hf_common.read_jsonl(MINI_PATH)
        return rows, {
            "profile_note": "committed_mini_fixture",
            "resolved_download_url": f"seed://{MINI_PATH}",
            "content_checksum": hf_common.sha256_file(MINI_PATH),
        }
    return acquire_full()


def load_pack(session, *, profile: str = "mini", force: bool = False) -> Dict[str, Any]:
    records, acq = load_records(profile=profile)
    return hf_common.ingest_text_documents(
        session,
        release_id=RELEASE_ID,
        rag_pack_id=RAG_PACK_ID,
        collection_id=COLLECTION_ID,
        source_id=SOURCE_ID,
        source_name="SOPBench operational SOPs",
        licence=LICENCE,
        publisher=PUBLISHER,
        records=records,
        force=force,
        acquisition=acq,
    )
