# Retrieval evaluation report

Generated: `2026-07-15T09:07:39.582164+00:00`

## Summary

- Corpus documents: **5**
- Gold cases: **3**
- Metric: recall@5 (expected answer substring present in top-5 excerpts)

| Mode | Recall@k | Hits |
|------|----------|------|
| Lexical | 100% | 3/3 |
| Vector (hash-v1) | 100% | 3/3 |
| Hybrid RRF | 100% | 3/3 |

## Notes

- Offline closed corpus: sample_docs.jsonl + grounding_hint texts.
- Vector channel uses the same hash-v1 embedding space as RETAILOPS_EMBED_BACKEND=hash.
- Hybrid = RRF(k=60) over lexical overlap ranks and vector cosine ranks.
- Live FastEmbed/pgvector recall belongs in a post-ingest pack run; this report is CI-safe.

## Per-case hits

- **return_policy**: lex=Y vec=Y hyb=Y — What is the return window for unused items?
- **warehouse_inspection**: lex=Y vec=Y hyb=Y — How should warehouse staff handle a damaged inbound package?
- **promo_lookup**: lex=Y vec=Y hyb=Y — What multipack soft-drink promotion is on the leaflet for SunValley?
