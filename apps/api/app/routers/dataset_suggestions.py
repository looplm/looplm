"""Source extraction & suggestion-building helpers for dataset endpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import unquote, urlparse

from app.models.models import FeedbackScore, Span, Trace
from app.schemas.datasets import TestCaseSuggestion
from app.services.retrieval_config import (
    DEFAULT_RETRIEVAL_SPAN_NAME,
    extract_retrieval_source_urls,
    normalize_source_url as _normalize_source_url,
)

from .dataset_conversation import _extract_user_prompt, strip_personal_greeting

logger = logging.getLogger(__name__)


async def load_trace_source_urls(
    db: Any,
    trace_ids: list[Any],
    span_name: str = DEFAULT_RETRIEVAL_SPAN_NAME,
) -> dict[str, list[str]]:
    """Load retrieval-span outputs for ``trace_ids`` and return a
    ``{str(trace_id): [url, ...]}`` map.

    Looks for spans named ``span_name`` (the agent's RAG step — per-project
    configurable, defaults to ``retrieval-context``). A single trace can have
    multiple — we merge them in insertion order and de-duplicate URLs.
    """
    from sqlalchemy import select

    if not trace_ids:
        return {}

    rows = (
        await db.execute(
            select(Span.trace_id, Span.output)
            .where(Span.trace_id.in_(trace_ids))
            .where(Span.name == span_name)
            .order_by(Span.created_at)
        )
    ).all()

    by_trace: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for trace_id, output in rows:
        key = str(trace_id)
        bucket = by_trace.setdefault(key, [])
        seen_set = seen.setdefault(key, set())
        for url in extract_retrieval_source_urls(output):
            if url not in seen_set:
                seen_set.add(url)
                bucket.append(url)
    return by_trace


def _source_label(raw_url: str, src: dict) -> str:
    """Human-readable label for a retrieved source.

    Prefers an explicit title/name on the source, then the original URL's last
    path segment (e.g. a Confluence page-title slug, which normalization strips
    from the canonical URL), falling back to the host. This keeps rows
    distinguishable when many sources share one base domain.
    """
    for key in ("title", "name", "label"):
        value = src.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    parsed = urlparse(raw_url)
    segments = [s for s in parsed.path.split("/") if s]
    if segments:
        last = unquote(segments[-1].replace("+", " ")).strip()
        if last:
            return last
    return parsed.netloc or raw_url


def extract_retrieval_sources(span_output: Any) -> list[dict]:
    """Like :func:`extract_retrieval_source_urls` but also returns a display label.

    Returns de-duplicated ``{"url", "label"}`` dicts (canonical URL for counting,
    label for display) preserving original order.
    """
    if not isinstance(span_output, dict):
        return []
    sources = span_output.get("sources")
    if not isinstance(sources, list):
        return []
    seen: set[str] = set()
    out: list[dict] = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        raw_url = src.get("url")
        if not isinstance(raw_url, str):
            continue
        raw_url = raw_url.strip()
        url = _normalize_source_url(raw_url)
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "label": _source_label(raw_url, src)})
    return out


def build_suggestions(
    rows: list[tuple[FeedbackScore, Trace | None]],
    trace_sources: dict[str, list[str]] | None = None,
) -> list[TestCaseSuggestion]:
    """Build test case suggestions from feedback+trace rows.

    Deduplicates by prompt and enriches with context metadata.

    ``trace_sources`` maps ``str(trace_id) -> [source_url, ...]`` extracted
    from each trace's retrieval-context span(s). Passed in by the endpoint so
    we keep this helper pure and avoid an N+1 lookup per trace.
    """
    suggestions: list[TestCaseSuggestion] = []
    seen_prompts: set[str] = set()
    trace_sources = trace_sources or {}

    for feedback, trace in rows:
        if trace is None:
            continue

        # ``trace.input`` is the bare final user message on these integrations
        # (verified empirically — the multi-turn history lives on the agent's
        # llm-generation span, not here). The suggestion worker rewrites this
        # field with a summary + last-turn preamble for multi-turn traces.
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

        # User name (display) for stripping personal greetings from the
        # canonical answer. metadata.userName is the friendly display name;
        # trace.user_id is usually an opaque identifier but worth a fallback.
        user_name = metadata.get("userName") or trace.user_id

        # For positive feedback, use the actual answer as the expected one,
        # but strip the personal greeting first so names don't leak into the
        # canonical test case.
        suggested = (
            strip_personal_greeting(actual_answer, known_name=user_name)
            if feedback.value == 1
            else None
        )

        sources = trace_sources.get(str(trace.id), []) if trace.id else []

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
            expected_sources=sources,
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
    """Use the LLM to draft acceptance criteria for the test case.

    The user feedback rarely contains a verbatim correct answer, so we ask
    the model for *criteria* describing what a correct response must
    cover, plus a non-negotiable fallback rule: if the assistant lacks
    grounded information, it must say so rather than fabricate.
    """
    parts = [f"User question:\n{prompt}"]
    if actual_answer:
        parts.append(f"Response that the user marked as incorrect:\n{actual_answer[:2000]}")
    if comment:
        parts.append(f"User feedback / correction:\n{comment}")

    user_content = "\n\n".join(parts)

    try:
        content, usage = await llm_service.tracked_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a QA specialist authoring acceptance criteria for a test case. "
                        "You will receive a user question, the response the user marked as wrong, "
                        "and (optionally) the user's feedback. Write CRITERIA describing what a "
                        "correct response must contain — NOT a fabricated answer.\n\n"
                        "Hard rules:\n"
                        "1. Do NOT invent factual content or specific procedures. You almost "
                        "certainly do not know the ground truth.\n"
                        "2. State the topic, scope, and intent the answer must address, derived "
                        "only from what the user question and feedback reveal.\n"
                        "3. If the feedback explicitly contains a correction or required fact, "
                        "capture that as a required element. Otherwise, do not assert specifics.\n"
                        "4. Always include this fallback rule explicitly: if the assistant cannot "
                        "find the information in its sources, it must say so plainly and must not "
                        "guess or produce a plausible-sounding answer.\n"
                        "5. Output 2–5 short bullet points starting with '- ', in the same "
                        "language as the user question. No preamble or meta-commentary."
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
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
