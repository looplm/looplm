"""Tests for the file-type dimension reader extracted from routers/index_explorer.py.

Guards the extraction: the Overview page and the Data Sources drill-down must detect the
same field and report the same distribution.
"""

from __future__ import annotations

import pytest

from app.index_providers.base import BaseIndexProvider, PartitionKey, PartitionValue
from app.services.index_dimensions import FILETYPE_FIELDS, file_type_distribution


class _Provider(BaseIndexProvider):
    """Minimal provider exposing a configurable set of partition keys."""

    # `None` means "use the default two values"; an explicit [] means an empty index.
    _DEFAULT_VALUES = (
        PartitionValue(value="pdf", doc_count=10),
        PartitionValue(value="html", doc_count=4),
    )

    def __init__(self, keys: list[str], values: list[PartitionValue] | None = None):
        self._keys = keys
        self._values = list(self._DEFAULT_VALUES) if values is None else values
        self.faceted_on: str | None = None

    async def test_connection(self):
        return 14

    async def list_partition_keys(self):
        return [PartitionKey(key=k, label=k) for k in self._keys]

    async def get_partition_distribution(self, key, filters=None):
        self.faceted_on = key
        return self._values

    async def sample_documents(self, key, value, n, filters=None):
        return []

    async def search_files(self, query, limit):
        return []

    async def list_file_chunks(self, key, value, kind, limit):
        return []

    async def fetch_documents_by_key(self, ids):
        return {}

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_detects_the_type_field_and_returns_counts():
    provider = _Provider(["title", "content_type", "url"])
    field, values = await file_type_distribution(provider)
    assert field == "content_type"
    assert values == [("pdf", 10), ("html", 4)]
    assert provider.faceted_on == "content_type"


@pytest.mark.asyncio
async def test_returns_none_when_no_type_field_exists():
    """An index with no facetable type field must degrade, not raise."""
    provider = _Provider(["title", "url", "chunk_text"])
    field, values = await file_type_distribution(provider)
    assert field is None
    assert values == []
    # Must not have wasted a facet query.
    assert provider.faceted_on is None


@pytest.mark.asyncio
async def test_field_priority_is_respected():
    """content_type outranks the generic `type` when an index exposes both."""
    assert FILETYPE_FIELDS.index("content_type") < FILETYPE_FIELDS.index("type")
    provider = _Provider(["type", "content_type"])
    field, _ = await file_type_distribution(provider)
    assert field == "content_type"


@pytest.mark.asyncio
async def test_empty_distribution_is_passed_through():
    provider = _Provider(["doc_type"], values=[])
    field, values = await file_type_distribution(provider)
    assert field == "doc_type"
    assert values == []
