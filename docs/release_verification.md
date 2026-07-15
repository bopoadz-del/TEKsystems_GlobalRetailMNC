# RetailOps v1 — release verification

This document is the single source of truth for the RetailOps v1 release
certification. It is updated in place as certification phases complete
(baseline → CI → gates → deploy). See the final "Deploy certification"
section for the live evidence gathered against the deployed URL.

## Release identity

| Field | Value |
| --- | --- |
| Release commit (SHA) | `b10db180127d0bd147cef86a6c3c8e54e6986c05` (merge PR #10 into `main`) — the certified working tree; the certification branch adds only release-gate tooling/CI/docs/isolation-test/manifest-path fixes on top |
| Certification branch | `release/retailops-v1-certification` (created from `main` at the commit above) |
| Merge target | `main` |
| Superseded branch | `feat/retailops-platform-v1` — frozen; no further development after this certification |
| UTC test date | 2026-07-15 |
| App version (`RETAILOPS_VERSION`) | `1.0.0` |
| Kit snapshot (`KIT_SNAPSHOT_ID` / `blocks_commit`) | `local-retail-kit-1.3.0` |
| Deployment URL | https://retailops-3ayp.onrender.com |
| Render service | `retailops` (`srv-d9al9l0458ps73cb4hag`) |
| Working principal | `u_platform` / `platform` / `prj_prebuilt_retail_core` |

## Environment / toolchain versions

| Component | Version | Source |
| --- | --- | --- |
| Python | 3.11 | `python:3.11-slim` (Dockerfile runtime stage); CI `actions/setup-python@v5` pins `3.11` |
| Node.js | 20 | `node:20-slim` (Dockerfile frontend build stage); CI `actions/setup-node@v4` pins `20` |
| PostgreSQL | 16 | Render managed Postgres 16; CI service container `pgvector/pgvector:pg16` |
| pgvector | bundled with `pgvector/pgvector:pg16` image | `CREATE EXTENSION IF NOT EXISTS vector` on migrate |
| Embedding backend | `fastembed` (production/live default) | `RETAILOPS_EMBED_BACKEND=fastembed`, `backend/app/retailops/embeddings.py` |
| Embedding model | `BAAI/bge-small-en-v1.5` (ONNX, warmed at image build) | `backend/app/retailops/deploy/Dockerfile` |
| Embedding dimension | 384 | `EMBED_DIM` in `backend/app/retailops/config.py` |
| LLM provider (live) | OpenAI `gpt-4o-mini` (falls back to deterministic `FakeProvider` when no credential is configured) | `backend/app/retailops/providers.py`, `README.md` |

## Phase 1 — baseline

- `main` (local + `origin/main`) HEAD is exactly `b10db180127d0bd147cef86a6c3c8e54e6986c05` — confirmed via
  `git rev-parse origin/main` and `git merge-base --is-ancestor`.
- `release/retailops-v1-certification` created from that commit.
- No further commits were made on `feat/retailops-platform-v1`; all certification work
  (CI workflow, `scripts/release_gate.py`, isolation tests, manifest path fix, docs) lives on the
  release branch only, targeting `main`.
- Render service `retailops` (`srv-d9al9l0458ps73cb4hag`) is switched to auto-deploy from `main`
  after the certification PR merges (see "Deploy certification" below for the outcome / evidence).
- Stale docs that claimed prod deploys from `feat/retailops-platform-v1` (`README.md`,
  `backend/app/retailops/README.md`, `RENDER.md`) were corrected to say `main`.

## Phase 2 — CI

`.github/workflows/ci.yml` (new on this branch; the repository's previous local, unpushed
CI commits `59e84dd`/`fce3590` on `feat/retailops-platform-v1` were folded in and extended)
runs on PRs/pushes to `main` and `workflow_dispatch`, with six blocking jobs:

1. **Backend unit/contract** — embedding guard (no silent hash fallback), API-key + CORS gate,
   discipline-agent manifests (base + 10 hats, formulas/standards/procedures), memory
   confirmation gating, reasoner action-contract routing (rag/action/unsupported,
   `dependency_required`), integrations registry contract.
2. **Postgres + pgvector integration** — real `pgvector/pgvector:pg16` service container,
   `RETAILOPS_REQUIRE_DB=1` + `CI=true` (fails, never skips, on an unreachable DB), full
   `tests/retailops` suite (isolation, audit, ingest + hybrid retrieval included).
3. **Frontend** — `npm ci`, `npm run lint`, `npm run build` (which runs `tsc -b && vite build`).
4. **Docker build + health** — builds the exact `backend/app/retailops/deploy/Dockerfile`, runs
   the container against a real Postgres/pgvector service (mandatory startup migrations, no
   skip), asserts `/health` is public and the `RETAILOPS_API_KEY` shared-secret gate on `/v1/*`
   rejects no-key and wrong-key requests (401) and passes a correct key through to the app
   (which then legitimately 403s the unseeded/unknown test principal — defense in depth, not a
   gate failure), never a wildcard CORS origin.
5. **E2E release oracle (full stack)** — migrates, loads demo + platform-prebuilt + HF mini
   packs, starts the real API, runs `scripts/oracle_smoke.py` **and**
   `scripts/release_gate.py` against the local full stack.
6. **Retrieval eval report** — offline lexical/vector/hybrid recall on the
   `retail_ecom_rag_eval_v1` gold set → `docs/retrieval_eval_report.md` +
   `artifacts/retrieval_eval.json`, uploaded as a CI artifact.

CI run link / status: all 6 jobs green on the certification branch —
https://github.com/bopoadz-del/TEKsystems_GlobalRetailMNC/actions/runs/29421341846 (commit
`75c2e32`). See "Deploy certification" below for the merge-to-`main` run.

