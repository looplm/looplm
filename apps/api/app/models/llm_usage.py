"""LLM usage tracking model."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.base import Base


class LlmUsageRecord(Base):
    __tablename__ = "llm_usage_records"
    __table_args__ = (
        Index("idx_llm_usage_project_id", "project_id"),
        Index("idx_llm_usage_created_at", text("created_at DESC")),
        Index("idx_llm_usage_service_name", "service_name"),
        Index("idx_llm_usage_project_service", "project_id", "service_name"),
        Index("idx_llm_usage_project_created", "project_id", text("created_at DESC")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), nullable=False)
    service_name = Column(String(128), nullable=False)
    function_name = Column(String(128), nullable=False)
    provider = Column(String(32), nullable=False)
    model = Column(String(128), nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    total_tokens = Column(Integer, nullable=False)
    cost_usd = Column(Float, nullable=True)
    cached_tokens = Column(Integer, nullable=False, server_default=text("0"))
    reasoning_tokens = Column(Integer, nullable=False, server_default=text("0"))
    request_metadata = Column(JSONB, nullable=False, server_default=text("'{}'"))
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
