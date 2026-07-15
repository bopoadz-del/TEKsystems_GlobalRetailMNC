# CEREBRUM RetailOps — TEKsystems Global Retail MNC

Standalone deployable retail-operations platform for multi-region retail
operations. It ingests documents and open evaluation datasets, answers
document-grounded questions with citations, executes retail deliverable
actions with full audit evidence, reasons across operational domains via
vendor-neutral discipline agents, learns from **verified** outcomes only,
and serves a business UI.

This repository is the **product**. Upstream CerebrumDev.ai / Cerebrum-Blocks
may be used as design references; the action contract and Retail kit ship here
as a **local kit snapshot** under `backend/app/retailops/kit/`.

## Architecture

```
User request
  → LangGraph (classify_request → reason_retail_request)
  → RetailOperationsReasoner → RetailExecutionPlan
  → RAG (retrieve_context)  OR  ActionRegistry (resolve → execute)
  → synthesize_response
  → persist_audit

Verified outcome (separate write flow)
  → retail.record_verified_outcome (permission + confirmation)
  → retail_learning_events (immutable)
  → profile recalculation
  → retail_learning_profiles (advisory)
  → optional advisory input to future analyses
```

```
                     ┌──────────── Business UI (React/Vite) ───────────────────┐
                     │ Overview · Documents · Assistant · Actions · Agents · Learning · Audit │
                     └───────────────────────────┬─────────────────────────────┘
                                                  │ HTTP (X-User/Tenant/Project)
                     ┌────────────────────────────▼────────────────────────────┐
   /v1/ask ─────────▶  LangGraph + RetailOperationsReasoner                     │
   /v1/actions ──────▶  Generic ActionRegistry + execute_action                 │
   /v1/agents ───────▶  Discipline base+hat catalog (composed manifests)        │
   /v1/exports ──────▶  PDF / DOCX / XLSX generation (streamed download)         │
   /v1/learning/* ───▶  Advisory learning read APIs                             │
   /v1/documents ────▶  Ingestion (PDF/DOCX/TXT/MD/CSV/XLSX)                     │
   /v1/audit ────────▶  Audit (action_runs)                                     │
                     └───────┬───────────────────────────────┬─────────────────┘
                             │ hybrid retrieval               │ providers
                     ┌───────▼─────────┐             ┌────────▼─────────┐
                     │ PostgreSQL 16   │             │ Azure OpenAI /   │
                     │ + pgvector      │             │ OpenAI-compat /  │
                     │ + learning msgs │             │ deterministic fake│
                     └─────────────────┘             └──────────────────┘
```

## Retail Operations Reasoning Layer

`RetailOperationsReasoner` is deterministic. It does **not** call action
handlers or replace LangGraph. It emits an auditable `RetailExecutionPlan`
(primary intent, confidence, route, recommended registered actions, related
domains, dependencies, evidence requirements, confirmation flag, notes,
active discipline hats, and handoff tips).

- Factual questions stay on RAG (anti-hijack).
- Explicit `action:<id>` addressing is supported.
- Only actions present in `ActionRegistry` and permitted for the trusted
  context may be recommended. Trust-scope keys are never taken from arguments.

Cross-domain expansion is data-driven in
`backend/app/retailops/reasoning/domain_map.py`.

## Discipline Agents (base + hats)

Vendor-neutral manifests under `backend/app/retailops/agents/` encode the
product contract for a retail mogul’s discipline agents:

| Product need | Manifest field |
| --- | --- |
| Triggered / put off by user | `activation` (+ `put_off_by` / `disabled_agents`) |
| Knowledge boundary | `context_sources` + `allowed_paths` |
| Teachable / confirmed decisions | `memory.save` (always confirmation-gated) |
| Cross-discipline tips | `handoffs` |
| Formulas / standards / procedures | `playbook` |
| Honesty / grounding | `verification` + `failure_policy` |
| CerebrumDev.ai catalog | vendor-neutral JSON + `manifest.schema.json` |

