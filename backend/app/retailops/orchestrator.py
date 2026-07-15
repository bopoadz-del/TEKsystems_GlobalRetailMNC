"""LangGraph orchestration for RetailOps.

Graph:

    classify_request
    → reason_retail_request
    → (retrieve_context | resolve_action | unsupported)
    → execute_action
    → synthesize_response
    → persist_audit

``RetailOperationsReasoner`` produces an auditable RetailExecutionPlan.
Trusted tenant/project/permission fields in state are set by the caller and
are never replaced by model output.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.retailops.kit.contract import (
    ActionContext,
    ActionRegistry,
    ActionResult,
    ActionStatus,
    execute_action,
)
from app.retailops.providers import LLMProvider, ProviderError, get_provider
from app.retailops.reasoning import RetailOperationsReasoner
from app.retailops.retrieval import hybrid_search
from app.retailops import service


class OrchestratorState(TypedDict, total=False):
    # Inputs (trusted context is authoritative and never overwritten downstream).
    question: str
    context: ActionContext
    session: Session
    registry: ActionRegistry
    provider: LLMProvider
    disabled_agents: List[str]
    # Working fields
    route: str
    action_id: Optional[str]
    arguments: Dict[str, Any]
    citations: List[Dict[str, Any]]
    action_result: Optional[ActionResult]
    answer: str
    persisted: bool
    execution_plan: Dict[str, Any]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def classify_request(state: OrchestratorState) -> Dict[str, Any]:
    """Preliminary intent cues — final route still owned by the reasoner."""
    from app.retailops.reasoning.reasoner import _score_intent

    question = state.get("question") or ""
    intent, confidence = _score_intent(question)
    plan_seed = dict(state.get("execution_plan") or {})
    plan_seed.setdefault("primary_intent", intent)
    plan_seed.setdefault("confidence", confidence)
    return {
        "arguments": state.get("arguments", {}),
        "route": state.get("route") or "rag",
        "action_id": state.get("action_id"),
        "execution_plan": plan_seed,
    }



async def reason_retail_request(state: OrchestratorState) -> Dict[str, Any]:
    reasoner = RetailOperationsReasoner()
    plan = reasoner.reason(
        question=state["question"],
        registry=state["registry"],
        context=state["context"],
        arguments=state.get("arguments", {}),
        disabled_agents=state.get("disabled_agents") or [],
    )
    action_id = plan.recommended_action_ids[0] if plan.recommended_action_ids else None
    return {
        "execution_plan": plan.to_dict(),
        "route": plan.route,
        "action_id": action_id,
        "arguments": {**(state.get("arguments") or {}), **(plan.arguments or {})},
    }


async def retrieve_context(state: OrchestratorState) -> Dict[str, Any]:
    cites = hybrid_search(
        state["session"],
        tenant_id=state["context"].tenant_id,
        project_id=state["context"].project_id,
        query=state["question"],
    )
    return {"citations": [c.to_dict() for c in cites]}


async def resolve_action(state: OrchestratorState) -> Dict[str, Any]:
    spec = state["registry"].resolve(state["action_id"])
    if spec is None:
        return {"route": "unsupported"}
    args = service.enrich_arguments(
        state["session"],
        spec,
        state["context"],
        state.get("arguments", {}),
        query=state["question"],
    )
    return {"arguments": args}


async def execute_action_node(state: OrchestratorState) -> Dict[str, Any]:
    spec = state["registry"].resolve(state["action_id"])
    if spec is None:
        return {"route": "unsupported"}
    result = await execute_action(spec, state["context"], state.get("arguments", {}))
    citations = [e.to_dict() for e in result.evidence]
    return {"action_result": result, "citations": citations}


async def synthesize_response(state: OrchestratorState) -> Dict[str, Any]:
    route = state.get("route")
    provider = state.get("provider") or get_provider()

    if route == "unsupported":
        return {
            "answer": (
                "That request isn't a supported action for this project. "
                "Ask a document question or run one of the registered actions."
            )
        }

    if route == "action":
        result = state.get("action_result")
        if result is None:
            return {"answer": "The action could not be executed."}
        if result.status == ActionStatus.SUCCESS:
            spec = state["registry"].resolve(state["action_id"])
            # FakeProvider only assembles RAG citation lines; action prompts are
            # JSON so they would falsely report "no supporting documents".
            if getattr(provider, "name", "") == "fake":
                return {"answer": _deterministic_action_summary(result)}
            system = (spec.synthesis_instructions if spec else None) or (
                "Summarise the action result for a business user, grounded only in the output."
            )
            prompt = _action_prompt(state["question"], result)
            try:
                answer = await provider.complete(system, prompt)
            except ProviderError:
                answer = _deterministic_action_summary(result)
            return {"answer": answer}
        if result.status == ActionStatus.DEPENDENCY_REQUIRED:
            deps = "; ".join(d.description for d in result.dependencies)
            return {"answer": f"More information is required before this can run: {deps}"}
        if result.status == ActionStatus.PERMISSION_DENIED:
            return {"answer": "You do not have permission to run this action."}
        return {"answer": "The action failed to complete."}

    citations = state.get("citations") or []
    if not citations:
        return {
            "answer": (
                "I could not find supporting information in the project's "
                "documents to answer this question."
            )
        }
    system = (
        "You are a retail operations assistant. Answer strictly from the provided "
        "context and cite sources by their [n] markers. If the context is "
        "insufficient, say so."
    )
    prompt = _rag_prompt(state["question"], citations)
    try:
        answer = await provider.complete(system, prompt)
    except ProviderError:
        answer = (
            "Retrieval succeeded but the language model is unavailable, so no "
            "grounded answer could be generated."
        )
    return {"answer": answer}


async def persist_audit(state: OrchestratorState) -> Dict[str, Any]:
    result = state.get("action_result")
    if result is not None:
        from app.retailops.audit import persist_action_run

        persist_action_run(
            state["session"],
            result=result,
            context=state["context"],
            arguments=state.get("arguments", {}),
        )
        return {"persisted": True}
    return {"persisted": False}


def _rag_prompt(question: str, citations: List[Dict[str, Any]]) -> str:
    lines = [f"Question: {question}", "", "Context:"]
    for i, c in enumerate(citations, start=1):
        loc = c.get("filename") or c.get("document_id") or "source"
        if c.get("page"):
            loc += f" p.{c['page']}"
        lines.append(f"[{i}] {c.get('excerpt', '')} ({loc})")
    return "\n".join(lines)


def _action_prompt(question: str, result: ActionResult) -> str:
    import json

    return (
        f"Question: {question}\n\nAction output (JSON):\n"
        + json.dumps(result.output, default=str)[:4000]
    )


def _deterministic_action_summary(result: ActionResult) -> str:
    keys = ", ".join(sorted(result.output.keys()))
    return (
        f"Action {result.action_id} completed with {len(result.evidence)} evidence "
        f"reference(s). Result sections: {keys}."
    )


def _route_after_reason(state: OrchestratorState) -> str:
    route = state.get("route")
    if route == "action":
        return "resolve_action"
    if route == "unsupported":
        return "synthesize_response"
    return "retrieve_context"


def _route_after_resolve(state: OrchestratorState) -> str:
    return "synthesize_response" if state.get("route") == "unsupported" else "execute_action"


def build_graph():
    graph = StateGraph(OrchestratorState)
    graph.add_node("classify_request", classify_request)
    graph.add_node("reason_retail_request", reason_retail_request)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("resolve_action", resolve_action)
    graph.add_node("execute_action", execute_action_node)
    graph.add_node("synthesize_response", synthesize_response)
    graph.add_node("persist_audit", persist_audit)

    graph.add_edge(START, "classify_request")
    graph.add_edge("classify_request", "reason_retail_request")
    graph.add_conditional_edges(
        "reason_retail_request",
        _route_after_reason,
        {
            "resolve_action": "resolve_action",
            "retrieve_context": "retrieve_context",
            "synthesize_response": "synthesize_response",
        },
    )
    graph.add_conditional_edges(
        "resolve_action",
        _route_after_resolve,
        {"execute_action": "execute_action", "synthesize_response": "synthesize_response"},
    )
    graph.add_edge("execute_action", "synthesize_response")
    graph.add_edge("retrieve_context", "synthesize_response")
    graph.add_edge("synthesize_response", "persist_audit")
    graph.add_edge("persist_audit", END)
    return graph.compile()


_compiled = None


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


def reset_graph() -> None:
    """Drop the compiled graph (tests that mutate the registry during a run)."""
    global _compiled
    _compiled = None


async def run_orchestrator(
    *,
    session: Session,
    context: ActionContext,
    question: str,
    registry: Optional[ActionRegistry] = None,
    provider: Optional[LLMProvider] = None,
    arguments: Optional[Dict[str, Any]] = None,
    disabled_agents: Optional[List[str]] = None,
) -> Dict[str, Any]:
    graph = get_graph()
    registry = registry or service.build_registry()
    provider = provider or get_provider()
    state: OrchestratorState = {
        "question": question,
        "context": context,
        "session": session,
        "registry": registry,
        "provider": provider,
        "arguments": arguments or {},
        "disabled_agents": list(disabled_agents or []),
    }
    final = await graph.ainvoke(state)
    return {
        "route": final.get("route"),
        "action_id": final.get("action_id"),
        "answer": final.get("answer", ""),
        "citations": final.get("citations", []),
        "action_result": final.get("action_result"),
        "execution_plan": final.get("execution_plan"),
    }
