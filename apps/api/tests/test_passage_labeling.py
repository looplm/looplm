"""Tests for per-passage relevance selection (additive refinement of chunk labeling)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.datasets import TestCase, TestDataset
from app.models.passage_labels import (
    PASSAGE_SOURCE_CHUNK_SPLIT,
    PassageRelevanceLabel,
    is_valid_passage_relevance,
)
from app.services.passage_split import split_chunk_into_passages


# --- Splitter (the A source) -----------------------------------------------------


def test_split_sentences_and_ids_are_stable():
    passages = split_chunk_into_passages(
        "c1", "First sentence here. Second one follows!", section_path="Intro"
    )
    assert [p.passage_id for p in passages] == ["c1#s1", "c1#s2"]
    assert [p.text for p in passages] == ["First sentence here.", "Second one follows!"]
    assert all(p.section_path == "Intro" for p in passages)
    assert all(p.passage_source == PASSAGE_SOURCE_CHUNK_SPLIT for p in passages)
    # Deterministic: same input → same ids/text.
    again = split_chunk_into_passages("c1", "First sentence here. Second one follows!", section_path="Intro")
    assert [p.passage_id for p in again] == ["c1#s1", "c1#s2"]


def test_split_keeps_list_items_and_table_rows_whole():
    text = "Steps:\n- do the first thing\n- do the second thing\n| a | b |"
    passages = split_chunk_into_passages("c2", text)
    texts = [p.text for p in passages]
    assert "- do the first thing" in texts
    assert "- do the second thing" in texts
    assert "| a | b |" in texts


def test_split_empty_text_yields_nothing():
    assert split_chunk_into_passages("c3", "") == []
    assert split_chunk_into_passages("c3", None) == []


def test_is_valid_passage_relevance():
    assert is_valid_passage_relevance(0)
    assert is_valid_passage_relevance(1)
    assert not is_valid_passage_relevance(2)
    assert not is_valid_passage_relevance(True)  # bool is not a grade
    assert not is_valid_passage_relevance("1")


# --- Endpoints -------------------------------------------------------------------


async def _seed_dataset(db_session, project, *, test_id="q1", prompt="how to X"):
    dataset = TestDataset(id=uuid4(), project_id=project.id, name="DS")
    db_session.add(dataset)
    db_session.add(
        TestCase(id=uuid4(), dataset_id=dataset.id, test_id=test_id, prompt=prompt)
    )
    await db_session.commit()
    return dataset


@pytest.mark.asyncio
async def test_passage_upsert_roundtrip(client: AsyncClient, auth_headers, db_session, test_project):
    await _seed_dataset(db_session, test_project)

    # Uncheck one passage (0), keep another (1) — a batch under one (test_id, chunk_id).
    save = await client.post(
        "/api/pipeline/passage-labels",
        headers=auth_headers,
        json={
            "test_id": "q1",
            "chunk_id": "c1",
            "passages": [
                {
                    "passage_id": "c1#s1",
                    "relevant": 1,
                    "passage_source": "chunk_split",
                    "section_path": "Intro",
                    "text_preview": "First sentence.",
                },
                {
                    "passage_id": "c1#s2",
                    "relevant": 0,
                    "passage_source": "chunk_split",
                    "text_preview": "Off-topic aside.",
                },
            ],
        },
    )
    assert save.status_code == 200 and save.json()["saved"] == 2

    rows = (
        await db_session.execute(
            select(PassageRelevanceLabel).where(
                PassageRelevanceLabel.project_id == test_project.id
            )
        )
    ).scalars().all()
    by_pid = {r.passage_id: r for r in rows}
    assert by_pid["c1#s1"].relevant == 1 and by_pid["c1#s2"].relevant == 0
    assert by_pid["c1#s1"].section_path == "Intro"

    # Re-checking s2 updates the same row (per-annotator upsert, not a new row).
    update = await client.post(
        "/api/pipeline/passage-labels",
        headers=auth_headers,
        json={
            "test_id": "q1",
            "chunk_id": "c1",
            "passages": [
                {"passage_id": "c1#s2", "relevant": 1, "passage_source": "chunk_split"}
            ],
        },
    )
    assert update.status_code == 200
    await db_session.refresh(by_pid["c1#s2"])
    assert by_pid["c1#s2"].relevant == 1


@pytest.mark.asyncio
async def test_passage_upsert_rejects_bad_grade(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/pipeline/passage-labels",
        headers=auth_headers,
        json={
            "test_id": "q1",
            "chunk_id": "c1",
            "passages": [{"passage_id": "c1#s1", "relevant": 2, "passage_source": "chunk_split"}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_passage_upsert_rejects_bad_source(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/pipeline/passage-labels",
        headers=auth_headers,
        json={
            "test_id": "q1",
            "chunk_id": "c1",
            "passages": [{"passage_id": "c1#s1", "relevant": 1, "passage_source": "nope"}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_chunk_passages_without_provider(client: AsyncClient, auth_headers):
    """With no index provider connected there's nothing to split — honest empty response."""
    resp = await client.get(
        "/api/pipeline/chunk-passages?test_id=q1&chunk_id=c1", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_connected"] is False and body["available"] is False
    assert body["passages"] == []
