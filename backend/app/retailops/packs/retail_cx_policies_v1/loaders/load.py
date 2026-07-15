"""Acquire + ingest Bitext retail CX responses as RAG documents."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.retailops.packs import hf_common
from app.retailops.packs.retail_cx_policies_v1 import (
    COLLECTION_ID,
    HF_FILE,
    HF_REPO,
    LICENCE,
    MAX_SAMPLE_ROWS,
    PUBLISHER,
    RAG_PACK_ID,
    RELEASE_ID,
    SAMPLE_PER_INTENT,
    SOURCE_ID,
)

PACK_ROOT = Path(__file__).resolve().parents[1]
MINI_PATH = PACK_ROOT / "fixtures_min" / "sample.jsonl"


def _records_from_csv_text(text: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    by_intent: dict[str, list[Dict[str, Any]]] = defaultdict(list)
    for row in reader:
        intent = (row.get("intent") or "unknown").strip()
        category = (row.get("category") or "").strip()
        instruction = (row.get("instruction") or "").strip()
        response = (row.get("response") or "").strip()
        if len(response) < 40:
            continue
        if len(by_intent[intent]) >= SAMPLE_PER_INTENT:
            continue
        by_intent[intent].append(
            {
                "title": instruction or f"{category}/{intent}",
                "text": response,
                "meta": {
                    "category": category,
                    "intent": intent,
                    "hf_repo": HF_REPO,
                    "source_uri": f"hf://{HF_REPO}/{HF_FILE}",
                },
            }
        )
    out: List[Dict[str, Any]] = []
    for items in by_intent.values():
        out.extend(items)
        if len(out) >= MAX_SAMPLE_ROWS:
            return out[:MAX_SAMPLE_ROWS]
    return out[:MAX_SAMPLE_ROWS]


def acquire_full(cache: Optional[Path] = None) -> Dict[str, Any]:
    dest = (cache or hf_common.cache_dir()) / "bitext_retail_cx.csv"
    url = hf_common.hf_resolve_url(HF_REPO, HF_FILE)
    return hf_common.download_https(url, dest)


def load_records(*, profile: str = "mini") -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if profile == "mini":
        rows = hf_common.read_jsonl(MINI_PATH)
        return rows, {
            "profile_note": "committed_mini_fixture",
            "resolved_download_url": f"seed://{MINI_PATH}",
            "content_checksum": hf_common.sha256_file(MINI_PATH),
        }
    acq = acquire_full()
    text = Path(acq["path"]).read_text(encoding="utf-8", errors="replace")
    return _records_from_csv_text(text), {**acq, "profile_note": "hf_full_sample"}


def load_pack(session, *, profile: str = "mini", force: bool = False) -> Dict[str, Any]:
    records, acq = load_records(profile=profile)
    return hf_common.ingest_text_documents(
        session,
        release_id=RELEASE_ID,
        rag_pack_id=RAG_PACK_ID,
        collection_id=COLLECTION_ID,
        source_id=SOURCE_ID,
        source_name="Bitext Retail eCommerce CX",
        licence=LICENCE,
        publisher=PUBLISHER,
        records=records,
        force=force,
        acquisition=acq,
    )