Every discipline hat ships a `playbook` with:

- **formulas** — named expressions (bound to learning modules / actions when implemented)
- **standards** — policy, regulatory, KPI, or safety norms (`must_cite` where required)
- **procedures** — ordered steps, optional confirmation + handoff targets

Composed hat views inherit base playbook entries and overlay hat-specific ones.
Reasoner plans expose `playbook_refs` for the primary active hat.

Hats specialize `retail.base`. They annotate `RetailExecutionPlan` with
`active_agent_ids`, `primary_agent_id`, and `handoff_tips`. Keyword/imperative
action matches are **filtered** by the primary hat’s `allowed_actions`. Explicit
`action:<id>` addressing still wins when permitted. Playbook formulas with
`implemented_by` are disclosed on action outputs as `applied_formulas`.

Confirmed hat memory is now writable:

```
GET  /v1/agents/memory
POST /v1/agents/memory  { agent_id, key, value, confirm: true }
```

Keys must match the hat’s `memory.save` declarations. LLM free text / secrets /
PII keys are refused.

```
GET /v1/agents
GET /v1/agents/{agent_id}
POST /v1/ask  { "question": "...", "disabled_agents": ["disable:roster"] }
```

## LLM provider (OpenAI)

Production default is **OpenAI** (`gpt-4o-mini`):

| Env | Value |
| --- | --- |
| `RETAILOPS_LLM_PROVIDER` | `openai` |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` |
| `RETAILOPS_LLM_MODEL` | `gpt-4o-mini` |
| `OPENAI_API_KEY` | **Dashboard secret** (`sync: false` — never commit) |

Ollama Cloud remains available via `RETAILOPS_LLM_PROVIDER=ollama` + `OLLAMA_API_KEY`.
Without any key, `auto` falls back to the deterministic `FakeProvider` (tests/local).

## Document export (PDF / DOCX / XLSX)

The platform both **ingests** and **generates** office documents:

| Format | Ingest | Generate |
| --- | --- | --- |
| PDF | yes | yes (`retail.export_document`) |
| Word DOCX | yes | yes |
| Excel XLSX | yes | yes |

Generation is ActionRegistry-backed (no second runtime). Artefacts are built
in memory and returned as `document_base64` (Render disk is ephemeral) or
streamed via `POST /v1/exports`.

Document kinds: `operations_brief`, `inventory_risk`, `learning_summary`, `custom`.

```
# JSON + base64
curl -s $H -X POST localhost:8000/v1/actions/retail.export_document/execute \
  -d '{"arguments":{"format":"pdf","document_kind":"operations_brief","period":"daily"},"auto_context":true}'

# Stream download
curl -s $H -X POST localhost:8000/v1/exports \
  -d '{"format":"xlsx","document_kind":"inventory_risk"}' -o inventory-risk.xlsx
```

## Retail Outcome Learning Layer

Deterministic modules (no ML frameworks; never train on LLM text):

1. `DemandReorderCalibrator`
2. `SupplierFulfilmentLearner`
3. `PromotionEffectivenessLearner`
4. `StoreExceptionPatternDetector`

### Verified-only safety model

Learning happens only through authorised verified outcome capture:

```
verified outcome submitted
  → permission checked (retail:learning_write)
  → confirmation checked
  → payload validated
  → immutable retail_learning_events row
  → affected profile recalculated
  → action audit persisted
  → ActionResult returned
