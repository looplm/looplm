"""Background worker for feedback test case suggestion generation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.schemas.datasets import TestCaseSuggestion

logger = logging.getLogger(__name__)

_suggestion_tasks: dict[UUID, asyncio.Task] = {}


async def run_suggestion_generation(
    run_id: UUID,
    project_id: UUID,
    suggestions: list[TestCaseSuggestion],
    feedback_comments: dict[str, str | None],
    user_settings: dict | None,
    db_factory,
) -> None:
    """Background task that enriches suggestions with LLM-drafted criteria,
    scores their best-fit dataset, and persists the final list."""
    from app.models.feedback_eval import FeedbackSuggestionRun
    from app.models.models import TestCase, TestDataset
    from app.routers.dataset_helpers import generate_expected_answer, score_dataset_relevance
    from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService

    async def _mark_failed(message: str) -> None:
        async with db_factory() as db:
            run = await db.get(FeedbackSuggestionRun, run_id)
            if run is None:
                return
            run.status = "failed"
            run.error = message[:2000]
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()

    # Mark running
    async with db_factory() as db:
        run = await db.get(FeedbackSuggestionRun, run_id)
        if run is None:
            return
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        await db.commit()

    # Enrich negatives that lack a drafted expected answer. Each LLM call gets
    # its own DB session so per-item progress writes don't block one another.
    needs_enrichment = [
        s for s in suggestions
        if s.feedback_value == 0 and not s.suggested_expected_answer
    ]

    if needs_enrichment:
        try:
            llm_service = AnalysisLlmService(user_settings=user_settings)
        except AnalysisLlmConfigError:
            # No LLM configured — skip enrichment, finish the rest of the pipeline.
            logger.info("LLM not configured, skipping expected answer generation")
            llm_service = None
    else:
        llm_service = None

    async def _enrich_one(sug: TestCaseSuggestion) -> None:
        if llm_service is None:
            return
        try:
            answer = await generate_expected_answer(
                llm_service,
                sug.prompt,
                sug.actual_answer,
                feedback_comments.get(str(sug.feedback_id)),
            )
            if answer:
                sug.suggested_expected_answer = answer
        except Exception:
            logger.exception("LLM enrichment failed for one suggestion; continuing")
        finally:
            async with db_factory() as db_inner:
                row = await db_inner.get(FeedbackSuggestionRun, run_id)
                if row is not None:
                    row.processed = (row.processed or 0) + 1
                    await db_inner.commit()

    try:
        if needs_enrichment and llm_service is not None:
            await asyncio.gather(*[_enrich_one(s) for s in needs_enrichment])

        # Smart dataset suggestion: score datasets by metadata overlap.
        async with db_factory() as db:
            ds_rows = (
                await db.execute(
                    select(TestDataset).where(TestDataset.project_id == project_id)
                )
            ).scalars().all()

            if ds_rows:
                dataset_cases: dict[str, list[dict]] = {}
                for ds in ds_rows:
                    cases = (
                        await db.execute(
                            select(
                                TestCase.team_filter,
                                TestCase.tag_filter,
                                TestCase.context_filters,
                            ).where(TestCase.dataset_id == ds.id)
                        )
                    ).all()
                    dataset_cases[str(ds.id)] = [
                        {
                            "team_filter": row.team_filter or [],
                            "tag_filter": row.tag_filter or [],
                            "context_filters": row.context_filters or {},
                        }
                        for row in cases
                    ]

                for sug in suggestions:
                    best_id = None
                    best_score = 0.0
                    for ds in ds_rows:
                        score = score_dataset_relevance(
                            dataset_cases.get(str(ds.id), []),
                            sug.team_filter,
                            sug.tag_filter,
                            sug.context_filters,
                        )
                        if score > best_score:
                            best_score = score
                            best_id = ds.id
                    sug.suggested_dataset_id = best_id

            run = await db.get(FeedbackSuggestionRun, run_id)
            if run is None:
                return
            run.suggestions = [s.model_dump(mode="json") for s in suggestions]
            run.count = len(suggestions)
            # Ensure the bar reads 100% even if no enrichment happened.
            run.processed = run.total
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()
    except Exception as e:
        logger.exception("Suggestion generation failed")
        await _mark_failed(str(e))
