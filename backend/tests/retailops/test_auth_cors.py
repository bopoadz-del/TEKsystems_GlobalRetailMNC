"""CORS allowlist + optional RETAILOPS_API_KEY gate."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clear_app_env(monkeypatch):
    monkeypatch.delenv("RETAILOPS_API_KEY", raising=False)
    monkeypatch.setenv("RETAILOPS_CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("RETAILOPS_SKIP_MIGRATIONS", "1")
    monkeypatch.setenv(
        "RETAILOPS_DATABASE_URL",
        "postgresql+psycopg://retailops:retailops@127.0.0.1:1/retailops_none",
    )
    yield


def _client(monkeypatch):
    """Build TestClient without hanging on /health DB checks."""
    from app.retailops import app_factory

    monkeypatch.setattr(
        app_factory,
        "get_engine",
        lambda: MagicMock(**{"connect.side_effect": RuntimeError("no db in unit test")}),
    )
    # Re-import create_app after env is set so middleware picks up API key / CORS.
    return TestClient(app_factory.create_app())


def test_api_key_gates_v1_but_health_public(monkeypatch):
    monkeypatch.setenv("RETAILOPS_API_KEY", "test-secret-key")
    client = _client(monkeypatch)
    assert client.get("/health").status_code == 200
    denied = client.get(
        "/v1/overview",
        headers={"X-User-Id": "u", "X-Tenant-Id": "t", "X-Project-Id": "p"},
    )
    assert denied.status_code == 401
    bad = client.get(
        "/v1/overview",
        headers={
            "X-User-Id": "u",
            "X-Tenant-Id": "t",
            "X-Project-Id": "p",
            "X-API-Key": "wrong",
        },
    )
    assert bad.status_code == 401


def test_cors_allowlist_header(monkeypatch):
    monkeypatch.delenv("RETAILOPS_API_KEY", raising=False)
    monkeypatch.setenv("RETAILOPS_CORS_ORIGINS", "https://app.example.com")
    client = _client(monkeypatch)
    res = client.options(
        "/v1/actions",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.headers.get("access-control-allow-origin") == "https://app.example.com"
