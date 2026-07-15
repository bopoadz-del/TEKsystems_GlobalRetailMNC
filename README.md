# CEREBRUM RetailOps — TEKsystems Global Retail MNC

Standalone deployable retail-operations platform for multi-region retail
operations. It ingests documents and open evaluation datasets, answers
document-grounded questions with citations, executes three retail deliverable
actions with full audit evidence, and serves a business UI.

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

## Enterprise integrations (pilot connectors)

Eight visible connector cards behind one shared, provider-abstraction-style
contract (see `app/retailops/providers.py` for the LLM analogue):
`app/retailops/integrations/base.py` defines `RetailConnector` — every
connector implements `health()`, `test_connection()`, `pull()`,
`normalize()` and `push()`, and reports one of a closed status vocabulary:
`disabled | mock | configured | connected | degraded | error`.

**Signature layer:** `POS + ERP + WMS + Supplier EDI → RetailOps AI → Store
Digital Twin + Power BI + ServiceNow`. RetailOps AI is the RAG/action
runtime already documented above; the connectors in this section are its
inbound (POS/ERP/WMS/EDI) and outbound (Digital Twin/Power BI/ServiceNow)
integration surface.

| Connector | Card | Mode | Notes |
|---|---|---|---|
| `pos` | POS | **Mock-functional** | NCR / Toshiba / D365 Commerce / Generic — deterministic transactions, sales by SKU, returns, discounts |
| `inventory_wms` | Inventory & WMS | **Mock-functional** | Manhattan / Blue Yonder / RELEX / Generic — on-hand/available/reserved, reorder/safety, soft-wired to `retail.analyse_inventory_risk` via `to_inventory_risk_rows()` |
| `supplier_edi` | Supplier / EDI | **Mock-functional** | Ariba / EDI 850/856/810 / Portal — orders, promised vs. actual delivery, short/damaged/rejected notices |
| `power_bi` | Power BI | **Mock-functional** | Real CSV/XLSX export (openpyxl); dataset publish + semantic-model refresh are honest stubs; embed URL is an explicit placeholder |
| `sap_erp` | SAP / ERP | Honest stub | Not connected; planned capability, no vendor adapter |
| `crm_loyalty` | CRM & Loyalty | Honest stub | Not connected; read-only, returns a tiny illustrative sample on sync (not a live feed) |
| `store_digital_twin` | Store Digital Twin | Honest stub | Not connected; planogram record shape documented (`PLANOGRAM_RECORD_SHAPE`), no live adapter |
| `entra_id` | Microsoft Entra ID | Honest stub | Not connected; SSO/role/group mapping planned — RetailOps currently uses server-resolved `X-User-Id`/`X-Tenant-Id`/`X-Project-Id` headers |

No real credentials are hardcoded anywhere in `app/retailops/integrations/`.
Each connector reads optional configuration from environment variables
(`RETAILOPS_POS_*`, `RETAILOPS_WMS_*`, `RETAILOPS_EDI_*`,
`RETAILOPS_POWERBI_*`, `RETAILOPS_SAP_*`, `RETAILOPS_CRM_*`,
`RETAILOPS_DIGITAL_TWIN_*`, `RETAILOPS_ENTRA_*`) and degrades honestly
(`mock`/`disabled`) when they are absent — connector failures always raise
`ConnectorError`, never fabricated vendor data.

**Persistence note:** test/sync run history
(`app/retailops/integrations/runs.py`) is an in-process, in-memory ring
buffer per (tenant, project, connector) for this pilot — it does **not**
survive a process restart. It is shaped like an audit record so it can be
promoted to a real `integration_runs` table (with an Alembic migration)
without changing the `/v1/integrations/*` API contract.

**Deferred connectors** (documented, not shipped as pilot cards to avoid
clutter): ServiceNow (incident/ticket sync from operations briefs), Store
Task / Workforce management, and a generic Enterprise Data Platform export
lane. These sit downstream of the same `RetailConnector` contract and can be
added as additional cards without any router change.

API:

```
GET  /v1/integrations
GET  /v1/integrations/{connector_id}
POST /v1/integrations/{connector_id}/test
POST /v1/integrations/{connector_id}/sync
GET  /v1/integrations/{connector_id}/runs
```

UI: the **Integrations** tab in the business frontend renders all eight
cards with status badges and Test/Sync actions (mock-functional connectors)
or disabled, honestly-labelled CTAs (stub connectors).

