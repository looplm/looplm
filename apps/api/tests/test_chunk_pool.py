"""Tests for the multi-head candidate-pool assembler (services/chunk_pool.py)."""

from __future__ import annotations

import pytest

from app.index_providers.base import CorpusDoc
from app.services.chunk_pool import assemble_pool


class FakeProvider:
    """An index provider that returns canned hits per mode, or raises for unsupported modes."""

    def __init__(self, by_mode: dict[str, list[CorpusDoc]], unsupported: set[str] | None = None):
        self._by_mode = by_mode
        self._unsupported = unsupported or set()

    async def search_documents(self, query, n, filters=None, *, mode="keyword"):
        if mode in self._unsupported:
            raise NotImplementedError(f"no {mode}")
        return self._by_mode.get(mode, [])[:n]


def _doc(cid, **kw):
    return CorpusDoc(id=cid, **kw)


@pytest.mark.asyncio
async def test_trace_chunks_seed_pool_and_rank_first():
    provider = FakeProvider({"keyword": [_doc("k1")]})
    res = await assemble_pool(
        provider,
        "q",
        trace_chunks=[{"chunk_id": "t1", "title": "T", "content_preview": "p"}],
        modes=["keyword"],
    )
    ids = [c.chunk_id for c in res.chunks]
    assert ids[0] == "t1"  # trace seeded first
    assert set(ids) == {"t1", "k1"}
    assert res.heads_ran == ["trace", "keyword"]


@pytest.mark.asyncio
async def test_dedup_merges_provenance_across_heads():
    provider = FakeProvider(
        {"keyword": [_doc("shared"), _doc("kw_only")], "vector": [_doc("shared"), _doc("vec_only")]}
    )
    res = await assemble_pool(
        provider,
        "q",
        trace_chunks=[{"chunk_id": "shared"}],
        modes=["keyword", "vector"],
    )
    by_id = {c.chunk_id: c for c in res.chunks}
    assert by_id["shared"].provenance == ["trace", "keyword", "vector"]
    assert by_id["kw_only"].provenance == ["keyword"]
    assert by_id["vec_only"].provenance == ["vector"]


@pytest.mark.asyncio
async def test_unsupported_head_is_recorded_not_fatal():
    provider = FakeProvider({"keyword": [_doc("k1")]}, unsupported={"vector", "hybrid"})
    res = await assemble_pool(provider, "q", modes=["keyword", "vector", "hybrid"])
    assert [c.chunk_id for c in res.chunks] == ["k1"]
    assert res.heads_ran == ["keyword"]
    assert set(res.heads_failed) == {"vector", "hybrid"}


@pytest.mark.asyncio
async def test_backfills_missing_fields_from_index_head():
    # Trace chunk lacks title/url; the keyword head supplies them.
    provider = FakeProvider({"keyword": [_doc("c1", title="Title", url="http://u", snippet="snip")]})
    res = await assemble_pool(
        provider, "q", trace_chunks=[{"chunk_id": "c1"}], modes=["keyword"]
    )
    c1 = res.chunks[0]
    assert c1.title == "Title" and c1.url == "http://u" and c1.content_preview == "snip"


@pytest.mark.asyncio
async def test_ranks_capture_per_head_position():
    # "shared" is 2nd in keyword but 1st in vector; "trace" rank follows trace order.
    provider = FakeProvider(
        {
            "keyword": [_doc("kw_only"), _doc("shared")],
            "vector": [_doc("shared"), _doc("vec_only")],
        }
    )
    res = await assemble_pool(
        provider,
        "q",
        trace_chunks=[{"chunk_id": "t1"}, {"chunk_id": "shared"}],
        modes=["keyword", "vector"],
    )
    by_id = {c.chunk_id: c for c in res.chunks}
    assert by_id["t1"].ranks == {"trace": 1}
    assert by_id["shared"].ranks == {"trace": 2, "keyword": 2, "vector": 1}
    assert by_id["kw_only"].ranks == {"keyword": 1}
    assert by_id["vec_only"].ranks == {"vector": 2}


@pytest.mark.asyncio
async def test_no_provider_returns_trace_only_pool():
    res = await assemble_pool(None, "q", trace_chunks=[{"chunk_id": "t1"}])
    assert [c.chunk_id for c in res.chunks] == ["t1"]
    assert res.heads_ran == ["trace"]
    assert res.heads_failed == {}
