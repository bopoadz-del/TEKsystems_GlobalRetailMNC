"""Load rescommons group-B as eval fixtures + selective RAG ingest."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.retailops.packs import hf_common
from app.retailops.packs.retail_ecom_rag_eval_v1 import (
    COLLECTION_ID,
    HF_FILE,
    HF_REPO,
    LICENCE,
    MAX_EVAL_CASES,
    MAX_INGEST_DOCS,
    PUBLISHER,
    RAG_PACK_ID,
    RELEASE_ID,
    SOURCE_ID,
)

PACK_ROOT = Path(__file__).resolve().parents[1]
MINI_EVAL = PACK_ROOT / "fixtures_min" / "eval_cases.jsonl"
MINI_DOCS = PACK_ROOT / "fixtures_min" / "sample_docs.jsonl"


def _get(row: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def _is_group_b(row: Dict[str, Any]) -> bool:
    g = _get(row, "group", "Group", "capability_group")
    if g is None:
        return False
    return str(g).strip().upper() in {"B", "RAG", "GROUP_B", "GROUP B"}


def rows_from_parquet(path: Path) -> List[Dict[str, Any]]:
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    return table.to_pylist()


def split_eval_and_docs(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    eval_cases: List[Dict[str, Any]] = []
    docs: List[Dict[str, Any]] = []
    for row in rows:
        if not _is_group_b(row):
            # Some bitext shards omit group but are still RAG-oriented retail ecom;
            # only accept those when prompt/response present and no tool_call exclusive.
            resp_type = str(_get(row, "response_type", "responseType") or "").lower()
            if resp_type == "tool_call":
                continue
            if _get(row, "group") is not None:
                continue
        prompt = str(_get(row, "prompt", "instruction", "question", "user") or "").strip()
        response = str(_get(row, "response", "answer", "assistant") or "").strip()
        if not prompt or len(response) < 20:
            continue
        context = _get(row, "context", "retrieved_docs", "documents", "rag_context", "evidence")
        context_text = ""
        if isinstance(context, list):
            parts = []
            for item in context:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or item))
                else:
                    parts.append(str(item))
            context_text = "\n".join(parts)
        elif isinstance(context, str):
            context_text = context
        intent = str(_get(row, "intent", "intent_category", "sub_intent") or "")
        if len(eval_cases) < MAX_EVAL_CASES:
            eval_cases.append(
                {
                    "question": prompt,
                    "expected_answer_contains": response[:180],
                    "intent": intent,
                    "grounding_hint": (context_text or response)[:400],
                    "source": HF_REPO,
                }
            )
        if context_text and len(context_text) >= 40 and len(docs) < MAX_INGEST_DOCS:
            docs.append(
                {
                    "title": f"Grounded snippet — {intent or 'rag'}",
                    "text": context_text,
                    "meta": {
                        "intent": intent,
                        "hf_repo": HF_REPO,
                        "role": "selective_grounding_snippet",
                        "source_uri": f"hf://{HF_REPO}/{HF_FILE}",
                    },
                }
            )
        elif len(response) >= 40 and len(docs) < MAX_INGEST_DOCS:
            # Fallback: policy-like assistant response as document (Bitext-origin rows).
            docs.append(
                {
                    "title": prompt[:120] or "Retail support guidance",
                    "text": response,
                    "meta": {
                        "intent": intent,
                        "hf_repo": HF_REPO,
                        "role": "selective_response_snippet",
                        "source_uri": f"hf://{HF_REPO}/{HF_FILE}",
                    },
                }
            )
        if len(eval_cases) >= MAX_EVAL_CASES and len(docs) >= MAX_INGEST_DOCS:
            break
    return eval_cases, docs


def acquire_full(cache: Optional[Path] = None) -> Dict[str, Any]:
    dest = (cache or hf_common.cache_dir()) / "rescommons_bitext_retail_ecom.parquet"
    url = hf_common.hf_resolve_url(HF_REPO, HF_FILE)
    return hf_common.download_https(url, dest)


def load_eval_and_docs(*, profile: str = "mini") -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    if profile == "mini":
        eval_cases = hf_common.read_jsonl(MINI_EVAL)
        docs = hf_common.read_jsonl(MINI_DOCS)
        return (
            eval_cases,
            docs,
            {
                "profile_note": "committed_mini_fixture",
                "resolved_download_url": f"seed://{MINI_EVAL}",
                "content_checksum": hf_common.sha256_file(MINI_EVAL),
            },
        )
    acq = acquire_full()
    rows = rows_from_parquet(Path(acq["path"]))
    eval_cases, docs = split_eval_and_docs(rows)
    # Persist eval cases beside cache for oracle scripts.
    out_eval = Path(acq["path"]).with_name("rescommons_eval_cases.jsonl")
    hf_common.write_jsonl(out_eval, eval_cases)
    acq = {**acq, "eval_cases_path": str(out_eval), "profile_note": "hf_full_sample"}
    return eval_cases, docs, acq


def load_pack(session, *, profile: str = "mini", force: bool = False) -> Dict[str, Any]:
    eval_cases, docs, acq = load_eval_and_docs(profile=profile)
    # Keep a copy of mini/updated eval fixtures in pack tree when mini.
    if profile == "mini":
        eval_path = str(MINI_EVAL)
    else:
        eval_path = acq.get("eval_cases_path")
    result = hf_common.ingest_text_documents(
        session,
        release_id=RELEASE_ID,
        rag_pack_id=RAG_PACK_ID,
        collection_id=COLLECTION_ID,
        source_id=SOURCE_ID,
        source_name="rescommons group-B selective RAG snippets",
        licence=LICENCE,
        publisher=PUBLISHER,
        records=docs,
        force=force,
        acquisition=acq,
    )
    result["eval_cases"] = len(eval_cases)
    result["eval_cases_path"] = eval_path
    return result


def load_eval_cases(*, profile: str = "mini") -> List[Dict[str, Any]]:
    cases, _, _ = load_eval_and_docs(profile=profile)
    return cases
