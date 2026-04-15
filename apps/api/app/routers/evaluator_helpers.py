"""Pure helper functions and data for evaluator endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Evaluator, EvaluatorType, EvalRun
from app.schemas.evaluators import EvaluatorResponse

logger = logging.getLogger(__name__)


def _evaluator_type_value(t: str) -> EvaluatorType:
    """Parse type string into EvaluatorType enum."""
    try:
        return EvaluatorType(t)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "INVALID_TYPE", "message": f"Invalid evaluator type: {t}. Must be llm_judge, deterministic, or hybrid"}},
        )


async def _enrich_with_stats(
    evaluators: list[Evaluator],
    project_id: UUID,
    db: AsyncSession,
) -> list[EvaluatorResponse]:
    """Enrich evaluator list with stats from eval_runs.grader_summary."""
    # Fetch all runs for this project to compute stats
    result = await db.execute(
        select(EvalRun.grader_summary, EvalRun.created_at)
        .where(EvalRun.project_id == project_id)
        .order_by(EvalRun.created_at.desc())
    )
    runs = result.all()

    # Aggregate stats per evaluator name
    stats: dict[str, dict] = {}
    for grader_summary, run_created_at in runs:
        if not grader_summary:
            continue
        for name, summary in grader_summary.items():
            if name not in stats:
                stats[name] = {"total": 0, "passed": 0, "skipped": 0, "last_seen_at": None}
            stats[name]["total"] += summary.get("total", 0)
            stats[name]["passed"] += summary.get("passed", 0)
            stats[name]["skipped"] += summary.get("skipped", 0)
            if stats[name]["last_seen_at"] is None:
                stats[name]["last_seen_at"] = run_created_at.isoformat() if run_created_at else None

    responses = []
    for ev in evaluators:
        s = stats.get(ev.name, {})
        total_evals = s.get("total", 0)
        total_passed = s.get("passed", 0)
        total_skipped = s.get("skipped", 0)
        evaluated = total_evals - total_skipped
        pass_rate = total_passed / evaluated if evaluated > 0 else None

        responses.append(
            EvaluatorResponse(
                id=ev.id,
                name=ev.name,
                display_name=ev.display_name,
                type=ev.type.value if ev.type else "llm_judge",
                description=ev.description,
                relevance=ev.relevance or "important",
                affects_pass=ev.affects_pass,
                config=ev.config or {},
                source=ev.source,
                enabled=ev.enabled,
                total_evaluations=total_evals,
                pass_rate=pass_rate,
                last_seen_at=s.get("last_seen_at"),
                created_at=ev.created_at,
                updated_at=ev.updated_at,
            )
        )
    return responses


_JSON_ONLY_RESPONSE = (
    'Respond only as JSON: {"pass": true/false, "reason": "short explanation"}'
)

_FACTUAL_CORRECTNESS_PROMPT = (
    "You are evaluating factual consistency.\n\n"
    "Determine whether the answer contains claims that directly contradict the "
    "retrieved context.\n\n"
    "Guidelines:\n"
    "- Mark FAIL only for direct contradictions.\n"
    "- Omissions are not contradictions.\n"
    "- Paraphrases are acceptable if meaning is preserved.\n"
    "- General knowledge is acceptable unless it conflicts with the context.\n\n"
    "Retrieved context:\n{context}\n\n"
    "Answer:\n{output}\n\n"
    f"{_JSON_ONLY_RESPONSE}"
)

_FAITHFULNESS_PROMPT = (
    "You are evaluating whether an answer is grounded in the retrieved context.\n\n"
    "Determine whether the answer introduces unsupported factual claims.\n\n"
    "Guidelines:\n"
    "- Every factual claim should be supported by the context.\n"
    "- General knowledge may be acceptable if it does not conflict with the context.\n"
    "- Formatting help, clarifying questions, and short search suggestions are not failures.\n"
    "- Placeholder image references such as IMAGE_1 are acceptable when they appear in the context.\n"
    "- Invented facts, numbers, identifiers, URLs, or procedures should FAIL.\n\n"
    "Retrieved context:\n{context}\n\n"
    "Answer:\n{output}\n\n"
    f"{_JSON_ONLY_RESPONSE}"
)

_FAITHFULNESS_TO_SOURCE_PROMPT = (
    "You are evaluating source fidelity.\n\n"
    "The user requested exact or source-faithful information. Determine whether the "
    "answer stays faithful to the provided source content.\n\n"
    "Guidelines:\n"
    "- The essential source information must be present.\n"
    "- Light paraphrasing is acceptable if meaning is preserved.\n"
    "- Missing key source details should FAIL.\n"
    "- Invented source details should FAIL.\n"
    "- Clarifying questions and brief notes about missing information are acceptable.\n\n"
    "User request:\n{input}\n\n"
    "Source content:\n{context}\n\n"
    "Answer:\n{output}\n\n"
    f"{_JSON_ONLY_RESPONSE}"
)

_ANSWER_RELEVANCE_PROMPT = (
    "You are evaluating answer relevance.\n\n"
    "Determine whether the answer addresses the user's request while taking the "
    "available context into account.\n\n"
    "Guidelines:\n"
    "- The answer should stay on topic and address the core request.\n"
    "- Partial but relevant answers can PASS.\n"
    "- If the context does not contain the needed information, a transparent "
    "\"not enough information found\" answer with a focused follow-up question can PASS.\n"
    "- Irrelevant or off-topic answers should FAIL.\n\n"
    "User request:\n{input}\n\n"
    "Available context:\n{context}\n\n"
    "Answer:\n{output}\n\n"
    f"{_JSON_ONLY_RESPONSE}"
)

_HELPFULNESS_PROMPT = (
    "You are evaluating helpfulness.\n\n"
    "Determine whether the answer is clear, well-structured, and useful given the "
    "available context.\n\n"
    "Guidelines:\n"
    "- Prefer clear structure and actionable next steps when appropriate.\n"
    "- Judge the answer relative to the provided context, not against an ideal answer.\n"
    "- If the context lacks the needed information, a concise transparent answer with "
    "a useful follow-up can PASS.\n"
    "- Confusing, poorly structured, or context-ignoring answers should FAIL.\n\n"
    "User request:\n{input}\n\n"
    "Available context:\n{context}\n\n"
    "Answer:\n{output}\n\n"
    f"{_JSON_ONLY_RESPONSE}"
)

_CONCISENESS_PROMPT = (
    "You are evaluating conciseness.\n\n"
    "Determine whether the answer contains unnecessary repetition, filler, or "
    "excessive verbosity.\n\n"
    "Guidelines:\n"
    "- Repeated points and unnecessary meta commentary should FAIL.\n"
    "- One focused clarifying question is acceptable.\n"
    "- Detailed answers are acceptable when the task is complex.\n"
    "- Quotes or step-by-step instructions can be long if they are necessary.\n\n"
    "User request:\n{input}\n\n"
    "Answer:\n{output}\n\n"
    f"{_JSON_ONLY_RESPONSE}"
)


# Default metadata for well-known evaluators used for bootstrap and sync.
known_evaluators = {
    "sourceRetrieval": {
        "type": "deterministic", "relevance": "core", "affects_pass": True,
        "description": "Checks if expected source documents were retrieved by the search tool.",
        "config": {"check_type": "contains_urls"},
    },
    "factualCorrectness": {
        "type": "llm_judge", "relevance": "core", "affects_pass": True,
        "description": "Checks if the answer contradicts retrieved source documents.",
        "config": {
            "prompt_template": _FACTUAL_CORRECTNESS_PROMPT,
        },
    },
    "faithfulness": {
        "type": "llm_judge", "relevance": "core", "affects_pass": True,
        "description": "Checks if all claims are grounded in retrieved context.",
        "config": {
            "prompt_template": _FAITHFULNESS_PROMPT,
        },
    },
    "faithfulnessToSource": {
        "type": "hybrid", "relevance": "core", "affects_pass": True,
        "description": "Checks verbatim reproduction when user requests exact info.",
        "config": {
            "check_type": "regex_match",
            "pattern": r"(?i)(exact|verbatim|quote|from the source|original text|word-for-word|1:1|citation)",
            "prompt_template": _FAITHFULNESS_TO_SOURCE_PROMPT,
        },
    },
    "answerRelevance": {
        "type": "llm_judge", "relevance": "core", "affects_pass": False,
        "description": "Checks whether the answer addresses the user's question, considering available context.",
        "config": {
            "prompt_template": _ANSWER_RELEVANCE_PROMPT,
        },
    },
    "helpfulness": {
        "type": "llm_judge", "relevance": "important", "affects_pass": False,
        "description": "Checks if the answer is clear, well-structured, and actionable given available context.",
        "config": {
            "prompt_template": _HELPFULNESS_PROMPT,
        },
    },
    "conciseness": {
        "type": "hybrid", "relevance": "important", "affects_pass": False,
        "description": "Checks for unnecessary repetition and verbosity.",
        "config": {
            "check_type": "string_contains",
            "expected_strings": [],
            "prompt_template": _CONCISENESS_PROMPT,
        },
    },
    "imageMissing": {
        "type": "deterministic", "relevance": "important", "affects_pass": False,
        "description": "Checks that IMAGE references have corresponding markers in tool outputs.",
        "config": {"check_type": "image_missing"},
    },
    "imageOrdering": {
        "type": "deterministic", "relevance": "minor", "affects_pass": False,
        "description": "Checks that images from the same source appear in correct order.",
        "config": {"check_type": "image_ordering"},
    },
    "responseTime": {
        "type": "deterministic", "relevance": "important", "affects_pass": False,
        "description": "Checks if the target API response time is within the configured threshold.",
        "config": {"check_type": "response_time", "max_response_time_ms": 10000},
    },
    "quality": {"type": "llm_judge", "relevance": "important", "affects_pass": False, "description": "Auto-grade: response is well-structured and helpful."},
    "completeness": {"type": "llm_judge", "relevance": "important", "affects_pass": False, "description": "Auto-grade: response fully addresses the user's question."},
    "safety": {"type": "llm_judge", "relevance": "core", "affects_pass": False, "description": "Auto-grade: no harmful or misleading content."},
}


async def discover_and_sync_evaluators(
    project_id: UUID,
    db: AsyncSession,
) -> tuple[int, int]:
    """Discover evaluators from existing eval results and auto-create/backfill entries.

    Returns (created, updated) counts.
    """
    # Collect all grader names from eval_runs.grader_summary
    result = await db.execute(
        select(EvalRun.grader_summary)
        .where(EvalRun.project_id == project_id)
    )
    rows = result.all()

    discovered: set[str] = set()
    for (grader_summary,) in rows:
        if not grader_summary:
            continue
        for name in grader_summary:
            discovered.add(name)

    # Get existing evaluators (need full objects for backfill)
    existing_result = await db.execute(
        select(Evaluator).where(Evaluator.project_id == project_id)
    )
    existing_evaluators = {ev.name: ev for ev in existing_result.scalars().all()}
    existing_names = set(existing_evaluators.keys())

    created = 0
    updated = 0
    for name in discovered:
        known = known_evaluators.get(name, {})

        if name not in existing_names:
            ev_type_str = known.get("type", "llm_judge")
            ev_type = EvaluatorType(ev_type_str)

            ev = Evaluator(
                project_id=project_id,
                name=name,
                display_name=name[0].upper() + name[1:] if name else name,
                type=ev_type,
                description=known.get("description"),
                relevance=known.get("relevance", "important"),
                affects_pass=known.get("affects_pass", False),
                config=known.get("config", {}),
                source="discovered",
            )
            db.add(ev)
            created += 1
        else:
            # Backfill config for existing evaluators with empty config
            ev = existing_evaluators[name]
            known_config = known.get("config")
            if known_config and (not ev.config or ev.config == {}):
                ev.config = known_config
                ev.updated_at = datetime.now(timezone.utc)
                updated += 1

    if created > 0 or updated > 0:
        await db.flush()

    return created, updated
