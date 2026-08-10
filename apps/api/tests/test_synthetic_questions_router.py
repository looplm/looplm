"""Router tests for synthetic-question runs: validation, cancel semantics, summaries."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.base import IndexProviderType
from app.models.index_providers import IndexProvider
from app.models.synthetic_questions import SyntheticQuestionRun


async def _make_provider(db_session, project_id):
    provider = IndexProvider(
        project_id=project_id,
        name="Test index",
        type=IndexProviderType.azure_search,
        base_url="https://example.search.windows.net",
        api_key=b"encrypted",
        config={"index_name": "test-index"},
    )
    db_session.add(provider)
    await db_session.commit()
    await db_session.refresh(provider)
    return provider


async def _make_run(db_session, project_id, provider_id, status="running", results=None):
    run = SyntheticQuestionRun(
        project_id=project_id,
        provider_id=provider_id,
        status=status,
        stage="generating" if status == "running" else None,
        scope="corpus",
        sample_size=50,
        questions_per_chunk=2,
        negative_share=15,
        total=50,
        processed=10,
        results=results,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


@pytest.mark.asyncio
async def test_create_run_returns_202_and_persists_the_request(
    client: AsyncClient, auth_headers, db_session, test_project, monkeypatch
):
    # The worker hits a real index and a real LLM; the router's job is only to record and spawn.
    import app.routers.synthetic_questions as router_module

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr(router_module, "run_synthetic_question_generation", _noop)
    provider = await _make_provider(db_session, test_project.id)

    resp = await client.post(
        "/api/synthetic-questions/runs",
        headers=auth_headers,
        json={
            "provider_id": str(provider.id),
            "scope": "corpus",
            "sample_size": 20,
            "questions_per_chunk": 2,
            "negative_share": 10,
            "persist": False,
        },
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"

    run = (
        await db_session.execute(
            select(SyntheticQuestionRun).where(SyntheticQuestionRun.id == UUID(body["run_id"]))
        )
    ).scalar_one()
    assert run.sample_size == 20
    assert run.persist is False
    assert run.negative_share == 10


@pytest.mark.asyncio
async def test_create_run_rejects_partition_scope_without_a_value(
    client: AsyncClient, auth_headers, db_session, test_project
):
    provider = await _make_provider(db_session, test_project.id)
    resp = await client.post(
        "/api/synthetic-questions/runs",
        headers=auth_headers,
        json={"provider_id": str(provider.id), "scope": "partition", "partition_key": "tags"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_run_404s_on_an_unknown_provider(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/synthetic-questions/runs",
        headers=auth_headers,
        json={"provider_id": str(uuid4()), "scope": "corpus"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_run_404s_on_an_unknown_target_dataset(
    client: AsyncClient, auth_headers, db_session, test_project
):
    provider = await _make_provider(db_session, test_project.id)
    resp = await client.post(
        "/api/synthetic-questions/runs",
        headers=auth_headers,
        json={"provider_id": str(provider.id), "dataset_id": str(uuid4())},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_running_run(client: AsyncClient, auth_headers, db_session, test_project):
    provider = await _make_provider(db_session, test_project.id)
    run = await _make_run(db_session, test_project.id, provider.id)

    resp = await client.post(
        f"/api/synthetic-questions/runs/{run.id}/cancel", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    row = (
        await db_session.execute(
            select(SyntheticQuestionRun).where(SyntheticQuestionRun.id == run.id)
        )
    ).scalar_one()
    await db_session.refresh(row)
    assert row.status == "cancelled"
    assert row.stage is None
    assert row.completed_at is not None


@pytest.mark.asyncio
async def test_cancel_finished_run_conflicts(
    client: AsyncClient, auth_headers, db_session, test_project
):
    provider = await _make_provider(db_session, test_project.id)
    run = await _make_run(db_session, test_project.id, provider.id, status="completed")
    run.completed_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await client.post(
        f"/api/synthetic-questions/runs/{run.id}/cancel", headers=auth_headers
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_unknown_run_404s(client: AsyncClient, auth_headers):
    resp = await client.post(f"/api/synthetic-questions/runs/{uuid4()}/cancel", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_run_returns_questions_and_counts(
    client: AsyncClient, auth_headers, db_session, test_project
):
    provider = await _make_provider(db_session, test_project.id)
    results = {
        "questions": [
            {
                "text": "Innerhalb welcher Frist werden Reisekosten erstattet?",
                "style": "factual",
                "source_chunk_id": "page_1_chunk_0",
            }
        ],
        "counts": {
            "chunks_sampled": 30,
            "chunks_used": 20,
            "chunks_skipped": {"tiny": 10},
            "questions_generated": 1,
            "negatives_generated": 0,
            "cases_created": 1,
            "labels_created": 1,
        },
    }
    run = await _make_run(
        db_session, test_project.id, provider.id, status="completed", results=results
    )

    resp = await client.get(f"/api/synthetic-questions/runs/{run.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"]["questions"][0]["source_chunk_id"] == "page_1_chunk_0"
    assert body["results"]["counts"]["chunks_skipped"] == {"tiny": 10}


@pytest.mark.asyncio
async def test_list_runs_is_scoped_to_the_provider(
    client: AsyncClient, auth_headers, db_session, test_project
):
    provider = await _make_provider(db_session, test_project.id)
    other = await _make_provider(db_session, test_project.id)
    await _make_run(db_session, test_project.id, provider.id, status="completed",
                    results={"counts": {"questions_generated": 4, "negatives_generated": 1,
                                        "cases_created": 5}})
    await _make_run(db_session, test_project.id, other.id, status="completed")

    resp = await client.get(
        f"/api/synthetic-questions/runs?provider_id={provider.id}", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["questions_generated"] == 5
    assert data[0]["cases_created"] == 5


@pytest.mark.asyncio
async def test_delete_run_refuses_while_in_progress(
    client: AsyncClient, auth_headers, db_session, test_project
):
    provider = await _make_provider(db_session, test_project.id)
    run = await _make_run(db_session, test_project.id, provider.id, status="running")

    resp = await client.delete(f"/api/synthetic-questions/runs/{run.id}", headers=auth_headers)
    assert resp.status_code == 409

    run.status = "completed"
    await db_session.commit()
    resp = await client.delete(f"/api/synthetic-questions/runs/{run.id}", headers=auth_headers)
    assert resp.status_code == 204
