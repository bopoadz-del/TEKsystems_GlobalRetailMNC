"""Retail domain actions for the RetailOps pilot.

Pilot handlers are deterministic (no LLM calls in the handler body). Learning
actions write verified outcomes only; advisory profiles never overwrite source
systems automatically.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.retailops.kit.contract.models import (
    ActionContext,
    ActionDependency,
    ActionEvidence,
    ActionOutcome,
    ActionSpec,
    ActionStatus,
)
from app.retailops.kit.domains.retail import RETAIL_KIT_VERSION
from app.retailops.kit.domains.retail import schemas as S

_PERM_READ = "retail:read"
_PERM_ANALYSE = "retail:analyse"
_PERM_LEARNING_WRITE = "retail:learning_write"


def _with_formulas(action_id: str, output: Dict[str, Any]) -> Dict[str, Any]:
    """Attach playbook formula metadata for formulas this action actually applies."""
    from app.retailops.agents.formulas import formulas_applied_by_action

    enriched = dict(output or {})
    enriched["applied_formulas"] = formulas_applied_by_action(action_id)
    return enriched


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record_evidence(rec: Dict[str, Any]) -> ActionEvidence:
    return ActionEvidence(
        source_id=rec.get("source_id"),
        document_id=rec.get("document_id"),
        filename=rec.get("filename"),
        page=rec.get("page"),
        sheet=rec.get("sheet"),
        row_start=rec.get("row_start"),
        row_end=rec.get("row_end"),
        chunk_id=rec.get("chunk_id"),
        excerpt=(rec.get("text") or "")[:280] or None,
        score=rec.get("score"),
    )


def _classify_record(text: str) -> List[str]:
    """Return the operational signal categories a record touches."""
    t = text.lower()
    cats: List[str] = []
    if any(k in t for k in ["stock", "sku", "inventory", "on hand", "reorder", "stockout", "discrepancy", "variance", "count"]):
        cats.append("inventory")
    if any(k in t for k in ["promotion", "promo", "display", "campaign", "discount", "endcap", "signage", "planogram"]):
        cats.append("promotion")
    if any(k in t for k in ["supplier", "vendor", "delivery", "shipment", "notice", "recall", "lead time", "chilled", "backorder"]):
        cats.append("supplier")
    if any(k in t for k in ["incident", "injury", "accident", "safety", "escalat", "hazard", "spill", "theft"]):
        cats.append("incident")
    return cats


def _first_sentence(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    for sep in (". ", "! ", "? ", "\n"):
        idx = text.find(sep)
        if 0 < idx < limit:
            return text[: idx + 1].strip()
    return text[:limit].strip()


# ---------------------------------------------------------------------------
# A. generate_operations_brief
# ---------------------------------------------------------------------------

async def generate_operations_brief(
    context: ActionContext, arguments: Dict[str, Any]
) -> ActionOutcome:
    records: List[Dict[str, Any]] = [
        r for r in (arguments.get("records") or []) if (r.get("text") or "").strip()
    ]
    if not records:
        return ActionOutcome.dependency(
            [
                ActionDependency(
                    kind="operational_records",
                    description=(
                        "At least one operational record (incident report, supplier "
                        "notice, inventory record or merchandising instruction) is "
                        "required to generate an operations brief."
                    ),
                    hint="Ingest project documents or provide records for the requested period.",
                )
            ],
            metadata={"period": arguments.get("period")},
        )

    signals: Dict[str, List[Dict[str, Any]]] = {
        "inventory": [],
        "promotion": [],
        "supplier": [],
        "incident": [],
    }
    evidence: List[ActionEvidence] = []
    for rec in records:
        text = rec["text"]
        ev = _record_evidence(rec)
        evidence.append(ev)
        entry = {
            "summary": _first_sentence(text),
            "source": rec.get("filename") or rec.get("source_id") or rec.get("document_id"),
            "document_id": rec.get("document_id"),
            "page": rec.get("page"),
        }
        for cat in _classify_record(text) or ["incident"]:
            if cat in signals:
                signals[cat].append(entry)

    priority_actions: List[Dict[str, Any]] = []
    if signals["incident"]:
        priority_actions.append(
            {"priority": "high", "action": "Review and close open store incidents", "count": len(signals["incident"])}
        )
    if signals["inventory"]:
        priority_actions.append(
            {"priority": "high", "action": "Investigate inventory discrepancies / stock risks", "count": len(signals["inventory"])}
        )
    if signals["supplier"]:
        priority_actions.append(
            {"priority": "medium", "action": "Action outstanding supplier notices", "count": len(signals["supplier"])}
        )
    if signals["promotion"]:
        priority_actions.append(
            {"priority": "medium", "action": "Verify promotion / display compliance", "count": len(signals["promotion"])}
        )

    missing_information: List[str] = []
    for cat, label in [
        ("inventory", "inventory records"),
        ("promotion", "promotion / merchandising instructions"),
        ("supplier", "supplier notices"),
    ]:
        if not signals[cat]:
            missing_information.append(f"No {label} found for this period.")

    scope = arguments.get("store") or arguments.get("region") or "all locations"
    period = arguments.get("period", "daily")
    executive_summary = (
        f"{period.capitalize()} operations brief for {scope}: "
        f"{len(signals['incident'])} incident(s), {len(signals['inventory'])} inventory signal(s), "
        f"{len(signals['supplier'])} supplier signal(s), {len(signals['promotion'])} promotion signal(s) "
        f"across {len(records)} record(s)."
    )

    output = {
        "executive_summary": executive_summary,
        "priority_actions": priority_actions,
        "inventory_signals": signals["inventory"],
        "promotion_signals": signals["promotion"],
        "supplier_signals": signals["supplier"],
        "incidents": signals["incident"],
        "missing_information": missing_information,
        "evidence": [e.to_dict() for e in evidence],
    }
    return ActionOutcome.success(
        _with_formulas("retail.generate_operations_brief", output), evidence=evidence
    )


# ---------------------------------------------------------------------------
# B. analyse_inventory_risk
# ---------------------------------------------------------------------------

def _collect_rows(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Explicit rows win; otherwise fall back to structured rows carried on
    # records (avoids double-counting when both are supplied by enrichment).
    explicit = list(arguments.get("rows") or [])
    if explicit:
        return explicit
    rows: List[Dict[str, Any]] = []
    for rec in arguments.get("records") or []:
        payload = rec.get("rows") or rec.get("structured")
        if isinstance(payload, list):
            rows.extend(x for x in payload if isinstance(x, dict))
    return rows


async def analyse_inventory_risk(
    context: ActionContext, arguments: Dict[str, Any]
) -> ActionOutcome:
    raw_rows = _collect_rows(arguments)
    normalized = [S.normalize_inventory_row(r) for r in raw_rows]
    usable = [r for r in normalized if r.get("sku") and r.get("on_hand") is not None]

    if not usable:
        return ActionOutcome.dependency(
            [
                ActionDependency(
                    kind="inventory_data",
                    description="inventory CSV/XLSX or structured stock data required",
                    hint="Provide rows containing at least an SKU and on-hand quantity.",
                )
            ],
            metadata={"rows_received": len(raw_rows)},
        )

    thresholds = arguments.get("thresholds") or {}
    slow_days = float(thresholds.get("slow_moving_days", 90))
    overstock_days = float(thresholds.get("overstock_days", 120))
    stockout_days = float(thresholds.get("stockout_days", 7))

    present = S.present_fields([S.normalize_inventory_row(r) for r in raw_rows])
    missing_fields = [
        f
        for f in ["reorder_point", "safety_stock", "average_daily_sales"]
        if f not in present
    ]

    # Advisory learning profiles (high confidence only may alter applied ROP).
    learning_adjustments = _load_inventory_learning_adjustments(context, usable)

    stockout_risks: List[Dict[str, Any]] = []
    overstock_risks: List[Dict[str, Any]] = []
    slow_moving: List[Dict[str, Any]] = []
    anomalies: List[Dict[str, Any]] = []

    for row in usable:
        sku = row["sku"]
        on_hand = row["on_hand"]
        ads = row.get("average_daily_sales")
        original_rop = row.get("reorder_point")
        safety = row.get("safety_stock")
        store = row.get("store")
        item = {
            "sku": sku,
            "product_name": row.get("product_name"),
            "on_hand": on_hand,
            "store": store,
        }

        applied_rop = original_rop
        adj = learning_adjustments.get(_inv_key(sku, store))
        if adj and adj.get("apply"):
            applied_rop = adj.get("applied_value")

        if on_hand < 0:
            anomalies.append({**item, "issue": "negative_on_hand"})
        last_c = row.get("last_count_quantity")
        cur_c = row.get("current_count_quantity")
        if last_c is not None and cur_c is not None and last_c > 0:
            variance = abs(cur_c - last_c) / last_c
            if variance >= 0.2:
                anomalies.append(
                    {
                        **item,
                        "issue": "count_variance",
                        "variance_pct": round(variance * 100, 1),
                    }
                )

        days_of_supply = None
        if ads and ads > 0:
            days_of_supply = round(on_hand / ads, 1)
        reasons: List[str] = []
        if applied_rop is not None and on_hand <= applied_rop:
            reasons.append("on_hand<=reorder_point")
        if safety is not None and on_hand <= safety:
            reasons.append("on_hand<=safety_stock")
        if days_of_supply is not None and days_of_supply <= stockout_days:
            reasons.append(f"days_of_supply<={stockout_days}")
        if reasons:
            stockout_risks.append(
                {**item, "days_of_supply": days_of_supply, "reasons": reasons}
            )
            continue

        if days_of_supply is not None and days_of_supply >= overstock_days:
            overstock_risks.append({**item, "days_of_supply": days_of_supply})
        elif days_of_supply is not None and days_of_supply >= slow_days:
            slow_moving.append({**item, "days_of_supply": days_of_supply})
        elif ads is not None and ads == 0 and on_hand > 0:
            slow_moving.append({**item, "days_of_supply": None, "reason": "no_sales"})

    assumptions = [
        f"days_of_supply = on_hand / average_daily_sales; stockout if <= {stockout_days} days.",
        f"overstock if days_of_supply >= {overstock_days}; slow-moving if >= {slow_days}.",
        "count variance flagged at >= 20% between last and current physical counts.",
        "learned reorder profiles are advisory; only high-confidence profiles alter applied thresholds.",
    ]

    evidence = [
        _record_evidence(rec)
        for rec in (arguments.get("records") or [])
        if rec.get("text")
    ]

    summary = {
        "skus_analysed": len(usable),
        "stockout_count": len(stockout_risks),
        "overstock_count": len(overstock_risks),
        "slow_moving_count": len(slow_moving),
        "anomaly_count": len(anomalies),
        "learning_adjustments_applied": sum(
            1 for a in learning_adjustments.values() if a.get("apply")
        ),
    }

    output = {
        "summary": summary,
        "stockout_risks": stockout_risks,
        "overstock_risks": overstock_risks,
        "slow_moving_items": slow_moving,
        "anomalies": anomalies,
        "assumptions": assumptions,
        "missing_fields": missing_fields,
        "evidence": [e.to_dict() for e in evidence],
        "learning_adjustments": list(learning_adjustments.values()),
    }
    return ActionOutcome.success(
        _with_formulas("retail.analyse_inventory_risk", output), evidence=evidence
    )


def _inv_key(sku: Any, store: Any) -> str:
    return f"{sku}|{store or ''}"


def _load_inventory_learning_adjustments(
    context: ActionContext, rows: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Return advisory learning disclosures keyed by sku|store.

    Source inventory data remains authoritative. High-confidence profiles may
    alter the *applied* reorder point used in stockout checks; low/medium
    confidence profiles are disclosed but do not change calculations.
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        from app.retailops.db import session_scope
        from app.retailops.learning import RetailOutcomeLearningEngine
    except Exception:
        return out

    engine = RetailOutcomeLearningEngine()
    try:
        with session_scope() as session:
            for row in rows:
                sku = row.get("sku")
                store = row.get("store")
                if not sku or not store:
                    continue
                profile = engine.get_demand_profile(
                    session,
                    tenant_id=context.tenant_id,
                    project_id=context.project_id,
                    sku=str(sku),
                    store=str(store),
                )
                if profile is None:
                    continue
                metrics = profile.metrics or {}
                original = row.get("reorder_point")
                learned = metrics.get("recommended_reorder_point")
                confidence = profile.confidence
                apply = confidence == "high" and learned is not None
                out[_inv_key(sku, store)] = {
                    "sku": sku,
                    "store": store,
                    "original_threshold": original,
                    "learned_advisory_value": learned,
                    "applied_value": learned if apply else original,
                    "apply": apply,
                    "sample_count": profile.sample_count,
                    "confidence": confidence,
                    "source_period_start": (
                        profile.source_period_start.isoformat()
                        if profile.source_period_start
                        else None
                    ),
                    "source_period_end": (
                        profile.source_period_end.isoformat()
                        if profile.source_period_end
                        else None
                    ),
                    "profile_version": profile.version,
                    "advisory_only": True,
                }
    except Exception:
        return out
    return out


# ---------------------------------------------------------------------------
# C. check_promotion_compliance
# ---------------------------------------------------------------------------

def _extract_rules(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    for i, rule in enumerate(arguments.get("rules") or []):
        if isinstance(rule, dict) and (rule.get("requirement") or rule.get("text")):
            rules.append(
                {
                    "rule_id": rule.get("rule_id") or rule.get("id") or f"rule_{i+1}",
                    "requirement": rule.get("requirement") or rule.get("text"),
                    "keywords": [k.lower() for k in (rule.get("keywords") or [])],
                    "source": rule.get("source"),
                }
            )
    # Rules may also be supplied as parsed rule records (one requirement per line).
    for rec in arguments.get("rule_records") or []:
        for j, line in enumerate((rec.get("text") or "").splitlines()):
            line = line.strip("-• \t")
            if len(line) < 8:
                continue
            rules.append(
                {
                    "rule_id": f"{rec.get('document_id') or rec.get('filename') or 'rules'}#{j+1}",
                    "requirement": line,
                    "keywords": [],
                    "source": rec.get("filename") or rec.get("document_id"),
                }
            )
    return rules


def _keywords_for(rule: Dict[str, Any]) -> List[str]:
    if rule["keywords"]:
        return rule["keywords"]
    # Derive salient keywords from the requirement text (deterministic).
    stop = {
        "the", "a", "an", "must", "should", "be", "is", "are", "to", "of", "and",
        "or", "in", "on", "at", "for", "with", "all", "any", "each", "that", "this",
        "no", "not", "within", "per", "than", "least", "more", "less",
    }
    words = [w.strip(".,;:()").lower() for w in rule["requirement"].split()]
    salient = [w for w in words if len(w) > 3 and w not in stop]
    return salient[:6]


async def check_promotion_compliance(
    context: ActionContext, arguments: Dict[str, Any]
) -> ActionOutcome:
    rules = _extract_rules(arguments)
    if not rules:
        return ActionOutcome.dependency(
            [
                ActionDependency(
                    kind="promotion_rules",
                    description="promotion rules document required before a compliance conclusion can be drawn",
                    hint="Upload the promotion rules / display standards for this campaign.",
                )
            ],
        )

    evidence_records = [
        r for r in (arguments.get("evidence") or []) if (r.get("text") or "").strip()
    ]
    evidence_text = "\n".join(r["text"] for r in evidence_records).lower()

    rule_results: List[Dict[str, Any]] = []
    compliant: List[Dict[str, Any]] = []
    non_compliant: List[Dict[str, Any]] = []
    missing_evidence: List[Dict[str, Any]] = []

    for rule in rules:
        keywords = _keywords_for(rule)
        if not evidence_records:
            finding = "missing_evidence"
            confidence = 0.0
            ref = None
            explanation = "No campaign/store evidence was supplied to assess this rule."
        else:
            hits = [kw for kw in keywords if kw in evidence_text]
            matched_rec = None
            for rec in evidence_records:
                low = rec["text"].lower()
                if any(kw in low for kw in keywords):
                    matched_rec = rec
                    break
            coverage = (len(hits) / len(keywords)) if keywords else 0.0
            if coverage >= 0.5 and matched_rec is not None:
                finding = "compliant"
                confidence = round(min(1.0, 0.5 + coverage / 2), 2)
                ref = _record_evidence(matched_rec).to_dict()
                explanation = f"Evidence matched {len(hits)}/{len(keywords)} required terms."
            elif coverage > 0:
                finding = "non_compliant"
                confidence = round(0.4 + coverage / 2, 2)
                ref = _record_evidence(matched_rec).to_dict() if matched_rec else None
                explanation = f"Evidence only partially matched ({len(hits)}/{len(keywords)} terms)."
            else:
                finding = "non_compliant"
                confidence = 0.5
                ref = None
                explanation = "No supplied evidence satisfied this rule's requirements."

        result = {
            "rule_id": rule["rule_id"],
            "requirement": rule["requirement"],
            "finding": finding,
            "evidence_reference": ref,
            "confidence": confidence,
            "explanation": explanation,
        }
        rule_results.append(result)
        if finding == "compliant":
            compliant.append(result)
        elif finding == "non_compliant":
            non_compliant.append(result)
        else:
            missing_evidence.append(result)

    summary = {
        "rules_evaluated": len(rules),
        "compliant": len(compliant),
        "non_compliant": len(non_compliant),
        "missing_evidence": len(missing_evidence),
        "overall": "compliant" if not non_compliant and not missing_evidence else "attention_required",
    }

    output = {
        "compliant": compliant,
        "non_compliant": non_compliant,
        "missing_evidence": missing_evidence,
        "rule_results": rule_results,
        "summary": summary,
        "evidence": [_record_evidence(r).to_dict() for r in evidence_records],
    }
    return ActionOutcome.success(
        _with_formulas("retail.check_promotion_compliance", output),
        evidence=[_record_evidence(r) for r in evidence_records],
    )


# ---------------------------------------------------------------------------
# D. Learning actions
# ---------------------------------------------------------------------------

async def record_verified_outcome(
    context: ActionContext, arguments: Dict[str, Any]
) -> ActionOutcome:
    from app.retailops.db import session_scope
    from app.retailops.learning import RetailOutcomeLearningEngine

    module = arguments.get("module")
    payload = arguments.get("payload") or {}
    dedupe = arguments.get("deduplication_key")
    if not module or not dedupe:
        return ActionOutcome(
            status=ActionStatus.VALIDATION_ERROR,
            error_code="missing_fields",
            error_message="module and deduplication_key are required",
        )

    verification_status = arguments.get("verification_status") or "verified"
    engine = RetailOutcomeLearningEngine()
    try:
        with session_scope() as session:
            result = engine.record_verified_outcome(
                session,
                tenant_id=context.tenant_id,
                project_id=context.project_id,
                module=str(module),
                payload=dict(payload),
                verified_by=context.user_id,
                deduplication_key=str(dedupe),
                event_type=arguments.get("event_type"),
                source_document_id=arguments.get("source_document_id"),
                source_action_run_id=arguments.get("source_action_run_id"),
                source_reference=arguments.get("source_reference"),
                verification_status=str(verification_status),
            )
    except ValueError as exc:
        return ActionOutcome(
            status=ActionStatus.VALIDATION_ERROR,
            error_code="learning_validation_error",
            error_message=str(exc)[:500],
        )

    output = {
        "event_id": result.get("event_id"),
        "module": result.get("module") or module,
        "profile_key": result.get("profile_key"),
        "profile_version": result.get("profile_version"),
        "sample_count": result.get("sample_count") or 0,
        "confidence": result.get("confidence") or "low",
        "changed_metrics": result.get("changed_metrics") or {},
        "warnings": result.get("warnings") or [],
        "evidence": result.get("evidence") or {},
        "idempotent": bool(result.get("idempotent")),
        "advisory_only": True,
    }
    return ActionOutcome.success(
        output,
        warnings=list(output["warnings"]),
        metadata={
            "event_id": output["event_id"],
            "profile_version": output["profile_version"],
            "sample_count": output["sample_count"],
            "confidence": output["confidence"],
        },
    )


async def get_learning_summary(
    context: ActionContext, arguments: Dict[str, Any]
) -> ActionOutcome:
    from app.retailops.db import session_scope
    from app.retailops.learning import RetailOutcomeLearningEngine, profile_to_dict

    engine = RetailOutcomeLearningEngine()
    limit = int(arguments.get("limit") or 100)
    offset = int(arguments.get("offset") or 0)
    with session_scope() as session:
        profiles = engine.list_profiles(
            session,
            tenant_id=context.tenant_id,
            project_id=context.project_id,
            module=arguments.get("module"),
            entity_type=arguments.get("entity_type"),
            entity_key=arguments.get("entity_key"),
            limit=limit,
            offset=offset,
        )
        rows = [profile_to_dict(p) for p in profiles]
    return ActionOutcome.success(
        _with_formulas(
            "retail.get_learning_summary",
            {"profiles": rows, "count": len(rows), "advisory_only": True},
        )
    )


async def recommend_reorder_parameters(
    context: ActionContext, arguments: Dict[str, Any]
) -> ActionOutcome:
    from app.retailops.db import session_scope
    from app.retailops.learning import DemandReorderCalibrator, RetailOutcomeLearningEngine

    sku = arguments.get("sku")
    if not sku:
        return ActionOutcome(
            status=ActionStatus.VALIDATION_ERROR,
            error_code="missing_sku",
            error_message="sku is required",
        )
    store = arguments.get("store")
    region = arguments.get("region")
    if not store and not region:
        return ActionOutcome.dependency(
            [
                ActionDependency(
                    kind="location_context",
                    description="store or region is required for reorder recommendation",
                )
            ]
        )

    engine = RetailOutcomeLearningEngine()
    calibrator = DemandReorderCalibrator()
    with session_scope() as session:
        profile = engine.get_demand_profile(
            session,
            tenant_id=context.tenant_id,
            project_id=context.project_id,
            sku=str(sku),
            store=store,
            region=region,
        )
        metrics = dict(profile.metrics or {}) if profile else None
        recommendation = calibrator.recommend(
            profile_metrics=metrics,
            current_reorder_point=arguments.get("current_reorder_point"),
            current_safety_stock=arguments.get("current_safety_stock"),
        )

    if recommendation.get("status") == "dependency_required":
        return ActionOutcome.dependency(
            [
                ActionDependency(
                    kind="learning_profile",
                    description="verified demand/reorder learning profile required",
                    hint="Record verified forecast vs actual outcomes first.",
                )
            ],
            metadata={"sku": sku, "store": store, "region": region},
        )

    output = {
        "status": "ok",
        "sku": sku,
        "advisory_only": True,
    }
    if store is not None:
        output["store"] = store
    if region is not None:
        output["region"] = region
    for k, v in recommendation.items():
        if k == "status" or v is None:
            continue
        output[k] = v
    return ActionOutcome.success(_with_formulas("retail.recommend_reorder_parameters", output))


# ---------------------------------------------------------------------------
# G. export_document
# ---------------------------------------------------------------------------

async def export_document(
    context: ActionContext, arguments: Dict[str, Any]
) -> ActionOutcome:
    """Generate PDF / DOCX / XLSX bytes from structured retail content."""
    from app.retailops.exports import (
        build_export,
        document_from_custom,
        document_from_inventory_risk,
        document_from_learning_summary,
        document_from_operations_brief,
    )

    fmt = str(arguments.get("format") or "").lower()
    kind = str(arguments.get("document_kind") or "custom").lower()
    if fmt not in {"pdf", "docx", "xlsx"}:
        return ActionOutcome(
            status=ActionStatus.VALIDATION_ERROR,
            error_code="invalid_format",
            error_message="format must be one of pdf, docx, xlsx",
        )

    title = str(arguments.get("title") or "").strip()
    source = arguments.get("source_output")
    include_base64 = arguments.get("include_base64")
    if include_base64 is None:
        include_base64 = True

    if kind == "operations_brief":
        if not isinstance(source, dict):
            # Default period so nested brief generation validates.
            brief_args = dict(arguments)
            brief_args.setdefault("period", "daily")
            brief = await generate_operations_brief(context, brief_args)
            if brief.status != ActionStatus.SUCCESS:
                return brief
            source = brief.output
            evidence = list(brief.evidence)
        else:
            evidence = []
        document = document_from_operations_brief(
            source, title=title or "Operations Brief"
        )
    elif kind == "inventory_risk":
        if not isinstance(source, dict):
            risk = await analyse_inventory_risk(context, arguments)
            if risk.status != ActionStatus.SUCCESS:
                return risk
            source = risk.output
            evidence = list(risk.evidence)
        else:
            evidence = []
        document = document_from_inventory_risk(
            source, title=title or "Inventory Risk Report"
        )
    elif kind == "learning_summary":
        if not isinstance(source, dict):
            # Prefer explicit profiles payload; else empty table with advisory note.
            profiles = arguments.get("profiles")
            if profiles is None:
                summary = await get_learning_summary(context, arguments)
                if summary.status != ActionStatus.SUCCESS:
                    return summary
                source = summary.output
                evidence = list(summary.evidence)
            else:
                source = {"profiles": profiles, "advisory_only": True}
                evidence = []
        else:
            evidence = []
        document = document_from_learning_summary(
            source, title=title or "Learning Summary"
        )
    else:
        sections = arguments.get("sections") or []
        table = arguments.get("table")
        tables = arguments.get("tables")
        if not sections and not table and not tables:
            return ActionOutcome.dependency(
                [
                    ActionDependency(
                        kind="export_content",
                        description=(
                            "Provide sections/table content, or use document_kind "
                            "operations_brief / inventory_risk / learning_summary"
                        ),
                        hint="Pass source_output from a prior action, or custom sections.",
                    )
                ]
            )
        document = document_from_custom(
            title=title or "RetailOps Export",
            subtitle=str(arguments.get("subtitle") or ""),
            sections=sections,
            table=table,
            tables=tables,
        )
        evidence = []

    if arguments.get("subtitle") and not document.subtitle:
        document.subtitle = str(arguments["subtitle"])

    built = build_export(document, fmt)  # type: ignore[arg-type]
    output = built.to_public_dict(include_base64=bool(include_base64))
    output["document_kind"] = kind
    output["title"] = document.title
    output["advisory_only"] = True
    return ActionOutcome.success(
        _with_formulas("retail.export_document", output), evidence=evidence
    )


# ---------------------------------------------------------------------------
# Action specifications (discovered by the registry)
# ---------------------------------------------------------------------------

ACTION_SPECS: List[ActionSpec] = [
    ActionSpec(
        action_id="retail.generate_operations_brief",
        domain="retail",
        name="Generate Operations Brief",
        description="Generate a structured daily or weekly operations brief from available project records.",
        version="1.0.0",
        kit_version=RETAIL_KIT_VERSION,
        input_schema=S.OPERATIONS_BRIEF_INPUT,
        output_schema=S.OPERATIONS_BRIEF_OUTPUT,
        required_context=["tenant_id", "project_id"],
        permissions=[_PERM_READ],
        risk_classification="low",
        read_only=True,
        confirmation_required=False,
        synthesis_instructions=(
            "Summarise the brief for a store/regional manager. Lead with priority "
            "actions and incidents, cite each signal's source, and never invent "
            "figures that are not present in the evidence."
        ),
        evaluation_fixtures=["operations_brief_happy", "operations_brief_no_records"],
        handler=generate_operations_brief,
    ),
    ActionSpec(
        action_id="retail.analyse_inventory_risk",
        domain="retail",
        name="Analyse Inventory Risk",
        description="Analyse structured inventory data for stockout, overstock, slow-moving stock and anomalies.",
        version="1.1.0",
        kit_version=RETAIL_KIT_VERSION,
        input_schema=S.INVENTORY_RISK_INPUT,
        output_schema=S.INVENTORY_RISK_OUTPUT,
        required_context=["tenant_id", "project_id"],
        permissions=[_PERM_ANALYSE],
        risk_classification="low",
        read_only=True,
        confirmation_required=False,
        synthesis_instructions=(
            "Report inventory risks grouped by type with the deterministic figures "
            "provided. State assumptions, missing fields, and any advisory learning "
            "adjustments explicitly."
        ),
        evaluation_fixtures=["inventory_risk_happy", "inventory_risk_no_data"],
        handler=analyse_inventory_risk,
    ),
    ActionSpec(
        action_id="retail.check_promotion_compliance",
        domain="retail",
        name="Check Promotion Compliance",
        description="Compare campaign or store evidence against uploaded promotion rules.",
        version="1.0.0",
        kit_version=RETAIL_KIT_VERSION,
        input_schema=S.PROMOTION_COMPLIANCE_INPUT,
        output_schema=S.PROMOTION_COMPLIANCE_OUTPUT,
        required_context=["tenant_id", "project_id"],
        permissions=[_PERM_ANALYSE],
        risk_classification="medium",
        read_only=True,
        confirmation_required=False,
        synthesis_instructions=(
            "For each rule, state the finding (compliant / non-compliant / missing "
            "evidence) with its evidence reference. Never conclude compliance "
            "without a source rule."
        ),
        evaluation_fixtures=["promotion_compliance_happy", "promotion_compliance_no_rules"],
        handler=check_promotion_compliance,
    ),
    ActionSpec(
        action_id="retail.record_verified_outcome",
        domain="retail",
        name="Record Verified Outcome",
        description=(
            "Record an authorised verified operational outcome and update the "
            "relevant tenant/project learning profile."
        ),
        version="1.0.0",
        kit_version=RETAIL_KIT_VERSION,
        input_schema=S.RECORD_VERIFIED_OUTCOME_INPUT,
        output_schema=S.RECORD_VERIFIED_OUTCOME_OUTPUT,
        required_context=["tenant_id", "project_id", "user_id"],
        permissions=[_PERM_LEARNING_WRITE],
        risk_classification="high",
        read_only=False,
        confirmation_required=True,
        synthesis_instructions=(
            "Confirm the verified outcome was recorded, report sample count and "
            "confidence, and emphasise that learning remains advisory only."
        ),
        evaluation_fixtures=["learning_record_happy"],
        handler=record_verified_outcome,
    ),
    ActionSpec(
        action_id="retail.get_learning_summary",
        domain="retail",
        name="Get Learning Summary",
        description="Return current advisory learning profiles for the active tenant/project.",
        version="1.0.0",
        kit_version=RETAIL_KIT_VERSION,
        input_schema=S.GET_LEARNING_SUMMARY_INPUT,
        output_schema=S.GET_LEARNING_SUMMARY_OUTPUT,
        required_context=["tenant_id", "project_id"],
        permissions=[_PERM_READ],
        risk_classification="low",
        read_only=True,
        confirmation_required=False,
        synthesis_instructions=(
            "Summarise learned profiles with sample counts and confidence. Label "
            "all outputs as advisory only."
        ),
        evaluation_fixtures=["learning_summary_happy"],
        handler=get_learning_summary,
    ),
    ActionSpec(
        action_id="retail.recommend_reorder_parameters",
        domain="retail",
        name="Recommend Reorder Parameters",
        description=(
            "Return advisory reorder and safety-stock recommendations from verified "
            "demand learning profiles."
        ),
        version="1.0.0",
        kit_version=RETAIL_KIT_VERSION,
        input_schema=S.RECOMMEND_REORDER_INPUT,
        output_schema=S.RECOMMEND_REORDER_OUTPUT,
        required_context=["tenant_id", "project_id"],
        permissions=[_PERM_ANALYSE],
        risk_classification="low",
        read_only=True,
        confirmation_required=False,
        synthesis_instructions=(
            "Present current vs recommended reorder settings with sample count, "
            "confidence and source period. Never imply automatic application."
        ),
        evaluation_fixtures=["reorder_recommend_happy", "reorder_recommend_no_profile"],
        handler=recommend_reorder_parameters,
    ),
    ActionSpec(
        action_id="retail.export_document",
        domain="retail",
        name="Export Document",
        description=(
            "Generate a downloadable PDF, Word (DOCX), or Excel (XLSX) document "
            "from an operations brief, inventory risk analysis, learning summary, "
            "or custom sections/tables."
        ),
        version="1.0.0",
        kit_version=RETAIL_KIT_VERSION,
        input_schema=S.EXPORT_DOCUMENT_INPUT,
        output_schema=S.EXPORT_DOCUMENT_OUTPUT,
        required_context=["tenant_id", "project_id"],
        permissions=[_PERM_READ],
        risk_classification="low",
        read_only=True,
        confirmation_required=False,
        synthesis_instructions=(
            "Confirm the file was generated. Report filename, format, and byte size. "
            "Do not invent figures beyond the exported content. Mention that "
            "document_base64 can be downloaded by the client."
        ),
        evaluation_fixtures=["export_document_custom_pdf"],
        handler=export_document,
    ),
]
