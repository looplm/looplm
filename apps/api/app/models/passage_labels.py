"""Per-passage relevance selections — an additive refinement of chunk labeling.

A chunk label (``chunk_relevance_labels``) is the atomic gold signal: is this pooled chunk
relevant for the query. Passage labeling hangs *off* that: within a chunk a labeler judged
relevant, they can additionally mark which finer-grained passages (sentences / list items /
short sections) actually help answer the question — "uncheck passages that don't help". This
yields a sentence-level evidence signal on top of the chunk grade, without disturbing the
chunk-level model, metrics, or gold.

The atomic *chunk* unit is unchanged (see :mod:`app.models.chunk_labels`). A passage selection
is 1-to-many per ``(test_id, chunk_id, annotator)``, so it needs its own table rather than
columns on ``ChunkRelevanceLabel``. Passages are keyed by ``passage_id``:

* ``rde`` source — a stable, offset-anchored sentence sub-passage id from the rde indexer
  (``{passageId}#s{n}``), independent of chunk size/overlap, so a selection survives re-chunking.
* ``chunk_split`` source — a chunk-derived id (``{chunk_id}#s{n}``) from splitting the pooled
  chunk's own text locally, used when no rde-derived passages exist. These orphan on re-chunk.
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base

# Where a passage's identity came from — recorded per row so durability is legible. ``rde`` ids
# survive re-chunking of the index; ``chunk_split`` ids are derived from the pooled chunk's text
# and orphan when the chunk boundaries change.
PASSAGE_SOURCE_RDE = "rde"
PASSAGE_SOURCE_CHUNK_SPLIT = "chunk_split"
PASSAGE_SOURCES = (PASSAGE_SOURCE_RDE, PASSAGE_SOURCE_CHUNK_SPLIT)

# Passage relevance is binary: 1 = this passage helps answer the question, 0 = it does not. Stored
# as an Integer (not Boolean) so a future graded scale (mirroring the 0..3 chunk grade) needs no
# migration — the column already holds it.
PASSAGE_RELEVANT = 1
PASSAGE_NOT_RELEVANT = 0


def is_valid_passage_relevance(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value in (0, 1)


class PassageRelevanceLabel(Base):
    """One annotator's judgment of whether a single passage helps answer a case's query.

    Keyed by ``(project, test_id, chunk_id, passage_id, annotator)`` so multiple annotators can
    disagree at passage grain, mirroring :class:`ChunkRelevanceLabel`. A non-NULL ``annotator``
    (e.g. ``AI``) marks a non-human judgment; human rows carry ``labeled_by`` and NULL annotator.
    """

    __tablename__ = "passage_relevance_labels"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "test_id",
            "chunk_id",
            "passage_id",
            "labeled_by",
            name="uq_passage_label_project_test_chunk_passage_user",
        ),
        Index("idx_passage_labels_project_test_chunk", "project_id", "test_id", "chunk_id"),
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
    # The pooled chunk this passage was labeled under (the chunk stays the primary labeled unit).
    chunk_id = Column(String(512), nullable=False)
    # Passage identity: an rde sentence sub-passage id ({passageId}#s{n}) or a chunk-derived id.
    passage_id = Column(String(512), nullable=False)
    # Binary relevance: 1 = helps answer the question, 0 = does not (see PASSAGE_RELEVANT).
    relevant = Column(Integer, nullable=False)
    # "rde" | "chunk_split" — how the passage id was derived (see PASSAGE_SOURCES).
    passage_source = Column(String(16), nullable=False, server_default=text(f"'{PASSAGE_SOURCE_CHUNK_SPLIT}'"))

    # Snapshots so the passage stays readable in the UI without re-fetching/re-splitting.
    section_path = Column(Text, nullable=True)
    text_preview = Column(Text, nullable=True)

    # Document-anchored offsets: the passage's [char_start, char_end) into the parsed document,
    # derived by anchoring the local split to the chunk's own ``chunk_char_start`` from the index
    # (doc offset = chunk_char_start + offset-within-chunk). These share the parsed-markdown
    # coordinate space, so a selection can be re-matched to a *new* chunking by offset overlap —
    # i.e. it survives re-chunking, unlike the ``{chunk_id}#s{n}`` passage_id. NULL when the chunk
    # carries no offset (legacy-chunker pages, where the index lacks ``chunk_char_start``).
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)

    # Non-human annotator identity (e.g. ``AI``); NULL for human labels, where the annotator is
    # ``labeled_by``. A non-NULL annotator means ``labeled_by`` is NULL.
    annotator = Column(String(64), nullable=True)

    labeled_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=text("now()")
    )
