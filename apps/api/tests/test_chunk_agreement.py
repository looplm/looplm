"""Tests for gold resolution + inter-annotator agreement (services/chunk_agreement.py)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.evaluations import EvalResult, EvalRun
from app.services.chunk_agreement import (
    Vote,
    build_agreement_report,
    cohen_kappa,
    resolve_gold,
)


# --- resolve_gold (majority + override) ---

def test_resolve_gold_majority_vote():
    rows = [
        ("t1", "c1", True, "ann1"),
        ("t1", "c1", True, "ann2"),
        ("t1", "c1", False, "ann3"),  # 2-1 relevant
        ("t1", "c2", False, "ann1"),
        ("t1", "c2", False, "ann2"),  # both not relevant
    ]
    rel, non = resolve_gold(rows)
    assert rel == {"t1": {"c1"}}
    assert non == {"t1": {"c2"}}


def test_resolve_gold_tie_is_unjudged():
    # 1-1 split, no override → chunk is in neither set (stays unjudged).
    rel, non = resolve_gold([("t", "c", True, "a"), ("t", "c", False, "b")])
    assert rel == {}
    assert non == {}


def test_resolve_gold_override_wins_over_majority():
    rows = [("t", "c", True, "a"), ("t", "c", True, "b")]  # majority says relevant
    rel, non = resolve_gold(rows, overrides={("t", "c"): False})
    assert rel == {}
    assert non == {"t": {"c"}}


def test_resolve_gold_single_annotator_matches_their_vote():
    rel, non = resolve_gold([("t", "c1", True, "a"), ("t", "c2", False, "a")])
    assert rel == {"t": {"c1"}}
    assert non == {"t": {"c2"}}


# --- Cohen's kappa ---

def test_cohen_kappa_perfect_agreement():
    a = {"x": True, "y": False, "z": True}
    k, n = cohen_kappa(a, dict(a))
    assert n == 3 and k == 1.0


def test_cohen_kappa_no_better_than_chance():
    # Disagree on half; kappa near 0 (here exactly 0 by construction).
    a = {"1": True, "2": True, "3": False, "4": False}
    b = {"1": True, "2": False, "3": True, "4": False}
    k, n = cohen_kappa(a, b)
    assert n == 4 and abs(k) < 1e-9


def test_cohen_kappa_no_overlap():
    k, n = cohen_kappa({"x": True}, {"y": False})
    assert k is None and n == 0


# --- agreement report ---

def test_agreement_report_kappa_and_disagreements():
    votes = [
        Vote("t1", "c1", True, "a", "alice", title="Chunk one"),
        Vote("t1", "c1", False, "b", "bob"),  # disagreement on c1
        Vote("t1", "c2", True, "a", "alice"),
        Vote("t1", "c2", True, "b", "bob"),  # agreement on c2
    ]
    report = build_agreement_report(votes)
    assert report.available is True
    assert report.overlap_count == 2  # both chunks double-judged
    assert report.judged_items == 2
    assert len(report.pairwise) == 1
    assert report.pairwise[0].n == 2
    assert report.average_kappa is not None
    # Only c1 is a disagreement.
    assert len(report.disagreements) == 1
    d = report.disagreements[0]
    assert d.chunk_id == "c1" and d.title == "Chunk one"
    assert {v.labeler for v in d.votes} == {"alice", "bob"}


def test_agreement_report_unavailable_single_annotator():
    report = build_agreement_report([Vote("t", "c", True, "a", "alice")])
    assert report.available is False
    assert report.pairwise == []


def test_agreement_report_reflects_gold_override():
    votes = [
        Vote("t", "c", True, "a", "alice"),
        Vote("t", "c", False, "b", "bob"),
    ]
    report = build_agreement_report(votes, overrides={("t", "c"): True})
    assert report.disagreements[0].gold is True


# --- endpoints ---

@pytest.mark.asyncio
async def test_agreement_and_gold_endpoints(client: AsyncClient, auth_headers, db_session, test_project):
    run = EvalRun(id=uuid4(), project_id=test_project.id, name="agree-run")
    db_session.add(run)
    db_session.add(
        EvalResult(
            id=uuid4(), run_id=run.id, test_id="q1", pass_=True, input="q",
            graders={}, result_metadata={"retrieved_chunks": [{"chunk_id": "c1"}]},
        )
    )
    await db_session.commit()

    # Only one annotator so far → agreement not available.
    await client.post(
        "/api/pipeline/labels", headers=auth_headers,
        json={"labels": [{"test_id": "q1", "chunk_id": "c1", "relevant": True}]},
    )
    resp = await client.get("/api/pipeline/labeling/agreement", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["available"] is False

    # Adjudicate a gold verdict; metrics then score against it.
    gold = await client.put(
        "/api/pipeline/labeling/gold", headers=auth_headers,
        json={"test_id": "q1", "chunk_id": "c1", "relevant": True},
    )
    assert gold.status_code == 200
    metrics = await client.get(
        f"/api/pipeline/retrieval-metrics?run_id={run.id}&source=labels", headers=auth_headers
    )
    assert metrics.status_code == 200
    assert metrics.json()["available"] is True
    assert metrics.json()["recall_at_k"]["10"] == 1.0
