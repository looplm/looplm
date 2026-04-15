"""Multi-run eval report generation — aggregates results across multiple eval runs.

Produces a markdown report with summary tables, grader performance, failure
analysis, and LLM-generated recommendations spanning multiple runs.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import EvalResult, EvalRun, Evaluator
from app.services.analysis_llm import AnalysisLlmService
from app.services.eval_report import generate_eval_report

logger = logging.getLogger(__name__)


def generate_multi_run_markdown_report(
    runs_with_results: list[tuple[EvalRun, list[EvalResult]]],
    evaluators: list[Evaluator],
    *,
    included_graders: set[str] | None = None,
) -> tuple[str, list[dict]]:
    """Build a markdown report aggregating multiple eval runs.

    Args:
        included_graders: If set, only include these grader names in the report.

    Returns (markdown_string, list_of_per_run_reports).
    """
    per_run_reports: list[dict] = []
    for run, results in runs_with_results:
        report = generate_eval_report(run, results, evaluators, included_graders=included_graders)
        per_run_reports.append(report)

    # Aggregate stats
    total_tests = sum(r["summary"]["total"] for r in per_run_reports)
    total_passed = sum(r["summary"]["passed"] for r in per_run_reports)
    total_failed = sum(r["summary"]["failed"] for r in per_run_reports)
    overall_pass_rate = total_passed / total_tests if total_tests > 0 else 0.0

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    run_count = len(per_run_reports)

    lines: list[str] = []

    # Header
    lines.append(f"# Evaluation Report — {run_count} Run{'s' if run_count != 1 else ''}")
    lines.append("")
    lines.append(f"- **Generated:** {now}")
    lines.append(f"- **Runs:** {run_count}")
    lines.append(f"- **Total tests:** {total_tests}")
    lines.append(f"- **Overall pass rate:** {overall_pass_rate:.1%}")

    # Show filter modes used across runs
    filter_modes: set[str] = set()
    for run, _ in runs_with_results:
        fm = (run.run_metadata or {}).get("filter_mode")
        if fm:
            filter_modes.add(fm)
    if filter_modes:
        lines.append(f"- **Filter mode(s):** {', '.join(sorted(filter_modes))}")

    lines.append("")

    # Overall summary
    lines.append("## Overall Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total tests | {total_tests} |")
    lines.append(f"| Passed | {total_passed} |")
    lines.append(f"| Failed | {total_failed} |")
    lines.append(f"| Pass rate | {overall_pass_rate:.1%} |")
    lines.append("")

    # Per-run breakdown
    lines.append("## Per-Run Breakdown")
    lines.append("")
    lines.append("| Run | Date | Total | Passed | Failed | Pass Rate |")
    lines.append("|-----|------|-------|--------|--------|-----------|")
    for report in per_run_reports:
        run_info = report["eval_run"]
        s = report["summary"]
        date_str = run_info.get("created_at", "")
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str)
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                pass
        rate = f"{s['pass_rate']:.1%}"
        lines.append(f"| {run_info['name']} | {date_str} | {s['total']} | {s['passed']} | {s['failed']} | {rate} |")
    lines.append("")

    # Grader performance (aggregated)
    agg_graders: dict[str, dict[str, int]] = {}
    for report in per_run_reports:
        for gname, gdata in report["summary"].get("grader_summary", {}).items():
            if gname not in agg_graders:
                agg_graders[gname] = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
            agg_graders[gname]["total"] += gdata.get("total", 0)
            agg_graders[gname]["passed"] += gdata.get("passed", 0)
            agg_graders[gname]["failed"] += gdata.get("failed", 0)
            agg_graders[gname]["skipped"] += gdata.get("skipped", 0)

    if agg_graders:
        # Build evaluator metadata lookup
        eval_meta = {e.name: e for e in evaluators}

        lines.append("## Grader Performance")
        lines.append("")
        lines.append("> **Core** graders affect the pass/fail verdict. **Additional** graders provide extra signal but are not required for a passing grade.")
        lines.append("")
        lines.append("| Grader | Role | Total | Passed | Failed | Skipped | Pass Rate |")
        lines.append("|--------|------|-------|--------|--------|---------|-----------|")
        for gname, gdata in sorted(agg_graders.items()):
            evaluated = gdata["total"] - gdata["skipped"]
            rate = f"{gdata['passed'] / evaluated:.1%}" if evaluated > 0 else "N/A"
            ev = eval_meta.get(gname)
            if ev and ev.affects_pass:
                role = "Core"
            else:
                role = "Additional"
            lines.append(f"| {gname} | {role} | {gdata['total']} | {gdata['passed']} | {gdata['failed']} | {gdata['skipped']} | {rate} |")
        lines.append("")

    # Score summary (aggregated averages)
    agg_scores: dict[str, list[float]] = {}
    for report in per_run_reports:
        for sname, sdata in report["summary"].get("score_summary", {}).items():
            if sname not in agg_scores:
                agg_scores[sname] = []
            if sdata.get("count", 0) > 0:
                agg_scores[sname].append(sdata["avg"])

    if agg_scores:
        lines.append("## Score Summary")
        lines.append("")
        lines.append("| Score | Avg across runs | Min run avg | Max run avg |")
        lines.append("|-------|-----------------|-------------|-------------|")
        for sname, avgs in sorted(agg_scores.items()):
            if avgs:
                lines.append(f"| {sname} | {sum(avgs)/len(avgs):.3f} | {min(avgs):.3f} | {max(avgs):.3f} |")
        lines.append("")

    # Failure analysis by grader
    agg_failures: dict[str, dict] = {}
    for report in per_run_reports:
        for gname, gdata in report["failure_analysis"].get("by_grader", {}).items():
            if gname not in agg_failures:
                agg_failures[gname] = {"fail_count": 0, "common_issues": []}
            agg_failures[gname]["fail_count"] += gdata.get("fail_count", 0)
            agg_failures[gname]["common_issues"].extend(gdata.get("common_issues", []))

    if agg_failures:
        lines.append("## Failure Analysis by Grader")
        lines.append("")
        for gname, gdata in sorted(agg_failures.items(), key=lambda x: -x[1]["fail_count"]):
            lines.append(f"### {gname} ({gdata['fail_count']} failures)")
            lines.append("")
            # Deduplicate issues
            seen: set[str] = set()
            unique_issues: list[str] = []
            for issue in gdata["common_issues"]:
                normalized = issue.strip()
                key = normalized[:200]  # dedup key only
                if key not in seen:
                    seen.add(key)
                    unique_issues.append(normalized)
                if len(unique_issues) >= 10:
                    break
            if unique_issues:
                lines.append("**Top failure reasons:**")
                for issue in unique_issues:
                    lines.append(f"- {issue}")
            else:
                lines.append("_No failure reasons recorded._")
            lines.append("")

    # Failed test cases (top 30 across all runs)
    all_failed: list[dict] = []
    for report in per_run_reports:
        run_name = report["eval_run"]["name"]
        for tc in report["failure_analysis"].get("by_test_case", []):
            if not tc["pass"]:
                all_failed.append({**tc, "_run_name": run_name})

    if all_failed:
        lines.append("## Failed Test Cases")
        lines.append("")
        lines.append(f"Showing top {min(30, len(all_failed))} of {len(all_failed)} failures.")
        lines.append("")
        for tc in all_failed[:30]:
            lines.append(f"### `{tc['test_id']}` (run: {tc['_run_name']})")
            lines.append("")
            inp = (tc.get("input") or "")[:500]
            out = (tc.get("output") or "")[:500]
            exp = (tc.get("expected_output") or "")[:500]
            if inp:
                lines.append(f"**Input:** {inp}")
            if out:
                lines.append(f"**Output:** {out}")
            if exp:
                lines.append(f"**Expected:** {exp}")
            preconditions = tc.get("preconditions")
            if preconditions:
                filters = []
                if preconditions.get("team_filter"):
                    filters.append(f"teams: {', '.join(preconditions['team_filter'])}")
                if preconditions.get("tag_filter"):
                    filters.append(f"tags: {', '.join(preconditions['tag_filter'])}")
                if filters:
                    lines.append(f"**Filters:** {'; '.join(filters)}")
            for gname, gentry in tc.get("failed_graders", {}).items():
                reason = gentry.get("reason") or "No reason"
                lines.append(f"- **{gname}:** {reason}")
            lines.append("")

    # Recommendations placeholder
    if total_failed > 0:
        lines.append("## Recommendations")
        lines.append("")
        lines.append("{{RECOMMENDATIONS}}")
        lines.append("")

    return "\n".join(lines), per_run_reports


async def generate_multi_run_recommendations(
    llm: AnalysisLlmService,
    per_run_reports: list[dict],
    db: AsyncSession | None = None,
    project_id: UUID | None = None,
) -> str:
    """Use LLM to generate markdown recommendations from aggregated failure data."""
    # Collect failed cases (limit to 20 total across runs)
    failed_cases: list[dict] = []
    for report in per_run_reports:
        for tc in report["failure_analysis"].get("by_test_case", []):
            if not tc["pass"] and len(failed_cases) < 20:
                failed_cases.append({
                    "test_id": tc["test_id"],
                    "run": report["eval_run"]["name"],
                    "input": (tc.get("input") or "")[:500],
                    "output": (tc.get("output") or "")[:500],
                    "expected_output": (tc.get("expected_output") or "")[:500],
                    "failed_graders": tc.get("failed_graders", {}),
                })

    # Aggregate grader failures
    grader_failures: dict[str, dict] = {}
    for report in per_run_reports:
        for gname, gdata in report["failure_analysis"].get("by_grader", {}).items():
            if gname not in grader_failures:
                grader_failures[gname] = {"fail_count": 0, "common_issues": []}
            grader_failures[gname]["fail_count"] += gdata.get("fail_count", 0)
            grader_failures[gname]["common_issues"].extend(
                gdata.get("common_issues", [])[:5]
            )

    # Summary stats
    total = sum(r["summary"]["total"] for r in per_run_reports)
    passed = sum(r["summary"]["passed"] for r in per_run_reports)
    failed = sum(r["summary"]["failed"] for r in per_run_reports)

    context = {
        "summary": {"total": total, "passed": passed, "failed": failed, "pass_rate": passed / total if total > 0 else 0},
        "grader_failures": grader_failures,
        "failed_test_cases": failed_cases,
    }
    context_json = json.dumps(context, default=str, indent=2)

    try:
        content, usage = await llm.tracked_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior RAG application reliability engineer. "
                        "Analyze evaluation failures across multiple runs and produce actionable recommendations. "
                        "Return your recommendations as markdown text (bullet points or numbered list). "
                        "Do NOT wrap in a code block or JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Analyze the following aggregated evaluation failure data from multiple runs "
                        "and produce 3-7 actionable recommendations to improve the RAG application.\n\n"
                        "Each recommendation should:\n"
                        "- Be specific and actionable (not generic advice)\n"
                        "- Reference the grader or failure pattern it addresses\n"
                        "- Suggest a concrete change (system prompt, retrieval config, etc.)\n\n"
                        "Return as markdown text with bullet points or a numbered list.\n\n"
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
                service_name="eval_report_multi",
                function_name="generate_multi_run_recommendations",
                provider=llm.provider,
                model=llm.model,
                usage=usage,
            )

        return content or "_No recommendations generated._"

    except Exception as e:
        logger.error("Failed to generate multi-run recommendations: %s", e)
        return "_Could not generate recommendations._"
