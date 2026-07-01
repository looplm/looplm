"""Persisted retrieval-quality run snapshots (labels path).

A ``RetrievalRun`` is a durable point-in-time snapshot of the chunk-label retrieval metrics for a
chosen set of datasets and a gold source. It preserves history — so retrieval quality can be
tracked as the RAG pipeline and index evolve — and carries editable metadata (name, pipeline
version, index name + version, notes) so runs can be annotated and compared. The metric blobs are
stored verbatim (``RetrievalRunMetrics`` / ``ByStageMetricsResponse`` dumps) including their own
``ks`` list, so runs computed with different k-sets stay comparable.
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


class RetrievalRun(Base):
    """A saved snapshot of labels-path retrieval metrics with annotatable metadata."""

    __tablename__ = "retrieval_runs"
    __table_args__ = (
        Index("idx_retrieval_runs_project_created", "project_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Settings snapshot — what was measured.
    gold_source = Column(String(16), nullable=False, server_default=text("'human'"))
    dataset_ids = Column(JSONB, nullable=False, server_default=text("'[]'"))  # list[str]
    # Dataset names captured at save time, so history stays readable if a dataset is renamed/deleted.
    dataset_names = Column(JSONB, nullable=False, server_default=text("'[]'"))  # list[str]
    ks = Column(JSONB, nullable=False, server_default=text("'[]'"))  # list[int]

    # Results — verbatim schema dumps.
    metrics = Column(JSONB, nullable=False)  # RetrievalRunMetrics
    by_stage = Column(JSONB, nullable=True)  # ByStageMetricsResponse, when a cached one existed
    total_cases = Column(Integer, nullable=False, server_default=text("0"))
    evaluated_cases = Column(Integer, nullable=False, server_default=text("0"))

    # Editable metadata.
    name = Column(String(255), nullable=True)
    pipeline_version = Column(String(255), nullable=True)
    index_name = Column(String(255), nullable=True)
    index_version = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    project = relationship("Project")
