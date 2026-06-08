"""Issue endpoints — on-demand detection plus a prioritized issue list/detail.

Detection clusters recent production failure signals into named issues; the
list/detail endpoints surface them for review. The autonomous background loop
is a later phase — for now detection is triggered explicitly via POST /detect.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_project, get_current_user
from app.db import get_db
from app.models.issues import Issue, IssueEvent
from app.models.models import IssueStatus
from app.models.project import Project
from app.models.user import User
from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService
from app.services.engine.engine_service import detect_issues, diagnose_issues

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/issues", tags=["issues"])

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

# How many issues to diagnose synchronously in the detect request. Kept small so
# the request stays fast; the background poller diagnoses the remainder.
_INLINE_DIAGNOSE_LIMIT = 3


# ── Schemas ────────────────────────────────────────────────────────

class DetectResponse(BaseModel):
    signals: int
    issues_created: int
    issues_updated: int
    issues_diagnosed: int
    used_llm: bool


class IssueListItem(BaseModel):
    id: UUID
    title: str
    category: str | None
    severity: str
    status: str
    signal_types: list[str]
    trace_count: int
    affected_pct: float | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None


class EvidenceItem(BaseModel):
    trace_id: UUID | None
    signal_type: str
    detail: str | None
    occurred_at: datetime | None


class EventItem(BaseModel):
    event_type: str
    detail: dict | None
    created_at: datetime


class IssueDetail(IssueListItem):
    description: str | None
    root_cause: str | None
    suggested_fix: str | None
    integration_id: UUID | None
    created_at: datetime
    updated_at: datetime
    evidence: list[EvidenceItem]
    events: list[EventItem]


# ── Endpoints ──────────────────────────────────────────────────────

@router.post("/detect", response_model=DetectResponse)
async def run_detection(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
) -> DetectResponse:
    """Cluster the last ``days`` of production failure signals into issues."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    llm: AnalysisLlmService | None
    try:
        llm = AnalysisLlmService(user_settings=user.settings)
    except AnalysisLlmConfigError:
        # No analysis LLM configured — still run, using deterministic clustering.
        llm = None

    # Detection is the core result. If it fails, surface a real (non-sanitized)
    # message so the UI can show what went wrong.
    try:
        result = await detect_issues(db, project.id, since=since, llm=llm)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Issue detection failed for project %s", project.id)
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Detection failed: {exc}") from exc

    # Diagnosis is best-effort enrichment: bounded inline (the background poller
    # handles the rest) and never allowed to fail the detection response.
    diagnosed = 0
    try:
        diag = await diagnose_issues(db, project.id, llm=llm, limit=_INLINE_DIAGNOSE_LIMIT)
        diagnosed = diag["diagnosed"]
    except Exception:  # noqa: BLE001
        logger.exception("Issue diagnosis failed (detection results still returned)")
        await db.rollback()

    return DetectResponse(
        used_llm=llm is not None,
        issues_diagnosed=diagnosed,
        **result,
    )


@router.get("", response_model=list[IssueListItem])
async def list_issues(
    status: IssueStatus | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
) -> list[IssueListItem]:
    """List issues for the project, most severe and most recent first."""
    query = select(Issue).where(Issue.project_id == project.id)
    if status is not None:
        query = query.where(Issue.status == status)
    query = query.order_by(Issue.last_seen_at.desc().nullslast()).limit(limit)

    issues = (await db.execute(query)).scalars().all()
    items = [_to_list_item(i) for i in issues]
    items.sort(key=lambda x: (_SEVERITY_RANK.get(x.severity, 1), _neg_ts(x.last_seen_at)))
    return items


@router.get("/{issue_id}", response_model=IssueDetail)
async def get_issue(
    issue_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
) -> IssueDetail:
    issue = await _get_owned_issue(db, issue_id, project.id, with_relations=True)
    return IssueDetail(
        **_to_list_item(issue).model_dump(),
        description=issue.description,
        root_cause=issue.root_cause,
        suggested_fix=issue.suggested_fix,
        integration_id=issue.integration_id,
        created_at=issue.created_at,
        updated_at=issue.updated_at,
        evidence=[
            EvidenceItem(
                trace_id=e.trace_id,
                signal_type=e.signal_type.value,
                detail=e.detail,
                occurred_at=e.occurred_at,
            )
            for e in sorted(
                issue.evidence, key=lambda e: _neg_ts(e.occurred_at)
            )
        ],
        events=[
            EventItem(event_type=ev.event_type, detail=ev.detail, created_at=ev.created_at)
            for ev in sorted(issue.events, key=lambda ev: ev.created_at)
        ],
    )


@router.post("/{issue_id}/resolve", response_model=IssueListItem)
async def resolve_issue(
    issue_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
) -> IssueListItem:
    issue = await _get_owned_issue(db, issue_id, project.id)
    issue.status = IssueStatus.resolved
    issue.resolved_at = datetime.now(timezone.utc)
    db.add(IssueEvent(issue_id=issue.id, event_type="resolved"))
    await db.commit()
    await db.refresh(issue)
    return _to_list_item(issue)


@router.post("/{issue_id}/dismiss", response_model=IssueListItem)
async def dismiss_issue(
    issue_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
) -> IssueListItem:
    issue = await _get_owned_issue(db, issue_id, project.id)
    issue.status = IssueStatus.dismissed
    db.add(IssueEvent(issue_id=issue.id, event_type="dismissed"))
    await db.commit()
    await db.refresh(issue)
    return _to_list_item(issue)


# ── Helpers ────────────────────────────────────────────────────────

async def _get_owned_issue(
    db: AsyncSession, issue_id: UUID, project_id: UUID, *, with_relations: bool = False
) -> Issue:
    query = select(Issue).where(Issue.id == issue_id, Issue.project_id == project_id)
    if with_relations:
        query = query.options(
            selectinload(Issue.evidence), selectinload(Issue.events)
        )
    issue = (await db.execute(query)).scalar_one_or_none()
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


def _to_list_item(issue: Issue) -> IssueListItem:
    return IssueListItem(
        id=issue.id,
        title=issue.title,
        category=issue.category,
        severity=issue.severity.value,
        status=issue.status.value,
        signal_types=list(issue.signal_types or []),
        trace_count=issue.trace_count,
        affected_pct=issue.affected_pct,
        first_seen_at=issue.first_seen_at,
        last_seen_at=issue.last_seen_at,
    )


def _neg_ts(dt: datetime | None) -> float:
    """Sort key for 'most recent first' that tolerates None and naive/aware mixes."""
    if dt is None:
        return float("inf")
    ts = dt.timestamp() if dt.tzinfo else dt.replace(tzinfo=timezone.utc).timestamp()
    return -ts
