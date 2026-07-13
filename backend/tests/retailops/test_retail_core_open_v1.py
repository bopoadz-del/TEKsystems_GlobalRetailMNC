"""Tests for retail_core_open_v1 pack (manifest, policy, structured load, isolation)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.retailops.models import Document, RetailSale, RetailTransaction
from app.retailops.packs.retail_core_open_v1 import (
    COLLECTION_ID,
    PLATFORM_TENANT_ID,
    RAG_PACK_ID,
    RELEASE_ID,
)
from app.retailops.packs.retail_core_open_v1.loaders.ingest_text import ingest_all_text
from app.retailops.packs.retail_core_open_v1.loaders.load_structured import (
    inventory_rows_from_sql,
    load_freshretailnet,
    load_uci_online_retail_ii,
    select_fresh_pilot_stores,
)
from app.retailops.packs.retail_core_open_v1.loaders.summarize_to_rag import generate_summaries
from app.retailops.packs.retail_core_open_v1.registry import (
    SourcePolicyError,
    load_manifest,
    release_identity,
    validate_source_record,
)


def test_release_identity_and_manifest():
    ident = release_identity()
    assert ident["release_id"] == RELEASE_ID
    assert ident["rag_pack_id"] == RAG_PACK_ID
    assert ident["collection_id"] == COLLECTION_ID
    sources = load_manifest()["sources"]
    ids = {s["source_id"] for s in sources}
    assert "fda_food_code_2022" in ids
    assert "freshretailnet_50k" in ids
    assert "uci_online_retail_ii" in ids


def test_source_policy_rejects_unknown_and_tenant():
    with pytest.raises(SourcePolicyError):
        validate_source_record(
            {
                "source_id": "x",
                "source_name": "x",
                "source_class": "unknown_license",
                "authority_level": "none",
            }
        )
    with pytest.raises(SourcePolicyError):
        validate_source_record(
            {
                "source_id": "x",
                "source_name": "x",
                "source_class": "official_guidance",
                "authority_level": "official_guidance",
                "publisher": "FDA",
                "knowledge_layer": "tenant_project",
            }
        )


def test_fresh_subset_rule_deterministic():
    assert select_fresh_pilot_stores([9, 1, 5, 1, 3], limit=3) == [1, 3, 5]


def test_structured_load_and_inventory_projection(db):
    report = load_freshretailnet(db, use_mini_fixture=True)
    assert report["rows_loaded"] > 0
    uci = load_uci_online_retail_ii(db, use_mini_fixture=True)
    assert uci["rows_loaded"] >= 3
    assert uci["cancellations"] >= 1
    sales = db.execute(select(RetailSale).where(RetailSale.release_id == RELEASE_ID)).scalars().all()
    assert sales
    txns = db.execute(
        select(RetailTransaction).where(RetailTransaction.release_id == RELEASE_ID)
    ).scalars().all()
    assert any(t.is_cancellation for t in txns)
    rows = inventory_rows_from_sql(db)
    assert rows and all("sku" in r and "on_hand" in r for r in rows)


def test_text_and_summaries_stay_on_platform_tenant(db):
    text_report = ingest_all_text(db)
    assert text_report
    assert all(r["status"] in ("ingested", "idempotent_skip") for r in text_report)
    load_freshretailnet(db, use_mini_fixture=True)
    load_uci_online_retail_ii(db, use_mini_fixture=True)
    summaries = generate_summaries(db, limit=10)
    assert summaries["summaries_upserted"] >= 1
    docs = db.execute(
        select(Document).where(Document.tenant_id == PLATFORM_TENANT_ID)
    ).scalars().all()
    assert docs
    assert all((d.meta or {}).get("knowledge_layer") == "platform_prebuilt" for d in docs)


def test_inventory_action_prefers_sql_rows(client, db):
    from app.retailops import bootstrap
    from app.retailops.fixtures.loader import MANAGER_ID, TENANT_ID

    load_freshretailnet(db, use_mini_fixture=True)
    bootstrap.ensure_tenant(db, TENANT_ID, "Retail Demo Tenant")
    bootstrap.ensure_user(
        db, MANAGER_ID, TENANT_ID, permissions=["retail:read", "retail:analyse"]
    )
    project = bootstrap.ensure_project(db, tenant_id=TENANT_ID, canonical_name="Global Region")
    db.commit()
    r = client.post(
        "/v1/actions/retail.analyse_inventory_risk/execute",
        headers={
            "X-User-Id": MANAGER_ID,
            "X-Tenant-Id": TENANT_ID,
            "X-Project-Id": project.id,
        },
        json={"arguments": {}},
    )
    body = r.json()
    assert body["status"] == "success"
    assert body["output"]["summary"]["skus_analysed"] > 0


def test_pack_status_endpoint(client, db):
    load_freshretailnet(db, use_mini_fixture=True)
    db.commit()
    r = client.get("/v1/packs/retail_core_open_v1")
    assert r.status_code == 200
    body = r.json()
    assert body["identity"]["release_id"] == RELEASE_ID
    assert body["counts"]["retail_sales"] > 0
