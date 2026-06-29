"""Issue diagnosis.

Fills root_cause + suggested_fix on undiagnosed active issues via the LLM.
Split out of ``engine_service`` (detection + merging stays there); the two
share only the ``_event`` helper, imported lazily to avoid a circular import.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import (
    Issue,
    IssueStatus,
    SignalType,
)
from app.services.analysis_llm import AnalysisLlmService

logger = logging.getLogger(__name__)

# Only diagnose issues a team would still act on.
_DIAGNOSABLE_STATUSES = (
    IssueStatus.open,
    IssueStatus.diagnosing,
    IssueStatus.resolving,
    IssueStatus.recurring,
)

_DIAGNOSIS_SYSTEM_PROMPT = (
    "You are a senior LLM reliability engineer reviewing a cluster of related "
    "production failures (one 'issue'). Given the issue title and a sample of its "
    "evidence, determine the most likely root cause and propose one concrete fix.\n"
    'Respond with JSON only: {"root_cause": "<2-4 sentences>", '
    '"suggested_fix": "<one concrete, actionable fix>"}'
)

_MAX_EVIDENCE_FOR_DIAGNOSIS = 12


@dataclass
class Diagnosis:
    root_cause: str
    suggested_fix: str | None


def parse_diagnosis(content: str) -> Diagnosis | None:
    """Parse the diagnosis JSON. Returns None on garbage or a missing root cause."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    root_cause = data.get("root_cause")
    if not isinstance(root_cause, str) or not root_cause.strip():
        return None
    fix = data.get("suggested_fix")
    return Diagnosis(
        root_cause=root_cause.strip()[:4000],
        suggested_fix=fix.strip()[:4000] if isinstance(fix, str) and fix.strip() else None,
    )


def _evidence_digest(issue: Issue) -> str:
    """Compact text of an issue's evidence for the diagnosis prompt."""
    lines: list[str] = []
    for ev in issue.evidence[:_MAX_EVIDENCE_FOR_DIAGNOSIS]:
        st = ev.signal_type.value if isinstance(ev.signal_type, SignalType) else ev.signal_type
        detail = (ev.detail or "").strip().replace("\n", " ")
        lines.append(f"- [{st}] {detail[:300]}")
    return "\n".join(lines) if lines else "(no evidence details)"


async def diagnose_issues(
    db: AsyncSession,
    project_id: UUID,
    *,
    llm: AnalysisLlmService | None,
    limit: int = 10,
) -> dict:
    """Diagnose undiagnosed active issues: fill root_cause + suggested_fix via the LLM.

    No-op (returns 0) when no LLM is configured — diagnosis is inherently generative.
    Commits and returns ``{"diagnosed": n}``.
    """
    if llm is None:
        return {"diagnosed": 0}

    from app.services.engine.engine_service import _event
    from app.services.llm_usage_tracker import record_llm_usage

    rows = (
        await db.execute(
            select(Issue)
            .where(
                Issue.project_id == project_id,
                Issue.root_cause.is_(None),
                Issue.status.in_(_DIAGNOSABLE_STATUSES),
            )
            .options(selectinload(Issue.evidence))
            .order_by(Issue.last_seen_at.desc().nullslast())
            .limit(limit)
        )
    ).scalars().all()

    diagnosed = 0
    for issue in rows:
        prompt = (
            f"Issue title: {issue.title}\n"
            f"Category: {issue.category or 'unknown'}\n"
            f"Signal types: {', '.join(issue.signal_types or [])}\n\n"
            f"Evidence:\n{_evidence_digest(issue)}"
        )
        try:
            content, usage = await llm.tracked_chat_completion(
                messages=[
                    {"role": "system", "content": _DIAGNOSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
        except Exception:
            logger.exception("Issue diagnosis LLM call failed for issue %s", issue.id)
            break  # treat as infrastructure failure; stop the batch

        await record_llm_usage(
            db,
            project_id=project_id,
            service_name="issue_diagnosis",
            function_name="diagnose_issue",
            provider=llm.provider,
            model=llm.model,
            usage=usage,
        )

        parsed = parse_diagnosis(content)
        if parsed is None:
            continue
        issue.root_cause = parsed.root_cause
        issue.suggested_fix = parsed.suggested_fix
        db.add(_event(issue.id, "diagnosed", {"has_fix": parsed.suggested_fix is not None}))
        diagnosed += 1

    await db.commit()
    logger.info("Diagnosed %d issue(s) for project %s", diagnosed, project_id)
    return {"diagnosed": diagnosed}
