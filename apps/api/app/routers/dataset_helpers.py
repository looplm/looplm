"""Pure helper functions for dataset endpoints."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.models.models import FeedbackScore, Span, TestCase, Trace
from app.schemas.datasets import TestCaseItem, TestCaseSuggestion

logger = logging.getLogger(__name__)


# Strip leading personal salutations from assistant responses before they
# become canonical expected answers. Personal names ("Hallo Ursula, …",
# "Sehr geehrter Herr Müller, …") leak across test cases — they aren't part
# of the answer being graded. Reviewers can still edit in the modal if a
# false positive slips through.
_GREETING_WITH_PREFIX = re.compile(
    r"^(?:hallo|hi|hey|liebe[r]?|sehr\s+geehrte[r]?|guten\s+\w+)\s+"
    r"(?:(?:frau|herr|mr|mrs|ms|dr)\.?\s+)?"
    r"[A-ZÄÖÜ][a-zäöüß]+(?:[-\s][A-ZÄÖÜ][a-zäöüß]+)?"
    r"\s*[,!:.]\s*",
    re.IGNORECASE,
)


def strip_personal_greeting(text: str | None, known_name: str | None = None) -> str | None:
    """Remove leading personal salutations from assistant text.

    Always strips greeting-prefixed forms like ``"Hallo Ursula, "`` or
    ``"Sehr geehrter Herr Müller, "`` — those are unambiguous.

    Strips a bare ``"Name, "`` prefix only when ``known_name`` is provided
    (typically from ``trace.user_id`` / ``trace_metadata["userName"]``).
    Without that signal we leave bare leading words alone, so legitimate
    sentence starts like ``"Berlin, die Hauptstadt …"`` are not mangled.
    """
    if not text:
        return text

    stripped = _GREETING_WITH_PREFIX.sub("", text, count=1)

    if stripped == text and known_name:
        first_token = known_name.strip().split()[0] if known_name.strip() else ""
        if first_token:
            bare = re.compile(
                rf"^{re.escape(first_token)}\s*[,!:.]\s*",
                re.IGNORECASE,
            )
            stripped = bare.sub("", text, count=1)

    if stripped == text:
        return text
    stripped = stripped.lstrip()
    if stripped:
        stripped = stripped[0].upper() + stripped[1:]
    return stripped


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
    """Extract last user message from trace input.

    Handles plain strings, top-level message arrays, and the common dict
    shapes produced by Langfuse, LangSmith, Vercel AI SDK, and OpenAI-style
    payloads.
    """
    if not trace_input:
        return None

    if isinstance(trace_input, str):
        text = trace_input.strip()
        return text or None

    def _from_messages(messages: Any) -> str | None:
        if not isinstance(messages, list):
            return None
        for msg in reversed(messages):
            if not isinstance(msg, dict):
                continue
            if msg.get("role") and msg["role"] != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text", "")
                        if isinstance(text, str) and text.strip():
                            return text
            text = msg.get("text") or msg.get("input") or msg.get("prompt")
            if isinstance(text, str) and text.strip():
                return text
        return None

    if isinstance(trace_input, list):
        return _from_messages(trace_input)

    if isinstance(trace_input, dict):
        from_messages = _from_messages(trace_input.get("messages"))
        if from_messages:
            return from_messages
        for key in ("prompt", "question", "query", "text", "input"):
            value = trace_input.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, (dict, list)):
                nested = _extract_user_prompt(value)
                if nested:
                    return nested

    return None


def _extract_conversation_history(trace_input: Any) -> list[dict[str, str]]:
    """Return the ordered user/assistant turns recorded in a trace input.

    Each turn is ``{"role": "user" | "assistant", "content": "..."}``.
    Returns an empty list if the input doesn't expose a recognisable
    conversation structure (e.g. a bare prompt string).
    """
    if not trace_input or isinstance(trace_input, str):
        return []

    def _text_from_content(content: Any) -> str | None:
        if isinstance(content, str):
            return content.strip() or None
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text", "")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
            joined = "\n".join(parts).strip()
            return joined or None
        return None

    def _from_messages(messages: Any) -> list[dict[str, str]]:
        if not isinstance(messages, list):
            return []
        turns: list[dict[str, str]] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            text = _text_from_content(msg.get("content"))
            if not text:
                for k in ("text", "input", "prompt"):
                    v = msg.get(k)
                    if isinstance(v, str) and v.strip():
                        text = v.strip()
                        break
            if text:
                turns.append({"role": role, "content": text})
        return turns

    if isinstance(trace_input, list):
        return _from_messages(trace_input)

    if isinstance(trace_input, dict):
        from_messages = _from_messages(trace_input.get("messages"))
        if from_messages:
            return from_messages
        for key in ("prompt", "question", "query", "text", "input"):
            value = trace_input.get(key)
            if isinstance(value, (dict, list)):
                nested = _extract_conversation_history(value)
                if nested:
                    return nested

    return []


# Cap per-turn excerpt length and total turns kept as context so the prompt
# doesn't balloon when traces carry a long history. The final user question
# is always emitted in full — only prior turns are trimmed.
_CONTEXT_PER_TURN_CAP = 600
_CONTEXT_MAX_TURNS = 6


def _build_prompt_with_context(trace_input: Any) -> str | None:
    """Return a self-contained prompt string for a test-case suggestion.

    Single-turn traces return the user message as today. Multi-turn traces
    prepend a transcript of recent prior user/assistant turns so that
    follow-up questions like ``"Kannst du mir Rechtsentscheide dazu zeigen?"``
    carry the context their meaning depends on. The reviewer sees the
    transcript in the modal and can edit it before saving.
    """
    history = _extract_conversation_history(trace_input)
    if not history:
        return _extract_user_prompt(trace_input)

    last_user_idx = None
    for i in range(len(history) - 1, -1, -1):
        if history[i]["role"] == "user":
            last_user_idx = i
            break
    if last_user_idx is None:
        return None

    final_question = history[last_user_idx]["content"]
    prior = history[:last_user_idx]

    # No earlier user turn means there's nothing the follow-up could be
    # referring back to — emit just the question.
    if not any(t["role"] == "user" for t in prior):
        return final_question

    prior = prior[-_CONTEXT_MAX_TURNS:]
    lines = ["[Earlier in this conversation:"]
    for turn in prior:
        label = "User" if turn["role"] == "user" else "Assistant"
        content = turn["content"]
        if len(content) > _CONTEXT_PER_TURN_CAP:
            content = content[:_CONTEXT_PER_TURN_CAP].rstrip() + "…"
        lines.append(f"{label}: {content}")
    lines.append("]")
    lines.append("")
    lines.append(final_question)
    return "\n".join(lines)


async def load_trace_source_urls(
    db: Any,
    trace_ids: list[Any],
) -> dict[str, list[str]]:
    """Load retrieval-context span outputs for ``trace_ids`` and return a
    ``{str(trace_id): [url, ...]}`` map.

    Looks for spans named ``retrieval-context`` (the agent's RAG step in our
    observability traces). A single trace can have multiple — we merge them
    in insertion order and de-duplicate URLs.
    """
    from sqlalchemy import select

    if not trace_ids:
        return {}

    rows = (
        await db.execute(
            select(Span.trace_id, Span.output)
            .where(Span.trace_id.in_(trace_ids))
            .where(Span.name == "retrieval-context")
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


# Confluence Cloud URLs in retrieval payloads carry a trailing slug after
# ``/pages/<id>/`` that often contains malformed or double-encoded characters.
# Confluence resolves the bare ``/pages/<id>`` form to the same page, so trim
# the slug to keep the link clickable.
_CONFLUENCE_PAGE_URL = re.compile(
    r"^(https?://[^/]+/wiki/spaces/[^/]+/pages/\d+)(?:/.*)?$",
    re.IGNORECASE,
)


def _normalize_source_url(url: str) -> str:
    match = _CONFLUENCE_PAGE_URL.match(url)
    if match:
        return match.group(1)
    return url


def extract_retrieval_source_urls(span_output: Any) -> list[str]:
    """Pull source URLs out of a retrieval-context span's output payload.

    The expected shape is ``{"sources": [{"url": "...", ...}, ...]}``.
    Returns a de-duplicated list preserving original order. Non-string and
    blank URLs are skipped so we never persist garbage as expected sources.
    """
    if not isinstance(span_output, dict):
        return []
    sources = span_output.get("sources")
    if not isinstance(sources, list):
        return []
    seen: set[str] = set()
    urls: list[str] = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        url = src.get("url")
        if not isinstance(url, str):
            continue
        url = _normalize_source_url(url.strip())
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


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

        # Carry conversation history into the prompt for multi-turn traces.
        # Follow-up questions ("kannst du mir dazu Rechtsentscheide zeigen?")
        # are unusable as standalone test cases without the prior turns —
        # the reviewer sees the transcript and can edit it before saving.
        prompt = _build_prompt_with_context(trace.input)
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
