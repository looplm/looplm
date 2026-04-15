"""Code Agent service — eval-driven code suggestions via Claude Agent SDK."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.evaluations import EvalResult, EvalRun
from app.models.code_agent import CodeSuggestion, OpenCodeAnalysis
from app.schemas.code_agent import (
    AgentAnalysisOutput,
    CodeSuggestionItem,
    OpenCodeAnalysisResponse,
)

logger = logging.getLogger(__name__)

# ── System prompts ────────────────────────────────────────────

OPENCODE_SYSTEM_PROMPT = """\
You are an expert LLM application debugger. You are given a set of evaluation \
test failures from an LLM-powered application. Your job is to:

1. Analyze the failure patterns — identify common root causes, cluster similar failures.
2. Explore the codebase to find the relevant source code (prompts, retrieval logic, \
tool definitions, configuration files).
3. Generate specific, actionable code suggestions with exact file paths, line numbers, \
and before/after diffs that would fix or improve the failing tests.

Focus on high-impact changes. Prioritize suggestions that would fix the most test failures. \
Each suggestion should reference the specific test IDs it addresses.

For each suggestion, classify its type:
- prompt_change: modifications to system prompts, user prompts, or prompt templates
- code_fix: bug fixes in application logic
- config_change: configuration parameter adjustments
- architecture_change: structural improvements to the LLM pipeline"""

OPENCODE_SYSTEM_PROMPT_NO_REPO = """\
You are an expert LLM application debugger. You are given a set of evaluation \
test failures from an LLM-powered application. Your job is to:

1. Analyze the failure patterns — identify common root causes, cluster similar failures.
2. Generate actionable suggestions for improving the application based on the failures. \
Since you do not have access to the codebase, provide general recommendations for \
prompt changes, configuration adjustments, and architectural improvements.

Focus on high-impact changes. Prioritize suggestions that would fix the most test failures. \
Each suggestion should reference the specific test IDs it addresses.

For each suggestion, classify its type:
- prompt_change: modifications to system prompts, user prompts, or prompt templates
- code_fix: bug fixes in application logic
- config_change: configuration parameter adjustments
- architecture_change: structural improvements to the LLM pipeline

Since you cannot see the code, set file_path to null and diff to null for all suggestions."""

OPENCODE_SYSTEM_PROMPT_QUICK = """\
You are an expert LLM application debugger. You are given evaluation test failures \
from an LLM-powered application. Provide a quick, high-level analysis:

1. Briefly summarize the failure patterns (2-3 sentences).
2. List the top 3-5 most impactful suggestions that would fix the most failures. \
Keep each suggestion concise — title, short description, and impact level.

Do NOT explore the codebase deeply. Focus on the most obvious and impactful fixes. \
Each suggestion should reference the specific test IDs it addresses.

For each suggestion, classify its type:
- prompt_change: modifications to system prompts, user prompts, or prompt templates
- code_fix: bug fixes in application logic
- config_change: configuration parameter adjustments
- architecture_change: structural improvements to the LLM pipeline

