"""Tests for the GitHub prompt-extraction service."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from pydantic_ai.models.test import TestModel
from sqlalchemy import select

from app.models.models import Integration, IntegrationType, Prompt
from app.models.project import Project
from app.models.prompts import PromptExtraction
from app.services import prompt_extraction_service
from app.services.prompt_extraction_service import extract_prompts_from_repo


class _Factory:
    """db_factory shim: the test fixture exposes one live session."""

    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest_asyncio.fixture
async def pending_extraction(db_session, test_project: Project):
    extraction = PromptExtraction(id=uuid4(), project_id=test_project.id, status="pending")
    db_session.add(extraction)
    await db_session.commit()
    await db_session.refresh(extraction)
    return extraction


def _fake_model(output: dict):
    def _build(**_kwargs):
        return TestModel(call_tools=[], custom_output_args=output, model_name="gpt-4o")
    return _build


@pytest.mark.asyncio
async def test_extraction_upserts_prompts_under_github_integration(
    db_session, test_project: Project, pending_extraction, monkeypatch, tmp_path: Path
):
    output = {
        "summary": "Found two system prompts.",
        "files_analyzed": ["app/agent.py"],
        "prompts": [
            {
                "name": "Triage system prompt",
                "template": "You are a support agent. Topic: {topic}.",
                "variables": ["topic"],
                "file_path": "app/agent.py",
                "line_start": 12,
                "role": "system",
            },
            {
                "name": "Empty prompt",
                "template": "   ",  # blank -> skipped
                "variables": [],
                "file_path": "app/empty.py",
                "line_start": None,
                "role": None,
            },
        ],
    }
    monkeypatch.setattr(prompt_extraction_service, "_build_model", _fake_model(output))

    await extract_prompts_from_repo(
        project_id=test_project.id,
        extraction_id=pending_extraction.id,
        db_factory=_Factory(db_session),
        repo_path=str(tmp_path),
        repo_full_name="acme/app",
        provider="openai",
        model="gpt-4o",
        api_key="sk-test",
    )

    await db_session.refresh(pending_extraction)
    assert pending_extraction.status == "completed"
    assert pending_extraction.extracted_count == 1  # blank template skipped
    assert pending_extraction.summary == "Found two system prompts."

    integration = (
        await db_session.execute(
            select(Integration).where(
                Integration.project_id == test_project.id,
                Integration.type == IntegrationType.github,
            )
        )
    ).scalar_one()
    assert integration.config.get("repo_full_name") == "acme/app"

    prompts = (
        await db_session.execute(
            select(Prompt).where(Prompt.integration_id == integration.id)
        )
    ).scalars().all()
    assert len(prompts) == 1
    p = prompts[0]
    assert p.name == "Triage system prompt"
    assert p.variables == ["topic"]
    assert p.external_id == "app/agent.py::Triage system prompt"
    assert p.prompt_metadata["source"] == "github"
    assert p.prompt_metadata["file_path"] == "app/agent.py"


@pytest.mark.asyncio
async def test_re_extraction_removes_stale_prompts(
    db_session, test_project: Project, monkeypatch, tmp_path: Path
):
    first = {
        "summary": "one",
        "files_analyzed": [],
        "prompts": [
            {"name": "A", "template": "alpha", "variables": [], "file_path": "a.py", "line_start": None, "role": None},
            {"name": "B", "template": "beta", "variables": [], "file_path": "b.py", "line_start": None, "role": None},
        ],
    }
    second = {
        "summary": "two",
        "files_analyzed": [],
        "prompts": [
            {"name": "A", "template": "alpha v2", "variables": [], "file_path": "a.py", "line_start": None, "role": None},
        ],
    }

    async def _run(output):
        extraction = PromptExtraction(id=uuid4(), project_id=test_project.id, status="pending")
        db_session.add(extraction)
        await db_session.commit()
        monkeypatch.setattr(prompt_extraction_service, "_build_model", _fake_model(output))
        await extract_prompts_from_repo(
            project_id=test_project.id,
            extraction_id=extraction.id,
            db_factory=_Factory(db_session),
            repo_path=str(tmp_path),
            repo_full_name="acme/app",
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
        )

    await _run(first)
    await _run(second)

    integration = (
        await db_session.execute(
            select(Integration).where(
                Integration.project_id == test_project.id,
                Integration.type == IntegrationType.github,
            )
        )
    ).scalar_one()
    prompts = (
        await db_session.execute(
            select(Prompt).where(Prompt.integration_id == integration.id)
        )
    ).scalars().all()
    # B was removed; A updated in place.
    assert {p.name for p in prompts} == {"A"}
    assert prompts[0].template == "alpha v2"
