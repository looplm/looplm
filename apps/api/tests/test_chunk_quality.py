"""Unit tests for the chunk/metadata quality engine.

The four families are pure functions over a synthetic doc list, so they need no
live index; ``run_chunk_quality`` is exercised against a small in-memory fake
provider.
"""

import pytest

from app.index_providers.base import BaseIndexProvider, PartitionKey, PartitionValue
from app.index_providers.chunk_quality import (
    analyze_duplication,
    analyze_size,
    compute_score,
    run_chunk_quality,
)
from app.index_providers.chunk_quality_checks import analyze_content, analyze_metadata
from app.index_providers.chunk_quality_common import Finding


def _doc(text, **extra):
    return {"chunk_text": text, **extra}


# ── Size & consistency ───────────────────────────────────────────────────────

def test_size_flags_empty_and_tiny_chunks():
    docs = [_doc("")] + [_doc("word ")] * 20 + [_doc("x" * 4000) for _ in range(5)]
    metrics, findings = analyze_size(docs, text_field="chunk_text", group_field=None)
    assert metrics["empty"] == 1
    titles = {f.title for f in findings}
    assert "Empty chunks" in titles
    assert "Many very small chunks" in titles
    # Histogram totals the sample.
    assert sum(b["count"] for b in metrics["histogram"]) == len(docs)


def test_size_unavailable_without_text_field():
    metrics, findings = analyze_size([{"a": 1}], text_field=None, group_field=None)
    assert metrics == {"available": False}
    assert findings == []


# ── Duplication & overlap ────────────────────────────────────────────────────

def test_exact_duplicates_detected():
    docs = [_doc("the quick brown fox jumps over the lazy dog")] * 4 + [_doc("unique text here")]
    metrics, findings = analyze_duplication(
        docs, text_field="chunk_text", parent_field=None, ordinal_field=None
    )
    # 4 identical chunks → 3 duplicates beyond the first.
    assert metrics["exact_duplicates"] == 3
    assert any(f.title == "Duplicate chunks" for f in findings)


def test_adjacent_overlap_uses_ordinal_ordering():
    # Two chunks of one page that share a trailing/leading window.
    # Share a 5-word window so a 5-gram shingle overlaps (k=5).
    a = "alpha beta gamma delta epsilon zeta eta theta"
    b = "delta epsilon zeta eta theta iota kappa lambda"
    docs = [
        _doc(b, page_id="p1", chunk_index=1),
        _doc(a, page_id="p1", chunk_index=0),
    ]
    metrics, _ = analyze_duplication(
        docs, text_field="chunk_text", parent_field="page_id", ordinal_field="chunk_index"
    )
    adj = metrics["adjacency"]
    assert adj["available"] and adj["ordered"]
    assert adj["pairs"] == 1
    assert adj["median_overlap_pct"] > 0  # they share a shingle window


def test_adjacency_unavailable_without_parent_field():
    metrics, _ = analyze_duplication(
        [_doc("a b c d e f")], text_field="chunk_text", parent_field=None, ordinal_field=None
    )
    assert metrics["adjacency"]["available"] is False


# ── Content / parser quality ─────────────────────────────────────────────────

def test_content_flags_mojibake():
    docs = [_doc("Ã¼berschrift mit kaputtem encoding")] + [_doc("clean text") for _ in range(9)]
    metrics, findings = analyze_content(docs, text_field="chunk_text")
    assert metrics["mojibake"] == 1
    assert any(f.title == "Encoding artifacts (mojibake)" for f in findings)


def test_content_detects_boilerplate():
    boiler = "This document is confidential and proprietary to ACME"
    docs = [_doc(f"{boiler}\nbody {i}") for i in range(20)]
    metrics, findings = analyze_content(docs, text_field="chunk_text")
    assert metrics["boilerplate"]
    assert any(f.title == "Repeated boilerplate" for f in findings)


# ── Scoring ──────────────────────────────────────────────────────────────────

def test_score_penalises_by_severity():
    findings = [
        Finding("size", "critical", "x", "y"),
        Finding("size", "warn", "x", "y"),
        Finding("size", "info", "x", "y"),
    ]
    assert compute_score(findings) == 100 - 15 - 6 - 1
    assert compute_score([Finding("a", "critical", "x", "y")] * 100) == 0


# ── Metadata + orchestration against a fake provider ─────────────────────────

class _FakeProvider(BaseIndexProvider):
    def __init__(self, docs, *, facets=None, total=None):
        self._docs = docs
        self._facets = facets or {}
        self._total = total if total is not None else len(docs)

    async def test_connection(self):
        return self._total

    async def list_partition_keys(self):
        return [PartitionKey(key=k, label=k) for k in self._facets]

    async def get_partition_distribution(self, key, filters=None):
        return [PartitionValue(value=v, doc_count=c) for v, c in self._facets.get(key, [])]

    async def sample_documents(self, key, value, n, filters=None):
        return []

    async def sample_corpus(self, n, *, stratify_by=None):
        return self._docs[:n]


@pytest.mark.asyncio
async def test_metadata_fill_rate_from_facets_and_orphans():
    docs = [
        _doc("body one", page_url="https://x/1", page_id="p1"),
        _doc("body two", page_id="p2"),          # no url
        _doc("body three"),                       # orphan: no url, no parent
    ]
    provider = _FakeProvider(docs, facets={"source_type": [("page", 2), ("pdf", 1)]}, total=3)
    metrics, findings = await analyze_metadata(
        docs, provider, 3,
        text_field="chunk_text", title_field=None, url_field="page_url", parent_field="page_id",
    )
    st = next(f for f in metrics["fields"] if f["field"] == "source_type")
    assert st["fill_source"] == "facet"
    assert st["fill_rate"] == 100.0  # 3 of 3 docs faceted
    assert metrics["orphans"] == 1
    assert any(f.title == "Orphan chunks" for f in findings)


@pytest.mark.asyncio
async def test_run_chunk_quality_end_to_end():
    docs = (
        [_doc("the quick brown fox jumps over the lazy dog repeatedly", page_id="p1", page_url="u")]
        * 3
        + [_doc(f"distinct passage number {i} with some filler words here", page_id="p2", page_url="u")
           for i in range(12)]
    )
    provider = _FakeProvider(docs, facets={"source_type": [("page", 15)]})
    report = await run_chunk_quality(provider, sample_size=100)
    assert report.sample_size == len(docs)
    assert report.total_docs == len(docs)
    assert 0 <= report.score <= 100
    assert set(report.families) == {"size", "duplication", "metadata", "content"}
    blob = report.to_dict()
    assert blob["summary"]["score"] == report.score
    assert blob["fields"]["text"] == "chunk_text"


@pytest.mark.asyncio
async def test_run_chunk_quality_handles_no_sampling():
    class _NoSample(_FakeProvider):
        async def sample_corpus(self, n, *, stratify_by=None):
            raise NotImplementedError("no scan")

    with pytest.raises(NotImplementedError):
        await run_chunk_quality(_NoSample([]), sample_size=10)
