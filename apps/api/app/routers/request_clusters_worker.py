"""Background worker for request-type clustering analysis.

Clusters user *requests* across all traffic (not just feedback-bearing traces)
into named intent themes using the same LLM machinery as the Top Questions
analysis, then computes a per-theme outcome cross-tab (trace status + feedback
sentiment) that drives the Analytics page's request-type × outcome heatmap.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

# Reuse the proven question-clustering prompts and JSON parser — requests cluster
# by intent exactly like questions do.
from app.routers.top_questions_worker import (
    TOP_QUESTIONS_MERGE_PROMPT,
    TOP_QUESTIONS_SYSTEM_PROMPT,
    _parse_json_array,
    attribute_merged_themes,
)

logger = logging.getLogger(__name__)

_request_cluster_tasks: dict[UUID, asyncio.Task] = {}

# Cap how many example trace ids we persist per theme — keeps the JSONB small
# while still letting the UI deep-link to representative traces.
_MAX_TRACE_IDS = 50


def _empty_outcome() -> dict[str, int]:
    return {"success": 0, "degraded": 0, "failure": 0, "fb_positive": 0, "fb_negative": 0}


def _tally_outcome(items: list[dict]) -> dict[str, int]:
    """Cross-tab a theme's member requests by trace status and feedback sentiment."""
    outcome = _empty_outcome()
    for it in items:
        status = it.get("status")
        if status in outcome:
            outcome[status] += 1
        fv = it.get("feedback_value")
        if fv == 1:
            outcome["fb_positive"] += 1
        elif fv == 0:
            outcome["fb_negative"] += 1
    return outcome


