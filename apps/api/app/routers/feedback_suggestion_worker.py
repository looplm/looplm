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
    feedback_messages: dict[str, list[dict[str, str]]],
    user_settings: dict | None,
    db_factory,
) -> None:
    """Background task that contextualizes each suggestion against its prior
    conversation, drafts acceptance criteria for negatives, scores the
    best-fit dataset, and persists the final list."""
    from app.models.feedback_eval import FeedbackSuggestionRun
    from app.models.models import TestCase, TestDataset
    from app.routers.dataset_helpers import (
        build_contextualized_prompt,
        generate_expected_answer,
        score_dataset_relevance,
        summarize_conversation,
    )
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

    try:
        llm_service = AnalysisLlmService(user_settings=user_settings)
    except AnalysisLlmConfigError:
        # No LLM configured — we can still emit bare-prompt suggestions and
        # skip both contextualization and criteria drafting.
        logger.info("LLM not configured, skipping context summary and criteria")
        llm_service = None

    async def _bump_processed() -> None:
        async with db_factory() as db_inner:
            row = await db_inner.get(FeedbackSuggestionRun, run_id)
            if row is not None:
                row.processed = (row.processed or 0) + 1
                await db_inner.commit()

    async def _process_one(sug: TestCaseSuggestion) -> None:
        try:
            messages = feedback_messages.get(str(sug.feedback_id), [])
            # Drop the trailing turn if it's exactly the final user question —
            # that's the part the suggestion is grading, not prior context.
            final_question = sug.prompt
            older_turns = [
                t for t in messages
                if t["content"].strip() != final_question.strip()
            ]
            if older_turns and older_turns[-1]["role"] == "assistant":
                # The last assistant turn is shown verbatim — only summarize
                # what comes before it.
                to_summarize = older_turns[:-1]
            else:
                to_summarize = older_turns

            summary: str | None = None
            if llm_service is not None and to_summarize:
                summary = await summarize_conversation(llm_service, to_summarize)

            if messages:
                sug.prompt = build_contextualized_prompt(
                    messages, final_question, summary=summary,
                )

            # Criteria drafting still only applies to negative feedback that
            # doesn't already have a suggested answer.
            if (
                llm_service is not None
                and sug.feedback_value == 0
                and not sug.suggested_expected_answer
            ):
                answer = await generate_expected_answer(
                    llm_service,
                    sug.prompt,
                    sug.actual_answer,
                    feedback_comments.get(str(sug.feedback_id)),
                )
                if answer:
                    sug.suggested_expected_answer = answer
        except Exception:
            logger.exception("Suggestion processing failed for one item; continuing")
        finally:
            await _bump_processed()

    try:
        if suggestions:
            await asyncio.gather(*[_process_one(s) for s in suggestions])

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
