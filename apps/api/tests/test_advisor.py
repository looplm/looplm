"""Tests for architecture advisor endpoints and service."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.models import AdvisorAnalysis
from app.schemas.advisor import AdvisorResponse, ImpactLevel, Suggestion, SuggestionCategory
from app.services.analysis_llm import LlmUsageInfo
from app.services.architecture_advisor import _parse_suggestions


# ── Schema validation ─────────────────────────────────────────

def test_suggestion_schema_valid():
    s = Suggestion(
        title="Cache LLM calls",
        description="Add caching layer",
        category=SuggestionCategory.time_to_value,
        impact=ImpactLevel.high,
        confidence=0.9,
        reasoning="Repeated calls detected",
    )
    assert s.title == "Cache LLM calls"
    assert s.confidence == 0.9


def test_suggestion_schema_confidence_bounds():
    with pytest.raises(Exception):
        Suggestion(
            title="Bad", description="", category=SuggestionCategory.architecture,
            impact=ImpactLevel.low, confidence=1.5,
        )


def test_advisor_response_schema():
    resp = AdvisorResponse(
        integration_id="abc",
        suggestions=[],
        analyzed_at=datetime.now(timezone.utc),
    )
    assert resp.integration_id == "abc"
    assert resp.suggestions == []


# ── Parse suggestions ─────────────────────────────────────────

def test_parse_suggestions_valid_json():
    raw = '''[
        {"title": "A", "description": "B", "category": "architecture", "impact": "high", "confidence": 0.8, "reasoning": "R"}
    ]'''
    result = _parse_suggestions(raw)
    assert len(result) == 1
    assert result[0].title == "A"


def test_parse_suggestions_with_code_fences():
    raw = '```json\n[{"title": "A", "description": "B", "category": "architecture", "impact": "high", "confidence": 0.8}]\n```'
    result = _parse_suggestions(raw)
    assert len(result) == 1


def test_parse_suggestions_invalid_json():
    result = _parse_suggestions("not json at all")
    assert result == []


def test_parse_suggestions_empty_array():
    result = _parse_suggestions("[]")
    assert result == []


# ── Endpoint tests ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_endpoint(client: AsyncClient, auth_headers, test_integration, sample_traces_and_spans):
    mock_content = '''[
        {"title": "Parallelize tools", "description": "Run tools concurrently",
         "category": "time_to_value", "impact": "high", "confidence": 0.85, "reasoning": "Sequential tools detected"}
    ]'''

    with patch("app.services.analysis_llm.AnalysisLlmService") as MockLLM:
        instance = MockLLM.return_value
        instance.tracked_chat_completion = AsyncMock(
            return_value=(
                mock_content,
                LlmUsageInfo(
                    input_tokens=10,
                    output_tokens=5,
                    total_tokens=15,
                    cost_usd=0.001,
                    cached_tokens=0,
                    reasoning_tokens=0,
                    duration_ms=100,
                ),
            )
        )
        instance.provider = "openai"
        instance.model = "gpt-4o-mini"

        resp = await client.post(f"/api/advisor/{test_integration.id}/analyze", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["integration_id"] == str(test_integration.id)
    assert len(data["suggestions"]) == 1
    assert data["suggestions"][0]["title"] == "Parallelize tools"


@pytest.mark.asyncio
async def test_analyze_not_found(client: AsyncClient, auth_headers):
    resp = await client.post(f"/api/advisor/{uuid4()}/analyze", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_suggestions_persisted(client: AsyncClient, auth_headers, test_integration, db_session):
    # Insert an AdvisorAnalysis row directly into the DB
    row = AdvisorAnalysis(
        integration_id=test_integration.id,
        suggestions=[{
            "title": "Persisted",
            "description": "From DB",
            "category": "architecture",
            "impact": "medium",
            "confidence": 0.7,
            "reasoning": "",
        }],
        analyzed_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    await db_session.commit()

    resp = await client.get(f"/api/advisor/{test_integration.id}/suggestions", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["suggestions"][0]["title"] == "Persisted"


@pytest.mark.asyncio
async def test_suggestions_not_found(client: AsyncClient, auth_headers, test_integration):
    resp = await client.get(f"/api/advisor/{test_integration.id}/suggestions", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_analyze_with_empty_routes(client: AsyncClient, auth_headers, test_integration):
    """No traces → LLM still called, returns suggestions (or empty)."""
    with patch("app.services.analysis_llm.AnalysisLlmService") as MockLLM:
        instance = MockLLM.return_value
        instance.tracked_chat_completion = AsyncMock(
            return_value=(
                "[]",
                LlmUsageInfo(
                    input_tokens=10,
                    output_tokens=2,
                    total_tokens=12,
                    cost_usd=0.001,
                    cached_tokens=0,
                    reasoning_tokens=0,
                    duration_ms=100,
                ),
            )
        )
        instance.provider = "openai"
        instance.model = "gpt-4o-mini"

        resp = await client.post(f"/api/advisor/{test_integration.id}/analyze", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["suggestions"] == []


@pytest.mark.asyncio
async def test_analyze_no_auth(client: AsyncClient, test_integration):
    resp = await client.post(f"/api/advisor/{test_integration.id}/analyze")
    assert resp.status_code in (401, 403)


# ── Repo-aware agentic path ───────────────────────────────────

@pytest.mark.asyncio
async def test_advisor_agent_persists_suggestions(
    db_session, test_project, test_integration, monkeypatch,
):
    """The agentic path writes suggestions + an LlmUsageRecord to the DB."""
    from datetime import datetime, timezone

    from pydantic_ai.models.test import TestModel
    from sqlalchemy import select

    from app.models.llm_usage import LlmUsageRecord
    from app.schemas.route_analysis import RouteAnalysisResponse
    from app.services import advisor_agent_service
    from app.services.advisor_agent_service import analyze_architecture_with_repo

    row = AdvisorAnalysis(
        integration_id=test_integration.id,
        project_id=test_project.id,
        status="pending",
        repo_used=True,
        analyzed_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)

    canned = {
        "suggestions": [
            {
                "title": "Parallelize sequential tools",
                "description": "Tools run one after another.",
                "category": "time_to_value",
                "impact": "high",
                "confidence": 0.8,
                "reasoning": "Found sequential awaits in app/agent.py.",
            }
        ],
        "files_analyzed": ["app/agent.py"],
    }

    monkeypatch.setattr(
        advisor_agent_service, "_build_model",
        lambda **_: TestModel(call_tools=[], custom_output_args=canned, model_name="gpt-4o"),
    )

    async def fake_route(*_a, **_k):
        return RouteAnalysisResponse(total_traces=3)

    monkeypatch.setattr(advisor_agent_service, "get_route_analysis", fake_route)

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    await analyze_architecture_with_repo(
        integration_id=test_integration.id,
        project_id=test_project.id,
        analysis_id=row.id,
        db_factory=_Factory(),
        repo_path="/tmp/fake-repo",
        provider="openai",
        model="gpt-4o",
        api_key="sk-test",
    )

    await db_session.refresh(row)
    assert row.status == "completed"
    assert row.repo_used is True
    assert len(row.suggestions) == 1
    assert row.suggestions[0]["title"] == "Parallelize sequential tools"
    assert row.files_analyzed == ["app/agent.py"]

    usage = (
        await db_session.execute(
            select(LlmUsageRecord).where(
                LlmUsageRecord.service_name == "architecture_advisor"
            )
        )
    ).scalars().all()
    assert len(usage) == 1
    assert usage[0].provider == "openai"


@pytest.mark.asyncio
async def test_advisor_use_repo_no_repo_returns_400(
    client: AsyncClient, auth_headers, test_integration, monkeypatch,
):
    """use_repo with no connected repo → clear 400 NO_REPO (no LLM/git touched)."""
    async def fake_resolve(project, db):
        return None

    monkeypatch.setattr("app.routers.advisor.resolve_project_repo", fake_resolve)

    resp = await client.post(
        f"/api/advisor/{test_integration.id}/analyze",
        headers=auth_headers,
        json={"use_repo": True},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "NO_REPO"


@pytest.mark.asyncio
async def test_advisor_use_repo_launches_task(
    client: AsyncClient, db_session, test_project, test_integration, auth_headers, monkeypatch,
):
    """use_repo launches the async task with the provider resolved from settings."""
    test_project.settings = {
        "code_agent_provider": "azure_foundry",  # legacy → coerced to anthropic
        "code_agent_api_key": "sk-fake",
    }
    await db_session.commit()

    async def fake_resolve(project, db):
        return "/tmp/fake-repo"

    captured: dict[str, object] = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.routers.advisor.resolve_project_repo", fake_resolve)
    monkeypatch.setattr("app.routers.advisor.analyze_architecture_with_repo", fake_run)

    resp = await client.post(
        f"/api/advisor/{test_integration.id}/analyze",
        headers=auth_headers,
        json={"use_repo": True},
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "pending"
    assert captured.get("provider") == "anthropic"
    assert captured.get("repo_path") == "/tmp/fake-repo"


@pytest.mark.asyncio
async def test_get_advisor_run_404_when_none(
    client: AsyncClient, auth_headers, test_integration,
):
    resp = await client.get(f"/api/advisor/{test_integration.id}/run", headers=auth_headers)
    assert resp.status_code == 404
