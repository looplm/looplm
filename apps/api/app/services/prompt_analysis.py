"""Prompt import & analysis service."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import Integration, IntegrationType, Prompt, PromptReview, SyncStatus
from app.schemas.prompts import AntiPattern, PromptImportItem, PromptReviewResult

logger = logging.getLogger(__name__)


async def import_prompts_from_json(
    items: list[PromptImportItem],
    project_id: UUID,
    db: AsyncSession,
) -> int:
    """Import prompts from a JSON upload, creating a json_file integration if needed."""
    from app.encryption import encrypt_api_key

    # Find or create the json_file integration for this project
    result = await db.execute(
        select(Integration).where(
            Integration.project_id == project_id,
            Integration.type == IntegrationType.json_file,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        integration = Integration(
            project_id=project_id,
            type=IntegrationType.json_file,
            name="JSON Import",
            api_key=encrypt_api_key("json_file_placeholder"),
            sync_status=SyncStatus.idle,
        )
        db.add(integration)
        await db.flush()

    # Upsert prompts (match by name + version)
    synced = 0
    for item in items:
        external_id = item.name  # use name as external_id for json imports
        result = await db.execute(
            select(Prompt).where(
                Prompt.integration_id == integration.id,
                Prompt.external_id == external_id,
                Prompt.version == item.version,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.name = item.name
            existing.template = item.template
            existing.variables = item.variables
            existing.prompt_metadata = item.metadata
            existing.updated_at = datetime.now(timezone.utc)
        else:
            db.add(Prompt(
                integration_id=integration.id,
                external_id=external_id,
                name=item.name,
                template=item.template,
                version=item.version,
                variables=item.variables,
                prompt_metadata=item.metadata,
            ))
        synced += 1

    await db.commit()
    return synced


async def sync_prompts(
    integration_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> int:
    """Import prompts from a connected platform."""
    result = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.project_id == project_id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise ValueError("Integration not found")

    from app.encryption import decrypt_api_key

    api_key = decrypt_api_key(integration.api_key)
    raw_prompts: list[dict] = []

    if integration.type.value == "langfuse":
        from connectors.langfuse.connector import LangfuseConnector

        connector = LangfuseConnector(
            public_key=integration.config.get("public_key", api_key),
            secret_key=api_key,
            host=integration.base_url or integration.config.get("host") or "https://cloud.langfuse.com",
        )
        raw_prompts = await connector.sync_prompts()
    elif integration.type.value == "langsmith":
        from connectors.langsmith.connector import LangSmithConnector

        connector = LangSmithConnector(
            api_key=api_key,
            api_url=integration.base_url or "https://api.smith.langchain.com",
        )
        raw_prompts = await connector.sync_prompts()

    # Build set of (external_id, version) from the remote source
    remote_keys = {(rp["external_id"], rp.get("version", 1)) for rp in raw_prompts}

    # Delete local prompts that no longer exist remotely
    existing_all = await db.execute(
        select(Prompt).where(Prompt.integration_id == integration_id)
    )
    for existing_prompt in existing_all.scalars().all():
        if (existing_prompt.external_id, existing_prompt.version) not in remote_keys:
            await db.delete(existing_prompt)

    # Upsert prompts from the remote source
    synced = 0
    for rp in raw_prompts:
        result = await db.execute(
            select(Prompt).where(
                Prompt.integration_id == integration_id,
                Prompt.external_id == rp["external_id"],
                Prompt.version == rp.get("version", 1),
            )
        )
        existing_prompt = result.scalar_one_or_none()
        if existing_prompt:
            # Update fields in case they changed (e.g. template was empty)
            existing_prompt.name = rp["name"]
            existing_prompt.template = rp.get("template", "")
            existing_prompt.variables = rp.get("variables", [])
            existing_prompt.prompt_metadata = rp.get("metadata", {})
            existing_prompt.updated_at = datetime.now(timezone.utc)
            synced += 1
            continue

        prompt = Prompt(
            integration_id=integration_id,
            external_id=rp["external_id"],
            name=rp["name"],
            template=rp.get("template", ""),
            version=rp.get("version", 1),
            variables=rp.get("variables", []),
            prompt_metadata=rp.get("metadata", {}),
        )
        db.add(prompt)
        synced += 1

    await db.commit()
    return synced


async def list_prompts(
    project_id: UUID,
    db: AsyncSession,
    integration_id: UUID | None = None,
) -> list[Prompt]:
    """List all imported prompts for a project."""
    project_integrations = select(Integration.id).where(Integration.project_id == project_id)
    q = select(Prompt).options(selectinload(Prompt.integration)).where(Prompt.integration_id.in_(project_integrations))
    if integration_id:
        q = q.where(Prompt.integration_id == integration_id)
    q = q.order_by(Prompt.updated_at.desc(), Prompt.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_prompt(prompt_id: UUID, project_id: UUID, db: AsyncSession) -> Prompt | None:
    """Get a single prompt with project ownership check."""
    project_integrations = select(Integration.id).where(Integration.project_id == project_id)
    result = await db.execute(
        select(Prompt).options(selectinload(Prompt.integration)).where(
            Prompt.id == prompt_id,
            Prompt.integration_id.in_(project_integrations),
        )
    )
    return result.scalar_one_or_none()


async def review_prompt(
    prompt_id: UUID,
    project_id: UUID,
    db: AsyncSession,
    user_settings: dict | None = None,
) -> PromptReviewResult:
    """LLM-based prompt review for anti-patterns."""
    prompt = await get_prompt(prompt_id, project_id, db)
    if not prompt:
        raise ValueError("Prompt not found")

    from app.services.analysis_llm import AnalysisLlmService

    llm = AnalysisLlmService(user_settings=user_settings)

    review_prompt_text = f"""Analyze this LLM prompt template for anti-patterns and suggest improvements.

