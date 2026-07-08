"""Tests for the source-review chunk resolver (Data Sources 'Source review' tab)."""

from __future__ import annotations

import pytest

from app.index_providers.base import BaseIndexProvider, CorpusDoc, FileMatch
from app.index_providers.source_gaps import page_id_for
from app.services.source_chunks import SourceChunkInput, get_source_chunks


class _FakeProvider(BaseIndexProvider):
    """Resolves one URL by page_id and one source by filename/title search."""

    def __init__(self, *, chunk_ordinals):
        self.indexed_url = "https://www.gesetze-im-internet.de/bgb/BJNR001950896.html"
        self.chunk_ordinals = chunk_ordinals

    async def test_connection(self):  # pragma: no cover - unused
        return 1

    async def list_partition_keys(self):  # pragma: no cover - unused
        return []

    async def get_partition_distribution(self, key, filters=None):  # pragma: no cover
        return []

    async def sample_documents(self, key, value, n, filters=None):  # pragma: no cover
        return []

    async def lookup_ids(self, key, values):
        target = page_id_for(self.indexed_url)
        return {target: 3} if target in values else {}

    async def search_files(self, query, limit):
        if "utilmd" in query.lower():
            return [
                FileMatch(
                    key="attachment_filename",
                    value="utilmd_ahb.pdf",
                    label="UTILMD AHB Strom 2.1",
                    kind="attachment",
                    chunk_count=2,
                    url="https://x/utilmd_ahb.pdf",
                )
            ]
        return []

    async def list_file_chunks(self, key, value, kind, limit):
        return [
            CorpusDoc(id=f"{value}_chunk_{o}", title="c", url=None, snippet="text", ordinal=o)
            for o in self.chunk_ordinals
        ]


@pytest.mark.asyncio
async def test_resolves_by_url_hash_and_flags_gaps():
    provider = _FakeProvider(chunk_ordinals=[0, 1, 2, 5])
    source = SourceChunkInput(
        id="1",
        name="BGB",
        html_url="https://www.gesetze-im-internet.de/bgb/BJNR001950896.html",
    )
    result = await get_source_chunks(provider, source)

    assert result.resolved is True
    assert result.resolution == "url"
    assert result.chunk_count == 4
    assert result.ordinal_available is True
    assert result.missing_ordinals == [3, 4]
    assert result.duplicate_ordinals == []


@pytest.mark.asyncio
async def test_resolves_by_title_search_when_no_url_hit():
    provider = _FakeProvider(chunk_ordinals=[0, 0, 1])
    source = SourceChunkInput(id="2", name="UTILMD AHB Strom", html_url="https://platform/docs")
    result = await get_source_chunks(provider, source)

    assert result.resolved is True
    assert result.resolution == "title"
    assert result.kind == "attachment"
    assert result.duplicate_ordinals == [0]
    assert result.missing_ordinals == []


@pytest.mark.asyncio
async def test_unresolved_source_returns_empty():
    provider = _FakeProvider(chunk_ordinals=[0, 1])
    source = SourceChunkInput(id="3", name="Voellig unbekannt XYZQ", html_url="https://nope/docs")
    result = await get_source_chunks(provider, source)

    assert result.resolved is False
    assert result.resolution == "none"
    assert result.chunks == []


@pytest.mark.asyncio
async def test_no_ordinal_field_reports_unavailable():
    provider = _FakeProvider(chunk_ordinals=[None, None])
    source = SourceChunkInput(
        id="4",
        name="BGB",
        html_url="https://www.gesetze-im-internet.de/bgb/BJNR001950896.html",
    )
    result = await get_source_chunks(provider, source)

    assert result.resolved is True
    assert result.ordinal_available is False
    assert result.missing_ordinals == []
