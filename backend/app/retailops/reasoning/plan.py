"""Typed RetailExecutionPlan returned by the operations reasoner."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field, field_validator

from app.retailops.kit.contract.models import _DeterministicModel


class RetailExecutionPlan(_DeterministicModel):
    """Auditable plan produced by :class:`RetailOperationsReasoner`.

    The reasoner never calls action handlers. It only recommends registered,
    permitted actions (or RAG / unsupported routes).
    """

    primary_intent: str = "unknown"
    confidence: float = 0.0
    route: str = "rag"  # rag | action | unsupported
    recommended_action_ids: List[str] = Field(default_factory=list)
    related_domains: List[str] = Field(default_factory=list)
    required_dependencies: List[str] = Field(default_factory=list)
    evidence_requirements: List[str] = Field(default_factory=list)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    confirmation_required: bool = False
    notes: List[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator("route")
    @classmethod
    def _validate_route(cls, v: str) -> str:
        allowed = {"rag", "action", "unsupported"}
        if v not in allowed:
            raise ValueError(f"route must be one of {sorted(allowed)}")
        return v


def empty_plan(*, notes: Optional[List[str]] = None) -> RetailExecutionPlan:
    return RetailExecutionPlan(
        primary_intent="unknown",
        confidence=0.0,
        route="rag",
        notes=list(notes or []),
    )
