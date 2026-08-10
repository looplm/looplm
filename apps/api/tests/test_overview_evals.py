"""Tests for the evals section of GET /api/overview/summary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.models import EvalResult, EvalRun, TestCase, TestDataset

W1 = datetime(2025, 1, 6, 12, 0, tzinfo=timezone.utc)   # week 2025-01-06
W2 = datetime(2025, 1, 14, 12, 0, tzinfo=timezone.utc)  # week 2025-01-13

RANGE = {"start_date": "2025-01-06T00:00:00+00:00", "end_date": "2025-01-19T00:00:00+00:00"}


@pytest.fixture
def headers(auth_headers, test_project):
    return {**auth_headers, "X-Project-Id": str(test_project.id)}


def _run(project_id, name, created_at, total, passed, run_metadata=None, source="triggered"):
    return EvalRun(
        id=uuid4(), project_id=project_id, name=name, source=source, tags=[],
        total=total, passed=passed, failed=total - passed, grader_summary={},
        score_summary={}, run_metadata=run_metadata or {}, created_at=created_at,
    )


def _result(run_id, test_id, passed=True, execution_status="ok"):
    return EvalResult(
        id=uuid4(), run_id=run_id, test_id=test_id, pass_=passed, tags=[],
        graders={}, scores={}, result_metadata={}, execution_status=execution_status,
    )


@pytest_asyncio.fixture
async def seeded(db_session, test_project):
    """Two scoring runs, one empty run, one rerun. Three cases, one needs_work."""
    ds = TestDataset(id=uuid4(), project_id=test_project.id, name="DS")
    db_session.add(ds)
    await db_session.flush()
    db_session.add_all([
        TestCase(id=uuid4(), dataset_id=ds.id, test_id="case-a", prompt="p", status="active"),
        TestCase(id=uuid4(), dataset_id=ds.id, test_id="case-b", prompt="p", status="active"),
        # Excluded from the runnable suite, so it must not appear in the denominator.
        TestCase(id=uuid4(), dataset_id=ds.id, test_id="case-c", prompt="p", status="needs_work"),
    ])

    run1 = _run(test_project.id, "Eval 1", W1, total=10, passed=9)
    run2 = _run(test_project.id, "Eval 2", W2, total=10, passed=8)
    # Aborted run: including it would drag its bucket toward 0%.
    empty = _run(test_project.id, "Aborted", W2 + timedelta(hours=1), total=0, passed=0)
    db_session.add_all([run1, run2, empty])
    await db_session.flush()
    rerun = _run(
        test_project.id, "Rerun", W2 + timedelta(hours=2), total=4, passed=4,
        run_metadata={"rerun_of": str(run2.id)},
    )
    db_session.add(rerun)
    await db_session.flush()

    db_session.add_all([
        # Both filter-mode variants of one case: must collapse to a single case.
        _result(run1.id, "case-a [filtered]"),
        _result(run1.id, "case-a [unfiltered]"),
        # Non-ok rows are the dead-letter queue and are not "evaluated".
        _result(run1.id, "case-b", execution_status="degraded"),
    ])
    await db_session.commit()
    return run1, run2, empty, rerun


@pytest.mark.asyncio
async def test_pass_rate_is_case_weighted_per_bucket(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    assert r.status_code == 200, r.text
    points = {p["bucket"]: p for p in r.json()["evals"]["points"]}

    assert points["2025-01-06"]["pass_rate"] == 0.9
    # Week 2 holds run2 (8/10) and the rerun (4/4): 12/14 weighted.
    assert points["2025-01-13"]["cases"] == 14
    assert points["2025-01-13"]["pass_rate"] == round(12 / 14, 4)


@pytest.mark.asyncio
async def test_unweighted_rate_is_also_reported(client, headers, seeded):
    """A 5-case run and a 500-case run should be comparable both ways."""
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    points = {p["bucket"]: p for p in r.json()["evals"]["points"]}
    # Mean of 0.8 and 1.0 rather than the case-weighted 12/14.
    assert points["2025-01-13"]["unweighted_pass_rate"] == 0.9


@pytest.mark.asyncio
async def test_zero_case_runs_are_excluded_and_counted(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    evals = r.json()["evals"]
    assert evals["runs_excluded_no_cases"] == 1
    assert evals["runs"] == 3  # run1, run2, rerun


@pytest.mark.asyncio
async def test_buckets_without_runs_are_null_not_zero(client, headers, db_session, test_project):
    """A quiet week is a gap in the line, not a collapse to 0% pass rate."""
    db_session.add(_run(test_project.id, "Only", W1, total=10, passed=9))
    await db_session.commit()
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    points = {p["bucket"]: p for p in r.json()["evals"]["points"]}
    assert points["2025-01-06"]["pass_rate"] == 0.9
    assert points["2025-01-13"]["pass_rate"] is None
    assert points["2025-01-13"]["run_count"] == 0


@pytest.mark.asyncio
async def test_reruns_can_be_excluded(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary",
        params={"bucket": "week", "include_reruns": "false", **RANGE},
        headers=headers,
    )
    points = {p["bucket"]: p for p in r.json()["evals"]["points"]}
    assert points["2025-01-13"]["cases"] == 10  # the 4-case rerun is gone
    assert points["2025-01-13"]["pass_rate"] == 0.8


@pytest.mark.asyncio
async def test_current_pass_rate_comes_from_the_newest_scoring_run(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    evals = r.json()["evals"]
    # The rerun is newest and has cases, so it is the headline. The aborted run is skipped.
    assert evals["current_pass_rate"] == 1.0
    assert evals["latest_run"]["name"] == "Rerun"
    assert evals["window_pass_rate"] == round(21 / 24, 4)


@pytest.mark.asyncio
async def test_progress_normalizes_variant_suffixes(client, headers, seeded):
    """case-a ran as [filtered] and [unfiltered]; that is one evaluated case, not two."""
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    progress = r.json()["evals"]["progress"]
    assert progress["total"] == 2          # case-a, case-b; case-c is needs_work
    assert progress["evaluated"] == 1      # only case-a has an ok result
    assert progress["never_evaluated"] == 1
    assert progress["evaluated_unknown"] == 0
    assert progress["progress_rate"] == 0.5


@pytest.mark.asyncio
async def test_progress_never_exceeds_the_denominator(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    progress = r.json()["evals"]["progress"]
    assert progress["evaluated"] <= progress["total"]


@pytest.mark.asyncio
async def test_progress_is_all_time_not_window_scoped(client, headers, seeded):
    """Narrowing the date range must not shrink dataset coverage.

    Pass rate is a property of the window; progress is a property of the suite. Mixing
    the two would make a narrower range look like a regression.
    """
    wide = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    narrow = await client.get(
        "/api/overview/summary",
        params={"bucket": "day", "start_date": "2025-01-18T00:00:00+00:00",
                "end_date": "2025-01-19T00:00:00+00:00"},
        headers=headers,
    )
    assert narrow.json()["evals"]["progress"] == wide.json()["evals"]["progress"]
    # But the window pass rate does react to the range.
    assert narrow.json()["evals"]["window_pass_rate"] is None


@pytest.mark.asyncio
async def test_source_filter(client, headers, db_session, test_project):
    db_session.add_all([
        _run(test_project.id, "Triggered", W1, total=10, passed=9, source="triggered"),
        _run(test_project.id, "Legacy", W1, total=10, passed=2, source="legacy-eval-import"),
    ])
    await db_session.commit()
    r = await client.get(
        "/api/overview/summary",
        params={"bucket": "week", "sources": "triggered", **RANGE},
        headers=headers,
    )
    assert r.json()["evals"]["window_pass_rate"] == 0.9


@pytest.mark.asyncio
async def test_pass_rate_kpi_and_previous_window(client, headers, db_session, test_project, seeded):
    # A run in the preceding window gives the delta a baseline.
    db_session.add(
        _run(test_project.id, "Earlier", datetime(2024, 12, 30, tzinfo=timezone.utc),
             total=10, passed=5)
    )
    await db_session.commit()
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    kpi = next(k for k in r.json()["kpis"] if k["key"] == "eval_pass_rate")
    assert kpi["value"] == 1.0
    assert kpi["previous"] == 0.5
    assert kpi["change_pct"] == 1.0
    assert kpi["sub"] == "1 of 2 cases evaluated"


@pytest.mark.asyncio
async def test_no_runs_yields_nulls_not_zeros(client, headers):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    evals = r.json()["evals"]
    assert evals["current_pass_rate"] is None
    assert evals["window_pass_rate"] is None
    assert evals["latest_run"] is None
    assert evals["progress"]["total"] == 0
