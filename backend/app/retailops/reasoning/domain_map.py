"""Declarative retail cross-domain relationship map.

Kept data-driven so intent expansion is not scattered across if/elif branches.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# Closed set of retail intents supported by the operations reasoner.
RETAIL_INTENTS: Tuple[str, ...] = (
    "inventory",
    "promotion",
    "supplier",
    "store_operations",
    "incident",
    "compliance",
    "customer_experience",
    "workforce",
    "reporting",
    "unknown",
)

# Deterministic related-domain expansion for each primary intent.
RELATED_DOMAINS: Dict[str, List[str]] = {
    "inventory": ["supplier", "store_operations", "reporting"],
    "promotion": ["inventory", "compliance", "reporting"],
    "supplier": ["inventory", "incident"],
    "incident": ["compliance", "store_operations", "reporting"],
    "store_operations": ["inventory", "workforce"],
    "customer_experience": ["store_operations", "reporting"],
    "compliance": ["reporting"],
    "workforce": ["store_operations", "reporting"],
    "reporting": [],
    "unknown": [],
}

# Lexical cues for intent classification (order matters: first match wins after score).
INTENT_CUES: Dict[str, Tuple[str, ...]] = {
    "inventory": (
        "inventory", "stock", "sku", "reorder", "stockout", "overstock",
        "safety stock", "on hand", "on-hand", "warehouse",
    ),
    "promotion": (
        "promotion", "promo", "campaign", "display rules", "markdown", "offer",
    ),
    "supplier": (
        "supplier", "vendor", "delivery", "fulfilment", "purchase order", "otif",
        "shipment", "lead time",
    ),
    "store_operations": (
        "store operations", "operations brief", "ops brief", "store ops",
        "opening checklist", "closing checklist",
    ),
    "incident": (
        "incident", "accident", "slip", "hazard", "injury", "near miss",
    ),
    "compliance": (
        "compliance", "regulation", "policy", "food code", "advertise",
        "advertising", "ftc", "osha", "fda",
    ),
    "customer_experience": (
        "customer experience", "customer complaint", "nps", "service level",
        "queue", "checkout wait",
    ),
    "workforce": (
        "workforce", "roster", "staffing", "labour", "labor", "shift",
    ),
    "reporting": (
        "report", "dashboard", "kpi", "metric", "summary",
    ),
}

# Which registered actions are natural fits for an intent (advisory mapping).
INTENT_ACTION_HINTS: Dict[str, Tuple[str, ...]] = {
    "inventory": (
        "retail.analyse_inventory_risk",
        "retail.recommend_reorder_parameters",
        "retail.get_learning_summary",
    ),
    "promotion": ("retail.check_promotion_compliance", "retail.get_learning_summary"),
    "supplier": ("retail.get_learning_summary",),
    "store_operations": ("retail.generate_operations_brief",),
    "incident": ("retail.generate_operations_brief",),
    "compliance": ("retail.check_promotion_compliance",),
    "customer_experience": ("retail.generate_operations_brief",),
    "workforce": ("retail.generate_operations_brief",),
    "reporting": (
        "retail.generate_operations_brief",
        "retail.get_learning_summary",
    ),
    "unknown": (),
}

# Imperative verbs that indicate an action/generation request (not RAG Q&A).
ACTION_IMPERATIVES: Tuple[str, ...] = (
    "analyse",
    "analyze",
    "generate",
    "check",
    "recommend",
    "record",
    "run",
    "create",
    "produce",
    "compute",
    "calculate",
)
