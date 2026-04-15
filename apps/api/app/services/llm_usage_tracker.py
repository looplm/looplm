"""Helper to persist LLM usage records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_usage import LlmUsageRecord
from app.services.analysis_llm import LlmUsageInfo


async def record_llm_usage(
    db: AsyncSession,
    *,
    project_id: UUID,
    service_name: str,
    function_name: str,
    provider: str,
    model: str,
    usage: LlmUsageInfo,
    request_metadata: dict | None = None,
) -> None:
    """Add an LLM usage record to the session. Caller is responsible for commit."""
    db.add(
        LlmUsageRecord(
            project_id=project_id,
            service_name=service_name,
            function_name=function_name,
            provider=provider,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=usage.cost_usd,
            cached_tokens=usage.cached_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            duration_ms=usage.duration_ms,
            request_metadata=request_metadata or {},
        )
    )
