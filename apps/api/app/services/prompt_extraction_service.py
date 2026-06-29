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

The pipeline is split across sibling modules to keep each focused:
`prompt_extraction_core` (agent helpers + constants), `prompt_extraction_confirm`
(`confirm_extraction`), and `prompt_extraction_maintenance` (`recheck_prompt` +
pruning/usage). `confirm_extraction` and `recheck_prompt` are re-exported here so
existing importers keep working.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits
from sqlalchemy import select

from app.models.models import Prompt
from app.schemas.prompts import PromptLocation, PromptLocationList
from app.services.code_agent_helpers import _update_progress
from app.services.code_agent_prompts import (
    PROMPT_DISCOVERY_SYSTEM_PROMPT,
)
from app.services.code_agent_service import _build_model
from app.services.code_agent_tools import RepoContext, glob_files, grep_files, read_file
from app.services.llm_pricing import calculate_cost
from app.services.prompt_analysis import (
    get_excluded_ids,
    get_or_create_github_integration,
    upsert_prompts_for_integration,
)
from app.services.prompt_extraction_confirm import confirm_extraction
from app.services.prompt_extraction_core import (
    _DISCOVERY_REQUEST_LIMIT,
    _EXTRACT_ONE_REQUEST_LIMIT,
    _EXTRACTION_TIMEOUT_SECONDS,
    _MAX_PROMPTS,
    _discover_locations,
    _extract_one,
    _loc_ext_id,
    _make_extract_agent,
    _tokens,
)
from app.services.prompt_extraction_maintenance import (
    _prune_prompts,
    _record_usage,
    recheck_prompt,
)

logger = logging.getLogger(__name__)

# `confirm_extraction` and `recheck_prompt` live in sibling modules but are
# re-exported so `from app.services.prompt_extraction_service import …` keeps
# working unchanged.
__all__ = [
    "extract_prompts_from_repo",
    "discover_repo_prompts",
    "confirm_extraction",
    "recheck_prompt",
]


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
