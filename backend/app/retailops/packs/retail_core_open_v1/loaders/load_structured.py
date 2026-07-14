"""Load FreshRetailNet (pilot subset) and UCI Online Retail II into SQL tables."""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import delete, select, text
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


def _iter_fresh_parquet_batches(
    train_path: Path, *, store_limit: int, batch_rows: int = 2000
):
    """Yield filtered FreshRetailNet row dict batches without materializing all rows."""
    import pyarrow.compute as pc
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(train_path)
    total_rows = pf.metadata.num_rows
    # Contiguous store_ids 0..N-1 — avoid scanning 4.5M ids just to pick the smallest N.
    allowed = list(range(store_limit))
    keep = [
        "city_id",
        "store_id",
        "management_group_id",
        "first_category_id",
        "second_category_id",
        "third_category_id",
        "product_id",
        "dt",
        "sale_amount",
        "stock_hour6_22_cnt",
        "discount",
        "holiday_flag",
        "activity_flag",
        "precpt",
        "avg_temperature",
        "avg_humidity",
        "avg_wind_level",
    ]
    dataset = ds.dataset(str(train_path), format="parquet")
    scanner = dataset.scanner(
        columns=keep,
        filter=pc.field("store_id").isin(allowed),
        batch_size=batch_rows,
    )
    meta = {
        "parquet_rows_total": total_rows,
        "parquet_stores_total": None,
        "store_id_rule": f"contiguous_smallest_{store_limit}",
        "train_parquet": str(train_path),
    }
    yielded = 0
    for batch in scanner.to_batches():
        rows = batch.to_pylist()
        yielded += len(rows)
        yield rows, allowed, meta
    meta["parquet_rows_subset"] = yielded


def _flush_fresh_batches(
    session: Session,
    *,
    batch_prod: List[RetailProduct],
    batch_sales: List[RetailSale],
    batch_stock: List[RetailStockStatus],
    batch_promo: List[RetailPromotion],
) -> None:
    if batch_prod:
        session.bulk_save_objects(batch_prod)
    if batch_sales:
        session.bulk_save_objects(batch_sales)
    if batch_stock:
        session.bulk_save_objects(batch_stock)
    if batch_promo:
        session.bulk_save_objects(batch_promo)
    session.flush()
    session.expire_all()
    session.commit()


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

    stream_batches = None
    if rows is not None:
        data = rows
        acquisition["acquisition_method"] = "provided_rows"
        store_ids = [int(r["store_id"]) for r in data]
        allowed = select_fresh_pilot_stores(store_ids, limit=store_limit)
        filtered = [r for r in data if int(r["store_id"]) in allowed]
        stream_batches = [(filtered, allowed, {})]
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
        stream_batches = _iter_fresh_parquet_batches(train, store_limit=store_limit)
        acquisition["acquisition_method"] = "https_parquet"
        allowed = list(range(store_limit))
    else:
        data = list(MINI_FRESH_ROWS)
        acquisition["acquisition_method"] = "mini_fixture"
        warnings.append("fresh_loaded_from_mini_fixture")
        store_ids = [int(r["store_id"]) for r in data]
        allowed = select_fresh_pilot_stores(store_ids, limit=store_limit)
        filtered = [r for r in data if int(r["store_id"]) in allowed]
        stream_batches = [(filtered, allowed, {})]

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
    session.commit()

    products_seen: set = set()
    promo_keys: set = set()
    batch_sales: List[RetailSale] = []
    batch_stock: List[RetailStockStatus] = []
    batch_promo: List[RetailPromotion] = []
    batch_prod: List[RetailProduct] = []
    rows_loaded = 0
    pmeta_last: Dict[str, Any] = {}

    for filtered, allowed, pmeta in stream_batches:
        if pmeta:
            pmeta_last = pmeta
            acquisition.update(pmeta)
        for i, r in enumerate(filtered, start=rows_loaded):
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
            if len(batch_sales) >= 2000:
                _flush_fresh_batches(
                    session,
                    batch_prod=batch_prod,
                    batch_sales=batch_sales,
                    batch_stock=batch_stock,
                    batch_promo=batch_promo,
                )
                batch_prod, batch_sales, batch_stock, batch_promo = [], [], [], []
        rows_loaded += len(filtered)
        if rows_loaded and rows_loaded % 20000 == 0:
            print(f"fresh_progress rows={rows_loaded}", flush=True)

    if batch_prod or batch_sales or batch_stock or batch_promo:
        _flush_fresh_batches(
            session,
            batch_prod=batch_prod,
            batch_sales=batch_sales,
            batch_stock=batch_stock,
            batch_promo=batch_promo,
        )

    acquisition["structured_row_count"] = rows_loaded
    acquisition["subset_store_ids"] = sorted(allowed)
    acquisition["subset_rule"] = f"store_id in {store_limit} smallest distinct store_ids"
    acquisition["warnings"] = warnings
    if pmeta_last and "parquet_rows_subset" not in acquisition:
        acquisition["parquet_rows_subset"] = rows_loaded
    _upsert_source(session, acquisition, rows=rows_loaded)
    session.flush()
    return {
        "source_id": FRESH_SOURCE,
        "rows_loaded": rows_loaded,
        "stores": sorted(allowed),
        "products": len(products_seen),
        "promotions": len(promo_keys),
        "warnings": warnings,
    }