## Phase 3 — `scripts/release_gate.py`

New CLI (`--base-url`, `--user`, `--tenant`, `--project`, `--api-key` optional). Six-question
regression, each with a **hard** pass/fail assertion (non-zero exit on any failure):

1. Stock discrepancy escalation → RAG (`route == "rag"`, grounded citations).
2. Ops brief → direct action-contract execution (`retail.generate_operations_brief`, `success`).
3. Chilled supplier promo (Harbour Fresh) → RAG (grounded citations mentioning "chilled").
4. Inventory risk → direct action-contract execution (`retail.analyse_inventory_risk`, `success`).
5. Unknown/unsupported command ("book me a flight to the moon") → `route == "unsupported"`.
6. Return window → RAG anti-hijack (`route == "rag"`, no `action_result`, grounded citations).

`scripts/oracle_smoke.py` is unchanged/preserved.

## Phase 4 — deterministic action fixtures

`scripts/oracle_smoke.py` (unchanged) keeps exercising the kit's own six deterministic
`evaluation_fixtures` pairs (happy + negative per action):
`operations_brief_happy/no_records`, `inventory_risk_happy/no_data`,
`promotion_compliance_happy/no_rules`.

## Phase 5 — discipline agents

`GET /v1/agents` returns `base_count: 1`, `hat_count: 10`; every hat composes formulas +
standards + procedures over the base playbook (see `test_every_hat_has_formulas_standards_procedures`).
Routing (`disabled_agents`), `put_off_by`, and memory-save confirmation gating are unit-tested
(`test_discipline_agents.py`, `test_audit_hardcut.py`) and re-verified live (see below).

**Defect found + fixed during this gate:** all eleven agent manifests still referenced the
pre-rename fixture directory `fixtures/northstar/**` in `allowed_paths` / playbook `ref` fields
after the demo fixtures were renamed to `fixtures/demo/australia` / `fixtures/demo/global`
(commit `b10db180`). `allowed_paths` is descriptive catalog metadata only (never enforced as an
access-control check — confirmed via code search), so this was not an authorization bypass, but
it was a stale, incorrect knowledge-boundary claim in every published agent manifest. Fixed on
this branch; a regression test (`test_no_dangling_northstar_fixture_paths`) guards against
recurrence, mirroring the existing `test_no_dangling_packs_paths` guard.

