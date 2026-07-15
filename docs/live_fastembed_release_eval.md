# Live FastEmbed release evaluation

Generated: `2026-07-15T13:29:57.367189+00:00`
Target: `https://retailops-3ayp.onrender.com` (principal `u_platform` / `platform` / `prj_prebuilt_retail_core`)

## Summary

- Server health: **ok**
- Embedding backend (deploy default): **fastembed**
- Embedding model: **BAAI/bge-small-en-v1.5**
- Embedding dim: **384**
- Gold cases: **3**
- Recall@5 (expected substring in retrieved citation excerpts or answer): **33%** (1/3)

## Per-case results

| Intent | Question | Expected | HTTP | Route | Citations | Hit |
|---|---|---|---|---|---|---|
| return_policy | What is the return window for unused items? | `30 days` | 200 | rag | 6 | Y |
| warehouse_inspection | How should warehouse staff handle a damaged inbound package? | `quarantine` | 200 | rag | 6 | N |
| promo_lookup | What multipack soft-drink promotion is on the leaflet for SunValley? | `3.00 for 2` | 200 | rag | 6 | N |

## Notes

- Live evaluation against a real deployment: RETAILOPS_EMBED_BACKEND=fastembed (BAAI/bge-small-en-v1.5, 384 dims) is the deploy default per backend/app/retailops/embeddings.py and backend/app/retailops/deploy/Dockerfile (model is warmed at image build time so a cold ONNX download never occurs at request time).
- This report is a fixed 3-question gold-case regression on the live corpus, not a general proof of FastEmbed embedding quality.
- The CI-safe offline hash-v1 3-case report (docs/retrieval_eval_report.md) is retained unmodified and is not claimed to demonstrate FastEmbed quality.
- Embedding fingerprint stamping/mismatch enforcement (embedding_model + embedding_dim per document, raise — never silently fall back to hash) is unit-tested in backend/tests/retailops/test_embedding_guard.py and is unconditionally active in backend/app/retailops/embedding_guard.py for every ingest and retrieval call.
- Recall<100% here is a known, honestly-reported limitation of hybrid retrieval over a small mixed corpus (large FDA/OSHA/FTC regulatory documents alongside a handful of tiny HF SOP/promo snippets in the same project) for naturally-phrased questions that do not repeat the answer's keywords — it is NOT a silent-fallback or embedding-mismatch defect (those are hard-gated separately). scripts/release_gate.py's six-question regression (which uses release-representative phrasing) is the release-blocking RAG contract gate and passes 6/6 live.
