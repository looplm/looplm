"""Test case CRUD endpoints (sub-router of datasets)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_project, get_current_user, require_write
from app.db import get_db
from app.models.datasets import is_no_retrieval_expected
from app.models.models import Integration, TestCase, TestDataset, Trace
from app.models.project import Project
from app.models.user import User
from app.schemas.datasets import (
    ExpectedUrlsAdd,
    ExpectedUrlsResponse,
    ExpectedUrlsSyncAllRequest,
    ExpectedUrlsSyncAllResponse,
    ExpectedUrlsSyncCase,
    ExpectedUrlsSyncDatasetResult,
    ExpectedUrlsSyncRequest,
    ExpectedUrlsSyncResponse,
    TestCaseCreate,
    TestCaseItem,
    TestCaseUpdate,
)
from app.services.chunk_gold import gold_relevant_urls_by_test
from app.services.failure_pattern import normalize_result_test_id
from app.services.rag_pipeline import build_rag_pipeline, rag_pipeline_summary
from app.services.retrieval_config import get_rag_span_names, normalize_source_url

from .dataset_helpers import _display_name, _tc_to_item, resolve_validator_names

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
    user: User = Depends(get_current_user),
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
        elif field == "validated":
            # Stamp the validating user server-side; never trust a client-supplied identity.
            tc.validated = bool(value)
            if value:
                tc.validated_by = user.id
                tc.validated_at = datetime.now(timezone.utc)
            else:
                tc.validated_by = None
                tc.validated_at = None
        else:
            setattr(tc, field, value)

    await db.flush()
    await db.refresh(tc)
    # The validator is usually the current request user, whose email we already
    # hold; only hit the DB when someone else validated the case earlier.
    if tc.validated_by is None:
        validated_email = None
    elif tc.validated_by == user.id:
        validated_email = _display_name(user.email)
    else:
        names = await resolve_validator_names(db, [tc])
        validated_email = names.get(tc.validated_by)
    return _tc_to_item(tc, validated_email)


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


def _apply_url_sync(tc: TestCase, label_urls: list[str], mode: str) -> ExpectedUrlsSyncCase | None:
    """Overwrite (``replace``) or extend (``merge``) a case's expected_page_urls from labels.

    Returns the change record, or ``None`` when the case was already in sync. Added/removed
    counts compare normalized URL sets, so a slug variant of an existing URL doesn't count as
    a change.
    """
    current = list(tc.expected_page_urls or [])
    if mode == "replace":
        new_urls = label_urls
    else:
        existing_norm = {normalize_source_url(u.strip()) for u in current if u.strip()}
        new_urls = current + [u for u in label_urls if normalize_source_url(u) not in existing_norm]

    if new_urls == current:
        return None
    current_norm = {normalize_source_url(u.strip()) for u in current if u.strip()}
    new_norm = {normalize_source_url(u) for u in new_urls}
    tc.expected_page_urls = new_urls
    return ExpectedUrlsSyncCase(
        test_id=tc.test_id,
        expected_page_urls=new_urls,
        added=len(new_norm - current_norm),
        removed=len(current_norm - new_norm),
    )


@router.post(
    "/expected-urls/sync-from-labels",
    response_model=ExpectedUrlsSyncAllResponse,
    dependencies=[require_write("evaluate", "datasets")],
)
async def sync_expected_urls_from_labels_all_datasets(
    body: ExpectedUrlsSyncAllRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Sync ``expected_page_urls`` from chunk labels across every dataset in the project.

    One-click variant of the per-dataset sync: same merge/replace semantics, applied to all
    test cases of all datasets, with the outcome grouped per dataset. Cases without
    labeled-relevant URLs are skipped, never wiped; cases tagged no-retrieval-expected are
    reported in ``flagged`` and never touched. Datasets without test cases are omitted.
    """
    derived = await gold_relevant_urls_by_test(db, project, body.gold_source)

    rows = (
        await db.execute(
            select(TestCase, TestDataset)
            .join(TestDataset, TestCase.dataset_id == TestDataset.id)
            .where(TestDataset.project_id == project.id)
            .order_by(TestDataset.name, TestCase.test_id)
        )
    ).all()

    results: dict[str, ExpectedUrlsSyncDatasetResult] = {}
    for tc, ds in rows:
        result = results.setdefault(
            str(ds.id),
            ExpectedUrlsSyncDatasetResult(
                dataset_id=ds.id, dataset_name=ds.name, updated=[], unchanged=[], skipped=[]
            ),
        )
        if is_no_retrieval_expected(tc.tags):
            result.flagged.append(tc.test_id)
            continue
        label_urls = derived.get(tc.test_id) or []
        if not label_urls:
            result.skipped.append(tc.test_id)
            continue
        change = _apply_url_sync(tc, label_urls, body.mode)
        if change is None:
            result.unchanged.append(tc.test_id)
        else:
            result.updated.append(change)

    await db.flush()
    datasets = list(results.values())
    return ExpectedUrlsSyncAllResponse(
        mode=body.mode,
        datasets=datasets,
        total_updated=sum(len(d.updated) for d in datasets),
        total_unchanged=sum(len(d.unchanged) for d in datasets),
        total_skipped=sum(len(d.skipped) for d in datasets),
        total_flagged=sum(len(d.flagged) for d in datasets),
    )


