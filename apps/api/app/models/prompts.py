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
