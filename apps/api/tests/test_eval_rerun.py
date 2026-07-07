"""Tests for partial eval reruns (rerun failed / filtered / selected subsets)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from app.models.models import EvalJob, EvalJobStatus, EvalResult, EvalRun, TestCase, TestDataset


@pytest_asyncio.fixture
async def eval_setup(db_session, test_project):
    """Dataset with cases a/b/c (active) + d (needs_work), original run with
    a=pass, b=fail, c=fail, d=fail, and the job that produced the run."""
    test_project.settings = {"eval_target_endpoint": "https://target.example.com/chat"}
    db_session.add(test_project)

    dataset = TestDataset(id=uuid4(), project_id=test_project.id, name="DS1")
    db_session.add(dataset)
    await db_session.flush()

    cases = {}
    for tid, status in [("case-a", "active"), ("case-b", "active"), ("case-c", "active"), ("case-d", "needs_work")]:
        tc = TestCase(id=uuid4(), dataset_id=dataset.id, test_id=tid, prompt=f"prompt {tid}", status=status)
        db_session.add(tc)
        cases[tid] = tc

    run = EvalRun(
        id=uuid4(), project_id=test_project.id, name="Eval: DS1", source="triggered",
        tags=[], total=4, passed=1, failed=3, grader_summary={}, score_summary={}, run_metadata={},
    )
    db_session.add(run)
    await db_session.flush()

    for tid, passed, meta in [
        ("case-a", True, {}),
        ("case-b", False, {"failure_pattern": "faithfulness", "root_cause": {"category": "retrieval"}}),
        ("case-c", False, {"failure_pattern": "sourceRetrieval"}),
        ("case-d", False, {}),
    ]:
        db_session.add(EvalResult(
            id=uuid4(), run_id=run.id, test_id=tid, pass_=passed,
            tags=[], graders={}, scores={}, result_metadata=meta,
        ))

    job = EvalJob(
        id=uuid4(), project_id=test_project.id, test_suite="DS1",
        dataset_ids=[str(dataset.id)], status=EvalJobStatus.completed, run_id=run.id,
        config={"filter_mode": "as_configured", "concurrency": 2, "max_turns": 1, "use_batch": False},
    )
    db_session.add(job)
    await db_session.commit()

    return {"dataset": dataset, "cases": cases, "run": run, "job": job}


@pytest.fixture
def capture_background(monkeypatch):
    """Replace _run_eval_background at the rerun endpoint's import site with a
    capturing stub. Args are recorded synchronously at call time."""
    captured = {}

    def fake_background(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

        async def _noop():
            pass

        return _noop()

    monkeypatch.setattr("app.routers.eval_reports_router._run_eval_background", fake_background)
    return captured


@pytest.mark.asyncio
async def test_rerun_without_body_is_full_rerun(client, auth_headers, eval_setup, capture_background):
    resp = await client.post(f"/api/evals/{eval_setup['run'].id}/rerun", headers=auth_headers)
    assert resp.status_code == 202
    assert capture_background["kwargs"]["include_test_ids"] is None
    assert capture_background["kwargs"]["rerun_of"] is None


@pytest.mark.asyncio
async def test_rerun_scope_failed_resolves_failed_test_ids(client, auth_headers, eval_setup, capture_background):
    resp = await client.post(
        f"/api/evals/{eval_setup['run'].id}/rerun", headers=auth_headers, json={"scope": "failed"},
    )
    assert resp.status_code == 202
    # case-d failed too, but is needs_work and therefore not runnable
    assert capture_background["kwargs"]["include_test_ids"] == ["case-b", "case-c"]
    assert capture_background["kwargs"]["rerun_of"] == eval_setup["run"].id
    assert capture_background["kwargs"]["rerun_scope"] == "failed"
    assert capture_background["kwargs"]["rerun_source_name"] == "Eval: DS1"


@pytest.mark.asyncio
async def test_rerun_explicit_test_ids_are_normalized_and_deduped(
    client, auth_headers, eval_setup, capture_background, db_session,
):
    resp = await client.post(
        f"/api/evals/{eval_setup['run'].id}/rerun",
        headers=auth_headers,
        json={"test_ids": ["case-b [filtered]", "case-c", "case-c [unfiltered]"]},
    )
    assert resp.status_code == 202
    assert capture_background["kwargs"]["include_test_ids"] == ["case-b", "case-c"]

    job_id = resp.json()["job_id"]
    job = await db_session.get(EvalJob, UUID(job_id))
    assert job.config["include_test_ids"] == ["case-b", "case-c"]
    assert job.config["rerun_of"] == str(eval_setup["run"].id)
    assert job.config["rerun_scope"] == "selected"
    assert job.config["use_batch"] is False
    assert "(rerun: 2 selected)" in job.test_suite


@pytest.mark.asyncio
async def test_rerun_filtered_scope_label_is_recorded(client, auth_headers, eval_setup, capture_background):
    resp = await client.post(
        f"/api/evals/{eval_setup['run'].id}/rerun",
        headers=auth_headers,
        json={"test_ids": ["case-b"], "scope": "filtered"},
    )
    assert resp.status_code == 202
    assert capture_background["kwargs"]["rerun_scope"] == "filtered"


@pytest.mark.asyncio
async def test_rerun_dlq_scope_selects_only_degraded_and_errored(
    client, auth_headers, test_project, db_session, capture_background,
):
    """scope='dlq' reruns only execution-failed rows, not quality (pass=False) failures."""
    test_project.settings = {"eval_target_endpoint": "https://target.example.com/chat"}
    db_session.add(test_project)
    dataset = TestDataset(id=uuid4(), project_id=test_project.id, name="DSX")
    db_session.add(dataset)
    await db_session.flush()
    for tid in ["ok-pass", "quality-fail", "degraded-1", "error-1"]:
        db_session.add(TestCase(id=uuid4(), dataset_id=dataset.id, test_id=tid, prompt=tid, status="active"))

    run = EvalRun(
        id=uuid4(), project_id=test_project.id, name="Eval: DSX", source="triggered",
        tags=[], total=2, passed=1, failed=1, grader_summary={}, score_summary={}, run_metadata={},
    )
    db_session.add(run)
    await db_session.flush()

    for tid, passed, es in [
        ("ok-pass", True, "ok"),
        ("quality-fail", False, "ok"),   # a real quality failure — NOT in the DLQ
        ("degraded-1", False, "degraded"),
        ("error-1", False, "error"),
    ]:
        db_session.add(EvalResult(
            id=uuid4(), run_id=run.id, test_id=tid, pass_=passed,
            tags=[], graders={}, scores={}, result_metadata={}, execution_status=es,
        ))
    db_session.add(EvalJob(
        id=uuid4(), project_id=test_project.id, test_suite="DSX",
        dataset_ids=[str(dataset.id)], status=EvalJobStatus.completed, run_id=run.id,
        config={"filter_mode": "as_configured", "concurrency": 2, "max_turns": 1, "use_batch": False},
    ))
    await db_session.commit()

    resp = await client.post(f"/api/evals/{run.id}/rerun", headers=auth_headers, json={"scope": "dlq"})
    assert resp.status_code == 202
    assert capture_background["kwargs"]["include_test_ids"] == ["degraded-1", "error-1"]
    assert capture_background["kwargs"]["rerun_scope"] == "dlq"


@pytest.mark.asyncio
async def test_rerun_dlq_scope_400_when_no_dead_letters(client, auth_headers, eval_setup):
    """A run whose results all ran representatively ('ok') has an empty DLQ."""
    resp = await client.post(
        f"/api/evals/{eval_setup['run'].id}/rerun", headers=auth_headers, json={"scope": "dlq"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "NO_MATCHING_TEST_CASES"


@pytest.mark.asyncio
async def test_rerun_unknown_ids_returns_400(client, auth_headers, eval_setup, capture_background):
    resp = await client.post(
        f"/api/evals/{eval_setup['run'].id}/rerun",
        headers=auth_headers,
        json={"test_ids": ["deleted-case", "renamed-case"]},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "NO_MATCHING_TEST_CASES"
    assert "kwargs" not in capture_background  # no job spawned


@pytest.mark.asyncio
async def test_rerun_needs_work_only_returns_400(client, auth_headers, eval_setup, capture_background):
    resp = await client.post(
        f"/api/evals/{eval_setup['run'].id}/rerun",
        headers=auth_headers,
        json={"test_ids": ["case-d"]},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "NO_MATCHING_TEST_CASES"


@pytest.mark.asyncio
async def test_run_eval_with_include_test_ids_runs_subset(db_session, test_project, eval_setup, monkeypatch):
    """run_eval executes only the included cases and links the new run to the original."""
    from app.schemas.evaluations import EvalResultImport
    from app.services import eval_executor

    async def fake_evaluate(client, endpoint, request_template, response_path,
                            extra_headers, evaluators, llm, tc, **kwargs):
        return EvalResultImport(test_id=tc.test_id, **{"pass": True}), []

    monkeypatch.setattr(eval_executor, "_evaluate_single_test_case", fake_evaluate)

    job = EvalJob(
        id=uuid4(), project_id=test_project.id, test_suite="DS1",
        dataset_ids=[str(eval_setup["dataset"].id)], status=EvalJobStatus.pending,
        config={},
    )
    db_session.add(job)
    await db_session.commit()

    original_run = eval_setup["run"]
    await eval_executor.run_eval(
        job.id, test_project.id, [eval_setup["dataset"].id], 1, db_session,
        project_settings={"eval_target_endpoint": "https://target.example.com/chat"},
        include_test_ids=["case-b [filtered]"],
        rerun_of=original_run.id,
        rerun_scope="failed",
        rerun_source_name=original_run.name,
    )

    await db_session.refresh(job)
    assert job.status == EvalJobStatus.completed
    new_run = await db_session.get(EvalRun, job.run_id)
    assert new_run.id != original_run.id
    assert new_run.total == 1
    assert new_run.name == "Rerun (failed): Eval: DS1"
    assert new_run.run_metadata["rerun_of"] == str(original_run.id)
    assert new_run.run_metadata["rerun_scope"] == "failed"
    assert new_run.run_metadata["rerun_test_count"] == 1

    # Original run untouched
    await db_session.refresh(original_run)
    assert original_run.total == 4
    assert original_run.failed == 3


@pytest.mark.asyncio
async def test_rerun_links_round_trip(client, auth_headers, db_session, test_project, eval_setup):
    parent = eval_setup["run"]
    child = EvalRun(
        id=uuid4(), project_id=test_project.id, name="Rerun (failed): Eval: DS1",
        source="triggered", tags=[], total=2, passed=2, failed=0,
        grader_summary={}, score_summary={},
        run_metadata={"rerun_of": str(parent.id), "rerun_scope": "failed"},
    )
    db_session.add(child)
    await db_session.commit()

    resp = await client.get(f"/api/evals/{parent.id}", headers=auth_headers)
    assert resp.status_code == 200
    reruns = resp.json()["reruns"]
    assert [r["id"] for r in reruns] == [str(child.id)]
    assert resp.json()["rerun_of"] is None

    resp = await client.get(f"/api/evals/{child.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["rerun_of"]["id"] == str(parent.id)
    assert resp.json()["rerun_of"]["name"] == "Eval: DS1"
    assert resp.json()["reruns"] == []
