"""Unit tests for negative (unanswerable) synthetic questions and their verification."""

import pytest

from app.index_providers.base import CorpusDoc
from app.services.synthetic_negatives import (
    generate_negatives,
    parse_negatives,
    parse_verdicts,
    verify_negatives,
)
from app.services.synthetic_questions import GeneratedQuestion, SourceChunk
from tests.test_synthetic_questions import GOOD_TEXT, _FakeLlm


def _chunk(chunk_id="c1"):
    return SourceChunk(chunk_id=chunk_id, text=GOOD_TEXT, title="Policy")


def _candidate(text):
    return GeneratedQuestion(text=text, style="negative")


class _FakeProvider:
    """Index stand-in returning canned hits per mode, or raising for unsupported modes."""

    def __init__(self, hits_by_mode=None, unsupported=()):
        self.hits_by_mode = hits_by_mode or {}
        self.unsupported = set(unsupported)
        self.queries = []

    async def search_documents(self, query, n, filters=None, *, mode="keyword", query_vector=None):
        self.queries.append((query, mode))
        if mode in self.unsupported:
            raise NotImplementedError(f"{mode} not supported")
        return self.hits_by_mode.get(mode, [])


def _doc(snippet):
    return CorpusDoc(id="x", snippet=snippet)


# --- parsing -------------------------------------------------------------------


def test_parse_negatives_accepts_objects_and_bare_strings():
    content = '{"questions": [{"text": "Wie hoch ist die Tagespauschale in Japan?"}, "Gilt die Regel auch fuer Praktikanten?"]}'
    questions = parse_negatives(content, 5)
    assert [q.style for q in questions] == ["negative", "negative"]
    assert len(questions) == 2
    # Negatives carry no ground truth; that is what makes them negative.
    assert all(q.source_chunk_id is None for q in questions)


def test_parse_negatives_caps_at_the_requested_count_and_drops_stubs():
    content = '{"questions": [{"text": "Wie hoch ist die Pauschale in Japan?"}, {"text": "Hm?"}, {"text": "Gilt das auch fuer Praktikanten?"}]}'
    assert len(parse_negatives(content, 1)) == 1
    assert [q.text for q in parse_negatives(content, 5)] == [
        "Wie hoch ist die Pauschale in Japan?",
        "Gilt das auch fuer Praktikanten?",
    ]


@pytest.mark.parametrize("content", ["nope", "{}", '{"questions": {}}'])
def test_parse_negatives_returns_nothing_for_unusable_responses(content):
    assert parse_negatives(content, 3) == []


def test_parse_verdicts_ignores_out_of_range_and_non_boolean_entries():
    content = (
        '{"verdicts": [{"candidate": 1, "answerable": true}, {"candidate": 2, "answerable": "no"},'
        ' {"candidate": 9, "answerable": false}, {"candidate": 3, "answerable": false}]}'
    )
    assert parse_verdicts(content, 3) == {1: True, 3: False}


# --- generate_negatives --------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_negatives_asks_once_and_returns_candidates():
    llm = _FakeLlm(['{"questions": [{"text": "Wie hoch ist die Pauschale in Japan?"}]}'])
    questions, usage = await generate_negatives(llm, [_chunk()], 1)
    assert len(llm.calls) == 1
    assert len(questions) == 1
    assert usage.total_tokens == 15


@pytest.mark.asyncio
async def test_generate_negatives_skipped_when_none_wanted():
    llm = _FakeLlm([])
    questions, _usage = await generate_negatives(llm, [_chunk()], 0)
    assert questions == []
    assert llm.calls == []


@pytest.mark.asyncio
async def test_generate_negatives_survives_a_provider_error():
    llm = _FakeLlm([RuntimeError("provider exploded")])
    questions, _usage = await generate_negatives(llm, [_chunk()], 3)
    assert questions == []


# --- verify_negatives ----------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_drops_candidates_the_index_actually_answers():
    provider = _FakeProvider({"hybrid": [_doc("Die Erstattung erfolgt in 14 Tagen.")]})
    llm = _FakeLlm(
        ['{"verdicts": [{"candidate": 1, "answerable": true}, {"candidate": 2, "answerable": false}]}']
    )
    kept, dropped, _usage = await verify_negatives(
        llm,
        provider,
        [_candidate("Wie lange dauert die Erstattung?"), _candidate("Gilt das in Japan?")],
    )
    assert [q.text for q in kept] == ["Gilt das in Japan?"]
    assert dropped == 1


@pytest.mark.asyncio
async def test_verify_drops_candidates_with_no_verdict():
    # An unverified negative is not trustworthy, so a missing verdict discards rather than admits.
    provider = _FakeProvider({"hybrid": [_doc("Etwas Text.")]})
    llm = _FakeLlm(['{"verdicts": []}'])
    kept, dropped, _usage = await verify_negatives(llm, provider, [_candidate("Gilt das in Japan?")])
    assert kept == []
    assert dropped == 1


@pytest.mark.asyncio
async def test_verify_falls_back_to_keyword_when_hybrid_is_unsupported():
    provider = _FakeProvider({"keyword": [_doc("Etwas Text.")]}, unsupported=("hybrid",))
    llm = _FakeLlm(['{"verdicts": [{"candidate": 1, "answerable": false}]}'])
    kept, _dropped, _usage = await verify_negatives(llm, provider, [_candidate("Gilt das in Japan?")])
    assert [mode for _q, mode in provider.queries] == ["hybrid", "keyword"]
    assert len(kept) == 1


@pytest.mark.asyncio
async def test_verify_keeps_candidates_when_the_index_returns_nothing_at_all():
    # No hits anywhere means the index is unreachable, not that every candidate is a good
    # negative; silently discarding the whole negative half would be the wrong call.
    provider = _FakeProvider({})
    llm = _FakeLlm([])
    kept, dropped, _usage = await verify_negatives(llm, provider, [_candidate("Gilt das in Japan?")])
    assert len(kept) == 1
    assert dropped == 0
    assert llm.calls == []


@pytest.mark.asyncio
async def test_verify_drops_everything_when_the_judge_call_fails():
    provider = _FakeProvider({"hybrid": [_doc("Etwas Text.")]})
    llm = _FakeLlm([RuntimeError("judge exploded")])
    kept, dropped, _usage = await verify_negatives(llm, provider, [_candidate("Gilt das in Japan?")])
    assert kept == []
    assert dropped == 1


@pytest.mark.asyncio
async def test_verify_with_no_candidates_makes_no_calls():
    provider = _FakeProvider({"hybrid": [_doc("x")]})
    llm = _FakeLlm([])
    kept, dropped, _usage = await verify_negatives(llm, provider, [])
    assert (kept, dropped) == ([], 0)
    assert provider.queries == []
