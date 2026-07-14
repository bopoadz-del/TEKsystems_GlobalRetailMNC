"""Deterministic Retail Operations Reasoning Layer.

``RetailOperationsReasoner`` expands a user request into an auditable
:class:`RetailExecutionPlan`. It does **not** execute actions, call LLMs, or
override trusted ActionContext fields.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from app.retailops.agents import get_agent_catalog
from app.retailops.kit.contract import ActionContext, ActionRegistry, ActionSpec
from app.retailops.kit.contract.models import RESERVED_CONTEXT_KEYS
from app.retailops.reasoning.domain_map import (
    ACTION_IMPERATIVES,
    DISCIPLINE_HAT_KEYWORDS,
    INTENT_ACTION_HINTS,
    INTENT_CUES,
    INTENT_PRIMARY_HAT,
    RELATED_DOMAINS,
    RETAIL_INTENTS,
)
from app.retailops.reasoning.plan import RetailExecutionPlan, empty_plan

_QUESTION_STARTS = (
    "what", "which", "how", "why", "when", "where", "who", "is", "are",
    "does", "do", "can", "could", "should", "explain", "describe", "list",
)

_STOPWORDS = {
    "generate", "analyse", "analyze", "check", "run", "create", "the", "a",
    "an", "of", "for", "s", "recommend", "record", "get",
}


def _is_question(text: str) -> bool:
    t = text.strip().lower()
    if t.endswith("?"):
        return True
    first = re.split(r"\W+", t, maxsplit=1)[0] if t else ""
    return first in _QUESTION_STARTS


def _tokens(text: str) -> Set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _action_keywords(action_id: str) -> Set[str]:
    name_part = action_id.split(".", 1)[1]
    return {w for w in name_part.split("_") if w not in _STOPWORDS}


def _score_intent(text: str) -> tuple[str, float]:
    lowered = text.lower()
    best_intent = "unknown"
    best_score = 0
    for intent, cues in INTENT_CUES.items():
        score = sum(1 for cue in cues if cue in lowered)
        if score > best_score:
            best_score = score
            best_intent = intent
    if best_score == 0:
        return "unknown", 0.15
    # Soft-max style confidence bound for discrete cue hits.
    confidence = min(0.95, 0.35 + 0.15 * best_score)
    return best_intent, confidence


def _has_imperative(text: str) -> bool:
    tokens = _tokens(text)
    return any(v in tokens for v in ACTION_IMPERATIVES)


_COMMAND_LEAD_INS = (
    "please ",
    "kindly ",
    "i need you to ",
    "i want you to ",
    "go ahead and ",
)

# Extra command verbs beyond retail action imperatives (unsupported if unmatched).
_EXTRA_COMMAND_VERBS = frozenset(
    {
        "book",
        "send",
        "schedule",
        "delete",
        "update",
        "cancel",
        "order",
        "deploy",
        "teleport",
        "buy",
        "sell",
        "ship",
        "approve",
        "reject",
        "fetch",
        "download",
    }
)


def _looks_like_command(text: str) -> bool:
    """True when the utterance looks like a command / request to do work."""
    if _has_imperative(text):
        return True
    lowered = text.strip().lower()
    if any(lowered.startswith(p) for p in _COMMAND_LEAD_INS):
        return True
    first = re.split(r"\W+", lowered, maxsplit=1)[0] if lowered else ""
    return first in ACTION_IMPERATIVES or first in _EXTRA_COMMAND_VERBS


def _sanitize_plan_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in (arguments or {}).items() if k not in RESERVED_CONTEXT_KEYS}


class RetailOperationsReasoner:
    """Deterministic retail-domain reasoner used by LangGraph."""

    def reason(
        self,
        *,
        question: str,
        registry: ActionRegistry,
        context: ActionContext,
        arguments: Optional[Dict[str, Any]] = None,
        disabled_agents: Optional[List[str]] = None,
    ) -> RetailExecutionPlan:
        q = (question or "").strip()
        if not q:
            return empty_plan(notes=["empty_request"])

        permitted = {s.action_id: s for s in registry.list_permitted(context)}
        registered = {s.action_id: s for s in registry.all()}
        notes: List[str] = []
        args = _sanitize_plan_arguments(arguments or {})
        disabled = list(disabled_agents or [])

        # Explicit action addressing always wins when the id is known.
        explicit = re.search(r"action[:=]\s*([a-z_]+\.[a-z_]+)", q.lower())
        if explicit:
            action_id = explicit.group(1)
            if action_id not in registered:
                return self._annotate(
                    RetailExecutionPlan(
                        primary_intent="unknown",
                        confidence=1.0,
                        route="unsupported",
                        recommended_action_ids=[],
                        related_domains=[],
                        notes=[f"unregistered_action:{action_id}"],
                        arguments=args,
                    ),
                    question=q,
                    intent="unknown",
                    disabled=disabled,
                )
            if action_id not in permitted:
                intent = self._intent_for_action(action_id)
                return self._annotate(
                    RetailExecutionPlan(
                        primary_intent=intent,
                        confidence=1.0,
                        route="unsupported",
                        recommended_action_ids=[],
                        related_domains=RELATED_DOMAINS.get(intent, []),
                        notes=[f"action_not_permitted:{action_id}"],
                        arguments=args,
                        confirmation_required=bool(
                            registered[action_id].confirmation_required
                        ),
                    ),
                    question=q,
                    intent=intent,
                    disabled=disabled,
                )
            intent = self._intent_for_action(action_id)
            spec = permitted[action_id]
            return self._annotate(
                RetailExecutionPlan(
                    primary_intent=intent,
                    confidence=1.0,
                    route="action",
                    recommended_action_ids=[action_id],
                    related_domains=list(RELATED_DOMAINS.get(intent, [])),
                    required_dependencies=self._dependency_hints(spec),
                    evidence_requirements=self._evidence_hints(intent),
                    arguments=args,
                    confirmation_required=bool(spec.confirmation_required),
                    notes=["explicit_action_addressing"],
                ),
                question=q,
                intent=intent,
                disabled=disabled,
            )

        intent, confidence = _score_intent(q)
        related = list(RELATED_DOMAINS.get(intent, []))
        is_question = _is_question(q)
        looks_like_command = _looks_like_command(q)

        # Factual / procedure questions stay on RAG even when action topic words
        # or imperative verbs appear in the sentence.
        if is_question:
            notes.append("factual_question_stays_on_rag")
            return self._annotate(
                RetailExecutionPlan(
                    primary_intent=intent,
                    confidence=confidence,
                    route="rag",
                    recommended_action_ids=[],
                    related_domains=related,
                    evidence_requirements=self._evidence_hints(intent),
                    arguments=args,
                    notes=notes,
                ),
                question=q,
                intent=intent,
                disabled=disabled,
            )

        # Match permitted actions by noun keywords and intent hints.
        candidates = self._match_actions(q, permitted, intent)
        if not candidates:
            # Commands that do not map to a registered action must not fall
            # through to RAG (nearest-neighbour retrieval + fake LLM can
            # fabricate an answer from unrelated store documents).
            if looks_like_command:
                notes.append("unsupported_command_no_registered_action")
                return self._annotate(
                    RetailExecutionPlan(
                        primary_intent=intent,
                        confidence=confidence,
                        route="unsupported",
                        recommended_action_ids=[],
                        related_domains=related,
                        evidence_requirements=self._evidence_hints(intent),
                        arguments=args,
                        notes=notes,
                    ),
                    question=q,
                    intent=intent,
                    disabled=disabled,
                )
            notes.append("default_rag")
            return self._annotate(
                RetailExecutionPlan(
                    primary_intent=intent,
                    confidence=confidence,
                    route="rag",
                    recommended_action_ids=[],
                    related_domains=related,
                    evidence_requirements=self._evidence_hints(intent),
                    arguments=args,
                    notes=notes,
                ),
                question=q,
                intent=intent,
                disabled=disabled,
            )

        primary = candidates[0]
        spec = permitted[primary]
        notes.append(
            "imperative_action_match" if looks_like_command else "action_keyword_match"
        )
        return self._annotate(
            RetailExecutionPlan(
                primary_intent=intent if intent in RETAIL_INTENTS else "unknown",
                confidence=max(confidence, 0.7),
                route="action",
                recommended_action_ids=candidates,
                related_domains=related,
                required_dependencies=self._dependency_hints(spec),
                evidence_requirements=self._evidence_hints(intent),
                arguments=args,
                confirmation_required=bool(spec.confirmation_required),
                notes=notes,
            ),
            question=q,
            intent=intent if intent in RETAIL_INTENTS else "unknown",
            disabled=disabled,
        )

    def _annotate(
        self,
        plan: RetailExecutionPlan,
        *,
        question: str,
        intent: str,
        disabled: List[str],
    ) -> RetailExecutionPlan:
        """Attach active discipline hats + handoff tips without changing route."""
        catalog = get_agent_catalog()
        active = catalog.enabled_hats(
            disabled=disabled, question=question, intent=intent
        )
        active_ids = [h.agent_id for h in active]
        primary = self._select_primary_hat(question, intent, active_ids)
        handoffs: List[Dict[str, Any]] = []
        if primary:
            handoffs = catalog.recommend_handoffs(
                primary,
                related_domains=list(plan.related_domains or []),
                include_all=True,
            )
        notes = list(plan.notes or [])
        if primary:
            notes.append(f"discipline_hat:{primary}")
        if disabled:
            notes.append(f"agents_put_off:{','.join(sorted(disabled))}")
        return plan.model_copy(
            update={
                "active_agent_ids": active_ids,
                "primary_agent_id": primary,
                "handoff_tips": handoffs,
                "notes": notes,
            }
        )

    def _select_primary_hat(
        self, question: str, intent: str, active_ids: List[str]
    ) -> Optional[str]:
        if not active_ids:
            return None
        lowered = question.lower()
        # Keyword discipline overrides (accounting / HR / roster) win when active.
        best_hat: Optional[str] = None
        best_hits = 0
        for hat_id, cues in DISCIPLINE_HAT_KEYWORDS.items():
            if hat_id not in active_ids:
                continue
            hits = sum(1 for cue in cues if cue in lowered)
            if hits > best_hits:
                best_hits = hits
                best_hat = hat_id
        if best_hat:
            return best_hat
        preferred = INTENT_PRIMARY_HAT.get(intent)
        if preferred and preferred in active_ids:
            return preferred
        return active_ids[0]

    def _intent_for_action(self, action_id: str) -> str:
        for intent, hints in INTENT_ACTION_HINTS.items():
            if action_id in hints:
                return intent
        # Fallback: infer from action name tokens.
        name = action_id.split(".", 1)[-1]
        intent, _ = _score_intent(name.replace("_", " "))
        return intent

    def _match_actions(
        self,
        question: str,
        permitted: Dict[str, ActionSpec],
        intent: str,
    ) -> List[str]:
        tokens = _tokens(question)
        ordered: List[str] = []

        # Prefer intent-aligned hints that are actually permitted.
        for action_id in INTENT_ACTION_HINTS.get(intent, ()):
            if action_id in permitted and action_id not in ordered:
                # Require at least one noun keyword overlap OR strong imperative
                # plus intent score so we don't auto-fire unrelated hints.
                kws = _action_keywords(action_id)
                if kws & tokens or (_looks_like_command(question) and intent != "unknown"):
                    if kws.issubset(tokens) or (kws & tokens) or action_id.split(".")[-1].split("_")[0] in tokens:
                        ordered.append(action_id)

        # Also match any permitted action whose noun keywords are a subset of tokens.
        for action_id, spec in permitted.items():
            kws = _action_keywords(action_id)
            if kws and kws.issubset(tokens) and action_id not in ordered:
                ordered.append(action_id)

        # Special phrases that should pick learning/recommendation actions.
        lowered = question.lower()
        phrase_map = (
            ("recommend reorder", "retail.recommend_reorder_parameters"),
            ("reorder parameters", "retail.recommend_reorder_parameters"),
            ("learning summary", "retail.get_learning_summary"),
            ("record verified", "retail.record_verified_outcome"),
            ("operations brief", "retail.generate_operations_brief"),
            ("inventory risk", "retail.analyse_inventory_risk"),
            ("promotion compliance", "retail.check_promotion_compliance"),
            ("promotion for compliance", "retail.check_promotion_compliance"),
        )
        for phrase, action_id in phrase_map:
            if phrase in lowered and action_id in permitted and action_id not in ordered:
                ordered.insert(0, action_id)

        return ordered

    def _dependency_hints(self, spec: ActionSpec) -> List[str]:
        hints: List[str] = []
        props = (spec.input_schema or {}).get("properties") or {}
        if "rows" in props:
            hints.append("structured_inventory_rows")
        if "records" in props:
            hints.append("project_document_records")
        if "rules" in props or "rule_records" in props:
            hints.append("promotion_rules")
        if "module" in props:
            hints.append("verified_outcome_payload")
        return hints

    def _evidence_hints(self, intent: str) -> List[str]:
        mapping = {
            "inventory": ["inventory_records", "stock_counts"],
            "promotion": ["promotion_rules", "promotion_evidence"],
            "supplier": ["supplier_notices", "delivery_records"],
            "incident": ["incident_reports"],
            "store_operations": ["sop_documents", "ops_signals"],
            "compliance": ["policy_documents", "official_guidance"],
            "customer_experience": ["complaint_records"],
            "workforce": ["roster_records"],
            "reporting": ["kpi_exports"],
        }
        return list(mapping.get(intent, ["project_documents"]))
