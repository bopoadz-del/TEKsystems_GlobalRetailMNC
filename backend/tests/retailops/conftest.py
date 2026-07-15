"""Shared fixtures for RetailOps tests (real PostgreSQL + pgvector).

Set ``RETAILOPS_TEST_DATABASE_URL`` to point at a Postgres database with the
``vector`` extension available. Defaults to a local ``retailops_test`` DB.
Tests are skipped (not failed) if the database is unreachable, so the suite
degrades gracefully in environments without Postgres.
"""

from __future__ import annotations

import os
os.environ.setdefault("RETAILOPS_EMBED_BACKEND", "hash")

import pytest
from sqlalchemy import text

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


def _db_available() -> bool:
    from sqlalchemy import create_engine

    try:
        eng = create_engine(TEST_DB_URL)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def _migrate():
    if not _db_available():
        pytest.skip("RetailOps test database is not available")
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
