"""Tests for no-retrieval-expected (negative) test cases.

A case tagged with the reserved ``no-retrieval-expected`` tag intentionally has no relevant
documents. It must never receive retrieval ground truth (expected-URL sync, AI judge) and is
excluded from retrieval metrics.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.chunk_labels import ChunkRelevanceLabel
from app.models.datasets import NO_RETRIEVAL_TAG, TestCase, TestDataset, is_no_retrieval_expected
from app.models.evaluations import EvalResult, EvalRun
from app.services.retrieval_metrics_aggregate import (
    aggregate_run_retrieval_metrics,
    negative_test_ids,
)


def test_is_no_retrieval_expected():
    assert is_no_retrieval_expected([NO_RETRIEVAL_TAG]) is True
    assert is_no_retrieval_expected(["other", NO_RETRIEVAL_TAG]) is True
    assert is_no_retrieval_expected(["other"]) is False
    assert is_no_retrieval_expected([]) is False
    assert is_no_retrieval_expected(None) is False


async def _create_dataset_with_case(
    client,
    auth_headers,
    *,
    test_id: str = "case-1",
    tags: list[str] | None = None,
    expected_page_urls: list[str] | None = None,
) -> tuple[str, str]:
    resp = await client.post(
        "/api/datasets", headers=auth_headers, json={"name": "Negative Cases Dataset"}
    )
    assert resp.status_code == 201
    dataset_id = resp.json()["id"]

    body: dict = {"test_id": test_id, "prompt": "Wechsel den Filter auf MSB"}
    if tags is not None:
        body["tags"] = tags
    if expected_page_urls is not None:
        body["expected_page_urls"] = expected_page_urls
    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases", headers=auth_headers, json=body
    )
    assert resp.status_code == 201
    return dataset_id, resp.json()["id"]


async def _add_relevant_label(db_session, project, user, *, test_id: str):
    db_session.add(
        ChunkRelevanceLabel(
            project_id=project.id,
            test_id=test_id,
            chunk_id="c1",
            relevance=3,
            url="https://a.example/looks-relevant",
            labeled_by=user.id,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_patch_sets_flag_and_clears_expected_urls(client: AsyncClient, auth_headers):
    dataset_id, case_id = await _create_dataset_with_case(
        client, auth_headers, expected_page_urls=["https://stale.example/bogus"]
    )

    resp = await client.patch(
        f"/api/datasets/{dataset_id}/cases/{case_id}",
        headers=auth_headers,
        json={"tags": [NO_RETRIEVAL_TAG], "expected_page_urls": []},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tags"] == [NO_RETRIEVAL_TAG]
    assert data["expected_page_urls"] == []


@pytest.mark.asyncio
async def test_single_case_sync_rejects_flagged_case(
    client: AsyncClient, auth_headers, db_session, test_project, test_user
):
    """Even with relevant-labeled chunks, a flagged case is never synced (merge or replace)."""
    dataset_id, _ = await _create_dataset_with_case(
        client, auth_headers, tags=[NO_RETRIEVAL_TAG]
    )
    await _add_relevant_label(db_session, test_project, test_user, test_id="case-1")

    for mode in ("replace", "merge"):
        resp = await client.post(
            f"/api/datasets/{dataset_id}/cases/expected-urls/sync-from-labels",
            headers=auth_headers,
            json={"test_id": "case-1", "mode": mode},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"]["code"] == "NO_RETRIEVAL_EXPECTED"

    resp = await client.get(
        f"/api/datasets/{dataset_id}/cases/expected-urls",
        headers=auth_headers,
        params={"test_id": "case-1"},
    )
    assert resp.json()["expected_page_urls"] == []


@pytest.mark.asyncio
async def test_dataset_sync_reports_flagged_cases(
    client: AsyncClient, auth_headers, db_session, test_project, test_user
):
    dataset_id, _ = await _create_dataset_with_case(
        client, auth_headers, test_id="negative", tags=[NO_RETRIEVAL_TAG]
    )
    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases",
        headers=auth_headers,
        json={"test_id": "normal", "prompt": "What is X?"},
    )
    assert resp.status_code == 201
    for tid in ("negative", "normal"):
        await _add_relevant_label(db_session, test_project, test_user, test_id=tid)

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases/expected-urls/sync-from-labels",
        headers=auth_headers,
        json={"mode": "replace"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert [c["test_id"] for c in data["updated"]] == ["normal"]
    assert data["flagged"] == ["negative"]
    assert data["skipped"] == []

    resp = await client.get(
        f"/api/datasets/{dataset_id}/cases/expected-urls",
        headers=auth_headers,
        params={"test_id": "negative"},
    )
    assert resp.json()["expected_page_urls"] == []


@pytest.mark.asyncio
async def test_project_wide_sync_reports_flagged_cases(
    client: AsyncClient, auth_headers, db_session, test_project, test_user
):
    dataset_id, _ = await _create_dataset_with_case(
        client, auth_headers, test_id="negative", tags=[NO_RETRIEVAL_TAG]
    )
    await _add_relevant_label(db_session, test_project, test_user, test_id="negative")

    resp = await client.post(
        "/api/datasets/expected-urls/sync-from-labels",
        headers=auth_headers,
        json={"mode": "replace"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_flagged"] == 1
    assert data["total_updated"] == 0
    by_id = {d["dataset_id"]: d for d in data["datasets"]}
    assert by_id[dataset_id]["flagged"] == ["negative"]


@pytest.mark.asyncio
async def test_ai_judge_skips_flagged_case_without_labeling(
    client: AsyncClient, auth_headers, db_session, test_project
):
    from sqlalchemy import select

    dataset = TestDataset(id=uuid4(), project_id=test_project.id, name="set")
    db_session.add(dataset)
    db_session.add(
        TestCase(
            id=uuid4(),
            dataset_id=dataset.id,
            test_id="q1",
            prompt="Wechsel den Filter auf MSB",
            tags=[NO_RETRIEVAL_TAG],
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/pipeline/labeling/ai-judge", headers=auth_headers, json={"test_id": "q1"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["skipped_reason"] == NO_RETRIEVAL_TAG
    assert data["judged"] == 0 and data["grades"] == {}

    labels = (
        await db_session.execute(
            select(ChunkRelevanceLabel).where(ChunkRelevanceLabel.test_id == "q1")
        )
    ).scalars().all()
    assert labels == []


@pytest.mark.asyncio
async def test_negative_test_ids_by_dataset_and_project(
    client: AsyncClient, auth_headers, db_session, test_project
):
    dataset_id, _ = await _create_dataset_with_case(
        client, auth_headers, test_id="negative", tags=[NO_RETRIEVAL_TAG]
    )
    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases",
        headers=auth_headers,
        json={"test_id": "normal", "prompt": "What is X?"},
    )
    assert resp.status_code == 201

    from uuid import UUID

    by_dataset = await negative_test_ids(db_session, dataset_ids=[UUID(dataset_id)])
    assert by_dataset == {"negative"}
    by_project = await negative_test_ids(db_session, project_id=test_project.id)
    assert by_project == {"negative"}


def test_urls_aggregation_excludes_flagged_results():
    """A flagged case with stale ground-truth URLs is dropped from the run summary."""
    hit = "https://x.example/relevant"

    def _result(test_id):
        return EvalResult(
            id=uuid4(),
            run_id=uuid4(),
            test_id=test_id,
            pass_=True,
            input="q",
            graders={
                "contains_urls": {
                    "pass": True,
                    "details": {"found_urls": [hit], "missing_urls": [], "retrieved_urls": [hit]},
                }
            },
        )

    run = EvalRun(id=uuid4(), name="nightly-rag")
    results = [_result("normal"), _result("negative [filtered]")]
    out = aggregate_run_retrieval_metrics(run, results, exclude_test_ids={"negative"})
    assert out.negative_cases_excluded == 1
    assert out.total_cases == 1
    assert [c.test_id for c in out.cases] == ["normal"]
