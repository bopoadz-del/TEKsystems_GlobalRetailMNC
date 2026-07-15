# retail_ecom_rag_eval_v1

rescommons group-B RAG eval gold + selective grounded snippet ingest.

Eval fixtures land in `fixtures_min/eval_cases.jsonl` (mini) or pack cache (full).

```bash
PYTHONPATH=. python -m app.retailops.packs.load_hf_retail_packs --pack eval --profile mini|full
```
