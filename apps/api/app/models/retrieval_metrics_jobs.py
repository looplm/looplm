"""Background compute jobs for labels-path retrieval metrics.

The live retrieval-metrics computation (probe the connected index per case + embed queries) can take
tens of seconds for the overall view and minutes for the by-stage view. Running it inline as one
blocking request means a server reload, crash, or proxy timeout resets the socket mid-flight and the
client sees a phantom 500. Instead the panel starts a job here, the compute runs detached (writing
its result into the Redis metrics cache), and the panel polls this row for status. On failure the
job stores the exception message and traceback so the UI can show — and copy — the real error.

Mirrors the ``EvalJob`` pattern (in-process ``asyncio`` task + a status row); a hard restart orphans
the task, so ``main.py``'s lifespan reconciles any still-``running`` rows to ``failed``.
"""

from uuid import uuid4

from sqlalchemy import (
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


class RetrievalMetricsJob(Base):
    """A detached compute of labels-path retrieval metrics for one settings snapshot."""

    __tablename__ = "retrieval_metrics_jobs"
    __table_args__ = (
        Index("idx_retrieval_metrics_jobs_project_created", "project_id", "started_at"),
        Index("idx_retrieval_metrics_jobs_status", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # What is being computed — the same tuple that keys the Redis result cache.
    view = Column(String(16), nullable=False, server_default=text("'overall'"))  # overall | byStage
    gold_source = Column(String(16), nullable=False, server_default=text("'human'"))
    dataset_ids = Column(JSONB, nullable=False, server_default=text("'[]'"))  # list[str]

    # pending | running | completed | failed
    status = Column(String(16), nullable=False, server_default=text("'pending'"))
    error = Column(Text, nullable=True)
    trace = Column(Text, nullable=True)
    progress_current = Column(Integer, nullable=True)
    progress_total = Column(Integer, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project")
