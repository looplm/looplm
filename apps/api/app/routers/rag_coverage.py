"""RAG eval-coverage endpoints.

Two halves:
  * Index-provider CRUD — per-project, credentialed read-only connections to a
    retrieval backend (Azure AI Search today). Mirrors the integrations router.
  * Coverage analysis — kick off a background ``CoverageRun`` for a chosen
    partition key and poll it. Mirrors the feedback-suggestion run/poll flow.
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section, require_write
from app.db import async_session, get_db
from app.encryption import encrypt_api_key
from app.index_providers.registry import build_index_provider
from app.models.base import IndexProviderType
from app.models.index_providers import (
    CoverageRun,
    IndexProvider,
    PartitionAcknowledgement,
)
from app.models.project import Project
from app.models.user import User
from app.routers.rag_coverage_worker import run_coverage_analysis
from app.schemas.index_providers import (
    AcknowledgementCreate,
    AcknowledgementListResponse,
    AcknowledgementResponse,
    AnalyzeRequest,
    AnalyzeResponse,
    CoverageCategoryOverview,
    CoverageOverviewResponse,
    CoverageRunResponse,
    CoverageRunSummary,
    CoverageRunSummaryListResponse,
    IndexProviderCreate,
    IndexProviderListResponse,
    IndexProviderResponse,
    IndexProviderUpdate,
    PartitionKeyListResponse,
    PartitionKeyResponse,
    TestConnectionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/rag-coverage",
    tags=["rag-coverage"],
    dependencies=[require_section("evaluate", "coverage")],
)

# Track background coverage tasks so they aren't garbage-collected mid-run.
_coverage_tasks: dict[UUID, asyncio.Task] = {}


def _not_found(what: str = "Index provider") -> HTTPException:
    return HTTPException(
        status_code=404, detail={"error": {"code": "NOT_FOUND", "message": f"{what} not found"}}
    )


async def _get_provider_or_404(
    db: AsyncSession, provider_id: UUID, project: Project
) -> IndexProvider:
    provider = (
        await db.execute(
            select(IndexProvider).where(
                IndexProvider.id == provider_id, IndexProvider.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if provider is None:
        raise _not_found()
    return provider


# ── Provider CRUD ──────────────────────────────────────────────────────────

@router.post(
    "/providers",
    response_model=IndexProviderResponse,
    status_code=201,
    dependencies=[require_write("evaluate", "coverage")],
)
async def create_provider(
    body: IndexProviderCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    existing = await db.execute(
        select(IndexProvider).where(
            IndexProvider.project_id == project.id, IndexProvider.name == body.name
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "CONFLICT", "message": "Provider name already exists"}},
        )

    provider = IndexProvider(
        project_id=project.id,
        type=IndexProviderType(body.type),
        name=body.name,
        api_key=encrypt_api_key(body.api_key),
        base_url=body.base_url,
        config=body.config,
    )
    db.add(provider)
    await db.flush()
    await db.refresh(provider)
    return provider


@router.get("/providers", response_model=IndexProviderListResponse)
async def list_providers(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(IndexProvider)
        .where(IndexProvider.project_id == project.id)
        .order_by(IndexProvider.created_at.desc())
    )
    return IndexProviderListResponse(data=result.scalars().all())


@router.patch(
    "/providers/{provider_id}",
    response_model=IndexProviderResponse,
    dependencies=[require_write("evaluate", "coverage")],
)
async def update_provider(
    provider_id: UUID,
    body: IndexProviderUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    provider = await _get_provider_or_404(db, provider_id, project)
    if body.name is not None:
        provider.name = body.name
    if body.api_key is not None:
        provider.api_key = encrypt_api_key(body.api_key)
    if body.base_url is not None:
        provider.base_url = body.base_url
    if body.config is not None:
        provider.config = body.config
    await db.flush()
    await db.refresh(provider)
    return provider


@router.delete(
    "/providers/{provider_id}",
    status_code=204,
    dependencies=[require_write("evaluate", "coverage")],
)
async def delete_provider(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    provider = await _get_provider_or_404(db, provider_id, project)
    await db.delete(provider)
    return None


@router.post("/providers/{provider_id}/test", response_model=TestConnectionResponse)
async def test_provider(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    provider = await _get_provider_or_404(db, provider_id, project)
    client = build_index_provider(provider)
    try:
        count = await client.test_connection()
        return TestConnectionResponse(ok=True, document_count=count)
    except Exception as e:  # surface the backend error to the caller
        logger.warning("Provider %s test failed: %s", provider_id, e)
        return TestConnectionResponse(ok=False, error=str(e))
    finally:
        await client.aclose()


@router.get("/providers/{provider_id}/partition-keys", response_model=PartitionKeyListResponse)
async def list_partition_keys(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    provider = await _get_provider_or_404(db, provider_id, project)
    client = build_index_provider(provider)
    try:
        keys = await client.list_partition_keys()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "PROVIDER_ERROR", "message": str(e)}},
        )
    finally:
        await client.aclose()
    return PartitionKeyListResponse(
        data=[
            PartitionKeyResponse(
                key=k.key, label=k.label, multivalued=k.multivalued, metadata=k.metadata
            )
            for k in keys
        ]
    )


# ── Coverage analysis ───────────────────────────────────────────────────────

@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    status_code=202,
    dependencies=[require_write("evaluate", "coverage")],
)
async def analyze(
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    await _get_provider_or_404(db, body.provider_id, project)

    # Project-scoped LLM settings are shared by all members; a user's personal
    # settings fill any gaps.
    from app.services.analysis_llm import merge_llm_settings

    llm_settings = merge_llm_settings(project.settings, user.settings)

    run = CoverageRun(
        project_id=project.id,
        provider_id=body.provider_id,
        status="pending",
        partition_key=body.partition_key,
        dataset_ids=[str(d) for d in body.dataset_ids] if body.dataset_ids else None,
        suggest="true" if body.suggest else "false",
        min_covering_cases=body.min_covering_cases,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    run_id = run.id
    # Commit before spawning the background task: it opens its own session and
    # reads this row immediately, so the row must be visible to other connections.
    await db.commit()

    task = asyncio.create_task(
        run_coverage_analysis(
            run_id=run_id,
            project_id=project.id,
            provider_id=body.provider_id,
            partition_key=body.partition_key,
            dataset_ids=body.dataset_ids,
            suggest=body.suggest,
            min_covering_cases=body.min_covering_cases,
            sample_n=body.sample_n,
            max_questions_per_gap=body.max_questions_per_gap,
            max_gaps_to_suggest=body.max_gaps_to_suggest,
            user_settings=llm_settings,
            db_factory=async_session,
        )
    )
    _coverage_tasks[run_id] = task
    task.add_done_callback(lambda _t, rid=run_id: _coverage_tasks.pop(rid, None))

    return AnalyzeResponse(run_id=run_id, status="pending")


def _summary_from_run(run: CoverageRun) -> CoverageRunSummary:
    """Headline projection of a run — derived from the stored results blob."""
    res = run.results or {}
    total_values = int(res.get("total_values") or 0)
    covered_values = int(res.get("covered_values") or 0)
    return CoverageRunSummary(
        id=run.id,
        provider_id=run.provider_id,
        partition_key=run.partition_key,
        status=run.status,
        value_coverage_pct=res.get("value_coverage_pct"),
        doc_coverage_pct=res.get("doc_coverage_pct"),
        total_values=total_values,
        covered_values=covered_values,
        gaps=max(0, total_values - covered_values),
        issue_count=len(res.get("issues") or []),
        suggestion_count=len(run.suggestions or []),
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.get("/runs", response_model=CoverageRunSummaryListResponse)
async def list_runs(
    provider_id: UUID | None = None,
    partition_key: str | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    query = select(CoverageRun).where(CoverageRun.project_id == project.id)
    if provider_id is not None:
        query = query.where(CoverageRun.provider_id == provider_id)
    if partition_key is not None:
        query = query.where(CoverageRun.partition_key == partition_key)
    result = await db.execute(query.order_by(CoverageRun.created_at.desc()))
    return CoverageRunSummaryListResponse(
        data=[_summary_from_run(r) for r in result.scalars().all()]
    )


@router.get("/overview", response_model=CoverageOverviewResponse)
async def overview(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Latest coverage per analyzed partition key (with trend vs the previous run)."""
    result = await db.execute(
        select(CoverageRun)
        .where(
            CoverageRun.project_id == project.id,
            CoverageRun.provider_id == provider_id,
            CoverageRun.status == "completed",
        )
        .order_by(CoverageRun.created_at.desc())
    )
    runs = list(result.scalars().all())

    by_key: dict[str, list[CoverageRun]] = {}
    for r in runs:
        by_key.setdefault(r.partition_key, []).append(r)  # already newest-first

    categories: list[CoverageCategoryOverview] = []
    for key, key_runs in by_key.items():
        latest = _summary_from_run(key_runs[0])
        prev = key_runs[1] if len(key_runs) > 1 else None
        value_delta = doc_delta = None
        prev_at = None
        if prev is not None:
            prev_sum = _summary_from_run(prev)
            prev_at = prev.created_at
            if latest.value_coverage_pct is not None and prev_sum.value_coverage_pct is not None:
                value_delta = round(latest.value_coverage_pct - prev_sum.value_coverage_pct, 1)
            if latest.doc_coverage_pct is not None and prev_sum.doc_coverage_pct is not None:
                doc_delta = round(latest.doc_coverage_pct - prev_sum.doc_coverage_pct, 1)
        categories.append(
            CoverageCategoryOverview(
                partition_key=key,
                latest=latest,
                value_coverage_delta=value_delta,
                doc_coverage_delta=doc_delta,
                previous_run_at=prev_at,
            )
        )
    categories.sort(key=lambda c: c.latest.created_at, reverse=True)
    return CoverageOverviewResponse(data=categories)


