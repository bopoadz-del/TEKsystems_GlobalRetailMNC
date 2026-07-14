"""Typed discipline-agent manifests (base agent + discipline hats)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, field_validator

from app.retailops.kit.contract.models import _DeterministicModel

ManifestKind = Literal["base", "hat"]
ActivationMode = Literal["manual", "auto", "hybrid"]
MemoryScope = Literal["tenant_project", "tenant", "user_project"]


class ActivationTrigger(_DeterministicModel):
    type: Literal["intent", "keyword", "action_id", "user_toggle"]
    value: str


class ActivationConfig(_DeterministicModel):
    mode: ActivationMode = "hybrid"
    default_enabled: bool = True
    triggers: List[ActivationTrigger] = Field(default_factory=list)
    put_off_by: List[str] = Field(default_factory=list)


class ContextSource(_DeterministicModel):
    source_id: str
    kind: Literal[
        "project_documents",
        "learning_profiles",
        "structured_tables",
        "official_guidance",
        "fixtures",
        "memory",
    ]
    doc_roles: List[str] = Field(default_factory=list)
    modules: List[str] = Field(default_factory=list)
    description: str = ""


class HandoffRule(_DeterministicModel):
    to_agent_id: str
    when: str
    carry: List[str] = Field(default_factory=list)
    requires_confirmation: bool = False


class MemorySaveRule(_DeterministicModel):
    key: str
    description: str
    requires_confirmation: bool = True


class MemoryConfig(_DeterministicModel):
    scope: MemoryScope = "tenant_project"
    save: List[MemorySaveRule] = Field(default_factory=list)
    never_persist: List[str] = Field(
        default_factory=lambda: [
            "llm_raw_text",
            "secrets",
            "cross_tenant_data",
            "unverified_claims",
        ]
    )


class VerificationConfig(_DeterministicModel):
    grounding: Literal[
        "documents_or_learning_only", "documents_only", "structured_only"
    ] = "documents_or_learning_only"
    cite_required: bool = True
    refuse_unaided_figures: bool = True
    checks: List[str] = Field(default_factory=list)


class FailurePolicy(_DeterministicModel):
    on_missing_context: Literal[
        "dependency_required", "unsupported", "ask_clarifying"
    ] = "dependency_required"
    on_unregistered_action: Literal["unsupported", "handoff"] = "unsupported"
    on_low_confidence: Literal["disclose_only", "block", "handoff"] = "disclose_only"


class PlaybookFormula(_DeterministicModel):
    """Named discipline formula — declarative; optional runtime binding."""

    id: str
    name: str
    expression: str
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    implemented_by: Optional[str] = None
    unit: Optional[str] = None
    notes: str = ""


class PlaybookStandard(_DeterministicModel):
    """Policy / regulatory / KPI standard the hat must respect."""

    id: str
    name: str
    kind: Literal["policy", "regulatory", "internal", "kpi", "safety"] = "internal"
    ref: str = ""
    must_cite: bool = True
    description: str = ""


class PlaybookProcedureStep(_DeterministicModel):
    step: int
    action: str
    requires_confirmation: bool = False


class PlaybookProcedure(_DeterministicModel):
    """Ordered operating procedure for the discipline."""

    id: str
    name: str
    steps: List[PlaybookProcedureStep] = Field(default_factory=list)
    trigger: str = ""
    handoff_to: Optional[str] = None
    requires_confirmation: bool = False


class DisciplinePlaybook(_DeterministicModel):
    """Per-hat formulas, standards, and procedures (catalog-ready)."""

    formulas: List[PlaybookFormula] = Field(default_factory=list)
    standards: List[PlaybookStandard] = Field(default_factory=list)
    procedures: List[PlaybookProcedure] = Field(default_factory=list)


class CatalogMeta(_DeterministicModel):
    vendor_neutral: bool = True
    product: str = "TEKsystems RetailOps"
    tags: List[str] = Field(default_factory=list)


class AgentManifest(_DeterministicModel):
    """Base agent or discipline hat — catalog-ready JSON contract."""

    manifest_version: str = "1.0.0"
    agent_id: str
    kind: ManifestKind
    display_name: str
    discipline: str
    extends: Optional[str] = None
    summary: str = ""
    activation: ActivationConfig = Field(default_factory=ActivationConfig)
    context_sources: List[ContextSource] = Field(default_factory=list)
    allowed_paths: List[str] = Field(default_factory=list)
    allowed_actions: List[str] = Field(default_factory=list)
    handoffs: List[HandoffRule] = Field(default_factory=list)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    failure_policy: FailurePolicy = Field(default_factory=FailurePolicy)
    playbook: DisciplinePlaybook = Field(default_factory=DisciplinePlaybook)
    permissions: List[str] = Field(default_factory=list)
    catalog: CatalogMeta = Field(default_factory=CatalogMeta)

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, v: str) -> str:
        import re

        if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", v):
            raise ValueError("agent_id must be namespaced lowercase segments")
        return v

    def model_post_init(self, __context: Any) -> None:  # noqa: D401
        if self.kind == "hat" and not self.extends:
            raise ValueError(f"hat '{self.agent_id}' must declare extends=base agent_id")
        if self.kind == "base" and self.extends:
            raise ValueError(f"base '{self.agent_id}' must not declare extends")
        # Hats that claim a playbook must declare all three dimensions.
        if self.kind == "hat":
            pb = self.playbook
            if not (pb.formulas and pb.standards and pb.procedures):
                raise ValueError(
                    f"hat '{self.agent_id}' playbook must include formulas, "
                    "standards, and procedures"
                )


def _merge_by_id(base_items: List[Dict[str, Any]], hat_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Hat entries override base entries with the same id; preserve order."""
    out: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for item in base_items + hat_items:
        iid = item.get("id")
        if not iid:
            continue
        if iid not in out:
            order.append(iid)
        out[iid] = item
    return [out[i] for i in order]


