# CEREBRUM RetailOps — TEKsystems Global Retail MNC

Standalone deployable retail-operations platform for the Northstar Global
Retail portfolio pilot. It ingests fictional retail records, answers
document-grounded questions with citations, executes retail deliverable
actions with full audit evidence, reasons across operational domains, learns
from **verified** outcomes only, and serves a business UI.

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
| Honesty / grounding | `verification` + `failure_policy` |
| CerebrumDev.ai catalog | vendor-neutral JSON + `manifest.schema.json` |

Hats specialize `retail.base`. They annotate `RetailExecutionPlan` with
`active_agent_ids`, `primary_agent_id`, and `handoff_tips` — they do **not**
add a second orchestrator. Roster / staffing is first-class via
`retail.hat.workforce_roster`.

```
GET /v1/agents
GET /v1/agents/{agent_id}
POST /v1/ask  { "question": "...", "disabled_agents": ["disable:roster"] }
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

Kit version: `1.3.0`.

## Database & retrieval

- **Store:** PostgreSQL 16 + pgvector.
- Tables include core ops tables plus learning events/profiles.
- Hybrid retrieval: pgvector cosine + Postgres `ts_rank_cd` fused with RRF.
  Tenant + project filters apply before fusion (fail-closed).

## Local run (Docker — preferred)

```bash
# From repo root
docker compose up --build
# App: http://localhost:8000/   Health: http://localhost:8000/health
```

Load fictional Northstar fixtures (documents + verified learning outcomes):

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

## Render

See [RENDER.md](RENDER.md). Blueprint: root `render.yaml`.

## API examples

```bash
H='-H X-User-Id:u_ops_manager -H X-Tenant-Id:northstar -H X-Project-Id:<PID> -H Content-Type:application/json'

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

`backend/app/retailops/fixtures/northstar/` — fictional **Northstar Global Retail**
for *Northstar Riyadh Region* and *Northstar Melbourne Region*.

Learning fixtures in `fixtures/northstar/learning/verified_outcomes.json`
demonstrate low / medium / high demand confidence, two suppliers, two
campaigns, and repeated store exceptions. Idempotent via `deduplication_key`.

## Security

Trusted tenant/project/permissions are server-resolved. Retrieval and learning
are fail-closed for isolation. Audit stores hashes/metadata — never secrets.
Model/request arguments cannot override `tenant_id` / `project_id` / permissions.

## Known limitations

- Learning is deterministic advisory analytics, not neural forecasting.
- No autonomous ordering or supplier selection.
- No cross-tenant global learning.
- Write form for verified outcomes is API-first; UI Learning tab is read-only.
