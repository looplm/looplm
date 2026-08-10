"""Synthetic question generation endpoints.

Turns indexed chunks into a retrieval benchmark: sample chunks, ask the LLM to write questions
each chunk answers, and persist them as a dataset whose ground truth is the source chunk. The
result is scoreable on the Retrieval page with ``gold_source=synthetic``, against a live index,
with no eval run and no human labeling.

Lives under the same permission page as the rest of the index views ("data-sources"). Starting a
run additionally requires dataset write access, because a persisting run creates a dataset.
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
from app.models.datasets import TestDataset
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.models.synthetic_questions import SyntheticQuestionRun
from app.models.user import User
from app.routers.synthetic_questions_worker import run_synthetic_question_generation
from app.schemas.synthetic_questions import (
    SyntheticQuestionRunCreateResponse,
    SyntheticQuestionRunRequest,
    SyntheticQuestionRunResponse,
    SyntheticQuestionRunSummary,
    SyntheticQuestionRunSummaryListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/synthetic-questions",
    tags=["synthetic-questions"],
    dependencies=[require_section("observe", "data-sources")],
)

# Keep background tasks referenced so they aren't garbage-collected mid-run.
_tasks: dict[UUID, asyncio.Task] = {}


def _not_found(what: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail={"error": {"code": "NOT_FOUND", "message": f"{what} not found"}}
    )


def _bad_request(message: str) -> HTTPException:
    return HTTPException(
        status_code=400, detail={"error": {"code": "BAD_REQUEST", "message": message}}
    )


async def _run_or_404(
    db: AsyncSession, run_id: UUID, project: Project
) -> SyntheticQuestionRun:
    run = (
        await db.execute(
            select(SyntheticQuestionRun).where(
                SyntheticQuestionRun.id == run_id,
                SyntheticQuestionRun.project_id == project.id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise _not_found("Synthetic question run")
    return run


@router.post(
    "/runs",
    response_model=SyntheticQuestionRunCreateResponse,
    status_code=202,
    dependencies=[
        require_write("observe", "data-sources"),
        # A persisting run creates a dataset and its test cases, so it needs that write too.
        require_write("evaluate", "datasets"),
    ],
)
async def create_run(
    body: SyntheticQuestionRunRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Start a generation run. Returns immediately; poll ``GET /runs/{run_id}`` for progress."""
    provider = (
        await db.execute(
            select(IndexProvider).where(
                IndexProvider.id == body.provider_id, IndexProvider.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if provider is None:
        raise _not_found("Index provider")

    if body.scope == "partition" and not (body.partition_key and body.partition_value):
        raise _bad_request("Partition scope requires a partition key and value")

    if body.dataset_id is not None:
        exists = (
            await db.execute(
                select(TestDataset.id).where(
                    TestDataset.id == body.dataset_id, TestDataset.project_id == project.id
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            raise _not_found("Dataset")

    run = SyntheticQuestionRun(
        project_id=project.id,
        provider_id=body.provider_id,
        status="pending",
        scope=body.scope,
        partition_key=body.partition_key,
        partition_value=body.partition_value,
        sample_size=body.sample_size,
        questions_per_chunk=body.questions_per_chunk,
        negative_share=body.negative_share,
        verify_negatives=body.verify_negatives,
        persist=body.persist,
        dataset_id=body.dataset_id,
        dataset_name=body.dataset_name,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    run_id = run.id
    # Commit before spawning: the worker opens its own session and must see the row.
    await db.commit()

    task = asyncio.create_task(
        run_synthetic_question_generation(
            run_id=run_id,
            project_id=project.id,
            provider_id=body.provider_id,
            scope=body.scope,
            partition_key=body.partition_key,
            partition_value=body.partition_value,
            sample_size=body.sample_size,
            questions_per_chunk=body.questions_per_chunk,
            negative_share=body.negative_share,
            verify=body.verify_negatives,
            persist=body.persist,
            dataset_id=body.dataset_id,
            dataset_name=body.dataset_name,
            user_settings=user.settings,
            db_factory=async_session,
        )
    )
    _tasks[run_id] = task
    task.add_done_callback(lambda _t, rid=run_id: _tasks.pop(rid, None))
    return SyntheticQuestionRunCreateResponse(run_id=run_id, status="pending")


@router.post(
    "/runs/{run_id}/cancel",
    response_model=SyntheticQuestionRunCreateResponse,
    dependencies=[require_write("observe", "data-sources")],
)
async def cancel_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Stop a pending/running generation.

    Flips the row to 'cancelled' first (so a worker that survives the task cancellation cannot
    overwrite it), then cancels the in-process task. A run cancelled mid-generation persists
    nothing: the dataset is written in one step at the end.
    """
    run = await _run_or_404(db, run_id, project)
    if run.status not in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "NOT_RUNNING", "message": "Run is not in progress"}},
        )
    run.status = "cancelled"
    run.stage = None
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()

    task = _tasks.get(run_id)
    if task is not None:
        task.cancel()
    return SyntheticQuestionRunCreateResponse(run_id=run_id, status="cancelled")


def _summary_from_run(run: SyntheticQuestionRun) -> SyntheticQuestionRunSummary:
    counts = (run.results or {}).get("counts") or {}
    return SyntheticQuestionRunSummary(
        id=run.id,
        provider_id=run.provider_id,
        status=run.status,
        stage=run.stage,
        scope=run.scope,
        partition_key=run.partition_key,
        partition_value=run.partition_value,
        sample_size=run.sample_size,
        questions_per_chunk=run.questions_per_chunk,
        negative_share=run.negative_share,
        persist=run.persist,
        dataset_id=run.dataset_id,
        dataset_name=run.dataset_name,
        total=run.total,
        processed=run.processed,
        questions_generated=int(counts.get("questions_generated") or 0)
        + int(counts.get("negatives_generated") or 0),
        cases_created=int(counts.get("cases_created") or 0),
        error=run.error,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.get("/runs", response_model=SyntheticQuestionRunSummaryListResponse)
async def list_runs(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(SyntheticQuestionRun)
        .where(
            SyntheticQuestionRun.project_id == project.id,
            SyntheticQuestionRun.provider_id == provider_id,
        )
        .order_by(SyntheticQuestionRun.created_at.desc())
    )
    return SyntheticQuestionRunSummaryListResponse(
        data=[_summary_from_run(r) for r in result.scalars().all()]
    )


@router.get("/runs/{run_id}", response_model=SyntheticQuestionRunResponse)
async def get_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    return await _run_or_404(db, run_id, project)


@router.delete(
    "/runs/{run_id}",
    status_code=204,
    dependencies=[require_write("observe", "data-sources")],
)
async def delete_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Delete a run record. The dataset it created (if any) is left untouched."""
    run = await _run_or_404(db, run_id, project)
    if run.status in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "IN_PROGRESS", "message": "Cancel the run before deleting"}},
        )
    await db.delete(run)
    await db.commit()
