"""Tests for the LLM field-documentation service + /field-docs routes
(Data Sources "Fields" tab). Output sanitization is pure Python; the LLM is
mocked so these run on the SQLite test stack."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from app.index_providers.base import BaseIndexProvider, FieldSchema
from app.models.base import IndexProviderType
from app.models.index_providers import IndexProvider
from app.services.analysis_llm import LlmUsageInfo
from app.services.index_field_docs import _no_em_dash, _parse, explain_fields

_VALID = ["page_url", "attachment_url", "source_type", "content_type", "chunk_index"]


def _usage() -> LlmUsageInfo:
    return LlmUsageInfo(
        input_tokens=10, output_tokens=20, total_tokens=30, cost_usd=0.0,
        cached_tokens=0, reasoning_tokens=0, duration_ms=5,
    )


def test_parse_clamps_names_and_dedupes_fields():
    raw = json.dumps(
        {
            "summary": "A chunked Confluence corpus.",
            "fields": [
                {"name": "page_url", "purpose": "URL of the source page."},
                {"name": "page_url", "purpose": "duplicate, dropped"},
                {"name": "ghost", "purpose": "hallucinated, dropped"},
                {"name": "source_type", "purpose": ""},  # blank purpose dropped
            ],
            "groups": [],
        }
    )
    docs = _parse(raw, _VALID)
    assert [f.name for f in docs.fields] == ["page_url"]
    assert docs.summary == "A chunked Confluence corpus."


def test_parse_groups_require_two_valid_fields():
    raw = json.dumps(
        {
            "fields": [],
            "groups": [
                {"title": "URLs", "field_names": ["page_url", "attachment_url"],
                 "distinction": "One is the page, the other the attachment."},
                {"title": "singleton", "field_names": ["page_url"], "distinction": "x"},
                {"title": "hallucinated", "field_names": ["ghost", "phantom"], "distinction": "y"},
                {"title": "no distinction", "field_names": ["source_type", "content_type"],
                 "distinction": ""},
            ],
        }
    )
    docs = _parse(raw, _VALID)
    assert len(docs.groups) == 1
    assert docs.groups[0].field_names == ["page_url", "attachment_url"]


def test_parse_accepts_legacy_fields_key_in_group():
    raw = json.dumps(
        {"groups": [{"title": "T", "fields": ["source_type", "content_type"],
                     "message": "they differ"}]}
    )
    docs = _parse(raw, _VALID)
    assert docs.groups[0].field_names == ["source_type", "content_type"]
    assert docs.groups[0].distinction == "they differ"


def test_parse_strips_em_dashes():
    raw = json.dumps(
        {
            "summary": "Corpus — of chunks.",
            "fields": [{"name": "page_url", "purpose": "The page URL — canonical."}],
            "groups": [{"title": "URLs — pair", "field_names": ["page_url", "attachment_url"],
                        "distinction": "page — vs — attachment"}],
        }
    )
    docs = _parse(raw, _VALID)
    assert "—" not in docs.summary
    assert "—" not in docs.fields[0].purpose
    assert "—" not in docs.groups[0].title
    assert "—" not in docs.groups[0].distinction


def test_parse_handles_non_json():
    docs = _parse("not json", _VALID)
    assert docs.fields == [] and docs.groups == []


def test_no_em_dash_replaces_with_comma():
    assert _no_em_dash("a — b") == "a, b"


class _SchemaProvider(BaseIndexProvider):
    async def test_connection(self):
        return 100

    async def list_partition_keys(self):
        return []

    async def get_partition_distribution(self, key, filters=None):
        return []

    async def sample_documents(self, key, value, n, filters=None):
        return []

    async def get_field_schema(self, *, sample_size=50):
        return [
            FieldSchema(name="page_url", type="Edm.String", retrievable=True,
                        example_values=["https://x/p"], fill_rate=0.6),
            FieldSchema(name="attachment_url", type="Edm.String", retrievable=True,
                        example_values=["https://x/a.pdf"], fill_rate=0.4),
        ]


@pytest.mark.asyncio
async def test_explain_fields_end_to_end(db_session, test_project):
    llm_json = json.dumps(
        {
            "summary": "Chunked pages and attachments.",
            "fields": [
                {"name": "page_url", "purpose": "Canonical URL of the source page."},
                {"name": "ghost", "purpose": "dropped"},
            ],
            "groups": [
                {"title": "URLs", "field_names": ["page_url", "attachment_url"],
                 "distinction": "page_url points at the page; attachment_url at a file."},
            ],
        }
    )
    with patch("app.services.analysis_llm.AnalysisLlmService") as MockLLM:
        instance = MockLLM.return_value
        instance.provider = "openai"
        instance.model = "gpt-test"
        instance.tracked_chat_completion = AsyncMock(return_value=(llm_json, _usage()))

        docs, model = await explain_fields(
            _SchemaProvider(), project_id=test_project.id, db=db_session
        )

    assert model == "gpt-test"
    assert [f.name for f in docs.fields] == ["page_url"]  # hallucinated dropped
    assert docs.groups[0].field_names == ["page_url", "attachment_url"]


# ── Route-level tests ────────────────────────────────────────────────────────


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
        "app.routers.index_explorer.build_index_provider", lambda provider: _SchemaProvider()
    )


@pytest.mark.asyncio
async def test_field_docs_get_empty_then_post_then_cached(client, auth_headers, index_provider):
    # Nothing cached yet.
    r = await client.get(
        f"/api/index-explorer/field-docs?provider_id={index_provider.id}", headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json()["docs"] is None

    llm_json = json.dumps(
        {
            "summary": "Pages and attachments.",
            "fields": [{"name": "page_url", "purpose": "The source page URL."}],
            "groups": [{"title": "URLs", "field_names": ["page_url", "attachment_url"],
                        "distinction": "page vs file"}],
        }
    )
    with patch("app.services.analysis_llm.AnalysisLlmService") as MockLLM:
        instance = MockLLM.return_value
        instance.provider = "openai"
        instance.model = "gpt-test"
        instance.tracked_chat_completion = AsyncMock(return_value=(llm_json, _usage()))

        r = await client.post(
            "/api/index-explorer/field-docs",
            json={"provider_id": str(index_provider.id)},
            headers=auth_headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "gpt-test"
    assert body["docs"]["fields"][0]["name"] == "page_url"
    assert body["docs"]["groups"][0]["field_names"] == ["page_url", "attachment_url"]
    assert body["generated_at"] is not None

    # Now it's cached and returned without an LLM call.
    r = await client.get(
        f"/api/index-explorer/field-docs?provider_id={index_provider.id}", headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json()["docs"]["fields"][0]["purpose"] == "The source page URL."
