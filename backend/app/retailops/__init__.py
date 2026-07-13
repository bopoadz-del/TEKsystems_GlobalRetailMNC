"""RetailOps standalone product runtime (TEKsystems Global Retail MNC).

This package is the deployable retail-operations product: PostgreSQL/pgvector
persistence, hybrid retrieval, ingestion, citations, LLM providers, a LangGraph
orchestrator, generic action APIs, audit persistence, and a business UI.

The action contract + Retail kit live under :mod:`app.retailops.kit` as a
**local kit snapshot** shipped with this repository. Upstream CerebrumDev.ai /
Cerebrum-Blocks may be used as design references; this product does not depend
on a live pin to those remotes.
"""

RETAILOPS_VERSION = "1.0.0"

# Local kit snapshot id (not a Git commit SHA). Kept as BLOCKS_COMMIT for
# backward-compatible /health JSON and build metadata fields.
KIT_SNAPSHOT_ID = "local-retail-kit-1.2.0"
BLOCKS_COMMIT = KIT_SNAPSHOT_ID
