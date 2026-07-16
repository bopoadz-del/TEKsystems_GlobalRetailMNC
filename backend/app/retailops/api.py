"""Generic action + RAG + document + audit HTTP API for the RetailOps runtime.

Endpoints:
    GET  /v1/actions
    GET  /v1/actions/{action_id}
    POST /v1/actions/{action_id}/execute
    POST /v1/ask                      (LangGraph orchestration)
    GET  /v1/agents                   (discipline base + hats catalog)
    GET  /v1/agents/{agent_id}
    GET  /v1/agents/memory
    POST /v1/agents/memory
    POST /v1/exports                  (stream PDF/DOCX/XLSX download)
    POST /v1/documents                (ingest)
    GET  /v1/documents
    GET  /v1/audit
    GET  /v1/overview
    GET  /health

The execute route is fully generic: adding an action to a kit needs no router
change. Trusted context (tenant/project/permissions) is resolved server-side
from the authenticated principal and never from the request body.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.retailops import service
from app.retailops.audit import list_action_runs, persist_action_run
from app.retailops.db import get_session
from app.retailops.kit.contract import ActionContext, ActionResult, ActionStatus
from app.retailops.kit.contract.models import ActionResult as _AR
from app.retailops.models import Document, Project, User
from app.retailops.orchestrator import run_orchestrator

router = APIRouter()

# Domains installed in this generated product (server-controlled allow-list).
INSTALLED_DOMAINS = ["retail"]


# ---------------------------------------------------------------------------
# Trusted context resolution
# ---------------------------------------------------------------------------

def get_context(
    session: Session = Depends(get_session),
    x_user_id: Optional[str] = Header(None),
    x_tenant_id: Optional[str] = Header(None),
    x_project_id: Optional[str] = Header(None),
) -> ActionContext:
    if not (x_user_id and x_tenant_id and x_project_id):
        raise HTTPException(status_code=401, detail="missing X-User-Id/X-Tenant-Id/X-Project-Id")
    user = session.get(User, x_user_id)
    if user is None or user.tenant_id != x_tenant_id:
        raise HTTPException(status_code=403, detail="unknown principal for tenant")
    # Project must exist under the same tenant — blocks invented / cross-tenant IDs.
    project = session.get(Project, x_project_id)
    if project is None or project.tenant_id != x_tenant_id:
        raise HTTPException(status_code=403, detail="unknown project for tenant")
    # Permissions are read from the trusted user record, never from the client.
    return ActionContext(
        user_id=user.id,
        tenant_id=x_tenant_id,
        organisation_id=x_tenant_id,
        project_id=project.id,
        permissions=list(user.permissions or []),
        allowed_domains=list(INSTALLED_DOMAINS),
        corpus_id=project.id,
        knowledge_layer="project",
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    arguments: Dict[str, Any] = Field(default_factory=dict)
    auto_context: bool = True
    confirm: bool = False


class AskRequest(BaseModel):
    question: str
    disabled_agents: List[str] = Field(default_factory=list)


class IngestRequest(BaseModel):
    filename: str
    content_base64: Optional[str] = None
    text: Optional[str] = None
    content_type: Optional[str] = None
    doc_role: Optional[str] = None


# ---------------------------------------------------------------------------
# Action discovery + execution
# ---------------------------------------------------------------------------

@router.get("/v1/actions")
def list_actions(context: ActionContext = Depends(get_context)) -> Dict[str, Any]:
    registry = service.build_registry()
    return {"actions": [s.public_dict() for s in registry.list_permitted(context)]}


@router.get("/v1/actions/{action_id}")
def get_action(action_id: str, context: ActionContext = Depends(get_context)) -> Dict[str, Any]:
    registry = service.build_registry()
    spec = registry.resolve(action_id)
    if spec is None or not context.allows_domain(spec.domain):
        raise HTTPException(status_code=404, detail={"status": "unsupported", "action_id": action_id})
    return spec.public_dict()


def _unsupported_result(action_id: str) -> ActionResult:
    now = datetime.now(timezone.utc)
    return _AR(
        request_id=f"act_{uuid.uuid4().hex}",
        action_id=action_id if "." in action_id else f"unknown.{action_id}",
        status=ActionStatus.UNSUPPORTED,
        started_at=now,
        completed_at=now,
        duration_ms=0,
        error_code="unsupported_action",
        error_message=f"action '{action_id}' is not registered",
    )


@router.post("/v1/actions/{action_id}/execute")
async def execute(
    action_id: str,
    body: ExecuteRequest,
    session: Session = Depends(get_session),
    context: ActionContext = Depends(get_context),
) -> Dict[str, Any]:
    registry = service.build_registry()
    spec = registry.resolve(action_id)
    if spec is None:
        result = _unsupported_result(action_id)
        return result.to_dict()

    arguments = dict(body.arguments or {})
    if body.auto_context:
        arguments = service.enrich_arguments(session, spec, context, arguments)
    result = await service.execute_and_audit(
        session, spec, context, arguments, confirmed=body.confirm
    )
    session.commit()
    return result.to_dict()


# ---------------------------------------------------------------------------
# RAG / orchestration
# ---------------------------------------------------------------------------

@router.post("/v1/ask")
async def ask(
    body: AskRequest,
    session: Session = Depends(get_session),
    context: ActionContext = Depends(get_context),
) -> Dict[str, Any]:
    outcome = await run_orchestrator(
        session=session,
        context=context,
        question=body.question,
        disabled_agents=body.disabled_agents,
    )
    session.commit()
    result = outcome.get("action_result")
    return {
        "route": outcome["route"],
        "action_id": outcome.get("action_id"),
        "answer": outcome["answer"],
        "citations": outcome.get("citations", []),
        "action_result": result.to_dict() if result is not None else None,
        "execution_plan": outcome.get("execution_plan"),
    }


# ---------------------------------------------------------------------------
# Discipline agents (base + hats) — catalog, not a second orchestrator
# ---------------------------------------------------------------------------

@router.get("/v1/agents")
def list_agents(
    composed: bool = True,
    context: ActionContext = Depends(get_context),
) -> Dict[str, Any]:
    if not context.has_permission("retail:read"):
        raise HTTPException(status_code=403, detail="missing retail:read")
    from app.retailops.agents import get_agent_catalog

    catalog = get_agent_catalog()
    bases = [m.to_dict() for m in catalog.bases()]
    if composed:
        hats = [catalog.compose(h.agent_id) for h in catalog.hats()]
    else:
        hats = [h.to_dict() for h in catalog.hats()]
    return {
        "vendor_neutral": True,
        "catalog_product": "TEKsystems RetailOps",
        "base_count": len(bases),
        "hat_count": len(hats),
        "bases": bases,
        "hats": hats,
    }



class MemorySaveRequest(BaseModel):
    agent_id: str
    key: str
    value: Dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False


@router.get("/v1/agents/memory")
def list_agent_memory(
    agent_id: Optional[str] = None,
    key: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_session),
    context: ActionContext = Depends(get_context),
) -> Dict[str, Any]:
    if not context.has_permission("retail:read"):
        raise HTTPException(status_code=403, detail="missing retail:read")
    from app.retailops.agents.memory import list_memory, memory_to_dict

    rows = list_memory(
        session,
        tenant_id=context.tenant_id,
        project_id=context.project_id,
        agent_id=agent_id,
        key=key,
        limit=limit,
        offset=offset,
    )
    return {
        "advisory_only": True,
        "count": len(rows),
        "entries": [memory_to_dict(r) for r in rows],
    }


@router.post("/v1/agents/memory")
def save_agent_memory(
    body: MemorySaveRequest,
    session: Session = Depends(get_session),
    context: ActionContext = Depends(get_context),
) -> Dict[str, Any]:
    if not context.has_permission("retail:analyse"):
        raise HTTPException(status_code=403, detail="missing retail:analyse")
    from app.retailops.agents.memory import AgentMemoryError, memory_to_dict, save_memory

    try:
        row = save_memory(
            session,
            tenant_id=context.tenant_id,
            project_id=context.project_id,
            user_id=context.user_id,
            agent_id=body.agent_id,
            key=body.key,
            value=body.value,
            confirmed=body.confirm,
        )
    except AgentMemoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return {"status": "saved", "entry": memory_to_dict(row), "advisory_only": True}


@router.get("/v1/agents/{agent_id}")
def get_agent(
    agent_id: str,
    composed: bool = True,
    context: ActionContext = Depends(get_context),
) -> Dict[str, Any]:
    if not context.has_permission("retail:read"):
        raise HTTPException(status_code=403, detail="missing retail:read")
    from app.retailops.agents import get_agent_catalog
    from app.retailops.agents.catalog import AgentCatalogError

    catalog = get_agent_catalog()
    manifest = catalog.get(agent_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"unknown agent '{agent_id}'")
    if manifest.kind == "hat" and composed:
        try:
            return catalog.compose(agent_id)
        except AgentCatalogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return manifest.to_dict()


# ---------------------------------------------------------------------------
# Document exports (PDF / DOCX / XLSX)
# ---------------------------------------------------------------------------

class ExportRequest(BaseModel):
    format: str = Field(..., description="pdf | docx | xlsx")
    document_kind: str = Field(
        "custom",
        description="custom | operations_brief | inventory_risk | learning_summary",
    )
    title: Optional[str] = None
    subtitle: Optional[str] = None
    source_output: Optional[Dict[str, Any]] = None
    sections: Optional[List[Dict[str, Any]]] = None
    table: Optional[Dict[str, Any]] = None
    tables: Optional[List[Dict[str, Any]]] = None
    period: Optional[str] = "daily"
    store: Optional[str] = None
    module: Optional[str] = None
    profiles: Optional[List[Dict[str, Any]]] = None
    auto_context: bool = True


@router.post("/v1/exports")
async def export_file(
    body: ExportRequest,
    session: Session = Depends(get_session),
    context: ActionContext = Depends(get_context),
):
    """Generate and stream a PDF/DOCX/XLSX download."""
    import base64

    from fastapi.responses import Response

    registry = service.build_registry()
    spec = registry.resolve("retail.export_document")
    if spec is None:
        raise HTTPException(status_code=404, detail="export action not registered")

    arguments: Dict[str, Any] = {
        "format": body.format,
        "document_kind": body.document_kind,
        "include_base64": True,
    }
    for key in (
        "title",
        "subtitle",
        "source_output",
        "sections",
        "table",
        "tables",
        "period",
        "store",
        "module",
        "profiles",
    ):
        value = getattr(body, key)
        if value is not None:
            arguments[key] = value

    if body.auto_context:
        arguments = service.enrich_arguments(session, spec, context, arguments)
    result = await service.execute_and_audit(
        session, spec, context, arguments, confirmed=False
    )
    session.commit()
    if result.status != ActionStatus.SUCCESS:
        raise HTTPException(status_code=400, detail=result.to_dict())

    payload = result.output or {}
    raw_b64 = payload.get("document_base64")
    if not raw_b64:
        raise HTTPException(status_code=500, detail="export produced no document bytes")
    data = base64.b64decode(raw_b64)
    filename = str(payload.get("filename") or f"export.{body.format}")
    content_type = str(payload.get("content_type") or "application/octet-stream")
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Sha256": str(payload.get("sha256") or ""),
            "X-Export-Request-Id": result.request_id,
        },
    )


# ---------------------------------------------------------------------------
# Documents / ingestion
# ---------------------------------------------------------------------------

@router.post("/v1/documents")
def ingest(
    body: IngestRequest,
    session: Session = Depends(get_session),
    context: ActionContext = Depends(get_context),
) -> Dict[str, Any]:
    import base64

    from app.retailops.ingestion import ingest_document

    if body.content_base64:
        data = base64.b64decode(body.content_base64)
    elif body.text is not None:
        data = body.text.encode("utf-8")
    else:
        raise HTTPException(status_code=400, detail="provide content_base64 or text")

    doc = ingest_document(
        session,
        tenant_id=context.tenant_id,
        project_id=context.project_id,
        filename=body.filename,
        data=data,
        content_type=body.content_type,
    )
    if body.doc_role:
        meta = dict(doc.meta or {})
        meta["doc_role"] = body.doc_role
        doc.meta = meta
    session.commit()
    return {
        "document_id": doc.id,
        "status": doc.status,
        "chunk_count": doc.chunk_count,
        "page_count": doc.page_count,
        "filename": doc.filename,
    }


@router.get("/v1/documents")
def list_documents(
    session: Session = Depends(get_session),
    context: ActionContext = Depends(get_context),
) -> Dict[str, Any]:
    stmt = (
        select(Document)
        .where(
            Document.tenant_id == context.tenant_id,
            Document.project_id == context.project_id,
        )
        .order_by(Document.created_at.desc())
    )
    docs = session.execute(stmt).scalars().all()
    return {
        "documents": [
            {
                "document_id": d.id,
                "filename": d.filename,
                "status": d.status,
                "chunk_count": d.chunk_count,
                "page_count": d.page_count,
                "content_type": d.content_type,
                "doc_role": (d.meta or {}).get("doc_role"),
                "error": d.error,
            }
            for d in docs
        ]
    }


# ---------------------------------------------------------------------------
# Audit + overview
# ---------------------------------------------------------------------------

@router.get("/v1/audit")
def audit(
    session: Session = Depends(get_session),
    context: ActionContext = Depends(get_context),
) -> Dict[str, Any]:
    runs = list_action_runs(session, tenant_id=context.tenant_id, project_id=context.project_id)
    return {
        "runs": [
            {
                "request_id": r.request_id,
                "action_id": r.action_id,
                "user_id": r.user_id,
                "project_id": r.project_id,
                "status": r.status,
                "started_at": r.started_at.isoformat(),
                "duration_ms": r.duration_ms,
                "evidence_count": r.evidence_count,
                "kit_version": r.kit_version,
                "error_code": r.error_code,
            }
            for r in runs
        ]
    }


@router.get("/v1/overview")
def overview(
    session: Session = Depends(get_session),
    context: ActionContext = Depends(get_context),
) -> Dict[str, Any]:
    doc_count = session.execute(
        select(func.count(Document.id)).where(
            Document.tenant_id == context.tenant_id,
            Document.project_id == context.project_id,
        )
    ).scalar_one()
    runs = list_action_runs(
        session, tenant_id=context.tenant_id, project_id=context.project_id, limit=5
    )
    return {
        "project_id": context.project_id,
        "document_count": doc_count,
        "recent_actions": [
            {"action_id": r.action_id, "status": r.status, "started_at": r.started_at.isoformat()}
            for r in runs
        ],
        "system_health": {"database": "ok", "kit_domains": INSTALLED_DOMAINS},
    }


@router.get("/v1/packs/retail_core_open_v1")
def pack_release_status(session: Session = Depends(get_session)) -> Dict[str, Any]:
    """Inspect retail_core_open_v1 release identity, sources, and load counts."""
    from app.retailops.models import RetailPackSource, RetailSale, RetailTransaction
    from app.retailops.packs.retail_core_open_v1 import RELEASE_ID
    from app.retailops.packs.retail_core_open_v1.registry import load_manifest, release_identity

    sources = session.execute(
        select(RetailPackSource).where(RetailPackSource.release_id == RELEASE_ID)
    ).scalars().all()
    sales = session.execute(
        select(func.count()).select_from(RetailSale).where(RetailSale.release_id == RELEASE_ID)
    ).scalar_one()
    txns = session.execute(
        select(func.count()).select_from(RetailTransaction).where(
            RetailTransaction.release_id == RELEASE_ID
        )
    ).scalar_one()
    return {
        "identity": release_identity(),
        "manifest": {
            "release_id": load_manifest().get("release_id"),
            "source_count": len(load_manifest().get("sources") or []),
        },
        "loaded_sources": [
            {
                "source_id": s.source_id,
                "status": s.status,
                "structured_row_count": s.structured_row_count,
                "document_count": s.document_count,
                "chunk_count": s.chunk_count,
                "content_checksum": s.content_checksum,
                "knowledge_layer": s.knowledge_layer,
            }
            for s in sources
        ],
        "counts": {"retail_sales": sales, "retail_transactions": txns},
    }


@router.get("/v1/packs/hf_retail")
def hf_retail_packs_status(session: Session = Depends(get_session)) -> Dict[str, Any]:
    """Inspect Hugging Face retail RAG packs (Bitext, SOPBench, mSOP, rescommons)."""
    from app.retailops.models import RetailPackSource
    from app.retailops.packs.promo_leaflet_rag_v1 import RELEASE_ID as PROMO_ID
    from app.retailops.packs.retail_cx_policies_v1 import RELEASE_ID as CX_ID
    from app.retailops.packs.retail_ecom_rag_eval_v1 import RELEASE_ID as EVAL_ID
    from app.retailops.packs.retail_ops_sops_v1 import RELEASE_ID as SOPS_ID

    release_ids = [CX_ID, SOPS_ID, PROMO_ID, EVAL_ID]
    sources = session.execute(
        select(RetailPackSource).where(RetailPackSource.release_id.in_(release_ids))
    ).scalars().all()
    by_release: Dict[str, List[Dict[str, Any]]] = {rid: [] for rid in release_ids}
    for s in sources:
        by_release.setdefault(s.release_id, []).append(
            {
                "source_id": s.source_id,
                "status": s.status,
                "document_count": s.document_count,
                "chunk_count": s.chunk_count,
                "content_checksum": s.content_checksum,
                "licence": s.licence,
                "publisher": s.publisher,
            }
        )
    return {
        "packs": [
            {
                "release_id": CX_ID,
                "hub": "bitext/Bitext-retail-ecommerce-llm-chatbot-training-dataset",
                "role": "general_cx_policies",
                "loaded_sources": by_release.get(CX_ID, []),
            },
            {
                "release_id": SOPS_ID,
                "hub": "amazon/sop-bench",
                "role": "ops_sop_texts",
                "loaded_sources": by_release.get(SOPS_ID, []),
            },
            {
                "release_id": PROMO_ID,
                "hub": "retail-product-promotion/mSOP-765k",
                "role": "multi_brand_promo_leaflets",
                "loaded_sources": by_release.get(PROMO_ID, []),
            },
            {
                "release_id": EVAL_ID,
                "hub": "rescommons/Ecom-Chatbot-Finetuning-Dataset",
                "role": "rag_eval_plus_selective_snippets",
                "loaded_sources": by_release.get(EVAL_ID, []),
            },
        ]
    }


@router.get("/v1/learning/summary")
def learning_summary(
    module: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_session),
    context: ActionContext = Depends(get_context),
) -> Dict[str, Any]:
    if not context.has_permission("retail:read"):
        raise HTTPException(status_code=403, detail="missing retail:read")
    from app.retailops.learning import RetailOutcomeLearningEngine, profile_to_dict

    engine = RetailOutcomeLearningEngine()
    profiles = engine.list_profiles(
        session,
        tenant_id=context.tenant_id,
        project_id=context.project_id,
        module=module,
        limit=limit,
        offset=offset,
    )
    return {
        "advisory_only": True,
        "count": len(profiles),
        "profiles": [profile_to_dict(p) for p in profiles],
    }


@router.get("/v1/learning/profiles")
def learning_profiles(
    module: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_key: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_session),
    context: ActionContext = Depends(get_context),
) -> Dict[str, Any]:
    if not context.has_permission("retail:read"):
        raise HTTPException(status_code=403, detail="missing retail:read")
    from app.retailops.learning import RetailOutcomeLearningEngine, profile_to_dict

    engine = RetailOutcomeLearningEngine()
    profiles = engine.list_profiles(
        session,
        tenant_id=context.tenant_id,
        project_id=context.project_id,
        module=module,
        entity_type=entity_type,
        entity_key=entity_key,
        limit=limit,
        offset=offset,
    )
    return {
        "advisory_only": True,
        "count": len(profiles),
        "profiles": [profile_to_dict(p) for p in profiles],
    }
