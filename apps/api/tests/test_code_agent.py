"""Tests for the Pydantic AI–based Code Agent service."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from sqlalchemy import select

from app.models.code_agent import CodeSuggestion, OpenCodeAnalysis
from app.models.evaluations import EvalResult, EvalRun
from app.models.llm_usage import LlmUsageRecord
from app.models.project import Project
from app.services import code_agent_service
from app.services.code_agent_service import (
    CodeAgentConfigError,
    _build_model,
    analyze_eval_run,
)
from app.services.code_agent_tools import (
    RepoContext,
    SandboxError,
    _resolve_in_sandbox,
    glob_files,
    grep_files,
    read_file,
)


# ── Sandbox helpers ──────────────────────────────────────────────


def test_resolve_in_sandbox_accepts_internal_path(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n")
    resolved = _resolve_in_sandbox(tmp_path.resolve(), "src/main.py")
    assert resolved == (tmp_path / "src" / "main.py").resolve()


def test_resolve_in_sandbox_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(SandboxError):
        _resolve_in_sandbox(tmp_path.resolve(), "../etc/passwd")


def test_resolve_in_sandbox_rejects_absolute_outside(tmp_path: Path) -> None:
    with pytest.raises(SandboxError):
        _resolve_in_sandbox(tmp_path.resolve(), "/etc/passwd")


# ── Tool behaviour ───────────────────────────────────────────────


def _make_ctx(repo_root: Path) -> RunContext[RepoContext]:
    # RunContext requires a fair number of positional fields. Use SimpleNamespace
    # via a tiny shim — we only need .deps in the tools we test.
    class _Ctx:
        deps = RepoContext(repo_root=repo_root)

    return _Ctx()  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_read_file_returns_numbered_lines(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("alpha\nbeta\ngamma\n")
    ctx = _make_ctx(tmp_path)
    out = await read_file(ctx, "hello.txt")
    assert "alpha" in out
    assert "     1\t" in out
    assert "beta" in out


@pytest.mark.asyncio
async def test_read_file_traversal_returns_error(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    # SandboxError propagates as a Python exception out of the tool; that's
    # what Pydantic AI surfaces back to the model as a tool error.
    with pytest.raises(SandboxError):
        await read_file(ctx, "../something")


@pytest.mark.asyncio
async def test_glob_files_finds_python_sources(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / "src" / "b.py").write_text("y = 2\n")
    (tmp_path / "README.md").write_text("hi\n")
    ctx = _make_ctx(tmp_path)
    out = await glob_files(ctx, "**/*.py")
    lines = out.splitlines()
    assert any(line.endswith("a.py") for line in lines)
    assert any(line.endswith("b.py") for line in lines)
    assert not any("README.md" in line for line in lines)


@pytest.mark.asyncio
async def test_glob_files_skips_noise_directories(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("//\n")
    (tmp_path / "real.js").write_text("//\n")
    ctx = _make_ctx(tmp_path)
    out = await glob_files(ctx, "**/*.js")
    assert "real.js" in out
    assert "node_modules" not in out


@pytest.mark.asyncio
async def test_grep_files_matches_pattern(tmp_path: Path) -> None:
    (tmp_path / "code.py").write_text("def foo():\n    return 42\n\ndef bar():\n    return 7\n")
    ctx = _make_ctx(tmp_path)
    out = await grep_files(ctx, r"def \w+\(")
    assert "code.py:1:def foo():" in out
    assert "code.py:4:def bar():" in out


# ── _build_model ─────────────────────────────────────────────────


def test_build_model_openai() -> None:
    model = _build_model(provider="openai", model="gpt-4o", api_key="sk-test")
    assert model.model_name == "gpt-4o"


def test_build_model_anthropic_uses_default_when_no_model() -> None:
    model = _build_model(provider="anthropic", model=None, api_key="sk-test")
    # The default model name has the form claude-sonnet-4-...
    assert model.model_name.startswith("claude")


def test_build_model_azure_requires_endpoint_and_version() -> None:
    with pytest.raises(CodeAgentConfigError, match="endpoint"):
        _build_model(
            provider="azure_openai",
            model="my-deployment",
            api_key="sk-test",
            azure_endpoint=None,
            azure_api_version="2024-10-21",
        )
    with pytest.raises(CodeAgentConfigError, match="API version"):
        _build_model(
            provider="azure_openai",
            model="my-deployment",
            api_key="sk-test",
            azure_endpoint="https://example.openai.azure.com",
            azure_api_version=None,
        )
    with pytest.raises(CodeAgentConfigError, match="deployment"):
        _build_model(
            provider="azure_openai",
            model=None,
            api_key="sk-test",
            azure_endpoint="https://example.openai.azure.com",
            azure_api_version="2024-10-21",
        )


def test_build_model_azure_ok() -> None:
    model = _build_model(
        provider="azure_openai",
        model="my-deployment",
        api_key="sk-test",
        azure_endpoint="https://example.openai.azure.com",
        azure_api_version="2024-10-21",
    )
    assert model.model_name == "my-deployment"


def test_build_model_missing_api_key_raises() -> None:
    for provider in ("openai", "anthropic"):
        with pytest.raises(CodeAgentConfigError, match="API key"):
            _build_model(provider=provider, model=None, api_key=None)


def test_build_model_rejects_legacy_foundry() -> None:
    with pytest.raises(CodeAgentConfigError, match="Unsupported"):
        _build_model(provider="azure_foundry", model="x", api_key="sk-test")


# ── End-to-end via TestModel ─────────────────────────────────────


@pytest_asyncio.fixture
async def eval_run_with_failure(db_session, test_project: Project):
    """Insert an EvalRun with one failing EvalResult and a pending analysis."""
    run = EvalRun(
        id=uuid4(),
        project_id=test_project.id,
        name="test run",
        total=1,
        passed=0,
        failed=1,
    )
    db_session.add(run)
    await db_session.flush()

    result = EvalResult(
        id=uuid4(),
        run_id=run.id,
        test_id="t1",
        pass_=False,
        input="what is 2+2?",
        output="5",
        expected_output="4",
        reason="wrong math",
    )
    db_session.add(result)

    analysis = OpenCodeAnalysis(
        id=uuid4(),
        project_id=test_project.id,
        eval_run_id=run.id,
        status="pending",
        analysis_mode="quick",
    )
    db_session.add(analysis)
    await db_session.commit()
    await db_session.refresh(analysis)
    return run, analysis


@pytest.mark.asyncio
async def test_analyze_eval_run_persists_suggestions(
    db_session,
    test_project: Project,
    eval_run_with_failure,
    monkeypatch,
):
    run, analysis = eval_run_with_failure

    canned_output = {
        "failure_summary": "Math reasoning fails on simple addition.",
        "files_analyzed": [],
        "suggestions": [
            {
                "type": "prompt_change",
                "title": "Tighten arithmetic system prompt",
                "description": "Add 'show your work' to the system prompt.",
                "file_path": None,
                "line_start": None,
                "line_end": None,
                "diff": None,
                "impact": "high",
                "confidence": 0.8,
                "reasoning": "Failures cluster around arithmetic.",
                "related_test_ids": ["t1"],
            }
        ],
    }

    def fake_build_model(**_kwargs):
        # `model_name` is what the service records on the LlmUsageRecord.
        return TestModel(call_tools=[], custom_output_args=canned_output, model_name="gpt-4o")

    monkeypatch.setattr(code_agent_service, "_build_model", fake_build_model)

    # `db_factory` is called as an async context manager. The test fixture only
    # exposes a single live session, so wrap it in a tiny context that yields it.
    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    await analyze_eval_run(
        project_id=test_project.id,
        eval_run_id=run.id,
        analysis_id=analysis.id,
        db_factory=_Factory(),
        repo_path=None,
        provider="openai",
        model="gpt-4o",
        api_key="sk-test",
        mode="quick",
    )

    await db_session.refresh(analysis)
    assert analysis.status == "completed"
    assert analysis.failure_summary == "Math reasoning fails on simple addition."
    assert analysis.suggestion_count == 1

    suggestions = (
        await db_session.execute(
            select(CodeSuggestion).where(CodeSuggestion.analysis_id == analysis.id)
        )
    ).scalars().all()
    assert len(suggestions) == 1
    assert suggestions[0].title == "Tighten arithmetic system prompt"

    usage_rows = (
        await db_session.execute(
            select(LlmUsageRecord).where(LlmUsageRecord.project_id == test_project.id)
        )
    ).scalars().all()
    assert len(usage_rows) == 1
    usage = usage_rows[0]
    assert usage.provider == "openai"
    assert usage.model == "gpt-4o"
    assert usage.input_tokens > 0
    assert usage.output_tokens > 0
    assert usage.total_tokens == usage.input_tokens + usage.output_tokens


# ── Router validation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_router_falls_back_when_provider_is_legacy(
    client,
    db_session,
    test_project: Project,
    auth_headers,
    monkeypatch,
    tmp_path: Path,
):
    # Stash a legacy provider value on the project settings — should be
    # silently coerced to 'anthropic' (mirroring the Settings UI fallback)
    # rather than rejected, so users aren't blocked by a stored value the
    # UI no longer surfaces to them.
    test_project.settings = {
        "code_agent_provider": "azure_foundry",
        "code_agent_api_key": "sk-fake",
        "code_agent_repo_path": str(tmp_path),
    }
    await db_session.commit()

    captured: dict[str, object] = {}

    async def fake_analyze_eval_run(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "app.routers.code_agent.analyze_eval_run", fake_analyze_eval_run
    )

    run = EvalRun(
        id=uuid4(),
        project_id=test_project.id,
        name="r",
        total=0,
        passed=0,
        failed=0,
    )
    db_session.add(run)
    await db_session.commit()

    resp = await client.post(
        f"/api/code-agent/{run.id}/analyze",
        headers={**auth_headers, "X-Project-Id": str(test_project.id)},
        json={"analysis_mode": "quick"},
    )
    assert resp.status_code == 202
    assert captured.get("provider") == "anthropic"
