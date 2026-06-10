"""Tests for the feedback-themes worker: comment/sentiment resolution."""

from app.routers.feedback_themes_worker import _build_theme_from_indices

COMMENTS = [
    {"comment": "loved it", "feedback_value": 1, "trace_id": "t1", "question": "q1"},
    {"comment": "wrong answer", "feedback_value": 0, "trace_id": "t2", "question": "q2"},
    {"comment": "perfect", "feedback_value": 1, "trace_id": None, "question": None},
]


def test_build_theme_resolves_indices_and_tallies_sentiment():
    theme = _build_theme_from_indices(
        {"theme": "Mixed", "count": 2, "summary": "s"}, [1, 2], COMMENTS
    )
    assert theme["theme"] == "Mixed"
    assert theme["count"] == 2
    assert theme["feedback_sentiment"] == {"positive": 1, "negative": 1}
    assert [c["comment"] for c in theme["all_comments"]] == ["loved it", "wrong answer"]
    # display context is carried through
    assert theme["all_comments"][0]["trace_id"] == "t1"
    assert theme["all_comments"][0]["question"] == "q1"


def test_build_theme_ignores_out_of_range_indices():
    theme = _build_theme_from_indices(
        {"theme": "X", "summary": ""}, [1, 99, 0, -1], COMMENTS
    )
    # only index 1 is valid (1-based); 0/-1/99 dropped
    assert len(theme["all_comments"]) == 1
    assert theme["all_comments"][0]["comment"] == "loved it"
    # count falls back to len(indices) when LLM omits it
    assert theme["count"] == 4


def test_build_theme_count_defaults_to_index_count():
    theme = _build_theme_from_indices({"theme": "Y"}, [3], COMMENTS)
    assert theme["count"] == 1
    assert theme["feedback_sentiment"] == {"positive": 1, "negative": 0}
