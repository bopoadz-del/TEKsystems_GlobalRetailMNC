"""Unit tests for embedding-space safety (no Postgres required)."""

from __future__ import annotations

import pytest

from app.retailops.embedding_guard import EmbeddingSpaceError, fingerprint
from app.retailops.embeddings import HashEmbeddingProvider, get_embedder, reset_embedder


def test_fingerprint_hash_backend(monkeypatch):
    monkeypatch.setenv("RETAILOPS_EMBED_BACKEND", "hash")
    reset_embedder()
    fp = fingerprint(get_embedder())
    assert fp["embedding_model"] == "hash-v1"
    assert fp["embedding_dim"] == 384


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("RETAILOPS_EMBED_BACKEND", "azure")
    reset_embedder()
    with pytest.raises(ValueError, match="Unknown RETAILOPS_EMBED_BACKEND"):
        get_embedder()


def test_assert_compatible_mismatch(monkeypatch):
    from unittest.mock import MagicMock

    from app.retailops.embedding_guard import assert_compatible

    monkeypatch.setenv("RETAILOPS_EMBED_BACKEND", "hash")
    reset_embedder()
    session = MagicMock()
    # Simulate existing BGE corpus while active embedder is hash.
    session.execute.return_value.scalars.return_value = iter(
        [{"embedding_model": "BAAI/bge-small-en-v1.5", "embedding_dim": 384}]
    )
    with pytest.raises(EmbeddingSpaceError, match="mismatch"):
        assert_compatible(
            session,
            tenant_id="t1",
            project_id="p1",
            embedder=HashEmbeddingProvider(),
        )


def test_assert_compatible_ok_empty_project(monkeypatch):
    from unittest.mock import MagicMock

    from app.retailops.embedding_guard import assert_compatible

    monkeypatch.setenv("RETAILOPS_EMBED_BACKEND", "hash")
    reset_embedder()
    session = MagicMock()
    session.execute.return_value.scalars.return_value = iter([])
    fp = assert_compatible(session, tenant_id="t1", project_id="p1")
    assert fp["embedding_model"] == "hash-v1"
