"""Tests for the Data Sources "Fields" tab: index field-schema extraction
(attributes + example values + fill rate) and the /field-schema route."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from app.index_providers.base import BaseIndexProvider, FieldSchema
from app.models.base import IndexProviderType
from app.models.index_providers import IndexProvider


# ── Provider-level: real Azure extraction logic over a stubbed search client ──


class _FakeResults:
    def __init__(self, docs):
        self._docs = docs

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d

        return gen()

    async def get_facets(self):
        # No facet buckets → sample_corpus falls back to a flat paged scan.
        return {}


def _azure_provider(fields):
    """An AzureSearchIndexProvider with a stubbed schema.

    ``fields`` maps name -> (edm_type, is_key, facetable).
    """
    from app.index_providers.azure_search import AzureSearchIndexProvider, _FieldInfo

    p = AzureSearchIndexProvider(
        endpoint="https://x.search.windows.net", api_key="k", index_name="idx"
    )
    p._fields = {
        name: _FieldInfo(name, edm, facetable, is_key, searchable=not is_key)
        for name, (edm, is_key, facetable) in fields.items()
    }
    return p


@pytest.mark.asyncio
async def test_get_field_schema_examples_fill_rate_and_vectors():
    p = _azure_provider(
        {
            "id": ("Edm.String", True, False),
            "source_type": ("Edm.String", False, True),
            "page_url": ("Edm.String", False, False),
            "tags": ("Collection(Edm.String)", False, True),
            "embedding": ("Collection(Edm.Single)", False, False),
        }
    )

    sample = [
        {"id": "c0", "source_type": "page", "page_url": "https://a", "tags": ["x", "y"],
         "embedding": [0.1] * 10},
        {"id": "c1", "source_type": "page", "page_url": "", "tags": [],
         "embedding": [0.2] * 10},
        {"id": "c2", "source_type": "attachment", "tags": ["x"], "embedding": [0.3] * 10},
    ]

    class _FakeClient:
        async def search(self, **kwargs):
            return _FakeResults(sample if kwargs.get("skip", 0) == 0 else [])

    p._search_client = _FakeClient()

    fields = await p.get_field_schema(sample_size=10)
    by_name = {f.name: f for f in fields}

    # Schema order preserved.
    assert [f.name for f in fields] == ["id", "source_type", "page_url", "tags", "embedding"]

    src = by_name["source_type"]
    assert src.fill_rate == 1.0
    assert src.facetable is True and src.searchable is True
    assert src.example_values == ["page", "attachment"]  # distinct, in first-seen order

    url = by_name["page_url"]
    assert url.fill_rate == round(1 / 3, 3)  # empty string + missing key don't count
    assert url.example_values == ["https://a"]

    tags = by_name["tags"]
    assert tags.is_collection is True
    assert tags.fill_rate == round(2 / 3, 3)  # empty list doesn't count
    assert tags.example_values == ["x", "y"]  # flattened, deduped across docs

    emb = by_name["embedding"]
    assert emb.is_vector is True
    assert emb.fill_rate == 1.0
    assert emb.example_values == []  # vectors never surfaced as examples

    assert by_name["id"].is_key is True


@pytest.mark.asyncio
async def test_get_field_schema_survives_sampling_failure():
    p = _azure_provider({"id": ("Edm.String", True, False), "title": ("Edm.String", False, True)})

    class _BoomClient:
        async def search(self, **kwargs):
            raise RuntimeError("boom")

    p._search_client = _BoomClient()

    fields = await p.get_field_schema(sample_size=10)
    assert [f.name for f in fields] == ["id", "title"]
    assert all(f.fill_rate == 0.0 and f.example_values == [] for f in fields)


@pytest.mark.asyncio
async def test_get_field_schema_truncates_long_examples():
    p = _azure_provider({"id": ("Edm.String", True, False), "body": ("Edm.String", False, False)})
    long_text = "z" * 500
    sample = [{"id": "c0", "body": long_text}]

    class _FakeClient:
        async def search(self, **kwargs):
            return _FakeResults(sample if kwargs.get("skip", 0) == 0 else [])

    p._search_client = _FakeClient()

    fields = {f.name: f for f in await p.get_field_schema(sample_size=5)}
    example = fields["body"].example_values[0]
    assert example.endswith("…") and len(example) < len(long_text)


# ── Route-level: fake provider via build_index_provider ──────────────────────


class _FakeProvider(BaseIndexProvider):
    async def test_connection(self):
        return 3

    async def list_partition_keys(self):
        return []

    async def get_partition_distribution(self, key, filters=None):
        return []

    async def sample_documents(self, key, value, n, filters=None):
        return []

    async def get_field_schema(self, *, sample_size=50):
        return [
            FieldSchema(
                name="chunk_text", type="Edm.String", searchable=True,
                example_values=["hello world"], fill_rate=1.0,
            ),
            FieldSchema(
                name="page_url", type="Edm.String", retrievable=True,
                example_values=["https://x/p"], fill_rate=0.5,
            ),
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
async def test_field_schema_route(client, auth_headers, index_provider):
    r = await client.get(
        f"/api/index-explorer/field-schema?provider_id={index_provider.id}", headers=auth_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sample_size"] == 50
    names = [f["name"] for f in body["fields"]]
    assert names == ["chunk_text", "page_url"]
    assert body["fields"][0]["searchable"] is True
    assert body["fields"][0]["example_values"] == ["hello world"]
    assert body["fields"][1]["fill_rate"] == 0.5