Prompt template:
---
{prompt.template}
---
Variables: {json.dumps(prompt.variables)}

Check for these anti-patterns:
1. Vague instructions (no clear task definition)
2. Missing examples (no few-shot examples when beneficial)
3. No output format specification
4. Token waste (unnecessary verbosity, redundant instructions)
5. Missing guardrails or constraints

Respond with JSON:
{{
  "anti_patterns": [
    {{"pattern": "name", "description": "details", "severity": "high|medium|low", "location": "where"}}
  ],
  "suggestions": ["suggestion1", "suggestion2"],
  "rewritten_prompt": "improved version of the prompt"
}}"""

    from app.services.llm_usage_tracker import record_llm_usage

    raw, usage = await llm.tracked_chat_completion(
        messages=[
            {
                "role": "system",
                "content": "You are a prompt engineering expert. Analyze prompts and suggest improvements. Respond only with valid JSON.",
            },
            {"role": "user", "content": review_prompt_text},
        ],
        temperature=0.2,
    )

    await record_llm_usage(
        db,
        project_id=project_id,
        service_name="prompt_analysis",
        function_name="review_prompt",
        provider=llm.provider,
        model=llm.model,
        usage=usage,
        request_metadata={"prompt_id": str(prompt_id)},
    )
    # Strip code fences
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
    except json.JSONDecodeError:
        data = {}

    anti_patterns = [
        AntiPattern(**ap) for ap in data.get("anti_patterns", [])
    ]

    now = datetime.now(timezone.utc)

    # Persist review to DB
    review_record = PromptReview(
        prompt_id=prompt_id,
        anti_patterns=data.get("anti_patterns", []),
        suggestions=data.get("suggestions", []),
        rewritten_prompt=data.get("rewritten_prompt", ""),
        model=llm.model,
        reviewed_at=now,
    )
    db.add(review_record)
    await db.commit()

    return PromptReviewResult(
        id=str(review_record.id),
        prompt_id=str(prompt_id),
        anti_patterns=anti_patterns,
        suggestions=data.get("suggestions", []),
        rewritten_prompt=data.get("rewritten_prompt", ""),
        reviewed_at=now,
        model=llm.model,
    )


async def list_reviews(
    prompt_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> list[PromptReview]:
    """List all reviews for a prompt."""
    # Verify ownership
    prompt = await get_prompt(prompt_id, project_id, db)
    if not prompt:
        raise ValueError("Prompt not found")

    result = await db.execute(
        select(PromptReview)
        .where(PromptReview.prompt_id == prompt_id)
        .order_by(PromptReview.reviewed_at.desc())
    )
    return list(result.scalars().all())


async def list_versions(
    prompt_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> list[Prompt]:
    """List all versions of a prompt (by same name & integration)."""
    prompt = await get_prompt(prompt_id, project_id, db)
    if not prompt:
        raise ValueError("Prompt not found")

    project_integrations = select(Integration.id).where(Integration.project_id == project_id)
    result = await db.execute(
        select(Prompt)
        .options(selectinload(Prompt.integration))
        .where(
            Prompt.name == prompt.name,
            Prompt.integration_id == prompt.integration_id,
            Prompt.integration_id.in_(project_integrations),
        )
        .order_by(Prompt.version.desc())
    )
    return list(result.scalars().all())
