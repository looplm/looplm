"""Tests for analytics helpers: merged-theme resolution and retrieval-source labels."""

from app.routers.dataset_helpers import extract_retrieval_sources
from app.routers.top_questions_worker import resolve_merged_source_themes


# ── Merge resolution (fixes the all-zero heatmap) ──────────────────

CHUNKS = [
    {"theme": "Order issues", "items": [1, 2]},
    {"theme": "Login problems", "items": [3]},
    {"theme": "Order delays", "items": [4, 5]},
]


def test_resolve_by_source_indices_survives_renaming():
    # Merge renamed "Order issues" + "Order delays" → "Ordering" but kept indices.
    merged = {"theme": "Ordering", "source_indices": [0, 2]}
    out = resolve_merged_source_themes(merged, CHUNKS)
    items = [i for ct in out for i in ct["items"]]
    assert sorted(items) == [1, 2, 4, 5]


def test_resolve_falls_back_to_name_when_indices_missing():
    merged = {"theme": "login problems"}  # different case, no indices
    out = resolve_merged_source_themes(merged, CHUNKS)
    assert [ct["theme"] for ct in out] == ["Login problems"]


def test_resolve_ignores_out_of_range_indices():
    merged = {"theme": "X", "source_indices": [0, 99, -1]}
    out = resolve_merged_source_themes(merged, CHUNKS)
    assert out == [CHUNKS[0]]


# ── Retrieval source labels (fixes identical domain rows) ──────────

def test_extract_sources_uses_confluence_slug_as_label():
    output = {
        "sources": [
            {"url": "https://acme.atlassian.net/wiki/spaces/OPS/pages/123/Wie+erstelle+ich+X"},
            {"url": "https://acme.atlassian.net/wiki/spaces/OPS/pages/456/Reset+Password"},
        ]
    }
    out = extract_retrieval_sources(output)
    labels = [s["label"] for s in out]
    assert labels == ["Wie erstelle ich X", "Reset Password"]
    # Canonical URLs drop the slug (so counting dedupes correctly).
    assert out[0]["url"].endswith("/pages/123")


def test_extract_sources_prefers_explicit_title():
    output = {"sources": [{"url": "https://x.test/a/b", "title": "My Page"}]}
    assert extract_retrieval_sources(output)[0]["label"] == "My Page"


def test_extract_sources_dedupes_by_canonical_url():
    output = {
        "sources": [
            {"url": "https://acme.atlassian.net/wiki/spaces/OPS/pages/123/Title-A"},
            {"url": "https://acme.atlassian.net/wiki/spaces/OPS/pages/123/Title-A-again"},
        ]
    }
    out = extract_retrieval_sources(output)
    assert len(out) == 1


def test_extract_sources_handles_non_dict():
    assert extract_retrieval_sources(None) == []
    assert extract_retrieval_sources({"sources": "nope"}) == []
