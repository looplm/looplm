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
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base

# Risk slices for a test case. Aggregate metrics are reported per slice because a relevant
# chunk missed at deep rank only matters on the safety/adversarial slices; ``broad`` is the
# default when unset. Safety/adversarial pools are judged deeper (see chunk_pool).
SLICE_VALUES = ("broad", "safety", "adversarial")
DEFAULT_SLICE = "broad"

# Graded relevance scale (TREC-style): 0 irrelevant, 1 marginally relevant, 2 relevant,
# 3 highly relevant. nDCG uses the grade directly as gain; the set-based metrics
# (recall/precision/hit/bpref) and Cohen's kappa binarize at ``RELEVANT_GRADE`` — any
# grade >= 1 is "relevant".
GRADE_MIN = 0
GRADE_MAX = 3
RELEVANT_GRADE = 1
GRADE_LABELS = {0: "Irrelevant", 1: "Marginally relevant", 2: "Relevant", 3: "Highly relevant"}

# Display name (and stored ``annotator`` value) of the built-in LLM annotator. A label whose
# ``annotator`` is set is a non-human judgment: it is a distinct annotator in inter-annotator
# agreement (so a single human + the AI judge already yields Cohen's kappa), but it is excluded
# from the gold resolution that feeds the retrieval metrics — the human labels stay the ground
# truth, the AI judge is a second opinion.
AI_ANNOTATOR = "AI"


def is_valid_grade(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and GRADE_MIN <= value <= GRADE_MAX


class ChunkRelevanceLabel(Base):
    """One human relevance judgment: is this chunk relevant for this test case's query."""

    __tablename__ = "chunk_relevance_labels"
    __table_args__ = (
        # One judgment per (chunk, annotator) so multiple annotators can disagree on the same
        # chunk — the rows needed for inter-annotator agreement (Cohen's kappa) and gold
        # resolution. (project, test_id, chunk_id) alone is no longer unique.
        UniqueConstraint(
            "project_id",
            "test_id",
            "chunk_id",
            "labeled_by",
            name="uq_chunk_label_project_test_chunk_user",
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
    # Graded relevance 0..3 (see GRADE_LABELS). 0 = irrelevant, 3 = highly relevant.
    relevance = Column(Integer, nullable=False)

    # Snapshots so the chunk stays readable in the UI without re-running the eval.
    content_preview = Column(Text, nullable=True)
    url = Column(Text, nullable=True)
    title = Column(Text, nullable=True)

    # Non-human annotator identity (e.g. ``AI``); NULL for human labels, where the annotator is
    # ``labeled_by``. A non-NULL annotator means ``labeled_by`` is NULL — the judgment isn't a
    # user's. The agreement panel treats this as a distinct annotator.
    annotator = Column(String(64), nullable=True)

    labeled_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=text("now()")
    )


class ChunkGoldLabel(Base):
    """An adjudicated 'gold' relevance verdict for a chunk, resolving annotator disagreement.

    When present it overrides the majority vote in gold resolution, so an expert can settle a
    tie or correct a wrong majority. One per (project, test_id, chunk_id).
    """

    __tablename__ = "chunk_gold_labels"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "test_id", "chunk_id", name="uq_chunk_gold_project_test_chunk"
        ),
        Index("idx_chunk_gold_project_test", "project_id", "test_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_id = Column(String(512), nullable=False)
    chunk_id = Column(String(512), nullable=False)
    # Adjudicated graded relevance 0..3, overriding the annotator consensus.
    relevance = Column(Integer, nullable=False)
    decided_by = Column(
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
    # Risk slice (broad | safety | adversarial); null = unset, treated as broad. See SLICE_VALUES.
    slice = Column(String(32), nullable=True)
    marked_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=text("now()")
    )
