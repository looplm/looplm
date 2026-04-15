"""Analysis service — analyzes traces for failures and root causes."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import Analysis, FixSuggestion, FixType, Trace

logger = logging.getLogger(__name__)


async def analyze_trace(trace_id: UUID, db: AsyncSession, analysis_id: UUID | None = None) -> Analysis:
    """Analyze a trace: detect failure type, root cause, and generate fix suggestions."""
    result = await db.execute(
        select(Trace).where(Trace.id == trace_id).options(selectinload(Trace.spans))
    )
    trace = result.scalar_one_or_none()
    if not trace:
        raise ValueError(f"Trace {trace_id} not found")

    if analysis_id:
        analysis = await db.get(Analysis, analysis_id)
        if not analysis:
            raise ValueError(f"Analysis {analysis_id} not found")
        if analysis.trace_id != trace_id:
            raise ValueError("Analysis trace_id does not match requested trace")
        await db.execute(delete(FixSuggestion).where(FixSuggestion.analysis_id == analysis.id))
    else:
        analysis = Analysis(trace_id=trace_id)
        db.add(analysis)
        await db.flush()
        await db.refresh(analysis)

    # Heuristic failure detection
    failure_type = _detect_failure_type(trace)
    root_cause = _identify_root_cause(trace, failure_type)
    confidence = _compute_confidence(trace, failure_type)

    analysis.failure_type = failure_type
    analysis.root_cause = root_cause
    analysis.confidence = confidence

    # Generate fix suggestions
    suggestions = _generate_fix_suggestions(trace, failure_type, root_cause)
    for s in suggestions:
        fix = FixSuggestion(
            analysis_id=analysis.id,
            type=s["type"],
            title=s["title"],
            description=s["description"],
            diff=s.get("diff"),
        )
        db.add(fix)

    await db.commit()
    logger.info("Analysis complete for trace %s: %s (confidence=%.2f)", trace_id, failure_type, confidence)
    return analysis


def _detect_failure_type(trace: Trace) -> str | None:
    """Detect the primary failure type from spans."""
    if not trace.spans:
        return None

    for span in trace.spans:
        if span.status == "error":
            if span.type and span.type.value == "tool":
                return "tool_failure"
            if span.type and span.type.value == "retriever":
                return "retrieval_failure"
            if span.type and span.type.value == "llm":
                return "prompt_failure"

    if trace.error_message:
        msg = trace.error_message.lower()
        if "timeout" in msg:
            return "tool_failure"
        if "context" in msg or "token" in msg:
            return "context_overflow"
        return "prompt_failure"

    return None


def _identify_root_cause(trace: Trace, failure_type: str | None) -> str | None:
    """Generate a human-readable root cause description."""
    if not failure_type:
        return None

    error_spans = [s for s in trace.spans if s.status == "error"]
    if not error_spans:
        return f"Trace failed with type '{failure_type}' but no error spans were found."

    span = error_spans[0]
    parts = [f"The '{span.name or 'unknown'}' span ({span.type.value if span.type else 'unknown'} type) failed"]
    if span.error_message:
        parts.append(f"with error: {span.error_message}")
    if span.duration_ms:
        parts.append(f"after {span.duration_ms}ms")

    return ". ".join(parts) + "."


def _compute_confidence(trace: Trace, failure_type: str | None) -> float:
    """Compute confidence score for the analysis."""
    if not failure_type:
        return 0.0

    score = 0.5
    error_spans = [s for s in trace.spans if s.status == "error"]
    if error_spans:
        score += 0.2
    if trace.error_message:
        score += 0.15
    if len(error_spans) == 1:
        score += 0.1  # Single clear failure point

    return min(score, 1.0)


def _generate_fix_suggestions(trace: Trace, failure_type: str | None, root_cause: str | None) -> list[dict]:
    """Generate fix suggestions based on failure analysis."""
    if not failure_type:
        return []

    suggestions = []

    if failure_type == "tool_failure":
        error_spans = [s for s in trace.spans if s.status == "error" and s.type and s.type.value == "tool"]
        for span in error_spans[:1]:
            if span.error_message and "timeout" in span.error_message.lower():
                suggestions.append({
                    "type": FixType.tool_config,
                    "title": f"Increase timeout for {span.name or 'tool'}",
                    "description": f"The {span.name or 'tool'} timed out after {span.duration_ms or '?'}ms. Consider increasing the timeout threshold.",
                    "diff": {"path": f"tools.{span.name}.timeout_ms", "before": span.duration_ms, "after": (span.duration_ms or 2000) * 2},
                })
            else:
                suggestions.append({
                    "type": FixType.tool_config,
                    "title": f"Add error handling for {span.name or 'tool'}",
                    "description": f"The {span.name or 'tool'} failed with: {span.error_message or 'unknown error'}. Add retry logic or fallback behavior.",
                })

        suggestions.append({
            "type": FixType.prompt_rewrite,
            "title": "Add fallback instruction for tool failures",
            "description": "Instruct the agent to inform the user and retry rather than failing silently.",
            "diff": {"path": "system_prompt", "added_lines": ["If a tool call fails or times out, inform the user and offer to retry."]},
        })

    elif failure_type == "retrieval_failure":
        suggestions.append({
            "type": FixType.knowledge_gap,
            "title": "Review retrieval configuration",
            "description": "Retrieval steps returned irrelevant or empty results. Review chunk size, overlap, and embedding model settings.",
        })

    elif failure_type == "prompt_failure":
        suggestions.append({
            "type": FixType.prompt_rewrite,
            "title": "Refine system prompt",
            "description": "The LLM produced an unexpected output. Review the system prompt for ambiguity or missing constraints.",
        })

    elif failure_type == "context_overflow":
        suggestions.append({
            "type": FixType.parameter_change,
            "title": "Reduce context size or upgrade model",
            "description": "The trace failed due to context window limits. Consider summarizing context or using a model with a larger context window.",
        })

    return suggestions
