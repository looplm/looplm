"""Repo-aware architecture advisor — agentic analysis via Pydantic AI.

The opt-in counterpart to the synchronous graph-only advisor in
`architecture_advisor.py`. Given an execution graph derived from traces, it lets
an LLM explore the project's connected code repository (the same sandboxed
filesystem tools the Code Agent uses) to ground architecture suggestions in the
actual code, then persists them in the existing `advisor_analyses` shape.

Designed to run as an asyncio background task (mirrors `analyze_eval_run`).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai._agent_graph import CallToolsNode, ModelRequestNode
from pydantic_ai.usage import UsageLimits
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AdvisorAnalysis
from app.schemas.advisor import AdvisorAgentOutput, AdvisorRunResponse, Suggestion
from app.services.architecture_advisor import _build_prompt
from app.services.code_agent_service import (
    CodeAgentConfigError,
    _build_model,
    _summarize_model_response,
)
from app.services.code_agent_helpers import _update_progress
from app.services.code_agent_tools import RepoContext, glob_files, grep_files, read_file
from app.services.llm_pricing import calculate_cost
from app.services.route_analysis import get_route_analysis

logger = logging.getLogger(__name__)

_REQUEST_LIMIT = 25


ADVISOR_AGENT_SYSTEM_PROMPT = """\
You are an expert LLM application architect with read-only access to the \
application's source code. You are given an execution graph derived from \
production traces, plus tools to explore the codebase.

Graph semantics: each node has a `name` (a developer-instrumented span label, \
e.g. `search_tool`, `agent_chain`, `gpt4_call`) and an `id` of the form \
`{name}::{type}` where type is one of llm/tool/retriever/chain/agent. The graph \
carries NO source-code locations — you must correlate nodes to code yourself.

Your job:
1. Study the execution graph — latencies, error rates, call counts, fan-out, loops.
2. Use the tools to find the code behind the nodes: `grep_files` for the node \
names and related symbols, then `read_file` to understand routing, prompts, \
retrieval, error handling, and how steps are wired together.
3. Produce concrete architecture suggestions grounded in what the code actually \
does. Only claim something the graph data or the code you read supports — cite \
the relevant files in your reasoning.

Provide suggestions in these categories:
- time_to_value — latency reduction, caching, parallelization
- output_quality — prompt improvements, loop reduction
- architecture — node consolidation, better routing, error handling

