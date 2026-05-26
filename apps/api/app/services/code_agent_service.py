"""Code Agent service — eval-driven code suggestions via Pydantic AI.

Replaces the previous Claude Agent SDK implementation. Supports OpenAI,
Anthropic, and Azure OpenAI as providers. Filesystem tools live in
`code_agent_tools.py` and are sandboxed to the configured repo path.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai._agent_graph import CallToolsNode, ModelRequestNode
from pydantic_ai.messages import TextPart, ToolCallPart
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.code_agent import CodeSuggestion, OpenCodeAnalysis
from app.models.evaluations import EvalResult, EvalRun
from app.schemas.code_agent import (
    AgentAnalysisOutput,
    CodeSuggestionItem,
    OpenCodeAnalysisResponse,
)
from app.services.code_agent_helpers import (
    _build_agent_prompt,
    _update_progress,
)
from app.services.code_agent_prompts import (
    OPENCODE_SYSTEM_PROMPT,
    OPENCODE_SYSTEM_PROMPT_NO_REPO,
    OPENCODE_SYSTEM_PROMPT_QUICK,
)
from app.services.code_agent_tools import (
    RepoContext,
    glob_files,
    grep_files,
    read_file,
)
from app.services.llm_pricing import calculate_cost

logger = logging.getLogger(__name__)


# Default model name per provider when the caller hasn't picked one.
_DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-20250514",
    # Azure has no sensible default — the deployment name is required.
    "azure_openai": None,
}

_QUICK_MODE_REQUEST_LIMIT = 3
_QUICK_MODE_OUTPUT_TOKEN_LIMIT = 4000
_DETAILED_MODE_REQUEST_LIMIT = 25


class CodeAgentConfigError(ValueError):
    """Raised when the per-project Code Agent configuration is invalid."""


def _build_model(
    provider: str,
    model: str | None,
    api_key: str | None,
    azure_endpoint: str | None = None,
    azure_api_version: str | None = None,
):
    """Construct a Pydantic AI model for the configured provider."""
    if provider == "openai":
        if not api_key:
            raise CodeAgentConfigError("OpenAI API key is required.")
        return OpenAIChatModel(
            model or _DEFAULT_MODELS["openai"],
            provider=OpenAIProvider(api_key=api_key),
        )

    if provider == "anthropic":
        if not api_key:
            raise CodeAgentConfigError("Anthropic API key is required.")
        return AnthropicModel(
            model or _DEFAULT_MODELS["anthropic"],
            provider=AnthropicProvider(api_key=api_key),
        )

    if provider == "azure_openai":
        if not api_key:
            raise CodeAgentConfigError("Azure OpenAI API key is required.")
        if not azure_endpoint:
            raise CodeAgentConfigError("Azure OpenAI endpoint is required.")
        if not azure_api_version:
            raise CodeAgentConfigError("Azure OpenAI API version is required.")
        if not model:
            raise CodeAgentConfigError("Azure OpenAI deployment name is required.")
        return OpenAIChatModel(
            model,
            provider=AzureProvider(
                azure_endpoint=azure_endpoint,
                api_version=azure_api_version,
                api_key=api_key,
            ),
        )

    raise CodeAgentConfigError(
        f"Unsupported Code Agent provider: {provider!r}. "
        "Reconfigure in Settings — supported values: openai, anthropic, azure_openai."
    )


async def analyze_eval_run(
    project_id: UUID,
    eval_run_id: UUID,
    analysis_id: UUID,
    db_factory,
    repo_path: str | None = None,
    extra_context: str = "",
    file_patterns: list[str] | None = None,
    provider: str = "anthropic",
    model: str | None = None,
    api_key: str | None = None,
    azure_endpoint: str | None = None,
    azure_api_version: str | None = None,
    mode: str = "detailed",
) -> None:
    """Run the Code Agent for an eval run. Designed to run as a background task."""
    async with db_factory() as db:
        analysis = await db.get(OpenCodeAnalysis, analysis_id)
        if not analysis:
            logger.error("OpenCodeAnalysis %s not found", analysis_id)
            return
        analysis.status = "running"
        analysis.started_at = datetime.now(timezone.utc)
        analysis.progress_message = "Preparing analysis..."
        await db.commit()

        try:
            # Load eval run + failed results
            run_result = await db.execute(
                select(EvalRun).where(
                    EvalRun.id == eval_run_id,
                    EvalRun.project_id == project_id,
                )
            )
            run = run_result.scalar_one_or_none()
            if not run:
                raise ValueError(f"Eval run {eval_run_id} not found")

            results_query = await db.execute(
                select(EvalResult)
                .where(EvalResult.run_id == eval_run_id, EvalResult.pass_ == False)  # noqa: E712
                .order_by(EvalResult.created_at)
            )
            failed_results = list(results_query.scalars().all())

            if not failed_results:
                analysis.status = "completed"
                analysis.completed_at = datetime.now(timezone.utc)
                analysis.failure_summary = "No failures found in this evaluation run."
                analysis.progress_message = None
                await db.commit()
                return

            prompt = _build_agent_prompt(failed_results, run, extra_context, file_patterns)

            await _update_progress(
                db, analysis,
                progress_message=f"Analyzing {len(failed_results)} failure(s)...",
            )

            llm_model = _build_model(
                provider=provider,
                model=model,
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                azure_api_version=azure_api_version,
            )

            is_quick = mode == "quick"
            if is_quick:
                system_prompt = OPENCODE_SYSTEM_PROMPT_QUICK
                tools = ()
            elif repo_path:
                system_prompt = OPENCODE_SYSTEM_PROMPT
                tools = (read_file, glob_files, grep_files)
            else:
                system_prompt = OPENCODE_SYSTEM_PROMPT_NO_REPO
                tools = ()

            agent = Agent(
                llm_model,
                output_type=AgentAnalysisOutput,
                system_prompt=system_prompt,
                deps_type=RepoContext,
                tools=tools,
            )

            deps = RepoContext(repo_root=Path(repo_path) if repo_path and not is_quick else None)
            usage_limits = UsageLimits(
                request_limit=_QUICK_MODE_REQUEST_LIMIT if is_quick else _DETAILED_MODE_REQUEST_LIMIT,
                output_tokens_limit=_QUICK_MODE_OUTPUT_TOKEN_LIMIT if is_quick else None,
            )

            access_log = _describe_code_access(
                is_quick=is_quick, repo_path=repo_path, deps=deps
            )
            await _update_progress(db, analysis, log_entry=access_log)

            await _update_progress(
                db, analysis,
                progress_message="Agent started...",
                log_entry="Agent session started",
            )

            turn_count = 0
            agent_output: AgentAnalysisOutput | None = None
            usage = None
            resolved_model_name = getattr(llm_model, "model_name", model or "")

            async with agent.iter(prompt, deps=deps, usage_limits=usage_limits) as run_ctx:
                async for node in run_ctx:
                    if isinstance(node, ModelRequestNode):
                        turn_count += 1
                        await _update_progress(
                            db, analysis,
                            num_turns=turn_count,
                            progress_message=f"Turn {turn_count}: Thinking...",
                            log_entry=f"Turn {turn_count}",
                        )
                    elif isinstance(node, CallToolsNode):
                        log_msg, progress_msg = _summarize_model_response(node, turn_count)
                        await _update_progress(
                            db, analysis,
                            progress_message=progress_msg,
                            log_entry=log_msg,
                        )
                agent_output = run_ctx.result.output if run_ctx.result else None
                usage = run_ctx.result.usage if run_ctx.result else None

            if agent_output is None:
                raise RuntimeError("Agent returned no output")

            await _persist_results(
                analysis=analysis,
                output=agent_output,
                project_id=project_id,
                usage=usage,
                provider=provider,
                model_name=resolved_model_name,
                num_turns=turn_count,
                db=db,
            )

        except asyncio.CancelledError:
            logger.info("Code Agent analysis cancelled for run %s", eval_run_id)
            analysis.status = "cancelled"
            analysis.completed_at = datetime.now(timezone.utc)
            analysis.progress_message = None
            await db.commit()
            raise

        except CodeAgentConfigError as e:
            logger.warning("Code Agent config error for run %s: %s", eval_run_id, e)
            analysis.status = "failed"
            analysis.error = str(e)[:2000]
            analysis.completed_at = datetime.now(timezone.utc)
            analysis.progress_message = None
            await db.commit()

        except Exception as e:
            logger.exception("Code Agent analysis failed for run %s", eval_run_id)
            analysis.status = "failed"
            analysis.error = str(e)[:2000]
            analysis.completed_at = datetime.now(timezone.utc)
            analysis.progress_message = None
            await db.commit()


def _describe_code_access(
    *, is_quick: bool, repo_path: str | None, deps: RepoContext
) -> str:
    """Produce a single log line telling the user whether the agent can read code.

    Surfaces the configured repo, missing-path errors, and quick-mode (no tools)
    up front so users don't have to guess from later turns whether the model
    actually has filesystem access.
    """
    if is_quick:
        return "Code access: disabled — quick mode (model reasons from failure context only)"
    if not repo_path:
        return "Code access: disabled — no repository configured for this project"
    root = deps.repo_root
    if root is None or not root.exists() or not root.is_dir():
        return f"Code access: unavailable — path not found: {repo_path}"
    try:
        top_entries = sum(1 for _ in root.iterdir())
    except OSError as exc:
        return f"Code access: unavailable — {repo_path} ({exc.strerror or exc})"
    return f"Code access: enabled — {root} ({top_entries} top-level entries)"


def _summarize_model_response(node: CallToolsNode, turn_count: int) -> tuple[str, str | None]:
    """Extract a one-line log + progress message from a model response node."""
    model_response = node.model_response
    log_msg = f"Turn {turn_count}"
    progress_msg: str | None = f"Turn {turn_count}: Thinking..."

    for part in model_response.parts:
        if isinstance(part, ToolCallPart):
            args = part.args_as_dict() if hasattr(part, "args_as_dict") else {}
            if not isinstance(args, dict):
                args = {}
            detail = (
                args.get("path")
                or args.get("pattern")
                or args.get("path_glob")
                or ""
            )
            log_msg = f"{part.tool_name}: {detail}" if detail else part.tool_name
            progress_msg = f"Turn {turn_count}: {part.tool_name}..."
            break
        if isinstance(part, TextPart) and part.content:
            log_msg = part.content[:120].replace("\n", " ").strip() or log_msg
            break

    return log_msg, progress_msg


async def _persist_results(
    analysis: OpenCodeAnalysis,
    output: AgentAnalysisOutput,
    project_id: UUID,
    usage,
    provider: str,
    model_name: str,
    num_turns: int,
    db: AsyncSession,
) -> None:
    """Persist agent output as CodeSuggestion rows + an LlmUsageRecord."""
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    total_tokens = input_tokens + output_tokens
    cost_usd = calculate_cost(model_name, input_tokens, output_tokens) if model_name else None

    analysis.status = "completed"
    analysis.completed_at = datetime.now(timezone.utc)
    analysis.progress_message = None
    analysis.failure_summary = output.failure_summary
    analysis.files_analyzed = output.files_analyzed
    analysis.suggestion_count = len(output.suggestions)
    analysis.total_cost_usd = cost_usd
    analysis.num_turns = num_turns

    from app.models.llm_usage import LlmUsageRecord
    db.add(LlmUsageRecord(
        project_id=project_id,
        service_name="code_agent",
        function_name="analyze_eval_run",
        provider=provider,
        model=model_name or "unknown",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        request_metadata={
            "analysis_id": str(analysis.id),
            "num_turns": num_turns,
        },
    ))

    for suggestion in output.suggestions:
        db.add(CodeSuggestion(
            analysis_id=analysis.id,
            project_id=project_id,
            type=suggestion.type,
            title=suggestion.title,
            description=suggestion.description,
            file_path=suggestion.file_path,
            line_start=suggestion.line_start,
            line_end=suggestion.line_end,
            diff=suggestion.diff,
            impact=suggestion.impact,
            confidence=suggestion.confidence,
            reasoning=suggestion.reasoning,
            related_test_ids=suggestion.related_test_ids,
        ))

    await db.commit()


# ── Retrieval ─────────────────────────────────────────────────

async def get_analysis(
    eval_run_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> OpenCodeAnalysisResponse | None:
    """Get the latest analysis for an eval run."""
    stmt = (
        select(OpenCodeAnalysis)
        .where(
            OpenCodeAnalysis.eval_run_id == eval_run_id,
            OpenCodeAnalysis.project_id == project_id,
        )
        .options(selectinload(OpenCodeAnalysis.suggestions))
        .order_by(OpenCodeAnalysis.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    analysis = result.scalar_one_or_none()
    if not analysis:
        return None

    suggestions = [
        CodeSuggestionItem.model_validate(s) for s in analysis.suggestions
    ]

    return OpenCodeAnalysisResponse(
        id=analysis.id,
        eval_run_id=analysis.eval_run_id,
        status=analysis.status,
        error=analysis.error,
        files_analyzed=analysis.files_analyzed or [],
        failure_summary=analysis.failure_summary,
        suggestion_count=analysis.suggestion_count,
        suggestions=suggestions,
        total_cost_usd=analysis.total_cost_usd,
        num_turns=analysis.num_turns,
        analysis_mode=analysis.analysis_mode,
        progress_message=analysis.progress_message,
        progress_log=analysis.progress_log or [],
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
    )


async def update_suggestion_status(
    suggestion_id: UUID,
    project_id: UUID,
    status: str,
    db: AsyncSession,
) -> CodeSuggestionItem | None:
    """Update a code suggestion's status (apply/dismiss)."""
    stmt = select(CodeSuggestion).where(
        CodeSuggestion.id == suggestion_id,
        CodeSuggestion.project_id == project_id,
    )
    result = await db.execute(stmt)
    suggestion = result.scalar_one_or_none()
    if not suggestion:
        return None

    suggestion.status = status
    await db.commit()
    await db.refresh(suggestion)
    return CodeSuggestionItem.model_validate(suggestion)
