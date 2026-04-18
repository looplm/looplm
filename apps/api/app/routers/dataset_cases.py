"""Test case CRUD endpoints (sub-router of datasets)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_write
from app.db import get_db
from app.models.models import TestCase, TestDataset
from app.models.project import Project
from app.schemas.datasets import TestCaseCreate, TestCaseItem, TestCaseUpdate

from .dataset_helpers import _tc_to_item

router = APIRouter(tags=["datasets"])


@router.post(
    "/{dataset_id}/cases",
    response_model=TestCaseItem,
    status_code=201,
    dependencies=[require_write("evaluate", "datasets")],
)
async def create_test_case(
    dataset_id: UUID,
    body: TestCaseCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(TestDataset).where(TestDataset.id == dataset_id, TestDataset.project_id == project.id)
    )
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}})

    tc = TestCase(
        dataset_id=ds.id,
        test_id=body.test_id,
        prompt=body.prompt,
        expected_answer=body.expected_answer,
        expected_sources=body.expected_sources,
        context_filters=body.context_filters,
        team_filter=body.team_filter,
        tag_filter=body.tag_filter,
        message_count=body.message_count,
        has_summary=body.has_summary,
        folder=body.folder,
        document=body.document,
        expected_page_urls=body.expected_page_urls,
        expected_source_types=body.expected_source_types,
        follow_up_prompts=body.follow_up_prompts,
        source_feedback_id=body.source_feedback_id,
        source_trace_id=body.source_trace_id,
        tags=body.tags,
        test_case_metadata=body.metadata,
    )
    db.add(tc)
    await db.flush()
    await db.refresh(tc)
    return _tc_to_item(tc)


@router.post(
    "/{dataset_id}/cases/from-suggestion",
    response_model=TestCaseItem,
    status_code=201,
    dependencies=[require_write("evaluate", "datasets")],
)
async def create_from_suggestion(
    dataset_id: UUID,
    body: TestCaseCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Accept a suggestion as a test case. Same as create but semantic alias."""
    return await create_test_case(dataset_id, body, db, project)


@router.patch(
    "/{dataset_id}/cases/{case_id}",
    response_model=TestCaseItem,
    dependencies=[require_write("evaluate", "datasets")],
)
async def update_test_case(
    dataset_id: UUID,
    case_id: UUID,
    body: TestCaseUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    # Verify dataset belongs to project
    ds_result = await db.execute(
        select(TestDataset).where(TestDataset.id == dataset_id, TestDataset.project_id == project.id)
    )
    if not ds_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}})

    result = await db.execute(
        select(TestCase).where(TestCase.id == case_id, TestCase.dataset_id == dataset_id)
    )
    tc = result.scalar_one_or_none()
    if not tc:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Test case not found"}})

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "metadata":
            tc.test_case_metadata = value
        else:
            setattr(tc, field, value)

    await db.flush()
    await db.refresh(tc)
    return _tc_to_item(tc)


@router.delete(
    "/{dataset_id}/cases/{case_id}",
    status_code=204,
    dependencies=[require_write("evaluate", "datasets")],
)
async def delete_test_case(
    dataset_id: UUID,
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    ds_result = await db.execute(
        select(TestDataset).where(TestDataset.id == dataset_id, TestDataset.project_id == project.id)
    )
    if not ds_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}})

    result = await db.execute(
        select(TestCase).where(TestCase.id == case_id, TestCase.dataset_id == dataset_id)
    )
    tc = result.scalar_one_or_none()
    if not tc:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Test case not found"}})
    await db.delete(tc)
