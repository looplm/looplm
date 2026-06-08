"""Tests for analytics helpers: merged-theme resolution and retrieval-source labels."""

from app.routers.dataset_helpers import extract_retrieval_sources
from app.routers.top_questions_worker import (
    attribute_merged_themes,
    resolve_merged_source_indices,
)


# ── Merge resolution (fixes the all-zero heatmap) ──────────────────

CHUNKS = [
    {"theme": "Order issues", "items": [1, 2]},
    {"theme": "Login problems", "items": [3]},
    {"theme": "Order delays", "items": [4, 5]},
]


def test_resolve_by_source_indices_survives_renaming():
    # Merge renamed "Order issues" + "Order delays" → "Ordering" but kept indices.
    merged = {"theme": "Ordering", "source_indices": [0, 2]}
    assert resolve_merged_source_indices(merged, CHUNKS) == [0, 2]


def test_resolve_coerces_string_indices():
    assert resolve_merged_source_indices({"source_indices": ["0", "2"]}, CHUNKS) == [0, 2]


def test_resolve_falls_back_to_name_when_indices_missing():
    merged = {"theme": "login problems"}  # different case, no indices
    assert resolve_merged_source_indices(merged, CHUNKS) == [1]


def test_resolve_ignores_out_of_range_indices():
    assert resolve_merged_source_indices({"source_indices": [0, 99, -1]}, CHUNKS) == [0]


def test_attribute_is_lossless_when_indices_present():
    merged = [{"theme": "Ordering", "source_indices": [0, 2]}]
    out = attribute_merged_themes(merged, CHUNKS)
    # Merged theme keeps 0+2; the unclaimed "Login problems" is appended standalone.
    assert [idxs for _, idxs in out] == [[0, 2], [1]]


def test_attribute_drops_empty_merge_and_recovers_via_standalone():
    # Model renamed everything and gave no usable indices → no merge resolves;
    # every chunk theme must still surface (no data lost), just un-merged.
    merged = [{"theme": "Totally Different Label"}]
    out = attribute_merged_themes(merged, CHUNKS)
    assert sorted(i for _, idxs in out for i in idxs) == [0, 1, 2]


def test_attribute_no_double_claim():
    merged = [
        {"theme": "A", "source_indices": [0, 1]},
        {"theme": "B", "source_indices": [1, 2]},  # 1 already claimed by A
    ]
    out = attribute_merged_themes(merged, CHUNKS)
    claimed = [i for _, idxs in out for i in idxs]
    assert sorted(claimed) == [0, 1, 2]  # each chunk attributed exactly once


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
