# RetailOps pilot guardrails

**Status:** Conditional go — pilot yes, enterprise-GA no.

RetailOps v1 is certified for a **controlled pilot**. Use these rules before real customer data or a wider rollout.

## Network and identity

- Deploy only behind a **trusted network, VPN, or gateway**. Identity is header-trusted (`X-User-Id` / `X-Tenant-Id` / `X-Project-Id`) plus an optional shared `RETAILOPS_API_KEY`. That is **not** SSO or session auth.
- Anyone who can reach the API with the shared key (if set) can impersonate any known principal. Keep the URL private.
- Production must set `RETAILOPS_ENV=production` and an explicit `RETAILOPS_CORS_ORIGINS` allowlist (never leave CORS as `*`).

## Project authorization

- The server rejects unknown or cross-tenant `X-Project-Id` values (project must exist under the caller’s tenant).
- Pilot default: single tenant, small trusted user group. Prefer synthetic / non-sensitive data first.

## Integrations (honest)

| Card | Mode |
|------|------|
| POS, Inventory & WMS, Supplier/EDI, Power BI | **Mock-functional** — deterministic fictional data |
| SAP/ERP, CRM & Loyalty, Store Digital Twin, Microsoft Entra ID | **Honest stubs** — not connected |

Do not present mock connector numbers as live vendor feeds.

## CI gates that must stay green

- PostgreSQL + pgvector isolation suite (hard fail if DB unavailable in CI)
- `scripts/release_gate.py` / oracle smoke
- Embedding-space mismatch rejection (no silent FastEmbed → hash fallback)

## Explicitly out of pilot scope

- Real Entra / SSO
- Open-internet exposure without a private perimeter
- Treating mock integrations as production systems of record
