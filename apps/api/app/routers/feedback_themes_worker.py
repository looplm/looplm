"""Background worker for feedback theme clustering using LLM.

Clusters the qualitative *comment* text of user feedback into recurring themes.
Mirrors the structure of ``top_questions_worker`` (which clusters questions) but
operates on free-text comments and is sentiment-aware.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

# Reuse the battle-tested merge/parse helpers from the top-questions worker —
# the chunk→merge attribution logic is identical regardless of what is clustered.
from app.routers.top_questions_worker import (
    _parse_json_array,
    attribute_merged_themes,
)

logger = logging.getLogger(__name__)

_feedback_theme_tasks: dict[UUID, asyncio.Task] = {}

FEEDBACK_THEMES_SYSTEM_PROMPT = (
    "You are a customer-feedback analyst. You receive a numbered list of qualitative "
    "comments users left as feedback on an AI assistant's answers. Your job is to identify "
    "the most common recurring themes in what users are expressing.\n\n"
    "Instructions:\n"
    "1. Group comments by what the user is expressing — praise, a specific complaint, a "
    "feature request, confusion — not by surface-level word overlap.\n"
    "2. Comments phrased differently but expressing the same thing belong to the same theme.\n"
    "3. Give each theme a clear, concise label.\n"
    "4. Count how many comments belong to each theme.\n"
    "5. List ALL comment indices that belong to each theme.\n"
    "6. Write a single one-line summary that captures the substance and sentiment of the "
    "theme (e.g. \"Users praise clear, actionable step-by-step instructions\").\n\n"
    "Return a JSON array sorted by count descending (most common first), with at most 10 themes:\n"
    '[{"theme": "...", "count": N, "comment_indices": [1, 3, 7, ...], '
    '"summary": "A single sentence summarizing this theme"}]\n\n'
    "Return ONLY the JSON array, no markdown or explanation."
)

FEEDBACK_THEMES_MERGE_PROMPT = (
    "You are a customer-feedback analyst. You receive theme clusters from multiple batches "
    "of feedback comments, each with a numeric \"index\". Your job is to merge "
    "overlapping/duplicate themes, sum their counts, and return the final top 10 themes.\n\n"
    "Instructions:\n"
    "1. Merge themes that cover the same sentiment/topic (even if labeled differently).\n"
    "2. Sum the counts of merged themes.\n"
    "3. For each final theme, write a single one-line summary capturing its substance and sentiment.\n"
    "4. In \"source_indices\", list the index of EVERY input cluster you merged into that theme. "
    "Each input index must appear in exactly one final theme — do not drop any.\n"
    "5. Return at most 10 themes sorted by count descending.\n\n"
    "Return a JSON array:\n"
    '[{"theme": "...", "count": N, "summary": "...", "source_indices": [0, 3, 7]}]\n\n'
    "Return ONLY the JSON array, no markdown or explanation."
)


async def _abort_if_cancelled(db, analysis_id: UUID) -> None:
    """Cooperatively honor a stop request, even from another worker/replica.

    The ``/stop`` endpoint commits ``status='cancelled'`` from a *different* DB
    session — and in prod often a different process, where the in-memory
    ``task.cancel()`` can never reach this task. So re-read the row on a fresh
    snapshot at each checkpoint and bail out if a stop was requested.
    """
    from app.models.feedback_eval import FeedbackThemeAnalysis

    db.expire_all()
    current = await db.get(FeedbackThemeAnalysis, analysis_id)
    if current is None or current.status == "cancelled":
        raise asyncio.CancelledError()


def _build_theme_from_indices(raw_theme: dict, indices: list[int], comments: list[dict]) -> dict:
    """Resolve comment indices (1-based, LLM-supplied) to full items + sentiment."""
    all_items: list[dict] = []
    positive = 0
    negative = 0
    for i in indices:
        if 1 <= i <= len(comments):
            c = comments[i - 1]
            fv = c.get("feedback_value")
            all_items.append({
                "comment": c["comment"],
                "feedback_value": fv,
                "trace_id": c.get("trace_id"),
                "question": c.get("question"),
            })
            if fv == 1:
                positive += 1
            elif fv == 0:
                negative += 1
    return {
        "theme": raw_theme.get("theme", "Unknown"),
        "count": raw_theme.get("count", len(indices)),
        "summary": raw_theme.get("summary", ""),
        "all_comments": all_items,
        "feedback_sentiment": {"positive": positive, "negative": negative},
    }


async def run_feedback_themes_analysis(
    analysis_id: UUID,
    comments: list[dict],
    user_settings: dict | None,
    db_factory,
) -> None:
    """Background task that clusters feedback comments into themes using LLM."""
    from app.models.feedback_eval import FeedbackThemeAnalysis
    from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService

    async with db_factory() as db:
        try:
            llm_service = AnalysisLlmService(user_settings=user_settings)
        except AnalysisLlmConfigError as e:
            analysis = await db.get(FeedbackThemeAnalysis, analysis_id)
            analysis.status = "failed"
            analysis.error = str(e)
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        analysis = await db.get(FeedbackThemeAnalysis, analysis_id)
        analysis.status = "running"
        analysis.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            from app.services.llm_usage_tracker import record_llm_usage

            numbered = [f"{i}. {c['comment']}" for i, c in enumerate(comments, 1)]

            chunk_size = 80
            themes: list[dict] = []

            if len(comments) <= 100:
                await _abort_if_cancelled(db, analysis_id)
                text, usage = await llm_service.tracked_chat_completion(
                    messages=[
                        {"role": "system", "content": FEEDBACK_THEMES_SYSTEM_PROMPT},
                        {"role": "user", "content": "\n".join(numbered)},
                    ],
                    temperature=0.1,
                )
                await record_llm_usage(
                    db,
                    project_id=analysis.project_id,
                    service_name="feedback_themes",
                    function_name="run_feedback_themes_analysis",
                    provider=llm_service.provider,
                    model=llm_service.model,
                    usage=usage,
                    request_metadata={"analysis_id": str(analysis_id), "comment_count": len(comments)},
                )

                for t in _parse_json_array(text):
                    themes.append(
                        _build_theme_from_indices(t, t.get("comment_indices", []), comments)
                    )

                analysis = await db.get(FeedbackThemeAnalysis, analysis_id)
                analysis.processed_comments = len(comments)
                await db.commit()
            else:
                chunks = [numbered[i : i + chunk_size] for i in range(0, len(numbered), chunk_size)]
                comment_slices = [
                    comments[i : i + chunk_size] for i in range(0, len(comments), chunk_size)
                ]

                all_chunk_themes: list[dict] = []
                processed = 0

                for chunk_idx, chunk in enumerate(chunks):
                    await _abort_if_cancelled(db, analysis_id)
                    text, usage = await llm_service.tracked_chat_completion(
                        messages=[
                            {"role": "system", "content": FEEDBACK_THEMES_SYSTEM_PROMPT},
                            {"role": "user", "content": "\n".join(chunk)},
                        ],
                        temperature=0.1,
                    )
                    await record_llm_usage(
                        db,
                        project_id=analysis.project_id,
                        service_name="feedback_themes",
                        function_name="run_feedback_themes_analysis",
                        provider=llm_service.provider,
                        model=llm_service.model,
                        usage=usage,
                        request_metadata={
                            "analysis_id": str(analysis_id),
                            "chunk": chunk_idx + 1,
                            "total_chunks": len(chunks),
                        },
                    )

                    chunk_comments = comment_slices[chunk_idx]
                    for t in _parse_json_array(text):
                        all_chunk_themes.append(
                            _build_theme_from_indices(
                                t, t.get("comment_indices", []), chunk_comments
                            )
                        )

                    processed += len(chunk)
                    analysis = await db.get(FeedbackThemeAnalysis, analysis_id)
                    analysis.processed_comments = min(processed, len(comments))
                    await db.commit()

                # Phase 2: merge chunk themes. Send an indexed, trimmed view (drop the
                # bulky comment lists) so the LLM can reference clusters by index.
                import json

                merge_input = json.dumps(
                    [
                        {
                            "index": idx,
                            "theme": ct["theme"],
                            "count": ct["count"],
                            "summary": ct.get("summary", ""),
                        }
                        for idx, ct in enumerate(all_chunk_themes)
                    ],
                    indent=2,
                    default=str,
                )
                await _abort_if_cancelled(db, analysis_id)
                text, usage = await llm_service.tracked_chat_completion(
                    messages=[
                        {"role": "system", "content": FEEDBACK_THEMES_MERGE_PROMPT},
                        {"role": "user", "content": merge_input},
                    ],
                    temperature=0.1,
                )
                await record_llm_usage(
                    db,
                    project_id=analysis.project_id,
                    service_name="feedback_themes",
                    function_name="run_feedback_themes_analysis_merge",
                    provider=llm_service.provider,
                    model=llm_service.model,
                    usage=usage,
                    request_metadata={"analysis_id": str(analysis_id), "phase": "merge"},
                )

                # Re-aggregate each merged theme's comments + sentiment from its source
                # chunk themes by index (lossless — renamed/garbled merges fall back to
                # standalone chunk themes) so no data is dropped.
                for t, indices in attribute_merged_themes(_parse_json_array(text), all_chunk_themes):
                    members = [all_chunk_themes[i] for i in indices]
                    positive = sum(m.get("feedback_sentiment", {}).get("positive", 0) for m in members)
                    negative = sum(m.get("feedback_sentiment", {}).get("negative", 0) for m in members)
                    all_comments: list = []
                    for m in members:
                        all_comments.extend(m.get("all_comments", []))
                    count = sum(m.get("count", 0) for m in members) or t.get("count", 0)
                    themes.append({
                        "theme": t.get("theme", "Unknown"),
                        "count": count,
                        "summary": t.get("summary", ""),
                        "all_comments": all_comments,
                        "feedback_sentiment": {"positive": positive, "negative": negative},
                    })

            # Assign ranks and store results
            themes.sort(key=lambda x: x["count"], reverse=True)
            for i, t in enumerate(themes[:10], 1):
                t["rank"] = i

            # Don't clobber a stop that landed while we were finishing up.
            db.expire_all()
            analysis = await db.get(FeedbackThemeAnalysis, analysis_id)
            if analysis is None or analysis.status == "cancelled":
                return
            analysis.results = themes[:10]
            analysis.status = "completed"
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()

        except asyncio.CancelledError:
            logger.info("Feedback themes analysis %s stopped", analysis_id)
            raise
        except Exception as e:
            logger.exception("Feedback themes analysis failed")
            analysis = await db.get(FeedbackThemeAnalysis, analysis_id)
            analysis.status = "failed"
            analysis.error = str(e)[:2000]
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()
        finally:
            _feedback_theme_tasks.pop(analysis_id, None)
