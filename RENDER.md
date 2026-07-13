# Render deployment — TEKsystems RetailOps

## Service map

| Resource | Name | Notes |
|----------|------|--------|
| Web | `retailops` (`srv-d9al9l0458ps73cb4hag`) | Docker, health `/health` |
| DB | `retailops-db` (`dpg-d9al9im7r5hc73eea510-a`) | Postgres 16 (+ pgvector on first migrate) |
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

After merging to `main`, auto-deploy should fire. Force if needed:

```bash
# Dashboard → Manual Deploy, or:
curl -sS -X POST \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Accept: application/json" \
  "https://api.render.com/v1/services/srv-d9al9l0458ps73cb4hag/deploys" \
  -d '{"clearCache":"do_not_clear"}'

curl -sS https://retailops-3ayp.onrender.com/health
curl -sS -o /dev/null -w '%{http_code}\n' https://retailops-3ayp.onrender.com/
```

Expect `/health` with `kit_snapshot: local-retail-kit-1.1.0` and `/` → `200` HTML
(`title: CEREBRUM RetailOps`).

## Fixture load on Render

Prefer a **one-off job** (SSH is interactive-only in CLI). Keep the Python
payload on a single logical `-c` string (embedded newlines are fine; do not
leave statements after a truncated `init_engine()` call).

```bash
# Example: Render Jobs API
curl -sS -X POST \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  "https://api.render.com/v1/services/srv-d9al9l0458ps73cb4hag/jobs" \
  -d '{"startCommand":"python -c '\''from app.retailops.db import init_engine, session_scope\nfrom app.retailops.fixtures.loader import load_fixtures\ninit_engine()\nwith session_scope() as s:\n    print(load_fixtures(s))'\''"}'
```

Or from an SSH session / ephemeral shell with `RETAILOPS_DATABASE_URL` set:

```bash
python -c "
from app.retailops.db import init_engine, session_scope
from app.retailops.fixtures.loader import load_fixtures
init_engine()
with session_scope() as s:
    print(load_fixtures(s))
"
```

Copy a returned project id (Australia / Global) into the UI header.

## Smoke checklist

Verified against live after the hardened `main` redeploy:

1. `GET /health` → `status:ok`, `database:ok`, `kit_snapshot` present  
2. `GET /` → 200 HTML business shell (+ `/assets/*.js` / `.css` 200)  
3. `GET /v1/overview`, `GET /v1/actions` with `X-User-Id` / `X-Tenant-Id` / `X-Project-Id`  
4. After fixtures: cited `/v1/ask`; three retail actions succeed; empty project → `dependency_required`  
5. Australia project citations stay Australia-scoped (no Global-only suppliers)

## Two-minute demo

1. Open https://retailops-3ayp.onrender.com/  
2. Paste Australia or Global project id from fixture load  
3. Assistant: stock discrepancy escalation → citations  
4. Actions: inventory risk → success; unknown/empty project → `dependency_required`  
5. Audit: persisted runs with status/duration/evidence count  
