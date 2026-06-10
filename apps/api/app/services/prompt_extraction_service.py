"""Prompt extraction service — pull prompts out of a connected GitHub codebase.

Reuses the Code Agent's repo-reading agent (Pydantic AI + sandboxed glob/grep/read
tools) to locate prompt definitions, then upserts them into the prompts table under
the project's auto-created `github` integration. Runs as a background task with
live progress, mirroring `code_agent_service.analyze_eval_run`.
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
from pydantic_ai.usage import UsageLimits

from app.schemas.prompts import PromptExtractionOutput
from app.services.code_agent_helpers import _update_progress
from app.services.code_agent_prompts import PROMPT_EXTRACTION_SYSTEM_PROMPT
from app.services.code_agent_service import _build_model
from app.services.code_agent_tools import RepoContext, glob_files, grep_files, read_file
from app.services.llm_pricing import calculate_cost
from app.services.prompt_analysis import (
    get_or_create_github_integration,
    upsert_prompts_for_integration,
)

logger = logging.getLogger(__name__)

_EXTRACTION_REQUEST_LIMIT = 25
# Wall-clock safety net: the request_limit caps turns but not time. A slow or
# hung model turn would otherwise leave the run "stuck" forever — fail cleanly.
_EXTRACTION_TIMEOUT_SECONDS = 900
_USER_PROMPT = (
    "Find all LLM prompts defined in this repository and return them in the "
    "structured format. Start by grepping for common prompt signals, then read "
    "the most promising files to capture the full template text."
)


def _describe_activity(node: CallToolsNode) -> tuple[str, str]:
    """Turn a model response into a friendly (progress_message, log_entry).

    The extraction agent only returns the prompt list at the very end, so the
    live signal users can see is *what it is currently doing* — which files it
    reads and searches. Phrase those as plain English.
    """
    for part in node.model_response.parts:
        if isinstance(part, ToolCallPart):
            args = part.args_as_dict() if hasattr(part, "args_as_dict") else {}
            if not isinstance(args, dict):
                args = {}
            if part.tool_name == "read_file":
                path = args.get("path") or "a file"
                return f"Reading {path}", f"Read {path}"
            if part.tool_name == "grep_files":
                pattern = (args.get("pattern") or "").strip()
                return (
                    "Searching the code for prompts…",
                    f"Searched for: {pattern}"[:120] if pattern else "Searched the code",
                )
            if part.tool_name == "glob_files":
                pattern = (args.get("pattern") or "").strip()
                return (
                    "Looking for prompt files…",
                    f"Looked for files: {pattern}"[:120] if pattern else "Looked for files",
                )
            return f"Running {part.tool_name}…", part.tool_name
        if isinstance(part, TextPart) and part.content:
            snippet = part.content[:140].replace("\n", " ").strip()
            if snippet:
                return "Analyzing the codebase…", snippet
    return "Analyzing the codebase…", "Analyzing"


async def extract_prompts_from_repo(
    project_id: UUID,
    extraction_id: UUID,
    db_factory,
    repo_path: str,
    repo_full_name: str | None,
    provider: str,
    model: str | None,
    api_key: str | None,
    azure_endpoint: str | None = None,
    azure_api_version: str | None = None,
) -> None:
    """Run the extraction agent over a cloned repo. Designed as a background task."""
    async with db_factory() as db:
        from app.models.prompts import PromptExtraction

        extraction = await db.get(PromptExtraction, extraction_id)
        if not extraction:
            logger.error("PromptExtraction %s not found", extraction_id)
            return

        extraction.status = "running"
        extraction.started_at = datetime.now(timezone.utc)
        extraction.progress_message = "Preparing extraction..."
        await db.commit()

        try:
            llm_model = _build_model(
                provider=provider,
                model=model,
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                azure_api_version=azure_api_version,
            )

            agent = Agent(
                llm_model,
                output_type=PromptExtractionOutput,
                system_prompt=PROMPT_EXTRACTION_SYSTEM_PROMPT,
                deps_type=RepoContext,
                tools=(read_file, glob_files, grep_files),
            )
            deps = RepoContext(repo_root=Path(repo_path))
            usage_limits = UsageLimits(request_limit=_EXTRACTION_REQUEST_LIMIT)
            resolved_model_name = getattr(llm_model, "model_name", model or "")

            await _update_progress(
                db, extraction,
                progress_message="Scanning repository...",
                log_entry=f"Scanning {repo_full_name or repo_path}",
            )

            turn_count = 0

            async def _drive() -> tuple[PromptExtractionOutput | None, object]:
                nonlocal turn_count
                _output: PromptExtractionOutput | None = None
                _usage = None
                async with agent.iter(
                    _USER_PROMPT, deps=deps, usage_limits=usage_limits
                ) as run_ctx:
                    async for node in run_ctx:
                        if isinstance(node, ModelRequestNode):
                            turn_count += 1
                            await _update_progress(
                                db, extraction,
                                num_turns=turn_count,
                                progress_message="Reading the codebase…" if turn_count == 1
                                else "Analyzing the codebase…",
                            )
                        elif isinstance(node, CallToolsNode):
                            progress_msg, log_msg = _describe_activity(node)
                            await _update_progress(
                                db, extraction,
                                progress_message=progress_msg,
                                log_entry=log_msg,
                            )
                    _output = run_ctx.result.output if run_ctx.result else None
                    _usage = run_ctx.result.usage if run_ctx.result else None
                return _output, _usage

            try:
                output, usage = await asyncio.wait_for(
                    _drive(), timeout=_EXTRACTION_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError as exc:
                minutes = _EXTRACTION_TIMEOUT_SECONDS // 60
                raise RuntimeError(
                    f"Extraction timed out after {minutes} minutes. The codebase may "
                    f"be very large — try again or point the Code Agent at a narrower repo."
                ) from exc

            if output is None:
                raise RuntimeError("Extraction agent returned no output")

            found = len(output.prompts)
            await _update_progress(
                db, extraction,
                progress_message=f"Found {found} prompt{'s' if found != 1 else ''} — saving…",
                log_entry=f"Found {found} prompt{'s' if found != 1 else ''}; saving",
            )

            count = await _persist_prompts(db, project_id, repo_full_name, output)

            await _record_usage(
                db,
                project_id=project_id,
                provider=provider,
                model_name=resolved_model_name,
                usage=usage,
                extraction_id=extraction_id,
                num_turns=turn_count,
            )

            extraction.status = "completed"
            extraction.completed_at = datetime.now(timezone.utc)
            extraction.progress_message = None
            extraction.summary = output.summary
            extraction.files_analyzed = output.files_analyzed
            extraction.extracted_count = count
            extraction.num_turns = turn_count
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
            extraction.total_cost_usd = (
                calculate_cost(resolved_model_name, input_tokens, output_tokens)
                if resolved_model_name else None
            )
            await db.commit()

        except asyncio.CancelledError:
            logger.info("Prompt extraction cancelled for project %s", project_id)
            extraction.status = "cancelled"
            extraction.completed_at = datetime.now(timezone.utc)
            extraction.progress_message = None
            await db.commit()
            raise

        except Exception as e:
            logger.exception("Prompt extraction failed for project %s", project_id)
            extraction.status = "failed"
            extraction.error = str(e)[:2000]
            extraction.completed_at = datetime.now(timezone.utc)
            extraction.progress_message = None
            await db.commit()


async def _persist_prompts(
    db,
    project_id: UUID,
    repo_full_name: str | None,
    output: PromptExtractionOutput,
) -> int:
    """Upsert the agent's extracted prompts under the github integration."""
    integration = await get_or_create_github_integration(project_id, db, repo_full_name)

    items: list[dict] = []
    seen: set[str] = set()
    for p in output.prompts:
        if not p.template.strip():
            continue
        external_id = f"{p.file_path}::{p.name}"[:512]
        if external_id in seen:
            continue
        seen.add(external_id)
        items.append({
            "external_id": external_id,
            "name": p.name[:512],
            "template": p.template,
            "version": 1,
            "variables": p.variables,
            "metadata": {
                "source": "github",
                "file_path": p.file_path,
                "line_start": p.line_start,
                "role": p.role,
                "repo": repo_full_name,
            },
        })

    count = await upsert_prompts_for_integration(integration.id, items, db)
    await db.commit()
    return count


async def _record_usage(
    db,
    *,
    project_id: UUID,
    provider: str,
    model_name: str,
    usage,
    extraction_id: UUID,
    num_turns: int,
) -> None:
    from app.models.llm_usage import LlmUsageRecord

    input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    db.add(LlmUsageRecord(
        project_id=project_id,
        service_name="prompt_extraction",
        function_name="extract_prompts_from_repo",
        provider=provider,
        model=model_name or "unknown",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cost_usd=calculate_cost(model_name, input_tokens, output_tokens) if model_name else None,
        request_metadata={"extraction_id": str(extraction_id), "num_turns": num_turns},
    ))
    await db.commit()
