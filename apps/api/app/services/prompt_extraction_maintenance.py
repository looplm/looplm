"""Prompt extraction — maintenance helpers: single-prompt recheck, pruning, usage.

Split out of `prompt_extraction_service`; `recheck_prompt` is re-exported there so
existing importers keep working.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic_ai.usage import UsageLimits
from sqlalchemy import select

from app.models.models import Prompt
from app.schemas.prompts import PromptLocation
from app.services.code_agent_service import _build_model
from app.services.code_agent_tools import RepoContext
from app.services.llm_pricing import calculate_cost
from app.services.prompt_extraction_core import (
    _EXTRACT_ONE_REQUEST_LIMIT,
    _tokens,
)

logger = logging.getLogger(__name__)


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
    # Resolve agent helpers through the service module so test monkeypatches that
    # target `prompt_extraction_service` (the historical import location) still
    # take effect after the module split.
    from app.services import prompt_extraction_service as pes

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
    agent = pes._make_extract_agent(llm_model)
    deps = RepoContext(repo_root=Path(repo_path))
    loc = PromptLocation(
        name=prompt.name,
        file_path=file_path,
        line_start=md.get("line_start"),
        role=md.get("role"),
    )

    ep, usage = await pes._extract_one(
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
