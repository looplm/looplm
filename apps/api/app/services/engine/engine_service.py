"""Issue detection orchestrator.

Ties the pieces together for one detection pass:

    collect_signals → cluster_signals → upsert Issue / IssueEvidence / IssueEvent

This is the on-demand entry point (called by the issues router). The autonomous
background loop is a later phase that will call ``detect_issues`` on a schedule.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import IssueSeverity
from app.models.models import (
    Integration,
    Issue,
    IssueEvidence,
    IssueEvent,
    IssueStatus,
    SignalType,
    Trace,
)
from app.services.analysis_llm import AnalysisLlmService
from app.services.engine.clustering import (
    ExistingIssueRef,
    IssueGroup,
    cluster_signals,
)
from app.services.engine.signals import Signal, collect_signals

logger = logging.getLogger(__name__)

# Statuses eligible to absorb new signals. 'dismissed' is excluded — the user
# said it's not an issue, so we don't resurrect it.
_MATCHABLE_STATUSES = (
    IssueStatus.open,
    IssueStatus.diagnosing,
    IssueStatus.resolving,
    IssueStatus.recurring,
    IssueStatus.resolved,
)

# Active statuses — a duplicate in one of these keeps a merged survivor alive.
_ACTIVE_STATUSES = (
    IssueStatus.open,
    IssueStatus.diagnosing,
    IssueStatus.resolving,
    IssueStatus.recurring,
)

_SEVERITY_RANK = {IssueSeverity.high: 0, IssueSeverity.medium: 1, IssueSeverity.low: 2}


async def detect_issues(
    db: AsyncSession,
    project_id: UUID,
    *,
    since: datetime | None = None,
    llm: AnalysisLlmService | None = None,
) -> dict:
    """Run one detection pass for a project. Commits and returns a summary dict."""
    integration_ids = await _project_integration_ids(db, project_id)
    if not integration_ids:
        return _summary(0, 0, 0)

    total_traces = await _total_root_traces(db, integration_ids, since)

    # Self-healing cleanup: collapse any pre-existing issues that share a
    # fingerprint into a single survivor before detecting. Repairs duplicates
    # created before fingerprint dedup was wired up, and keeps the list clean
    # even if the LLM clusterer ever splits the same problem into two issues.
    merged = await _merge_duplicate_issues_by_fingerprint(db, project_id, total_traces)

    signals = await collect_signals(
        db, project_id, since=since, integration_ids=integration_ids
    )
    if not signals:
        if merged:
            await db.commit()
        return _summary(0, 0, 0, merged)

    existing = await _load_matchable_issues(db, project_id)
    groups, _usage = await cluster_signals(signals, existing, llm)

    lone_integration = integration_ids[0] if len(integration_ids) == 1 else None

    # Deterministic dedup index: fingerprint -> issue id. Seeded with existing
    # issues and grown as new issues are created during this pass, so any group
    # the clusterer left unmatched (the no-LLM fallback, the LLM-overflow tail,
    # or simply a repeat detection run) still collapses onto the right issue
    # instead of spawning a duplicate "Recurring X failures".
    fingerprint_to_id: dict[str, UUID] = {}
    for e in existing:
        if e.fingerprint:
            fingerprint_to_id.setdefault(e.fingerprint, e.id)

    created = updated = 0
    existing_by_id = {e.id: e for e in existing}
    for group in groups:
        is_new = await _apply_group(
            db,
            project_id=project_id,
            group=group,
            signals=signals,
            known_existing_ids=set(existing_by_id),
            fingerprint_to_id=fingerprint_to_id,
            total_traces=total_traces,
            lone_integration_id=lone_integration,
        )
        created += int(is_new)
        updated += int(not is_new)

    await db.commit()
    logger.info(
        "Issue detection for project %s: %d signals, %d created, %d updated, %d merged",
        project_id, len(signals), created, updated, merged,
    )
    return _summary(len(signals), created, updated, merged)


def _summary(signals: int, created: int, updated: int, merged: int = 0) -> dict:
    return {
        "signals": signals,
        "issues_created": created,
        "issues_updated": updated,
        "issues_merged": merged,
    }


# ── Diagnosis ──────────────────────────────────────────────────────

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


async def _project_integration_ids(db: AsyncSession, project_id: UUID) -> list[UUID]:
    rows = await db.execute(
        select(Integration.id).where(Integration.project_id == project_id)
    )
    return list(rows.scalars().all())


async def _load_matchable_issues(
    db: AsyncSession, project_id: UUID
) -> list[ExistingIssueRef]:
    rows = await db.execute(
        select(Issue.id, Issue.title, Issue.category, Issue.fingerprint).where(
            Issue.project_id == project_id,
            Issue.status.in_(_MATCHABLE_STATUSES),
        )
    )
    return [
        ExistingIssueRef(id=r.id, title=r.title, category=r.category, fingerprint=r.fingerprint)
        for r in rows
    ]


async def _merge_duplicate_issues_by_fingerprint(
    db: AsyncSession, project_id: UUID, total_traces: int
) -> int:
    """Collapse matchable issues that share a fingerprint into one survivor.

    The survivor is the oldest issue (stable identity); the rest are absorbed —
    their evidence and events are reassigned, metadata is unioned, and the
    duplicate rows are deleted. Dismissed issues are left untouched (the user
    already judged them). Returns the number of duplicates removed. Does not
    commit — the caller owns the transaction.
    """
    rows = (
        await db.execute(
            select(Issue)
            .where(
                Issue.project_id == project_id,
                Issue.fingerprint.isnot(None),
                Issue.status.in_(_MATCHABLE_STATUSES),
            )
            .order_by(Issue.created_at.asc())
        )
    ).scalars().all()

    by_fingerprint: dict[str, list[Issue]] = {}
    for issue in rows:
        by_fingerprint.setdefault(issue.fingerprint, []).append(issue)

    removed = 0
    for fingerprint, group in by_fingerprint.items():
        if len(group) < 2:
            continue
        survivor, *dups = group  # oldest first
        survivor_keys = await _existing_evidence_keys(db, survivor.id)
        for dup in dups:
            await _absorb_issue(db, survivor, dup, survivor_keys)
        db.add(_event(survivor.id, "merged", {"fingerprint": fingerprint, "count": len(dups)}))
        await db.flush()
        await _recompute_counts(db, survivor, total_traces)
        removed += len(dups)

    return removed


async def _absorb_issue(
    db: AsyncSession, survivor: Issue, dup: Issue, survivor_keys: set[tuple]
) -> None:
    """Fold ``dup`` into ``survivor`` and delete it. Pure-core child reassignment
    so the ORM cascade never deletes the rows we just moved."""
    dup_evidence = (
        await db.execute(
            select(IssueEvidence.id, IssueEvidence.trace_id, IssueEvidence.signal_type).where(
                IssueEvidence.issue_id == dup.id
            )
        )
    ).all()
    to_delete: list[UUID] = []
    to_move: list[UUID] = []
    for ev_id, trace_id, signal_type in dup_evidence:
        st = signal_type.value if isinstance(signal_type, SignalType) else signal_type
        key = (trace_id, st)
        if trace_id is not None and key in survivor_keys:
            to_delete.append(ev_id)  # would collide on uq_issue_evidence
        else:
            to_move.append(ev_id)
            survivor_keys.add(key)
    if to_delete:
        await db.execute(delete(IssueEvidence).where(IssueEvidence.id.in_(to_delete)))
    if to_move:
        await db.execute(
            update(IssueEvidence).where(IssueEvidence.id.in_(to_move)).values(issue_id=survivor.id)
        )
    await db.execute(
        update(IssueEvent).where(IssueEvent.issue_id == dup.id).values(issue_id=survivor.id)
    )

    # Union metadata onto the survivor.
    survivor.signal_types = sorted(set(survivor.signal_types or []) | set(dup.signal_types or []))
    s_first, d_first = _aware(survivor.first_seen_at), _aware(dup.first_seen_at)
    if d_first is not None and (s_first is None or d_first < s_first):
        survivor.first_seen_at = dup.first_seen_at
    s_last, d_last = _aware(survivor.last_seen_at), _aware(dup.last_seen_at)
    if d_last is not None and (s_last is None or d_last > s_last):
        survivor.last_seen_at = dup.last_seen_at
    if not survivor.root_cause and dup.root_cause:
        survivor.root_cause = dup.root_cause
        survivor.suggested_fix = dup.suggested_fix
    if _SEVERITY_RANK.get(dup.severity, 1) < _SEVERITY_RANK.get(survivor.severity, 1):
        survivor.severity = dup.severity
    # A still-active duplicate revives a survivor that had been resolved.
    if survivor.status == IssueStatus.resolved and dup.status in _ACTIVE_STATUSES:
        survivor.status = IssueStatus.recurring
        survivor.resolved_at = None

    await db.flush()  # persist child reassignment before the core delete
    await db.execute(delete(Issue).where(Issue.id == dup.id))
    db.expunge(dup)  # drop the now-deleted row from the identity map


async def _total_root_traces(
    db: AsyncSession, integration_ids: list[UUID], since: datetime | None
) -> int:
    query = select(func.count(Trace.id)).where(
        Trace.integration_id.in_(integration_ids),
        Trace.parent_trace_id.is_(None),
    )
    if since:
        query = query.where(Trace.created_at > since)
    return int((await db.execute(query)).scalar() or 0)


async def _apply_group(
    db: AsyncSession,
    *,
    project_id: UUID,
    group: IssueGroup,
    signals: list[Signal],
    known_existing_ids: set[UUID],
    fingerprint_to_id: dict[str, UUID],
    total_traces: int,
    lone_integration_id: UUID | None,
) -> bool:
    """Create or update one issue from a group. Returns True if a new issue was created.

    Resolves the target issue in priority order:
      1. an existing issue the clusterer explicitly matched, then
      2. any issue (existing, or already created in this pass) with the same
         fingerprint — the deterministic dedup that prevents duplicates.
    Falls back to creating a new issue, registering its fingerprint so later
    groups in this pass dedup against it. ``fingerprint_to_id`` is mutated.
    """
    members = [signals[i] for i in group.signal_indices]
    if not members:
        return False

    occurred = [_aware(s.occurred_at) for s in members if s.occurred_at is not None]
    group_first = min(occurred) if occurred else _now()
    group_last = max(occurred) if occurred else _now()
    signal_type_values = sorted({s.signal_type.value for s in members})
    fingerprint = _dominant_fingerprint(members)

    target_id: UUID | None = None
    if group.existing_issue_id is not None and group.existing_issue_id in known_existing_ids:
        target_id = group.existing_issue_id
    elif fingerprint and fingerprint in fingerprint_to_id:
        target_id = fingerprint_to_id[fingerprint]

    issue = await db.get(Issue, target_id) if target_id is not None else None

    if issue is None:  # nothing to merge into (or a matched issue raced/deleted)
        issue = Issue(
            project_id=project_id,
            integration_id=lone_integration_id,
            title=group.title,
            category=group.category,
            severity=group.severity,
            status=IssueStatus.open,
            signal_types=signal_type_values,
            fingerprint=fingerprint,
            first_seen_at=group_first,
            last_seen_at=group_last,
        )
        db.add(issue)
        await db.flush()
        db.add(_event(issue.id, "detected", {"signal_count": len(members)}))
        existing_keys: set[tuple] = set()
        if fingerprint:
            fingerprint_to_id[fingerprint] = issue.id
        is_new = True
    else:
        is_new = False
        if fingerprint:
            fingerprint_to_id.setdefault(fingerprint, issue.id)
        recurred = issue.status in (IssueStatus.resolved,)
        if recurred:
            issue.status = IssueStatus.recurring
            issue.resolved_at = None
            db.add(_event(issue.id, "recurred", {"signal_count": len(members)}))
        else:
            db.add(_event(issue.id, "updated", {"signal_count": len(members)}))

        issue.signal_types = sorted(set(issue.signal_types or []) | set(signal_type_values))
        ex_first = _aware(issue.first_seen_at)
        ex_last = _aware(issue.last_seen_at)
        if ex_first is None or group_first < ex_first:
            issue.first_seen_at = group_first
        if ex_last is None or group_last > ex_last:
            issue.last_seen_at = group_last
        existing_keys = await _existing_evidence_keys(db, issue.id)

    # Add evidence, skipping duplicates that would violate uq_issue_evidence.
    added_keys: set[tuple] = set()
    for s in members:
        key = (s.trace_id, s.signal_type.value)
        if s.trace_id is not None and (key in existing_keys or key in added_keys):
            continue
        added_keys.add(key)
        db.add(
            IssueEvidence(
                issue_id=issue.id,
                trace_id=s.trace_id,
                signal_type=s.signal_type,
                detail=s.detail or s.summary,
                occurred_at=s.occurred_at,
            )
        )

    await db.flush()
    await _recompute_counts(db, issue, total_traces)
    return is_new


def _dominant_fingerprint(members: list[Signal]) -> str | None:
    counts: dict[str, int] = {}
    for s in members:
        if s.fingerprint_hint:
            counts[s.fingerprint_hint] = counts.get(s.fingerprint_hint, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)[:256]


async def _existing_evidence_keys(db: AsyncSession, issue_id: UUID) -> set[tuple]:
    rows = await db.execute(
        select(IssueEvidence.trace_id, IssueEvidence.signal_type).where(
            IssueEvidence.issue_id == issue_id
        )
    )
    keys: set[tuple] = set()
    for trace_id, signal_type in rows:
        st = signal_type.value if isinstance(signal_type, SignalType) else signal_type
        keys.add((trace_id, st))
    return keys


async def _recompute_counts(db: AsyncSession, issue: Issue, total_traces: int) -> None:
    distinct_traces = await db.execute(
        select(func.count(func.distinct(IssueEvidence.trace_id))).where(
            IssueEvidence.issue_id == issue.id,
            IssueEvidence.trace_id.isnot(None),
        )
    )
    count = int(distinct_traces.scalar() or 0)
    issue.trace_count = count
    if total_traces > 0:
        issue.affected_pct = min(100.0, round(count / total_traces * 100, 2))


def _event(issue_id: UUID, event_type: str, detail: dict | None = None) -> IssueEvent:
    return IssueEvent(issue_id=issue_id, event_type=event_type, detail=detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """Coerce naive datetimes (SQLite drops tzinfo on read) to UTC for safe comparison."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
