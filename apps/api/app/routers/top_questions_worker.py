"""Background worker for top questions analysis using LLM clustering."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from uuid import UUID

logger = logging.getLogger(__name__)

_top_questions_tasks: dict[UUID, asyncio.Task] = {}

TOP_QUESTIONS_SYSTEM_PROMPT = (
    "You are a question clustering analyst. You receive a numbered list of user questions "
    "asked to an AI assistant. Your job is to identify the most common question themes/topics.\n\n"
    "Instructions:\n"
    "1. Group questions by semantic intent/topic, not by surface-level word overlap.\n"
    "2. Questions phrased differently but asking about the same thing belong to the same theme.\n"
    "3. Give each theme a clear, concise label.\n"
    "4. Count how many questions belong to each theme.\n"
    "5. List ALL question indices that belong to each theme.\n"
    "6. Write a single summary_question that best represents/captures the intent of all "
    "questions in the theme. This should read like a natural user question.\n\n"
    "Return a JSON array sorted by count descending (most common first), with at most 10 themes:\n"
    '[{"theme": "...", "count": N, "question_indices": [1, 3, 7, ...], '
    '"summary_question": "A single question summarizing this theme"}]\n\n'
    "Return ONLY the JSON array, no markdown or explanation."
)

TOP_QUESTIONS_MERGE_PROMPT = (
    "You are a question clustering analyst. You receive theme clusters from multiple batches "
    "of user questions. Your job is to merge overlapping/duplicate themes, sum their counts, "
    "and return the final top 10 themes.\n\n"
    "Instructions:\n"
    "1. Merge themes that cover the same topic (even if labeled differently).\n"
    "2. Sum the counts of merged themes.\n"
    "3. For each final theme, write a single summary_question that best captures the intent.\n"
    "4. Return at most 10 themes sorted by count descending.\n\n"
    "Return a JSON array:\n"
    '[{"theme": "...", "count": N, "summary_question": "...", '
    '"representative_questions": ["...", "...", "..."]}]\n\n'
    "Return ONLY the JSON array, no markdown or explanation."
)


def _parse_json_array(text: str) -> list[dict]:
    """Parse a JSON array from LLM response, handling markdown fences."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return []


