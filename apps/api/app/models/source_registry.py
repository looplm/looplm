"""Wanted-status source registry + gap-run models.

``SourceExpectation`` is one row of the *wanted status* of an index: a named
source (law, spec, application guide, …) that should be retrievable, with the
URL(s) it lives at and light business metadata. Rows are typically seeded from
a CSV export maintained by product owners.

``SourceGapRun`` mirrors ``CoverageRun``: a background job that compares all
expectations against what is actually in the index and persists per-row
verdicts so they survive reloads and can be polled.
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class SourceExpectation(Base):
    """One wanted source for an index provider (the 'should be indexed' side)."""

    __tablename__ = "source_expectations"
    __table_args__ = (
        UniqueConstraint("project_id", "provider_id", "name", name="uq_source_expectation_name"),
        Index("idx_source_expectations_lookup", "project_id", "provider_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    provider_id = Column(
        UUID(as_uuid=True), ForeignKey("index_providers.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(512), nullable=False)
    # A source may publish the same document as an HTML page and a PDF twin;
    # the expectation is covered when EITHER variant is indexed.
    html_url = Column(String(2048), nullable=True)
    pdf_url = Column(String(2048), nullable=True)
    # Which ingestion group/crawler should produce this source (matches the
    # indexer's chunk `tags` value, e.g. 'gesetze', 'bdew-mako').
    adapter_tag = Column(String(64), nullable=True)
    # Business metadata carried over from the source list (free-form).
    typ = Column(String(255), nullable=True)
    sparte = Column(String(255), nullable=True)
    thema = Column(String(255), nullable=True)
    publisher = Column(String(255), nullable=True)
    hierarchie = Column(String(512), nullable=True)
    update_frequency = Column(String(255), nullable=True)
    comment = Column(Text, nullable=True)
    # Set = "this source is knowingly not indexed"; mutes the gap on future runs.
    ack_note = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
    provider = relationship("IndexProvider")


class SourceGapRun(Base):
    """A wanted-vs-actual gap analysis job over all expectations of a provider."""

    __tablename__ = "source_gap_runs"
    __table_args__ = (
        Index("idx_source_gap_runs_lookup", "project_id", "provider_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    provider_id = Column(
        UUID(as_uuid=True), ForeignKey("index_providers.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(32), nullable=False, server_default=text("'pending'"))
    error = Column(Text, nullable=True)
    total = Column(Integer, nullable=False, server_default=text("0"))  # expectations
    processed = Column(Integer, nullable=False, server_default=text("0"))
    # {summary: {...}, rows: [SourceGapRowResult...]} — see schemas.source_registry.
    results = Column(JSONB, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
    provider = relationship("IndexProvider")
