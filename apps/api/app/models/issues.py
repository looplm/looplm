"""Issue, IssueEvidence, and IssueEvent models.

An ``Issue`` is a cluster of related production failures surfaced from many
traces (the unit the Engine loop operates on): explicit failures, eval
failures, negative feedback, and anomalies are grouped into a single named,
prioritized issue with linked evidence and an append-only event timeline.
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, IssueSeverity, IssueStatus, SignalType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        Index("idx_issues_project_id", "project_id"),
        Index("idx_issues_project_status", "project_id", "status"),
        Index("idx_issues_integration_id", "integration_id"),
        Index("idx_issues_last_seen_at", text("last_seen_at DESC")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    integration_id = Column(
        UUID(as_uuid=True), ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True
    )

    title = Column(String(512), nullable=False)
    description = Column(Text)
    category = Column(String(128))  # e.g. tool_failure, quality_regression, unhandled_request
    severity = Column(
        Enum(IssueSeverity, name="issue_severity"),
        nullable=False,
        server_default=text("'medium'"),
    )
    status = Column(
        Enum(IssueStatus, name="issue_status"), nullable=False, server_default=text("'open'")
    )

    # Which signal types contributed to this cluster (deduplicated list of values).
    signal_types = Column(JSONB, nullable=False, server_default=text("'[]'"))
    # Deterministic fallback key used to merge obvious duplicates without an LLM call.
    fingerprint = Column(String(256))
    # Filled in by the diagnosis step.
    root_cause = Column(Text)
    suggested_fix = Column(Text)

    trace_count = Column(Integer, nullable=False, server_default=text("0"))
    affected_pct = Column(Float, CheckConstraint("affected_pct >= 0 AND affected_pct <= 100"))

    first_seen_at = Column(DateTime(timezone=True))
    last_seen_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=_utcnow,  # Python-side so it works on both Postgres and SQLite (tests)
    )

    evidence = relationship(
        "IssueEvidence", back_populates="issue", cascade="all, delete-orphan"
    )
    events = relationship(
        "IssueEvent", back_populates="issue", cascade="all, delete-orphan"
    )


class IssueEvidence(Base):
    __tablename__ = "issue_evidence"
    __table_args__ = (
        # One piece of evidence per (issue, trace, signal) — re-detection updates, not duplicates.
        UniqueConstraint("issue_id", "trace_id", "signal_type", name="uq_issue_evidence"),
        Index("idx_issue_evidence_issue_id", "issue_id"),
        Index("idx_issue_evidence_trace_id", "trace_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    issue_id = Column(
        UUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    trace_id = Column(
        UUID(as_uuid=True), ForeignKey("traces.id", ondelete="SET NULL"), nullable=True
    )
    signal_type = Column(Enum(SignalType, name="signal_type"), nullable=False)
    detail = Column(Text)
    occurred_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    issue = relationship("Issue", back_populates="evidence")
    trace = relationship("Trace")


class IssueEvent(Base):
    __tablename__ = "issue_events"
    __table_args__ = (Index("idx_issue_events_issue_id", "issue_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    issue_id = Column(
        UUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    # detected | updated | recurred | diagnosed | fix_drafted | evaluator_created | resolved | dismissed
    event_type = Column(String(64), nullable=False)
    detail = Column(JSONB)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    issue = relationship("Issue", back_populates="events")
