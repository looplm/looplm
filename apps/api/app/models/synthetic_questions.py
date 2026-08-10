"""Synthetic-question generation run model.

A run samples chunks from one index provider, asks the LLM to write questions each chunk
answers, and (unless it is a preview) persists them as a test dataset whose ground truth is
the source chunk itself. ``SyntheticQuestionRun`` mirrors ``ChunkQualityRun``: a background
job whose status/progress is polled, and whose output survives reloads.
"""

from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base

# How chunks are drawn. ``corpus`` spreads the sample across the whole index; ``partition``
# restricts it to one value of a facetable field. Stored as a plain string so adding a scope
# later (full sweep, per-file) needs no migration.
SCOPE_VALUES = ("corpus", "partition")
DEFAULT_SCOPE = "corpus"

# Question style stored on each generated case. ``factual`` may reuse the chunk's terminology;
# ``paraphrase`` deliberately avoids it (so keyword search isn't flattered); ``negative`` is an
# unanswerable question with no gold chunk.
STYLE_VALUES = ("factual", "paraphrase", "negative")


class SyntheticQuestionRun(Base):
    """One generation job: sample chunks, draft questions, optionally persist a dataset."""

    __tablename__ = "synthetic_question_runs"
    __table_args__ = (
        Index("idx_synthetic_question_runs_lookup", "project_id", "provider_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    provider_id = Column(
        UUID(as_uuid=True), ForeignKey("index_providers.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(32), nullable=False, server_default=text("'pending'"))
    # Which step the worker is on (sampling | generating | verifying | persisting). Null once
    # the run is terminal.
    stage = Column(String(64), nullable=True)
    error = Column(Text, nullable=True)

    # --- request ---
    scope = Column(String(32), nullable=False, server_default=text("'corpus'"))
    partition_key = Column(String(255), nullable=True)
    partition_value = Column(Text, nullable=True)
    sample_size = Column(Integer, nullable=False, server_default=text("0"))  # chunks requested
    questions_per_chunk = Column(Integer, nullable=False, server_default=text("2"))
    # Fraction of the run spent on unanswerable questions, 0..1.
    negative_share = Column(Integer, nullable=False, server_default=text("0"))  # percent
    verify_negatives = Column(Boolean, nullable=False, server_default=text("true"))
    # False = preview: generate and report, persist nothing.
    persist = Column(Boolean, nullable=False, server_default=text("true"))
    # Target dataset. ``dataset_id`` set on the request appends to an existing dataset; otherwise
    # the worker creates one named ``dataset_name`` and writes its id back here.
    dataset_id = Column(UUID(as_uuid=True), nullable=True)
    dataset_name = Column(String(255), nullable=True)

    # --- progress ---
    total = Column(Integer, nullable=False, server_default=text("0"))  # chunks to process
    processed = Column(Integer, nullable=False, server_default=text("0"))

    # {questions: [...], counts: {...}, skipped: {...}} — see schemas.synthetic_questions.
    results = Column(JSONB, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
    provider = relationship("IndexProvider")