```

Never learned from: chat, RAG answers, LLM synthesis, failed/unsupported
actions, unverified uploads, or inferred values.

### PostgreSQL learning schema

- `retail_learning_events` — immutable observations; unique
  `(tenant_id, project_id, deduplication_key)`
- `retail_learning_profiles` — advisory knowledge; unique
  `(tenant_id, project_id, module, entity_type, entity_key)`

Tenant/project isolation is mandatory. No cross-tenant aggregation.

Confidence bands: **low** `<3` samples, **medium** `3–7`, **high** `≥8`.

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
- `retail.analyse_inventory_risk` (may consume high-confidence demand profiles as advisory)
- `retail.check_promotion_compliance`
- `retail.record_verified_outcome` (write; confirmation required)
- `retail.get_learning_summary` (read)
- `retail.recommend_reorder_parameters` (read; advisory)

**Advisory-not-autonomous rule:** learned profiles never silently overwrite
source reorder settings. Inventory analysis discloses original / learned /
applied values; only **high** confidence may alter applied thresholds.

Kit id exposed on `/health` as `kit_snapshot` / legacy `blocks_commit`:
`local-retail-kit-1.3.0`.

## Database & retrieval

- **Store:** PostgreSQL 16 + pgvector. Tables include core ops tables
  (`tenants`, `users`, `projects`, `documents`, `document_chunks`,
  `action_runs`, `conversations`, `messages`) plus learning events/profiles
  and discipline-hat memory.
- Hybrid retrieval: pgvector cosine + Postgres `ts_rank_cd` fused with RRF.
  Tenant + project filters apply before fusion (fail-closed). See
  [docs/retrieval_eval_report.md](docs/retrieval_eval_report.md) for a
  lexical vs. vector vs. hybrid evaluation on a small gold set.
- Embeddings default to real ONNX BGE-small (`RETAILOPS_EMBED_BACKEND=fastembed`,
  `BAAI/bge-small-en-v1.5`, 384 dims). An unknown backend or a requested
  `fastembed` backend that fails to load **raises** — it never silently
  falls back to the hash embedder. Mixed embedding spaces (e.g. re-embedding
  a project with a different model) are also rejected loudly — see
  `app/retailops/embedding_guard.py`.

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

Load generic regional fixtures (Australia + Global, including verified
learning outcomes):

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
export RETAILOPS_TEST_DATABASE_URL="postgresql+psycopg://retailops:retailops@localhost:5432/retailops_test"
pip install -r backend/app/retailops/deploy/requirements.txt pytest httpx
cd backend && PYTHONPATH=. pytest tests/retailops -q
```

