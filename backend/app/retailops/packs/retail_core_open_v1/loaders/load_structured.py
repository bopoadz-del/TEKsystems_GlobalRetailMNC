"""Load FreshRetailNet (pilot subset) and UCI Online Retail II into SQL tables."""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.retailops.models import (
    RetailPackSource,
    RetailProduct,
    RetailPromotion,
    RetailSale,
    RetailStockStatus,
    RetailTransaction,
)
from app.retailops.packs.retail_core_open_v1 import RELEASE_ID
from app.retailops.packs.retail_core_open_v1.fixtures_min import MINI_FRESH_ROWS, MINI_UCI_ROWS
from app.retailops.packs.retail_core_open_v1.loaders.acquire import acquire_source
from app.retailops.packs.retail_core_open_v1.registry import get_source

FRESH_SOURCE = "freshretailnet_50k"
UCI_SOURCE = "uci_online_retail_ii"
PILOT_STORE_LIMIT = 50
# Cap UCI historical load for starter DB/job runtime while still using the full zip.
UCI_FULL_ROW_CAP = int(os.getenv("RETAILOPS_UCI_ROW_CAP", "250000"))


def _id(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return "r_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _upsert_source(session: Session, acquisition: Dict[str, Any], *, rows: int = 0) -> None:
    sid = acquisition["source_id"]
    pk = _id(RELEASE_ID, sid, "source")
    existing = session.get(RetailPackSource, pk)
    payload = {
        "id": pk,
        "release_id": RELEASE_ID,
        "source_id": sid,
        "rag_pack_id": acquisition.get("rag_pack_id"),
        "collection_id": acquisition.get("collection_id"),
        "knowledge_layer": acquisition.get("knowledge_layer") or "structured_public_eval",
        "source_name": acquisition.get("source_name") or sid,
        "source_class": acquisition.get("source_class") or "open_license",
        "authority_level": acquisition.get("authority_level") or "public_research_dataset",
        "licence": acquisition.get("licence"),
        "publisher": acquisition.get("publisher"),
        "content_checksum": acquisition.get("content_checksum"),
        "resolved_download_url": acquisition.get("resolved_download_url"),
        "acquisition_record": acquisition,
        "structured_row_count": rows,
        "status": acquisition.get("status") or "ok",
    }
    if existing:
        for k, v in payload.items():
            setattr(existing, k, v)
    else:
        session.add(RetailPackSource(**payload))


def select_fresh_pilot_stores(store_ids: Sequence[int], limit: int = PILOT_STORE_LIMIT) -> List[int]:
    """Deterministic subset: the N smallest distinct store_ids."""
    return sorted({int(s) for s in store_ids})[:limit]


def _rows_from_fresh_parquet(
    train_path: Path, *, store_limit: int
) -> Tuple[List[Dict[str, Any]], List[int], Dict[str, Any]]:
    """Filter FreshRetailNet train parquet to the pilot store subset."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    table = pq.read_table(train_path)
    store_col = table.column("store_id")
    all_stores = sorted(pc.unique(store_col).to_pylist())
    allowed = select_fresh_pilot_stores(all_stores, limit=store_limit)
    mask = pc.is_in(store_col, value_set=pa.array(allowed))
    sub = table.filter(mask)
    keep = [c for c in sub.column_names if c not in ("hours_sale", "hours_stock_status")]
    sub = sub.select(keep)
    rows = sub.to_pylist()
    meta = {
        "parquet_rows_total": table.num_rows,
        "parquet_rows_subset": len(rows),
        "parquet_stores_total": len(all_stores),
        "train_parquet": str(train_path),
    }
    return rows, allowed, meta


def load_freshretailnet(
    session: Session,
    *,
    rows: Optional[List[Dict[str, Any]]] = None,
    use_mini_fixture: bool = False,
    acquire: bool = False,
    store_limit: int = PILOT_STORE_LIMIT,
) -> Dict[str, Any]:
    """Load FreshRetailNet-shaped rows with the deterministic 50-store pilot rule."""
    meta = get_source(FRESH_SOURCE) or {}
    acquisition: Dict[str, Any] = {
        **meta,
        "release_id": RELEASE_ID,
        "rag_pack_id": "retail_core_rag",
        "collection_id": "prebuilt_retail_core",
        "knowledge_layer": "structured_public_eval",
        "status": "ok",
        "acquisition_method": "mini_fixture",
    }
    warnings: List[str] = []

    if rows is not None:
        data = rows
        acquisition["acquisition_method"] = "provided_rows"
        store_ids = [int(r["store_id"]) for r in data]
        allowed = select_fresh_pilot_stores(store_ids, limit=store_limit)
        filtered = [r for r in data if int(r["store_id"]) in allowed]
    elif acquire and not use_mini_fixture:
        acq = acquire_source(FRESH_SOURCE)
        acquisition.update(acq)
        train = Path(acq.get("train_parquet") or "")
        if not train.exists():
            root = Path(acq["path"])
            candidates = list(root.glob("**/fresh_train.parquet")) + list(
                root.glob("**/train.parquet")
            )
            if not candidates:
                raise FileNotFoundError("FreshRetailNet train parquet missing after acquire")
            train = candidates[0]
        filtered, allowed, pmeta = _rows_from_fresh_parquet(train, store_limit=store_limit)
        acquisition.update(pmeta)
        acquisition["acquisition_method"] = "https_parquet"
    else:
        data = list(MINI_FRESH_ROWS)
        acquisition["acquisition_method"] = "mini_fixture"
        warnings.append("fresh_loaded_from_mini_fixture")
        store_ids = [int(r["store_id"]) for r in data]
        allowed = select_fresh_pilot_stores(store_ids, limit=store_limit)
        filtered = [r for r in data if int(r["store_id"]) in allowed]

    session.execute(
        delete(RetailSale).where(
            RetailSale.release_id == RELEASE_ID, RetailSale.source_id == FRESH_SOURCE
        )
    )
    session.execute(
        delete(RetailStockStatus).where(
            RetailStockStatus.release_id == RELEASE_ID,
            RetailStockStatus.source_id == FRESH_SOURCE,
        )
    )
    session.execute(
        delete(RetailPromotion).where(
            RetailPromotion.release_id == RELEASE_ID,
            RetailPromotion.source_id == FRESH_SOURCE,
        )
    )
    session.execute(
        delete(RetailProduct).where(
            RetailProduct.release_id == RELEASE_ID, RetailProduct.source_id == FRESH_SOURCE
        )
    )
    session.flush()

    products_seen: set = set()
    promo_keys: set = set()
    batch_sales: List[RetailSale] = []
    batch_stock: List[RetailStockStatus] = []
    batch_promo: List[RetailPromotion] = []
    batch_prod: List[RetailProduct] = []

    for i, r in enumerate(filtered):
        store = str(r["store_id"])
        sku = str(r["product_id"])
        dt = str(r["dt"])
        if sku not in products_seen:
            products_seen.add(sku)
            batch_prod.append(
                RetailProduct(
                    id=_id(RELEASE_ID, FRESH_SOURCE, "prod", sku),
                    release_id=RELEASE_ID,
                    source_id=FRESH_SOURCE,
                    sku=sku,
                    description=f"encoded_product_{sku}",
                    category=str(r.get("third_category_id") or ""),
                    meta={
                        "real_retailer_catalogue": False,
                        "city_id": r.get("city_id"),
                        "encoded": True,
                    },
                )
            )
        batch_sales.append(
            RetailSale(
                id=_id(RELEASE_ID, FRESH_SOURCE, "sale", store, sku, dt),
                release_id=RELEASE_ID,
                source_id=FRESH_SOURCE,
                source_row=i,
                store_id=store,
                sku=sku,
                sale_date=dt,
                sale_amount=float(r.get("sale_amount") or 0),
                discount=float(r.get("discount") or 1.0),
                activity_flag=int(r.get("activity_flag") or 0),
                holiday_flag=int(r.get("holiday_flag") or 0),
                category=str(r.get("third_category_id") or ""),
                weather={
                    "precpt": r.get("precpt"),
                    "avg_temperature": r.get("avg_temperature"),
                    "avg_humidity": r.get("avg_humidity"),
                    "avg_wind_level": r.get("avg_wind_level"),
                },
                meta={"usage": "pilot analytics and benchmarking"},
            )
        )
        stockout_hours = int(r.get("stock_hour6_22_cnt") or 0)
        batch_stock.append(
            RetailStockStatus(
                id=_id(RELEASE_ID, FRESH_SOURCE, "stock", store, sku, dt),
                release_id=RELEASE_ID,
                source_id=FRESH_SOURCE,
                source_row=i,
                store_id=store,
                sku=sku,
                sale_date=dt,
                stockout_hours=stockout_hours,
                is_stockout_event=stockout_hours > 0,
                meta={},
            )
        )
        if float(r.get("discount") or 1.0) < 1.0 or int(r.get("activity_flag") or 0) == 1:
            key = (store, sku, dt)
            if key not in promo_keys:
                promo_keys.add(key)
                batch_promo.append(
                    RetailPromotion(
                        id=_id(RELEASE_ID, FRESH_SOURCE, "promo", store, sku, dt),
                        release_id=RELEASE_ID,
                        source_id=FRESH_SOURCE,
                        store_id=store,
                        sku=sku,
                        period_start=dt,
                        period_end=dt,
                        discount=float(r.get("discount") or 1.0),
                        activity_flag=int(r.get("activity_flag") or 0),
                        meta={},
                    )
                )
        if len(batch_sales) >= 5000:
            session.bulk_save_objects(batch_prod)
            session.bulk_save_objects(batch_sales)
            session.bulk_save_objects(batch_stock)
            session.bulk_save_objects(batch_promo)
            batch_prod, batch_sales, batch_stock, batch_promo = [], [], [], []
            session.flush()

    if batch_prod or batch_sales or batch_stock or batch_promo:
        session.bulk_save_objects(batch_prod)
        session.bulk_save_objects(batch_sales)
        session.bulk_save_objects(batch_stock)
        session.bulk_save_objects(batch_promo)
        session.flush()

    acquisition["structured_row_count"] = len(filtered)
    acquisition["subset_store_ids"] = sorted(allowed)
    acquisition["subset_rule"] = f"store_id in {store_limit} smallest distinct store_ids"
    acquisition["warnings"] = warnings
    _upsert_source(session, acquisition, rows=len(filtered))
    session.flush()
    return {
        "source_id": FRESH_SOURCE,
        "rows_loaded": len(filtered),
        "stores": sorted(allowed),
        "products": len(products_seen),
        "promotions": len(promo_keys),
        "warnings": warnings,
    }


def _parse_uci_xlsx_bytes(
    data: bytes, *, row_cap: Optional[int] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    import openpyxl

    warnings: List[str] = []
    xlsx_bytes = data
    if data[:2] == b"PK" and b"[Content_Types].xml" not in data[:4096]:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".xlsx")]
            if not names:
                raise ValueError("UCI zip contained no xlsx")
            xlsx_bytes = zf.read(names[0])
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    rows_out: List[Dict[str, Any]] = []
    rejected = 0
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        headers = None
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            values = list(row)
            if headers is None:
                headers = [
                    str(c).strip() if c is not None else f"col{j}" for j, c in enumerate(values)
                ]
                continue
            if not any(values):
                continue
            rec = {headers[j]: values[j] for j in range(min(len(headers), len(values)))}
            rec["_sheet"] = sheet
            rec["_row"] = i
            invoice = str(rec.get("Invoice") or rec.get("InvoiceNo") or "").strip()
            sku = str(rec.get("StockCode") or "").strip()
            if not invoice or not sku:
                rejected += 1
                continue
            rows_out.append(rec)
            if row_cap is not None and len(rows_out) >= row_cap:
                warnings.append(f"uci_row_cap_applied={row_cap}")
                if rejected:
                    warnings.append(f"rejected_malformed_rows={rejected}")
                return rows_out, warnings
    if rejected:
        warnings.append(f"rejected_malformed_rows={rejected}")
    return rows_out, warnings


def load_uci_online_retail_ii(
    session: Session,
    *,
    rows: Optional[List[Dict[str, Any]]] = None,
    use_mini_fixture: bool = False,
    acquire: bool = False,
    row_cap: Optional[int] = None,
) -> Dict[str, Any]:
    meta = get_source(UCI_SOURCE) or {}
    warnings: List[str] = []
    acquisition: Dict[str, Any] = {
        **meta,
        "release_id": RELEASE_ID,
        "rag_pack_id": "retail_core_rag",
        "collection_id": "prebuilt_retail_core",
        "knowledge_layer": "structured_public_eval",
        "status": "ok",
    }

    cap = UCI_FULL_ROW_CAP if row_cap is None else row_cap

    if rows is not None:
        data = rows
        acquisition["acquisition_method"] = "provided_rows"
    elif use_mini_fixture or not acquire:
        data = list(MINI_UCI_ROWS)
        acquisition["acquisition_method"] = "mini_fixture"
        warnings.append("uci_loaded_from_mini_fixture")
    else:
        acq = acquire_source(UCI_SOURCE)
        acquisition.update(acq)
        path = Path(acq["path"])
        data, w = _parse_uci_xlsx_bytes(path.read_bytes(), row_cap=cap)
        warnings.extend(w)

    session.execute(
        delete(RetailTransaction).where(
            RetailTransaction.release_id == RELEASE_ID,
            RetailTransaction.source_id == UCI_SOURCE,
        )
    )
    session.execute(
        delete(RetailProduct).where(
            RetailProduct.release_id == RELEASE_ID, RetailProduct.source_id == UCI_SOURCE
        )
    )
    session.flush()

    products_seen: set = set()
    cancellations = 0
    batch_txn: List[RetailTransaction] = []
    batch_prod: List[RetailProduct] = []
    for i, r in enumerate(data):
        invoice = str(r.get("Invoice") or r.get("InvoiceNo") or "").strip()
        sku = str(r.get("StockCode") or "").strip()
        qty = float(r.get("Quantity") or 0)
        is_cancel = invoice.upper().startswith("C") or qty < 0
        if is_cancel:
            cancellations += 1
        if sku and sku not in products_seen:
            products_seen.add(sku)
            batch_prod.append(
                RetailProduct(
                    id=_id(RELEASE_ID, UCI_SOURCE, "prod", sku),
                    release_id=RELEASE_ID,
                    source_id=UCI_SOURCE,
                    sku=sku,
                    description=str(r.get("Description") or ""),
                    meta={
                        "current_retail_intelligence": False,
                        "period": "2009-2011",
                    },
                )
            )
        batch_txn.append(
            RetailTransaction(
                id=_id(RELEASE_ID, UCI_SOURCE, "txn", invoice, sku, i),
                release_id=RELEASE_ID,
                source_id=UCI_SOURCE,
                source_row=int(r.get("_row") or i),
                source_sheet=str(r.get("_sheet") or ""),
                invoice=invoice,
                sku=sku,
                description=str(r.get("Description") or ""),
                quantity=qty,
                invoice_date=str(r.get("InvoiceDate") or ""),
                unit_price=float(r.get("UnitPrice") or 0) if r.get("UnitPrice") is not None else None,
                customer_id=str(r.get("CustomerID") or "") or None,
                country=str(r.get("Country") or "") or None,
                is_cancellation=is_cancel,
                meta={"usage": "historical evaluation and demonstration data"},
            )
        )
        if len(batch_txn) >= 5000:
            session.bulk_save_objects(batch_prod)
            session.bulk_save_objects(batch_txn)
            batch_prod, batch_txn = [], []
            session.flush()

    if batch_prod or batch_txn:
        session.bulk_save_objects(batch_prod)
        session.bulk_save_objects(batch_txn)
        session.flush()

    acquisition["structured_row_count"] = len(data)
    acquisition["warnings"] = warnings
    _upsert_source(session, acquisition, rows=len(data))
    session.flush()
    return {
        "source_id": UCI_SOURCE,
        "rows_loaded": len(data),
        "cancellations": cancellations,
        "products": len(products_seen),
        "warnings": warnings,
    }


def inventory_rows_from_sql(session: Session, *, release_id: str = RELEASE_ID) -> List[Dict[str, Any]]:
    """Project structured FreshRetailNet stock/sales into inventory action row aliases."""
    sales = session.execute(
        select(RetailSale).where(RetailSale.release_id == release_id)
    ).scalars().all()
    stock = {
        (s.store_id, s.sku, s.sale_date): s
        for s in session.execute(
            select(RetailStockStatus).where(RetailStockStatus.release_id == release_id)
        ).scalars().all()
    }
    latest: Dict[Tuple[str, str], RetailSale] = {}
    for s in sales:
        key = (s.store_id, s.sku)
        prev = latest.get(key)
        if prev is None or s.sale_date > prev.sale_date:
            latest[key] = s

    rows: List[Dict[str, Any]] = []
    for (store, sku), s in latest.items():
        st = stock.get((store, sku, s.sale_date))
        stockout_h = int(st.stockout_hours or 0) if st else 0
        on_hand = max(0, 16 - stockout_h)
        rows.append(
            {
                "sku": sku,
                "on_hand": on_hand,
                "reorder_point": 8,
                "average_daily_sales": float(s.sale_amount or 0),
                "store": store,
                "sale_date": s.sale_date,
                "discount": s.discount,
                "source_id": FRESH_SOURCE,
                "release_id": release_id,
            }
        )
    return rows