def _iter_uci_records(
    path: Path, *, row_cap: Optional[int] = None
) -> Tuple[Iterable[Dict[str, Any]], List[str]]:
    """Stream UCI Online Retail II rows from an xlsx or outer zip path."""
    import openpyxl

    warnings: List[str] = []
    raw = path.read_bytes()
    xlsx_bytes = raw
    if raw[:2] == b"PK":
        # Prefer explicit member scan — compressed nested xlsx bytes can contain the
        # literal "[Content_Types].xml" string and fool a prefix heuristic.
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
                xlsx_names = [n for n in names if n.lower().endswith(".xlsx")]
                if xlsx_names:
                    xlsx_bytes = zf.read(xlsx_names[0])
                elif "[Content_Types].xml" not in names and "[Content_Types].xml" not in {
                    n.lstrip("/") for n in names
                }:
                    raise ValueError("UCI archive is neither an xlsx nor a zip of xlsx")
                # else: raw itself is already an OOXML workbook
        except zipfile.BadZipFile as exc:
            raise ValueError(f"UCI file is not a zip/xlsx: {path}") from exc
    # Drop outer archive bytes before workbook parse.
    del raw

    def _gen() -> Iterable[Dict[str, Any]]:
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
        rejected = 0
        yielded = 0
        try:
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                headers = None
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    values = list(row)
                    if headers is None:
                        headers = [
                            str(c).strip() if c is not None else f"col{j}"
                            for j, c in enumerate(values)
                        ]
                        continue
                    if not any(values):
                        continue
                    rec = {
                        headers[j]: values[j] for j in range(min(len(headers), len(values)))
                    }
                    rec["_sheet"] = sheet
                    rec["_row"] = i
                    invoice = str(rec.get("Invoice") or rec.get("InvoiceNo") or "").strip()
                    sku = str(rec.get("StockCode") or "").strip()
                    if not invoice or not sku:
                        rejected += 1
                        continue
                    yield rec
                    yielded += 1
                    if row_cap is not None and yielded >= row_cap:
                        warnings.append(f"uci_row_cap_applied={row_cap}")
                        if rejected:
                            warnings.append(f"rejected_malformed_rows={rejected}")
                        return
            if rejected:
                warnings.append(f"rejected_malformed_rows={rejected}")
        finally:
            wb.close()

    return _gen(), warnings


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
    stream: Iterable[Dict[str, Any]]

    if rows is not None:
        stream = rows
        acquisition["acquisition_method"] = "provided_rows"
    elif use_mini_fixture or not acquire:
        stream = list(MINI_UCI_ROWS)
        acquisition["acquisition_method"] = "mini_fixture"
        warnings.append("uci_loaded_from_mini_fixture")
    else:
        acq = acquire_source(UCI_SOURCE)
        acquisition.update(acq)
        path = Path(acq["path"])
        stream, w = _iter_uci_records(path, row_cap=cap)
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
    session.commit()

    products_seen: set = set()
    cancellations = 0
    batch_txn: List[RetailTransaction] = []
    batch_prod: List[RetailProduct] = []
    rows_loaded = 0
    for i, r in enumerate(stream):
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
        if len(batch_txn) >= 2000:
            if batch_prod:
                session.bulk_save_objects(batch_prod)
            session.bulk_save_objects(batch_txn)
            batch_prod, batch_txn = [], []
            session.flush()
            session.expire_all()
            session.commit()
            if (i + 1) % 20000 == 0:
                print(f"uci_progress rows={i + 1}", flush=True)
        rows_loaded = i + 1

    if batch_prod or batch_txn:
        if batch_prod:
            session.bulk_save_objects(batch_prod)
        if batch_txn:
            session.bulk_save_objects(batch_txn)
        session.flush()
        session.commit()

    acquisition["structured_row_count"] = rows_loaded
    acquisition["warnings"] = warnings
    _upsert_source(session, acquisition, rows=rows_loaded)
    session.flush()
    return {
        "source_id": UCI_SOURCE,
        "rows_loaded": rows_loaded,
        "cancellations": cancellations,
        "products": len(products_seen),
        "warnings": warnings,
    }


def inventory_rows_from_sql(
    session: Session, *, release_id: str = RELEASE_ID, limit: int = 2000
) -> List[Dict[str, Any]]:
    """Project FreshRetailNet stock/sales into inventory action rows (capped, SQL-side)."""
    # Avoid loading the full pilot subset (~250k) into the web process.
    result = session.execute(
        text(
            """
            WITH latest AS (
              SELECT DISTINCT ON (store_id, sku)
                     store_id, sku, sale_date, sale_amount, discount
              FROM retail_sales
              WHERE release_id = :rid AND source_id = :sid
              ORDER BY store_id, sku, sale_date DESC
            )
            SELECT l.store_id, l.sku, l.sale_date, l.sale_amount, l.discount,
                   COALESCE(st.stockout_hours, 0) AS stockout_hours
            FROM latest l
            LEFT JOIN retail_stock_status st
              ON st.release_id = :rid
             AND st.source_id = :sid
             AND st.store_id = l.store_id
             AND st.sku = l.sku
             AND st.sale_date = l.sale_date
            ORDER BY COALESCE(st.stockout_hours, 0) DESC, l.sale_amount DESC
            LIMIT :lim
            """
        ),
        {"rid": release_id, "sid": FRESH_SOURCE, "lim": int(limit)},
    )
    rows: List[Dict[str, Any]] = []
    for store, sku, sale_date, sale_amount, discount, stockout_h in result:
        stockout_h = int(stockout_h or 0)
        rows.append(
            {
                "sku": sku,
                "on_hand": max(0, 16 - stockout_h),
                "reorder_point": 8,
                "average_daily_sales": float(sale_amount or 0),
                "store": store,
                "sale_date": sale_date,
                "discount": discount,
                "source_id": FRESH_SOURCE,
                "release_id": release_id,
            }
        )
    return rows