If the test database is unreachable, tests skip rather than fail hard when
run locally. **CI is different:** the `db-integration` job in
`.github/workflows/ci.yml` fails outright (does not skip) if
`RETAILOPS_TEST_DATABASE_URL` cannot be reached — see
[CI](#ci-github-actions) below.

## CI (GitHub Actions)

<a id="ci-github-actions"></a>

Workflow: [`.github/workflows/ci.yml`](.github/workflows/ci.yml)

| Job | What it enforces |
|-----|------------------|
| **Unit (embedding guard + auth/CORS)** | Embedding fingerprint mismatch raises; unknown embed backends raise (no silent hash/Azure fallthrough); `RETAILOPS_API_KEY` gates `/v1/*` while `/health` stays public; CORS uses `RETAILOPS_CORS_ORIGINS` allowlist. |
| **Postgres + pgvector integration** | Service container `pgvector/pgvector:pg16`. Sets `RETAILOPS_REQUIRE_DB=1` / `CI=true` so unreachable DBs **fail** (never skip). Full `tests/retailops` suite. |
| **E2E oracle smoke** | Migrates, loads demo fixtures, starts uvicorn, runs `scripts/oracle_smoke.py` against localhost. |
| **Retrieval eval report** | Offline lexical / vector / hybrid RRF recall on `retail_ecom_rag_eval_v1` gold cases → `docs/retrieval_eval_report.md` + `artifacts/retrieval_eval.json`. |
| **Frontend lint + build** | `npm ci` + `npm run build` for the business shell. |

Env knobs used in CI:

- `RETAILOPS_TEST_DATABASE_URL` / `RETAILOPS_DATABASE_URL`
- `RETAILOPS_EMBED_BACKEND=hash` (deterministic tests; production default remains `fastembed`)
- `RETAILOPS_REQUIRE_DB=1` — convert DB unavailability into a hard failure
- Optional deploy: `RETAILOPS_API_KEY`, `RETAILOPS_CORS_ORIGINS`, `RETAILOPS_ENV=production`

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
`feat/retailops-platform-v1`.

## API examples

```bash
H='-H X-User-Id:u_ops_manager -H X-Tenant-Id:retail -H X-Project-Id:<PID> -H Content-Type:application/json'
# If RETAILOPS_API_KEY is set on the server, also add: -H X-API-Key:<key>
curl -s $H localhost:8000/v1/actions

# Reasoned ask (returns execution_plan)
curl -s $H -d '{"question":"What is the escalation process for a stock discrepancy?"}' localhost:8000/v1/ask

# Advisory learning summary
curl -s $H localhost:8000/v1/learning/summary
curl -s $H localhost:8000/v1/learning/profiles

# Recommend reorder parameters (advisory)
curl -s $H -d '{"arguments":{"sku":"BEV-2201","store":"Riyadh Olaya","current_reorder_point":20}}' \
  localhost:8000/v1/actions/retail.recommend_reorder_parameters/execute

# Record verified outcome (requires confirmation + retail:learning_write)
curl -s $H -d '{
  "confirm": true,
  "arguments": {
    "module": "demand_reorder",
    "deduplication_key": "demo-bev-week-9",
    "payload": {
      "sku":"BEV-2201","store":"Riyadh Olaya",
      "forecast_quantity":100,"actual_sales_quantity":118,
      "current_reorder_point":20,"safety_stock":10,
      "stockout_occurrence":false,
      "period_start":"2024-03-01","period_end":"2024-03-07"
    }
  }
}' localhost:8000/v1/actions/retail.record_verified_outcome/execute
```

### Example learning profile shape

```json
{
  "module": "demand_reorder",
  "entity_key": "BEV-2201|Riyadh Olaya",
  "sample_count": 8,
  "confidence": "high",
  "metrics": {
    "actual_to_forecast_ratio": 1.12,
    "current_reorder_point": 20,
    "recommended_reorder_point": 22.4,
    "advisory_assumptions": ["advisory_only_does_not_overwrite_source_systems"]
  },
  "advisory_only": true
}
```

## Fixture data

`backend/app/retailops/fixtures/demo/` — fictional regional project fixtures for
*Australia Region* and *Global Region* (no retailer brand names). Open knowledge
lives in the `retail_core_open_v1` platform-prebuilt release.

Learning fixtures in `fixtures/demo/learning/verified_outcomes.json`
demonstrate low / medium / high demand confidence, two suppliers, two
campaigns, and repeated store exceptions against the *Global Region* project.
Idempotent via `deduplication_key`.

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

Trusted tenant/project/permissions are server-resolved. Retrieval and learning
are fail-closed for isolation. Audit stores hashes/metadata — never secrets.
Model/request arguments cannot override `tenant_id` / `project_id` / permissions.

Optional shared-secret gate: set `RETAILOPS_API_KEY` and send `X-API-Key` on
non-public routes (`/health` remains public). Browser CORS is an allowlist via
`RETAILOPS_CORS_ORIGINS` (comma-separated); production with `RETAILOPS_ENV=production`
does not default to `*`. This is not end-user OAuth — identity still comes from
trusted header triples resolved server-side.

Embedding space: documents stamp `embedding_model` + `embedding_dim`; ingest and
hybrid query refuse mismatched fingerprints (`embedding_guard.py`).

## Known limitations

- Live embeddings default to real ONNX BGE-small (`RETAILOPS_EMBED_BACKEND=fastembed`); tests use `hash`.
- Fake LLM provider is credential-free; set Azure/OpenAI for fluent synthesis.
- SPA is served only when `frontend/dist` is present in the image (Docker build).
- Learning is deterministic advisory analytics, not neural forecasting.
- No autonomous ordering or supplier selection.
- No cross-tenant global learning.
- Write form for verified outcomes is API-first; UI Learning tab is read-only.
- Auth beyond the `RETAILOPS_API_KEY` shared-secret + trusted headers is not
  implemented (no per-user session tokens / SSO yet — see Security below).
