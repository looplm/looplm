"""Eval report generation — builds structured reports from eval run results.

Produces a machine-readable JSON report with summary stats, failure analysis,
per-test-case trace info, and LLM-generated recommendations.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import EvalResult, EvalRun, Evaluator
from app.services.analysis_llm import AnalysisLlmService

logger = logging.getLogger(__name__)

RAW_RESPONSE_EXCERPT_LIMIT = 2000


def _parse_trace(result_metadata: dict) -> dict:
    """Extract trace info (tool calls, tools used, tokens) from raw API response."""
    trace: dict[str, Any] = {
        "tool_calls_count": 0,
        "tools_used": [],
        "token_usage": None,
        "raw_response_excerpt": None,
    }

    raw = result_metadata.get("raw_response")
    if not raw:
        return trace

    # Store excerpt
    if isinstance(raw, str):
        trace["raw_response_excerpt"] = raw[:RAW_RESPONSE_EXCERPT_LIMIT]
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return trace
    elif isinstance(raw, dict):
        excerpt = json.dumps(raw, default=str)
        trace["raw_response_excerpt"] = excerpt[:RAW_RESPONSE_EXCERPT_LIMIT]
        parsed = raw
    else:
        return trace

    # Extract tool calls from common response formats
    tools_used: list[str] = []
    tool_calls_count = 0

    # OpenAI format: choices[].message.tool_calls
    for choice in parsed.get("choices", []):
        msg = choice.get("message", {})
        for tc in msg.get("tool_calls", []):
            tool_calls_count += 1
            fn = tc.get("function", {})
            name = fn.get("name")
            if name and name not in tools_used:
                tools_used.append(name)

    # Anthropic format: content[].type == "tool_use"
    for block in parsed.get("content", []):
        if block.get("type") == "tool_use":
            tool_calls_count += 1
            name = block.get("name")
            if name and name not in tools_used:
                tools_used.append(name)

    # Generic: top-level tool_calls / toolCalls / tools arrays
    for key in ("tool_calls", "toolCalls", "tools"):
        items = parsed.get(key)
        if isinstance(items, list):
            for item in items:
                tool_calls_count += 1
                name = item.get("name") or item.get("function", {}).get("name")
                if name and name not in tools_used:
                    tools_used.append(name)

    trace["tool_calls_count"] = tool_calls_count
    trace["tools_used"] = tools_used

    # Token usage
    usage = parsed.get("usage")
    if isinstance(usage, dict):
        trace["token_usage"] = usage

    return trace


def _build_grader_affects_pass_map(evaluators: list[Evaluator]) -> dict[str, bool]:
    """Map evaluator name → affects_pass."""
    return {e.name: e.affects_pass for e in evaluators}


def generate_eval_report(
    run: EvalRun,
    results: list[EvalResult],
    evaluators: list[Evaluator],
    included_graders: set[str] | None = None,
) -> dict:
    """Build a structured evaluation report from run data.

    Args:
        included_graders: If set, only include these grader names in the report.

    Returns a dict ready for JSON serialization.
    """
    affects_pass = _build_grader_affects_pass_map(evaluators)

    # --- Summary ---
    total = len(results)
    if included_graders is not None:
        # Recompute pass/fail based on filtered graders only
        _passed = 0
        for r in results:
            graders = r.graders or {}
            has_critical_fail = False
            for gname, gdata in graders.items():
                if gname not in included_graders:
                    continue
                if affects_pass.get(gname, False) and not gdata.get("skipped") and not gdata.get("pass"):
                    has_critical_fail = True
                    break
            if not has_critical_fail:
                _passed += 1
        passed = _passed
    else:
        passed = sum(1 for r in results if r.pass_)
    failed = total - passed

    grader_summary = {}
    for name, gs in (run.grader_summary or {}).items():
        if included_graders is not None and name not in included_graders:
            continue
        grader_summary[name] = {
            "total": gs.get("total", 0),
            "passed": gs.get("passed", 0),
            "failed": gs.get("failed", 0),
            "skipped": gs.get("skipped", 0),
            "pass_rate": gs.get("pass_rate", 0),
        }

    score_summary = {}
    for name, ss in (run.score_summary or {}).items():
        if included_graders is not None and name not in included_graders:
            continue
        score_summary[name] = {
            "count": ss.get("count", 0),
            "avg": ss.get("avg", 0),
            "min": ss.get("min", 0),
            "max": ss.get("max", 0),
        }

    summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": passed / total if total > 0 else 0.0,
        "grader_summary": grader_summary,
        "score_summary": score_summary,
    }

    # --- Failure analysis: by grader ---
    by_grader: dict[str, dict] = {}
    for r in results:
        graders = r.graders or {}
        for gname, gdata in graders.items():
            if included_graders is not None and gname not in included_graders:
                continue
            if gname not in by_grader:
                by_grader[gname] = {
                    "fail_count": 0,
                    "affects_pass": affects_pass.get(gname, False),
                    "common_issues": [],
                    "failed_test_ids": [],
                }
            if not gdata.get("skipped") and not gdata.get("pass"):
                by_grader[gname]["fail_count"] += 1
                by_grader[gname]["failed_test_ids"].append(r.test_id)
                reason = gdata.get("reason")
                if reason:
                    by_grader[gname]["common_issues"].append(reason)

    # Deduplicate and limit common_issues to most frequent
    for gname, ginfo in by_grader.items():
        issues = ginfo["common_issues"]
        # Keep unique issues, up to 10
        seen: set[str] = set()
        unique: list[str] = []
        for issue in issues:
            normalized = issue.strip()
            key = normalized[:200]  # dedup key only
            if key not in seen:
                seen.add(key)
                unique.append(normalized)
            if len(unique) >= 10:
                break
        ginfo["common_issues"] = unique

    # Remove graders with zero failures
    by_grader = {k: v for k, v in by_grader.items() if v["fail_count"] > 0}

    # --- Failure analysis: by test case ---
    by_test_case = []
    for r in results:
        graders = r.graders or {}
        failed_graders = {}
        passed_graders = {}
        skipped_graders = {}

        for gname, gdata in graders.items():
            if included_graders is not None and gname not in included_graders:
                continue
            entry = {"reason": gdata.get("reason")}
            if gdata.get("skipped"):
                skipped_graders[gname] = entry
            elif not gdata.get("pass"):
                failed_graders[gname] = entry
            else:
                passed_graders[gname] = entry

        # Recompute pass/fail when graders are filtered
        if included_graders is not None:
            # A test passes if no affects_pass grader failed
            test_pass = all(
                not affects_pass.get(gname, False)
                for gname in failed_graders
            )
        else:
            test_pass = r.pass_

        metadata = r.result_metadata or {}
        trace = _parse_trace(metadata)

        # Extract filter pre-conditions from result metadata
        preconditions: dict[str, Any] = {}
        if metadata.get("filter_mode"):
            preconditions["filter_mode"] = metadata["filter_mode"]
        if metadata.get("team_filter"):
            preconditions["team_filter"] = metadata["team_filter"]
        if metadata.get("tag_filter"):
            preconditions["tag_filter"] = metadata["tag_filter"]
        if metadata.get("context_filters"):
            preconditions["context_filters"] = metadata["context_filters"]

        by_test_case.append({
            "test_id": r.test_id,
            "pass": test_pass,
            "input": r.input,
            "output": r.output,
            "expected_output": r.expected_output,
            "failed_graders": failed_graders,
            "passed_graders": passed_graders,
            "skipped_graders": skipped_graders,
            "scores": r.scores or {},
            "trace": trace,
            "preconditions": preconditions if preconditions else None,
        })

    # Sort: failures first
    by_test_case.sort(key=lambda x: (x["pass"], x["test_id"]))

    return {
        "eval_run": {
            "id": str(run.id),
            "name": run.name,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "source": run.source,
        },
        "summary": summary,
        "failure_analysis": {
            "by_grader": by_grader,
            "by_test_case": by_test_case,
        },
        "recommendations": [],  # Populated by LLM in generate step
    }


async def generate_recommendations(
    llm: AnalysisLlmService,
    report: dict,
    db: AsyncSession | None = None,
    project_id: UUID | None = None,
) -> list[str]:
    """Use LLM to generate actionable recommendations from the report.

    Analyzes failure patterns, grader reasons, and trace data to produce
    improvement suggestions for the RAG app.
    """
    # Build a focused prompt with failure data
    summary = report["summary"]
    by_grader = report["failure_analysis"]["by_grader"]

    # Collect failed test case details (limit to avoid token overflow)
    failed_cases = [
        tc for tc in report["failure_analysis"]["by_test_case"] if not tc["pass"]
    ][:20]

    # Build failure context
    failure_context = {
        "summary": {
            "total": summary["total"],
            "passed": summary["passed"],
            "failed": summary["failed"],
            "pass_rate": summary["pass_rate"],
        },
        "grader_failures": {
            name: {
                "fail_count": info["fail_count"],
                "affects_pass": info["affects_pass"],
                "common_issues": info["common_issues"][:5],
            }
            for name, info in by_grader.items()
        },
        "failed_test_cases": [
            {
                "test_id": tc["test_id"],
                "input": (tc["input"] or "")[:500],
                "output": (tc["output"] or "")[:500],
                "expected_output": (tc["expected_output"] or "")[:500],
                "failed_graders": tc["failed_graders"],
                "trace": {
                    "tool_calls_count": tc["trace"]["tool_calls_count"],
                    "tools_used": tc["trace"]["tools_used"],
                },
            }
            for tc in failed_cases
        ],
    }

    context_json = json.dumps(failure_context, default=str, indent=2)

    try:
        content, usage = await llm.tracked_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior RAG application reliability engineer. "
                        "Analyze evaluation failures and produce actionable recommendations "
                        "to improve the RAG application. Focus on concrete, specific fixes. "
                        "Return a JSON array of recommendation strings."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Analyze the following evaluation failure data and produce 3-7 "
                        "actionable recommendations to improve the RAG application.\n\n"
                        "Each recommendation should:\n"
                        "- Be specific and actionable (not generic advice)\n"
                        "- Reference the grader or failure pattern it addresses\n"
                        "- Suggest a concrete change (system prompt, retrieval config, etc.)\n\n"
                        "Respond ONLY with a JSON array of strings, e.g.:\n"
                        '["Recommendation 1", "Recommendation 2"]\n\n'
                        f"Failure data:\n{context_json}"
                    ),
                },
            ],
            temperature=0.3,
        )

        if db and project_id:
            from app.services.llm_usage_tracker import record_llm_usage
            await record_llm_usage(
                db,
                project_id=project_id,
                service_name="eval_report",
                function_name="generate_recommendations",
                provider=llm.provider,
                model=llm.model,
                usage=usage,
            )

        # Parse JSON array from response (handle markdown code blocks)
        json_match = re.search(r"\[.*\]", content, re.DOTALL)
        if json_match:
            recommendations = json.loads(json_match.group())
            if isinstance(recommendations, list):
                return [str(r) for r in recommendations]

        logger.warning("Could not parse recommendations from LLM response: %s", content[:200])
        return []

    except Exception as e:
        logger.error("Failed to generate recommendations: %s", e)
        return []
