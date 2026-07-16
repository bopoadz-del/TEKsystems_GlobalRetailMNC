# RetailOps v1 — closure report

**Date (UTC):** 2026-07-16  
**Product:** TEKsystems Global Retail MNC — RetailOps pilot platform  
**Repo:** https://github.com/bopoadz-del/TEKsystems_GlobalRetailMNC  
**Live:** https://retailops-3ayp.onrender.com  

## Verdict

**Conditional go — pilot yes, enterprise-GA no.**

Feature development is **frozen**. Agents stay as certified: reasoner auto-selects discipline hats from chat wording; no slash `/menu` / pin / `/auto` UX. Live chat does not expose put-off toggles.

## Closure identity

| Item | Value |
|------|--------|
| Live `/health.commit_sha` | `2c6cef4b00caa1ce9e21c8f2ba179bf9f6cc1c63` |
| Tip of `main` at closure | includes certification PR #11 + pilot hotfix PR #12 |
| Certification merge | PR [#11](https://github.com/bopoadz-del/TEKsystems_GlobalRetailMNC/pull/11) → `eb83c9f…` |
| Pilot hotfix merge | PR [#12](https://github.com/bopoadz-del/TEKsystems_GlobalRetailMNC/pull/12) → `2c6cef4…` |
| Deploy branch | `main` (Render `retailops`) |
| Working principal | `u_platform` / `platform` / `prj_prebuilt_retail_core` |

Evidence pack: [release_verification.md](release_verification.md) · [pilot_guardrails.md](pilot_guardrails.md)

## What shipped (preserved)

- FastAPI + React/Vite shell
- PostgreSQL 16 + pgvector; FastEmbed `BAAI/bge-small-en-v1.5` (384); hybrid lexical/vector + RRF
- LangGraph orchestration + retail reasoner
- 1 base + 10 discipline hats (auto annotation; `disabled_agents` API opt-out)
- Actions, audit, learning, exports, enterprise connector cards (4 mock / 4 stubs)
- API-key middleware (optional) + production CORS allowlist
- Embedding-space mismatch protection
- Mandatory CI (unit, pgvector integration, frontend, Docker, E2E oracle, retrieval eval)
- HF retail packs (Bitext, SOPBench, mSOP, rescommons eval) + `retail_core_open_v1`

## Final cleaning performed at closure

- Open Dependabot PRs closed (pilot freeze); remote dependabot heads pruned via fetch
- Hotfix branch merged and deleted via PR #12
- Local scratch `_ingest_check.py` removed (already gitignored)
- Working tree on `main` clean vs `origin/main`
- Live CORS re-check: disallowed origin → HTTP 400
- Live health: `status=ok`, `database=ok`, commit matches `2c6cef4`

## Pilot must-keep (ops)

1. Private network / VPN / gateway — header identity is not SSO.
2. Keep `RETAILOPS_ENV=production` and CORS allowlist on Render.
3. Synthetic / non-sensitive data; small trusted user group.
4. Say out loud: mock integrations ≠ live vendor feeds.
5. Keep isolation + release_gate CI green; do not merge unvetted major Dependabot bumps during pilot.

## Explicitly deferred

- Real Entra / SSO / session auth
- Live SPA `RETAILOPS_API_KEY` injection (gate certified in CI/Docker only)
- Python lockfile
- Tri-brand UI polish
- Slash-command agent pin / multi-select / delegate tool
- More agents, connectors, packs, or UI redesign

## Demo path (safe)

1. Open live URL → default platform principal.
2. Ask an FDA/OSHA-style grounding question (citations).
3. Run **Inventory Risk Analysis** (Actions).
4. Show Audit + Agents catalog (1 base / 10 hats).
5. Avoid improvising numbers the model did not cite.

## Statement

```text
RetailOps v1 is certified, pilot-ready under guardrails, and feature development is frozen.
Closure complete as of 2026-07-16 UTC.
```
