"""Unit tests for synthetic question generation (chunk selection, prompting, parsing, dedup)."""

import pytest

from app.services.synthetic_questions import (
    MIN_QUESTION_CHARS,
    GeneratedQuestion,
    SourceChunk,
    build_user_prompt,
    chunk_from_document,
    dedupe_questions,
    generate_questions,
    parse_questions,
    select_chunks,
    style_plan,
)

GOOD_TEXT = (
    "Die Erstattung von Reisekosten erfolgt innerhalb von 14 Tagen nach Einreichung des "
    "Antrags. Belege müssen im Original beigefügt werden, digitale Kopien werden nur bei "
    "Beträgen unter 50 Euro akzeptiert. Anträge ohne Kostenstelle werden zurückgewiesen."
)


def _chunk(chunk_id="c1", text=GOOD_TEXT, **kw):
    return SourceChunk(chunk_id=chunk_id, text=text, **kw)


# --- chunk_from_document -------------------------------------------------------


def test_chunk_from_document_resolves_azure_style_fields():
    doc = {
        "id": "page_42_chunk_3",
        "chunk_text": GOOD_TEXT,
        "page_title": "Reisekostenrichtlinie",
        "page_url": "https://intranet/reisekosten",
        "chunk_index": 3,
    }
    chunk = chunk_from_document(doc)
    assert chunk is not None
    assert chunk.chunk_id == "page_42_chunk_3"
    assert chunk.title == "Reisekostenrichtlinie"
    assert chunk.url == "https://intranet/reisekosten"


def test_chunk_from_document_resolves_generic_field_names():
    chunk = chunk_from_document({"chunk_id": "x1", "content": GOOD_TEXT, "title": "T"})
    assert chunk is not None
    assert chunk.chunk_id == "x1"
    assert chunk.title == "T"


@pytest.mark.parametrize(
    "doc",
    [
        {"chunk_text": GOOD_TEXT},  # no key field
        {"id": "a"},  # no text field
        {"id": "", "chunk_text": GOOD_TEXT},  # empty key
        {"id": "a", "chunk_text": "   "},  # blank text
    ],
)
def test_chunk_from_document_rejects_unusable_documents(doc):
    assert chunk_from_document(doc) is None


# --- select_chunks -------------------------------------------------------------


def test_select_chunks_keeps_good_chunks():
    selection = select_chunks([_chunk("a"), _chunk("b")])
    assert [c.chunk_id for c in selection.kept] == ["a", "b"]
    assert selection.skipped == {}


def test_select_chunks_drops_empty_tiny_and_mojibake():
    selection = select_chunks(
        [
            _chunk("good"),
            _chunk("empty", text="   "),
            _chunk("tiny", text="Kurz."),
            _chunk("mojibake", text=GOOD_TEXT + " Ã¤Ã¶Ã¼ ÃŸ â€ Ã©"),
        ]
    )
    assert [c.chunk_id for c in selection.kept] == ["good"]
    assert selection.skipped["empty"] == 1
    assert selection.skipped["tiny"] == 1
    assert selection.skipped["mojibake"] == 1
    assert selection.skipped_total == 3


def test_select_chunks_collapses_repeated_chunk_ids():
    selection = select_chunks([_chunk("a"), _chunk("a"), _chunk("b")])
    assert [c.chunk_id for c in selection.kept] == ["a", "b"]
    assert selection.skipped == {"duplicate": 1}


def test_select_chunks_keeps_table_heavy_chunks():
    # A table chunk is awkward but genuinely retrievable; excluding it would hide a real part
    # of the corpus from the benchmark.
    table = "| a | b |\t| c | d |\t" * 20
    selection = select_chunks([_chunk("t", text=table + GOOD_TEXT)])
    assert [c.chunk_id for c in selection.kept] == ["t"]


# --- prompting -----------------------------------------------------------------


def test_style_plan_is_one_factual_then_paraphrases():
    assert style_plan(1) == ["factual"]
    assert style_plan(2) == ["factual", "paraphrase"]
    assert style_plan(3) == ["factual", "paraphrase", "paraphrase"]
    assert style_plan(0) == ["factual"]


def test_user_prompt_numbers_chunks_and_states_the_quota():
    prompt = build_user_prompt([_chunk("a", title="Policy"), _chunk("b")], 2)
    assert "1 factual and 1 paraphrase" in prompt
    assert "[1] (Policy)" in prompt
    assert "[2]" in prompt
    # Chunks go out whole; the benchmark must not be written against truncated text.
    assert GOOD_TEXT.split(". ")[-1][:30] in prompt


# --- parse_questions -----------------------------------------------------------


def test_parse_questions_maps_entries_back_onto_chunks():
    chunks = [_chunk("a"), _chunk("b")]
    content = """{"chunks": [
        {"chunk": 1, "questions": [
            {"text": "Wie lange dauert die Erstattung von Reisekosten?", "style": "factual"},
            {"text": "Wann bekomme ich mein ausgelegtes Geld zurueck?", "style": "paraphrase"}
        ]},
        {"chunk": 2, "questions": [
            {"text": "Welche Belege sind fuer eine Erstattung erforderlich?", "style": "factual"}
        ]}
    ]}"""
    questions = parse_questions(content, chunks, 2)
    assert len(questions) == 3
    assert questions[0].source_chunk_id == "a"
    assert questions[0].style == "factual"
    assert questions[1].style == "paraphrase"
    assert questions[2].source_chunk_id == "b"
    assert questions[0].source_preview


def test_parse_questions_tolerates_code_fences_and_prose():
    chunks = [_chunk("a")]
    content = (
        "Sure, here you go:\n```json\n"
        '{"chunks": [{"chunk": 1, "questions": [{"text": "Wie lange dauert die Erstattung?",'
        ' "style": "factual"}]}]}\n```'
    )
    assert len(parse_questions(content, chunks, 2)) == 1


