"""Saved retrieval-run history: create / list / detail / metadata / delete."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.base import IndexProviderType
from app.models.datasets import TestCase, TestDataset
from app.models.index_providers import IndexProvider


async def _seed(db_session, project, *, test_id="q1", prompt="how to X"):
    dataset = TestDataset(id=uuid4(), project_id=project.id, name="set")
    db_session.add(dataset)
    db_session.add(TestCase(id=uuid4(), dataset_id=dataset.id, test_id=test_id, prompt=prompt))
    db_session.add(
        IndexProvider(
            id=uuid4(),
            project_id=project.id,
            type=IndexProviderType.azure_search,
            name="idx",
            config={"index_name": "prod-index"},
            api_key=b"x",
            base_url="https://example.net",
        )
    )
    await db_session.commit()
    return dataset


def _stub_probe(monkeypatch):
    """Make the labels-metrics computation return a measurable result without a real index."""
    import app.services.retrieval_labels_metrics as labels_metrics

    class _FakeProvider:
        async def aclose(self):
            pass

    async def _fake_probe(provider, project_id, test_id, query, k, *, embedder=None, refresh=False):
        return ["c1", "c2"]

    monkeypatch.setattr(labels_metrics, "build_index_provider", lambda row: _FakeProvider())
    monkeypatch.setattr(labels_metrics, "cached_probe_chunk_ids", _fake_probe)


@pytest.mark.asyncio
async def test_create_list_get_patch_delete(
    client: AsyncClient, auth_headers, db_session, test_project, monkeypatch
):
    dataset = await _seed(db_session, test_project)
    await client.post(
        "/api/pipeline/labels",
        headers=auth_headers,
        json={"labels": [{"test_id": "q1", "chunk_id": "c1", "relevance": 2}]},
    )
    _stub_probe(monkeypatch)

    # Create a run.
    created = await client.post(
        "/api/pipeline/retrieval-runs",
        headers=auth_headers,
        json={"dataset_ids": [str(dataset.id)], "gold_source": "human", "name": "baseline"},
    )
    assert created.status_code == 200, created.text
    run = created.json()
    run_id = run["id"]
    assert run["name"] == "baseline"
    assert run["index_name"] == "prod-index"  # auto-captured
    assert run["dataset_names"] == ["set"]
    assert run["evaluated_cases"] == 1
    assert run["metrics"]["available"] is True

    # List shows the run with headline metrics.
    listed = await client.get("/api/pipeline/retrieval-runs", headers=auth_headers)
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert len(data) == 1 and data[0]["id"] == run_id
    assert data[0]["recall"] is not None

    # Patch metadata.
    patched = await client.patch(
        f"/api/pipeline/retrieval-runs/{run_id}",
        headers=auth_headers,
        json={"pipeline_version": "v2.3", "index_version": "2026-07-01", "notes": "after reindex"},
    )
    assert patched.status_code == 200
    assert patched.json()["pipeline_version"] == "v2.3"
    assert patched.json()["name"] == "baseline"  # unchanged

    # Detail carries the metric blob.
    detail = await client.get(f"/api/pipeline/retrieval-runs/{run_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["metrics"]["available"] is True

    # Delete.
    deleted = await client.delete(f"/api/pipeline/retrieval-runs/{run_id}", headers=auth_headers)
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    assert (await client.get("/api/pipeline/retrieval-runs", headers=auth_headers)).json()["data"] == []


@pytest.mark.asyncio
async def test_create_rejects_when_nothing_to_measure(
    client: AsyncClient, auth_headers, db_session, test_project
):
    # A dataset but no labels and no index provider → nothing to snapshot.
    dataset = TestDataset(id=uuid4(), project_id=test_project.id, name="empty")
    db_session.add(dataset)
    db_session.add(TestCase(id=uuid4(), dataset_id=dataset.id, test_id="q1", prompt="x"))
    await db_session.commit()

    resp = await client.post(
        "/api/pipeline/retrieval-runs",
        headers=auth_headers,
        json={"dataset_ids": [str(dataset.id)]},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "NOTHING_TO_MEASURE"


@pytest.mark.asyncio
async def test_get_missing_run_404(client: AsyncClient, auth_headers, test_project):
    resp = await client.get(f"/api/pipeline/retrieval-runs/{uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
