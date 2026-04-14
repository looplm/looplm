"""Code Agent models — eval-driven code suggestions via Claude Agent SDK."""

from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, CodeSuggestionStatus, CodeSuggestionType


class OpenCodeAnalysis(Base):
    __tablename__ = "opencode_analyses"
    __table_args__ = (
        Index("idx_opencode_analyses_project_id", "project_id"),
        Index("idx_opencode_analyses_eval_run_id", "eval_run_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    eval_run_id = Column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(32), nullable=False, server_default=text("'pending'"))
    error = Column(Text, nullable=True)
    files_analyzed = Column(JSONB, nullable=False, server_default=text("'[]'"))
    failure_summary = Column(Text, nullable=True)
    suggestion_count = Column(Integer, nullable=False, server_default=text("0"))
    total_cost_usd = Column(Float, nullable=True)
    num_turns = Column(Integer, nullable=True)
    analysis_mode = Column(String(32), nullable=True, server_default=text("'detailed'"))
    progress_message = Column(String(512), nullable=True)
    progress_log = Column(JSONB, nullable=False, server_default=text("'[]'"))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
    suggestions = relationship(
        "CodeSuggestion", back_populates="analysis", cascade="all, delete-orphan"
    )


class CodeSuggestion(Base):
    __tablename__ = "code_suggestions"
    __table_args__ = (
        Index("idx_code_suggestions_analysis_id", "analysis_id"),
        Index("idx_code_suggestions_project_id", "project_id"),
        Index("idx_code_suggestions_status", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("opencode_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    type = Column(
        Enum(CodeSuggestionType, name="code_suggestion_type"), nullable=False
    )
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    file_path = Column(String(1024), nullable=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    diff = Column(JSONB, nullable=True)
    impact = Column(String(32), nullable=True)
    confidence = Column(Float, nullable=True)
    reasoning = Column(Text, nullable=True)
    related_test_ids = Column(JSONB, nullable=False, server_default=text("'[]'"))
    status = Column(
        Enum(CodeSuggestionStatus, name="code_suggestion_status"),
        nullable=False,
        server_default=text("'pending'"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    analysis = relationship("OpenCodeAnalysis", back_populates="suggestions")