@router.get("/runs/{run_id}", response_model=CoverageRunResponse)
async def get_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    run = (
        await db.execute(
            select(CoverageRun).where(
                CoverageRun.id == run_id, CoverageRun.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise _not_found("Coverage run")
    return CoverageRunResponse.from_row(run)


# ── Acknowledgements (partition-quality "memory") ────────────────────────────

@router.get("/acknowledgements", response_model=AcknowledgementListResponse)
async def list_acknowledgements(
    provider_id: UUID,
    partition_key: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(PartitionAcknowledgement).where(
            PartitionAcknowledgement.project_id == project.id,
            PartitionAcknowledgement.provider_id == provider_id,
            PartitionAcknowledgement.partition_key == partition_key,
        )
    )
    return AcknowledgementListResponse(data=result.scalars().all())


@router.post(
    "/acknowledgements",
    response_model=AcknowledgementResponse,
    status_code=201,
    dependencies=[require_write("evaluate", "coverage")],
)
async def create_acknowledgement(
    body: AcknowledgementCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    # Upsert on (project, provider, partition_key, partition_value).
    existing = (
        await db.execute(
            select(PartitionAcknowledgement).where(
                PartitionAcknowledgement.project_id == project.id,
                PartitionAcknowledgement.provider_id == body.provider_id,
                PartitionAcknowledgement.partition_key == body.partition_key,
                PartitionAcknowledgement.partition_value == body.partition_value,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.note = body.note
        existing.updated_at = datetime.now(timezone.utc)
        ack = existing
    else:
        ack = PartitionAcknowledgement(
            project_id=project.id,
            provider_id=body.provider_id,
            partition_key=body.partition_key,
            partition_value=body.partition_value,
            note=body.note,
            created_by=user.id,
        )
        db.add(ack)
    await db.flush()
    await db.refresh(ack)
    return ack


@router.delete(
    "/acknowledgements/{ack_id}",
    status_code=204,
    dependencies=[require_write("evaluate", "coverage")],
)
async def delete_acknowledgement(
    ack_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    ack = (
        await db.execute(
            select(PartitionAcknowledgement).where(
                PartitionAcknowledgement.id == ack_id,
                PartitionAcknowledgement.project_id == project.id,
            )
        )
    ).scalar_one_or_none()
    if ack is None:
        raise _not_found("Acknowledgement")
    await db.delete(ack)
    return None
