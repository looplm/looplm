"""Read endpoints for the chunk-labeling flow: the labeling view, candidate pool, metadata."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user
from app.db import get_db
from app.index_providers.registry import build_index_provider
from app.models.chunk_labels import TestCaseLabelingStatus
from app.models.datasets import TestCase
from app.models.index_providers import IndexProvider
from app.models.passage_labels import PASSAGE_SOURCE_CHUNK_SPLIT, PassageRelevanceLabel
from app.models.project import Project
from app.models.user import User
from app.schemas.retrieval import (
    ChunkMetadataResponse,
    ChunkPassagesResponse,
    LabelingPoolResponse,
    LabelingPromptDefaults,
    LabelingQueries,
    LabelingRunResponse,
    PassageForLabeling,
)
from app.services.chunk_ai_judge import DEFAULT_AI_JUDGE_INSTRUCTIONS
from app.services.chunk_labeling import (
    build_labeling_cases,
    build_pool_view,
    merge_labeling_view,
)
from app.services.passage_split import split_chunk_into_passages
from app.services.query_planner import DEFAULT_QUERY_PLANNER_INSTRUCTIONS

from ._helpers import (
    INDEX_HEADING_FIELDS,
    INDEX_TEXT_FIELDS,
    _dataset_case_query,
    _display_name,
    _first_str_field,
    _list_dataset_options,
    _project_labels,
    _resolve_dataset,
    assemble_case_pool,
    ensure_case_agentic_queries,
    fetch_chunk_fields,
)

router = APIRouter()


@router.get("/labeling", response_model=LabelingRunResponse)
async def get_labeling_view(
    dataset_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """A dataset's test cases, grouped per case, with the viewer's own label tallies merged in.

    Labeling operates on a dataset (chosen with ``dataset_id``; defaults to the most recently
    updated one). Each case is a query to judge; the chunks themselves are pooled live per case
    from the connected index via ``/labeling/pool``. Labels and per-case status are keyed by
    ``test_id`` and re-merged live, so judgments made under any dataset that shares a test_id
    carry over. ``datasets`` lists every dataset for the picker.
    """
    datasets = await _list_dataset_options(db, project)
    dataset = await _resolve_dataset(db, project, dataset_id)
    if dataset is None:
        # Project has no datasets yet — nothing to label, but still return the (empty) picker.
        return LabelingRunResponse(available=False, datasets=datasets)

    test_cases = (
        await db.execute(select(TestCase).where(TestCase.dataset_id == dataset.id))
    ).scalars().all()
    cases, total_cases = build_labeling_cases(test_cases)

    labels_by_key, _labeler_by_key, labelers_by_test, _ai = await _project_labels(
        db, project, user_id=user.id
    )

    statuses = (
        await db.execute(
            select(TestCaseLabelingStatus).where(TestCaseLabelingStatus.project_id == project.id)
        )
    ).scalars().all()
    complete_by_test = {s.test_id: s.complete for s in statuses}
    slice_by_test = {s.test_id: s.slice for s in statuses if s.slice}

    return merge_labeling_view(
        cases,
        total_cases,
        labels_by_key,
        dataset_id=str(dataset.id),
        dataset_name=dataset.name,
        datasets=datasets,
        complete_by_test=complete_by_test,
        slice_by_test=slice_by_test,
        labelers_by_test=labelers_by_test,
    )


@router.get("/labeling/pool", response_model=LabelingPoolResponse)
async def get_labeling_pool(
    test_id: str,
    dataset_id: UUID | None = None,
    q: str | None = None,
    depth: int | None = None,
    refresh: bool = False,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Multi-head candidate pool for one dataset test case: the chunks to judge.

    Runs the connected index's heads (keyword/vector/hybrid) for the case's query and merges
    them, deduped by chunk id — this *is* the set of chunks the labeler judges. ``q`` overrides
    the query (the manual "find more candidates" box); without it the dataset case's prompt is
    used. ``depth`` tunes per-head top-k (otherwise slice-driven). With no index provider
    connected the pool is empty (nothing to label).
    """
    dataset = await _resolve_dataset(db, project, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}},
        )

    # A manual-search query stands on its own; otherwise use the dataset case's prompt.
    manual = bool(q and q.strip())
    case_query = await _dataset_case_query(db, dataset.id, test_id)
    if not manual and case_query is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Test case not found in dataset"}},
        )
    query = (q if manual else str(case_query or "")).strip()

    # Fold the case's planned agentic sub-queries into the auto pool (not a manual one-off search).
    # The planner runs automatically the first time a case is pooled — exactly once, persisted even
    # when it plans nothing — so the agentic retrieval path is judged alongside the base heads
    # without a separate click. The AI judge shares this helper, so both pool the same candidates.
    agentic: list[str] = []
    if not manual:
        agentic = await ensure_case_agentic_queries(
            db, project, user, dataset_id=dataset.id, test_id=test_id, query=query
        )

    pool, computed_at, provider_connected = await assemble_case_pool(
        db, project, test_id, query, depth=depth, manual=manual, refresh=refresh,
        agentic_queries=agentic,
    )

    labels_by_key, labeler_by_key, _, ai_labels_by_key = await _project_labels(
        db, project, user_id=user.id
    )
    return build_pool_view(
        test_id,
        (case_query or query) or None,
        pool,
        provider_connected=provider_connected,
        labels_by_key=labels_by_key,
        labeler_by_key=labeler_by_key,
        ai_labels_by_key=ai_labels_by_key,
        computed_at=computed_at,
        queries=LabelingQueries(base=[query] if query else [], agentic=agentic),
    )


