# CEREBRUM RetailOps — TEKsystems Global Retail MNC

Standalone deployable retail-operations platform for an Australian mega retailer
with global flagship operations (fictional Meridian Markets demo). It ingests
retail records, answers document-grounded questions with citations, executes
three retail deliverable actions with full audit evidence, and serves a business UI.

This repository is the **product**. Upstream CerebrumDev.ai / Cerebrum-Blocks
may be used as design references; the action contract and Retail kit ship here
as a **local kit snapshot** under `backend/app/retailops/kit/`.

## Architecture

```
                     ┌──────────────── Business UI (React/Vite) ───────────────┐
                     │  Overview · Documents · Assistant · Actions · Audit      │
                     └───────────────────────────┬─────────────────────────────┘
                                                  │ HTTP (X-User/Tenant/Project)
                     ┌────────────────────────────▼────────────────────────────┐
   /v1/ask ─────────▶  LangGraph orchestrator                                   │
                     │   classify → (retrieve | resolve) → execute → synthesize │
                     │            → persist_audit                               │
   /v1/actions ──────▶  Generic ActionRegistry + execute_action (from kit)      │
   /v1/documents ────▶  Ingestion (PDF/DOCX/TXT/MD/CSV/XLSX)                     │
   /v1/audit ────────▶  Audit (action_runs)                                     │
                     └───────┬───────────────────────────────┬─────────────────┘
                             │ hybrid retrieval               │ providers
                     ┌───────▼─────────┐             ┌────────▼─────────┐
                     │ PostgreSQL 16   │             │ Azure OpenAI /   │
                     │ + pgvector      │             │ OpenAI-compat /  │
                     │ (vector+tsvector)│            │ deterministic fake│
                     └─────────────────┘             └──────────────────┘
```

## Database & retrieval

- **Store:** PostgreSQL 16 + pgvector. Tables: `tenants`, `users`, `projects`,
  `documents`, `document_chunks`, `action_runs`, `conversations`, `messages`.
- Hybrid retrieval: pgvector cosine + Postgres `ts_rank_cd` fused with RRF.
  Tenant + project filters apply before fusion (fail-closed).

## Actions (local kit snapshot)

Namespaced deliverables — adding one requires **no** router change:

- `retail.generate_operations_brief`
- `retail.analyse_inventory_risk`
- `retail.check_promotion_compliance`

Kit id exposed on `/health` as `kit_snapshot` / legacy `blocks_commit`:
`local-retail-kit-1.1.0`.

## Local run (Docker — preferred)

```bash
# From repo root
docker compose up --build
# App: http://localhost:8000/   Health: http://localhost:8000/health
```

Load fictional Meridian Markets fixtures (Australia + Global):

```bash
docker compose exec app python -c "
from app.retailops.db import init_engine, session_scope
from app.retailops.fixtures.loader import load_fixtures
init_engine()
with session_scope() as s:
    print(load_fixtures(s))
"
```

## Local run (no Docker)

```bash
export RETAILOPS_DATABASE_URL="postgresql+psycopg://retailops:retailops@localhost:5432/retailops"
pip install -r backend/app/retailops/deploy/requirements.txt
cd backend && uvicorn app.retailops.app_factory:app --host 0.0.0.0 --port 8000
```

## Tests

```bash
# Requires Postgres 16 + pgvector with a retailops_test database (or set URL).
export RETAILOPS_TEST_DATABASE_URL="postgresql+psycopg://retailops:retailops@localhost:5432/retailops_test"
pip install -r backend/app/retailops/deploy/requirements.txt pytest httpx
cd backend && PYTHONPATH=. pytest tests/retailops -q
```

If the test database is unreachable, tests skip rather than fail hard.

## Render

See [RENDER.md](RENDER.md). Blueprint: root `render.yaml` (same Dockerfile as local).

Live service (when deployed): https://retailops-3ayp.onrender.com

## API examples

```bash
H='-H X-User-Id:u_ops_manager -H X-Tenant-Id:meridian -H X-Project-Id:<PID> -H Content-Type:application/json'
curl -s $H localhost:8000/v1/actions
curl -s $H -d '{"question":"What is the escalation process for a stock discrepancy?"}' localhost:8000/v1/ask
curl -s $H -d '{"arguments":{"period":"daily"}}' localhost:8000/v1/actions/retail.generate_operations_brief/execute
curl -s $H localhost:8000/v1/audit
```

## Fixture data

`backend/app/retailops/fixtures/meridian/` — fictional **Meridian Markets** for
*Meridian Australia Region* and *Meridian Global Region*. No real client or
employer data.

## Security

Trusted tenant/project/permissions are server-resolved. Retrieval is fail-closed
for isolation. Audit stores hashes/metadata — never secrets.

## Known limitations

- Default embeddings are deterministic feature-hash (`RETAILOPS_EMBED_BACKEND=hash`).
- Fake LLM provider is credential-free; set Azure/OpenAI for fluent synthesis.
- SPA is served only when `frontend/dist` is present in the image (Docker build).
