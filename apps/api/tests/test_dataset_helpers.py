"""Tests for trace-input → suggestion prompt helpers."""

from __future__ import annotations

import pytest

from app.routers.dataset_helpers import (
    _extract_conversation_history,
    _extract_user_prompt,
    build_contextualized_prompt,
    summarize_conversation,
)


# ── _extract_conversation_history ──────────────────────────────

def test_history_empty_for_string_input():
    assert _extract_conversation_history("just a string") == []


def test_history_empty_for_none():
    assert _extract_conversation_history(None) == []
    assert _extract_conversation_history({}) == []


def test_history_from_messages_array():
    history = _extract_conversation_history([
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "Bye"},
    ])
    assert history == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "Bye"},
    ]


def test_history_handles_openai_multipart_content():
    history = _extract_conversation_history({
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Part A"}, {"type": "text", "text": "Part B"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Reply"}]},
        ],
    })
    assert history == [
        {"role": "user", "content": "Part A\nPart B"},
        {"role": "assistant", "content": "Reply"},
    ]


# ── build_contextualized_prompt ────────────────────────────────

def test_contextualized_empty_messages_returns_bare_question():
    assert build_contextualized_prompt([], "What is X?") == "What is X?"


def test_contextualized_single_user_turn_returns_bare_question():
    # The conversation contains only the final user message → no preamble.
    result = build_contextualized_prompt(
        [{"role": "user", "content": "What is X?"}],
        "What is X?",
    )
    assert result == "What is X?"


def test_contextualized_with_summary_and_last_assistant():
    messages = [
        {"role": "user", "content": "Was sind die Hauptrisiken von X?"},
        {"role": "assistant", "content": "Die Hauptrisiken sind A, B und C."},
        {"role": "user", "content": "Und die Fristen?"},
        {"role": "assistant", "content": "Die Frist beträgt 14 Tage."},
        {"role": "user", "content": "Kannst du mir dazu Rechtsentscheide zeigen?"},
    ]
    result = build_contextualized_prompt(
        messages,
        final_question="Kannst du mir dazu Rechtsentscheide zeigen?",
        summary="Nutzer fragte nach Risiken von X und Fristen.",
    )
    assert result.startswith("[Earlier in this conversation (summary):")
    assert "Nutzer fragte nach Risiken von X und Fristen." in result
    assert "Last turn:" in result
    assert "Assistant: Die Frist beträgt 14 Tage." in result
    assert result.endswith("Kannst du mir dazu Rechtsentscheide zeigen?")


def test_contextualized_without_summary_still_shows_last_assistant():
    # No LLM available → no summary, but the last assistant turn is still
    # carried verbatim so the follow-up's referent is visible.
    result = build_contextualized_prompt(
        messages=[
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
            {"role": "user", "content": "follow up"},
        ],
        final_question="follow up",
        summary=None,
    )
    assert result.startswith("[Earlier in this conversation:")
    assert "(summary)" not in result
    assert "Assistant: previous answer" in result
    assert result.endswith("follow up")


def test_contextualized_truncates_long_last_assistant_turn():
    long_answer = "x" * 5000
    result = build_contextualized_prompt(
        messages=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": long_answer},
            {"role": "user", "content": "follow up"},
        ],
        final_question="follow up",
    )
    # Final question is intact; long answer is capped.
    assert result.endswith("follow up")
    assert "x" * 5000 not in result
    assert "…" in result


def test_contextualized_drops_trailing_user_message_matching_question():
    # The span typically ends with the final user message — we shouldn't
    # echo it inside the preamble.
    result = build_contextualized_prompt(
        messages=[
            {"role": "user", "content": "earlier question"},
            {"role": "assistant", "content": "earlier answer"},
            {"role": "user", "content": "Kannst du mir dazu mehr zeigen?"},
        ],
        final_question="Kannst du mir dazu mehr zeigen?",
        summary="User asked about X.",
    )
    # The final question appears exactly once — at the end.
    assert result.count("Kannst du mir dazu mehr zeigen?") == 1


# ── _extract_user_prompt (unchanged behavior) ──────────────────

def test_extract_user_prompt_returns_last_user_message():
    result = _extract_user_prompt([
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second"},
    ])
    assert result == "second"


# ── summarize_conversation (LLM-backed) ────────────────────────

class _FakeLlm:
    def __init__(self, response: str | None = "summary text"):
        self.response = response
        self.calls: list[dict] = []

    async def tracked_chat_completion(self, *, messages, temperature=0.1):
        self.calls.append({"messages": messages, "temperature": temperature})
        if self.response is None:
            raise RuntimeError("simulated LLM failure")
        return self.response, {"input": 0, "output": 0}


@pytest.mark.asyncio
async def test_summarize_returns_none_for_empty_turns():
    llm = _FakeLlm()
    assert await summarize_conversation(llm, []) is None
    assert llm.calls == []


@pytest.mark.asyncio
async def test_summarize_returns_llm_text_stripped():
    llm = _FakeLlm(response="  User asked about X.  ")
    out = await summarize_conversation(llm, [
        {"role": "user", "content": "What is X?"},
        {"role": "assistant", "content": "X is Y."},
    ])
    assert out == "User asked about X."
    assert len(llm.calls) == 1
    # Transcript must include both roles.
    transcript = llm.calls[0]["messages"][1]["content"]
    assert "User: What is X?" in transcript
    assert "Assistant: X is Y." in transcript


@pytest.mark.asyncio
async def test_summarize_returns_none_on_llm_failure():
    llm = _FakeLlm(response=None)
    out = await summarize_conversation(llm, [
        {"role": "user", "content": "What is X?"},
    ])
    assert out is None
