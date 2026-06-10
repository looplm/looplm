"""Tests for the GitHub prompt-extraction service (discover → extract pipeline)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.models import Integration, IntegrationType, Prompt
from app.models.project import Project
from app.models.prompts import PromptExtraction
from app.schemas.prompts import ExtractedPrompt, PromptLocation, PromptLocationList
from app.services import prompt_extraction_service as pes
from app.services.prompt_extraction_service import extract_prompts_from_repo, recheck_prompt


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


def _patch_pipeline(monkeypatch, locations, extracts, *, calls: list | None = None):
    """Stub the two LLM phases. `extracts` maps location name -> ExtractedPrompt.

    When `calls` is given, each extracted location name is appended to it so a
    test can assert which prompts actually triggered an LLM extraction.
    """

    async def fake_discover(agent, deps, limits, *, db, extraction):
        return PromptLocationList(summary="found prompts", locations=locations), _Usage()

    async def fake_extract(agent, deps, loc, limits):
        if calls is not None:
            calls.append(loc.name)
        return extracts.get(loc.name), _Usage()

    monkeypatch.setattr(pes, "_discover_locations", fake_discover)
    monkeypatch.setattr(pes, "_extract_one", fake_extract)


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
async def test_resume_skips_already_saved(
    db_session, test_project: Project, monkeypatch, tmp_path: Path
):
    # First run saves A and B.
    _patch_pipeline(
        monkeypatch,
        [PromptLocation(name="A", file_path="a.py"), PromptLocation(name="B", file_path="b.py")],
        {
            "A": ExtractedPrompt(name="A", template="alpha", variables=[], file_path="a.py"),
            "B": ExtractedPrompt(name="B", template="beta", variables=[], file_path="b.py"),
        },
    )
    await _run(db_session, test_project, tmp_path)

    # Second run discovers A, B (already saved) and a new C. Only C is extracted.
    calls: list[str] = []
    _patch_pipeline(
        monkeypatch,
        [
            PromptLocation(name="A", file_path="a.py"),
            PromptLocation(name="B", file_path="b.py"),
            PromptLocation(name="C", file_path="c.py"),
        ],
        {"C": ExtractedPrompt(name="C", template="gamma", variables=[], file_path="c.py")},
        calls=calls,
    )
    await _run(db_session, test_project, tmp_path)

    assert calls == ["C"]  # A and B were not re-extracted
    _, prompts = await _github_prompts(db_session, test_project)
    assert {p.name for p in prompts} == {"A", "B", "C"}


@pytest.mark.asyncio
async def test_reextraction_prunes_removed_prompts(
    db_session, test_project: Project, monkeypatch, tmp_path: Path
):
    _patch_pipeline(
        monkeypatch,
        [PromptLocation(name="A", file_path="a.py"), PromptLocation(name="B", file_path="b.py")],
        {
            "A": ExtractedPrompt(name="A", template="alpha", variables=[], file_path="a.py"),
            "B": ExtractedPrompt(name="B", template="beta", variables=[], file_path="b.py"),
        },
    )
    await _run(db_session, test_project, tmp_path)

    # B is gone from the repo now → discovery returns only A → B is pruned.
    _patch_pipeline(
        monkeypatch,
        [PromptLocation(name="A", file_path="a.py")],
        {"A": ExtractedPrompt(name="A", template="alpha", variables=[], file_path="a.py")},
    )
    await _run(db_session, test_project, tmp_path)

    _, prompts = await _github_prompts(db_session, test_project)
    assert {p.name for p in prompts} == {"A"}


async def _noop_cluster(db, project_id, **kwargs):
    return 0


@pytest.mark.asyncio
async def test_discover_stores_planned_and_filters_excluded(
    db_session, test_project: Project, monkeypatch, tmp_path: Path
):
    from app.services.prompt_analysis import (
        add_exclusion,
        get_or_create_github_integration,
        upsert_prompts_for_integration,
    )

    integ = await get_or_create_github_integration(test_project.id, db_session, "acme/app")
    await upsert_prompts_for_integration(
        integ.id,
        [{"external_id": "a.py::A", "name": "A", "template": "x", "version": 1,
          "variables": [], "metadata": {}}],
        db_session, delete_stale=False,
    )
    await add_exclusion(integ, "z.py::Z", db_session)
    await db_session.commit()

    locs = [
        PromptLocation(name="A", file_path="a.py"),
        PromptLocation(name="B", file_path="b.py"),
        PromptLocation(name="Z", file_path="z.py"),
    ]

    async def fake_discover(agent, deps, limits, *, db, extraction):
        return PromptLocationList(summary="s", locations=locs), _Usage()

    monkeypatch.setattr(pes, "_discover_locations", fake_discover)

    extraction = PromptExtraction(id=uuid4(), project_id=test_project.id, status="pending")
    db_session.add(extraction)
    await db_session.commit()

    await pes.discover_repo_prompts(
        project_id=test_project.id, extraction_id=extraction.id,
        db_factory=_Factory(db_session), repo_path=str(tmp_path),
        repo_full_name="acme/app", provider="openai", model="gpt-4o", api_key="sk-test",
    )

    await db_session.refresh(extraction)
    assert extraction.status == "awaiting_selection"
    planned = {p["external_id"]: p for p in extraction.planned_locations}
    assert set(planned) == {"a.py::A", "b.py::B"}  # Z excluded
    assert planned["a.py::A"]["already_saved"] is True
    assert planned["b.py::B"]["already_saved"] is False


@pytest.mark.asyncio
async def test_confirm_extracts_selected_and_prunes(
    db_session, test_project: Project, monkeypatch, tmp_path: Path
):
    from app.services.prompt_analysis import (
        get_or_create_github_integration,
        upsert_prompts_for_integration,
    )

    integ = await get_or_create_github_integration(test_project.id, db_session, "acme/app")
    await upsert_prompts_for_integration(
        integ.id,
        [
            {"external_id": "a.py::A", "name": "A", "template": "alpha", "version": 1,
             "variables": [], "metadata": {}},
            {"external_id": "old.py::Old", "name": "Old", "template": "o", "version": 1,
             "variables": [], "metadata": {}},
        ],
        db_session, delete_stale=False,
    )
    planned = [
        {"external_id": "a.py::A", "name": "A", "file_path": "a.py", "line_start": None,
         "role": None, "note": None, "already_saved": True},
        {"external_id": "b.py::B", "name": "B", "file_path": "b.py", "line_start": None,
         "role": None, "note": None, "already_saved": False},
        {"external_id": "c.py::C", "name": "C", "file_path": "c.py", "line_start": None,
         "role": None, "note": None, "already_saved": False},
    ]
    extraction = PromptExtraction(
        id=uuid4(), project_id=test_project.id, status="awaiting_selection",
        planned_locations=planned,
    )
    db_session.add(extraction)
    await db_session.commit()

    calls: list[str] = []
    extracts = {"B": ExtractedPrompt(name="B", template="beta", variables=[], file_path="b.py")}

    async def fake_extract(agent, deps, loc, limits):
        calls.append(loc.name)
        return extracts.get(loc.name), _Usage()

    monkeypatch.setattr(pes, "_extract_one", fake_extract)
    monkeypatch.setattr("app.services.prompt_clustering.cluster_project_prompts", _noop_cluster)

    await pes.confirm_extraction(
        project_id=test_project.id, extraction_id=extraction.id,
        db_factory=_Factory(db_session), repo_path=str(tmp_path), repo_full_name="acme/app",
        selected_external_ids=["b.py::B"],  # A already saved, C not selected
        provider="openai", model="gpt-4o", api_key="sk-test",
    )

    await db_session.refresh(extraction)
    assert extraction.status == "completed"
    assert calls == ["B"]  # only the selected, not-already-saved location is extracted
    _, prompts = await _github_prompts(db_session, test_project)
    # A kept (still in planned), B added, Old pruned (gone from repo), C never imported.
    assert {p.name for p in prompts} == {"A", "B"}


@pytest.mark.asyncio
async def test_delete_and_exclusion_helpers(db_session, test_project: Project):
    from app.services.prompt_analysis import (
        add_exclusion,
        delete_prompt,
        get_excluded_ids,
        get_or_create_github_integration,
        remove_exclusion,
        upsert_prompts_for_integration,
    )

    integ = await get_or_create_github_integration(test_project.id, db_session, "acme/app")
    await upsert_prompts_for_integration(
        integ.id,
        [{"external_id": "a.py::A", "name": "A", "template": "x", "version": 1,
          "variables": [], "metadata": {}}],
        db_session, delete_stale=False,
    )
    await db_session.commit()

    _, prompts = await _github_prompts(db_session, test_project)
    assert await delete_prompt(prompts[0].id, test_project.id, db_session) is True
    _, prompts = await _github_prompts(db_session, test_project)
    assert prompts == []

    await add_exclusion(integ, "a.py::A", db_session)
    await db_session.commit()
    assert get_excluded_ids(integ) == {"a.py::A"}
    await remove_exclusion(integ, "a.py::A", db_session)
    await db_session.commit()
    assert get_excluded_ids(integ) == set()


@pytest.mark.asyncio
async def test_recheck_updates_when_changed(
    db_session, test_project: Project, monkeypatch, tmp_path: Path
):
    _patch_pipeline(
        monkeypatch,
        [PromptLocation(name="A", file_path="a.py", line_start=3)],
        {"A": ExtractedPrompt(name="A", template="alpha", variables=[], file_path="a.py")},
    )
    await _run(db_session, test_project, tmp_path)
    _, prompts = await _github_prompts(db_session, test_project)
    prompt = prompts[0]

    async def changed_extract(agent, deps, loc, limits):
        return ExtractedPrompt(name="A", template="alpha v2", variables=["x"], file_path="a.py"), _Usage()

    monkeypatch.setattr(pes, "_extract_one", changed_extract)
    changed = await recheck_prompt(
        prompt, project_id=test_project.id, repo_path=str(tmp_path),
        provider="openai", model="gpt-4o", api_key="sk-test",
        azure_endpoint=None, azure_api_version=None, db=db_session,
    )
    assert changed is True
    await db_session.refresh(prompt)
    assert prompt.template == "alpha v2"
    assert prompt.variables == ["x"]

    # Re-checking with identical content reports no change.
    async def same_extract(agent, deps, loc, limits):
        return ExtractedPrompt(name="A", template="alpha v2", variables=["x"], file_path="a.py"), _Usage()

    monkeypatch.setattr(pes, "_extract_one", same_extract)
    changed_again = await recheck_prompt(
        prompt, project_id=test_project.id, repo_path=str(tmp_path),
        provider="openai", model="gpt-4o", api_key="sk-test",
        azure_endpoint=None, azure_api_version=None, db=db_session,
    )
    assert changed_again is False
