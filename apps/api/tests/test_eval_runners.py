"""Tests for eval runner helpers — retrieved-URL extraction and the contains_urls grader."""

from __future__ import annotations

import json

import pytest

from app.models.models import Evaluator, EvaluatorType, TestCase
from app.services.eval_executor_helpers import _run_evaluators_for_turn
from app.services.eval_runners import _run_deterministic, derive_judge_context
from app.services.retrieval_config import extract_retrieved_urls


# --- extract_retrieved_urls ---

def test_retrieved_urls_from_top_level_sources():
    raw = json.dumps({
        "answer": "hi",
        "sources": [
            {"url": "https://a.example/page"},
            {"url": "https://b.example/doc", "title": "B"},
            {"url": "https://a.example/page"},  # duplicate
        ],
    })
    assert extract_retrieved_urls(raw) == ["https://a.example/page", "https://b.example/doc"]


def test_retrieved_urls_from_sources_under_payload_key():
    raw = json.dumps({
        "answer": "hi",
        "myContext": {"sources": [{"url": "https://a.example/x"}]},
    })
    assert extract_retrieved_urls(raw, payload_key="myContext") == ["https://a.example/x"]


def test_retrieved_urls_from_sources_under_fallback_key():
    raw = json.dumps({
        "retrievedContext": {"sources": [{"url": "https://a.example/x"}]},
    })
    assert extract_retrieved_urls(raw) == ["https://a.example/x"]


def test_retrieved_urls_from_bare_source_list_under_fallback_key():
    # searchSources holds the source list directly (no {"sources": ...} wrapper),
    # and sources may carry pageUrl instead of url.
    raw = json.dumps({
        "answer": "hi [1]",
        "searchSources": [
            {"id": "page_1", "url": "https://co.example/wiki/spaces/AB/pages/111/Slug%20One"},
            {"id": "page_2", "pageUrl": "https://co.example/wiki/spaces/AB/pages/222/Slug+Two"},
        ],
    })
    assert extract_retrieved_urls(raw) == [
        "https://co.example/wiki/spaces/AB/pages/111",
        "https://co.example/wiki/spaces/AB/pages/222",
    ]


def test_retrieved_urls_url_free_context_falls_back_to_raw_response():
    # retrievedContext matches first but holds plain-text chunks without URLs —
    # extraction must fall through to the raw response instead of returning [].
    raw = json.dumps({
        "answer": "hi",
        "retrievedContext": ["Gefundene Dokumente (2 von 10): [1] Some chunk text, no links."],
        "pageImageGroups": [{"imageUrl": "https://co.example/wiki/download/attachments/1/a.png"}],
    })
    assert extract_retrieved_urls(raw) == [
        "https://co.example/wiki/download/attachments/1/a.png"
    ]


def test_retrieved_urls_regex_fallback_over_retrieval_context():
    raw = json.dumps({
        "answer": "see https://unrelated.example/in-answer",
        "retrievalContext": "Chunk from https://a.example/p1. More at https://b.example/p2, done.",
    })
    # Regex runs over the retrieval context only, not the answer
    assert extract_retrieved_urls(raw) == ["https://a.example/p1", "https://b.example/p2"]


def test_retrieved_urls_regex_fallback_over_raw_response():
    raw = json.dumps({"answer": "cited: https://a.example/p1 and (https://b.example/p2)."})
    assert extract_retrieved_urls(raw) == ["https://a.example/p1", "https://b.example/p2"]


def test_retrieved_urls_non_json_input_uses_regex():
    assert extract_retrieved_urls("plain text https://a.example/x end") == ["https://a.example/x"]


def test_retrieved_urls_normalizes_confluence_slugs():
    raw = "https://co.example/wiki/spaces/AB/pages/123/Some%20Mangled+Slug"
    assert extract_retrieved_urls(raw) == ["https://co.example/wiki/spaces/AB/pages/123"]


def test_retrieved_urls_empty_and_capped():
    assert extract_retrieved_urls("") == []
    assert extract_retrieved_urls("no urls here") == []
    many = " ".join(f"https://e.example/{i}" for i in range(50))
    assert len(extract_retrieved_urls(many, limit=30)) == 30


# --- contains_urls grader ---

def _contains_urls_evaluator() -> Evaluator:
    return Evaluator(
        name="sourceRetrieval",
        type=EvaluatorType.deterministic,
        config={"check_type": "contains_urls"},
        affects_pass=True,
    )


