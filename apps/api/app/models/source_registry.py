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


class SourceScanRun(Base):
    """A background completeness scan over a provider's source expectations.

    Runs the per-source resolve+chunk analysis (the one the 'Source review' tab
    runs on expand) across every source, resilient to index rate-limiting, so a
    reviewer can flag missing/incomplete sources without opening each one. Owns
    the run lifecycle + progress; the per-source verdicts live in
    :class:`SourceScanResult`. ``scope='dlq'`` re-scans only sources that errored
    on a previous run (mirrors the evaluations dead-letter-queue rerun).
    """

    __tablename__ = "source_scan_runs"
    __table_args__ = (
        Index("idx_source_scan_runs_lookup", "project_id", "provider_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    provider_id = Column(
        UUID(as_uuid=True), ForeignKey("index_providers.id", ondelete="CASCADE"), nullable=False
    )
    scope = Column(String(16), nullable=False, server_default=text("'all'"))  # all | dlq
    status = Column(String(32), nullable=False, server_default=text("'pending'"))
    error = Column(Text, nullable=True)
    total = Column(Integer, nullable=False, server_default=text("0"))  # sources to scan
    processed = Column(Integer, nullable=False, server_default=text("0"))
    failed = Column(Integer, nullable=False, server_default=text("0"))  # errored after retries
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
    provider = relationship("IndexProvider")


class SourceScanResult(Base):
    """The current scan verdict for one source (upserted by each scan run).

    One row per (project, provider, expectation): the latest scan wins. Rows with
    ``execution_status='error'`` are the dead-letter set surfaced for retry. The
    'Source review' tab reads these to label each source without expanding it.
    """

    __tablename__ = "source_scan_results"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "provider_id", "expectation_id", name="uq_source_scan_result"
        ),
        Index(
            "idx_source_scan_results_dlq", "project_id", "provider_id", "execution_status"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    provider_id = Column(
        UUID(as_uuid=True), ForeignKey("index_providers.id", ondelete="CASCADE"), nullable=False
    )
    expectation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_expectations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # How the source was located: url | title | none.
    resolution = Column(String(16), nullable=False, server_default=text("'none'"))
    resolved = Column(Boolean, nullable=False, server_default=text("false"))
    kind = Column(String(32), nullable=True)  # web | page | attachment
    matched_url = Column(String(2048), nullable=True)
    matched_title = Column(String(512), nullable=True)
    chunk_count = Column(Integer, nullable=False, server_default=text("0"))
    # Holes in the chunk-order sequence; 0 when contiguous or unknown.
    missing_chunk_count = Column(Integer, nullable=False, server_default=text("0"))
    ordinal_checked = Column(Boolean, nullable=False, server_default=text("false"))
    # ok = scanned cleanly; error = failed after retries (the dead-letter set).
    execution_status = Column(String(16), nullable=False, server_default=text("'ok'"))
    error = Column(Text, nullable=True)
    scanned_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
    provider = relationship("IndexProvider")
    expectation = relationship("SourceExpectation")