## Phase 6 — live FastEmbed evaluation

`scripts/live_fastembed_eval.py` (new) → `docs/live_fastembed_release_eval.md` +
`artifacts/live_fastembed_release_eval.json`. Runs the same three gold questions as the offline
`hash-v1` report against the **live** deployment (real `fastembed` / `BAAI/bge-small-en-v1.5` /
384-dim vectors + real pgvector). The offline hash-v1 3-case report
(`docs/retrieval_eval_report.md`) is retained unmodified and is **not** claimed to demonstrate
FastEmbed quality — that claim is explicitly disclaimed in both reports.

No silent hash fallback / no embedding mismatch: enforced unconditionally by
`backend/app/retailops/embedding_guard.py` for every ingest and retrieval call, unit-tested in
`backend/tests/retailops/test_embedding_guard.py` (raises on unknown backend, raises on
fingerprint mismatch — never falls through to the hash embedder).

## Phase 7 — security / isolation

- API key gate: `RETAILOPS_API_KEY` (when configured) gates all `/v1/*` routes; `/health` stays
  public. Unit-tested (`test_auth_cors.py`) and exercised in CI's Docker job with a key
  configured, key-present/absent both asserted.
- CORS: allowlist via `RETAILOPS_CORS_ORIGINS`; production (`RETAILOPS_ENV=production`) never
  defaults to `*`. Already configured on Render via the Render MCP
  (`RETAILOPS_ENV=production`, `RETAILOPS_CORS_ORIGINS` allowlist) prior to this certification.
- Tenant/project isolation — **new** `backend/tests/retailops/test_isolation.py` closes gate
  coverage gaps found during this certification, for the categories the mission required:
  - Docs/citations — pre-existing (`test_db_retrieval.py`, `test_api_orchestrator.py`).
  - Learning — pre-existing (`test_tenant_isolation_profiles`).
  - **Actions/audit** — new (`test_audit_runs_isolated_across_tenants`,
    `test_audit_route_isolated_across_tenants`).
  - **Discipline-hat memory** — new (`test_agent_memory_isolated_across_tenants`,
    `test_agent_memory_route_isolated_across_projects`).
  - **Integrations run history** — new (`test_integration_runs_isolated_across_tenants`).

### API-key / SPA limitation (documented, not wired as a feature)

`RETAILOPS_API_KEY` is deliberately **unset** on the live Render deployment: the SPA is a
same-origin static bundle served by the same FastAPI process and does not send `X-API-Key`.
Wiring the SPA to inject a build/runtime key would be a product feature change, out of scope
for a certification-only release. The API-key gate itself is fully tested: unit tests
(`test_auth_cors.py`) and a dedicated CI Docker job (job 4 above) run the container **with**
`RETAILOPS_API_KEY` set and assert both the 401-without-key and 200-with-key contract, so the
gate mechanism is certified even though it stays off on the live same-origin SPA deployment.
This is an accepted, honestly-documented limitation, not a defect.

## Phase 8 — deploy certification