def merged_public_dict(base: AgentManifest, hat: AgentManifest) -> Dict[str, Any]:
    """Compose base + hat for catalog/UI without mutating either."""
    if hat.kind != "hat":
        raise ValueError("merged_public_dict expects a hat")
    if hat.extends != base.agent_id:
        raise ValueError(f"hat {hat.agent_id} does not extend {base.agent_id}")
    data = base.to_dict()
    hat_data = hat.to_dict()
    base_pb = data.get("playbook") or {}
    hat_pb = hat_data.get("playbook") or {}
    data.update(
        {
            "agent_id": hat.agent_id,
            "kind": "hat",
            "display_name": hat.display_name,
            "discipline": hat.discipline,
            "extends": hat.extends,
            "summary": hat.summary or base.summary,
            "activation": hat_data["activation"],
            "context_sources": hat_data["context_sources"] or data["context_sources"],
            "allowed_paths": sorted(set(base.allowed_paths) | set(hat.allowed_paths)),
            "allowed_actions": sorted(
                set(base.allowed_actions) | set(hat.allowed_actions)
            ),
            "handoffs": hat_data["handoffs"] or data["handoffs"],
            "memory": hat_data["memory"],
            "verification": hat_data["verification"],
            "failure_policy": hat_data["failure_policy"],
            "playbook": {
                "formulas": _merge_by_id(
                    list(base_pb.get("formulas") or []),
                    list(hat_pb.get("formulas") or []),
                ),
                "standards": _merge_by_id(
                    list(base_pb.get("standards") or []),
                    list(hat_pb.get("standards") or []),
                ),
                "procedures": _merge_by_id(
                    list(base_pb.get("procedures") or []),
                    list(hat_pb.get("procedures") or []),
                ),
            },
            "permissions": sorted(set(base.permissions) | set(hat.permissions)),
            "catalog": hat_data["catalog"] or data["catalog"],
            "composed_from": [base.agent_id, hat.agent_id],
        }
    )
    return data
