"""Chunk/metadata quality run model.

``ChunkQualityRun`` mirrors ``SourceGapRun``: a background job that samples a
provider's index and persists a quality report (size/consistency, duplication/
overlap, metadata completeness, content/parser checks) so results survive
reloads and can be polled while running.
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


class ChunkQualityRun(Base):
    """A sampled chunk/metadata quality analysis over one index provider."""

    __tablename__ = "chunk_quality_runs"
    __table_args__ = (
        Index("idx_chunk_quality_runs_lookup", "project_id", "provider_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    provider_id = Column(
        UUID(as_uuid=True), ForeignKey("index_providers.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(32), nullable=False, server_default=text("'pending'"))
    # Which step the worker is on while running (sampling | analyzing | one of
    # the extended pass names). Null once the run is terminal.
    stage = Column(String(64), nullable=True)
    error = Column(Text, nullable=True)
    sample_size = Column(Integer, nullable=False, server_default=text("0"))  # requested sample
    # Which extended passes ran and with what caps — see
    # schemas.chunk_quality.ChunkQualityRunConfig. Null = base families only.
    config = Column(JSONB, nullable=True)
    total_docs = Column(Integer, nullable=False, server_default=text("0"))
    processed = Column(Integer, nullable=False, server_default=text("0"))  # docs analysed so far
    # {summary: {...}, score, fields, families: {...}, findings: [...]} — see
    # index_providers.chunk_quality.ChunkQualityReport.to_dict().
    results = Column(JSONB, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
    provider = relationship("IndexProvider")