## Actions (local kit snapshot)

Namespaced deliverables — adding one requires **no** router change:

- `retail.generate_operations_brief`
- `retail.analyse_inventory_risk`
- `retail.check_promotion_compliance`

Kit id exposed on `/health` as `kit_snapshot` / legacy `blocks_commit`:
`local-retail-kit-1.2.0`.

## Login

The UI is prefilled with the working pilot identity:

- **User:** `u_platform`
- **Tenant:** `platform`
- **Project:** `prj_prebuilt_retail_core`

This is the tenant/project seeded by the `retail_core_open_v1` platform-prebuilt
pack (see below); it authenticates out of the box once that pack has been
loaded on the target deployment. Regional fixture projects (Australia Region /
Global Region, tenant `retail`) also work once `load_fixtures` has run, but
their project ids are generated per-deployment — paste one into the **Project
ID** field instead.

Browsers that signed in before this default was fixed may have the old,
never-valid `tenant=northstar` / `user=u_ops_manager` principal cached in
`localStorage`. The frontend detects that one specific stale value and
migrates it back to the working default on load, so a normal reload — not a
manual cache clear — is enough to recover a stuck session.

## Local run (Docker — preferred)

```bash
# From repo root
docker compose up --build
# App: http://localhost:8000/   Health: http://localhost:8000/health
```

Load generic regional fixtures (Australia + Global):

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

## Oracle smoke (fixtures + live checklist)

`scripts/oracle_smoke.py` is a stdlib-only ad-hoc runner (no third-party
deps): it POSTs each action's deterministic `evaluation_fixtures` straight to
`/execute` and asserts the guaranteed status, then also drives the RENDER.md
smoke checklist (health, root, actions discovery, a RAG `/v1/ask`, audit
persistence).

```bash
python scripts/oracle_smoke.py --base-url https://retailops-3ayp.onrender.com \
    --user u_platform --tenant platform --project prj_prebuilt_retail_core
```

## Render

See [RENDER.md](RENDER.md) for the full deploy/env/smoke-test guide. Blueprint:
root `render.yaml` (same Dockerfile as local).

Live: https://retailops-3ayp.onrender.com — this service auto-deploys from
`feat/retailops-platform-v1`, not `main` (`main` is behind this branch).

## API examples

```bash
H='-H X-User-Id:u_ops_manager -H X-Tenant-Id:retail -H X-Project-Id:<PID> -H Content-Type:application/json'
curl -s $H localhost:8000/v1/actions
curl -s $H -d '{"question":"What is the escalation process for a stock discrepancy?"}' localhost:8000/v1/ask
curl -s $H -d '{"arguments":{"period":"daily"}}' localhost:8000/v1/actions/retail.generate_operations_brief/execute
curl -s $H localhost:8000/v1/audit
```

## Fixture data

`backend/app/retailops/fixtures/demo/` — fictional regional project fixtures for
*Australia Region* and *Global Region* (no retailer brand names). Open knowledge
lives in the `retail_core_open_v1` platform-prebuilt release.

### Hugging Face RAG packs

Additional general / multi-brand corpora (not H&M or Amazon product catalogues):

| Pack | Hub | Role |
|------|-----|------|
| `retail_cx_policies_v1` | Bitext retail chatbot | General CX/policy RAG |
| `retail_ops_sops_v1` | amazon/sop-bench | Ops SOP procedure texts |
| `promo_leaflet_rag_v1` | mSOP-765k | Multi-brand flyer offers (text; images deferred) |
| `retail_ecom_rag_eval_v1` | rescommons (group B) | RAG eval gold + selective snippets |

```bash
cd backend
PYTHONPATH=. python -m app.retailops.packs.load_hf_retail_packs --pack all --profile mini --force
# GET /v1/packs/hf_retail
```

See [RENDER.md](RENDER.md) for full HF load on Render and [LICENSES.md](backend/app/retailops/packs/retail_cx_policies_v1/LICENSES.md) per pack.

## Security

Trusted tenant/project/permissions are server-resolved. Retrieval is fail-closed
for isolation. Audit stores hashes/metadata — never secrets.

## Known limitations

- Live embeddings default to real ONNX BGE-small (`RETAILOPS_EMBED_BACKEND=fastembed`); tests use `hash`.
- Fake LLM provider is credential-free; set Azure/OpenAI for fluent synthesis.
- SPA is served only when `frontend/dist` is present in the image (Docker build).
