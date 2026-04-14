"""Analysis, FixSuggestion, FeedbackScore, and AdvisorAnalysis models."""

from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, FixStatus, FixType


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (Index("idx_analyses_trace_id", "trace_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    trace_id = Column(
        UUID(as_uuid=True), ForeignKey("traces.id", ondelete="CASCADE"), nullable=False
    )
    failure_type = Column(String(128))
    root_cause = Column(Text)
    confidence = Column(Float, CheckConstraint("confidence >= 0 AND confidence <= 1"))
    suggested_fixes = Column(JSONB, nullable=False, server_default=text("'[]'"))
    applied = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    trace = relationship("Trace", back_populates="analyses")
    fix_suggestions = relationship(
        "FixSuggestion", back_populates="analysis", cascade="all, delete-orphan"
    )


class FixSuggestion(Base):
    __tablename__ = "fix_suggestions"
    __table_args__ = (
        Index("idx_fix_suggestions_analysis_id", "analysis_id"),
        Index("idx_fix_suggestions_status", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    analysis_id = Column(
        UUID(as_uuid=True), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    type = Column(Enum(FixType, name="fix_type"), nullable=False)
    title = Column(String(512), nullable=False)
    description = Column(Text)
    diff = Column(JSONB)
    status = Column(
        Enum(FixStatus, name="fix_status"), nullable=False, server_default=text("'pending'")
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    analysis = relationship("Analysis", back_populates="fix_suggestions")


class FeedbackScore(Base):
    __tablename__ = "feedback_scores"
    __table_args__ = (
        UniqueConstraint("integration_id", "external_id"),
        Index("idx_feedback_scores_trace_id_name", "trace_id", "score_name"),
        Index("idx_feedback_scores_name_value", "score_name", "value"),
        Index("idx_feedback_scores_scored_at", text("scored_at DESC")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    integration_id = Column(
        UUID(as_uuid=True), ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    trace_id = Column(
        UUID(as_uuid=True), ForeignKey("traces.id", ondelete="CASCADE"), nullable=True
    )
    external_id = Column(String(512), nullable=False)
    external_trace_id = Column(String(512), nullable=False)
    score_name = Column(String(128), nullable=False)
    value = Column(Float, nullable=False)
    data_type = Column(String(32), nullable=False, server_default=text("'BOOLEAN'"))
    comment = Column(Text)
    scored_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    integration = relationship("Integration")
    trace = relationship("Trace", backref="feedback_scores")


class AdvisorAnalysis(Base):
    __tablename__ = "advisor_analyses"
    __table_args__ = (
        Index("idx_advisor_analyses_integration_id", "integration_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    integration_id = Column(
        UUID(as_uuid=True), ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    suggestions = Column(JSONB, nullable=False, server_default=text("'[]'"))
    analyzed_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    integration = relationship("Integration")
