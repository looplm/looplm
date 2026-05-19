"""Helpers for the Code Agent service.

Extracted from `code_agent_service.py` to keep file sizes manageable.
Contains prompt-building and progress tracking utilities.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_agent import OpenCodeAnalysis
from app.models.evaluations import EvalResult, EvalRun

logger = logging.getLogger(__name__)


# ── Prompt building ───────────────────────────────────────────

def _build_agent_prompt(
    failed_results: list[EvalResult],
    run: EvalRun,
    extra_context: str = "",
    file_patterns: list[str] | None = None,
) -> str:
    """Build the user prompt with eval failure context."""
    lines = [
        f"## Evaluation Run: {run.name}",
        f"Total: {run.total} | Passed: {run.passed} | Failed: {run.failed}",
        "",
    ]

    if run.grader_summary:
        lines.append("### Grader Summary")
        lines.append(json.dumps(run.grader_summary, indent=2, default=str))
        lines.append("")

    lines.append(f"### Failed Test Cases ({len(failed_results)} failures)")
    lines.append("")

    for result in failed_results[:50]:  # Cap to avoid excessive token usage
        lines.append(f"#### Test: {result.test_id}")
        if result.input:
            lines.append(f"**Input:** {result.input[:1000]}")
        if result.output:
            lines.append(f"**Output:** {result.output[:1000]}")
        if result.expected_output:
            lines.append(f"**Expected:** {result.expected_output[:1000]}")
        if result.reason:
            lines.append(f"**Reason:** {result.reason[:500]}")
        if result.graders:
            lines.append(f"**Graders:** {json.dumps(result.graders, default=str)}")
        lines.append("")

    if len(failed_results) > 50:
        lines.append(f"... and {len(failed_results) - 50} more failures (showing first 50)")
        lines.append("")

    if file_patterns:
        lines.append("### Suggested file patterns to explore")
        for pattern in file_patterns:
            lines.append(f"- `{pattern}`")
        lines.append("")

    if extra_context:
        lines.append("### Additional Context")
        lines.append(extra_context)
        lines.append("")

    lines.append(
        "Analyze these failures and provide your suggestions. "
        "Be specific and actionable."
    )

    return "\n".join(lines)


# ── Core analysis ─────────────────────────────────────────────

async def _update_progress(
    db: AsyncSession,
    analysis: OpenCodeAnalysis,
    *,
    num_turns: int | None = None,
    total_cost_usd: float | None = None,
    progress_message: str | None = None,
    log_entry: str | None = None,
) -> None:
    """Persist live progress fields so the polling frontend can display them."""
    if num_turns is not None:
        analysis.num_turns = num_turns
    if total_cost_usd is not None:
        analysis.total_cost_usd = total_cost_usd
    if progress_message is not None:
        analysis.progress_message = progress_message
    if log_entry is not None:
        from sqlalchemy.orm.attributes import flag_modified
        log = list(analysis.progress_log or [])
        log.append({
            "t": datetime.now(timezone.utc).isoformat(),
            "msg": log_entry,
        })
        # Keep last 50 entries to avoid bloat
        analysis.progress_log = log[-50:]
        flag_modified(analysis, "progress_log")
    await db.commit()


