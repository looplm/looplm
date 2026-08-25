"""The eval label columns must be unbounded.

Triggering an eval over many datasets joins every dataset name into the job label
(and, downstream, into the run name). On Postgres those columns used to be
VARCHAR(255)/VARCHAR(512), so ~20 datasets overflowed and the trigger returned a
500. Tests run on SQLite, which ignores VARCHAR length, so the only check that
would have caught it is an assertion on the column definitions themselves.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.models.models import EvalJob, EvalRun, EvalSession, TestCase, TestDataset


@pytest.mark.parametrize(
    "model, column",
    [
        (EvalJob, "test_suite"),
        (EvalRun, "name"),
        (EvalSession, "name"),
    ],
)
def test_label_columns_are_unbounded(model, column):
    """A joined multi-dataset label has no useful upper bound, so these columns
    must be TEXT. `length is None` is what distinguishes Text from String(n)."""
    assert model.__table__.c[column].type.length is None


@pytest.fixture
def capture_background(monkeypatch):
    """Stub out the background runner so the trigger endpoint only exercises
    label building and the EvalJob insert."""
    captured = {}

    def fake_background(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

        async def _noop():
            pass

        return _noop()

    monkeypatch.setattr("app.routers.eval_jobs._run_eval_background", fake_background)
    return captured


@pytest.mark.asyncio
async def test_trigger_over_many_datasets_keeps_full_label(
    client, auth_headers, db_session, test_project, capture_background,
):
    test_project.settings = {"eval_target_endpoint": "https://target.example.com/chat"}
    db_session.add(test_project)

    # 25 datasets whose joined names run well past the old 255-char limit.
    names = [f"Dataset {i:02d} with a fairly long descriptive name" for i in range(25)]
    dataset_ids = []
    for name in names:
        ds = TestDataset(id=uuid4(), project_id=test_project.id, name=name)
        db_session.add(ds)
        await db_session.flush()
        db_session.add(
            TestCase(id=uuid4(), dataset_id=ds.id, test_id=f"{name}-case", prompt="hi", status="active")
        )
        dataset_ids.append(str(ds.id))
    await db_session.commit()

    resp = await client.post(
        "/api/evals/trigger",
        headers=auth_headers,
        json={"dataset_ids": dataset_ids, "filter_mode": "no_filters"},
    )
    assert resp.status_code == 202

    job = await db_session.get(EvalJob, UUID(resp.json()["job_id"]))
    assert len(job.test_suite) > 255
    for name in names:
        assert name in job.test_suite
    assert sorted(job.dataset_ids) == sorted(dataset_ids)