For each suggestion set: title, description, category, impact (high|medium|low), \
confidence (0.0-1.0), and reasoning (reference the files/nodes you used). Also \
return the list of files you read in `files_analyzed`."""


async def analyze_architecture_with_repo(
    integration_id: UUID,
    project_id: UUID,
    analysis_id: UUID,
    db_factory,
    repo_path: str | None,
    extra_context: str = "",
    provider: str = "anthropic",
    model: str | None = None,
    api_key: str | None = None,
    azure_endpoint: str | None = None,
    azure_api_version: str | None = None,
) -> None:
    """Run repo-aware architecture analysis. Designed to run as a background task."""
    async with db_factory() as db:
        analysis = await db.get(AdvisorAnalysis, analysis_id)
        if not analysis:
            logger.error("AdvisorAnalysis %s not found", analysis_id)
            return
        analysis.status = "running"
        analysis.started_at = datetime.now(timezone.utc)
        analysis.repo_used = bool(repo_path)
        analysis.progress_message = "Building execution graph..."
        await db.commit()

        try:
            route_data = await get_route_analysis(integration_id, project_id, db)
            route_dict = route_data.model_dump()

            prompt = _build_prompt(route_dict)
            if extra_context:
                prompt += f"\n\nAdditional context: {extra_context}"
            prompt += (
                "\n\nUse the repository tools to correlate the graph nodes to the "
                "actual code before drawing conclusions."
            )

            llm_model = _build_model(
                provider=provider,
                model=model,
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                azure_api_version=azure_api_version,
            )

            agent = Agent(
                llm_model,
                output_type=AdvisorAgentOutput,
                system_prompt=ADVISOR_AGENT_SYSTEM_PROMPT,
                deps_type=RepoContext,
                tools=(read_file, glob_files, grep_files),
            )
            deps = RepoContext(repo_root=Path(repo_path) if repo_path else None)
            usage_limits = UsageLimits(request_limit=_REQUEST_LIMIT)

            await _update_progress(
                db, analysis,
                progress_message="Agent started...",
                log_entry="Agent session started",
            )

            turn_count = 0
            agent_output: AdvisorAgentOutput | None = None
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
                integration_id=integration_id,
                usage=usage,
                provider=provider,
                model_name=resolved_model_name,
                num_turns=turn_count,
                db=db,
            )

        except asyncio.CancelledError:
            logger.info("Advisor analysis cancelled for integration %s", integration_id)
            analysis.status = "cancelled"
            analysis.completed_at = datetime.now(timezone.utc)
            analysis.progress_message = None
            await db.commit()
            raise

        except CodeAgentConfigError as e:
            logger.warning("Advisor config error for integration %s: %s", integration_id, e)
            analysis.status = "failed"
            analysis.error = str(e)[:2000]
            analysis.completed_at = datetime.now(timezone.utc)
            analysis.progress_message = None
            await db.commit()

        except ValueError as e:
            # e.g. integration not found from get_route_analysis
            logger.warning("Advisor analysis value error for %s: %s", integration_id, e)
            analysis.status = "failed"
            analysis.error = str(e)[:2000]
            analysis.completed_at = datetime.now(timezone.utc)
            analysis.progress_message = None
            await db.commit()

        except Exception as e:
            logger.exception("Advisor analysis failed for integration %s", integration_id)
            analysis.status = "failed"
            analysis.error = str(e)[:2000]
            analysis.completed_at = datetime.now(timezone.utc)
            analysis.progress_message = None
            await db.commit()


async def _persist_results(
    analysis: AdvisorAnalysis,
    output: AdvisorAgentOutput,
    project_id: UUID,
    integration_id: UUID,
    usage,
    provider: str,
    model_name: str,
    num_turns: int,
    db: AsyncSession,
) -> None:
    """Persist agent suggestions into advisor_analyses + an LlmUsageRecord."""
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    total_tokens = input_tokens + output_tokens
    cost_usd = calculate_cost(model_name, input_tokens, output_tokens) if model_name else None

    # Map agent suggestions to the canonical Suggestion shape stored as JSONB
    # (same shape get_latest_suggestions / the legacy GET read back).
    suggestions = [
        Suggestion(
            title=s.title,
            description=s.description,
            category=s.category,
            impact=s.impact,
            confidence=s.confidence,
            reasoning=s.reasoning,
        ).model_dump()
        for s in output.suggestions
    ]

    analysis.status = "completed"
    analysis.completed_at = datetime.now(timezone.utc)
    analysis.progress_message = None
    analysis.suggestions = suggestions
    analysis.files_analyzed = output.files_analyzed
    analysis.num_turns = num_turns
    analysis.total_cost_usd = cost_usd
    analysis.analyzed_at = datetime.now(timezone.utc)

    from app.models.llm_usage import LlmUsageRecord
    db.add(LlmUsageRecord(
        project_id=project_id,
        service_name="architecture_advisor",
        function_name="analyze_architecture_with_repo",
        provider=provider,
        model=model_name or "unknown",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        request_metadata={
            "analysis_id": str(analysis.id),
            "integration_id": str(integration_id),
            "num_turns": num_turns,
        },
    ))

    await db.commit()


async def get_advisor_run(
    integration_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> AdvisorRunResponse | None:
    """Return the most recent advisor run (any status) for polling."""
    stmt = (
        select(AdvisorAnalysis)
        .where(
            AdvisorAnalysis.integration_id == integration_id,
            AdvisorAnalysis.project_id == project_id,
        )
        .order_by(AdvisorAnalysis.created_at.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None

    suggestions = [Suggestion(**item) for item in (row.suggestions or [])]
    return AdvisorRunResponse(
        id=row.id,
        integration_id=str(integration_id),
        status=row.status or "completed",
        suggestions=suggestions,
        error=row.error,
        files_analyzed=list(row.files_analyzed or []),
        num_turns=row.num_turns,
        total_cost_usd=row.total_cost_usd,
        repo_used=bool(row.repo_used),
        progress_message=row.progress_message,
        progress_log=list(row.progress_log or []),
        started_at=row.started_at,
        completed_at=row.completed_at,
        analyzed_at=row.analyzed_at,
    )