def test_contains_urls_includes_retrieved_urls_in_details():
    tc = TestCase(expected_page_urls=["https://a.example/p1", "https://b.example/p2"])
    raw = json.dumps({
        "answer": "x",
        "sources": [{"url": "https://a.example/p1"}, {"url": "https://c.example/other"}],
    })
    result = _run_deterministic(_contains_urls_evaluator(), "x", tc, context=raw)
    assert result["pass"] is False
    assert result["details"]["found_urls"] == ["https://a.example/p1"]
    assert result["details"]["missing_urls"] == ["https://b.example/p2"]
    assert result["details"]["retrieved_urls"] == [
        "https://a.example/p1",
        "https://c.example/other",
    ]
    # One of two expected URLs retrieved → recall 0.5 at every k.
    assert result["details"]["recall_at_k"] == {"5": 0.5, "10": 0.5}
    # One relevant URL inside the top-k slice (cutoff k), one relevant hit present.
    assert result["details"]["precision_at_k"] == {"5": 0.2, "10": 0.1}
    assert result["details"]["hit_rate_at_k"] == {"5": 1.0, "10": 1.0}


def test_contains_urls_skips_recall_when_no_expected():
    tc = TestCase(expected_page_urls=[])
    result = _run_deterministic(_contains_urls_evaluator(), "x", tc, context="{}")
    assert result["skipped"] is True
    assert "details" not in result


@pytest.mark.asyncio
async def test_run_evaluators_for_turn_preserves_details():
    tc = TestCase(expected_page_urls=["https://a.example/p1"])
    raw = json.dumps({"sources": [{"url": "https://c.example/other"}]})
    graders, overall_pass, _scores, _usages = await _run_evaluators_for_turn(
        [_contains_urls_evaluator()], None, "q", "answer", None, raw, tc,
    )
    assert overall_pass is False
    g = graders["sourceRetrieval"]
    assert g.details is not None
    assert g.details["missing_urls"] == ["https://a.example/p1"]
    assert g.details["retrieved_urls"] == ["https://c.example/other"]


# --- derive_judge_context ---

def test_judge_context_narrows_to_retrieved_context():
    """The judge must see retrieved evidence only — not the target's own system prompt.

    Regression: the full payload was passed through, so the target's prompt (which states
    what its answers may claim) reached the judge as if it were source material, and the
    judge enforced it against the answer.
    """
    raw = json.dumps({
        "answer": "Die Erstprüfung erfolgt monatlich.",
        "retrievedContext": ["QUELLE [1]: Die Erstprüfung erfolgt monatlich."],
        "prompt": {"system": "An offer to explain implicitly claims the context contains it."},
        "formattedContext": "duplicate of the sources",
        "searchSources": [{"content": "duplicate again"}],
    })

    narrowed = derive_judge_context(raw)

    assert json.loads(narrowed) == ["QUELLE [1]: Die Erstprüfung erfolgt monatlich."]
    assert "An offer to explain" not in narrowed
    assert "duplicate" not in narrowed


def test_judge_context_keeps_the_glossary_element():
    """The abbreviation glossary is authoritative grounding and lives in retrievedContext."""
    raw = json.dumps({
        "retrievedContext": ["QUELLE [1]: …", "ABKÜRZUNGSVERZEICHNIS (autoritative Auflösungen)\nLF = Lieferant"],
    })

    narrowed = json.loads(derive_judge_context(raw))

    assert len(narrowed) == 2
    assert narrowed[1].startswith("ABKÜRZUNGSVERZEICHNIS")


def test_judge_context_keeps_umlauts_unescaped():
    raw = json.dumps({"retrievedContext": ["Die Erstprüfung für Mandant Ebersdorf"]})
    assert "Erstprüfung für" in derive_judge_context(raw)


@pytest.mark.parametrize("raw", [
    None,
    "",
    "a plain-text answer, not JSON",
    json.dumps(["already", "a", "list"]),
    json.dumps({"answer": "no retrievedContext key here"}),
    json.dumps({"retrievedContext": "not a list"}),
    json.dumps({"retrievedContext": [{"not": "a string"}]}),
])
def test_judge_context_passes_through_unrecognised_payloads(raw):
    """Targets that don't expose a retrievedContext string list keep their old behaviour."""
    assert derive_judge_context(raw) == raw
