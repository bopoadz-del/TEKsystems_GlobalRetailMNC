"""Bind playbook formulas to real ActionRegistry / learning implementations."""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from app.retailops.agents import get_agent_catalog

# Maps playbook ``implemented_by`` tokens → concrete runtime symbols.
_IMPL_ALIASES: Dict[str, str] = {
    "learning.demand_reorder": "module:demand_reorder",
    "learning.supplier_fulfilment": "module:supplier_fulfilment",
    "learning.promotion_effectiveness": "module:promotion_effectiveness",
    "learning.store_exceptions": "module:store_exceptions",
    "learning.common.confidence_label": "fn:confidence_label",
    "retail.analyse_inventory_risk": "action:retail.analyse_inventory_risk",
    "retail.recommend_reorder_parameters": "action:retail.recommend_reorder_parameters",
    "retail.check_promotion_compliance": "action:retail.check_promotion_compliance",
    "retail.get_learning_summary": "action:retail.get_learning_summary",
    "retail.export_document": "action:retail.export_document",
    "retail.generate_operations_brief": "action:retail.generate_operations_brief",
}

# Action → formula ids that the handler is responsible for applying/disclosing.
_ACTION_FORMULAS: Dict[str, List[str]] = {
    "retail.analyse_inventory_risk": [
        "inventory.days_of_cover",
        "inventory.recommended_reorder_point",
        "inventory.safety_stock_adjust",
        "base.confidence_label",
    ],
    "retail.recommend_reorder_parameters": [
        "inventory.recommended_reorder_point",
        "inventory.safety_stock_adjust",
        "base.confidence_label",
    ],
    "retail.check_promotion_compliance": [
        "marketing.rule_coverage",
        "compliance.promo_rule_alignment",
    ],
    "retail.get_learning_summary": [
        "reporting.profile_roll_count",
        "reporting.confidence_mix",
        "base.confidence_label",
    ],
    "retail.export_document": [
        "reporting.export_bytes",
    ],
    "retail.generate_operations_brief": [
        "store_ops.exception_risk",
        "base.grounding_gate",
    ],
}


def resolve_implementation(implemented_by: Optional[str]) -> Optional[str]:
    if not implemented_by:
        return None
    return _IMPL_ALIASES.get(implemented_by)


def executable_formula_ids(agent_id: Optional[str] = None) -> List[str]:
    """Return formula ids that declare a resolvable implementation."""
    catalog = get_agent_catalog()
    agents = [catalog.get(agent_id)] if agent_id else catalog.all()
    out: List[str] = []
    seen: Set[str] = set()
    for agent in agents:
        if agent is None:
            continue
        for formula in agent.playbook.formulas:
            if not formula.implemented_by:
                continue
            if resolve_implementation(formula.implemented_by) is None:
                continue
            if formula.id in seen:
                continue
            seen.add(formula.id)
            out.append(formula.id)
    return out


def formulas_applied_by_action(action_id: str) -> List[Dict[str, str]]:
    """Public metadata for action outputs: which formulas this action applies."""
    catalog = get_agent_catalog()
    wanted = _ACTION_FORMULAS.get(action_id, [])
    by_id = {}
    for agent in catalog.all():
        for formula in agent.playbook.formulas:
            by_id[formula.id] = formula
    rows: List[Dict[str, str]] = []
    for fid in wanted:
        formula = by_id.get(fid)
        if formula is None:
            continue
        rows.append(
            {
                "id": formula.id,
                "name": formula.name,
                "expression": formula.expression,
                "implemented_by": formula.implemented_by or "",
                "resolved_as": resolve_implementation(formula.implemented_by) or "",
            }
        )
    return rows


def allowed_actions_for_hat(hat_id: Optional[str]) -> Set[str]:
    """Composed allowed actions for a hat (base ∪ hat). Empty if unknown."""
    if not hat_id:
        return set()
    catalog = get_agent_catalog()
    hat = catalog.get(hat_id)
    if hat is None or hat.kind != "hat":
        return set()
    base = catalog.get(hat.extends or "")
    allowed = set(hat.allowed_actions)
    if base is not None:
        allowed |= set(base.allowed_actions)
    return allowed
