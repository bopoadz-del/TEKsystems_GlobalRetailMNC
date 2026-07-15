"""SQLAlchemy ORM models for the RetailOps operational store.

Primary store is PostgreSQL 16 + pgvector. Document chunks carry both a dense
vector embedding (pgvector) and a generated ``tsvector`` lexical representation
so hybrid (semantic + lexical) retrieval runs entirely in Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.retailops.config import EMBED_DIM


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    permissions: Mapped[List[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "canonical_name", name="uq_project_canonical"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(128))
    source_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    chunks: Mapped[List["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(index=True)
    project_id: Mapped[str] = mapped_column(index=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_ordinal: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector(EMBED_DIM))
    # Generated lexical representation (BM25-equivalent ranking via ts_rank_cd).
    text_tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', text)", persisted=True),
    )
    source_filename: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sheet: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    row_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    row_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    document: Mapped["Document"] = relationship(back_populates="chunks")


class ActionRun(Base):
    __tablename__ = "action_runs"

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(index=True)
    project_id: Mapped[str] = mapped_column(index=True)
    user_id: Mapped[str] = mapped_column(String(64))
    action_id: Mapped[str] = mapped_column(String(128), index=True)
    kit_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer)
    dependencies: Mapped[List[Any]] = mapped_column(JSONB, default=list)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    input_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    output_metadata: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    warnings: Mapped[List[str]] = mapped_column(JSONB, default=list)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(index=True)
    project_id: Mapped[str] = mapped_column(index=True)
    user_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(index=True)
    project_id: Mapped[str] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[List[Any]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ---------------------------------------------------------------------------
# retail_core_open_v1 structured public evaluation tables
# ---------------------------------------------------------------------------


class RetailPackSource(Base):
    """Acquisition / licence governance row for a content release source."""

    __tablename__ = "retail_pack_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    release_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    rag_pack_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    collection_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    knowledge_layer: Mapped[str] = mapped_column(String(64), default="structured_public_eval")
    source_name: Mapped[str] = mapped_column(String(255))
    source_class: Mapped[str] = mapped_column(String(64))
    authority_level: Mapped[str] = mapped_column(String(64))
    licence: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    publisher: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resolved_download_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    acquisition_record: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    structured_row_count: Mapped[int] = mapped_column(Integer, default=0)
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ---------------------------------------------------------------------------
# Outcome learning tables (verified operational events + calculated advisories)
# ---------------------------------------------------------------------------


class RetailLearningEvent(Base):
    """Immutable verified operational observation used for outcome learning."""

    __tablename__ = "retail_learning_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "deduplication_key",
            name="uq_learning_event_dedupe",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    module: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_key: Mapped[str] = mapped_column(String(255), index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    planned_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    event_payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_document_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_action_run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_reference: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(32), default="unverified")
    verified_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deduplication_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RetailLearningProfile(Base):
    """Calculated advisory knowledge scoped to a tenant + project."""

    __tablename__ = "retail_learning_profiles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "module",
            "entity_type",
            "entity_key",
            name="uq_learning_profile_entity",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    module: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_key: Mapped[str] = mapped_column(String(255), index=True)
    metrics: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[str] = mapped_column(String(16), default="low")
    source_period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_calculated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ---------------------------------------------------------------------------
# retail_core_open_v1 structured public evaluation tables (row-level data)
# ---------------------------------------------------------------------------


class RetailProduct(Base):
    __tablename__ = "retail_products"
    __table_args__ = (
        UniqueConstraint("release_id", "source_id", "sku", name="uq_retail_product_sku"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    release_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    sku: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class RetailSale(Base):
    __tablename__ = "retail_sales"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    release_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    source_row: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    store_id: Mapped[str] = mapped_column(String(64), index=True)
    sku: Mapped[str] = mapped_column(String(128), index=True)
    sale_date: Mapped[str] = mapped_column(String(32), index=True)
    sale_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    activity_flag: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    holiday_flag: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    weather: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class RetailStockStatus(Base):
    __tablename__ = "retail_stock_status"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    release_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    source_row: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    store_id: Mapped[str] = mapped_column(String(64), index=True)
    sku: Mapped[str] = mapped_column(String(128), index=True)
    sale_date: Mapped[str] = mapped_column(String(32), index=True)
    stockout_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_stockout_event: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class RetailPromotion(Base):
    __tablename__ = "retail_promotions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    release_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    store_id: Mapped[str] = mapped_column(String(64), index=True)
    sku: Mapped[str] = mapped_column(String(128), index=True)
    period_start: Mapped[str] = mapped_column(String(32))
    period_end: Mapped[str] = mapped_column(String(32))
    discount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    activity_flag: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class RetailTransaction(Base):
    __tablename__ = "retail_transactions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    release_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    source_row: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_sheet: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    invoice: Mapped[str] = mapped_column(String(64), index=True)
    sku: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    invoice_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_cancellation: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


# ---------------------------------------------------------------------------
# Discipline-hat teachable memory
# ---------------------------------------------------------------------------


class RetailAgentMemory(Base):
    """Confirmed discipline-hat memory entries (teachable overrides).

    Writes require explicit confirmation and must match a hat ``memory.save`` key.
    Never stores LLM free text, secrets, or PII payloads.
    """

    __tablename__ = "retail_agent_memory"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "agent_id",
            "key",
            name="uq_agent_memory_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(128), index=True)
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[str] = mapped_column(String(64))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
