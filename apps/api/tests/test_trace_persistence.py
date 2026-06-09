"""Unit tests for persist_normalized_trace.

Guards the batched-insert rewrite (pre-generated UUIDs + single flush): span
parent linkage, multi-level child-trace hierarchy, and the update_existing
delete-and-reinsert path must all behave exactly as before.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Integration, Span, Trace
from app.services.trace_persistence import persist_normalized_trace


def _trace(external_id: str, **overrides) -> dict:
    base = {
        "external_id": external_id,
        "name": "root",
        "start_time": __import__("datetime").datetime(2026, 6, 1, tzinfo=__import__("datetime").timezone.utc),
        "spans": [],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_persist_links_multi_level_spans(db_session: AsyncSession, test_integration: Integration):
    normalized = _trace(
        "t-spans",
        spans=[
            {"external_id": "s1", "name": "chain", "type": "chain"},
            {"external_id": "s2", "name": "llm", "type": "llm", "parent_external_id": "s1"},
            {"external_id": "s3", "name": "tool", "type": "tool", "parent_external_id": "s2"},
        ],
    )
    root_id, status = await persist_normalized_trace(db_session, test_integration.id, normalized)
    await db_session.commit()
    assert status == "created"

    spans = (
        await db_session.execute(select(Span).where(Span.trace_id == root_id))
    ).scalars().all()
    by_name = {s.name: s for s in spans}
    assert len(spans) == 3
    # Linkage resolved entirely in-memory before the single flush.
    assert by_name["chain"].parent_span_id is None
    assert by_name["llm"].parent_span_id == by_name["chain"].id
    assert by_name["tool"].parent_span_id == by_name["llm"].id


@pytest.mark.asyncio
async def test_persist_builds_child_trace_hierarchy(db_session: AsyncSession, test_integration: Integration):
    import datetime as _dt

    t0 = _dt.datetime(2026, 6, 1, tzinfo=_dt.timezone.utc)
    normalized = _trace(
        "root-1",
        thread_id="thread-x",
        child_traces=[
            {"external_id": "child-a", "name": "a", "parent_external_id": "root-1", "start_time": t0},
            {
                "external_id": "grandchild",
                "name": "gc",
                "parent_external_id": "child-a",
                "start_time": t0 + _dt.timedelta(seconds=1),
            },
        ],
    )
    root_id, status = await persist_normalized_trace(db_session, test_integration.id, normalized)
    await db_session.commit()
    assert status == "created"

    by_ext = {
        t.external_id: t
        for t in (
            await db_session.execute(
                select(Trace).where(Trace.integration_id == test_integration.id)
            )
        ).scalars().all()
    }
    assert set(by_ext) == {"root-1", "child-a", "grandchild"}
    # Parent links chain up; every node shares the same root.
    assert by_ext["child-a"].parent_trace_id == root_id
    assert by_ext["grandchild"].parent_trace_id == by_ext["child-a"].id
    assert by_ext["child-a"].root_trace_id == root_id
    assert by_ext["grandchild"].root_trace_id == root_id


@pytest.mark.asyncio
async def test_persist_update_existing_replaces_spans(db_session: AsyncSession, test_integration: Integration):
    first = _trace("t-upd", spans=[{"external_id": "old", "name": "old-span", "type": "chain"}])
    root_id, _ = await persist_normalized_trace(db_session, test_integration.id, first)
    await db_session.commit()

    # Re-persist with new spans + update_existing → old spans gone, new linked.
    second = _trace(
        "t-upd",
        name="root-v2",
        spans=[
            {"external_id": "n1", "name": "new-parent", "type": "chain"},
            {"external_id": "n2", "name": "new-child", "type": "llm", "parent_external_id": "n1"},
        ],
    )
    root_id_2, status = await persist_normalized_trace(
        db_session, test_integration.id, second, update_existing=True
    )
    await db_session.commit()
    assert status == "updated"
    assert root_id_2 == root_id  # same row, idempotent on (integration, external_id)

    spans = (
        await db_session.execute(select(Span).where(Span.trace_id == root_id))
    ).scalars().all()
    by_name = {s.name: s for s in spans}
    assert set(by_name) == {"new-parent", "new-child"}  # old span replaced
    assert by_name["new-child"].parent_span_id == by_name["new-parent"].id

    trace = (await db_session.execute(select(Trace).where(Trace.id == root_id))).scalar_one()
    assert trace.name == "root-v2"


@pytest.mark.asyncio
async def test_persist_skips_existing_without_update(db_session: AsyncSession, test_integration: Integration):
    payload = _trace("t-skip", name="v1")
    await persist_normalized_trace(db_session, test_integration.id, payload)
    await db_session.commit()

    again = _trace("t-skip", name="v2")
    root_id, status = await persist_normalized_trace(db_session, test_integration.id, again)
    await db_session.commit()
    assert status == "skipped"

    rows = (
        await db_session.execute(select(Trace).where(Trace.external_id == "t-skip"))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "v1"  # unchanged
