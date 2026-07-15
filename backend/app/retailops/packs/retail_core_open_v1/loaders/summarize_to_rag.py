"""Generate controlled analytical summaries and embed them (never raw row dumps)."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.retailops.embeddings import get_embedder
from app.retailops.models import Document, DocumentChunk, RetailSale, RetailStockStatus, RetailTransaction
from app.retailops.packs.retail_core_open_v1 import (
    COLLECTION_ID,
    PLATFORM_TENANT_ID,
    RAG_PACK_ID,
    RELEASE_ID,
)
from app.retailops.packs.retail_core_open_v1.loaders.ingest_text import ensure_platform_project

FRESH = "freshretailnet_50k"
UCI = "uci_online_retail_ii"


def _doc_id(kind: str, key: str) -> str:
    return "doc_" + hashlib.sha256(f"{RELEASE_ID}|summary|{kind}|{key}".encode()).hexdigest()[:20]


def _chunk_id(document_id: str, text: str) -> str:
    return "ch_" + hashlib.sha256(f"{document_id}|0|{text[:160]}".encode()).hexdigest()[:24]


def _persist_summary(
    session: Session,
    *,
    project_id: str,
    kind: str,
    key: str,
    title: str,
    body: str,
    lineage: Dict[str, Any],
) -> str:
    document_id = _doc_id(kind, key)
    existing = session.get(Document, document_id)
    if existing:
        return document_id
    embedder = get_embedder()
    text = f"{title}\n\n{body}"
    vector = embedder.embed(text)
    meta = {
        "release_id": RELEASE_ID,
        "rag_pack_id": RAG_PACK_ID,
        "collection_id": COLLECTION_ID,
        "knowledge_layer": "platform_prebuilt",
        "source_class": "open_license",
        "authority_level": "public_research_dataset",
        "doc_role": "open_dataset_summary",
        "summary_type": kind,
        "not_governing_policy": True,
        **lineage,
    }
    session.add(
        Document(
            id=document_id,
            tenant_id=PLATFORM_TENANT_ID,
            project_id=project_id,
            filename=f"summary_{kind}_{key}.md",
            content_type="text/markdown",
            source_uri=f"summary://{RELEASE_ID}/{kind}/{key}",
            status="processed",
            chunk_count=1,
            meta=meta,
        )
    )
    session.add(
        DocumentChunk(
            id=_chunk_id(document_id, text),
            tenant_id=PLATFORM_TENANT_ID,
            project_id=project_id,
            document_id=document_id,
            chunk_ordinal=0,
            text=text,
            embedding=vector,
            source_filename=f"summary_{kind}.md",
            meta=meta,
        )
    )
    return document_id


def generate_summaries(session: Session, *, limit: int = 40) -> Dict[str, Any]:
    project_id = ensure_platform_project(session)
    created: List[str] = []

    # store × SKU × day (top stockout events)
    stocks = session.execute(
        select(RetailStockStatus)
        .where(RetailStockStatus.release_id == RELEASE_ID, RetailStockStatus.is_stockout_event.is_(True))
        .limit(limit)
    ).scalars().all()
    for s in stocks:
        created.append(
            _persist_summary(
                session,
                project_id=project_id,
                kind="stockout_event",
                key=f"{s.store_id}_{s.sku}_{s.sale_date}",
                title=f"Stockout event summary — store {s.store_id} SKU {s.sku} on {s.sale_date}",
                body=(
                    f"Analytical summary (not a governing policy document).\n"
                    f"Source dataset: FreshRetailNet-50K ({FRESH}).\n"
                    f"Store={s.store_id} SKU={s.sku} date={s.sale_date} "
                    f"stockout_hours={s.stockout_hours}.\n"
                    f"Lineage: retail_stock_status.id={s.id}."
                ),
                lineage={
                    "source_id": FRESH,
                    "source_dataset": "FreshRetailNet-50K",
                    "summary_type": "stockout_event",
                    "store_id": s.store_id,
                    "sku": s.sku,
                    "source_period": s.sale_date,
                    "aggregation_lineage": f"retail_stock_status:{s.id}",
                },
            )
        )

    # store × category × week rollup from sales
    by_week: Dict[str, List[RetailSale]] = defaultdict(list)
    for sale in session.execute(
        select(RetailSale).where(RetailSale.release_id == RELEASE_ID).limit(500)
    ).scalars().all():
        week = sale.sale_date[:8] + "W"  # coarse key from date prefix
        key = f"{sale.store_id}|{sale.category}|{week}"
        by_week[key].append(sale)
    for i, (key, items) in enumerate(by_week.items()):
        if i >= limit:
            break
        store, category, week = key.split("|")
        total = sum(float(x.sale_amount or 0) for x in items)
        created.append(
            _persist_summary(
                session,
                project_id=project_id,
                kind="store_category_week",
                key=key.replace("|", "_"),
                title=f"Store×category×week summary — store {store} category {category}",
                body=(
                    f"Analytical summary derived from retail_sales.\n"
                    f"Store={store} category={category} period_key={week} "
                    f"rows={len(items)} sale_amount_sum={total:.4f}.\n"
                    f"Source dataset: FreshRetailNet-50K."
                ),
                lineage={
                    "source_id": FRESH,
                    "source_dataset": "FreshRetailNet-50K",
                    "summary_type": "store_category_week",
                    "store_id": store,
                    "aggregation_lineage": f"retail_sales filter store={store} category={category}",
                },
            )
        )

    # Promotion period summaries
    promo_sales = [
        s
        for s in session.execute(
            select(RetailSale).where(RetailSale.release_id == RELEASE_ID).limit(200)
        ).scalars().all()
        if (s.discount is not None and s.discount < 1.0) or (s.activity_flag == 1)
    ]
    for s in promo_sales[:limit]:
        created.append(
            _persist_summary(
                session,
                project_id=project_id,
                kind="promotion_period",
                key=f"{s.store_id}_{s.sku}_{s.sale_date}",
                title=f"Promotion-period summary — store {s.store_id} SKU {s.sku}",
                body=(
                    f"Discount/activity analytical summary.\n"
                    f"date={s.sale_date} discount={s.discount} activity_flag={s.activity_flag} "
                    f"sale_amount={s.sale_amount}.\n"
                    f"Source: FreshRetailNet-50K sale id={s.id}."
                ),
                lineage={
                    "source_id": FRESH,
                    "source_dataset": "FreshRetailNet-50K",
                    "summary_type": "promotion_period",
                    "aggregation_lineage": f"retail_sales:{s.id}",
                },
            )
        )

    # Transaction anomalies (cancellations)
    cancels = session.execute(
        select(RetailTransaction)
        .where(
            RetailTransaction.release_id == RELEASE_ID,
            RetailTransaction.is_cancellation.is_(True),
        )
        .limit(limit)
    ).scalars().all()
    for t in cancels:
        created.append(
            _persist_summary(
                session,
                project_id=project_id,
                kind="transaction_anomaly",
                key=f"{t.invoice}_{t.sku}",
                title=f"Transaction anomaly (cancellation) — invoice {t.invoice}",
                body=(
                    f"Historical evaluation summary from UCI Online Retail II.\n"
                    f"invoice={t.invoice} sku={t.sku} qty={t.quantity} "
                    f"date={t.invoice_date} country={t.country}.\n"
                    f"Not current retail intelligence. Lineage: retail_transactions.id={t.id}."
                ),
                lineage={
                    "source_id": UCI,
                    "source_dataset": "UCI Online Retail II",
                    "summary_type": "transaction_anomaly",
                    "aggregation_lineage": f"retail_transactions:{t.id}",
                },
            )
        )

    # store × SKU × day sales snapshot samples
    for s in session.execute(
        select(RetailSale).where(RetailSale.release_id == RELEASE_ID).limit(min(limit, 20))
    ).scalars().all():
        created.append(
            _persist_summary(
                session,
                project_id=project_id,
                kind="store_sku_day",
                key=f"{s.store_id}_{s.sku}_{s.sale_date}",
                title=f"Store×SKU×day summary — store {s.store_id} SKU {s.sku} {s.sale_date}",
                body=(
                    f"Daily analytical summary.\n"
                    f"sale_amount={s.sale_amount} discount={s.discount}.\n"
                    f"Source: FreshRetailNet-50K sale id={s.id}."
                ),
                lineage={
                    "source_id": FRESH,
                    "source_dataset": "FreshRetailNet-50K",
                    "summary_type": "store_sku_day",
                    "aggregation_lineage": f"retail_sales:{s.id}",
                },
            )
        )

    session.flush()
    return {"summaries_upserted": len(set(created)), "document_ids": sorted(set(created))}