async def run_top_questions_analysis(
    analysis_id: UUID,
    questions: list[dict],
    user_settings: dict | None,
    db_factory,
) -> None:
    """Background task that clusters user questions into themes using LLM."""
    from app.models.feedback_eval import TopQuestionsAnalysis
    from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService

    async with db_factory() as db:
        try:
            llm_service = AnalysisLlmService(user_settings=user_settings)
        except AnalysisLlmConfigError as e:
            analysis = await db.get(TopQuestionsAnalysis, analysis_id)
            analysis.status = "failed"
            analysis.error = str(e)
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        analysis = await db.get(TopQuestionsAnalysis, analysis_id)
        analysis.status = "running"
        analysis.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            from app.services.llm_usage_tracker import record_llm_usage

            # Build numbered question list
            numbered_questions = []
            for i, q in enumerate(questions, 1):
                numbered_questions.append(f"{i}. {q['question']}")

            chunk_size = 80
            themes: list[dict] = []

            if len(questions) <= 100:
                # Single-pass: send all questions at once
                user_content = "\n".join(numbered_questions)
                text, usage = await llm_service.tracked_chat_completion(
                    messages=[
                        {"role": "system", "content": TOP_QUESTIONS_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.1,
                )
                await record_llm_usage(
                    db,
                    project_id=analysis.project_id,
                    service_name="top_questions",
                    function_name="run_top_questions_analysis",
                    provider=llm_service.provider,
                    model=llm_service.model,
                    usage=usage,
                    request_metadata={"analysis_id": str(analysis_id), "question_count": len(questions)},
                )

                raw_themes = _parse_json_array(text)

                # Resolve question_indices to actual question text and compute sentiment
                for t in raw_themes:
                    indices = t.get("question_indices", [])
                    # Build all_questions with feedback value
                    all_qs = []
                    positive = 0
                    negative = 0
                    for i in indices:
                        if 1 <= i <= len(questions):
                            q = questions[i - 1]
                            fv = q.get("feedback_value")
                            all_qs.append({
                                "question": q["question"],
                                "feedback_value": fv,
                                "trace_id": q.get("trace_id"),
                            })
                            if fv == 1:
                                positive += 1
                            elif fv == 0:
                                negative += 1
                    themes.append({
                        "theme": t.get("theme", "Unknown"),
                        "count": t.get("count", len(indices)),
                        "summary_question": t.get("summary_question", ""),
                        "all_questions": all_qs,
                        "feedback_sentiment": {"positive": positive, "negative": negative},
                    })

                analysis = await db.get(TopQuestionsAnalysis, analysis_id)
                analysis.processed_questions = len(questions)
                await db.commit()
            else:
                # Two-phase approach for large sets
                chunks = [
                    numbered_questions[i : i + chunk_size]
                    for i in range(0, len(numbered_questions), chunk_size)
                ]
                chunk_question_slices = [
                    questions[i : i + chunk_size]
                    for i in range(0, len(questions), chunk_size)
                ]

                all_chunk_themes: list[dict] = []
                processed = 0

                for chunk_idx, chunk in enumerate(chunks):
                    user_content = "\n".join(chunk)
                    text, usage = await llm_service.tracked_chat_completion(
                        messages=[
                            {"role": "system", "content": TOP_QUESTIONS_SYSTEM_PROMPT},
                            {"role": "user", "content": user_content},
                        ],
                        temperature=0.1,
                    )
                    await record_llm_usage(
                        db,
                        project_id=analysis.project_id,
                        service_name="top_questions",
                        function_name="run_top_questions_analysis",
                        provider=llm_service.provider,
                        model=llm_service.model,
                        usage=usage,
                        request_metadata={
                            "analysis_id": str(analysis_id),
                            "chunk": chunk_idx + 1,
                            "total_chunks": len(chunks),
                        },
                    )

                    raw_themes = _parse_json_array(text)
                    chunk_qs = chunk_question_slices[chunk_idx]

                    for t in raw_themes:
                        indices = t.get("question_indices", [])
                        all_qs = []
                        positive = 0
                        negative = 0
                        for i in indices:
                            if 1 <= i <= len(chunk_qs):
                                q = chunk_qs[i - 1]
                                fv = q.get("feedback_value")
                                all_qs.append({
                                    "question": q["question"],
                                    "feedback_value": fv,
                                })
                                if fv == 1:
                                    positive += 1
                                elif fv == 0:
                                    negative += 1
                        all_chunk_themes.append({
                            "theme": t.get("theme", "Unknown"),
                            "count": t.get("count", len(indices)),
                            "summary_question": t.get("summary_question", ""),
                            "all_questions": all_qs,
                            "feedback_sentiment": {"positive": positive, "negative": negative},
                        })

                    processed += len(chunk)
                    analysis = await db.get(TopQuestionsAnalysis, analysis_id)
                    analysis.processed_questions = min(processed, len(questions))
                    await db.commit()

                # Phase 2: Merge chunk themes
                merge_input = json.dumps(all_chunk_themes, indent=2, default=str)
                text, usage = await llm_service.tracked_chat_completion(
                    messages=[
                        {"role": "system", "content": TOP_QUESTIONS_MERGE_PROMPT},
                        {"role": "user", "content": merge_input},
                    ],
                    temperature=0.1,
                )
                await record_llm_usage(
                    db,
                    project_id=analysis.project_id,
                    service_name="top_questions",
                    function_name="run_top_questions_analysis_merge",
                    provider=llm_service.provider,
                    model=llm_service.model,
                    usage=usage,
                    request_metadata={"analysis_id": str(analysis_id), "phase": "merge"},
                )

                merged = _parse_json_array(text)

                # Build lookup from chunk themes for sentiment and questions
                chunk_data: dict[str, dict] = {}
                for ct in all_chunk_themes:
                    theme_key = ct["theme"].lower().strip()
                    if theme_key not in chunk_data:
                        chunk_data[theme_key] = {"positive": 0, "negative": 0, "all_questions": []}
                    chunk_data[theme_key]["positive"] += ct.get("feedback_sentiment", {}).get("positive", 0)
                    chunk_data[theme_key]["negative"] += ct.get("feedback_sentiment", {}).get("negative", 0)
                    chunk_data[theme_key]["all_questions"].extend(ct.get("all_questions", []))

                for t in merged:
                    theme_key = t.get("theme", "").lower().strip()
                    cd = chunk_data.get(theme_key, {"positive": 0, "negative": 0, "all_questions": []})
                    themes.append({
                        "theme": t.get("theme", "Unknown"),
                        "count": t.get("count", 0),
                        "summary_question": t.get("summary_question", ""),
                        "all_questions": cd["all_questions"],
                        "feedback_sentiment": {"positive": cd["positive"], "negative": cd["negative"]},
                    })

            # Assign ranks and store results
            themes.sort(key=lambda x: x["count"], reverse=True)
            for i, t in enumerate(themes[:10], 1):
                t["rank"] = i

            analysis = await db.get(TopQuestionsAnalysis, analysis_id)
            analysis.results = themes[:10]
            analysis.status = "completed"
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()

        except Exception as e:
            logger.exception("Top questions analysis failed")
            analysis = await db.get(TopQuestionsAnalysis, analysis_id)
            analysis.status = "failed"
            analysis.error = str(e)[:2000]
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()
