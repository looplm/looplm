"""Tests for prompt endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Integration, Prompt
from app.services.analysis_llm import LlmUsageInfo


@pytest_asyncio.fixture
async def sample_prompts(db_session: AsyncSession, test_integration: Integration):
    """Create a few prompts in the DB."""
    prompts = []
    for i in range(3):
        p = Prompt(
            id=uuid4(),
            integration_id=test_integration.id,
            external_id=f"ext-prompt-{i}",
            name=f"prompt-{i}",
            template=f"You are a helpful assistant. Answer: {{{{question_{i}}}}}",
            version=1,
            variables=[f"question_{i}"],
            prompt_metadata={"source": "test"},
        )
        db_session.add(p)
        prompts.append(p)
    await db_session.commit()
    for p in prompts:
        await db_session.refresh(p)
    return prompts


# ── List prompts ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_prompts_empty(client: AsyncClient, auth_headers, test_integration):
    resp = await client.get("/api/prompts", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["data"] == []


@pytest.mark.asyncio
async def test_list_prompts(client: AsyncClient, auth_headers, sample_prompts):
    resp = await client.get("/api/prompts", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3


@pytest.mark.asyncio
async def test_list_prompts_filter_by_integration(client: AsyncClient, auth_headers, test_integration, sample_prompts):
    resp = await client.get(f"/api/prompts?integration_id={test_integration.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 3

    # Non-existent integration
    resp2 = await client.get(f"/api/prompts?integration_id={uuid4()}", headers=auth_headers)
    assert resp2.json()["total"] == 0


# ── Get single prompt ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_prompt(client: AsyncClient, auth_headers, sample_prompts):
    pid = str(sample_prompts[0].id)
    resp = await client.get(f"/api/prompts/{pid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "prompt-0"


@pytest.mark.asyncio
async def test_get_prompt_not_found(client: AsyncClient, auth_headers):
    resp = await client.get(f"/api/prompts/{uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


# ── Sync prompts (mocked connector) ──────────────────────────

@pytest.mark.asyncio
async def test_sync_prompts_integration_not_found(client: AsyncClient, auth_headers):
    resp = await client.post(f"/api/prompts/sync/{uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


# ── Review prompt (mocked LLM) ───────────────────────────────

@pytest.mark.asyncio
async def test_review_prompt(client: AsyncClient, auth_headers, sample_prompts):
    pid = str(sample_prompts[0].id)

    mock_content = '''{
        "anti_patterns": [{"pattern": "vague_instructions", "description": "Too vague", "severity": "high", "location": "line 1"}],
        "suggestions": ["Add examples", "Specify output format"],
        "rewritten_prompt": "Improved prompt text"
    }'''

    with patch("app.services.analysis_llm.AnalysisLlmService") as MockLLM:
        instance = MockLLM.return_value
        instance.tracked_chat_completion = AsyncMock(
            return_value=(
                mock_content,
                LlmUsageInfo(
                    input_tokens=12,
                    output_tokens=8,
                    total_tokens=20,
                    cost_usd=0.001,
                    cached_tokens=0,
                    reasoning_tokens=0,
                    duration_ms=100,
                ),
            )
        )
        instance.provider = "openai"
        instance.model = "gpt-4o-mini"

        resp = await client.post(f"/api/prompts/{pid}/review", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["prompt_id"] == pid
    assert len(data["anti_patterns"]) == 1
    assert data["anti_patterns"][0]["pattern"] == "vague_instructions"
    assert len(data["suggestions"]) == 2
    assert data["rewritten_prompt"] == "Improved prompt text"


@pytest.mark.asyncio
async def test_review_prompt_not_found(client: AsyncClient, auth_headers):
    resp = await client.post(f"/api/prompts/{uuid4()}/review", headers=auth_headers)
    assert resp.status_code == 404
