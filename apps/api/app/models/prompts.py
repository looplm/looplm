"""Prompt and PromptReview models."""

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
from sqlalchemy import Float
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class Prompt(Base):
    __tablename__ = "prompts"
    __table_args__ = (
        UniqueConstraint("integration_id", "external_id", "version"),
        Index("idx_prompts_integration_id", "integration_id"),
        Index("idx_prompts_name", "name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    integration_id = Column(
        UUID(as_uuid=True), ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    external_id = Column(String(512), nullable=False)
    name = Column(String(512), nullable=False)
    template = Column(Text, nullable=False, server_default=text("''"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    variables = Column(JSONB, nullable=False, server_default=text("'[]'"))
    prompt_metadata = Column("metadata", JSONB, nullable=False, server_default=text("'{}'"))
    # Ordered hierarchy this prompt belongs to, e.g. ["Graders", "Conciseness"].
    # Empty = ungrouped. Suggested by the clustering pass, editable by the user.
    cluster_path = Column(JSONB, nullable=False, server_default=text("'[]'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    integration = relationship("Integration")
    reviews = relationship("PromptReview", back_populates="prompt", cascade="all, delete-orphan")


class PromptReview(Base):
    __tablename__ = "prompt_reviews"
    __table_args__ = (
        Index("idx_prompt_reviews_prompt_id", "prompt_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    prompt_id = Column(
        UUID(as_uuid=True), ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False
    )
    anti_patterns = Column(JSONB, nullable=False, server_default=text("'[]'"))
    suggestions = Column(JSONB, nullable=False, server_default=text("'[]'"))
    rewritten_prompt = Column(Text, nullable=False, server_default=text("''"))
    model = Column(String(256), nullable=False, server_default=text("''"))
    reviewed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    prompt = relationship("Prompt", back_populates="reviews")


class PromptExtraction(Base):
    """Background run that extracts prompts from a connected GitHub codebase.

    Mirrors OpenCodeAnalysis: an agentic, long-running task whose live progress
    is polled by the frontend. The extracted prompts themselves land in the
    `prompts` table under the project's `github` integration; this row only
    tracks the run.
    """

    __tablename__ = "prompt_extractions"
    __table_args__ = (
        Index("idx_prompt_extractions_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    integration_id = Column(
        UUID(as_uuid=True), ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True
    )
    status = Column(String(32), nullable=False, server_default=text("'pending'"))
    error = Column(Text, nullable=True)
    files_analyzed = Column(JSONB, nullable=False, server_default=text("'[]'"))
    summary = Column(Text, nullable=True)
    extracted_count = Column(Integer, nullable=False, server_default=text("0"))
    total_cost_usd = Column(Float, nullable=True)
    num_turns = Column(Integer, nullable=True)
    progress_message = Column(String(512), nullable=True)
    progress_log = Column(JSONB, nullable=False, server_default=text("'[]'"))
    # Locations found during discovery, awaiting user selection before extraction.
    planned_locations = Column(JSONB, nullable=False, server_default=text("'[]'"))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
