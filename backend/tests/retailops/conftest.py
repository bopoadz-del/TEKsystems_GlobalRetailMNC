"""Shared fixtures for RetailOps tests (real PostgreSQL + pgvector).

Set ``RETAILOPS_TEST_DATABASE_URL`` to point at a Postgres database with the
``vector`` extension available. Defaults to a local ``retailops_test`` DB.

Locally, unreachable DBs skip. In CI (``CI=true`` or ``RETAILOPS_REQUIRE_DB=1``)
an unreachable DB **fails** the suite instead of silently skipping.
"""

from __future__ import annotations

import os
os.environ.setdefault("RETAILOPS_EMBED_BACKEND", "hash")

import pytest

TEST_DB_URL = os.getenv(
    "RETAILOPS_TEST_DATABASE_URL",
    "postgresql+psycopg://retailops:retailops@localhost:5432/retailops_test",
)

# Configure the runtime to use the test DB and skip app-startup migrations
# (the session fixture runs them explicitly).
os.environ["RETAILOPS_DATABASE_URL"] = TEST_DB_URL
os.environ["RETAILOPS_SKIP_MIGRATIONS"] = "1"

_TABLES = [
    "messages", "conversations", "action_runs", "document_chunks",
    "documents", "projects", "users", "tenants",
    "retail_transactions", "retail_promotions", "retail_stock_status",
    "retail_sales", "retail_products", "retail_pack_sources",
    "retail_learning_profiles", "retail_learning_events",
    "retail_agent_memory",
]


def _require_db() -> bool:
    flag = (os.getenv("RETAILOPS_REQUIRE_DB") or "").lower()
    if flag in ("1", "true", "yes"):
        return True
    return (os.getenv("CI") or "").lower() in ("1", "true", "yes")


def _db_available() -> bool:
    from sqlalchemy import create_engine, text

    try:
        eng = create_engine(TEST_DB_URL)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


def _ensure_db_or_abort():
    if _db_available():
        return
    msg = (
        f"RetailOps test database is not available at {TEST_DB_URL}. "
        "Start Postgres with pgvector or set RETAILOPS_TEST_DATABASE_URL."
    )
    if _require_db():
        pytest.exit(msg, returncode=1)
    pytest.skip(msg)


@pytest.fixture(scope="session")
def _migrate():
    _ensure_db_or_abort()
    from app.retailops.db import init_engine, reset_engine
    from app.retailops.migrations_runner import downgrade_to_base, upgrade_to_head

    reset_engine()
    try:
        downgrade_to_base(TEST_DB_URL)
    except Exception:
        pass
    upgrade_to_head(TEST_DB_URL)
    init_engine()
    yield


@pytest.fixture()
def db(_migrate):
    from sqlalchemy import text

    from app.retailops.db import session_scope

    with session_scope() as session:
        for tbl in _TABLES:
            session.execute(text(f"TRUNCATE TABLE {tbl} CASCADE"))
        session.commit()
    with session_scope() as session:
        yield session


@pytest.fixture()
def client(_migrate):
    from fastapi.testclient import TestClient

    from app.retailops.app_factory import create_app

    return TestClient(create_app())


@pytest.fixture()
def loaded_projects(db):
    """Load the generic demo fixture pack and commit; return {canonical: id}."""
    from app.retailops.db import session_scope
    from app.retailops.fixtures.loader import load_fixtures

    with session_scope() as session:
        ids = load_fixtures(session)
    return ids
