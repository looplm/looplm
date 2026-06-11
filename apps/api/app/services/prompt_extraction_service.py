"""Prompt extraction service — pull prompts out of a connected GitHub codebase.

Two-phase pipeline, both phases reusing the Code Agent's sandboxed repo tools
(Pydantic AI + glob/grep/read):

1. Discover — one agent run returns a lightweight *list of prompt locations*
   (name + file + line), not the template text. Small output → fast.
2. Extract — for each location, a focused agent run reads just that spot and
   returns the single prompt verbatim. Each prompt is persisted as it is found,
   so they appear in the UI one by one and a slow prompt can't stall the rest.

Runs as a background task with live progress, mirroring
`code_agent_service.analyze_eval_run`.
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
from sqlalchemy import select

from app.models.models import Prompt
from app.schemas.prompts import ExtractedPrompt, PromptLocation, PromptLocationList
from app.services.code_agent_helpers import _update_progress
from app.services.code_agent_prompts import (
    PROMPT_DISCOVERY_SYSTEM_PROMPT,
    PROMPT_EXTRACT_ONE_SYSTEM_PROMPT,
)
from app.services.code_agent_service import _build_model
from app.services.code_agent_tools import RepoContext, glob_files, grep_files, read_file
from app.services.llm_pricing import calculate_cost
from app.services.prompt_analysis import (
    get_excluded_ids,
    get_or_create_github_integration,
    upsert_prompts_for_integration,
)

logger = logging.getLogger(__name__)

_DISCOVERY_REQUEST_LIMIT = 25
_EXTRACT_ONE_REQUEST_LIMIT = 6
_MAX_PROMPTS = 100  # safety cap on how many locations we extract in one run
# Wall-clock safety net: request limits cap turns but not time. A slow or hung
# model turn would otherwise leave the run "stuck" forever — fail cleanly.
_EXTRACTION_TIMEOUT_SECONDS = 900

_DISCOVERY_PROMPT = (
    "Locate every LLM prompt defined in this repository and return the list of "
    "locations (name, file, line) — do not include the template text yet."
)


def _tokens(usage) -> tuple[int, int]:
    if not usage:
        return 0, 0
    return (
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
    )


def _describe_activity(node: CallToolsNode) -> tuple[str, str]:
    """Turn a model response into a friendly (progress_message, log_entry).

    The live signal users can see is *what the agent is doing* — which files it
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


def _make_extract_agent(llm_model) -> Agent:
    """Agent that reads one location and returns a single prompt verbatim."""
    return Agent(
        llm_model,
        output_type=ExtractedPrompt,
        system_prompt=PROMPT_EXTRACT_ONE_SYSTEM_PROMPT,
        deps_type=RepoContext,
        tools=(read_file, grep_files),
    )


async def _discover_locations(
    agent: Agent,
    deps: RepoContext,
    usage_limits: UsageLimits,
    *,
    db,
    extraction,
) -> tuple[PromptLocationList | None, object]:
    """Phase 1: locate prompts, streaming tool activity into the progress feed."""
    turn = 0
    async with agent.iter(_DISCOVERY_PROMPT, deps=deps, usage_limits=usage_limits) as ctx:
        async for node in ctx:
            if isinstance(node, ModelRequestNode):
                turn += 1
                await _update_progress(
                    db, extraction,
                    progress_message="Scanning the codebase…" if turn == 1
                    else "Looking for prompts…",
                )
            elif isinstance(node, CallToolsNode):
                progress_msg, log_msg = _describe_activity(node)
                await _update_progress(
                    db, extraction, progress_message=progress_msg, log_entry=log_msg
                )
        output = ctx.result.output if ctx.result else None
        usage = ctx.result.usage if ctx.result else None
    return output, usage


