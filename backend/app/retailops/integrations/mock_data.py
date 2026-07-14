"""Shared deterministic fictional reference data for mock-functional connectors.

All values here are invented for the pilot (no real retailer, store, SKU or
supplier names). Every generator is a pure function of its inputs — same
connector id + cursor always yields the same records — so demos, screenshots
and tests are reproducible.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.retailops.integrations.base import deterministic_rng

STORE_IDS = [f"ST-{n:03d}" for n in (101, 102, 103, 104, 105)]
TILL_IDS = ["T1", "T2", "T3", "T4"]
WAREHOUSE_IDS = ["WH-NORTH", "WH-SOUTH", "WH-CENTRAL"]
PAYMENT_TYPES = ["card", "cash", "mobile_wallet", "gift_card"]
SKUS = [
    ("BEV-2201", "Sparkling Water 500ml"),
    ("SNK-1180", "Trail Mix 250g"),
    ("DRY-3305", "Pasta 500g"),
    ("CHL-4410", "Greek Yoghurt 4-pack"),
    ("HHC-5520", "Dish Soap 750ml"),
    ("BKY-6630", "Sourdough Loaf"),
    ("FRZ-7741", "Frozen Berries 400g"),
    ("PRO-8852", "Chicken Breast 1kg"),
]
SUPPLIER_IDS = ["SUP-ALPINE", "SUP-HARBOUR", "SUP-MERIDIAN"]


def sku_catalog() -> List[Dict[str, str]]:
    return [{"sku": sku, "description": desc} for sku, desc in SKUS]


def pos_transactions(seed_key: str, count: int = 12) -> List[Dict[str, Any]]:
    """Fictional vendor-shaped POS transaction feed (raw, pre-normalize)."""
    rng = deterministic_rng("pos", seed_key)
    records: List[Dict[str, Any]] = []
    for i in range(count):
        sku, _desc = rng.choice(SKUS)
        qty = rng.randint(1, 5)
        unit_price = round(rng.uniform(1.5, 24.0), 2)
        is_return = rng.random() < 0.08
        discount = round(unit_price * qty * rng.choice([0, 0, 0, 0.1, 0.15]), 2)
        records.append(
            {
                "txn_id": f"TXN-{seed_key[:4].upper()}-{i:05d}",
                "store_id": rng.choice(STORE_IDS),
                "till_id": rng.choice(TILL_IDS),
                "ts": f"2026-07-{(i % 28) + 1:02d}T{8 + (i % 10):02d}:{(i * 7) % 60:02d}:00Z",
                "sku": sku,
                "qty": qty,
                "unit_price": unit_price,
                "discount": discount,
                "payment_type": rng.choice(PAYMENT_TYPES),
                "type": "return" if is_return else "sale",
            }
        )
    return records


def wms_inventory_events(seed_key: str, count: int = 12) -> List[Dict[str, Any]]:
    """Fictional vendor-shaped WMS inventory snapshot + movement feed."""
    rng = deterministic_rng("wms", seed_key)
    records: List[Dict[str, Any]] = []
    for i in range(count):
        sku, _desc = rng.choice(SKUS)
        on_hand = rng.randint(0, 250)
        reserved = rng.randint(0, min(40, on_hand))
        reorder_point = rng.randint(20, 60)
        safety_stock = rng.randint(5, 20)
        event_type = rng.choice(["transfer", "receipt", "adjustment", "snapshot"])
        qty_delta = rng.choice([0, 0, rng.randint(-15, 15)])
        records.append(
            {
                "warehouse_id": rng.choice(WAREHOUSE_IDS),
                "store_id": rng.choice(STORE_IDS),
                "sku": sku,
                "on_hand": on_hand,
                "available": max(0, on_hand - reserved),
                "reserved": reserved,
                "reorder_point": reorder_point,
                "safety_stock": safety_stock,
                "average_daily_sales": round(rng.uniform(0.5, 12.0), 1),
                "event_type": event_type,
                "qty_delta": qty_delta,
                "ts": f"2026-07-{(i % 28) + 1:02d}T06:00:00Z",
            }
        )
    return records


def edi_supplier_orders(seed_key: str, count: int = 10) -> List[Dict[str, Any]]:
    """Fictional EDI 850/856/810-shaped supplier order + delivery feed."""
    rng = deterministic_rng("edi", seed_key)
    records: List[Dict[str, Any]] = []
    for i in range(count):
        sku, _desc = rng.choice(SKUS)
        qty_ordered = rng.randint(50, 400)
        shortfall = rng.choice([0, 0, 0, rng.randint(1, 20)])
        damaged = rng.choice([0, 0, 0, rng.randint(1, 8)])
        rejected = rng.choice([0, 0, rng.randint(1, 5)])
        qty_received = max(0, qty_ordered - shortfall - damaged - rejected)
        promised_day = (i % 27) + 1
        actual_day = promised_day + rng.choice([0, 0, 1, 2, -1])
        notice_type = rng.choice([None, None, "delay", "quality_hold", "substitution"])
        records.append(
            {
                "po_number": f"PO-{seed_key[:3].upper()}-{2600 + i}",
                "supplier_id": rng.choice(SUPPLIER_IDS),
                "sku": sku,
                "qty_ordered": qty_ordered,
                "promised_date": f"2026-07-{promised_day:02d}",
                "actual_date": f"2026-07-{max(1, min(28, actual_day)):02d}",
                "qty_received": qty_received,
                "qty_short": shortfall,
                "qty_damaged": damaged,
                "qty_rejected": rejected,
                "notice_type": notice_type,
                "notice_text": (
                    f"{notice_type.replace('_', ' ').title()} notice for {sku} on PO-{2600 + i}."
                    if notice_type
                    else None
                ),
            }
        )
    return records


def power_bi_kpi_rows(seed_key: str, count: int = 14) -> List[Dict[str, Any]]:
    """Fictional daily KPI rows for the Power BI export/publish stub."""
    rng = deterministic_rng("powerbi", seed_key)
    rows: List[Dict[str, Any]] = []
    for i in range(count):
        store = rng.choice(STORE_IDS)
        rows.append(
            {
                "date": f"2026-07-{(i % 28) + 1:02d}",
                "store_id": store,
                "total_sales": round(rng.uniform(4000, 22000), 2),
                "transaction_count": rng.randint(120, 900),
                "stockout_events": rng.randint(0, 6),
                "supplier_delay_events": rng.randint(0, 3),
            }
        )
    return rows
