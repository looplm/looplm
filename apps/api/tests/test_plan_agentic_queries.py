"""The by-stage compute can plan a case's agentic sub-queries, not just read them.

Without this the agentic stages are permanently dark for any dataset nobody opened in the
labeling workbench — which is every synthetic dataset, since the whole point of those is that
they need no human labeling. Planning is opt-in because it costs one LLM call per unplanned case.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.models.chunk_labels import GRADE_MAX, SYNTHETIC_ANNOTATOR, ChunkRelevanceLabel
from app.models.datasets import TestCase, TestDataset
from app.services import retrieval_labels_metrics as rlm
from app.services.retrieval_metrics_cache import result_cache_key


async def _dataset_with_gold(db, project_id, n=2):
    dataset = TestDataset(project_id=project_id, name="Synthetic set", tags=["synthetic"])
    db.add(dataset)
    await db.flush()
    for i in range(1, n + 1):
        test_id = f"syn-abcd1234-{i:04d}"
        db.add(TestCase(dataset_id=dataset.id, test_id=test_id, prompt=f"Frage {i}?"))
        db.add(
            ChunkRelevanceLabel(
                project_id=project_id,
                test_id=test_id,
                chunk_id=f"page_{i}_chunk_0",
                relevance=GRADE_MAX,
                annotator=SYNTHETIC_ANNOTATOR,
            )
        )
    await db.commit()
    await db.refresh(dataset)
    return dataset


@pytest.fixture
def case_sessions(db_session):
    """Hand the pooling fan-out the test session instead of letting it open real ones.

    Production gives each concurrent case its own session (an AsyncSession is not safe for
    concurrent use), which means a real engine; the SQLite test engine holds a single
    connection, so replaying the fixture session keeps these tests on it.
    """

    @asynccontextmanager
    async def factory():
        yield db_session

    return factory


@pytest.fixture
def stubbed_pool(monkeypatch):
    """Report the index as unconnected, so no live probe is needed to exercise the plan pass."""

    async def fake_pool(*args, **kwargs):
        return SimpleNamespace(chunks=[], heads_failed={}), False, False

    monkeypatch.setattr(rlm, "assemble_case_pool", fake_pool)


@pytest.fixture
def planned(monkeypatch):
    """Record every ensure_case_agentic_queries call instead of calling an LLM."""
    calls: list[str] = []

    async def fake_ensure(db, project, user, *, dataset_id, test_id, query):
        calls.append(test_id)
        return ["sub query a", "sub query b"]

    monkeypatch.setattr(rlm, "ensure_case_agentic_queries", fake_ensure)
    return calls


@pytest.mark.asyncio
async def test_plan_agentic_plans_every_case_with_gold(
    db_session, test_project, test_user, stubbed_pool, planned, case_sessions
):
    dataset = await _dataset_with_gold(db_session, test_project.id)
    await rlm.compute_by_stage_metrics(
        db_session,
        test_project,
        [dataset],
        "synthetic",
        refresh=True,
        plan_agentic=True,
        user=test_user,
        db_factory=case_sessions,
    )
    assert sorted(planned) == ["syn-abcd1234-0001", "syn-abcd1234-0002"]


@pytest.mark.asyncio
async def test_planning_is_opt_in(
    db_session, test_project, test_user, stubbed_pool, planned, case_sessions
):
    dataset = await _dataset_with_gold(db_session, test_project.id)
    await rlm.compute_by_stage_metrics(
        db_session,
        test_project,
        [dataset],
        "synthetic",
        refresh=True,
        user=test_user,
        db_factory=case_sessions,
    )
    # Default off: a metrics read must never quietly spend an LLM call per case.
    assert planned == []


@pytest.mark.asyncio
async def test_planning_needs_a_user(
    db_session, test_project, stubbed_pool, planned, case_sessions
):
    dataset = await _dataset_with_gold(db_session, test_project.id)
    await rlm.compute_by_stage_metrics(
        db_session,
        test_project,
        [dataset],
        "synthetic",
        refresh=True,
        plan_agentic=True,
        user=None,
        db_factory=case_sessions,
    )
    # No user means no LLM settings to plan with; skip rather than fail the whole compute.
    assert planned == []


@pytest.mark.asyncio
async def test_cases_without_gold_are_not_planned(
    db_session, test_project, test_user, stubbed_pool, planned, case_sessions
):
    dataset = await _dataset_with_gold(db_session, test_project.id, n=1)
    db_session.add(TestCase(dataset_id=dataset.id, test_id="syn-abcd1234-0099", prompt="Ungolded?"))
    await db_session.commit()
    await rlm.compute_by_stage_metrics(
        db_session,
        test_project,
        [dataset],
        "synthetic",
        refresh=True,
        plan_agentic=True,
        user=test_user,
        db_factory=case_sessions,
    )
    # The aggregator drops cases without gold anyway, so planning them is wasted spend.
    assert planned == ["syn-abcd1234-0001"]


def test_plan_agentic_is_not_part_of_the_cache_key(test_project):
    """Planning is an action, not a result dimension.

    Planned queries persist on the case, so once planned a run *without* the flag reads them and
    produces identical numbers. Keying on the flag would fragment the cache and make the panel's
    warm-cache read miss the very result its own compute job just stored.
    """
    from uuid import uuid4

    ds = [uuid4()]
    assert result_cache_key(test_project.id, "by-stage", ds, "synthetic", 1) == result_cache_key(
        test_project.id, "by-stage", ds, "synthetic", 1
    )
    # The flags that DO change which stages a result carries are keyed; plan_agentic is absent
    # from the signature entirely, which is what keeps the two paths sharing one entry.
    assert (
        result_cache_key(test_project.id, "by-stage", ds, "synthetic", 1, True)
        != result_cache_key(test_project.id, "by-stage", ds, "synthetic", 1, False)
    )


@pytest.mark.asyncio
async def test_pool_agent_head_failure_does_not_exclude_cases(
    db_session, test_project, test_user, monkeypatch, planned, case_sessions
):
    """The pool's "agent" head must not drive the metrics agent stage's exclusions.

    ``labeling_pool`` marks that head failed whenever its (shallower) agent fetch came back
    empty, including a genuinely empty ranking. The metrics agent stage is sourced from its own
    deeper probe, so folding the pool's verdict in excluded cases the agent had actually
    answered — which silently dropped real hits out of the average.
    """
    dataset = await _dataset_with_gold(db_session, test_project.id, n=2)

    async def pool_with_agent_head_failed(*args, **kwargs):
        pool = SimpleNamespace(
            chunks=[],
            heads_failed={"agent": "agent returned no ranking for this query", "vector": "boom"},
        )
        return pool, False, True

    monkeypatch.setattr(rlm, "assemble_case_pool", pool_with_agent_head_failed)
    res = await rlm.compute_by_stage_metrics(
        db_session, test_project, [dataset], "synthetic", refresh=True, db_factory=case_sessions
    )
    by_stage = {s.stage: s for s in res.stages}
    # The real head failure is still honoured...
    assert by_stage["vector"].cases_failed == 2
    # ...but the agent head's "no ranking" is not treated as a measurement failure here.
    assert "agent" not in by_stage or by_stage.get("agent") is None


@pytest.mark.asyncio
async def test_pooling_opens_one_session_per_case(
    db_session, test_project, stubbed_pool, planned, case_sessions
):
    """Each pooled case gets its own session rather than sharing the caller's.

    An AsyncSession is not safe for concurrent use, and this fan-out runs several cases at once:
    sharing one session deadlocks the whole compute (the first case holds the connection, the
    rest wait forever) with no error raised and no case ever completing.
    """
    dataset = await _dataset_with_gold(db_session, test_project.id, n=3)
    opened: list[int] = []

    @asynccontextmanager
    async def counting_factory():
        opened.append(1)
        async with case_sessions() as session:
            yield session

    await rlm.compute_by_stage_metrics(
        db_session, test_project, [dataset], "synthetic", refresh=True, db_factory=counting_factory
    )
    assert len(opened) == 3
