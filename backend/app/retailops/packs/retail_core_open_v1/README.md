# retail_core_open_v1

Governed open retail content release for TEKsystems RetailOps.

| Field | Value |
|-------|--------|
| `release_id` | `retail_core_open_v1` |
| `rag_pack_id` | `retail_core_rag` |
| `collection_id` | `prebuilt_retail_core` |

## Layers

- **Platform-prebuilt:** FDA / OSHA / FTC text + controlled analytical summaries (tenant `platform`, project `prebuilt_retail_core`)
- **Structured public eval:** FreshRetailNet pilot subset + UCI transactions (`retail_*` tables)
- **Tenant/project:** generic Australia / Global fixtures (no brand names)

## Load

```bash
cd backend
# RETAILOPS_EMBED_BACKEND defaults to fastembed (real ONNX BGE-small vectors);
# set to hash only for deterministic, no-ML-deps unit tests.
# Offline / CI
PYTHONPATH=. python -m app.retailops.packs.load_retail_core_open_v1 --profile mini
# Full: HTTPS acquire FDA/OSHA/FTC + FreshRetailNet parquet + UCI zip, then embed
PYTHONPATH=. python -m app.retailops.packs.load_retail_core_open_v1 --profile full --force-text
```

Inspect: `GET /v1/packs/retail_core_open_v1`

Raw transaction/sales rows are **never** embedded. Only controlled summaries enter pgvector.

When FDA blocks egress, acquire falls back to Wayback mirrors, then to `seeds/fda_food_code_2022.pdf`.
