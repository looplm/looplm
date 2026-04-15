"""Pure helper functions for dataset endpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.models.models import FeedbackScore, TestCase, Trace
from app.schemas.datasets import TestCaseItem, TestCaseSuggestion

logger = logging.getLogger(__name__)


def _tc_to_item(tc: TestCase) -> TestCaseItem:
    return TestCaseItem(
        id=tc.id,
        dataset_id=tc.dataset_id,
        test_id=tc.test_id,
        prompt=tc.prompt,
        expected_answer=tc.expected_answer,
        expected_sources=tc.expected_sources or [],
        context_filters=tc.context_filters or {},
        team_filter=tc.team_filter or [],
        tag_filter=tc.tag_filter or [],
        message_count=tc.message_count,
        has_summary=tc.has_summary,
        folder=tc.folder,
        document=tc.document,
        expected_page_urls=tc.expected_page_urls or [],
        expected_source_types=tc.expected_source_types or [],
        follow_up_prompts=tc.follow_up_prompts,
        source_feedback_id=tc.source_feedback_id,
        source_trace_id=tc.source_trace_id,
        tags=tc.tags or [],
        metadata=tc.test_case_metadata or {},
        created_at=tc.created_at,
    )


def _extract_user_prompt(trace_input: Any) -> str | None:
    """Extract last user message from trace input."""
    if not trace_input:
        return None
    # Vercel AI SDK format: { messages: [...] }
    if isinstance(trace_input, dict):
        messages = trace_input.get("messages", [])
        if isinstance(messages, list):
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                return part.get("text", "")
    return None


def build_suggestions(
    rows: list[tuple[FeedbackScore, Trace | None]],
) -> list[TestCaseSuggestion]:
    """Build test case suggestions from feedback+trace rows.

    Deduplicates by prompt and enriches with context metadata.
    """
    suggestions: list[TestCaseSuggestion] = []
    seen_prompts: set[str] = set()

    for feedback, trace in rows:
        if trace is None:
            continue

        # Extract last user message from trace input
        prompt = _extract_user_prompt(trace.input)
        if not prompt:
            continue

        # Deduplicate by prompt
        prompt_key = prompt.strip().lower()[:200]
        if prompt_key in seen_prompts:
            continue
        seen_prompts.add(prompt_key)

        # Extract actual answer from trace output
        actual_answer = _extract_answer(trace.output)

        # Extract context from trace metadata
        metadata = trace.trace_metadata or {}
        context_filters = metadata.get("contextFilters", {})
        if not isinstance(context_filters, dict):
            context_filters = {}
        message_count = metadata.get("messageCount")
        has_summary = (isinstance(message_count, int) and message_count > 8) or bool(metadata.get("hasSummary"))

        # For positive feedback, use actual answer as expected
        suggested = actual_answer if feedback.value == 1 else None

        suggestions.append(TestCaseSuggestion(
            feedback_id=feedback.id,
            trace_id=feedback.trace_id,
            feedback_value=feedback.value,
            prompt=prompt,
            actual_answer=actual_answer,
            suggested_expected_answer=suggested,
            context_filters=context_filters,
            team_filter=metadata.get("teamFilter", []),
            tag_filter=metadata.get("tagFilter", []),
            message_count=message_count,
            has_summary=has_summary,
            scored_at=feedback.scored_at,
        ))

    return suggestions


def _extract_answer(trace_output: Any) -> str | None:
    """Extract assistant answer from trace output."""
    if not trace_output:
        return None
    if isinstance(trace_output, str):
        return trace_output
    if isinstance(trace_output, dict):
        # Common patterns
        if "text" in trace_output:
            return trace_output["text"]
        if "content" in trace_output:
            return trace_output["content"]
        if "output" in trace_output:
            return trace_output["output"]
    return None


async def generate_expected_answer(
    llm_service: Any,
    prompt: str,
    actual_answer: str | None,
    comment: str | None,
    db: Any = None,
    project_id: Any = None,
) -> str | None:
    """Use LLM to generate what the expected answer should have been."""
    parts = [f"User question:\n{prompt}"]
    if actual_answer:
        parts.append(f"Incorrect response that was given:\n{actual_answer[:2000]}")
    if comment:
        parts.append(f"User feedback on why this was wrong:\n{comment}")

    user_content = "\n\n".join(parts)

    try:
        content, usage = await llm_service.tracked_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a QA specialist creating test case expected answers. "
                        "Given a user question and an incorrect response (with optional feedback), "
                        "write a concise, correct expected answer. "
                        "Focus on what the correct answer should contain. "
                        "Write only the expected answer, no meta-commentary."
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
        )

        if db and project_id:
            from app.services.llm_usage_tracker import record_llm_usage
            await record_llm_usage(
                db,
                project_id=project_id,
                service_name="dataset_helpers",
                function_name="generate_expected_answer",
                provider=llm_service.provider,
                model=llm_service.model,
                usage=usage,
            )

        return content or None
    except Exception:
        logger.exception("Failed to generate expected answer via LLM")
        return None


async def enrich_suggestions_with_llm(
    suggestions: list[TestCaseSuggestion],
    llm_service: Any,
    feedback_comments: dict[str, str | None],
) -> list[TestCaseSuggestion]:
    """Enrich negative-feedback suggestions with LLM-generated expected answers."""

    async def _enrich(sug: TestCaseSuggestion) -> TestCaseSuggestion:
        if sug.feedback_value == 1 or sug.suggested_expected_answer:
            return sug
        answer = await generate_expected_answer(
            llm_service,
            sug.prompt,
            sug.actual_answer,
            feedback_comments.get(str(sug.feedback_id)),
        )
        if answer:
            sug.suggested_expected_answer = answer
        return sug

    return list(await asyncio.gather(*[_enrich(s) for s in suggestions]))


def score_dataset_relevance(
    dataset_cases: list[dict[str, Any]],
    trace_team_filter: list[str],
    trace_tag_filter: list[str],
    trace_context_filters: dict[str, str],
) -> float:
    """Score how relevant a dataset is for a given trace's metadata.

    Returns a relevance score (higher = more relevant).
    """
    if not dataset_cases:
        return 0.0

    score = 0.0
    trace_teams = set(t.lower() for t in trace_team_filter)
    trace_tags = set(t.lower() for t in trace_tag_filter)

    for tc in dataset_cases:
        tc_teams = set(t.lower() for t in (tc.get("team_filter") or []))
        tc_tags = set(t.lower() for t in (tc.get("tag_filter") or []))
        tc_ctx = tc.get("context_filters") or {}

        # Team overlap
        if trace_teams and tc_teams:
            score += len(trace_teams & tc_teams)

        # Tag overlap
        if trace_tags and tc_tags:
            score += len(trace_tags & tc_tags)

        # Context filter overlap
        for k, v in trace_context_filters.items():
            if tc_ctx.get(k) == v:
                score += 1

    return score
