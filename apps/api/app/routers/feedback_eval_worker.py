"""Background worker for feedback evaluation."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from uuid import UUID

logger = logging.getLogger(__name__)

_feedback_eval_tasks: dict[UUID, asyncio.Task] = {}

FEEDBACK_EVAL_SYSTEM_PROMPT = (
    "You are a feedback quality auditor for an AI assistant. "
    "You will receive a batch of user feedback items, each with: the user's question, the AI's response, "
    "the feedback value (1 = thumbs up, 0 = thumbs down), an optional comment, "
    "and optional metadata about the trace (e.g. model, userName, teamFilter, environment, "
    "hasRAG, messageCount, searchResultCount).\n\n"
    "Follow this evaluation process IN ORDER for each item:\n\n"
    "STEP 1 — CHECK FOR METADATA CONTRADICTIONS (this takes priority over everything else):\n"
    "Compare every factual claim in the comment against the metadata. Examples of contradictions:\n"
    "- Comment claims answer was filtered for ONE team (e.g. 'auf ein Team wie EDM gefiltert'), "
    "but teamFilter contains MULTIPLE teams → CONTRADICTION.\n"
    "- Comment claims no team filter was applied, but teamFilter is non-empty → CONTRADICTION.\n"
    "- Comment claims RAG was not used, but hasRAG is true → CONTRADICTION.\n"
    "- Comment claims a wrong model or environment → CONTRADICTION.\n"
    "If ANY contradiction is found → verdict MUST be 'suspicious', regardless of how actionable "
    "or well-written the feedback is. A factually wrong claim provides misleading signal.\n\n"
    "STEP 2 — ONLY if no metadata contradictions were found, evaluate normally:\n"
    "- **suspicious**: The feedback value contradicts the quality of the AI response "
    "(e.g. thumbs up on a clearly wrong answer, or thumbs down on a correct answer).\n"
    "- **helpful**: The feedback provides actionable, accurate signal for improving the AI. "
    "A thumbs down with a specific, factually correct comment is helpful. "
    "A thumbs up on a genuinely good answer is also helpful.\n"
    "- **unhelpful**: The feedback adds little signal (no comment, vague comment, ambiguous value).\n\n"
    "Return a JSON array (no markdown, no explanation) with one object per item:\n"
    '[{"feedback_id": "...", "verdict": "suspicious|helpful|unhelpful", '
    '"reasoning": "brief explanation", "confidence": 0.0-1.0}]'
)


async def run_feedback_evaluation(
    evaluation_id: UUID,
    eval_items: list[dict],
    user_settings: dict | None,
    db_factory,
    system_prompt: str | None = None,
    verdicts: list[str] | None = None,
    default_verdict: str | None = None,
) -> None:
    """Background task that evaluates feedback in batches and persists results."""
    from app.models.feedback_eval import FeedbackEvalResult, FeedbackEvaluation
    from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService

    prompt = system_prompt or FEEDBACK_EVAL_SYSTEM_PROMPT
    valid_verdicts = set(verdicts) if verdicts else {"suspicious", "helpful", "unhelpful"}
    fallback_verdict = default_verdict or "unhelpful"

    async with db_factory() as db:
        try:
            llm_service = AnalysisLlmService(user_settings=user_settings)
        except AnalysisLlmConfigError as e:
            evaluation = await db.get(FeedbackEvaluation, evaluation_id)
            evaluation.status = "failed"
            evaluation.error = str(e)
            evaluation.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        evaluation = await db.get(FeedbackEvaluation, evaluation_id)
        if evaluation is None:
            logger.error("Feedback evaluation %s not found; aborting worker", evaluation_id)
            return
        evaluation.status = "running"
        evaluation.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            batch_size = 5
            batches = [eval_items[i : i + batch_size] for i in range(0, len(eval_items), batch_size)]
            item_lookup = {item["feedback_id"]: item for item in eval_items}

            verdict_counts: dict[str, int] = {v: 0 for v in valid_verdicts}
            evaluated = 0

            from app.services.llm_usage_tracker import record_llm_usage

            for batch in batches:
                user_content = json.dumps(batch, indent=2, default=str)
                try:
                    text, usage = await llm_service.tracked_chat_completion(
                        messages=[
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": user_content},
                        ],
                        temperature=0.1,
                    )

                    await record_llm_usage(
                        db,
                        project_id=evaluation.project_id,
                        service_name="feedback_eval_worker",
                        function_name="run_feedback_evaluation",
                        provider=llm_service.provider,
                        model=llm_service.model,
                        usage=usage,
                        request_metadata={"evaluation_id": str(evaluation_id), "batch_size": len(batch)},
                    )

                    try:
                        results = json.loads(text)
                    except json.JSONDecodeError:
                        match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
                        results = json.loads(match.group(1)) if match else []
                except Exception:
                    logger.exception("Feedback evaluation batch failed")
                    results = []

                for r in results:
                    fid = r.get("feedback_id", "")
                    source = item_lookup.get(fid, {})
                    verdict = r.get("verdict", fallback_verdict)
                    if verdict not in valid_verdicts:
                        verdict = fallback_verdict

                    verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1

                    db.add(FeedbackEvalResult(
                        evaluation_id=evaluation_id,
                        feedback_id=fid,
                        trace_id=source.get("trace_id"),
                        score_name=source.get("score_name", "user-feedback"),
                        value=source.get("value", 0),
                        comment=source.get("comment"),
                        trace_input_preview=(source.get("user_question") or "")[:200] or None,
                        verdict=verdict,
                        reasoning=r.get("reasoning", ""),
                        confidence=min(max(float(r.get("confidence", 0.5)), 0.0), 1.0),
                    ))

                evaluated += len(batch)

                # Update progress after each batch
                evaluation = await db.get(FeedbackEvaluation, evaluation_id)
                evaluation.evaluated_count = evaluated
                evaluation.suspicious_count = verdict_counts.get("suspicious", 0)
                evaluation.helpful_count = verdict_counts.get("helpful", 0)
                evaluation.unhelpful_count = verdict_counts.get("unhelpful", 0)
                evaluation.verdict_counts = dict(verdict_counts)
                await db.commit()

            # Mark completed
            evaluation = await db.get(FeedbackEvaluation, evaluation_id)
            evaluation.status = "completed"
            evaluation.completed_at = datetime.now(timezone.utc)
            await db.commit()

        except Exception as e:
            logger.exception("Feedback evaluation failed")
            evaluation = await db.get(FeedbackEvaluation, evaluation_id)
            evaluation.status = "failed"
            evaluation.error = str(e)[:2000]
            evaluation.completed_at = datetime.now(timezone.utc)
            await db.commit()
