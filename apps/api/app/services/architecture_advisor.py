"""Architecture advisor service — LLM-based architecture suggestions."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AdvisorAnalysis
from app.schemas.advisor import (
    AdvisorResponse,
    ImpactLevel,
    Suggestion,
    SuggestionCategory,
)
from app.services.route_analysis import get_route_analysis

logger = logging.getLogger(__name__)


def _build_prompt(route_data: dict) -> str:
    return f"""You are an expert LLM application architect. Analyze the following execution graph data
from an LLM application and suggest concrete improvements.

Execution Graph Data:
{json.dumps(route_data, indent=2, default=str)}

Provide suggestions in these categories:
1. time_to_value — latency reduction, caching, parallelization
2. output_quality — prompt improvements, loop reduction
3. architecture — node consolidation, better routing, error handling

For each suggestion, provide:
- title: short descriptive title
- description: detailed explanation
- category: one of time_to_value, output_quality, architecture
- impact: high, medium, or low
- confidence: 0.0 to 1.0
- reasoning: your detailed reasoning

Respond with a JSON array of suggestion objects. Only valid JSON, no markdown."""


def _parse_suggestions(raw: str) -> list[Suggestion]:
    """Parse LLM response into Suggestion objects."""
    try:
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

        items = json.loads(text)
        suggestions = []
        for item in items:
            try:
                suggestions.append(
                    Suggestion(
                        title=item.get("title", "Untitled"),
                        description=item.get("description", ""),
                        category=SuggestionCategory(item.get("category", "architecture")),
                        impact=ImpactLevel(item.get("impact", "medium")),
                        confidence=float(item.get("confidence", 0.5)),
                        reasoning=item.get("reasoning", ""),
                    )
                )
            except (ValueError, KeyError) as e:
                logger.warning("Skipping malformed suggestion: %s", e)
        return suggestions
    except json.JSONDecodeError:
        logger.error("Failed to parse LLM response as JSON")
        return []


async def analyze_architecture(
    integration_id: UUID,
    project_id: UUID,
    db: AsyncSession,
    extra_context: str = "",
    user_settings: dict | None = None,
) -> AdvisorResponse:
    """Run LLM-based architecture analysis."""
    from app.services.analysis_llm import AnalysisLlmService

    route_data = await get_route_analysis(integration_id, project_id, db)
    route_dict = route_data.model_dump()

    llm = AnalysisLlmService(user_settings=user_settings)
    prompt = _build_prompt(route_dict)
    if extra_context:
        prompt += f"\n\nAdditional context: {extra_context}"

    from app.services.llm_usage_tracker import record_llm_usage

    raw_text, usage = await llm.tracked_chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a senior LLM application architect. "
                    "Analyze execution patterns and suggest improvements. "
                    "Always respond with valid JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )

    await record_llm_usage(
        db,
        project_id=project_id,
        service_name="architecture_advisor",
        function_name="analyze_architecture",
        provider=llm.provider,
        model=llm.model,
        usage=usage,
        request_metadata={"integration_id": str(integration_id)},
    )
    suggestions = _parse_suggestions(raw_text)
    analyzed_at = datetime.now(timezone.utc)

    result = AdvisorResponse(
        integration_id=str(integration_id),
        suggestions=suggestions,
        analyzed_at=analyzed_at,
    )

    # Persist to database
    row = AdvisorAnalysis(
        integration_id=integration_id,
        suggestions=[s.model_dump() for s in suggestions],
        analyzed_at=analyzed_at,
    )
    db.add(row)
    await db.commit()

    return result


async def get_latest_suggestions(
    integration_id: UUID,
    db: AsyncSession,
) -> AdvisorResponse | None:
    """Return the most recent advisor analysis for an integration."""
    stmt = (
        select(AdvisorAnalysis)
        .where(AdvisorAnalysis.integration_id == integration_id)
        .order_by(AdvisorAnalysis.analyzed_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None

    suggestions = [
        Suggestion(**item) for item in (row.suggestions or [])
    ]
    return AdvisorResponse(
        integration_id=str(integration_id),
        suggestions=suggestions,
        analyzed_at=row.analyzed_at,
    )
