"""Load and resolve base agents + discipline hats from JSON manifests."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from app.retailops.agents.models import AgentManifest, merged_public_dict

_MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"


class AgentCatalogError(ValueError):
    """Raised when manifests are invalid or incomplete."""


class AgentCatalog:
    """In-memory catalog of base agents and discipline hats."""

    def __init__(self) -> None:
        self._by_id: Dict[str, AgentManifest] = {}

    def register(self, manifest: AgentManifest) -> None:
        if manifest.agent_id in self._by_id:
            raise AgentCatalogError(f"duplicate agent_id '{manifest.agent_id}'")
        self._by_id[manifest.agent_id] = manifest

    def get(self, agent_id: str) -> Optional[AgentManifest]:
        return self._by_id.get(agent_id)

    def bases(self) -> List[AgentManifest]:
        return [m for m in self.all() if m.kind == "base"]

    def hats(self) -> List[AgentManifest]:
        return [m for m in self.all() if m.kind == "hat"]

    def all(self) -> List[AgentManifest]:
        return [self._by_id[k] for k in sorted(self._by_id)]

    def compose(self, hat_id: str) -> Dict:
        hat = self.get(hat_id)
        if hat is None or hat.kind != "hat":
            raise AgentCatalogError(f"unknown hat '{hat_id}'")
        base = self.get(hat.extends or "")
        if base is None or base.kind != "base":
            raise AgentCatalogError(
                f"hat '{hat_id}' extends missing base '{hat.extends}'"
            )
        return merged_public_dict(base, hat)

    def enabled_hats(
        self,
        *,
        disabled: Optional[Iterable[str]] = None,
        question: str = "",
        intent: Optional[str] = None,
    ) -> List[AgentManifest]:
        """Return hats activated for this turn (user can put off by agent_id)."""
        put_off: Set[str] = set(disabled or [])
        q = (question or "").lower()
        out: List[AgentManifest] = []
        for hat in self.hats():
            if hat.agent_id in put_off:
                continue
            if any(sig in put_off for sig in hat.activation.put_off_by):
                continue
            if not hat.activation.default_enabled and hat.activation.mode != "auto":
                # Manual hats still activate when an explicit trigger matches below.
                if not self._triggered(hat, q, intent):
                    continue
            if self._triggered(hat, q, intent):
                out.append(hat)
            elif hat.activation.default_enabled and hat.activation.mode in {
                "auto",
                "hybrid",
            }:
                # Only include auto-enabled when a soft intent/discipline cue matches.
                if intent and intent.replace("_", "") in hat.discipline.replace("_", ""):
                    out.append(hat)
                elif any(
                    t.type == "intent" and t.value == intent
                    for t in hat.activation.triggers
                ):
                    out.append(hat)
        return out

    def recommend_handoffs(
        self,
        agent_id: str,
        *,
        related_domains: Optional[List[str]] = None,
        include_all: bool = False,
    ) -> List[Dict]:
        """Return handoff tips from one agent.

        When ``include_all`` is true (typical for the primary active hat), every
        declared handoff is returned. Otherwise tips are filtered by related
        domain cues against the target discipline / when-clause.
        """
        agent = self.get(agent_id)
        if agent is None:
            return []
        domains = {d.replace("-", "_") for d in (related_domains or [])}
        tips: List[Dict] = []
        for rule in agent.handoffs:
            when = (rule.when or "").lower()
            target = self.get(rule.to_agent_id)
            target_disc = (target.discipline if target else "") or ""
            target_short = rule.to_agent_id.rsplit(".", 1)[-1]
            if include_all or when.startswith("always") or not domains:
                tips.append(rule.to_dict())
                continue
            if target_disc in domains or target_short in domains:
                tips.append(rule.to_dict())
                continue
            if any(d.replace("_", " ") in when for d in domains) or any(
                d in when for d in domains
            ):
                tips.append(rule.to_dict())
        return tips

    @staticmethod
    def _triggered(hat: AgentManifest, question: str, intent: Optional[str]) -> bool:
        for trigger in hat.activation.triggers:
            if trigger.type == "intent" and intent and trigger.value == intent:
                return True
            if trigger.type == "keyword" and trigger.value.lower() in question:
                return True
            if trigger.type == "action_id" and trigger.value.lower() in question:
                return True
            if trigger.type == "user_toggle" and trigger.value in question:
                return True
        return False


def load_manifests_from_dir(directory: Optional[Path] = None) -> AgentCatalog:
    root = directory or _MANIFEST_DIR
    catalog = AgentCatalog()
    if not root.exists():
        return catalog
    for path in sorted(root.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        catalog.register(AgentManifest.model_validate(data))
    # Structural integrity: every hat must extend a known base.
    for hat in catalog.hats():
        base = catalog.get(hat.extends or "")
        if base is None or base.kind != "base":
            raise AgentCatalogError(
                f"hat '{hat.agent_id}' extends unknown base '{hat.extends}'"
            )
    return catalog


@lru_cache(maxsize=1)
def get_agent_catalog() -> AgentCatalog:
    return load_manifests_from_dir()


def reset_agent_catalog() -> None:
    get_agent_catalog.cache_clear()
