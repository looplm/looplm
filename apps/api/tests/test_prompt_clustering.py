"""Tests for hierarchical prompt clustering."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.models import Prompt
from app.models.project import Project
from app.services.prompt_analysis import get_or_create_github_integration
from app.services.prompt_clustering import (
    move_cluster,
    parse_clustering_response,
    suggest_clusters,
)


class _Usage:
    input_tokens = 1
    output_tokens = 1


def test_parse_clamps_depth_and_fills_unmatched():
    content = (
        '{"clusters": ['
        '{"path": ["A", "B", "C", "D"], "prompt_indices": [0, 9]},'
        '{"path": [], "prompt_indices": [1]}'
        '], "summary": "s"}'
    )
    res = parse_clustering_response(content, 3)
    assert res[0] == ["A", "B", "C"]   # depth capped at 3
    assert res[1] == ["Ungrouped"]     # empty path falls back
    assert res[2] == ["Ungrouped"]     # index 2 unmatched
    assert 9 not in res                # out-of-range index dropped


def test_parse_handles_garbage():
    assert parse_clustering_response("not json", 2) == {0: ["Ungrouped"], 1: ["Ungrouped"]}


@pytest.mark.asyncio
async def test_suggest_clusters_maps_back_to_original_indices():
    class FakeLLM:
        provider = "openai"
        model = "gpt-4o"

        async def tracked_chat_completion(self, messages, *, temperature, response_format):
            return '{"clusters":[{"path":["G"],"prompt_indices":[0,1]}],"summary":"x"}', _Usage()

    items = [
        {"index": 10, "name": "a", "file_path": "", "snippet": ""},
        {"index": 20, "name": "b", "file_path": "", "snippet": ""},
    ]
    assignment, _summary, _usage = await suggest_clusters(items, FakeLLM())
    assert assignment[10] == ["G"]
    assert assignment[20] == ["G"]


@pytest.mark.asyncio
async def test_move_cluster_rewrites_prefix(db_session, test_project: Project):
    integ = await get_or_create_github_integration(test_project.id, db_session)
    await db_session.flush()

    def _p(name, path):
        return Prompt(
            id=uuid4(), integration_id=integ.id, external_id=name, name=name,
            template="", version=1, variables=[], prompt_metadata={}, cluster_path=path,
        )

    db_session.add_all([_p("1", ["A", "B"]), _p("2", ["A", "C"]), _p("3", ["X"])])
    await db_session.commit()

    moved = await move_cluster(db_session, test_project.id, ["A"], ["Z"])
    assert moved == 2

    rows = {p.name: p for p in (await _all_prompts(db_session, integ.id))}
    assert rows["1"].cluster_path == ["Z", "B"]
    assert rows["2"].cluster_path == ["Z", "C"]
    assert rows["3"].cluster_path == ["X"]


async def _all_prompts(db_session, integration_id):
    from sqlalchemy import select
    return (
        await db_session.execute(select(Prompt).where(Prompt.integration_id == integration_id))
    ).scalars().all()
