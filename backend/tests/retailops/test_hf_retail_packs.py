"""Unit tests for Hugging Face retail RAG pack loaders (mini fixtures)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.retailops.packs.promo_leaflet_rag_v1.loaders import load as promo_load
from app.retailops.packs.retail_cx_policies_v1.loaders import load as cx_load
from app.retailops.packs.retail_ecom_rag_eval_v1.loaders import load as eval_load
from app.retailops.packs.retail_ops_sops_v1.loaders import load as sops_load


def test_cx_mini_records_have_policy_text():
    records, acq = cx_load.load_records(profile="mini")
    assert len(records) >= 4
    assert any("return" in r["text"].lower() for r in records)
    assert acq["profile_note"] == "committed_mini_fixture"
    assert Path(acq["resolved_download_url"].replace("seed://", "")).exists() or "seed://" in acq[
        "resolved_download_url"
    ]


def test_sops_mini_covers_four_domains():
    records, _ = sops_load.load_records(profile="mini")
    domains = {r.get("meta", {}).get("sop_domain") for r in records}
    assert domains >= {
        "email_intent",
        "customer_service",
        "warehouse_package_inspection",
        "order_fulfillment",
    }


def test_promo_mini_has_gtin_offers():
    records, _ = promo_load.load_records(profile="mini")
    assert len(records) >= 3
    assert any("GTIN" in r["text"] for r in records)
    assert any("multi-brand" in r["text"].lower() for r in records)


def test_rescommons_mini_eval_and_docs():
    cases, docs, acq = eval_load.load_eval_and_docs(profile="mini")
    assert len(cases) >= 2
    assert cases[0]["question"]
    assert cases[0]["expected_answer_contains"]
    assert len(docs) >= 1
    assert acq["profile_note"] == "committed_mini_fixture"


def test_promo_row_to_record_normalizes():
    rec = promo_load.row_to_record(
        {
            "brand": "DemoBrand",
            "product_category": "snacks",
            "gtin": "123",
            "price": "1.00",
            "regular_price": "2.00",
        },
        0,
    )
    assert rec is not None
    assert "DemoBrand" in rec["title"]
    assert "1.00" in rec["text"]


def test_cx_csv_sampler_caps_per_intent():
    from app.retailops.packs.retail_cx_policies_v1 import SAMPLE_PER_INTENT

    csv_text = (
        "instruction,category,intent,response\n"
        + "\n".join(
            f"q{i},RETURNS,return_policy,{'This is a sufficiently long return policy answer number ' + str(i) + '.' * 40}"
            for i in range(200)
        )
        + "\n"
    )
    records = cx_load._records_from_csv_text(csv_text)
    assert len(records) <= SAMPLE_PER_INTENT
