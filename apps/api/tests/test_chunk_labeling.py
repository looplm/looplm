"""Tests for dataset-driven chunk labeling: view builder, probe-based metrics, and endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.base import IndexProviderType
from app.models.datasets import TestCase, TestDataset
from app.models.index_providers import IndexProvider
from app.services.chunk_labeling import (
    build_labeling_cases,
    build_labeling_view,
    build_pool_view,
    merge_labeling_view,
)
from app.services.chunk_pool import PooledChunk, PoolResult
from app.services.retrieval_metrics_aggregate import aggregate_retrieval_metrics_from_labels


def _tc(test_id, prompt):
    """A minimal stand-in for a TestCase row (build_labeling_cases reads .test_id / .prompt)."""
    return SimpleNamespace(test_id=test_id, prompt=prompt)


def test_build_pool_view_overlays_labels_and_provenance():
    pool = PoolResult(
        chunks=[
            PooledChunk(chunk_id="t1", title="T", provenance=["keyword"]),
            PooledChunk(chunk_id="v1", provenance=["vector"]),
        ],
        heads_ran=["keyword", "vector"],
        heads_failed={"hybrid": "no vector field"},
    )
    out = build_pool_view(
        "test-1",
        "what is X?",
        pool,
        provider_connected=True,
        labels_by_key={("test-1", "t1"): 2},
        labeler_by_key={("test-1", "t1"): "tim"},
        ai_labels_by_key={("test-1", "v1"): 1},
    )
    assert out.pool_size == 2
    assert out.heads_failed == {"hybrid": "no vector field"}
    t1, v1 = out.chunks
    assert t1.relevance == 2 and t1.labeled_by == "tim"
    # An unjudged candidate carries no human label, but may carry the AI judge's grade.
    assert v1.relevance is None and v1.ai_relevance == 1


def test_build_pool_view_orders_reranked_first():
    # Reranked first (by reranked rank), then hybrid, then vector, then keyword.
    pool = PoolResult(
        chunks=[
            PooledChunk(chunk_id="kw", provenance=["keyword"], ranks={"keyword": 1}),
            PooledChunk(chunk_id="rerank3", provenance=["hybrid", "semantic"], ranks={"hybrid": 2, "semantic": 3}),
            PooledChunk(chunk_id="hyb1", provenance=["hybrid", "vector"], ranks={"hybrid": 1, "vector": 5}),
            PooledChunk(chunk_id="rerank1", provenance=["semantic"], ranks={"semantic": 1}),
        ],
        heads_ran=["keyword", "vector", "hybrid", "semantic"],
        heads_failed={},
    )
    out = build_pool_view("t", "q", pool, provider_connected=True, labels_by_key={})
    assert [c.chunk_id for c in out.chunks] == ["rerank1", "rerank3", "hyb1", "kw"]


def test_build_labeling_cases_from_test_cases():
    cases, total = build_labeling_cases([_tc("a", "query a"), _tc("b", "query b")])
    assert total == 2
    assert [c.test_id for c in cases] == ["a", "b"]
    assert cases[0].input == "query a"
    # The skeleton carries no chunks (they're pooled per case) and no labels.
    assert cases[0].chunks == [] and cases[0].labeled_count == 0


def test_build_labeling_cases_dedupes_test_id():
    cases, total = build_labeling_cases([_tc("q1", "first"), _tc("q1", "dup")])
    assert total == 1 and len(cases) == 1 and cases[0].input == "first"


def test_merge_labeling_view_counts_labels_and_sorts_unfinished_first():
    cases, total = build_labeling_cases([_tc("done", "q"), _tc("todo", "q")])
    view = merge_labeling_view(
        cases,
        total,
        {("done", "c1"): 2, ("done", "c2"): 0},
        dataset_id="ds1",
        dataset_name="My set",
        complete_by_test={"done": False},
        labelers_by_test={"done": ["tim"]},
    )
    assert view.available is True and view.dataset_id == "ds1" and view.dataset_name == "My set"
    # Least-labeled case first.
    assert view.cases[0].test_id == "todo" and view.cases[0].labeled_count == 0
    done = next(c for c in view.cases if c.test_id == "done")
    assert done.labeled_count == 2
    assert done.relevant_count == 1  # grade 2 counts as relevant, grade 0 does not
    assert done.labelers == ["tim"]


def test_build_labeling_view_empty_without_cases():
    view = build_labeling_view([], {})
    assert view.available is False and view.labelable_cases == 0


def test_aggregate_metrics_from_labels_uses_probe_retrieved():
    # c1 judged relevant for t1; the probe returns c1 at rank 1 → perfect recall + MRR.
    out = aggregate_retrieval_metrics_from_labels(
        [("t1", "q")],
        {"t1": ["c1", "c2"]},
        {"t1": {"c1"}},
        dataset_id="ds1",
        dataset_name="set",
    )
    assert out.available is True and out.evaluated_cases == 1
    assert out.recall_at_k["10"] == 1.0
    assert out.mrr == 1.0
    assert out.precision_at_k["1"] == 1.0
    assert out.run_id == "ds1" and out.run_name == "set"


def test_aggregate_metrics_skips_unlabeled_cases():
    out = aggregate_retrieval_metrics_from_labels([("t1", "q")], {"t1": ["c1"]}, {})
    assert out.available is False


async def _seed_dataset(db_session, project, *, test_id="q1", prompt="how to X"):
    dataset = TestDataset(id=uuid4(), project_id=project.id, name="set")
    db_session.add(dataset)
    db_session.add(TestCase(id=uuid4(), dataset_id=dataset.id, test_id=test_id, prompt=prompt))
    await db_session.commit()
    return dataset


@pytest.mark.asyncio
async def test_labeling_endpoints_roundtrip(client: AsyncClient, auth_headers, db_session, test_project):
    dataset = await _seed_dataset(db_session, test_project)

    # The dataset's case shows up, unlabeled.
    resp = await client.get("/api/pipeline/labeling", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True and body["dataset_id"] == str(dataset.id)
    case = body["cases"][0]
    assert case["test_id"] == "q1" and case["labeled_count"] == 0

    # Grade a chunk (labels persist by test_id+chunk_id, independent of the pool).
    save = await client.post(
        "/api/pipeline/labels",
        headers=auth_headers,
        json={"labels": [{"test_id": "q1", "chunk_id": "c1", "relevance": 2}]},
    )
    assert save.status_code == 200 and save.json()["saved"] == 1

    resp2 = await client.get("/api/pipeline/labeling", headers=auth_headers)
    case2 = resp2.json()["cases"][0]
    assert case2["labeled_count"] == 1 and case2["relevant_count"] == 1
    assert "test" in case2["labelers"]

    # Mark complete; it persists into the labeling view.
    await client.put(
        "/api/pipeline/labeling/status", headers=auth_headers, json={"test_id": "q1", "complete": True}
    )
    resp3 = await client.get("/api/pipeline/labeling", headers=auth_headers)
    assert resp3.json()["cases"][0]["complete"] is True

    # Removing the label clears the count again (idempotent on repeat).
    deleted = await client.request(
        "DELETE", "/api/pipeline/labels?test_id=q1&chunk_id=c1", headers=auth_headers
    )
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    resp4 = await client.get("/api/pipeline/labeling", headers=auth_headers)
    assert resp4.json()["cases"][0]["labeled_count"] == 0


@pytest.mark.asyncio
async def test_ai_judge_stores_labels_under_ai_annotator(
    client: AsyncClient, auth_headers, db_session, test_project, monkeypatch
):
    import app.routers.chunk_labels.llm_ops as ops
    from app.services.analysis_llm import LlmUsageInfo

    await _seed_dataset(db_session, test_project)

    # A human grades c1; the AI judge will grade both pooled chunks.
    await client.post(
        "/api/pipeline/labels",
        headers=auth_headers,
        json={"labels": [{"test_id": "q1", "chunk_id": "c1", "relevance": 2}]},
    )

    class _FakeLlm:
        provider = "openai"
        model = "gpt-test"

        def __init__(self, *a, **k):
            pass

    async def _fake_pool(db, project, test_id, query, **kwargs):
        pool = PoolResult(
            chunks=[PooledChunk(chunk_id="c1"), PooledChunk(chunk_id="c2")],
            heads_ran=["keyword"],
            heads_failed={},
        )
        return pool, None, True

    async def _fake_judge(llm, query, chunks, *, instructions=None):
        return {"c1": 3, "c2": 0}, LlmUsageInfo(0, 0, 0, None, 0, 0, 0)

    monkeypatch.setattr(ops, "AnalysisLlmService", _FakeLlm)
    monkeypatch.setattr(ops, "assemble_case_pool", _fake_pool)
    monkeypatch.setattr(ops, "ai_judge_chunks", _fake_judge)

    judged = await client.post(
        "/api/pipeline/labeling/ai-judge", headers=auth_headers, json={"test_id": "q1"}
    )
    assert judged.status_code == 200
    assert judged.json()["judged"] == 2 and judged.json()["grades"] == {"c1": 3, "c2": 0}

    # The case lists the AI as an annotator; one human + the AI judge is enough for agreement.
    view = await client.get("/api/pipeline/labeling", headers=auth_headers)
    assert "AI" in view.json()["cases"][0]["labelers"]
    agreement = await client.get("/api/pipeline/labeling/agreement", headers=auth_headers)
    assert agreement.json()["available"] is True
    assert {a["name"] for a in agreement.json()["annotators"]} == {"test", "AI"}


@pytest.mark.asyncio
async def test_labels_metrics_use_live_probe(
    client: AsyncClient, auth_headers, db_session, test_project, monkeypatch
):
    import app.routers.retrieval as retrieval_router

    await _seed_dataset(db_session, test_project)
    await client.post(
        "/api/pipeline/labels",
        headers=auth_headers,
        json={"labels": [{"test_id": "q1", "chunk_id": "c1", "relevance": 2}]},
    )
    # An index provider must exist for the probe path to run.
    db_session.add(
        IndexProvider(
            id=uuid4(),
            project_id=test_project.id,
            type=IndexProviderType.azure_search,
            name="idx",
            config={"index_name": "i"},
            api_key=b"x",
            base_url="https://example.net",
        )
    )
    await db_session.commit()

    class _FakeProvider:
        async def aclose(self):
            pass

    async def _fake_probe(provider, project_id, test_id, query, k, *, embedder=None, refresh=False):
        return ["c1", "c2"]  # the system retrieves the relevant chunk at rank 1

    monkeypatch.setattr(retrieval_router, "build_index_provider", lambda row: _FakeProvider())
    monkeypatch.setattr(retrieval_router, "cached_probe_chunk_ids", _fake_probe)

    metrics = await client.get(
        "/api/pipeline/retrieval-metrics?source=labels", headers=auth_headers
    )
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["available"] is True
    assert body["recall_at_k"]["10"] == 1.0 and body["mrr"] == 1.0


@pytest.mark.asyncio
async def test_chunk_metadata_without_provider(client: AsyncClient, auth_headers):
    # No index provider connected → graceful, no error.
    resp = await client.get("/api/pipeline/chunk-metadata?chunk_id=c1", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["provider_connected"] is False
