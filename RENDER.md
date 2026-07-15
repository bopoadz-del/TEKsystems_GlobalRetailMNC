# Render deployment — TEKsystems RetailOps

## Service map

| Resource | Name | Notes |
|----------|------|--------|
| Web | `retailops` | Docker, health `/health` |
| DB | `retailops-db` | Postgres 16 (+ pgvector extension on first migrate) |
| URL | https://retailops-3ayp.onrender.com | Auto-deploy from `feat/retailops-platform-v1` (the active development branch; `main` is behind and not what's live) |

Blueprint source: root [`render.yaml`](render.yaml) (mirrors
`backend/app/retailops/deploy/render.yaml`).

## Env vars

| Key | Source |
|-----|--------|
| `RETAILOPS_DATABASE_URL` | From `retailops-db` connection string (Render converts for SQLAlchemy; app accepts `postgresql://` via runtime config) |
| `RETAILOPS_EMBED_BACKEND` | `fastembed` (real ONNX BGE-small vectors; `hash` is a deterministic fallback used only for local tests) |
| `RETAILOPS_LLM_PROVIDER` | `auto` (or `fake` for demos) |
| `AZURE_OPENAI_*` | Optional secrets, `sync: false` in blueprint |

Never commit API keys. Prefer dashboard/secret injection.

## Redeploy

After pushing to `feat/retailops-platform-v1` (the branch this service auto-deploys from):

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

The UI already defaults to the working pilot login
(`u_platform` / `platform` / `prj_prebuilt_retail_core`, seeded by
`retail_core_open_v1` below) so no paste is required for that path. To view the
regional fixtures instead, copy a returned Australia/Global project id into
the **Project ID** field in the UI.

## Smoke checklist

1. `GET /health` → `status:ok`, `database:ok`, `kit_snapshot` present  
2. `GET /` → 200 HTML business shell  
3. `GET /v1/actions` with `X-User-Id` / `X-Tenant-Id` / `X-Project-Id`  
4. After fixtures: cited `/v1/ask`, three retail actions, audit list  
5. Australia project cannot retrieve Global-only supplier evidence  

Run `python scripts/oracle_smoke.py --base-url https://retailops-3ayp.onrender.com` to check 1-4
automatically (health, root, actions discovery, the kit's own deterministic
`evaluation_fixtures`, a RAG `/v1/ask` smoke, and audit persistence) against a live deploy.

## Two-minute demo

1. Open https://retailops-3ayp.onrender.com/ — sign in with the prefilled default
   (`u_platform` / `platform` / `prj_prebuilt_retail_core`), or paste an
   Australia/Global fixture project id instead
2. Assistant: stock discrepancy escalation → citations  
3. Actions: inventory risk → success; empty project → `dependency_required`  
4. Audit: persisted runs with status/duration/evidence count  

Note: browsers that signed in before the default login was fixed may have a
stale `tenant=northstar` principal cached in `localStorage`; the frontend
auto-migrates that one known-bad value on load, so a normal reload recovers it.


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
