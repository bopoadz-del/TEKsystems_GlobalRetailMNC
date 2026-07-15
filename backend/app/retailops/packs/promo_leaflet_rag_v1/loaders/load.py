"""Acquire + ingest mSOP promotion rows as short offer documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.retailops.packs import hf_common
from app.retailops.packs.promo_leaflet_rag_v1 import (
    COLLECTION_ID,
    HF_FILE,
    HF_REPO,
    LICENCE,
    MAX_SAMPLE_ROWS,
    PUBLISHER,
    RAG_PACK_ID,
    RELEASE_ID,
    SOURCE_ID,
)

PACK_ROOT = Path(__file__).resolve().parents[1]
MINI_PATH = PACK_ROOT / "fixtures_min" / "sample.jsonl"


def _field(row: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        if k in row and row[k] is not None:
            val = row[k]
            if isinstance(val, (list, tuple)):
                return ", ".join(str(x) for x in val if x is not None)
            return str(val)
    return ""


def row_to_record(row: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    brand = _field(row, "brand", "Brand", "product_brand")
    category = _field(row, "product_category", "category", "Category")
    gtin = _field(row, "gtin", "GTIN", "gtins", "GTINs")
    weight = _field(row, "product_weight", "weight")
    price = _field(row, "price", "promo_price", "offer_price")
    regular = _field(row, "regular_price", "was_price")
    discount = _field(row, "relative_discount", "absolute_discount", "discount")
    filename = _field(row, "filename", "image_filename", "file_name")
    if not any([brand, category, gtin, price]):
        return None
    title = f"Promo offer: {brand or 'Unknown brand'} — {category or 'general'}"
    lines = [
        title,
        f"Brand: {brand}" if brand else "",
        f"Category: {category}" if category else "",
        f"GTIN(s): {gtin}" if gtin else "",
        f"Weight/size: {weight}" if weight else "",
        f"Offer price: {price}" if price else "",
        f"Regular price: {regular}" if regular else "",
        f"Discount: {discount}" if discount else "",
        f"Leaflet reference: {filename}" if filename else "",
        "Source: multi-brand advertisement leaflet corpus (mSOP-765k). Not a single-store proprietary catalogue.",
    ]
    text = "\n".join(line for line in lines if line)
    if len(text) < 40:
        return None
    return {
        "title": title,
        "text": text,
        "meta": {
            "brand": brand,
            "category": category,
            "gtin": gtin,
            "price": price,
            "hf_repo": HF_REPO,
            "row_index": idx,
            "source_uri": f"hf://{HF_REPO}/{HF_FILE}",
        },
    }


def records_from_parquet(path: Path, *, limit: int = MAX_SAMPLE_ROWS) -> List[Dict[str, Any]]:
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    # Read only needed columns when present to keep RAM bounded.
    cols = set(table.column_names)
    preferred = [
        c
        for c in (
            "brand",
            "Brand",
            "product_category",
            "category",
            "gtin",
            "GTIN",
            "gtins",
            "GTINs",
            "product_weight",
            "price",
            "promo_price",
            "regular_price",
            "relative_discount",
            "absolute_discount",
            "filename",
        )
        if c in cols
    ]
    if preferred:
        table = table.select(preferred)
    if table.num_rows > limit:
        table = table.slice(0, limit)
    rows = table.to_pylist()
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        rec = row_to_record(row, i)
        if rec:
            out.append(rec)
        if len(out) >= limit:
            break
    return out


def acquire_full(cache: Optional[Path] = None) -> Dict[str, Any]:
    dest = (cache or hf_common.cache_dir()) / "msop_train.parquet"
    url = hf_common.hf_resolve_url(HF_REPO, HF_FILE)
    return hf_common.download_https(url, dest)


def load_records(*, profile: str = "mini") -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if profile == "mini":
        rows = hf_common.read_jsonl(MINI_PATH)
        return rows, {
            "profile_note": "committed_mini_fixture",
            "resolved_download_url": f"seed://{MINI_PATH}",
            "content_checksum": hf_common.sha256_file(MINI_PATH),
        }
    acq = acquire_full()
    records = records_from_parquet(Path(acq["path"]))
    return records, {**acq, "profile_note": "hf_full_sample"}


def load_pack(session, *, profile: str = "mini", force: bool = False) -> Dict[str, Any]:
    records, acq = load_records(profile=profile)
    return hf_common.ingest_text_documents(
        session,
        release_id=RELEASE_ID,
        rag_pack_id=RAG_PACK_ID,
        collection_id=COLLECTION_ID,
        source_id=SOURCE_ID,
        source_name="mSOP multi-brand promo leaflets",
        licence=LICENCE,
        publisher=PUBLISHER,
        records=records,
        force=force,
        acquisition=acq,
    )
