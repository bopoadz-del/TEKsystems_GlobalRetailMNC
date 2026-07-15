"""Release registry and source-policy helpers for retail_core_open_v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.retailops.packs.retail_core_open_v1 import (
    COLLECTION_ID,
    DOMAIN,
    RAG_PACK_ID,
    RELEASE_ID,
)

_HERE = Path(__file__).resolve().parent
_MANIFEST_PATH = _HERE / "MANIFEST.json"

ALLOWED_SOURCE_CLASSES = {
    "public_domain",
    "open_license",
    "official_statute_or_regulation",
    "official_guidance",
    "platform_curated_template",
}

PRECLUDED_SOURCE_CLASSES = {
    "private_enterprise_data",
    "confidential_client_data",
    "copyrighted_commercial_content_without_license",
    "user_uploaded_project_records",
    "unknown_license",
}


class SourcePolicyError(ValueError):
    """Raised when a source fails licence / authority / class checks."""


def load_manifest() -> Dict[str, Any]:
    with open(_MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def release_identity() -> Dict[str, str]:
    return {
        "release_id": RELEASE_ID,
        "rag_pack_id": RAG_PACK_ID,
        "collection_id": COLLECTION_ID,
        "domain": DOMAIN,
    }


def list_sources() -> List[Dict[str, Any]]:
    return list(load_manifest().get("sources") or [])


def get_source(source_id: str) -> Optional[Dict[str, Any]]:
    for src in list_sources():
        if src.get("source_id") == source_id:
            return src
    return None


def validate_source_record(record: Dict[str, Any]) -> None:
    """Enforce MANIFEST source_policy on a source/acquisition record."""
    policy = load_manifest().get("source_policy") or {}
    allowed = set(policy.get("allowed_source_classes") or ALLOWED_SOURCE_CLASSES)
    precluded = set(policy.get("precluded_source_classes") or PRECLUDED_SOURCE_CLASSES)

    if policy.get("requires_source_record", True):
        if not record.get("source_id") or not record.get("source_name"):
            raise SourcePolicyError("source record missing source_id/source_name")

    source_class = record.get("source_class") or "unknown_license"
    if source_class in precluded or source_class == "unknown_license":
        raise SourcePolicyError(f"precluded or unknown source_class: {source_class}")
    if source_class not in allowed:
        raise SourcePolicyError(f"source_class not allowed: {source_class}")

    if policy.get("requires_license_review", True):
        if source_class == "open_license" and not record.get("licence"):
            raise SourcePolicyError("open_license source requires licence field")
        if source_class == "official_guidance" and not record.get("publisher"):
            raise SourcePolicyError("official_guidance requires publisher")

    if policy.get("requires_authority_rating", True):
        if not record.get("authority_level"):
            raise SourcePolicyError("authority_level required")

    # Tenant/project user uploads must never enter the prebuilt collection.
    if record.get("knowledge_layer") == "tenant_project":
        raise SourcePolicyError("tenant/project records cannot enter platform-prebuilt")