Set file_path and diff to null unless you are certain of the exact file and change."""


# ── Prompt building ───────────────────────────────────────────

def _build_agent_prompt(
    failed_results: list[EvalResult],
    run: EvalRun,
    extra_context: str = "",
    file_patterns: list[str] | None = None,
) -> str:
    """Build the user prompt with eval failure context."""
    lines = [
        f"## Evaluation Run: {run.name}",
        f"Total: {run.total} | Passed: {run.passed} | Failed: {run.failed}",
        "",
    ]

    if run.grader_summary:
        lines.append("### Grader Summary")
        lines.append(json.dumps(run.grader_summary, indent=2, default=str))
        lines.append("")

    lines.append(f"### Failed Test Cases ({len(failed_results)} failures)")
    lines.append("")

    for result in failed_results[:50]:  # Cap to avoid excessive token usage
        lines.append(f"#### Test: {result.test_id}")
        if result.input:
            lines.append(f"**Input:** {result.input[:1000]}")
        if result.output:
            lines.append(f"**Output:** {result.output[:1000]}")
        if result.expected_output:
            lines.append(f"**Expected:** {result.expected_output[:1000]}")
        if result.reason:
            lines.append(f"**Reason:** {result.reason[:500]}")
        if result.graders:
            lines.append(f"**Graders:** {json.dumps(result.graders, default=str)}")
        lines.append("")

    if len(failed_results) > 50:
        lines.append(f"... and {len(failed_results) - 50} more failures (showing first 50)")
        lines.append("")

    if file_patterns:
        lines.append("### Suggested file patterns to explore")
        for pattern in file_patterns:
            lines.append(f"- `{pattern}`")
        lines.append("")

    if extra_context:
        lines.append("### Additional Context")
        lines.append(extra_context)
        lines.append("")

    lines.append(
        "Analyze these failures and provide your suggestions. "
        "Be specific and actionable."
    )

    return "\n".join(lines)


# ── Core analysis ─────────────────────────────────────────────

async def _update_progress(
    db: AsyncSession,
    analysis: OpenCodeAnalysis,
    *,
    num_turns: int | None = None,
    total_cost_usd: float | None = None,
    progress_message: str | None = None,
    log_entry: str | None = None,
) -> None:
    """Persist live progress fields so the polling frontend can display them."""
    if num_turns is not None:
        analysis.num_turns = num_turns
    if total_cost_usd is not None:
        analysis.total_cost_usd = total_cost_usd
    if progress_message is not None:
        analysis.progress_message = progress_message
    if log_entry is not None:
        from sqlalchemy.orm.attributes import flag_modified
        log = list(analysis.progress_log or [])
        log.append({
            "t": datetime.now(timezone.utc).isoformat(),
            "msg": log_entry,
        })
        # Keep last 50 entries to avoid bloat
        analysis.progress_log = log[-50:]
        flag_modified(analysis, "progress_log")
    await db.commit()


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
    foundry_resource: str | None = None,
    mode: str = "detailed",
) -> None:
    """Run Claude agent to analyze eval failures. Designed to run as a background task."""
    import asyncio

    async with db_factory() as db:
        # Update status to running
        analysis = await db.get(OpenCodeAnalysis, analysis_id)
        if not analysis:
            logger.error("OpenCodeAnalysis %s not found", analysis_id)
            return
        analysis.status = "running"
        analysis.started_at = datetime.now(timezone.utc)
        analysis.progress_message = "Preparing analysis..."
        await db.commit()

        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
            # Load eval run and failed results
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

            # Build prompt
            prompt = _build_agent_prompt(
                failed_results, run, extra_context, file_patterns
            )

            await _update_progress(
                db, analysis,
                progress_message=f"Analyzing {len(failed_results)} failure(s)...",
            )

            # Build env vars for the Agent SDK subprocess (avoid mutating os.environ)
            sdk_env: dict[str, str] = {}
            if provider == "azure_foundry":
                sdk_env["CLAUDE_CODE_USE_FOUNDRY"] = "1"
                if api_key:
                    sdk_env["ANTHROPIC_FOUNDRY_API_KEY"] = api_key
                if foundry_resource:
                    sdk_env["ANTHROPIC_FOUNDRY_RESOURCE"] = foundry_resource
                # Clear any inherited direct API key so CLI doesn't use it
                sdk_env["ANTHROPIC_API_KEY"] = ""
            else:
                sdk_env["CLAUDE_CODE_USE_FOUNDRY"] = ""
                if api_key:
                    sdk_env["ANTHROPIC_API_KEY"] = api_key

            try:
                # Configure agent based on mode and repo availability
                is_quick = mode == "quick"
                common_opts: dict = {
                    "permission_mode": "bypassPermissions",
                    "output_format": {
                        "type": "json_schema",
                        "schema": AgentAnalysisOutput.model_json_schema(),
                    },
                    "env": sdk_env,
                }
                if model:
                    common_opts["model"] = model
                if is_quick:
                    common_opts["max_turns"] = 3
                    common_opts["max_budget_usd"] = 0.50

                if is_quick:
                    # Quick mode: no tool use, fast analysis
                    options = ClaudeAgentOptions(
                        allowed_tools=[],
                        system_prompt=OPENCODE_SYSTEM_PROMPT_QUICK,
                        **common_opts,
                    )
                elif repo_path:
                    options = ClaudeAgentOptions(
                        allowed_tools=["Read", "Glob", "Grep"],
                        cwd=repo_path,
                        system_prompt=OPENCODE_SYSTEM_PROMPT,
                        **common_opts,
                    )
                else:
                    options = ClaudeAgentOptions(
                        allowed_tools=[],
                        system_prompt=OPENCODE_SYSTEM_PROMPT_NO_REPO,
                        **common_opts,
                    )

                # Run the agent with progress tracking
                result_message = None
                turn_count = 0
                await _update_progress(
                    db, analysis,
                    progress_message="Agent started...",
                    log_entry="Agent session started",
                )
                from claude_agent_sdk.types import (
                    AssistantMessage as SDKAssistantMessage,
                    ResultMessage as SDKResultMessage,
                    SystemMessage as SDKSystemMessage,
                )

                async for message in query(prompt=prompt, options=options):
                    # ResultMessage — final result with cost/usage
                    if isinstance(message, SDKResultMessage):
                        result_message = message
                        continue

                    # AssistantMessage — agent thinking/tool use
                    if isinstance(message, SDKAssistantMessage):
                        turn_count += 1
                        log_msg = ""
                        progress_msg = f"Turn {turn_count}: Thinking..."

                        # Extract tool use or text from content blocks
                        for block in (message.content or []):
                            block_type = getattr(block, "type", None)
                            if block_type == "tool_use":
                                tool_name = getattr(block, "name", "tool")
                                inp = getattr(block, "input", {}) or {}
                                detail = ""
                                if isinstance(inp, dict):
                                    detail = inp.get("file_path") or inp.get("pattern") or inp.get("command", "")
                                log_msg = f"{tool_name}: {detail}" if detail else tool_name
                                progress_msg = f"Turn {turn_count}: {tool_name}..."
                                break
                            elif block_type == "text":
                                txt = getattr(block, "text", "")
                                if txt:
                                    log_msg = txt[:120].replace("\n", " ").strip()
                                break

                        if not log_msg:
                            log_msg = f"Turn {turn_count}"

                        await _update_progress(
                            db, analysis,
                            num_turns=turn_count,
                            progress_message=progress_msg,
                            log_entry=log_msg,
                        )
                        continue

                    # SystemMessage — metadata (init, subagent, etc.)
                    if isinstance(message, SDKSystemMessage):
                        subtype = message.subtype or "system"
                        data = message.data or {}
                        # Skip noisy system messages, log interesting ones
                        if subtype in ("init", "config"):
                            continue
                        if subtype == "api_retry":
                            error = data.get("error", "")
                            delay = data.get("delay", data.get("retry_after", ""))
                            log_msg = f"API retry: {error}" if error else "API retry"
                            if delay:
                                log_msg += f" (wait {delay}s)"
                            progress_msg = "Waiting for API..."
                        else:
                            log_msg = f"[{subtype}]"
                            if "message" in data:
                                log_msg += f" {str(data['message'])[:100]}"
                            progress_msg = None
                        await _update_progress(
                            db, analysis,
                            progress_message=progress_msg,
                            log_entry=log_msg,
                        )
                        continue

                    # UserMessage (tool results) — skip, not interesting for the user
            finally:
                pass  # env vars passed via options.env, no cleanup needed

            if not result_message:
                raise RuntimeError("Agent returned no result message")

            if getattr(result_message, "is_error", False):
                raise RuntimeError(
                    f"Agent error: {getattr(result_message, 'result', 'Unknown error')}"
                )

            # Parse structured output
            structured = getattr(result_message, "structured_output", None)
            if structured:
                output = AgentAnalysisOutput.model_validate(structured)
            else:
                # Fallback: try to parse from result text
                raw = getattr(result_message, "result", "")
                output = _parse_fallback_output(raw)

            # Persist results
            await _persist_results(
                analysis=analysis,
                output=output,
                project_id=project_id,
                result_message=result_message,
                db=db,
            )

        except asyncio.CancelledError:
            logger.info("Code Agent analysis cancelled for run %s", eval_run_id)
            analysis.status = "cancelled"
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


def _parse_fallback_output(raw: str) -> AgentAnalysisOutput:
    """Try to parse agent result text as JSON if structured output wasn't available."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()

    try:
        data = json.loads(text)
        return AgentAnalysisOutput.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Could not parse agent fallback output, returning empty")
        return AgentAnalysisOutput(
            failure_summary="Analysis completed but output could not be parsed.",
            suggestions=[],
            files_analyzed=[],
        )


