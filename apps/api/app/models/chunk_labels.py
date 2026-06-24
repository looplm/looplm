"""Human relevance labels on retrieved chunks, for chunk-level retrieval evaluation.

A label is keyed by (project, test case, chunk) and reused across eval runs: once a human
judges chunk X relevant for query Q, every run that retrieves X for Q inherits that
judgment. The pooled set of relevant chunks per test case is the ground truth the
retrieval metrics (precision/recall/MRR/nDCG) are computed against.
"""

from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base


class ChunkRelevanceLabel(Base):
    """One human relevance judgment: is this chunk relevant for this test case's query."""

    __tablename__ = "chunk_relevance_labels"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "test_id", "chunk_id", name="uq_chunk_label_project_test_chunk"
        ),
        Index("idx_chunk_labels_project_test", "project_id", "test_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The eval test case identity (EvalResult.test_id) — the query being judged.
    test_id = Column(String(512), nullable=False)
    # Azure AI Search document key of the chunk.
    chunk_id = Column(String(512), nullable=False)
    relevant = Column(Boolean, nullable=False)

    # Snapshots so the chunk stays readable in the UI without re-running the eval.
    content_preview = Column(Text, nullable=True)
    url = Column(Text, nullable=True)
    title = Column(Text, nullable=True)

    labeled_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=text("now()")
    )


class TestCaseLabelingStatus(Base):
    """Manual 'labeling complete' flag for a test case's chunk judgments.

    Completeness is an explicit human decision, not derived from whether every chunk has a
    label, so a reviewer can declare a case done even when some chunks are intentionally
    left unlabeled. Keyed by (project, test_id), independent of any run.
    """

    __tablename__ = "test_case_labeling_status"
    __table_args__ = (
        UniqueConstraint("project_id", "test_id", name="uq_labeling_status_project_test"),
        Index("idx_labeling_status_project", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    test_id = Column(String(512), nullable=False)
    complete = Column(Boolean, nullable=False, server_default=text("false"))
    marked_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=text("now()")
    )
