"""Router tests for chunk-quality runs: cancel semantics and summary fields."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.chunk_quality import ChunkQualityRun


async def _make_run(db_session, project_id, status="running", results=None):
    run = ChunkQualityRun(
        project_id=project_id,
        provider_id=uuid4(),
        status=status,
        stage="standalone" if status == "running" else None,
        sample_size=100,
        results=results,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


@pytest.mark.asyncio
async def test_cancel_running_run(client: AsyncClient, auth_headers, db_session, test_project):
    run = await _make_run(db_session, test_project.id)
    resp = await client.post(f"/api/chunk-quality/runs/{run.id}/cancel", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    row = (
        await db_session.execute(select(ChunkQualityRun).where(ChunkQualityRun.id == run.id))
    ).scalar_one()
    await db_session.refresh(row)
    assert row.status == "cancelled"
    assert row.stage is None
    assert row.completed_at is not None


@pytest.mark.asyncio
async def test_cancel_finished_run_conflicts(
    client: AsyncClient, auth_headers, db_session, test_project
):
    run = await _make_run(db_session, test_project.id, status="completed")
    run.completed_at = datetime.now(timezone.utc)
    await db_session.commit()
    resp = await client.post(f"/api/chunk-quality/runs/{run.id}/cancel", headers=auth_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_unknown_run_404(client: AsyncClient, auth_headers):
    resp = await client.post(f"/api/chunk-quality/runs/{uuid4()}/cancel", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_summary_lifts_stage_and_headline(
    client: AsyncClient, auth_headers, db_session, test_project
):
    results = {
        "summary": {"score": 77, "critical": 0, "warn": 1, "info": 0},
        "families": {
            "boundary": {"available": True, "bad_end_pct": 12.5, "bad_start_pct": 3.0},
            "standalone": {"available": False, "reason": "not configured"},
        },
    }
    run = await _make_run(db_session, test_project.id, results=results)
    resp = await client.get(
        f"/api/chunk-quality/runs?provider_id={run.provider_id}", headers=auth_headers
    )
    assert resp.status_code == 200
    summary = resp.json()["data"][0]
    assert summary["stage"] == "standalone"
    assert summary["headline"]["boundary_bad_end_pct"] == 12.5
    # An unavailable family contributes no headline value.
    assert summary["headline"]["standalone_dependent_pct"] is None
