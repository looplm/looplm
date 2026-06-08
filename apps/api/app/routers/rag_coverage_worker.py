"""Background worker for a coverage run.

Mirrors ``feedback_suggestion_worker.run_suggestion_generation``: kicked off via
``asyncio.create_task`` from the router, owns its own DB sessions through the
session factory, and drives a ``CoverageRun`` row through its status machine.

Steps:
  1. mark run ``running``
  2. build the provider, pull the partition distribution
  3. load the project's test cases, compute coverage (pure helper)
  4. (optional) sample docs for the biggest gaps and ask the LLM to draft eval
     questions + acceptance criteria for each
  5. persist results + suggestions, mark ``completed`` / ``failed``
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.index_providers.coverage import compute_coverage, coverage_fields_for
from app.index_providers.registry import build_index_provider
from app.models.datasets import TestCase, TestDataset
from app.models.index_providers import CoverageRun, IndexProvider
from app.schemas.index_providers import CoverageEvalSuggestion
from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService
from app.services.llm_usage_tracker import record_llm_usage

logger = logging.getLogger(__name__)

_SUGGESTION_SYSTEM_PROMPT = (
    "You are a QA specialist authoring RAG evaluation test cases for a knowledge "
    "assistant. You are given a slice of the knowledge base that currently has NO "
    "eval coverage, described by a category value and a few excerpts of indexed "
    "content from that slice. Draft evaluation questions a user might realistically "
    "ask that this slice should be able to answer.\n\n"
    "Hard rules:\n"
    "1. Base questions ONLY on the topics evidenced by the excerpts — do not invent "
    "subject matter that is not present.\n"
    "2. For each question write acceptance CRITERIA describing what a correct answer "
    "must contain — NOT a fabricated answer. You likely do not know the exact ground "
    "truth.\n"
    "3. Always include this fallback as a criterion: if the assistant cannot find the "
    "information in its sources it must say so plainly and not guess.\n"
    "4. Write questions and criteria in the same language as the excerpts.\n"
    "5. Return STRICT JSON: {\"questions\": [{\"prompt\": \"...\", "
    "\"acceptance_criteria\": \"...\"}]}. No prose outside the JSON."
)


def _scope_for(partition_key: str, value: str) -> dict:
    """How a suggestion for this partition value should be scoped on a TestCase."""
    fields = coverage_fields_for(partition_key)
    if "tag_filter" in fields:
        return {"tag_filter": [value]}
    if "team_filter" in fields:
        return {"team_filter": [value]}
    if "expected_source_types" in fields:
        return {"expected_source_types": [value]}
    return {"context_filters": {partition_key: value}}


def _build_user_prompt(partition_key: str, value: str, snippets: list[str]) -> str:
    joined = "\n\n".join(f"- {s}" for s in snippets if s) or "(no text excerpts available)"
    return (
        f"Category: {partition_key} = {value}\n\n"
        f"Indexed content excerpts from this slice:\n{joined}\n\n"
        "Draft the evaluation questions now."
    )


async def _draft_questions(
    llm: AnalysisLlmService, partition_key: str, value: str, snippets: list[str], max_questions: int
) -> tuple[list[dict], object | None]:
    content, usage = await llm.tracked_chat_completion(
        messages=[
            {"role": "system", "content": _SUGGESTION_SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(partition_key, value, snippets)},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    questions: list[dict] = []
    try:
        parsed = json.loads(content)
        raw = parsed.get("questions", []) if isinstance(parsed, dict) else []
        for q in raw[:max_questions]:
            if isinstance(q, dict) and q.get("prompt"):
                questions.append(
                    {
                        "prompt": str(q["prompt"]).strip(),
                        "acceptance_criteria": str(q.get("acceptance_criteria", "")).strip(),
                    }
                )
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning("Could not parse LLM suggestion JSON for %s=%s", partition_key, value)
    return questions, usage


async def run_coverage_analysis(
    *,
    run_id: UUID,
    project_id: UUID,
    provider_id: UUID,
    partition_key: str,
    dataset_ids: list[UUID] | None,
    suggest: bool,
    min_covering_cases: int,
    sample_n: int,
    max_questions_per_gap: int,
    max_gaps_to_suggest: int,
    user_settings: dict | None,
    db_factory,
) -> None:
    provider_obj = None
    try:
        async with db_factory() as db:
            run = (
                await db.execute(select(CoverageRun).where(CoverageRun.id == run_id))
            ).scalar_one()
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            await db.commit()

            provider_row = (
                await db.execute(
                    select(IndexProvider).where(
                        IndexProvider.id == provider_id, IndexProvider.project_id == project_id
                    )
                )
            ).scalar_one_or_none()
            if provider_row is None:
                raise ValueError("Index provider not found")
            provider_obj = build_index_provider(provider_row)

            distribution = await provider_obj.get_partition_distribution(partition_key)

            tc_query = select(TestCase).join(
                TestDataset, TestCase.dataset_id == TestDataset.id
            ).where(TestDataset.project_id == project_id)
            if dataset_ids:
                tc_query = tc_query.where(TestCase.dataset_id.in_(dataset_ids))
            test_cases = list((await db.execute(tc_query)).scalars().all())
            tc_dicts = [
                {
                    "tag_filter": tc.tag_filter or [],
                    "team_filter": tc.team_filter or [],
                    "expected_source_types": tc.expected_source_types or [],
                    "expected_page_urls": tc.expected_page_urls or [],
                    "expected_sources": tc.expected_sources or [],
                    "context_filters": tc.context_filters or {},
                    "tags": tc.tags or [],
                }
                for tc in test_cases
            ]

            report = compute_coverage(
                partition_key, distribution, tc_dicts, min_covering_cases=min_covering_cases
            )
            run.total = report.total_values
            run.results = report.to_dict()
            await db.commit()

            suggestions: list[dict] = []
            if suggest:
                try:
                    llm = AnalysisLlmService(user_settings=user_settings)
                except AnalysisLlmConfigError as e:
                    # Coverage is still valuable; just note why suggestions were skipped.
                    run.error = f"Coverage computed; suggestions skipped: {e}"
                    run.status = "completed"
                    run.processed = 0
                    run.completed_at = datetime.now(timezone.utc)
                    await db.commit()
                    return

                gaps = sorted(report.gaps, key=lambda r: r.indexed_count, reverse=True)[
                    :max_gaps_to_suggest
                ]
                for i, gap in enumerate(gaps):
                    try:
                        docs = await provider_obj.sample_documents(
                            partition_key, gap.value, sample_n
                        )
                        snippets = [d.snippet for d in docs if d.snippet]
                        questions, usage = await _draft_questions(
                            llm, partition_key, gap.value, snippets, max_questions_per_gap
                        )
                        if usage is not None:
                            await record_llm_usage(
                                db,
                                project_id=project_id,
                                service_name="rag_coverage_worker",
                                function_name="run_coverage_analysis",
                                provider=llm.provider,
                                model=llm.model,
                                usage=usage,
                                request_metadata={
                                    "run_id": str(run_id),
                                    "partition_value": gap.value,
                                },
                            )
                        scope = _scope_for(partition_key, gap.value)
                        for q in questions:
                            suggestions.append(
                                CoverageEvalSuggestion(
                                    partition_value=gap.value,
                                    prompt=q["prompt"],
                                    acceptance_criteria=q["acceptance_criteria"],
                                    **scope,
                                ).model_dump(mode="json")
                            )
                    except Exception:
                        logger.exception(
                            "Suggestion generation failed for %s=%s", partition_key, gap.value
                        )
                    run.processed = i + 1
                    run.suggestions = list(suggestions)
                    await db.commit()

            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()
    except Exception as e:
        logger.exception("Coverage run %s failed", run_id)
        try:
            async with db_factory() as db:
                run = (
                    await db.execute(select(CoverageRun).where(CoverageRun.id == run_id))
                ).scalar_one_or_none()
                if run is not None:
                    run.status = "failed"
                    run.error = str(e)
                    run.completed_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            logger.exception("Failed to record coverage run error for %s", run_id)
    finally:
        if provider_obj is not None:
            try:
                await provider_obj.aclose()
            except Exception:
                logger.debug("Provider aclose failed", exc_info=True)
