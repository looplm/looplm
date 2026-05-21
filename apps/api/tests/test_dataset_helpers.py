"""Tests for trace-input → suggestion prompt extraction helpers."""

from __future__ import annotations

from app.routers.dataset_helpers import (
    _build_prompt_with_context,
    _extract_conversation_history,
    _extract_user_prompt,
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


def test_history_skips_messages_without_text():
    history = _extract_conversation_history([
        {"role": "user", "content": ""},
        {"role": "user", "content": "real question"},
    ])
    assert history == [{"role": "user", "content": "real question"}]


# ── _build_prompt_with_context ─────────────────────────────────

def test_prompt_single_turn_returns_bare_message():
    result = _build_prompt_with_context([
        {"role": "user", "content": "What is the capital of France?"},
    ])
    assert result == "What is the capital of France?"


def test_prompt_bare_string_returns_as_is():
    result = _build_prompt_with_context("just a question")
    assert result == "just a question"


def test_prompt_falls_back_for_non_conversation_dict():
    # Dict with a prompt key but no messages array → falls back to bare extraction.
    result = _build_prompt_with_context({"prompt": "hello there"})
    assert result == "hello there"


def test_prompt_multi_turn_includes_prior_context():
    result = _build_prompt_with_context([
        {"role": "user", "content": "Was sind die Hauptrisiken von X?"},
        {"role": "assistant", "content": "Die Hauptrisiken sind A, B und C."},
        {"role": "user", "content": "Kannst du mir dazu Rechtsentscheide zeigen?"},
    ])
    assert result is not None
    assert result.startswith("[Earlier in this conversation:")
    assert "User: Was sind die Hauptrisiken von X?" in result
    assert "Assistant: Die Hauptrisiken sind A, B und C." in result
    # Final question is the trailing line, in full.
    assert result.endswith("Kannst du mir dazu Rechtsentscheide zeigen?")


def test_prompt_truncates_long_prior_turns():
    long_text = "x" * 2000
    result = _build_prompt_with_context([
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": long_text},
        {"role": "user", "content": "follow up"},
    ])
    assert result is not None
    # The long assistant turn must be capped, but the final question is intact.
    assert "x" * 2000 not in result
    assert "…" in result
    assert result.endswith("follow up")


def test_prompt_caps_total_prior_turns():
    # 10 prior turns; we keep at most _CONTEXT_MAX_TURNS = 6 of them.
    messages = []
    for i in range(5):
        messages.append({"role": "user", "content": f"q{i}"})
        messages.append({"role": "assistant", "content": f"a{i}"})
    messages.append({"role": "user", "content": "final"})

    result = _build_prompt_with_context(messages)
    assert result is not None
    # Oldest turns must be dropped; newest prior turns retained.
    assert "q0" not in result
    assert "a0" not in result
    assert "q4" in result
    assert "a4" in result
    assert result.endswith("final")


def test_prompt_assistant_only_prior_emits_bare_question():
    # If there is no earlier user message there's nothing the follow-up
    # could be referring back to — just emit the final question.
    result = _build_prompt_with_context([
        {"role": "assistant", "content": "greeting from the bot"},
        {"role": "user", "content": "what is X?"},
    ])
    assert result == "what is X?"


# ── _extract_user_prompt (unchanged behavior) ──────────────────

def test_extract_user_prompt_returns_last_user_message():
    # Confirm we didn't accidentally change the existing single-turn helper.
    result = _extract_user_prompt([
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second"},
    ])
    assert result == "second"
