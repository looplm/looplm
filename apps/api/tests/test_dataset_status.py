"""Tests for the test-case needs-work status (disable/re-enable flow)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.models import EvalJob, EvalJobStatus


async def _create_dataset_with_case(client, auth_headers, prompt: str = "What is X?") -> tuple[str, str]:
    """Helper: create a dataset with one test case, return (dataset_id, case_id)."""
    resp = await client.post(
        "/api/datasets",
        headers=auth_headers,
        json={"name": "Status Test Dataset"},
    )
    assert resp.status_code == 201
    dataset_id = resp.json()["id"]

    resp = await client.post(
        f"/api/datasets/{dataset_id}/cases",
        headers=auth_headers,
        json={"test_id": "case-1", "prompt": prompt},
    )
    assert resp.status_code == 201
    return dataset_id, resp.json()["id"]


@pytest.mark.asyncio
async def test_mark_needs_work_and_reactivate(client, auth_headers):
    dataset_id, case_id = await _create_dataset_with_case(client, auth_headers)

    # New cases start active
    resp = await client.get(f"/api/datasets/{dataset_id}", headers=auth_headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["test_cases"][0]["status"] == "active"
    assert detail["needs_work_count"] == 0

    # Mark as needs work with a note
    resp = await client.patch(
        f"/api/datasets/{dataset_id}/cases/{case_id}",
        headers=auth_headers,
        json={"status": "needs_work", "status_note": "expected answer outdated"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "needs_work"
    assert resp.json()["status_note"] == "expected answer outdated"

    # Detail and list both report the count
    detail = (await client.get(f"/api/datasets/{dataset_id}", headers=auth_headers)).json()
    assert detail["needs_work_count"] == 1
    assert detail["test_count"] == 1

    listing = (await client.get("/api/datasets", headers=auth_headers)).json()
    ds = next(d for d in listing["data"] if d["id"] == dataset_id)
    assert ds["needs_work_count"] == 1

    # Reactivate
    resp = await client.patch(
        f"/api/datasets/{dataset_id}/cases/{case_id}",
        headers=auth_headers,
        json={"status": "active", "status_note": None},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
    assert resp.json()["status_note"] is None

    detail = (await client.get(f"/api/datasets/{dataset_id}", headers=auth_headers)).json()
    assert detail["needs_work_count"] == 0


@pytest.mark.asyncio
async def test_invalid_status_rejected(client, auth_headers):
    dataset_id, case_id = await _create_dataset_with_case(client, auth_headers)

    resp = await client.patch(
        f"/api/datasets/{dataset_id}/cases/{case_id}",
        headers=auth_headers,
        json={"status": "bogus"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_export_import_round_trip_keeps_status(client, auth_headers):
    dataset_id, case_id = await _create_dataset_with_case(client, auth_headers)
    await client.patch(
        f"/api/datasets/{dataset_id}/cases/{case_id}",
        headers=auth_headers,
        json={"status": "needs_work", "status_note": "fix me"},
    )

    export = (await client.get(f"/api/datasets/{dataset_id}/export", headers=auth_headers)).json()
    assert export["testCases"][0]["status"] == "needs_work"
    assert export["testCases"][0]["statusNote"] == "fix me"

    resp = await client.post(
        "/api/datasets/import",
        headers=auth_headers,
        json={"name": "Reimported", "testCases": export["testCases"], "filename": "x.json"},
    )
    assert resp.status_code == 201
    reimported = resp.json()
    assert reimported["needs_work_count"] == 1

    detail = (await client.get(f"/api/datasets/{reimported['id']}", headers=auth_headers)).json()
    assert detail["test_cases"][0]["status"] == "needs_work"
    assert detail["test_cases"][0]["status_note"] == "fix me"


@pytest.mark.asyncio
async def test_run_eval_excludes_needs_work_cases(client, auth_headers, db_session, test_project):
    from app.services.eval_executor import run_eval

    dataset_id, case_id = await _create_dataset_with_case(client, auth_headers)
    await client.patch(
        f"/api/datasets/{dataset_id}/cases/{case_id}",
        headers=auth_headers,
        json={"status": "needs_work"},
    )

    job = EvalJob(project_id=test_project.id, test_suite="status-test")
    db_session.add(job)
    await db_session.flush()

    from uuid import UUID

    await run_eval(
        job_id=job.id,
        project_id=test_project.id,
        dataset_ids=[UUID(dataset_id)],
        concurrency=1,
        db=db_session,
        project_settings={"eval_target_endpoint": "http://localhost:1/unused"},
    )

    refreshed = (await db_session.execute(select(EvalJob).where(EvalJob.id == job.id))).scalar_one()
    assert refreshed.status == EvalJobStatus.failed
    assert "needs work" in (refreshed.error or "")
