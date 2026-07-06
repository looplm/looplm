"""LLM-backed labeling operations: the AI judge (second-opinion grader) and the query planner.

Both route through :class:`AnalysisLlmService` (the project's configured OpenAI / Azure provider),
judge or plan against the *same* pooled chunks the labeler sees, and record token usage. Kept
apart from the human label CRUD in ``operations.py`` so each file stays focused (and under the
size limit).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section, require_write
from app.db import get_db
from app.models.chunk_labels import AI_ANNOTATOR, ChunkRelevanceLabel
from app.models.datasets import NO_RETRIEVAL_TAG, is_no_retrieval_expected
from app.models.project import Project
from app.models.user import User
from app.schemas.retrieval import (
    AiJudgePreviewResponse,
    AiJudgePromptBatch,
    AiJudgeRequest,
    AiJudgeResponse,
    PlanQueriesRequest,
    PlanQueriesResponse,
)
from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService
from app.services.chunk_ai_judge import (
    AiJudgeChunk,
    ai_judge_chunks,
    plan_ai_judge_prompts,
)
from app.services.llm_usage_tracker import record_llm_usage

from ._helpers import (
    _as_uuid,
    _dataset_case_agentic_queries,
    _dataset_case_expected_answer,
    _dataset_case_query,
    _dataset_case_tags,
    _resolve_dataset,
    assemble_case_pool,
    ensure_case_agentic_queries,
    fetch_full_chunk_texts,
    plan_and_persist_case_queries,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/labeling/ai-judge",
    response_model=AiJudgeResponse,
    dependencies=[require_write("evaluate", "labeling")],
)
async def ai_judge_case(
    body: AiJudgeRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Grade a test case's retrieved chunks with the LLM, stored under the ``AI`` annotator.

    A one-click second opinion: the model judges each chunk's relevance to the query on the same
    0..3 scale a human uses. The grades become labels attributed to the AI annotator — a distinct
    annotator in the agreement panel (so a lone human reviewer gets a Cohen's kappa against the
    model) but excluded from the gold that feeds the retrieval metrics. Re-running re-grades the
    same chunks (the AI annotator owns one label per chunk).
    """
    # Resolve the dataset case's query, then judge the same pooled chunks the labeler sees.
    dataset = await _resolve_dataset(db, project, _as_uuid(body.dataset_id))
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}},
        )
    query = await _dataset_case_query(db, dataset.id, body.test_id)
    if query is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Test case not found in dataset"}},
        )
    # Negative cases must never accumulate AI relevance labels: those labels would feed
    # gold_source=ai/both and the expected-URL sync, attaching ground truth to a query that
    # by design retrieves nothing.
    if is_no_retrieval_expected(await _dataset_case_tags(db, dataset.id, body.test_id)):
        return AiJudgeResponse(test_id=body.test_id, skipped_reason=NO_RETRIEVAL_TAG)

    try:
        llm = AnalysisLlmService(user_settings=user.settings, project_settings=project.settings)
    except AnalysisLlmConfigError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "LLM_NOT_CONFIGURED", "message": str(exc)}},
        ) from exc

    # Judge the *same* chunks the labeler sees, including any agentic-pooled candidates. Plan the
    # agentic queries here if they were never planned (e.g. a batch judge over cases never opened in
    # the UI) so the judge never grades a base-only pool the labeler will later see augmented.
    agentic = await ensure_case_agentic_queries(
        db, project, user, dataset_id=dataset.id, test_id=body.test_id, query=query
    )
    pool, _computed_at, _connected = await assemble_case_pool(
        db, project, body.test_id, query, agentic_queries=agentic, refresh=body.refresh
    )
    if not pool.chunks:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "NO_CHUNKS",
                    "message": "No chunks to judge — connect an index provider so candidates can be pooled.",
                }
            },
        )

    # Snapshot fields (kept on the stored label so the chunk stays readable) come from the pool.
    snapshots = {
        pc.chunk_id: {"content_preview": pc.content_preview, "url": pc.url, "title": pc.title}
        for pc in pool.chunks
    }
    # Grade the FULL chunk text, not the pool's truncated display preview — fall back to the preview
    # only for chunks the index can't resolve.
    full_texts = await fetch_full_chunk_texts(db, project, [pc.chunk_id for pc in pool.chunks])
    chunks = [
        AiJudgeChunk(
            chunk_id=pc.chunk_id,
            text=full_texts.get(pc.chunk_id) or str(pc.content_preview or ""),
        )
        for pc in pool.chunks
    ]
    # Reference answer, when the case has one, sharpens the judge's relevance calls (context, not
    # a match target). Absent, or opted out via the request, → the judge grades on query-relevance
    # alone.
    expected_answer = (
        await _dataset_case_expected_answer(db, dataset.id, body.test_id)
        if body.include_expected_answer
        else None
    )
    try:
        grades, usage = await ai_judge_chunks(
            llm, query, chunks, instructions=body.instructions, expected_answer=expected_answer
        )
    except AnalysisLlmConfigError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "LLM_NOT_CONFIGURED", "message": str(exc)}},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI judge failed for test_id=%s", body.test_id)
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "AI_JUDGE_FAILED",
                    "message": f"The AI judge call failed: {exc}",
                }
            },
        ) from exc

    await record_llm_usage(
        db,
        project_id=project.id,
        service_name="chunk_labeling",
        function_name="ai_judge",
        provider=llm.provider,
        model=llm.model,
        usage=usage,
        request_metadata={"test_id": body.test_id, "chunks": len(chunks)},
    )

    # Upsert the AI annotator's own labels (one per chunk). AI rows carry annotator=AI and no
    # user, so they never collide with a human's label for the same chunk.
    existing = (
        await db.execute(
            select(ChunkRelevanceLabel).where(
                ChunkRelevanceLabel.project_id == project.id,
                ChunkRelevanceLabel.test_id == body.test_id,
                ChunkRelevanceLabel.annotator == AI_ANNOTATOR,
            )
        )
    ).scalars().all()
    by_chunk = {lbl.chunk_id: lbl for lbl in existing}

    for chunk_id, grade in grades.items():
        snap = snapshots.get(chunk_id, {})
        current = by_chunk.get(chunk_id)
        if current is None:
            db.add(
                ChunkRelevanceLabel(
                    project_id=project.id,
                    test_id=body.test_id,
                    chunk_id=chunk_id,
                    relevance=grade,
                    content_preview=snap.get("content_preview"),
                    url=snap.get("url"),
                    title=snap.get("title"),
                    annotator=AI_ANNOTATOR,
                    labeled_by=None,
                )
            )
        else:
            current.relevance = grade

    await db.flush()
    return AiJudgeResponse(test_id=body.test_id, grades=grades, judged=len(grades))


