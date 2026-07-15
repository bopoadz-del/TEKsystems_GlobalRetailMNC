#!/usr/bin/env python3
"""Offline retrieval eval: lexical vs vector vs hybrid RRF on gold cases.

Uses the retail_ecom_rag_eval_v1 mini fixtures (eval_cases.jsonl + sample_docs.jsonl)
plus case grounding_hint text as a tiny closed corpus — no live Postgres required.
Writes ``docs/retrieval_eval_report.md`` and optional JSON artifact for CI.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "backend" / "app" / "retailops" / "packs" / "retail_ecom_rag_eval_v1" / "fixtures_min"
TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text.lower())


def load_corpus(cases_path: Path, docs_path: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    cases = [json.loads(l) for l in cases_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    docs: List[Dict[str, Any]] = []
    if docs_path.is_file():
        for line in docs_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            text = row.get("text") or row.get("content") or row.get("body") or ""
            docs.append({"id": row.get("id") or f"doc_{len(docs)}", "text": text, "meta": row})
    # Ensure every gold hint is retrievable even if sample_docs is thin.
    for i, case in enumerate(cases):
        hint = (case.get("grounding_hint") or "").strip()
        if hint:
            docs.append({"id": f"gold_hint_{i}", "text": hint, "meta": {"source": "grounding_hint"}})
    return cases, docs


def hash_embed(text: str, dim: int = 384) -> List[float]:
    import hashlib

    vec = [0.0] * dim
    tokens = tokenize(text)
    for tok in tokens:
        features = [tok]
        if len(tok) > 3:
            features.extend(tok[i : i + 3] for i in range(len(tok) - 2))
        for feat in features:
            h = int.from_bytes(hashlib.md5(feat.encode("utf-8")).digest()[:8], "little")
            idx = h % dim
            sign = 1.0 if (h >> 63) & 1 else -1.0
            vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def lexical_rank(query: str, docs: List[Dict[str, Any]], limit: int) -> List[Tuple[str, float]]:
    qtoks = set(tokenize(query))
    scored: List[Tuple[str, float]] = []
    for d in docs:
        dtoks = tokenize(d["text"])
        if not dtoks:
            continue
        overlap = sum(1 for t in dtoks if t in qtoks)
        # Simple TF overlap / length (BM25-ish proxy for offline).
        score = overlap / math.sqrt(len(dtoks))
        if score > 0:
            scored.append((d["id"], score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def vector_rank(query: str, docs: List[Dict[str, Any]], limit: int) -> List[Tuple[str, float]]:
    qv = hash_embed(query)
    scored = [(d["id"], cosine(qv, hash_embed(d["text"]))) for d in docs if d["text"]]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def rrf_fuse(lists: List[List[Tuple[str, float]]], k: int = 60, limit: int = 6) -> List[Tuple[str, float]]:
    fused: Dict[str, float] = defaultdict(float)
    for ranked in lists:
        for rank, (doc_id, _score) in enumerate(ranked, start=1):
            fused[doc_id] += 1.0 / (k + rank)
    ordered = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    return ordered[:limit]


def hit_at_k(ranked_ids: List[str], docs_by_id: Dict[str, Dict[str, Any]], needle: str, k: int) -> bool:
    needle_l = needle.lower()
    for doc_id in ranked_ids[:k]:
        text = docs_by_id[doc_id]["text"].lower()
        if needle_l in text:
            return True
    return False


def evaluate(cases: List[Dict[str, Any]], docs: List[Dict[str, Any]], top_k: int = 5) -> Dict[str, Any]:
    docs_by_id = {d["id"]: d for d in docs}
    modes = ("lexical", "vector", "hybrid")
    totals = {m: 0 for m in modes}
    per_case: List[Dict[str, Any]] = []

    for case in cases:
        q = case["question"]
        needle = case["expected_answer_contains"]
        lex = lexical_rank(q, docs, limit=20)
        vec = vector_rank(q, docs, limit=20)
        hyb = rrf_fuse([lex, vec], limit=top_k)
        row = {
            "question": q,
            "expected": needle,
            "intent": case.get("intent"),
            "hits": {},
        }
        for name, ranked in (
            ("lexical", lex),
            ("vector", vec),
            ("hybrid", hyb),
        ):
            ids = [i for i, _ in ranked]
            ok = hit_at_k(ids, docs_by_id, needle, top_k)
            row["hits"][name] = ok
            if ok:
                totals[name] += 1
        per_case.append(row)

    n = max(len(cases), 1)
    metrics = {m: round(totals[m] / n, 4) for m in modes}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus_size": len(docs),
        "case_count": len(cases),
        "top_k": top_k,
        "recall_at_k": metrics,
        "hits": totals,
        "cases": per_case,
        "notes": [
            "Offline closed corpus: sample_docs.jsonl + grounding_hint texts.",
            "Vector channel uses the same hash-v1 embedding space as RETAILOPS_EMBED_BACKEND=hash.",
            "Hybrid = RRF(k=60) over lexical overlap ranks and vector cosine ranks.",
            "Live FastEmbed/pgvector recall belongs in a post-ingest pack run; this report is CI-safe.",
        ],
    }


def render_markdown(report: Dict[str, Any]) -> str:
    m = report["recall_at_k"]
    lines = [
        "# Retrieval evaluation report",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Summary",
        "",
        f"- Corpus documents: **{report['corpus_size']}**",
        f"- Gold cases: **{report['case_count']}**",
        f"- Metric: recall@{report['top_k']} (expected answer substring present in top-{report['top_k']} excerpts)",
        "",
        "| Mode | Recall@k | Hits |",
        "|------|----------|------|",
        f"| Lexical | {m['lexical']:.0%} | {report['hits']['lexical']}/{report['case_count']} |",
        f"| Vector (hash-v1) | {m['vector']:.0%} | {report['hits']['vector']}/{report['case_count']} |",
        f"| Hybrid RRF | {m['hybrid']:.0%} | {report['hits']['hybrid']}/{report['case_count']} |",
        "",
        "## Notes",
        "",
    ]
    for note in report["notes"]:
        lines.append(f"- {note}")
    lines.extend(["", "## Per-case hits", ""])
    for c in report["cases"]:
        hits = c["hits"]
        lines.append(
            f"- **{c['intent']}**: lex={'Y' if hits['lexical'] else 'N'} "
            f"vec={'Y' if hits['vector'] else 'N'} hyb={'Y' if hits['hybrid'] else 'N'} — {c['question']}"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=PACK / "eval_cases.jsonl")
    parser.add_argument("--docs", type=Path, default=PACK / "sample_docs.jsonl")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--md-out",
        type=Path,
        default=ROOT / "docs" / "retrieval_eval_report.md",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ROOT / "artifacts" / "retrieval_eval.json",
    )
    args = parser.parse_args(argv)

    cases, docs = load_corpus(args.cases, args.docs)
    if not cases:
        print("No eval cases found", file=sys.stderr)
        return 1
    report = evaluate(cases, docs, top_k=args.top_k)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.write_text(render_markdown(report), encoding="utf-8")
    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(render_markdown(report))
    print(f"Wrote {args.md_out} and {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
