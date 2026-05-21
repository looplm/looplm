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

def test_contextualized_without_summary_returns_bare_question():
    assert build_contextualized_prompt("What is X?") == "What is X?"
    assert build_contextualized_prompt("What is X?", summary=None) == "What is X?"
    assert build_contextualized_prompt("What is X?", summary="   ") == "What is X?"


def test_contextualized_with_summary_prepends_topic_preamble():
    result = build_contextualized_prompt(
        final_question="Kannst du mir dazu Rechtsentscheide zeigen?",
        summary="Der Nutzer fragt nach Datenschutzverstößen im Lieferantenkontext und wie diese korrekt gemeldet werden.",
    )
    assert result == (
        "[Conversation so far:\n"
        "Der Nutzer fragt nach Datenschutzverstößen im Lieferantenkontext "
        "und wie diese korrekt gemeldet werden.]\n\n"
        "Kannst du mir dazu Rechtsentscheide zeigen?"
    )


def test_contextualized_strips_summary_whitespace():
    result = build_contextualized_prompt(
        final_question="follow up",
        summary="  topic with surrounding whitespace  \n",
    )
    assert "topic with surrounding whitespace" in result
    assert "  topic with surrounding whitespace" not in result


def test_contextualized_does_not_echo_assistant_answer():
    # Regression guard: the prompt must NEVER contain the literal "Last turn"
    # or "Assistant:" markers we used earlier — those leaked answers into
    # the test prompt.
    result = build_contextualized_prompt(
        final_question="wie melde ich einen Datenschutzverstoß",
        summary="data-protection reporting in the supplier context",
    )
    assert "Last turn:" not in result
    assert "Assistant:" not in result


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
