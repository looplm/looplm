"""Feedback evaluation models — LLM-powered feedback quality analysis."""

from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
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

from app.models.base import Base


class FeedbackEvaluatorConfig(Base):
    """Per-project configuration for the feedback quality evaluator."""

    __tablename__ = "feedback_evaluator_configs"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_feedback_evaluator_config_project"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    prompt = Column(Text, nullable=False)
    verdicts = Column(JSONB, nullable=False, server_default=text("'[\"suspicious\", \"helpful\", \"unhelpful\"]'"))
    default_verdict = Column(String(32), nullable=False, server_default=text("'unhelpful'"))
    model = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")


class FeedbackEvaluation(Base):
    __tablename__ = "feedback_evaluations"
    __table_args__ = (
        Index("idx_feedback_evaluations_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(32), nullable=False, server_default=text("'pending'"))
    error = Column(Text, nullable=True)
    total_count = Column(Integer, nullable=False, server_default=text("0"))
    evaluated_count = Column(Integer, nullable=False, server_default=text("0"))
    suspicious_count = Column(Integer, nullable=False, server_default=text("0"))
    helpful_count = Column(Integer, nullable=False, server_default=text("0"))
    unhelpful_count = Column(Integer, nullable=False, server_default=text("0"))
    verdict_counts = Column(JSONB, nullable=False, server_default=text("'{}'"))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
    results = relationship(
        "FeedbackEvalResult", back_populates="evaluation", cascade="all, delete-orphan"
    )


class FeedbackEvalResult(Base):
    __tablename__ = "feedback_eval_results"
    __table_args__ = (
        Index("idx_feedback_eval_results_evaluation_id", "evaluation_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    evaluation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("feedback_evaluations.id", ondelete="CASCADE"),
        nullable=True,
    )
    feedback_id = Column(UUID(as_uuid=True), nullable=False)
    trace_id = Column(UUID(as_uuid=True), nullable=True)
    score_name = Column(String(128), nullable=False)
    value = Column(Float, nullable=False)
    comment = Column(Text, nullable=True)
    trace_input_preview = Column(Text, nullable=True)
    verdict = Column(String(32), nullable=False)
    reasoning = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    evaluation = relationship("FeedbackEvaluation", back_populates="results")


class TopQuestionsAnalysis(Base):
    """Stores results of LLM-based question clustering analysis."""

    __tablename__ = "top_questions_analyses"
    __table_args__ = (
        Index("idx_top_questions_analyses_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(32), nullable=False, server_default=text("'pending'"))
    error = Column(Text, nullable=True)
    total_questions = Column(Integer, nullable=False, server_default=text("0"))
    processed_questions = Column(Integer, nullable=False, server_default=text("0"))
    results = Column(JSONB, nullable=True)
    filter_from_date = Column(DateTime(timezone=True), nullable=True)
    filter_to_date = Column(DateTime(timezone=True), nullable=True)
    filter_environment = Column(String(255), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")


class FeedbackThemeAnalysis(Base):
    """Stores results of LLM-based clustering of qualitative feedback comments."""

    __tablename__ = "feedback_theme_analyses"
    __table_args__ = (
        Index("idx_feedback_theme_analyses_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(32), nullable=False, server_default=text("'pending'"))
    error = Column(Text, nullable=True)
    total_comments = Column(Integer, nullable=False, server_default=text("0"))
    processed_comments = Column(Integer, nullable=False, server_default=text("0"))
    results = Column(JSONB, nullable=True)
    filter_from_date = Column(DateTime(timezone=True), nullable=True)
    filter_to_date = Column(DateTime(timezone=True), nullable=True)
    filter_environment = Column(String(255), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")


class FeedbackSuggestionRun(Base):
    """Stores generated test case suggestions from feedback so they survive page reloads."""

    __tablename__ = "feedback_suggestion_runs"
    __table_args__ = (
        Index("idx_feedback_suggestion_runs_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(32), nullable=False, server_default=text("'pending'"))
    error = Column(Text, nullable=True)
    feedback_type = Column(String(16), nullable=False, server_default=text("'all'"))
    filter_from_date = Column(DateTime(timezone=True), nullable=True)
    filter_to_date = Column(DateTime(timezone=True), nullable=True)
    filter_environment = Column(String(255), nullable=True)
    filter_include_user_ids = Column(JSONB, nullable=True)
    filter_exclude_user_ids = Column(JSONB, nullable=True)
    filter_limit = Column(Integer, nullable=False, server_default=text("20"))
    total = Column(Integer, nullable=False, server_default=text("0"))
    processed = Column(Integer, nullable=False, server_default=text("0"))
    suggestions = Column(JSONB, nullable=False, server_default=text("'[]'"))
    count = Column(Integer, nullable=False, server_default=text("0"))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
