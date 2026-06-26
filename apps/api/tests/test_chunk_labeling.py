"""Tests for chunk-level labeling: view builder, label-based metrics, and endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.evaluations import EvalResult, EvalRun
from app.services.chunk_labeling import (
    build_labeling_view,
    build_pool_view,
    retrieved_chunk_ids,
)
from app.services.chunk_pool import PooledChunk, PoolResult
from app.services.retrieval_metrics_aggregate import (
    aggregate_run_retrieval_metrics_from_labels,
)


def test_build_pool_view_overlays_labels_and_provenance():
    pool = PoolResult(
        chunks=[
            PooledChunk(chunk_id="t1", title="T", provenance=["trace", "keyword"]),
            PooledChunk(chunk_id="v1", provenance=["vector"]),
        ],
        heads_ran=["trace", "keyword", "vector"],
        heads_failed={"hybrid": "no vector field"},
    )
    out = build_pool_view(
        "test-1",
        "what is X?",
        pool,
        provider_connected=True,
        labels_by_key={("test-1", "t1"): True},
        labeler_by_key={("test-1", "t1"): "tim"},
    )
    assert out.pool_size == 2
    assert out.heads_ran == ["trace", "keyword", "vector"]
    assert out.heads_failed == {"hybrid": "no vector field"}
    t1, v1 = out.chunks
    assert t1.provenance == ["trace", "keyword"]
    assert t1.relevant is True and t1.labeled_by == "tim"
    # An unjudged, index-only candidate carries no label.
    assert v1.provenance == ["vector"] and v1.relevant is None


def _run():
    return EvalRun(id=uuid4(), name="run-1")


def _result(test_id, chunks, input_text="q"):
    return EvalResult(
        id=uuid4(),
        run_id=uuid4(),
        test_id=test_id,
        pass_=True,
        input=input_text,
        graders={},
        result_metadata={"retrieved_chunks": chunks},
    )


CHUNKS = [
    {"chunk_id": "c1", "title": "A", "url": "https://x/p1", "score": 5.0, "content_preview": "aa"},
    {"chunk_id": "c2", "title": "B", "url": "https://x/p2", "score": 4.0, "content_preview": "bb"},
]


def test_retrieved_chunk_ids_in_rank_order():
    r = _result("t1", CHUNKS)
    assert retrieved_chunk_ids(r) == ["c1", "c2"]


def test_build_labeling_view_merges_labels_and_sorts_unfinished_first():
    results = [_result("done", CHUNKS), _result("todo", CHUNKS)]
    labels = {("done", "c1"): True, ("done", "c2"): False}
    view = build_labeling_view(results, labels)
    assert view.available is True
    assert view.labelable_cases == 2
    # Least-labeled case first.
    assert view.cases[0].test_id == "todo"
    assert view.cases[0].labeled_count == 0
    done = next(c for c in view.cases if c.test_id == "done")
    assert done.labeled_count == 2
    assert done.relevant_count == 1
    assert done.chunks[0].relevant is True
    assert done.chunks[1].relevant is False


def test_build_labeling_view_skips_cases_without_chunks():
    r = EvalResult(id=uuid4(), run_id=uuid4(), test_id="t", pass_=True, graders={}, result_metadata={})
    view = build_labeling_view([r], {})
    assert view.available is False
    assert view.total_cases == 1
    assert view.labelable_cases == 0


def test_build_labeling_view_dedupes_test_case_across_runs():
    # Same query captured by two runs (passed newest-first). One case, newest capture wins.
    newest = _result("q1", [{"chunk_id": "new", "content_preview": "n"}])
    oldest = _result("q1", CHUNKS)
    view = build_labeling_view([newest, oldest], {})
    assert view.total_cases == 1
    assert view.labelable_cases == 1
    assert [ch.chunk_id for ch in view.cases[0].chunks] == ["new"]


def test_label_based_pooled_metrics():
    results = [_result("t1", CHUNKS)]
    # c1 judged relevant for t1; c2 not labeled (so not relevant).
    relevant_by_test = {"t1": {"c1"}}
    out = aggregate_run_retrieval_metrics_from_labels(_run(), results, relevant_by_test)
    assert out.available is True
    assert out.evaluated_cases == 1
    # c1 relevant and retrieved at rank 1 → perfect recall + MRR.
    assert out.recall_at_k["10"] == 1.0
    assert out.mrr == 1.0
    # Precision@1: 1 relevant of top-1.
    assert out.precision_at_k["1"] == 1.0


def test_label_based_skips_unlabeled_cases():
    out = aggregate_run_retrieval_metrics_from_labels(_run(), [_result("t1", CHUNKS)], {})
    assert out.available is False


@pytest.mark.asyncio
async def test_labeling_endpoints_roundtrip(client: AsyncClient, auth_headers, db_session, test_project):
    # Seed a run + result with retrieved chunks.
    run = EvalRun(id=uuid4(), project_id=test_project.id, name="seeded")
    db_session.add(run)
    db_session.add(
        EvalResult(
            id=uuid4(), run_id=run.id, test_id="q1",
            pass_=True, input="how to X", graders={},
            result_metadata={"retrieved_chunks": CHUNKS},
        )
    )
    await db_session.commit()

    # Labeling view shows the chunks, unlabeled.
    resp = await client.get(f"/api/pipeline/labeling?run_id={run.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["cases"][0]["chunks"][0]["relevant"] is None

    # Save a label.
    save = await client.post(
        "/api/pipeline/labels",
        headers=auth_headers,
        json={"labels": [{"test_id": "q1", "chunk_id": "c1", "relevant": True}]},
    )
    assert save.status_code == 200
    assert save.json()["saved"] == 1

    # Label now shows up, and label-based metrics are measurable.
    resp2 = await client.get(f"/api/pipeline/labeling?run_id={run.id}", headers=auth_headers)
    c1 = next(c for c in resp2.json()["cases"][0]["chunks"] if c["chunk_id"] == "c1")
    assert c1["relevant"] is True

    # The labeler's display name is surfaced (local part of their email).
    assert c1["labeled_by"] == "test"
    case = resp2.json()["cases"][0]
    assert "test" in case["labelers"]
    assert case["complete"] is False

    metrics = await client.get(
        f"/api/pipeline/retrieval-metrics?run_id={run.id}&source=labels", headers=auth_headers
    )
    assert metrics.status_code == 200
    assert metrics.json()["available"] is True
    assert metrics.json()["mrr"] == 1.0

    # Mark the case complete; it persists into the labeling view.
    status = await client.put(
        "/api/pipeline/labeling/status",
        headers=auth_headers,
        json={"test_id": "q1", "complete": True},
    )
    assert status.status_code == 200
    resp3 = await client.get(f"/api/pipeline/labeling?run_id={run.id}", headers=auth_headers)
    assert resp3.json()["cases"][0]["complete"] is True


@pytest.mark.asyncio
async def test_chunk_metadata_without_provider(client: AsyncClient, auth_headers):
    # No index provider connected → graceful, no error.
    resp = await client.get("/api/pipeline/chunk-metadata?chunk_id=c1", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["provider_connected"] is False
    assert resp.json()["available"] is False
