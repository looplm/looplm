"""Tests for gold resolution + inter-annotator agreement (services/chunk_agreement.py)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.base import IndexProviderType
from app.models.datasets import TestCase, TestDataset
from app.models.index_providers import IndexProvider
from app.services.chunk_agreement import (
    Vote,
    build_agreement_report,
    cohen_kappa,
    resolve_gold,
)


# --- resolve_gold (majority + override) ---

def test_resolve_gold_majority_vote():
    rows = [
        ("t1", "c1", 2, "ann1"),
        ("t1", "c1", 3, "ann2"),
        ("t1", "c1", 0, "ann3"),  # 2-1 relevant
        ("t1", "c2", 0, "ann1"),
        ("t1", "c2", 0, "ann2"),  # both irrelevant
    ]
    rel, non, grades = resolve_gold(rows)
    assert rel == {"t1": {"c1"}}
    assert non == {"t1": {"c2"}}
    # Gold grade for c1 is the rounded mean of the votes (2, 3, 0) -> round(1.67) = 2.
    assert grades == {"t1": {"c1": 2}}


def test_resolve_gold_tie_is_unjudged():
    # 1-1 relevant/irrelevant split, no override → chunk is in neither set (stays unjudged).
    rel, non, grades = resolve_gold([("t", "c", 2, "a"), ("t", "c", 0, "b")])
    assert rel == {}
    assert non == {}
    assert grades == {}


def test_resolve_gold_override_wins_over_majority():
    rows = [("t", "c", 2, "a"), ("t", "c", 3, "b")]  # majority says relevant
    rel, non, grades = resolve_gold(rows, overrides={("t", "c"): 0})
    assert rel == {}
    assert non == {"t": {"c"}}
    assert grades == {}


def test_resolve_gold_single_annotator_matches_their_grade():
    rel, non, grades = resolve_gold([("t", "c1", 3, "a"), ("t", "c2", 0, "a")])
    assert rel == {"t": {"c1"}}
    assert non == {"t": {"c2"}}
    # A single annotator's grade is preserved exactly.
    assert grades == {"t": {"c1": 3}}


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
        Vote("t1", "c1", 2, "a", "alice", title="Chunk one"),
        Vote("t1", "c1", 0, "b", "bob"),  # disagreement on c1
        Vote("t1", "c2", 2, "a", "alice"),
        Vote("t1", "c2", 2, "b", "bob"),  # agreement on c2
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
    report = build_agreement_report([Vote("t", "c", 2, "a", "alice")])
    assert report.available is False
    assert report.pairwise == []


def test_agreement_report_reflects_gold_override():
    votes = [
        Vote("t", "c", 2, "a", "alice"),
        Vote("t", "c", 0, "b", "bob"),
    ]
    report = build_agreement_report(votes, overrides={("t", "c"): 3})
    assert report.disagreements[0].gold == 3


# --- endpoints ---

@pytest.mark.asyncio
async def test_agreement_and_gold_endpoints(
    client: AsyncClient, auth_headers, db_session, test_project, monkeypatch
):
    import app.services.retrieval_labels_metrics as retrieval_router

    dataset = TestDataset(id=uuid4(), project_id=test_project.id, name="set")
    db_session.add(dataset)
    db_session.add(TestCase(id=uuid4(), dataset_id=dataset.id, test_id="q1", prompt="q"))
    db_session.add(
        IndexProvider(
            id=uuid4(), project_id=test_project.id, type=IndexProviderType.azure_search,
            name="idx", config={"index_name": "i"}, api_key=b"x", base_url="https://example.net",
        )
    )
    await db_session.commit()

    # Only one annotator so far → agreement not available.
    await client.post(
        "/api/pipeline/labels", headers=auth_headers,
        json={"labels": [{"test_id": "q1", "chunk_id": "c1", "relevance": 2}]},
    )
    resp = await client.get("/api/pipeline/labeling/agreement", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["available"] is False

    # Adjudicate a gold grade; metrics then score it against what the live probe retrieves.
    gold = await client.put(
        "/api/pipeline/labeling/gold", headers=auth_headers,
        json={"test_id": "q1", "chunk_id": "c1", "relevance": 3},
    )
    assert gold.status_code == 200

    class _FakeProvider:
        async def aclose(self):
            pass

    async def _fake_probe(provider, project_id, test_id, query, k, *, embedder=None, refresh=False):
        return ["c1"]

    monkeypatch.setattr(retrieval_router, "build_index_provider", lambda row: _FakeProvider())
    monkeypatch.setattr(retrieval_router, "cached_probe_chunk_ids", _fake_probe)

    metrics = await client.get(
        "/api/pipeline/retrieval-metrics?source=labels", headers=auth_headers
    )
    assert metrics.status_code == 200
    assert metrics.json()["available"] is True
    assert metrics.json()["recall_at_k"]["10"] == 1.0
