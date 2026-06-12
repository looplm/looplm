"""Wanted-status source registry endpoints.

Lets product owners declare which sources *should* be retrievable from an
index (manually or via CSV import), run a gap analysis comparing that wanted
status against what is actually indexed, and export the result as a markdown
report for the indexing-pipeline owners.

Lives under the same permission page as the index explorer ("data-sources"):
it is the write-side counterpart to that read-side view.
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section, require_write
from app.db import async_session, get_db
from app.index_providers.source_gaps import build_markdown_report
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.models.source_registry import SourceExpectation, SourceGapRun
from app.models.user import User
from app.routers.source_registry_worker import run_source_gap_analysis
from app.schemas.source_registry import (
    CsvImportRequest,
    CsvImportResponse,
    GapRunCreateResponse,
    GapRunRequest,
    GapRunResponse,
    GapRunSummary,
    GapRunSummaryListResponse,
    SourceExpectationCreate,
    SourceExpectationListResponse,
    SourceExpectationResponse,
    SourceExpectationUpdate,
)
from app.services.source_csv import parse_source_csv

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/source-registry",
    tags=["source-registry"],
    dependencies=[require_section("observe", "data-sources")],
)

# Keep background gap tasks referenced so they aren't garbage-collected mid-run.
_gap_tasks: dict[UUID, asyncio.Task] = {}


def _not_found(what: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail={"error": {"code": "NOT_FOUND", "message": f"{what} not found"}}
    )


async def _provider_or_404(db: AsyncSession, provider_id: UUID, project: Project) -> IndexProvider:
    provider = (
        await db.execute(
            select(IndexProvider).where(
                IndexProvider.id == provider_id, IndexProvider.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if provider is None:
        raise _not_found("Index provider")
    return provider


# ── Expectations CRUD ────────────────────────────────────────────────────────

@router.get("/expectations", response_model=SourceExpectationListResponse)
async def list_expectations(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(SourceExpectation)
        .where(
            SourceExpectation.project_id == project.id,
            SourceExpectation.provider_id == provider_id,
        )
        .order_by(SourceExpectation.name)
    )
    return SourceExpectationListResponse(data=result.scalars().all())


@router.post(
    "/expectations",
    response_model=SourceExpectationResponse,
    status_code=201,
    dependencies=[require_write("observe", "data-sources")],
)
async def create_expectation(
    body: SourceExpectationCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    await _provider_or_404(db, body.provider_id, project)
    if not body.html_url and not body.pdf_url:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "VALIDATION",
                    "message": "At least one of html_url / pdf_url is required",
                }
            },
        )
    expectation = SourceExpectation(
        project_id=project.id, created_by=user.id, **body.model_dump()
    )
    db.add(expectation)
    try:
        await db.flush()
    except Exception:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {"code": "CONFLICT", "message": "A source with this name already exists"}
            },
        )
    await db.refresh(expectation)
    return expectation


@router.patch(
    "/expectations/{expectation_id}",
    response_model=SourceExpectationResponse,
    dependencies=[require_write("observe", "data-sources")],
)
async def update_expectation(
    expectation_id: UUID,
    body: SourceExpectationUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    expectation = (
        await db.execute(
            select(SourceExpectation).where(
                SourceExpectation.id == expectation_id,
                SourceExpectation.project_id == project.id,
            )
        )
    ).scalar_one_or_none()
    if expectation is None:
        raise _not_found("Source expectation")
    updates = body.model_dump(exclude_unset=True)
    # ack_note: "" clears the acknowledgement, a non-empty string sets it.
    if "ack_note" in updates and updates["ack_note"] == "":
        updates["ack_note"] = None
    for key, value in updates.items():
        setattr(expectation, key, value)
    expectation.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(expectation)
    return expectation


@router.delete(
    "/expectations/{expectation_id}",
    status_code=204,
    dependencies=[require_write("observe", "data-sources")],
)
async def delete_expectation(
    expectation_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    expectation = (
        await db.execute(
            select(SourceExpectation).where(
                SourceExpectation.id == expectation_id,
                SourceExpectation.project_id == project.id,
            )
        )
    ).scalar_one_or_none()
    if expectation is None:
        raise _not_found("Source expectation")
    await db.delete(expectation)
    return None


# ── CSV import ───────────────────────────────────────────────────────────────

@router.post(
    "/import-csv",
    response_model=CsvImportResponse,
    dependencies=[require_write("observe", "data-sources")],
)
async def import_csv(
    body: CsvImportRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    await _provider_or_404(db, body.provider_id, project)
    parsed = parse_source_csv(body.csv_text)
    if not parsed.sources:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "VALIDATION",
                    "message": "No importable rows found",
                    "warnings": parsed.warnings,
                }
            },
        )

    existing_rows = (
        (
            await db.execute(
                select(SourceExpectation).where(
                    SourceExpectation.project_id == project.id,
                    SourceExpectation.provider_id == body.provider_id,
                )
            )
        )
        .scalars()
        .all()
    )
    by_name = {e.name: e for e in existing_rows}

    created = updated = deleted = 0
    imported_names: set[str] = set()
    for src in parsed.sources:
        imported_names.add(src.name)
        existing = by_name.get(src.name)
        if existing is not None:
            for attr in (
                "html_url", "pdf_url", "adapter_tag", "typ", "sparte", "thema",
                "publisher", "hierarchie", "update_frequency", "comment",
            ):
                setattr(existing, attr, getattr(src, attr))
            existing.updated_at = datetime.now(timezone.utc)
            updated += 1
        else:
            db.add(
                SourceExpectation(
                    project_id=project.id,
                    provider_id=body.provider_id,
                    created_by=user.id,
                    name=src.name,
                    html_url=src.html_url,
                    pdf_url=src.pdf_url,
                    adapter_tag=src.adapter_tag,
                    typ=src.typ,
                    sparte=src.sparte,
                    thema=src.thema,
                    publisher=src.publisher,
                    hierarchie=src.hierarchie,
                    update_frequency=src.update_frequency,
                    comment=src.comment,
                )
            )
            created += 1

    if body.replace:
        for name, row in by_name.items():
            if name not in imported_names:
                await db.delete(row)
                deleted += 1

    await db.flush()
    return CsvImportResponse(
        created=created,
        updated=updated,
        deleted=deleted,
        skipped_rows=parsed.skipped_rows,
        total=len(parsed.sources),
        warnings=parsed.warnings,
    )


# ── Gap runs ─────────────────────────────────────────────────────────────────

@router.post(
    "/gap-runs",
    response_model=GapRunCreateResponse,
    status_code=202,
    dependencies=[require_write("observe", "data-sources")],
)
async def create_gap_run(
    body: GapRunRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    await _provider_or_404(db, body.provider_id, project)
    run = SourceGapRun(project_id=project.id, provider_id=body.provider_id, status="pending")
    db.add(run)
    await db.flush()
    await db.refresh(run)
    run_id = run.id
    # Commit before spawning: the worker opens its own session and must see the row.
    await db.commit()

    task = asyncio.create_task(
        run_source_gap_analysis(
            run_id=run_id,
            project_id=project.id,
            provider_id=body.provider_id,
            db_factory=async_session,
        )
    )
    _gap_tasks[run_id] = task
    task.add_done_callback(lambda _t, rid=run_id: _gap_tasks.pop(rid, None))
    return GapRunCreateResponse(run_id=run_id, status="pending")


def _summary_from_run(run: SourceGapRun) -> GapRunSummary:
    summary = (run.results or {}).get("summary", {})
    return GapRunSummary(
        id=run.id,
        provider_id=run.provider_id,
        status=run.status,
        total=run.total,
        processed=run.processed,
        covered=int(summary.get("covered") or 0),
        missing=int(summary.get("missing") or 0),
        review=int(summary.get("review") or 0),
        acked=int(summary.get("acked") or 0),
        error=run.error,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.get("/gap-runs", response_model=GapRunSummaryListResponse)
async def list_gap_runs(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(SourceGapRun)
        .where(
            SourceGapRun.project_id == project.id, SourceGapRun.provider_id == provider_id
        )
        .order_by(SourceGapRun.created_at.desc())
    )
    return GapRunSummaryListResponse(data=[_summary_from_run(r) for r in result.scalars().all()])


async def _run_or_404(db: AsyncSession, run_id: UUID, project: Project) -> SourceGapRun:
    run = (
        await db.execute(
            select(SourceGapRun).where(
                SourceGapRun.id == run_id, SourceGapRun.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise _not_found("Gap run")
    return run


@router.get("/gap-runs/{run_id}", response_model=GapRunResponse)
async def get_gap_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    return await _run_or_404(db, run_id, project)


@router.get("/gap-runs/{run_id}/report", response_class=PlainTextResponse)
async def get_gap_run_report(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    run = await _run_or_404(db, run_id, project)
    if run.status != "completed" or not run.results:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "NOT_READY", "message": "Gap run has no results yet"}},
        )
    provider = await _provider_or_404(db, run.provider_id, project)
    generated = (run.completed_at or run.created_at).strftime("%Y-%m-%d %H:%M UTC")
    markdown = build_markdown_report(run.results, provider.name, generated)
    return PlainTextResponse(content=markdown, media_type="text/markdown; charset=utf-8")
