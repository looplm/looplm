"""Tests for the GitHub prompt-extraction service (discover → extract pipeline)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.models import Integration, IntegrationType, Prompt
from app.models.project import Project
from app.models.prompts import PromptExtraction
from app.schemas.prompts import ExtractedPrompt, PromptLocation, PromptLocationList
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


class _Usage:
    def __init__(self, input_tokens=10, output_tokens=5):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


@pytest_asyncio.fixture
async def pending_extraction(db_session, test_project: Project):
    extraction = PromptExtraction(id=uuid4(), project_id=test_project.id, status="pending")
    db_session.add(extraction)
    await db_session.commit()
    await db_session.refresh(extraction)
    return extraction


def _patch_pipeline(monkeypatch, locations, extracts):
    """Stub the two LLM phases. `extracts` maps location name -> ExtractedPrompt."""

    async def fake_discover(agent, deps, limits, *, db, extraction):
        return PromptLocationList(summary="found prompts", locations=locations), _Usage()

    async def fake_extract(agent, deps, loc, limits):
        return extracts.get(loc.name), _Usage()

    monkeypatch.setattr(prompt_extraction_service, "_discover_locations", fake_discover)
    monkeypatch.setattr(prompt_extraction_service, "_extract_one", fake_extract)


async def _run(db_session, project: Project, tmp_path: Path):
    extraction = PromptExtraction(id=uuid4(), project_id=project.id, status="pending")
    db_session.add(extraction)
    await db_session.commit()
    await extract_prompts_from_repo(
        project_id=project.id,
        extraction_id=extraction.id,
        db_factory=_Factory(db_session),
        repo_path=str(tmp_path),
        repo_full_name="acme/app",
        provider="openai",
        model="gpt-4o",
        api_key="sk-test",
    )
    await db_session.refresh(extraction)
    return extraction


async def _github_prompts(db_session, project: Project):
    integration = (
        await db_session.execute(
            select(Integration).where(
                Integration.project_id == project.id,
                Integration.type == IntegrationType.github,
            )
        )
    ).scalar_one()
    prompts = (
        await db_session.execute(
            select(Prompt).where(Prompt.integration_id == integration.id)
        )
    ).scalars().all()
    return integration, prompts


@pytest.mark.asyncio
async def test_pipeline_extracts_and_persists_prompts(
    db_session, test_project: Project, monkeypatch, tmp_path: Path
):
    locations = [
        PromptLocation(name="Triage", file_path="app/agent.py", line_start=12, role="system"),
        PromptLocation(name="Greeting", file_path="app/hello.py"),
        PromptLocation(name="Blank", file_path="app/empty.py"),
    ]
    extracts = {
        "Triage": ExtractedPrompt(
            name="Triage", template="You are support. Topic: {topic}.",
            variables=["topic"], file_path="app/agent.py", line_start=12, role="system",
        ),
        "Greeting": ExtractedPrompt(
            name="Greeting", template="Say hi to {user}", variables=["user"],
            file_path="app/hello.py",
        ),
        "Blank": ExtractedPrompt(name="Blank", template="   ", variables=[], file_path="app/empty.py"),
    }
    _patch_pipeline(monkeypatch, locations, extracts)

    extraction = await _run(db_session, test_project, tmp_path)

    assert extraction.status == "completed"
    assert extraction.extracted_count == 2  # blank skipped

    integration, prompts = await _github_prompts(db_session, test_project)
    assert integration.config.get("repo_full_name") == "acme/app"
    by_name = {p.name: p for p in prompts}
    assert set(by_name) == {"Triage", "Greeting"}
    assert by_name["Triage"].variables == ["topic"]
    assert by_name["Triage"].external_id == "app/agent.py::Triage"
    assert by_name["Triage"].prompt_metadata["source"] == "github"
    assert by_name["Triage"].prompt_metadata["role"] == "system"


@pytest.mark.asyncio
async def test_re_extraction_prunes_stale_prompts(
    db_session, test_project: Project, monkeypatch, tmp_path: Path
):
    # First run finds two prompts.
    _patch_pipeline(
        monkeypatch,
        [
            PromptLocation(name="A", file_path="a.py"),
            PromptLocation(name="B", file_path="b.py"),
        ],
        {
            "A": ExtractedPrompt(name="A", template="alpha", variables=[], file_path="a.py"),
            "B": ExtractedPrompt(name="B", template="beta", variables=[], file_path="b.py"),
        },
    )
    await _run(db_session, test_project, tmp_path)

    # Second run finds only A (with updated text); B should be pruned.
    _patch_pipeline(
        monkeypatch,
        [PromptLocation(name="A", file_path="a.py")],
        {"A": ExtractedPrompt(name="A", template="alpha v2", variables=[], file_path="a.py")},
    )
    await _run(db_session, test_project, tmp_path)

    _, prompts = await _github_prompts(db_session, test_project)
    assert {p.name for p in prompts} == {"A"}
    assert prompts[0].template == "alpha v2"
