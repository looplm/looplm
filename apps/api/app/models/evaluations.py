"""EvalJob, EvalRun, EvalResult, and Evaluator models with related enums."""

import enum
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
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


class EvalJobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    batch_pending = "batch_pending"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class EvaluatorType(str, enum.Enum):
    llm_judge = "llm_judge"
    deterministic = "deterministic"
    hybrid = "hybrid"


class EvalJob(Base):
    __tablename__ = "eval_jobs"
    __table_args__ = (
        Index("idx_eval_jobs_project_id", "project_id"),
        Index("idx_eval_jobs_status", "status"),
        Index("idx_eval_jobs_started_at", text("started_at DESC")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    test_suite = Column(String(255), nullable=False, server_default=text("''"))
    dataset_ids = Column(JSONB, nullable=True)
    status = Column(
        Enum(EvalJobStatus, name="eval_job_status"), nullable=False, server_default=text("'pending'")
    )
    run_id = Column(UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="SET NULL"), nullable=True)
    error = Column(Text, nullable=True)
    log = Column(Text, nullable=True)
    config = Column(JSONB, nullable=False, server_default=text("'{}'"))
    progress_current = Column(Integer, nullable=True)
    progress_total = Column(Integer, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    batch_eval_job_id = Column(
        UUID(as_uuid=True), ForeignKey("batch_eval_jobs.id", ondelete="SET NULL"), nullable=True
    )

    project = relationship("Project")
    run = relationship("EvalRun")
    batch_eval_job = relationship("BatchEvalJob", foreign_keys=[batch_eval_job_id])


class BatchEvalJob(Base):
    """Tracks an Azure OpenAI Batch API job for LLM-judge evaluators."""

    __tablename__ = "batch_eval_jobs"
    __table_args__ = (
        Index("idx_batch_eval_jobs_status", "status"),
        Index("idx_batch_eval_jobs_eval_job_id", "eval_job_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    eval_job_id = Column(
        UUID(as_uuid=True), ForeignKey("eval_jobs.id", ondelete="CASCADE"), nullable=False
    )
    run_id = Column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    batch_id = Column(String(255), nullable=True)
    input_file_id = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, server_default=text("'preparing'"))
    total_requests = Column(Integer, nullable=False, server_default=text("0"))
    completed_requests = Column(Integer, nullable=False, server_default=text("0"))
    failed_requests = Column(Integer, nullable=False, server_default=text("0"))
    request_mapping = Column(JSONB, nullable=False, server_default=text("'{}'"))
    error = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    eval_job = relationship("EvalJob", foreign_keys=[eval_job_id])
    run = relationship("EvalRun")
    project = relationship("Project")


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        Index("idx_eval_runs_project_id", "project_id"),
        Index("idx_eval_runs_created_at", text("created_at DESC")),
        Index("idx_eval_runs_session_id", "session_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(512), nullable=False)
    source = Column(String(256))
    tags = Column(JSONB, nullable=False, server_default=text("'[]'"))
    total = Column(Integer, nullable=False, server_default=text("0"))
    passed = Column(Integer, nullable=False, server_default=text("0"))
    failed = Column(Integer, nullable=False, server_default=text("0"))
    grader_summary = Column(JSONB, nullable=False, server_default=text("'{}'"))
    score_summary = Column(JSONB, nullable=False, server_default=text("'{}'"))
    session_id = Column(
        UUID(as_uuid=True), ForeignKey("eval_sessions.id", ondelete="SET NULL"), nullable=True
    )
    experiment_id = Column(
        UUID(as_uuid=True), ForeignKey("experiments.id", ondelete="SET NULL"), nullable=True
    )
    run_metadata = Column("metadata", JSONB, nullable=False, server_default=text("'{}'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
    session = relationship("EvalSession", back_populates="runs")
    experiment = relationship("Experiment")
    results = relationship("EvalResult", back_populates="run", cascade="all, delete-orphan")


class EvalResult(Base):
    __tablename__ = "eval_results"
    __table_args__ = (
        Index("idx_eval_results_run_id", "run_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id = Column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    test_id = Column(String(512), nullable=False)
    pass_ = Column("pass", Boolean, nullable=False)
    reason = Column(Text)
    input = Column(Text)
    output = Column(Text)
    expected_output = Column(Text)
    tags = Column(JSONB, nullable=False, server_default=text("'[]'"))
    graders = Column(JSONB, nullable=False, server_default=text("'{}'"))
    scores = Column(JSONB, nullable=False, server_default=text("'{}'"))
    turns_to_pass = Column(Integer, nullable=True)
    result_metadata = Column("metadata", JSONB, nullable=False, server_default=text("'{}'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    run = relationship("EvalRun", back_populates="results")


class EvalReport(Base):
    __tablename__ = "eval_reports"
    __table_args__ = (
        Index("idx_eval_reports_project_id", "project_id"),
        Index("idx_eval_reports_created_at", text("created_at DESC")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title = Column(String(512), nullable=False)
    report_type = Column(String(32), nullable=False, server_default=text("'multi_run'"))
    markdown = Column(Text, nullable=False)
    run_ids = Column(JSONB, nullable=False, server_default=text("'[]'"))
    run_count = Column(Integer, nullable=False, server_default=text("0"))
    total_tests = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint("project_id", "name"),
        Index("idx_experiments_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    variables = Column(JSONB, nullable=False, server_default=text("'{}'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")


class EvalSession(Base):
    __tablename__ = "eval_sessions"
    __table_args__ = (
        Index("idx_eval_sessions_project_id", "project_id"),
        Index("idx_eval_sessions_started_at", text("started_at DESC")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(512), nullable=False)
    status = Column(
        Enum(EvalJobStatus, name="eval_job_status", create_type=False),
        nullable=False,
        server_default=text("'pending'"),
    )
    dataset_ids = Column(JSONB, nullable=True)
    experiment_ids = Column(JSONB, nullable=False, server_default=text("'[]'"))
    config = Column(JSONB, nullable=False, server_default=text("'{}'"))
    progress_current = Column(Integer, nullable=True)
    progress_total = Column(Integer, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project")
    runs = relationship("EvalRun", back_populates="session")


class Evaluator(Base):
    __tablename__ = "evaluators"
    __table_args__ = (
        UniqueConstraint("project_id", "name"),
        Index("idx_evaluators_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    display_name = Column(String(255))
    type = Column(Enum(EvaluatorType, name="evaluator_type"), nullable=False)
    description = Column(Text)
    relevance = Column(String(32), nullable=False, server_default=text("'important'"))
    affects_pass = Column(Boolean, nullable=False, server_default=text("false"))
    config = Column(JSONB, nullable=False, server_default=text("'{}'"))
    source = Column(String(128))
    # Which side of the RAG pipeline this evaluator assesses: "retrieval" (did we fetch the right
    # context) or "generation" (did the model use it well). Drives the Retrieval/Generation split
    # in the evaluators UI.
    category = Column(String(32), nullable=False, server_default=text("'generation'"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