@pytest.mark.parametrize(
    "content",
    ["not json at all", "{}", '{"chunks": "nope"}', '{"chunks": [{"chunk": 9, "questions": []}]}'],
)
def test_parse_questions_returns_nothing_for_unusable_responses(content):
    assert parse_questions(content, [_chunk("a")], 2) == []


def test_parse_questions_drops_stubs_and_artifact_references():
    chunks = [_chunk("a")]
    content = """{"chunks": [{"chunk": 1, "questions": [
        {"text": "Wie?", "style": "factual"},
        {"text": "What does this document say about reimbursement?", "style": "factual"},
        {"text": "Laut dem Text: welche Frist gilt fuer die Erstattung?", "style": "factual"},
        {"text": "Innerhalb welcher Frist werden Reisekosten erstattet?", "style": "factual"}
    ]}]}"""
    questions = parse_questions(content, chunks, 4)
    assert [q.text for q in questions] == [
        "Innerhalb welcher Frist werden Reisekosten erstattet?"
    ]
    assert all(len(q.text) >= MIN_QUESTION_CHARS for q in questions)


def test_parse_questions_caps_per_chunk_and_normalizes_unknown_styles():
    chunks = [_chunk("a")]
    content = """{"chunks": [{"chunk": 1, "questions": [
        {"text": "Innerhalb welcher Frist werden Reisekosten erstattet?", "style": "weird"},
        {"text": "Welche Belege muessen im Original beigefuegt werden?", "style": "paraphrase"},
        {"text": "Was passiert bei fehlender Kostenstelle im Antrag?", "style": "factual"}
    ]}]}"""
    questions = parse_questions(content, chunks, 2)
    assert len(questions) == 2
    assert questions[0].style == "factual"  # unknown style falls back rather than being dropped


def test_parse_questions_ignores_negative_style_from_the_model():
    # Negatives are produced by a separate, verified pass; a model claiming a question is
    # unanswerable here would smuggle in an unverified negative with a gold chunk attached.
    chunks = [_chunk("a")]
    content = """{"chunks": [{"chunk": 1, "questions": [
        {"text": "Innerhalb welcher Frist werden Reisekosten erstattet?", "style": "negative"}
    ]}]}"""
    assert parse_questions(content, chunks, 2)[0].style == "factual"


# --- dedupe_questions ----------------------------------------------------------


def _q(text, chunk_id="a"):
    return GeneratedQuestion(text=text, style="factual", source_chunk_id=chunk_id)


def test_dedupe_drops_exact_and_near_duplicates():
    questions = [
        _q("Innerhalb welcher Frist werden Reisekosten erstattet?", "a"),
        _q("innerhalb welcher frist werden reisekosten erstattet?", "b"),
        _q("Innerhalb welcher Frist werden Reisekosten erstattet ?", "c"),
        _q("Welche Belege muessen im Original beigefuegt werden?", "d"),
    ]
    kept, dropped = dedupe_questions(questions)
    assert [q.source_chunk_id for q in kept] == ["a", "d"]
    assert dropped == 2


def test_dedupe_keeps_distinct_questions_about_one_chunk():
    questions = [
        _q("Innerhalb welcher Frist werden Reisekosten erstattet?"),
        _q("Welche Belege muessen im Original beigefuegt werden?"),
    ]
    kept, dropped = dedupe_questions(questions)
    assert len(kept) == 2
    assert dropped == 0


# --- generate_questions --------------------------------------------------------


class _FakeLlm:
    """Minimal AnalysisLlmService stand-in: canned responses, recorded prompts."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.provider = "openai"
        self.model = "test-model"

    async def tracked_chat_completion(self, messages, **kwargs):
        self.calls.append(messages)
        from app.services.chunk_judge_common import empty_usage

        response = self._responses.pop(0) if self._responses else "{}"
        if isinstance(response, Exception):
            raise response
        usage = empty_usage()
        usage.input_tokens = 10
        usage.output_tokens = 5
        usage.total_tokens = 15
        return response, usage


@pytest.mark.asyncio
async def test_generate_questions_reports_progress_and_accumulates_usage():
    chunks = [_chunk("a"), _chunk("b")]
    llm = _FakeLlm(
        [
            """{"chunks": [
                {"chunk": 1, "questions": [{"text": "Innerhalb welcher Frist wird erstattet?",
                 "style": "factual"}]},
                {"chunk": 2, "questions": [{"text": "Welche Belege sind noetig?",
                 "style": "factual"}]}
            ]}"""
        ]
    )
    seen = []
    questions, usage = await generate_questions(
        llm, chunks, 1, on_progress=lambda n: _record(seen, n)
    )
    assert len(questions) == 2
    assert sum(seen) == len(chunks)
    assert usage.total_tokens == 15


@pytest.mark.asyncio
async def test_generate_questions_survives_a_failing_batch():
    llm = _FakeLlm([RuntimeError("provider exploded")])
    seen = []
    questions, _usage = await generate_questions(
        llm, [_chunk("a")], 1, on_progress=lambda n: _record(seen, n)
    )
    # The run continues with fewer questions rather than dying, and progress still advances.
    assert questions == []
    assert sum(seen) == 1


@pytest.mark.asyncio
async def test_generate_questions_with_no_chunks_makes_no_calls():
    llm = _FakeLlm([])
    questions, usage = await generate_questions(llm, [], 2)
    assert questions == []
    assert usage.total_tokens == 0
    assert llm.calls == []


async def _record(sink, n):
    sink.append(n)
