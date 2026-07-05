"""Index-provider connection + coverage-run models.

``IndexProvider`` mirrors ``Integration`` (a per-project, credentialed
connection — but to a corpus backend rather than a trace platform).
``CoverageRun`` mirrors ``FeedbackSuggestionRun`` (a background job whose
status, results and LLM-drafted suggestions are persisted so they survive
reloads and can be polled).
"""

from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, IndexProviderType


class IndexProvider(Base):
    """A read-only connection to a retrieval index (Azure AI Search, …)."""

    __tablename__ = "index_providers"
    __table_args__ = (
        Index("idx_index_providers_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type = Column(Enum(IndexProviderType, name="index_provider_type"), nullable=False)
    name = Column(String(255), nullable=False)
    # Backend-specific settings (e.g. {"index_name": "prod-index"} for Azure).
    config = Column(JSONB, nullable=False, server_default=text("'{}'"))
    api_key = Column(LargeBinary, nullable=False)  # encrypted at app layer
    base_url = Column(String(2048))  # endpoint URL
    # Cached LLM-suggested grouping hierarchy + metadata hints (IndexGroupingSuggestion);
    # null until the grouping advisor has run for this provider.
    grouping_suggestion = Column(JSONB, nullable=True)
    grouping_suggested_at = Column(DateTime(timezone=True), nullable=True)
    # Cached LLM field documentation (IndexFieldDocs): per-field purpose + groups
    # of confusable fields with their distinctions. Null until generated.
    field_docs = Column(JSONB, nullable=True)
    field_docs_generated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
    coverage_runs = relationship(
        "CoverageRun", back_populates="provider", cascade="all, delete-orphan"
    )


class CoverageRun(Base):
    """A coverage-analysis job over one partition key, with optional suggestions."""

    __tablename__ = "coverage_runs"
    __table_args__ = (
        Index("idx_coverage_runs_project_id", "project_id"),
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
    partition_key = Column(String(255), nullable=False)
    dataset_ids = Column(JSONB, nullable=True)  # null = all datasets in project
    suggest = Column(String(8), nullable=False, server_default=text("'false'"))
    min_covering_cases = Column(Integer, nullable=False, server_default=text("1"))
    total = Column(Integer, nullable=False, server_default=text("0"))  # partition values
    processed = Column(Integer, nullable=False, server_default=text("0"))  # gaps processed
    results = Column(JSONB, nullable=True)  # CoverageReport.to_dict()
    suggestions = Column(JSONB, nullable=False, server_default=text("'[]'"))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
    provider = relationship("IndexProvider", back_populates="coverage_runs")


class PartitionAcknowledgement(Base):
    """User memory: a partition value flagged as a quality issue is actually
    intentional. Mutes the flag on future runs; carries an optional note."""

    __tablename__ = "partition_acknowledgements"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "provider_id",
            "partition_key",
            "partition_value",
            name="uq_partition_ack",
        ),
        Index("idx_partition_acks_lookup", "project_id", "provider_id", "partition_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    provider_id = Column(
        UUID(as_uuid=True), ForeignKey("index_providers.id", ondelete="CASCADE"), nullable=False
    )
    partition_key = Column(String(255), nullable=False)
    partition_value = Column(Text, nullable=False)
    note = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
