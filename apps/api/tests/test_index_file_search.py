"""Tests for the Data Sources "Files" tab: file-type overview, filename search,
and chunks-of-a-file listing (index-explorer)."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from app.index_providers.base import BaseIndexProvider, CorpusDoc, FileMatch, PartitionValue
from app.models.base import IndexProviderType
from app.models.index_providers import IndexProvider


# ── Provider-level unit tests (real Azure logic, stubbed search client) ──────


def _azure_provider(field_types: dict[str, tuple[str, bool]]):
    """An AzureSearchIndexProvider with a stubbed schema.

    ``field_types`` maps field name → (edm_type, is_key).
    """
    from app.index_providers.azure_search import AzureSearchIndexProvider, _FieldInfo

    p = AzureSearchIndexProvider(
        endpoint="https://x.search.windows.net", api_key="k", index_name="idx"
    )
    p._fields = {
        name: _FieldInfo(name, edm, False, is_key)
        for name, (edm, is_key) in field_types.items()
    }
    return p


class _FakeResults:
    def __init__(self, docs, count=0):
        self._docs = docs
        self._count = count

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d

        return gen()

    async def get_count(self):
        return self._count


@pytest.mark.asyncio
async def test_list_file_chunks_sorts_by_ordinal():
    p = _azure_provider(
        {
            "id": ("Edm.String", True),
            "attachment_filename": ("Edm.String", False),
            "chunk_text": ("Edm.String", False),
            "chunk_index": ("Edm.Int32", False),
        }
    )

    # Returned out of order, with one non-numeric ordinal that must sort last.
    docs = [
        {"id": "c2", "attachment_filename": "r.pdf", "chunk_text": "second", "chunk_index": 2},
        {"id": "c0", "attachment_filename": "r.pdf", "chunk_text": "first", "chunk_index": 0},
        {"id": "cx", "attachment_filename": "r.pdf", "chunk_text": "last", "chunk_index": "n/a"},
        {"id": "c1", "attachment_filename": "r.pdf", "chunk_text": "middle", "chunk_index": 1},
    ]

    class _FakeClient:
        async def search(self, **kwargs):
            return _FakeResults(docs if kwargs.get("skip", 0) == 0 else [])

    p._search_client = _FakeClient()

    out = await p.list_file_chunks("attachment_filename", "r.pdf", "attachment", 500)
    assert [d.id for d in out] == ["c0", "c1", "c2", "cx"]
    assert out[0].ordinal == 0 and out[0].snippet == "first"
    assert out[-1].ordinal == "n/a"  # non-numeric ordinal sorts last, value preserved


@pytest.mark.asyncio
async def test_list_file_chunks_no_ordinal_preserves_order():
    p = _azure_provider(
        {
            "id": ("Edm.String", True),
            "attachment_filename": ("Edm.String", False),
            "chunk_text": ("Edm.String", False),
        }
    )
    docs = [
        {"id": "a", "attachment_filename": "r.pdf", "chunk_text": "x"},
        {"id": "b", "attachment_filename": "r.pdf", "chunk_text": "y"},
    ]

    class _FakeClient:
        async def search(self, **kwargs):
            return _FakeResults(docs if kwargs.get("skip", 0) == 0 else [])

    p._search_client = _FakeClient()

    out = await p.list_file_chunks("attachment_filename", "r.pdf", "attachment", 500)
    assert [d.id for d in out] == ["a", "b"]  # index order preserved
    assert all(d.ordinal is None for d in out)


@pytest.mark.asyncio
async def test_search_files_dedupes_and_counts():
    p = _azure_provider(
        {
            "id": ("Edm.String", True),
            "attachment_filename": ("Edm.String", False),
            "page_title": ("Edm.String", False),
            "page_id": ("Edm.String", False),
            "page_url": ("Edm.String", False),
        }
    )
    hits = [
        {"attachment_filename": "report.pdf", "page_id": "p1"},
        {"attachment_filename": "report.pdf", "page_id": "p1"},  # dup attachment
        {"page_title": "Onboarding", "page_id": "p1", "page_url": "http://x/p1"},
        {"page_title": "Onboarding", "page_id": "p1"},  # dup page
    ]

    class _FakeClient:
        async def search(self, **kwargs):
            if kwargs.get("top") == 0 and kwargs.get("include_total_count"):
                filt = kwargs.get("filter") or ""
                count = 3 if "report.pdf" in filt else 5
                return _FakeResults([], count=count)
            return _FakeResults(hits)

    p._search_client = _FakeClient()

    matches = await p.search_files("report", 25)
    assert len(matches) == 2
    # Sorted by chunk_count desc: the page (5) before the attachment (3).
    assert matches[0].kind == "page" and matches[0].key == "page_id"
    assert matches[0].value == "p1" and matches[0].label == "Onboarding"
    assert matches[0].chunk_count == 5
    assert matches[1].kind == "attachment" and matches[1].value == "report.pdf"
    assert matches[1].chunk_count == 3


@pytest.mark.asyncio
async def test_search_files_returns_empty_without_name_fields():
    # No filename/title field to search → empty, no error.
    p = _azure_provider({"id": ("Edm.String", True), "chunk_text": ("Edm.String", False)})
    assert await p.search_files("anything", 25) == []


# ── Route-level tests (fake provider via build_index_provider) ───────────────


class _FakeProvider(BaseIndexProvider):
    async def test_connection(self):
        return 42

    async def list_partition_keys(self):
        from app.index_providers.base import PartitionKey

        return [PartitionKey(key="content_type", label="content_type")]

    async def get_partition_distribution(self, key, filters=None):
        return [PartitionValue(value="pdf", doc_count=10), PartitionValue(value="html", doc_count=4)]

    async def sample_documents(self, key, value, n, filters=None):
        return []

    async def search_files(self, query, limit):
        return [
            FileMatch(
                key="attachment_filename", value="r.pdf", label="r.pdf",
                kind="attachment", chunk_count=3, url="http://x/r.pdf",
            )
        ]

    async def list_file_chunks(self, key, value, kind, limit):
        return [
            CorpusDoc(id="c0", title="r.pdf", url=None, snippet="first", ordinal=0),
            CorpusDoc(id="c1", title="r.pdf", url=None, snippet="second", ordinal=1),
        ]

    async def aclose(self):
        pass


@pytest_asyncio.fixture
async def index_provider(db_session, test_project) -> IndexProvider:
    prov = IndexProvider(
        id=uuid4(),
        project_id=test_project.id,
        type=IndexProviderType.azure_search,
        name="Test Index",
        config={"index_name": "idx"},
        api_key=b"fake-encrypted-key",
        base_url="https://x.search.windows.net",
    )
    db_session.add(prov)
    await db_session.commit()
    await db_session.refresh(prov)
    return prov


@pytest.fixture(autouse=True)
def _patch_provider(monkeypatch):
    monkeypatch.setattr(
        "app.routers.index_explorer.build_index_provider", lambda provider: _FakeProvider()
    )


@pytest.mark.asyncio
async def test_file_types_route(client, auth_headers, index_provider):
    r = await client.get(
        f"/api/index-explorer/file-types?provider_id={index_provider.id}", headers=auth_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["field"] == "content_type"
    assert body["values"] == [
        {"value": "pdf", "count": 10},
        {"value": "html", "count": 4},
    ]


@pytest.mark.asyncio
async def test_files_route(client, auth_headers, index_provider):
    r = await client.get(
        f"/api/index-explorer/files?provider_id={index_provider.id}&q=report",
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["kind"] == "attachment" and data[0]["value"] == "r.pdf"
    assert data[0]["chunk_count"] == 3


@pytest.mark.asyncio
async def test_file_chunks_route(client, auth_headers, index_provider):
    r = await client.get(
        f"/api/index-explorer/file-chunks?provider_id={index_provider.id}"
        "&file_key=attachment_filename&file_value=r.pdf&kind=attachment&label=r.pdf",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "r.pdf"
    assert body["ordinal_available"] is True
    assert [c["index"] for c in body["documents"]] == [0, 1]
    assert [c["ordinal"] for c in body["documents"]] == ["0", "1"]
