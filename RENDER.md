# Render deployment — TEKsystems RetailOps

## Service map

| Resource | Name | Notes |
|----------|------|--------|
| Web | `retailops` | Docker, health `/health` |
| DB | `retailops-db` | Postgres 16 (+ pgvector extension on first migrate) |
| URL | https://retailops-3ayp.onrender.com | Auto-deploy from `main` |

Blueprint source: root [`render.yaml`](render.yaml) (mirrors
`backend/app/retailops/deploy/render.yaml`).

## Env vars

| Key | Source |
|-----|--------|
| `RETAILOPS_DATABASE_URL` | From `retailops-db` connection string (Render converts for SQLAlchemy; app accepts `postgresql://` via runtime config) |
| `RETAILOPS_EMBED_BACKEND` | `hash` |
| `RETAILOPS_LLM_PROVIDER` | `auto` (or `fake` for demos) |
| `AZURE_OPENAI_*` | Optional secrets, `sync: false` in blueprint |

Never commit API keys. Prefer dashboard/secret injection.

## Redeploy

After merging to `main`:

```bash
# auto-deploy should fire; or force:
# render deploys create srv-d9al9l0458ps73cb4hag --wait
curl -sS https://retailops-3ayp.onrender.com/health
curl -sS -o /dev/null -w '%{http_code}\n' https://retailops-3ayp.onrender.com/
```

## Fixture load on Render

One-off shell / SSH (or temporary job) with the service’s `RETAILOPS_DATABASE_URL`:

```bash
python -c "
from app.retailops.db import init_engine, session_scope
from app.retailops.fixtures.loader import load_fixtures
init_engine()
with session_scope() as s:
    print(load_fixtures(s))
"
```

Copy a returned project id into the UI (header / Overview paste).

## Smoke checklist

1. `GET /health` → `status:ok`, `database:ok`, `kit_snapshot` present  
2. `GET /` → 200 HTML business shell  
3. `GET /v1/actions` with `X-User-Id` / `X-Tenant-Id` / `X-Project-Id`  
4. After fixtures: cited `/v1/ask`, three retail actions, audit list  
5. Australia project cannot retrieve Global-only supplier evidence  

## Two-minute demo

1. Open https://retailops-3ayp.onrender.com/  
2. Paste Australia or Global project id  
3. Assistant: stock discrepancy escalation → citations  
4. Actions: inventory risk → success; empty project → `dependency_required`  
5. Audit: persisted runs with status/duration/evidence count  


## retail_core_open_v1 on Render

After deploy, one-off job for **full** official-source acquire + index:

```bash
python -m app.retailops.packs.load_retail_core_open_v1 --profile full --force-text
```

Mini/offline:

```bash
python -m app.retailops.packs.load_retail_core_open_v1 --profile mini
```

Inspect: `GET /v1/packs/retail_core_open_v1`
