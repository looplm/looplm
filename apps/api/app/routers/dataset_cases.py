"""Test case CRUD endpoints (sub-router of datasets)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_project, require_write
from app.db import get_db
from app.models.models import Integration, TestCase, TestDataset, Trace
from app.models.project import Project
from app.schemas.datasets import (
    ExpectedUrlsAdd,
    ExpectedUrlsResponse,
    TestCaseCreate,
    TestCaseItem,
    TestCaseUpdate,
)
from app.services.failure_pattern import normalize_result_test_id
from app.services.rag_pipeline import build_rag_pipeline, rag_pipeline_summary
from app.services.retrieval_config import get_rag_span_names

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

    # When the case is built from a source trace, capture the RAG pipeline funnel for
    # provenance and prefill expected sources from the ones actually used in context.
    metadata = dict(body.metadata or {})
    expected_sources = body.expected_sources
    if body.source_trace_id:
        summary = await _trace_rag_summary(db, body.source_trace_id, project)
        if summary:
            metadata.setdefault("rag_pipeline", summary)
            if not expected_sources and summary["used_source_urls"]:
                expected_sources = summary["used_source_urls"]

    tc = TestCase(
        dataset_id=ds.id,
        test_id=body.test_id,
        prompt=body.prompt,
        expected_answer=body.expected_answer,
        expected_sources=expected_sources,
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
        test_case_metadata=metadata,
    )
    db.add(tc)
    await db.flush()
    await db.refresh(tc)
    return _tc_to_item(tc)


async def _trace_rag_summary(db: AsyncSession, trace_id: UUID, project: Project) -> dict | None:
    """Build a compact RAG-pipeline summary for a project-scoped trace, or None."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    result = await db.execute(
        select(Trace)
        .where(Trace.id == trace_id, Trace.integration_id.in_(project_integration_ids))
        .options(selectinload(Trace.spans))
    )
    trace = result.scalar_one_or_none()
    if not trace:
        return None
    return rag_pipeline_summary(build_rag_pipeline(trace, get_rag_span_names(project)))


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


@router.get(
    "/{dataset_id}/cases/expected-urls",
    response_model=ExpectedUrlsResponse,
)
async def get_expected_urls(
    dataset_id: UUID,
    test_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Return a test case's current ``expected_page_urls``, looked up by ``test_id``.

    Lets the eval results view mark retrieved URLs that have since been promoted
    into the expected set (the run's own snapshot only reflects what was expected
    when it ran). ``test_id`` may carry the executor's variant suffix.
    """
    ds_result = await db.execute(
        select(TestDataset).where(TestDataset.id == dataset_id, TestDataset.project_id == project.id)
    )
    if not ds_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}})

    normalized = normalize_result_test_id(test_id)
    result = await db.execute(
        select(TestCase).where(TestCase.dataset_id == dataset_id, TestCase.test_id == normalized)
    )
    tc = result.scalars().first()
    if not tc:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Test case not found"}})

    return ExpectedUrlsResponse(test_id=tc.test_id, expected_page_urls=tc.expected_page_urls or [])


@router.post(
    "/{dataset_id}/cases/expected-urls",
    response_model=TestCaseItem,
    dependencies=[require_write("evaluate", "datasets")],
)
async def add_expected_urls(
    dataset_id: UUID,
    body: ExpectedUrlsAdd,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Append URLs to a test case's ``expected_page_urls`` (deduped, order-preserving).

    Looked up by ``test_id`` (variant suffix stripped) so the eval results view can
    promote retrieved source URLs without knowing the test case's UUID.
    """
    ds_result = await db.execute(
        select(TestDataset).where(TestDataset.id == dataset_id, TestDataset.project_id == project.id)
    )
    if not ds_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}})

    test_id = normalize_result_test_id(body.test_id)
    result = await db.execute(
        select(TestCase).where(TestCase.dataset_id == dataset_id, TestCase.test_id == test_id)
    )
    tc = result.scalars().first()
    if not tc:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Test case not found"}})

    merged = list(tc.expected_page_urls or [])
    seen = set(merged)
    for url in body.urls:
        url = url.strip()
        if url and url not in seen:
            merged.append(url)
            seen.add(url)
    tc.expected_page_urls = merged

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
