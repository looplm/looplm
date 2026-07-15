"""Passage-offset backfill run model.

A background job that anchors NULL-offset passage selections to document coordinates once their
chunk's index doc carries ``chunk_char_start`` (see
:mod:`app.services.passage_offset_backfill`). One row per launch, driven pending → running →
completed/failed, so the labeling UI can trigger it and poll the per-outcome tallies. Mirrors
:class:`ChunkQualityRun`'s lifecycle but simpler — the work is fast and needs no sampling or cancel.
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class PassageOffsetBackfillRun(Base):
    """One launch of the passage document-offset backfill over a project's labels."""

    __tablename__ = "passage_offset_backfill_runs"
    __table_args__ = (Index("idx_passage_offset_backfill_project", "project_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(32), nullable=False, server_default=text("'pending'"))

    # Progress: chunks fetched/re-split so far, out of the total distinct chunks with null-offset
    # rows. Rows share chunks, so chunk counts (not row counts) drive the bar.
    total_chunks = Column(Integer, nullable=False, server_default=text("0"))
    processed_chunks = Column(Integer, nullable=False, server_default=text("0"))

    # Per-outcome tallies (rows), mirroring BackfillOutcome so the UI can explain every skip.
    anchored = Column(Integer, nullable=False, server_default=text("0"))
    no_offset = Column(Integer, nullable=False, server_default=text("0"))
    chunk_missing = Column(Integer, nullable=False, server_default=text("0"))
    no_split_match = Column(Integer, nullable=False, server_default=text("0"))
    drifted = Column(Integer, nullable=False, server_default=text("0"))

    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
