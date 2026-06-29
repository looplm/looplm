"""Prompt extraction — phase 2 confirm/extract pipeline.

Split out of `prompt_extraction_service`; `confirm_extraction` is re-exported there
so existing importers keep working.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic_ai.usage import UsageLimits
from sqlalchemy import select

from app.models.models import Prompt
from app.schemas.prompts import PromptLocation
from app.services.code_agent_helpers import _update_progress
from app.services.code_agent_service import _build_model
from app.services.code_agent_tools import RepoContext
from app.services.llm_pricing import calculate_cost
from app.services.prompt_analysis import (
    get_or_create_github_integration,
    upsert_prompts_for_integration,
)
from app.services.prompt_extraction_core import (
    _EXTRACT_ONE_REQUEST_LIMIT,
    _EXTRACTION_TIMEOUT_SECONDS,
    _tokens,
)
from app.services.prompt_extraction_maintenance import (
    _prune_prompts,
    _record_usage,
)

logger = logging.getLogger(__name__)


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
    # Resolve agent helpers through the service module so test monkeypatches that
    # target `prompt_extraction_service` (the historical import location) still
    # take effect after the module split.
    from app.services import prompt_extraction_service as pes

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
            extract_agent = pes._make_extract_agent(llm_model)
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
                    ep, usage = await pes._extract_one(extract_agent, deps, loc, extract_limits)
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
                from app.services.analysis_llm import AnalysisLlmService
                from app.services.prompt_clustering import cluster_project_prompts

                project_settings = await AnalysisLlmService.load_project_settings(db, project_id)
                await cluster_project_prompts(db, project_id, user_settings=project_settings)
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