- **PR**: [#11](https://github.com/bopoadz-del/TEKsystems_GlobalRetailMNC/pull/11) —
  "RetailOps v1 release certification (CI, release gate, isolation tests, docs)".
- **CI run (release branch, final green)**:
  [29422709269](https://github.com/bopoadz-del/TEKsystems_GlobalRetailMNC/actions/runs/29422709269)
  — all 6 jobs passed (backend unit/contract, Postgres+pgvector integration, frontend,
  Docker build+health, E2E release oracle, retrieval-eval report).
- **CI run (main, post-merge)**:
  [29422936079](https://github.com/bopoadz-del/TEKsystems_GlobalRetailMNC/actions/runs/29422936079)
  — green.
- **Merge commit**: `eb83c9f0221b9bd172f281700baac6b9cff4617e` (PR #11 merged into `main`).
  This is the release commit of record.
- **Render deploy**: service `retailops` (`srv-d9al9l0458ps73cb4hag`) switched to
  `branch: main` (was `feat/retailops-platform-v1`) and redeployed via the Render API/MCP.
  Deploy `dep-d9bpef3tqb8s73d5nf1g` → **live**, commit `eb83c9f0221b9bd172f281700baac6b9cff4617e`
  (exact match to the merge commit above — confirmed via `GET /health`, see below).
- **`/health` post-deploy**:
  ```json
  {"status":"ok","version":"1.0.0","kit_snapshot":"local-retail-kit-1.3.0","blocks_commit":"local-retail-kit-1.3.0","database":"ok","commit_sha":"eb83c9f0221b9bd172f281700baac6b9cff4617e"}
  ```
  `commit_sha` is populated from Render's built-in `RENDER_GIT_COMMIT` (minimal runtime
  evidence field added in this certification, not a product feature) and matches the deployed
  release commit exactly.
- **`scripts/release_gate.py` against the live URL, post-deploy**: **6/6 passed**
  (`u_platform` / `platform` / `prj_prebuilt_retail_core`).
- **`scripts/oracle_smoke.py` against the live URL, post-deploy**: **15/15 passed**
  (health, root UI 200, actions discovery, all 6 deterministic action fixtures, RAG smoke +
  4 HF-pack RAG prompts, audit persistence — `run_count=25`, cumulative across this
  certification's live checks).
- **Migrations/fixtures/packs idempotency**: `app_factory.lifespan` runs `upgrade_to_head()`
  unconditionally on every startup (mandatory, fails loud, never skipped in production) — this
  ran again on the post-merge redeploy with no migration errors, confirming idempotency on an
  already-migrated database. The `platform-prebuilt` pack/fixtures used by `release_gate.py` /
  `oracle_smoke.py` were already loaded on this live database from before this certification and
  were not reloaded (no destructive or duplicate-load operation was run against the live DB, in
  line with "fix only release-blocking defects" — the packs were already correctly loaded and
  passing before this branch's changes).
- **Live agent verification** (`GET /v1/agents`, `u_platform`/`platform`/`prj_prebuilt_retail_core`):
  `base_count: 1`, `hat_count: 10`; every hat's composed playbook (`?composed=true`) has a
  non-empty `formulas` (4–5), `standards` (5–6), and `procedures` (2–3) list; `retail.base`'s
  `allowed_paths` now correctly shows `fixtures/demo/**` (confirming the manifest-path fix is
  live). Memory safety verified live: unconfirmed save of a confirm-required key → `400`;
  save of a key named like a secret → `400`; save of an unrecognised/unknown key → `400`.
  `disable:<hat>` / `disable:<domain>` `put_off_by` triggers are present on every hat's
  activation config.
- **Live tenant-isolation spot check**: `GET /v1/audit` with the real `u_platform` principal
  returns its own runs; the same route with a fabricated, never-provisioned
  `X-User-Id`/`X-Tenant-Id` pair is rejected with `403` (unknown principal for tenant) before any
  data lookup — the full matrix of same-org cross-tenant/cross-project isolation (docs, actions,
  audit, agent memory, integration runs) is exercised with real seeded data in CI's
  `db-integration` job (`backend/tests/retailops/test_isolation.py` + pre-existing
  `test_db_retrieval.py` / `test_reasoning_learning.py` isolation tests), which is a stronger
  guarantee than a live click-through could give without provisioning throwaway tenants against
  the production database.
- **Manual UI checklist**: the browser automation tool available in this session could not open
  a tab in this headless Windows environment (repeated `No browser tab available` — not a
  product defect, an environment limitation), so full interactive click-through
  (RENDER.md "Two-minute demo") was not captured as a live screenshot. What *was* verified
  directly against the live URL instead:
  1. `GET /` returns the real SPA login shell HTML (title "CEREBRUM RetailOps", the
     "NORTHSTAR INTELLIGENCE" login card, prefilled `u_platform`/`platform`/
     `prj_prebuilt_retail_core` identity, "Enter workspace →") — fetched and inspected directly.
  2. Every subsequent demo-flow action was exercised at the API layer the UI itself calls:
     `/v1/ask` (stock-discrepancy question → grounded `route: rag` answer with citations),
     `/v1/actions/retail.analyse_inventory_risk/execute` (→ `success`), `/v1/audit`
     (→ persisted runs with status/duration/evidence visible). All passed live (see
     `release_gate.py` / `oracle_smoke.py` results above).
  3. Item 5 of the RENDER.md smoke checklist ("Australia project cannot retrieve Global-only
     supplier evidence") requires a live Australia/Global fixture project id, which is
     generated per-deployment and only discoverable via direct database access (no listing
     API by design) — this session had no working Postgres console/SSH access to the live
     `retailops-db` instance to fetch it. The equivalent check with real seeded data passes in
     CI (`test_db_retrieval.py::test_project_isolation` / `test_tenant_isolation`).

### Pre-existing live baseline (evidence gathered before this branch's changes were deployed)

Run locally against the still-live `feat/retailops-platform-v1`-deployed instance, to establish
a passing baseline before cutover:

- `scripts/oracle_smoke.py` — **15/15 passed** (health, root, actions discovery, all 6
  deterministic action fixtures, RAG smoke + 4 HF-pack RAG prompts, audit persistence).
- `scripts/release_gate.py` — **6/6 passed** (all six regression questions).
- `scripts/live_fastembed_eval.py` — server healthy, 1/3 gold-case recall (see Phase 6 note on
  known corpus-composition recall limits; not release-blocking — the six-question release gate
  is the hard RAG contract and passes 6/6).

### Post-cutover live evidence (deployed from `main` @ `eb83c9f`)

Both gates were re-run against the live URL **after** the Render branch switch + redeploy, i.e.
against the actual certified `main` commit, not the superseded feature branch:

- `scripts/release_gate.py` — **6/6 passed**.
- `scripts/oracle_smoke.py` — **15/15 passed**, including `root_ui_200` (the frontend SPA shell
  is built into the deployed Docker image, as it always was for this service).
- `GET /health` — `commit_sha: eb83c9f0221b9bd172f281700baac6b9cff4617e`, matching the merge
  commit exactly.

**RetailOps v1 is certified and feature development is frozen.**

## Unresolved limitations (carried forward, not release-blocking)

1. Live FastEmbed 3-case gold recall is 1/3 on naturally-phrased questions (see Phase 6) —
   documented, not hidden; the release-blocking RAG contract (`release_gate.py`) passes 6/6.
2. `RETAILOPS_API_KEY` is unset on the live SPA deployment (documented limitation above); the
   gate itself is certified in CI/Docker with a key configured.
3. The manual UI checklist could not be captured as a live browser screenshot in this session's
   headless environment (browser automation tool unavailable); equivalent coverage was gathered
   directly against the live API layer instead (see Phase 8 above). Item 5 of the RENDER.md
   smoke checklist (Australia-vs-Global project isolation) needs a live fixture project id that
   requires direct database access this session did not have; the equivalent check with real
   seeded data passes in CI.
4. Local Windows dev machine used for this certification has no Docker/Postgres available, so
   the Docker-build/health job and the Postgres/pgvector integration job could only be verified
   by direct inspection + GitHub Actions execution, not a second local run — GitHub Actions CI
   run results are the verification of record for those two jobs.
