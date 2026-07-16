"""Conversation extraction & summarization helpers for dataset endpoints."""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Span, TestCase
from app.models.user import User
from app.schemas.datasets import TestCaseItem

logger = logging.getLogger(__name__)


def _display_name(email: str) -> str:
    """Human-friendly label for a user: the local part of their email."""
    return email.split("@", 1)[0] if email else email


async def resolve_validator_names(
    db: AsyncSession, cases: list[TestCase]
) -> dict[UUID, str]:
    """Map each case's ``validated_by`` user id to a display name (email local part).

    Batch-loads the referenced users in one query. Ids with no matching user
    (e.g. a deleted account after ``SET NULL`` on the row) are simply absent.
    """
    ids = {tc.validated_by for tc in cases if tc.validated_by is not None}
    if not ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(ids)))
    return {u.id: _display_name(u.email) for u in result.scalars().all()}


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


def _tc_to_item(tc: TestCase, validated_by_email: str | None = None) -> TestCaseItem:
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
        status=tc.status or "active",
        status_note=tc.status_note,
        validated=tc.validated or False,
        validated_at=tc.validated_at,
        validated_by_email=validated_by_email,
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


def build_contextualized_prompt(
    final_question: str,
    summary: str | None = None,
) -> str:
    """Format a self-contained suggestion prompt.

    A multi-turn conversation gets a short topic recap above the user's
    final question so follow-ups like ``"kannst du mir dazu Rechtsentscheide
    zeigen?"`` carry the topic their meaning depends on. We deliberately do
    NOT include the assistant's prior answers — that would leak the answer
    to a question that's about to be asked again as a test case.
    """
    summary_text = summary.strip() if summary else None
    if not summary_text:
        return final_question

    return (
        "[Conversation so far:\n"
        f"{summary_text}]\n\n"
        f"{final_question}"
    )


async def load_trace_conversation_messages(
    db: Any,
    trace_ids: list[Any],
) -> dict[str, list[dict[str, str]]]:
    """Load the conversation messages the agent fed to its LLM, per trace.

    Returns ``{str(trace_id): [{"role": ..., "content": ...}, ...]}``.

    Pulls the **last** ``llm-generation`` span per trace because that span's
    ``input.messages`` is the most up-to-date conversation snapshot the agent
    constructed before producing the response being graded. ``trace.input``
    on these integrations is typically just the final user question string,
    so it has no prior turns on its own.
    """
    from sqlalchemy import select

    if not trace_ids:
        return {}

    rows = (
        await db.execute(
            select(Span.trace_id, Span.input, Span.created_at)
            .where(Span.trace_id.in_(trace_ids))
            .where(Span.name == "llm-generation")
            .order_by(Span.trace_id, Span.created_at.desc())
        )
    ).all()

    by_trace: dict[str, list[dict[str, str]]] = {}
    for trace_id, span_input, _ in rows:
        key = str(trace_id)
        if key in by_trace:
            continue  # only keep the most recent llm-generation span
        messages = span_input.get("messages") if isinstance(span_input, dict) else None
        if not isinstance(messages, list):
            continue
        history = _extract_conversation_history(messages)
        if history:
            by_trace[key] = history
    return by_trace


async def summarize_conversation(
    llm_service: Any,
    turns: list[dict[str, str]],
) -> str | None:
    """Use the analysis LLM to compress older conversation turns into a one-
    sentence topic recap so a follow-up question still makes sense without
    the full transcript.

    The summary intentionally captures *what was being discussed* (topic,
    subject, what the user was asking about) but NOT the assistant's
    answers, factual claims, names, numbers, or procedures. This output
    becomes part of the test prompt — leaking the assistant's prior answer
    would let the model under test cheat by regurgitating it.

    Returns ``None`` on any failure — callers should fall through to a
    bare-prompt suggestion rather than raise.
    """
    if not turns:
        return None

    transcript_lines: list[str] = []
    for t in turns:
        label = "User" if t["role"] == "user" else "Assistant"
        content = t["content"]
        if len(content) > 1500:
            content = content[:1500].rstrip() + "…"
        transcript_lines.append(f"{label}: {content}")
    transcript = "\n".join(transcript_lines)

    try:
        content, _usage = await llm_service.tracked_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write a short recap of what the user has been discussing "
                        "in a chat. Your output will be prepended to the user's next "
                        "question and used as a test case for an AI assistant, so the "
                        "assistant must be able to answer the question without your "
                        "recap containing the answer.\n\n"
                        "Hard rules:\n"
                        "1. Capture the subject(s) the user was asking about and any "
                        "details the user themselves provided (their role, their "
                        "context, constraints they mentioned, what they've tried, what "
                        "they're trying to achieve).\n"
                        "2. Do NOT include any information the assistant provided — no "
                        "specific facts, procedures, numbers, names, URLs, or "
                        "instructions. Those would give away the answer.\n"
                        "3. Write 2–4 short sentences in the same language as the chat. "
                        "Plain prose, no bullet points, no preamble, no meta-commentary.\n"
                        "4. If the user only asked one short question with no extra "
                        "context, a single sentence is fine."
                    ),
                },
                {"role": "user", "content": transcript},
            ],
            temperature=0.1,
        )
        return content.strip() if content else None
    except Exception:
        logger.exception("Failed to summarize conversation for suggestion")
        return None