@router.post(
    "/labeling/ai-judge/preview",
    response_model=AiJudgePreviewResponse,
    dependencies=[require_section("evaluate", "labeling")],
)
async def ai_judge_preview(
    body: AiJudgeRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Render the exact prompt the AI judge would send for a case, without calling the LLM.

    Assembles the *same* pooled chunks and applies the *same* rubric the ``ai-judge`` endpoint
    uses, then returns the full system + user message — including the chunk text folded into it —
    so a reviewer can inspect precisely what will be sent before spending a judge call.
    """
    dataset = await _resolve_dataset(db, project, _as_uuid(body.dataset_id))
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}},
        )
    query = await _dataset_case_query(db, dataset.id, body.test_id)
    if query is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Test case not found in dataset"}},
        )

    # Same pool the judge grades, including any agentic-pooled candidates. Preview reads the
    # already-planned queries (no user context here to plan); the judge itself plans if missing.
    agentic = await _dataset_case_agentic_queries(db, dataset.id, body.test_id)
    pool, _computed_at, _connected = await assemble_case_pool(
        db, project, body.test_id, query, agentic_queries=agentic, refresh=body.refresh
    )
    # Preview the FULL chunk text the judge grades, not the truncated display preview.
    full_texts = await fetch_full_chunk_texts(db, project, [pc.chunk_id for pc in pool.chunks])
    chunks = [
        AiJudgeChunk(
            chunk_id=pc.chunk_id,
            text=full_texts.get(pc.chunk_id) or str(pc.content_preview or ""),
        )
        for pc in pool.chunks
    ]
    # Mirror the judge: show the reference answer folded into the previewed prompt when present and
    # not opted out via the request.
    expected_answer = (
        await _dataset_case_expected_answer(db, dataset.id, body.test_id)
        if body.include_expected_answer
        else None
    )
    system_prompt, planned = plan_ai_judge_prompts(
        query, chunks, instructions=body.instructions, expected_answer=expected_answer
    )
    batches = [
        AiJudgePromptBatch(user_prompt=up, chunk_count=n) for up, n in planned
    ]
    return AiJudgePreviewResponse(
        test_id=body.test_id,
        system_prompt=system_prompt,
        batches=batches,
        chunk_count=len(chunks),
    )


@router.post(
    "/labeling/plan-queries",
    response_model=PlanQueriesResponse,
    dependencies=[require_write("evaluate", "labeling")],
)
async def plan_case_queries(
    body: PlanQueriesRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Decompose a case's question into focused agentic sub-queries with the LLM, and persist them.

    The planned queries are stored on the case (``metadata.labeling_queries``) so every later pool
    folds their index hits in — raising the recall ceiling to what an agentic retriever would
    surface. Re-running re-plans and overwrites. Returns the base question + the planned queries.
    """
    dataset = await _resolve_dataset(db, project, _as_uuid(body.dataset_id))
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}},
        )
    query = await _dataset_case_query(db, dataset.id, body.test_id)
    if query is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Test case not found in dataset"}},
        )

    try:
        queries = await plan_and_persist_case_queries(
            db,
            project,
            user,
            dataset_id=dataset.id,
            test_id=body.test_id,
            query=query,
            instructions=body.instructions,
            max_queries=body.max_queries,
        )
    except AnalysisLlmConfigError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "LLM_NOT_CONFIGURED", "message": str(exc)}},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Query planner failed for test_id=%s", body.test_id)
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "QUERY_PLANNER_FAILED",
                    "message": f"The query planner call failed: {exc}",
                }
            },
        ) from exc

    return PlanQueriesResponse(test_id=body.test_id, base=[query], agentic=queries)
