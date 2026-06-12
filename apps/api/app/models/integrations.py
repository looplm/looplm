"""Integration, Trace, and Span models."""

from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, IntegrationType, SpanType, SyncStatus, TraceStatus


class Integration(Base):
    __tablename__ = "integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type = Column(Enum(IntegrationType, name="integration_type"), nullable=False)
    name = Column(String(255), nullable=False)
    config = Column(JSONB, nullable=False, server_default=text("'{}'"))

    api_key = Column(LargeBinary, nullable=False)  # encrypted at app layer
    base_url = Column(String(2048))
    sync_status = Column(
        Enum(SyncStatus, name="sync_status"), nullable=False, server_default=text("'never'")
    )
    last_synced_at = Column(DateTime(timezone=True))
    last_sync_error = Column(Text)
    sync_progress_current = Column(Integer)
    sync_progress_total = Column(Integer)
    sync_started_at = Column(DateTime(timezone=True))
    sync_phase = Column(String(32))
    sync_message = Column(String(255))
    sync_since = Column(DateTime(timezone=True))
    # Push-based liveness for first-party (looplm) integrations: last time a
    # trace was received via the ingest endpoint. Distinct from last_synced_at
    # (pull-based) so the two semantics don't collide.
    last_received_at = Column(DateTime(timezone=True))
    # Auto-sync schedule (pull-based integrations only). NULL = disabled; a
    # positive value = run a sync every N minutes. next_sync_at is the durable
    # "due" marker — the poller advances it before each run so a failed sync
    # backs off to the next interval instead of being retried every tick.
    auto_sync_interval_minutes = Column(Integer)
    next_sync_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project", back_populates="integrations")
    traces = relationship("Trace", back_populates="integration", cascade="all, delete-orphan")
    ingest_keys = relationship(
        "IngestKey", back_populates="integration", cascade="all, delete-orphan"
    )


class Trace(Base):
    __tablename__ = "traces"
    __table_args__ = (
        UniqueConstraint("integration_id", "external_id"),
        Index("idx_traces_integration_id", "integration_id"),
        Index("idx_traces_status", "status"),
        Index("idx_traces_start_time", text("start_time DESC")),
        Index("idx_traces_integration_status", "integration_id", "status"),
        Index("idx_traces_integration_start_time", "integration_id", text("start_time DESC")),
        # Keyset pagination cursor: (integration_id, start_time DESC, id DESC).
        Index(
            "idx_traces_integration_start_time_id",
            "integration_id",
            text("start_time DESC"),
            text("id DESC"),
        ),
        Index("idx_traces_created_at", text("created_at DESC")),
        Index("idx_traces_thread_id", "thread_id", postgresql_where=text("thread_id IS NOT NULL")),
        Index("idx_traces_integration_thread_id", "integration_id", "thread_id"),
        Index("idx_traces_parent_trace_id", "parent_trace_id"),
        Index("idx_traces_root_trace_id", "root_trace_id"),
        Index("idx_traces_user_id", "user_id", postgresql_where=text("user_id IS NOT NULL")),
        # Partial index drives the signal poller's "not yet classified" scan cheaply.
        Index(
            "idx_traces_unclassified",
            text("created_at DESC"),
            postgresql_where=text("signals_classified_at IS NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    integration_id = Column(
        UUID(as_uuid=True), ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    external_id = Column(String(512), nullable=False)
    name = Column(String(512))
    input = Column(JSONB)
    output = Column(JSONB)
    trace_metadata = Column("metadata", JSONB, nullable=False, server_default=text("'{}'"))

    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True))
    duration_ms = Column(Integer)
    status = Column(Enum(TraceStatus, name="trace_status"))
    error_message = Column(Text)
    raw_data = Column(JSONB)
    thread_id = Column(String(512), nullable=True)
    user_id = Column(String(512), nullable=True)
    parent_trace_id = Column(
        UUID(as_uuid=True), ForeignKey("traces.id", ondelete="CASCADE"), nullable=True
    )
    root_trace_id = Column(
        UUID(as_uuid=True), ForeignKey("traces.id", ondelete="CASCADE"), nullable=True
    )
    run_type = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    # Watermark for the behavioral signal classifier: NULL means not yet considered.
    # Set once a trace has been classified (or deliberately sampled out) so the
    # poller doesn't reconsider it.
    signals_classified_at = Column(DateTime(timezone=True), nullable=True)

    integration = relationship("Integration", back_populates="traces")
    spans = relationship("Span", back_populates="trace", cascade="all, delete-orphan")
    analyses = relationship("Analysis", back_populates="trace", cascade="all, delete-orphan")
    parent_trace = relationship(
        "Trace",
        remote_side=[id],
        foreign_keys=[parent_trace_id],
        backref="child_traces",
    )
    root_trace = relationship(
        "Trace",
        remote_side=[id],
        foreign_keys=[root_trace_id],
    )


class Span(Base):
    __tablename__ = "spans"
    __table_args__ = (
        Index("idx_spans_trace_id", "trace_id"),
        Index("idx_spans_type", "type"),
        Index("idx_spans_parent_span_id", "parent_span_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    trace_id = Column(
        UUID(as_uuid=True), ForeignKey("traces.id", ondelete="CASCADE"), nullable=False
    )
    parent_span_id = Column(
        UUID(as_uuid=True), ForeignKey("spans.id", ondelete="SET NULL")
    )
    external_id = Column(String(512))
    name = Column(String(512))
    type = Column(Enum(SpanType, name="span_type"))
    input = Column(JSONB)
    output = Column(JSONB)
    model = Column(String(255))
    tokens_in = Column(Integer)
    tokens_out = Column(Integer)
    duration_ms = Column(Integer)
    status = Column(String(64))
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    trace = relationship("Trace", back_populates="spans")
    parent = relationship("Span", remote_side=[id], backref="children")


class IngestKey(Base):
    """An API key that authorizes an SDK/machine client to push traces into a
    first-party (looplm) integration.

    Unlike third-party credentials (stored encrypted/reversible in
    Integration.api_key), these are secrets *we* issue, so we keep only a
    sha256 hash and verify by hashing the presented key — the plaintext is
    shown to the user exactly once at creation.
    """

    __tablename__ = "ingest_keys"
    __table_args__ = (
        Index("idx_ingest_keys_integration_id", "integration_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    integration_id = Column(
        UUID(as_uuid=True), ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False, server_default=text("'default'"))
    key_hash = Column(String(64), nullable=False, unique=True)  # sha256 hex
    key_prefix = Column(String(16), nullable=False)  # e.g. "llm_sk_ab12" for display
    last_used_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    integration = relationship("Integration", back_populates="ingest_keys")
