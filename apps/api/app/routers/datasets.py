"""Test dataset endpoints."""

from __future__ import annotations

import logging
from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section
from app.db import get_db
from app.models.models import FeedbackScore, Integration, JsonImport, TestCase, TestDataset, Trace
from app.models.project import Project
from app.schemas.datasets import (
    ExportResponse,
    ExportTestCase,
    ImportRequest,
    TestCaseSuggestion,
    TestDatasetCreate,
    TestDatasetDetail,
    TestDatasetItem,
    TestDatasetListResponse,
    TestDatasetUpdate,
)
from app.schemas.evaluations import PaginationInfo

from .dataset_helpers import _tc_to_item, build_suggestions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/datasets", tags=["datasets"], dependencies=[require_section("evaluate")])

from .dataset_cases import router as dataset_cases_router
router.include_router(dataset_cases_router)


# ── Dataset CRUD ──────────────────────────────────────────────

@router.get("", response_model=TestDatasetListResponse)
async def list_datasets(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    base = [TestDataset.project_id == project.id]

    total = (await db.execute(
        select(func.count(TestDataset.id)).where(*base)
    )).scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = (
        select(TestDataset)
        .where(*base)
        .order_by(TestDataset.updated_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(query)
    datasets = result.scalars().all()

    data = []
    for ds in datasets:
        count = (await db.execute(
            select(func.count(TestCase.id)).where(TestCase.dataset_id == ds.id)
        )).scalar() or 0
        data.append(TestDatasetItem(
            id=ds.id,
            name=ds.name,
            description=ds.description,
            tags=ds.tags or [],
            test_count=count,
            created_at=ds.created_at,
            updated_at=ds.updated_at,
        ))

    return TestDatasetListResponse(
        data=data,
        pagination=PaginationInfo(page=page, per_page=per_page, total=total, total_pages=total_pages),
    )


@router.post("", response_model=TestDatasetItem, status_code=201)
async def create_dataset(
    body: TestDatasetCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    ds = TestDataset(
        project_id=project.id,
        name=body.name,
        description=body.description,
        tags=body.tags,
    )
    db.add(ds)
    await db.flush()
    await db.refresh(ds)

    return TestDatasetItem(
        id=ds.id,
        name=ds.name,
        description=ds.description,
        tags=ds.tags or [],
        test_count=0,
        created_at=ds.created_at,
        updated_at=ds.updated_at,
    )


@router.get("/suggestions", response_model=list[TestCaseSuggestion])
async def get_suggestions(
    feedback_type: str = Query("all", pattern="^(positive|negative|all)$"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Generate test case suggestions from recent feedback."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    query = (
        select(FeedbackScore, Trace)
        .outerjoin(Trace, FeedbackScore.trace_id == Trace.id)
        .where(
            FeedbackScore.integration_id.in_(project_integration_ids),
            FeedbackScore.score_name == "user-feedback",
        )
    )

    if feedback_type == "positive":
        query = query.where(FeedbackScore.value == 1)
    elif feedback_type == "negative":
        query = query.where(FeedbackScore.value == 0)

    query = query.order_by(FeedbackScore.scored_at.desc()).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    return build_suggestions(rows)


@router.post("/import", response_model=TestDatasetItem, status_code=201)
async def import_dataset(
    body: ImportRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Import a dataset from a legacy JSON format."""
    ds = TestDataset(
        project_id=project.id,
        name=body.name or "Imported Dataset",
        description=body.description,
        tags=[],
    )
    db.add(ds)
    await db.flush()

    for tc_data in body.testCases:
        tc = TestCase(
            dataset_id=ds.id,
            test_id=tc_data.get("id", ""),
            prompt=tc_data.get("prompt", ""),
            expected_answer=tc_data.get("expectedAnswer"),
            expected_sources=tc_data.get("expectedSources", []),
            context_filters=tc_data.get("filters", {}),
            team_filter=tc_data.get("teamFilter", []),
            tag_filter=tc_data.get("tagFilter", []),
            folder=tc_data.get("folder"),
            document=tc_data.get("document"),
            expected_page_urls=tc_data.get("expectedPageUrls", []),
            expected_source_types=tc_data.get("expectedSourceTypes", []),
            max_answer_length=tc_data.get("maxAnswerLength"),
            follow_up_prompts=tc_data.get("followUpPrompts"),
            tags=[],
            test_case_metadata=tc_data.get("metadata", {}),
        )
        db.add(tc)

    await db.flush()
    await db.refresh(ds)

    count = (await db.execute(
        select(func.count(TestCase.id)).where(TestCase.dataset_id == ds.id)
    )).scalar() or 0

    # Record import history
    db.add(JsonImport(
        project_id=project.id,
        entity_type="datasets",
        filename=body.filename,
        record_count=count,
    ))
    await db.flush()

    return TestDatasetItem(
        id=ds.id,
        name=ds.name,
        description=ds.description,
        tags=ds.tags or [],
        test_count=count,
        created_at=ds.created_at,
        updated_at=ds.updated_at,
    )


@router.get("/{dataset_id}", response_model=TestDatasetDetail)
async def get_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(TestDataset).where(TestDataset.id == dataset_id, TestDataset.project_id == project.id)
    )
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}})

    cases_result = await db.execute(
        select(TestCase).where(TestCase.dataset_id == ds.id).order_by(TestCase.test_id)
    )
    cases = cases_result.scalars().all()

    return TestDatasetDetail(
        id=ds.id,
        name=ds.name,
        description=ds.description,
        tags=ds.tags or [],
        test_count=len(cases),
        created_at=ds.created_at,
        updated_at=ds.updated_at,
        test_cases=[_tc_to_item(tc) for tc in cases],
    )


@router.patch("/{dataset_id}", response_model=TestDatasetItem)
async def update_dataset(
    dataset_id: UUID,
    body: TestDatasetUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(TestDataset).where(TestDataset.id == dataset_id, TestDataset.project_id == project.id)
    )
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}})

    if body.name is not None:
        ds.name = body.name
    if body.description is not None:
        ds.description = body.description
    if body.tags is not None:
        ds.tags = body.tags

    await db.flush()
    await db.refresh(ds)

    count = (await db.execute(
        select(func.count(TestCase.id)).where(TestCase.dataset_id == ds.id)
    )).scalar() or 0

    return TestDatasetItem(
        id=ds.id,
        name=ds.name,
        description=ds.description,
        tags=ds.tags or [],
        test_count=count,
        created_at=ds.created_at,
        updated_at=ds.updated_at,
    )


@router.delete("/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(TestDataset).where(TestDataset.id == dataset_id, TestDataset.project_id == project.id)
    )
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}})
    await db.delete(ds)


# ── Export ────────────────────────────────────────────────────

@router.get("/{dataset_id}/export", response_model=ExportResponse)
async def export_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(TestDataset).where(TestDataset.id == dataset_id, TestDataset.project_id == project.id)
    )
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}})

    cases_result = await db.execute(
        select(TestCase).where(TestCase.dataset_id == ds.id).order_by(TestCase.test_id)
    )
    cases = cases_result.scalars().all()

    return ExportResponse(
        name=ds.name,
        description=ds.description,
        testCases=[
            ExportTestCase(
                id=tc.test_id,
                prompt=tc.prompt,
                expectedAnswer=tc.expected_answer,
                expectedSources=tc.expected_sources or [],
                teamFilter=tc.team_filter or [],
                tagFilter=tc.tag_filter or [],
                filters=tc.context_filters or {},
                folder=tc.folder,
                document=tc.document,
                expectedPageUrls=tc.expected_page_urls or [],
                expectedSourceTypes=tc.expected_source_types or [],
                maxAnswerLength=tc.max_answer_length,
                followUpPrompts=tc.follow_up_prompts,
                metadata=tc.test_case_metadata or {},
            )
            for tc in cases
        ],
    )

