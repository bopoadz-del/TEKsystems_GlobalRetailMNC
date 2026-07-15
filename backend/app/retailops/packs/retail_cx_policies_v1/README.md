# retail_cx_policies_v1

General retail CX / policy RAG from Bitext (not H&M/Amazon catalogue).

```bash
cd backend
PYTHONPATH=. python -m app.retailops.packs.load_hf_retail_packs --pack cx --profile mini
PYTHONPATH=. python -m app.retailops.packs.load_hf_retail_packs --pack cx --profile full
```

Inspect: `GET /v1/packs/hf_retail`