async def _persist_results(
    analysis: OpenCodeAnalysis,
    output: AgentAnalysisOutput,
    project_id: UUID,
    result_message,
    db: AsyncSession,
) -> None:
    """Persist agent output as CodeSuggestion rows."""
    analysis.status = "completed"
    analysis.completed_at = datetime.now(timezone.utc)
    analysis.progress_message = None
    analysis.failure_summary = output.failure_summary
    analysis.files_analyzed = output.files_analyzed
    analysis.suggestion_count = len(output.suggestions)
    analysis.total_cost_usd = getattr(result_message, "total_cost_usd", None)
    analysis.num_turns = getattr(result_message, "num_turns", None)

    # Record in unified LLM usage table
    from app.models.llm_usage import LlmUsageRecord
    cost_usd = getattr(result_message, "total_cost_usd", None)
    if cost_usd is not None:
        db.add(LlmUsageRecord(
            project_id=project_id,
            service_name="code_agent",
            function_name="analyze_eval_run",
            provider="claude_agent_sdk",
            model=getattr(result_message, "model", "claude-sonnet-4-20250514"),
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            cost_usd=cost_usd,
            request_metadata={
                "analysis_id": str(analysis.id),
                "num_turns": getattr(result_message, "num_turns", None),
            },
        ))

    for suggestion in output.suggestions:
        row = CodeSuggestion(
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
        )
        db.add(row)

    await db.commit()


# ── Retrieval ─────────────────────────────────────────────────

async def get_analysis(
    eval_run_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> OpenCodeAnalysisResponse | None:
    """Get the latest OpenCode analysis for an eval run."""
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