async def _extract_one(
    agent: Agent,
    deps: RepoContext,
    loc: PromptLocation,
    usage_limits: UsageLimits,
) -> tuple[ExtractedPrompt | None, object]:
    """Phase 2: read one location and return the single prompt verbatim."""
    user = (
        f"Extract the prompt named {loc.name!r} defined in {loc.file_path}"
        + (f" around line {loc.line_start}." if loc.line_start else ".")
        + " Return its full template verbatim and its variables."
    )
    result = await agent.run(user, deps=deps, usage_limits=usage_limits)
    return result.output, result.usage


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
    """Run the discover→extract pipeline over a cloned repo. A background task."""
    async with db_factory() as db:
        from app.models.prompts import PromptExtraction

        extraction = await db.get(PromptExtraction, extraction_id)
        if not extraction:
            logger.error("PromptExtraction %s not found", extraction_id)
            return

        extraction.status = "running"
        extraction.started_at = datetime.now(timezone.utc)
        extraction.progress_message = "Preparing extraction…"
        await db.commit()

        total_in = 0
        total_out = 0

        try:
            llm_model = _build_model(
                provider=provider,
                model=model,
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                azure_api_version=azure_api_version,
            )
            resolved_model_name = getattr(llm_model, "model_name", model or "")
            deps = RepoContext(repo_root=Path(repo_path))

            discover_agent = Agent(
                llm_model,
                output_type=PromptLocationList,
                system_prompt=PROMPT_DISCOVERY_SYSTEM_PROMPT,
                deps_type=RepoContext,
                tools=(read_file, glob_files, grep_files),
            )
            extract_agent = _make_extract_agent(llm_model)
            discover_limits = UsageLimits(request_limit=_DISCOVERY_REQUEST_LIMIT)
            extract_limits = UsageLimits(request_limit=_EXTRACT_ONE_REQUEST_LIMIT)

            async def _drive() -> tuple[str, list[str], int]:
                nonlocal total_in, total_out

                # ── Phase 1: discover ──────────────────────────────
                await _update_progress(
                    db, extraction,
                    progress_message="Scanning the repository…",
                    log_entry=f"Scanning {repo_full_name or repo_path}",
                )
                loc_list, usage = await _discover_locations(
                    discover_agent, deps, discover_limits, db=db, extraction=extraction
                )
                di, do = _tokens(usage)
                total_in += di
                total_out += do

                locations = list(loc_list.locations) if loc_list else []
                if len(locations) > _MAX_PROMPTS:
                    await _update_progress(
                        db, extraction,
                        log_entry=f"Found {len(locations)}; capping at {_MAX_PROMPTS}",
                    )
                    locations = locations[:_MAX_PROMPTS]

                total = len(locations)

                # ── Phase 2: extract one by one, persisting as we go ─
                integration = await get_or_create_github_integration(
                    project_id, db, repo_full_name
                )
                # Resume support: anything already saved under this integration is
                # skipped — re-runs continue where the last one left off without
                # spending an LLM call per already-extracted prompt.
                existing_ids = set(
                    (await db.execute(
                        select(Prompt.external_id).where(
                            Prompt.integration_id == integration.id
                        )
                    )).scalars().all()
                )

                def _ext_id(loc: PromptLocation) -> str:
                    return f"{loc.file_path}::{loc.name}"[:512]

                already = sum(1 for loc in locations if _ext_id(loc) in existing_ids)
                await _update_progress(
                    db, extraction,
                    progress_message=(
                        f"Resuming — {already} of {total} already saved, "
                        f"extracting {total - already}…"
                        if already
                        else f"Found {total} prompt{'s' if total != 1 else ''}"
                        " — extracting one by one…"
                    ),
                    log_entry=(
                        f"Resuming: {already}/{total} already saved"
                        if already
                        else f"Found {total} prompt location{'s' if total != 1 else ''}"
                    ),
                )

                seen: set[str] = set()
                for i, loc in enumerate(locations):
                    external_id = _ext_id(loc)
                    if external_id in seen:
                        continue

                    # Already extracted in a prior run — keep it, skip the LLM call.
                    if external_id in existing_ids:
                        seen.add(external_id)
                        extraction.extracted_count = len(seen)
                        await db.commit()
                        continue

                    await _update_progress(
                        db, extraction,
                        progress_message=f"Extracting {i + 1}/{total}: {loc.name}",
                        log_entry=f"{loc.name} — {loc.file_path}",
                    )
                    ep, usage = await _extract_one(extract_agent, deps, loc, extract_limits)
                    ei, eo = _tokens(usage)
                    total_in += ei
                    total_out += eo

                    template = ((ep.template if ep else "") or "").strip()
                    if not template:
                        await _update_progress(
                            db, extraction,
                            log_entry=f"· no prompt text found in {loc.file_path}",
                        )
                        continue

                    seen.add(external_id)
                    await upsert_prompts_for_integration(
                        integration.id,
                        [{
                            "external_id": external_id,
                            "name": loc.name[:512],
                            "template": ep.template,
                            "version": 1,
                            "variables": ep.variables,
                            "metadata": {
                                "source": "github",
                                "file_path": loc.file_path,
                                "line_start": ep.line_start or loc.line_start,
                                "role": ep.role or loc.role,
                                "note": loc.note,
                                "repo": repo_full_name,
                            },
                        }],
                        db,
                        delete_stale=False,
                    )
                    extraction.extracted_count = len(seen)
                    await db.commit()  # commit per prompt so it shows up live

                removed = await _prune_prompts(integration.id, seen, db)
                if removed:
                    await _update_progress(
                        db, extraction, log_entry=f"Removed {removed} stale prompt(s)"
                    )

                files = sorted({loc.file_path for loc in locations})
                summary = loc_list.summary if loc_list else ""
                return summary, files, len(seen)

            try:
                summary, files_analyzed, extracted = await asyncio.wait_for(
                    _drive(), timeout=_EXTRACTION_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError as exc:
                minutes = _EXTRACTION_TIMEOUT_SECONDS // 60
                raise RuntimeError(
                    f"Extraction timed out after {minutes} minutes. Prompts found so "
                    f"far were saved — re-run to continue, or narrow the repo."
                ) from exc

            await _record_usage(
                db,
                project_id=project_id,
                provider=provider,
                model_name=resolved_model_name,
                input_tokens=total_in,
                output_tokens=total_out,
                extraction_id=extraction_id,
            )

            extraction.status = "completed"
            extraction.completed_at = datetime.now(timezone.utc)
            extraction.progress_message = None
            extraction.summary = summary
            extraction.files_analyzed = files_analyzed
            extraction.extracted_count = extracted
            extraction.total_cost_usd = (
                calculate_cost(resolved_model_name, total_in, total_out)
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


def _loc_ext_id(file_path: str, name: str) -> str:
    return f"{file_path}::{name}"[:512]


async def discover_repo_prompts(
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
    """Phase 1 only: discover prompt locations and pause for user selection."""
    async with db_factory() as db:
        from app.models.prompts import PromptExtraction

        extraction = await db.get(PromptExtraction, extraction_id)
        if not extraction:
            logger.error("PromptExtraction %s not found", extraction_id)
            return

        extraction.status = "discovering"
        extraction.started_at = datetime.now(timezone.utc)
        extraction.progress_message = "Scanning the repository…"
        await db.commit()

        try:
            llm_model = _build_model(
                provider=provider, model=model, api_key=api_key,
                azure_endpoint=azure_endpoint, azure_api_version=azure_api_version,
            )
            resolved_model_name = getattr(llm_model, "model_name", model or "")
            deps = RepoContext(repo_root=Path(repo_path))
            discover_agent = Agent(
                llm_model,
                output_type=PromptLocationList,
                system_prompt=PROMPT_DISCOVERY_SYSTEM_PROMPT,
                deps_type=RepoContext,
                tools=(read_file, glob_files, grep_files),
            )
            limits = UsageLimits(request_limit=_DISCOVERY_REQUEST_LIMIT)

            loc_list, usage = await asyncio.wait_for(
                _discover_locations(discover_agent, deps, limits, db=db, extraction=extraction),
                timeout=_EXTRACTION_TIMEOUT_SECONDS,
            )
            in_tok, out_tok = _tokens(usage)
            await _record_usage(
                db, project_id=project_id, provider=provider,
                model_name=resolved_model_name, input_tokens=in_tok,
                output_tokens=out_tok, extraction_id=extraction_id,
                function_name="discover_repo_prompts",
            )

            integration = await get_or_create_github_integration(project_id, db, repo_full_name)
            excluded = get_excluded_ids(integration)
            existing_ids = set(
                (await db.execute(
                    select(Prompt.external_id).where(Prompt.integration_id == integration.id)
                )).scalars().all()
            )

            locations = list(loc_list.locations) if loc_list else []
            planned: list[dict] = []
            seen: set[str] = set()
            for loc in locations:
                ext_id = _loc_ext_id(loc.file_path, loc.name)
                if ext_id in seen or ext_id in excluded:
                    continue
                seen.add(ext_id)
                planned.append({
                    "external_id": ext_id,
                    "name": loc.name,
                    "file_path": loc.file_path,
                    "line_start": loc.line_start,
                    "role": loc.role,
                    "note": loc.note,
                    "already_saved": ext_id in existing_ids,
                })
                if len(planned) >= _MAX_PROMPTS:
                    break

            extraction.planned_locations = planned
            extraction.summary = loc_list.summary if loc_list else ""
            extraction.files_analyzed = sorted({p["file_path"] for p in planned})
            extraction.status = "awaiting_selection"
            extraction.progress_message = None
            await db.commit()

        except asyncio.CancelledError:
            extraction.status = "cancelled"
            extraction.completed_at = datetime.now(timezone.utc)
            extraction.progress_message = None
            await db.commit()
            raise
        except asyncio.TimeoutError:
            extraction.status = "failed"
            extraction.error = "Discovery timed out. The repository may be very large."
            extraction.completed_at = datetime.now(timezone.utc)
            extraction.progress_message = None
            await db.commit()
        except Exception as e:
            logger.exception("Prompt discovery failed for project %s", project_id)
            extraction.status = "failed"
            extraction.error = str(e)[:2000]
            extraction.completed_at = datetime.now(timezone.utc)
            extraction.progress_message = None
            await db.commit()


async def confirm_extraction(
    project_id: UUID,
    extraction_id: UUID,
    db_factory,
    repo_path: str,
    repo_full_name: str | None,
    selected_external_ids: list[str],
    provider: str,
    model: str | None,
    api_key: str | None,
    azure_endpoint: str | None = None,
    azure_api_version: str | None = None,
) -> None:
    """Phase 2: extract the user-selected locations, then cluster. Background task."""
    async with db_factory() as db:
        from app.models.prompts import PromptExtraction

        extraction = await db.get(PromptExtraction, extraction_id)
        if not extraction:
            logger.error("PromptExtraction %s not found", extraction_id)
            return

        planned = list(extraction.planned_locations or [])
        selected = set(selected_external_ids)
        extraction.status = "running"
        extraction.progress_message = "Preparing extraction…"
        await db.commit()

        total_in = 0
        total_out = 0

        try:
            llm_model = _build_model(
                provider=provider, model=model, api_key=api_key,
                azure_endpoint=azure_endpoint, azure_api_version=azure_api_version,
            )
            resolved_model_name = getattr(llm_model, "model_name", model or "")
            deps = RepoContext(repo_root=Path(repo_path))
            extract_agent = _make_extract_agent(llm_model)
            extract_limits = UsageLimits(request_limit=_EXTRACT_ONE_REQUEST_LIMIT)

            integration = await get_or_create_github_integration(project_id, db, repo_full_name)
            existing_ids = set(
                (await db.execute(
                    select(Prompt.external_id).where(Prompt.integration_id == integration.id)
                )).scalars().all()
            )

            to_extract = [
                p for p in planned
                if p["external_id"] in selected and p["external_id"] not in existing_ids
            ]
            total = len(to_extract)

            async def _drive() -> int:
                nonlocal total_in, total_out
                done = 0
                for i, p in enumerate(to_extract):
                    loc = PromptLocation(
                        name=p["name"], file_path=p["file_path"],
                        line_start=p.get("line_start"), role=p.get("role"), note=p.get("note"),
                    )
                    await _update_progress(
                        db, extraction,
                        progress_message=f"Extracting {i + 1}/{total}: {loc.name}",
                        log_entry=f"{loc.name} — {loc.file_path}",
                    )
                    ep, usage = await _extract_one(extract_agent, deps, loc, extract_limits)
                    ei, eo = _tokens(usage)
                    total_in += ei
                    total_out += eo
                    template = ((ep.template if ep else "") or "").strip()
                    if not template:
                        await _update_progress(
                            db, extraction, log_entry=f"· no prompt text found in {loc.file_path}"
                        )
                        continue
                    ext_id = p["external_id"]
                    await upsert_prompts_for_integration(
                        integration.id,
                        [{
                            "external_id": ext_id,
                            "name": loc.name[:512],
                            "template": ep.template,
                            "version": 1,
                            "variables": ep.variables,
                            "metadata": {
                                "source": "github",
                                "file_path": loc.file_path,
                                "line_start": ep.line_start or loc.line_start,
                                "role": ep.role or loc.role,
                                "note": loc.note,
                                "repo": repo_full_name,
                            },
                        }],
                        db, delete_stale=False,
                    )
                    done += 1
                    extraction.extracted_count = done
                    await db.commit()
                return done

            try:
                await asyncio.wait_for(_drive(), timeout=_EXTRACTION_TIMEOUT_SECONDS)
            except asyncio.TimeoutError as exc:
                minutes = _EXTRACTION_TIMEOUT_SECONDS // 60
                raise RuntimeError(
                    f"Extraction timed out after {minutes} minutes. Prompts found so far "
                    f"were saved — re-run to continue."
                ) from exc

            # Prune against the FULL discovered set so unselecting doesn't delete
            # already-saved prompts; only repo-deleted locations are removed.
            keep = {p["external_id"] for p in planned}
            removed = await _prune_prompts(integration.id, keep, db)
            if removed:
                await _update_progress(db, extraction, log_entry=f"Removed {removed} stale prompt(s)")

            await _record_usage(
                db, project_id=project_id, provider=provider,
                model_name=resolved_model_name, input_tokens=total_in,
                output_tokens=total_out, extraction_id=extraction_id,
            )

            # Best-effort clustering: never discard saved prompts on a hiccup.
            extraction.status = "clustering"
            await _update_progress(
                db, extraction, progress_message="Organizing prompts into groups…",
            )
            try:
                from app.services.prompt_clustering import cluster_project_prompts
                await cluster_project_prompts(db, project_id)
            except Exception:
                logger.exception("Clustering failed for project %s (prompts kept)", project_id)

            saved = (await db.execute(
                select(Prompt).where(Prompt.integration_id == integration.id)
            )).scalars().all()
            extraction.status = "completed"
            extraction.completed_at = datetime.now(timezone.utc)
            extraction.progress_message = None
            extraction.extracted_count = len(saved)
            extraction.total_cost_usd = (
                calculate_cost(resolved_model_name, total_in, total_out)
                if resolved_model_name else None
            )
            await db.commit()

        except asyncio.CancelledError:
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


async def recheck_prompt(
    prompt,
    *,
    project_id: UUID,
    repo_path: str,
    provider: str,
    model: str | None,
    api_key: str | None,
    azure_endpoint: str | None,
    azure_api_version: str | None,
    db,
) -> bool:
    """Re-extract a single github-sourced prompt from the repo; update if changed.

    Returns True when the template or variables differ from what's stored.
    """
    md = prompt.prompt_metadata or {}
    file_path = md.get("file_path")
    if not file_path:
        raise ValueError("This prompt has no source file recorded; re-run extraction first.")

    llm_model = _build_model(
        provider=provider,
        model=model,
        api_key=api_key,
        azure_endpoint=azure_endpoint,
        azure_api_version=azure_api_version,
    )
    agent = _make_extract_agent(llm_model)
    deps = RepoContext(repo_root=Path(repo_path))
    loc = PromptLocation(
        name=prompt.name,
        file_path=file_path,
        line_start=md.get("line_start"),
        role=md.get("role"),
    )

    ep, usage = await _extract_one(
        agent, deps, loc, UsageLimits(request_limit=_EXTRACT_ONE_REQUEST_LIMIT)
    )
    in_tok, out_tok = _tokens(usage)
    await _record_usage(
        db,
        project_id=project_id,
        provider=provider,
        model_name=getattr(llm_model, "model_name", model or ""),
        input_tokens=in_tok,
        output_tokens=out_tok,
        extraction_id=None,
        function_name="recheck_prompt",
    )

    new_template = (ep.template if ep else "") or ""
    if not new_template.strip():
        return False  # couldn't locate it now — keep what we have

    new_vars = ep.variables or []
    changed = new_template != prompt.template or new_vars != (prompt.variables or [])
    if changed:
        prompt.template = new_template
        prompt.variables = new_vars
        prompt.prompt_metadata = {
            **md,
            "line_start": ep.line_start or md.get("line_start"),
            "role": ep.role or md.get("role"),
        }
        prompt.updated_at = datetime.now(timezone.utc)
        await db.commit()
    return changed


async def _prune_prompts(integration_id: UUID, keep: set[str], db) -> int:
    """Delete prompts under the integration whose external_id is not in `keep`."""
    rows = await db.execute(select(Prompt).where(Prompt.integration_id == integration_id))
    removed = 0
    for p in rows.scalars().all():
        if p.external_id not in keep:
            await db.delete(p)
            removed += 1
    if removed:
        await db.commit()
    return removed


async def _record_usage(
    db,
    *,
    project_id: UUID,
    provider: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    extraction_id: UUID | None,
    function_name: str = "extract_prompts_from_repo",
) -> None:
    from app.models.llm_usage import LlmUsageRecord

    db.add(LlmUsageRecord(
        project_id=project_id,
        service_name="prompt_extraction",
        function_name=function_name,
        provider=provider,
        model=model_name or "unknown",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cost_usd=calculate_cost(model_name, input_tokens, output_tokens) if model_name else None,
        request_metadata={"extraction_id": str(extraction_id)} if extraction_id else {},
    ))
    await db.commit()