@router.post(
    "/{dataset_id}/cases/expected-urls/sync-from-labels",
    response_model=ExpectedUrlsSyncResponse,
    dependencies=[require_write("evaluate", "datasets")],
)
async def sync_expected_urls_from_labels(
    dataset_id: UUID,
    body: ExpectedUrlsSyncRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Rebuild ``expected_page_urls`` from the gold-relevant chunk labels.

    ``replace`` discards a case's current URL list and recomputes it from the labels; ``merge``
    appends label-derived URLs the case doesn't already have (compared after URL
    normalization). With no ``test_id`` every case in the dataset is synced. A case whose
    labels yield no relevant URL is never wiped: dataset-wide it is reported in ``skipped``,
    and a single-case replace fails with 409 so a typo can't silently clear ground truth.
    Cases tagged no-retrieval-expected are never synced: dataset-wide they are reported in
    ``flagged``, single-case they fail with 409.
    """
    ds_result = await db.execute(
        select(TestDataset).where(TestDataset.id == dataset_id, TestDataset.project_id == project.id)
    )
    if not ds_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}})

    case_filter = [TestCase.dataset_id == dataset_id]
    if body.test_id:
        case_filter.append(TestCase.test_id == normalize_result_test_id(body.test_id))
    cases = (await db.execute(select(TestCase).where(*case_filter))).scalars().all()
    if body.test_id and not cases:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Test case not found"}})

    derived = await gold_relevant_urls_by_test(db, project, body.gold_source)

    updated: list[ExpectedUrlsSyncCase] = []
    unchanged: list[str] = []
    skipped: list[str] = []
    flagged: list[str] = []
    for tc in cases:
        if is_no_retrieval_expected(tc.tags):
            if body.test_id:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": {
                            "code": "NO_RETRIEVAL_EXPECTED",
                            "message": "This test case is flagged as no-retrieval-expected; expected URLs are not synced for it",
                        }
                    },
                )
            flagged.append(tc.test_id)
            continue
        label_urls = derived.get(tc.test_id) or []
        if not label_urls:
            if body.test_id and body.mode == "replace":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": {
                            "code": "NO_LABELED_URLS",
                            "message": "No chunks with a source URL are labeled relevant for this test case",
                        }
                    },
                )
            skipped.append(tc.test_id)
            continue
        change = _apply_url_sync(tc, label_urls, body.mode)
        if change is None:
            unchanged.append(tc.test_id)
        else:
            updated.append(change)

    await db.flush()
    return ExpectedUrlsSyncResponse(
        mode=body.mode, updated=updated, unchanged=unchanged, skipped=skipped, flagged=flagged
    )


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