def _trace_ids(items: list[dict]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        tid = it.get("trace_id")
        if tid and tid not in seen:
            seen.add(tid)
            out.append(tid)
        if len(out) >= _MAX_TRACE_IDS:
            break
    return out


async def run_request_cluster_analysis(
    analysis_id: UUID,
    requests: list[dict],
    user_settings: dict | None,
    db_factory,
) -> None:
    """Background task that clusters user requests into themes with outcome cross-tabs.

    ``requests`` items are dicts of ``{"request", "trace_id", "status", "feedback_value"}``.
    Only the ``request`` text is sent to the LLM; the rest is used locally to build the
    per-theme outcome cross-tab.
    """
    from app.models.analytics import RequestClusterAnalysis
    from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService

    async with db_factory() as db:
        try:
            llm_service = AnalysisLlmService(user_settings=user_settings)
        except AnalysisLlmConfigError as e:
            analysis = await db.get(RequestClusterAnalysis, analysis_id)
            analysis.status = "failed"
            analysis.error = str(e)
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        analysis = await db.get(RequestClusterAnalysis, analysis_id)
        analysis.status = "running"
        analysis.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            from app.services.llm_usage_tracker import record_llm_usage

            numbered = [f"{i}. {r['request']}" for i, r in enumerate(requests, 1)]
            chunk_size = 80
            themes: list[dict] = []

            if len(requests) <= 100:
                text, usage = await llm_service.tracked_chat_completion(
                    messages=[
                        {"role": "system", "content": TOP_QUESTIONS_SYSTEM_PROMPT},
                        {"role": "user", "content": "\n".join(numbered)},
                    ],
                    temperature=0.1,
                )
                await record_llm_usage(
                    db,
                    project_id=analysis.project_id,
                    service_name="request_clusters",
                    function_name="run_request_cluster_analysis",
                    provider=llm_service.provider,
                    model=llm_service.model,
                    usage=usage,
                    request_metadata={"analysis_id": str(analysis_id), "request_count": len(requests)},
                )

                for t in _parse_json_array(text):
                    indices = t.get("question_indices", [])
                    items = [requests[i - 1] for i in indices if 1 <= i <= len(requests)]
                    themes.append({
                        "theme": t.get("theme", "Unknown"),
                        "count": t.get("count", len(items)),
                        "summary_question": t.get("summary_question", ""),
                        "trace_ids": _trace_ids(items),
                        "outcome": _tally_outcome(items),
                    })

                analysis = await db.get(RequestClusterAnalysis, analysis_id)
                analysis.processed_requests = len(requests)
                await db.commit()
            else:
                request_slices = [requests[i : i + chunk_size] for i in range(0, len(requests), chunk_size)]

                all_chunk_themes: list[dict] = []
                processed = 0

                for chunk_idx, chunk_requests in enumerate(request_slices):
                    # Number each chunk locally (1-based within the slice) so the
                    # indices the LLM returns line up with ``chunk_requests`` below.
                    # (Slicing a globally-numbered list would hand the LLM indices
                    # like 81..160 that all fall outside this 80-item slice.)
                    chunk_numbered = [f"{i}. {r['request']}" for i, r in enumerate(chunk_requests, 1)]
                    text, usage = await llm_service.tracked_chat_completion(
                        messages=[
                            {"role": "system", "content": TOP_QUESTIONS_SYSTEM_PROMPT},
                            {"role": "user", "content": "\n".join(chunk_numbered)},
                        ],
                        temperature=0.1,
                    )
                    await record_llm_usage(
                        db,
                        project_id=analysis.project_id,
                        service_name="request_clusters",
                        function_name="run_request_cluster_analysis",
                        provider=llm_service.provider,
                        model=llm_service.model,
                        usage=usage,
                        request_metadata={
                            "analysis_id": str(analysis_id),
                            "chunk": chunk_idx + 1,
                            "total_chunks": len(request_slices),
                        },
                    )

                    for t in _parse_json_array(text):
                        indices = t.get("question_indices", [])
                        items = [chunk_requests[i - 1] for i in indices if 1 <= i <= len(chunk_requests)]
                        all_chunk_themes.append({
                            "theme": t.get("theme", "Unknown"),
                            "count": t.get("count", len(items)),
                            "summary_question": t.get("summary_question", ""),
                            "items": items,
                        })

                    processed += len(chunk_requests)
                    analysis = await db.get(RequestClusterAnalysis, analysis_id)
                    analysis.processed_requests = min(processed, len(requests))
                    await db.commit()

                # Phase 2: merge chunk themes. Send an indexed, item-stripped view so
                # the LLM can reference each input cluster by index in source_indices.
                merge_input = json.dumps(
                    [
                        {
                            "index": idx,
                            "theme": ct["theme"],
                            "count": ct["count"],
                            "summary_question": ct["summary_question"],
                        }
                        for idx, ct in enumerate(all_chunk_themes)
                    ],
                    indent=2,
                    default=str,
                )
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
                    service_name="request_clusters",
                    function_name="run_request_cluster_analysis_merge",
                    provider=llm_service.provider,
                    model=llm_service.model,
                    usage=usage,
                    request_metadata={"analysis_id": str(analysis_id), "phase": "merge"},
                )

                # Attribute each merged theme to its source chunk themes by index
                # (lossless: renamed/garbled merges fall back to standalone chunk
                # themes) so every theme keeps its real outcome cross-tab.
                for t, indices in attribute_merged_themes(_parse_json_array(text), all_chunk_themes):
                    items: list[dict] = []
                    for i in indices:
                        items.extend(all_chunk_themes[i].get("items", []))
                    themes.append({
                        "theme": t.get("theme", "Unknown"),
                        "count": len(items) or t.get("count", 0),
                        "summary_question": t.get("summary_question", ""),
                        "trace_ids": _trace_ids(items),
                        "outcome": _tally_outcome(items),
                    })

            themes.sort(key=lambda x: x["count"], reverse=True)
            for i, t in enumerate(themes[:10], 1):
                t["rank"] = i

            analysis = await db.get(RequestClusterAnalysis, analysis_id)
            analysis.results = themes[:10]
            analysis.status = "completed"
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Request cluster analysis failed")
            analysis = await db.get(RequestClusterAnalysis, analysis_id)
            analysis.status = "failed"
            analysis.error = str(e)[:2000]
            analysis.completed_at = datetime.now(timezone.utc)
            await db.commit()
