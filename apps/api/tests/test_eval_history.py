"""Tests for GET /api/evals/test-case-history (cross-run failure aggregation)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.models import EvalResult, EvalRun, TestCase, TestDataset

BASE_TIME = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_run(project_id, name, created_at, run_metadata=None):
    return EvalRun(
        id=uuid4(), project_id=project_id, name=name, source="triggered",
        tags=[], total=0, passed=0, failed=0, grader_summary={}, score_summary={},
        run_metadata=run_metadata or {}, created_at=created_at,
    )


def _make_result(run_id, test_id, passed, meta=None):
    return EvalResult(
        id=uuid4(), run_id=run_id, test_id=test_id, pass_=passed,
        tags=[], graders={}, scores={}, result_metadata=meta or {},
    )


@pytest_asyncio.fixture
async def history_setup(db_session, test_project):
    """3 runs (oldest → newest: run1, run2, rerun of run2) over 2 datasets.

    - case-x: fails in run1 and run2 (faithfulness/retrieval), passes in the rerun
    - case-y: passes everywhere; run1 has both-mode suffixed variants, one failed
      → counts as a failure for that run after merging
    - case-z: only in run2, fails, no classification metadata
    """
    ds1 = TestDataset(id=uuid4(), project_id=test_project.id, name="DS1")
    ds2 = TestDataset(id=uuid4(), project_id=test_project.id, name="DS2")
    db_session.add_all([ds1, ds2])
    await db_session.flush()

    db_session.add_all([
        TestCase(id=uuid4(), dataset_id=ds1.id, test_id="case-x", prompt="p", status="active"),
        TestCase(id=uuid4(), dataset_id=ds1.id, test_id="case-y", prompt="p", status="active"),
        TestCase(id=uuid4(), dataset_id=ds2.id, test_id="case-z", prompt="p", status="needs_work"),
    ])

    run1 = _make_run(test_project.id, "Eval: All", BASE_TIME)
    run2 = _make_run(test_project.id, "Eval: All", BASE_TIME + timedelta(hours=1))
    db_session.add_all([run1, run2])
    await db_session.flush()
    rerun = _make_run(
        test_project.id, "Rerun (failed): Eval: All", BASE_TIME + timedelta(hours=2),
        run_metadata={"rerun_of": str(run2.id)},
    )
    db_session.add(rerun)
    await db_session.flush()

    fail_meta = {"failure_pattern": "faithfulness", "root_cause": {"category": "retrieval"}}
    db_session.add_all([
        # run1
        _make_result(run1.id, "case-x", False, fail_meta),
        _make_result(run1.id, "case-y [filtered]", False, {"failure_pattern": "sourceRetrieval"}),
        _make_result(run1.id, "case-y [unfiltered]", True),
        # run2
        _make_result(run2.id, "case-x", False, fail_meta),
        _make_result(run2.id, "case-y", True),
        _make_result(run2.id, "case-z", False),
        # rerun (subset: only case-x)
        _make_result(rerun.id, "case-x", True),
    ])
    await db_session.commit()

    return {"ds1": ds1, "ds2": ds2, "run1": run1, "run2": run2, "rerun": rerun}


def _by_test_id(body):
    return {item["test_id"]: item for item in body["data"]}


@pytest.mark.asyncio
async def test_history_aggregates_across_runs(client, auth_headers, history_setup):
    resp = await client.get("/api/evals/test-case-history", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["runs_considered"] == 3
    items = _by_test_id(body)

    x = items["case-x"]
    assert x["runs_participated"] == 3  # presence-based: run1, run2, rerun
    assert x["fail_count"] == 2
    assert x["pass_count"] == 1
    assert x["dominant_failure_pattern"] == "faithfulness"
    assert x["dominant_failure_pattern_count"] == 2
    assert x["dominant_root_cause"] == "retrieval"
    assert x["last_failed_run_id"] == str(history_setup["run2"].id)
    assert x["exists"] is True
    assert x["case_status"] == "active"
    # Trend is newest-first; the rerun point is flagged
    assert [p["passed"] for p in x["trend"]] == [True, False, False]
    assert x["trend"][0]["is_rerun"] is True

    y = items["case-y"]
    # Suffixed variants merge into one entry; run1 counts as failed (any variant failed)
    assert "case-y [filtered]" not in items
    assert y["runs_participated"] == 2
    assert y["fail_count"] == 1
    assert y["dominant_failure_pattern"] == "sourceRetrieval"

    z = items["case-z"]
    assert z["runs_participated"] == 1
    assert z["fail_count"] == 1
    assert z["unclassified_failures"] == 1
    assert z["dominant_failure_pattern"] is None
    assert z["case_status"] == "needs_work"


@pytest.mark.asyncio
async def test_history_exclude_reruns(client, auth_headers, history_setup):
    resp = await client.get("/api/evals/test-case-history?include_reruns=false", headers=auth_headers)
    body = resp.json()
    assert body["runs_considered"] == 2
    x = _by_test_id(body)["case-x"]
    assert x["runs_participated"] == 2
    assert x["fail_count"] == 2
    assert x["pass_count"] == 0


@pytest.mark.asyncio
async def test_history_dataset_filter(client, auth_headers, history_setup):
    ds2 = history_setup["ds2"]
    resp = await client.get(f"/api/evals/test-case-history?dataset_id={ds2.id}", headers=auth_headers)
    items = _by_test_id(resp.json())
    assert set(items.keys()) == {"case-z"}


@pytest.mark.asyncio
async def test_history_min_failures_filter(client, auth_headers, history_setup):
    resp = await client.get("/api/evals/test-case-history?min_failures=2", headers=auth_headers)
    items = _by_test_id(resp.json())
    assert set(items.keys()) == {"case-x"}


@pytest.mark.asyncio
async def test_history_run_limit_window(client, auth_headers, history_setup):
    # Only the 2 newest runs (run2 + rerun) are in the window
    resp = await client.get("/api/evals/test-case-history?run_limit=2", headers=auth_headers)
    body = resp.json()
    assert body["runs_considered"] == 2
    items = _by_test_id(body)
    assert items["case-x"]["runs_participated"] == 2
    # case-y's failure was in run1, outside the window
    assert items["case-y"]["fail_count"] == 0


@pytest.mark.asyncio
async def test_history_deleted_case_flagged(client, auth_headers, history_setup, db_session):
    from sqlalchemy import delete
    await db_session.execute(delete(TestCase).where(TestCase.test_id == "case-x"))
    await db_session.commit()

    resp = await client.get("/api/evals/test-case-history", headers=auth_headers)
    x = _by_test_id(resp.json())["case-x"]
    assert x["exists"] is False
    assert x["dataset_name"] is None


@pytest.mark.asyncio
async def test_history_empty_project(client, auth_headers, test_project):
    resp = await client.get("/api/evals/test-case-history", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["runs_considered"] == 0