@router.get("/labeling/prompts", response_model=LabelingPromptDefaults)
async def get_labeling_prompts(
    project: Project = Depends(get_current_project),
):
    """Default rubrics for the AI judge and query planner, so the UI shows the real text.

    The reviewer can edit these before running either; the defaults are sourced from the services
    so the displayed text never drifts from what actually runs.
    """
    return LabelingPromptDefaults(
        ai_judge=DEFAULT_AI_JUDGE_INSTRUCTIONS,
        query_planner=DEFAULT_QUERY_PLANNER_INSTRUCTIONS,
    )


@router.get("/chunk-passages", response_model=ChunkPassagesResponse)
async def get_chunk_passages(
    test_id: str,
    chunk_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """The finer-grained passages of one pooled chunk, for the passage-selection panel.

    An additive refinement of chunk labeling: the chunk grade stays primary; here a labeler can
    additionally mark which passages *within* the chunk help answer the query. Fetches the chunk's
    full body from the index and splits it locally into sentence/line passages (the *A* source);
    the viewer's own prior selections are overlaid so the checkboxes reflect their state. Returns
    ``available=False`` when no index is connected or the chunk has no splittable text.
    """
    fields, provider_connected = await fetch_chunk_fields(db, project, chunk_id)
    if not provider_connected or fields is None:
        return ChunkPassagesResponse(
            test_id=test_id,
            chunk_id=chunk_id,
            provider_connected=provider_connected,
            available=False,
        )

    text = _first_str_field(fields, INDEX_TEXT_FIELDS)
    heading = _first_str_field(fields, INDEX_HEADING_FIELDS)
    split = split_chunk_into_passages(chunk_id, text, section_path=heading)
    if not split:
        return ChunkPassagesResponse(
            test_id=test_id,
            chunk_id=chunk_id,
            provider_connected=True,
            available=False,
            section_path=heading,
        )

    # Overlay the viewer's own prior selections (human rows only — annotator NULL).
    existing = (
        await db.execute(
            select(PassageRelevanceLabel).where(
                PassageRelevanceLabel.project_id == project.id,
                PassageRelevanceLabel.test_id == test_id,
                PassageRelevanceLabel.chunk_id == chunk_id,
                PassageRelevanceLabel.labeled_by == user.id,
                PassageRelevanceLabel.annotator.is_(None),
            )
        )
    ).scalars().all()
    relevant_by_pid = {row.passage_id: row.relevant for row in existing}
    viewer_name = _display_name(user.email)

    passages = [
        PassageForLabeling(
            passage_id=p.passage_id,
            text=p.text,
            section_path=p.section_path,
            passage_source=p.passage_source,
            relevant=relevant_by_pid.get(p.passage_id),
            labeled_by=viewer_name if p.passage_id in relevant_by_pid else None,
        )
        for p in split
    ]
    return ChunkPassagesResponse(
        test_id=test_id,
        chunk_id=chunk_id,
        provider_connected=True,
        available=True,
        passage_source=PASSAGE_SOURCE_CHUNK_SPLIT,
        section_path=heading,
        passages=passages,
    )


@router.get("/chunk-metadata", response_model=ChunkMetadataResponse)
async def get_chunk_metadata(
    chunk_id: str,
    provider_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """All index fields for a chunk, fetched live from the project's index provider.

    Returns ``provider_connected=False`` when the project has no index provider, so the UI
    can hide the feature; ``available=False`` when the chunk is not found in the index.
    """
    pf = [IndexProvider.project_id == project.id]
    if provider_id is not None:
        pf.append(IndexProvider.id == provider_id)
    provider_row = (
        await db.execute(
            select(IndexProvider).where(*pf).order_by(IndexProvider.created_at.asc()).limit(1)
        )
    ).scalar_one_or_none()
    if provider_row is None:
        return ChunkMetadataResponse(provider_connected=False, available=False)

    provider = build_index_provider(provider_row)
    try:
        docs = await provider.fetch_documents_by_key([chunk_id])
    finally:
        await provider.aclose()

    fields = docs.get(chunk_id)
    return ChunkMetadataResponse(
        provider_connected=True, available=fields is not None, fields=fields
    )
