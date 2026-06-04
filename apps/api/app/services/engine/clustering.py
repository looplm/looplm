"""Cluster production failure signals into named issues via one LLM call.

The grouper is given the currently-open issues plus a batch of new failure
signals and asked to assign each signal to an existing issue or to a new named
issue. The LLM call is isolated behind ``cluster_signals`` and the response
parsing is a pure function (``parse_clustering_response``) so both can be
tested without a live model. When no LLM is available — or the call fails — we
fall back to a deterministic grouping by ``fingerprint_hint``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from uuid import UUID

from app.models.base import IssueSeverity
from app.services.analysis_llm import AnalysisLlmService, LlmUsageInfo
from app.services.engine.signals import Signal

logger = logging.getLogger(__name__)

_MAX_SIGNALS_PER_CALL = 60
_MAX_EXISTING_ISSUES = 50

_SYSTEM_PROMPT = (
    "You triage production failures for an LLM application. You are given a list "
    "of EXISTING open issues and a batch of NEW failure signals. Group the new "
    "signals into issues: signals describing the same underlying problem belong "
    "to one issue. Assign a signal to an existing issue when it is clearly the "
    "same problem; otherwise create a new issue.\n\n"
    "Return ONLY a JSON object of the form:\n"
    '{"groups": [{"title": "...", "category": "...", "severity": "high|medium|low", '
    '"existing_issue_id": "<id or null>", "signal_indices": [0, 2, 5]}]}\n\n'
    "Rules:\n"
    "- Every signal index (0-based, from the NEW list) must appear in exactly one group.\n"
    "- title: a short, specific, human-readable name (e.g. 'Agent fails to handle "
    "subscription cancellation requests'). Not a generic label.\n"
    "- category: a lowercase slug for the failure kind (e.g. tool_failure, "
    "retrieval_failure, quality_regression, unhandled_request, latency).\n"
    "- severity: high if it likely breaks the user task or is widespread; low if minor.\n"
    "- existing_issue_id: copy an id from the EXISTING list when it matches, else null.\n"
    "Default to creating focused issues over one catch-all bucket."
)


@dataclass
class IssueGroup:
    """A proposed issue covering a set of new signals (by index)."""

    title: str
    severity: IssueSeverity
    signal_indices: list[int]
    category: str | None = None
    existing_issue_id: UUID | None = None


@dataclass
class ExistingIssueRef:
    id: UUID
    title: str
    category: str | None = None


def _build_user_message(signals: list[Signal], existing: list[ExistingIssueRef]) -> str:
    existing_payload = [
        {"id": str(e.id), "title": e.title, "category": e.category}
        for e in existing[:_MAX_EXISTING_ISSUES]
    ]
    new_payload = [
        {"index": i, "signal_type": s.signal_type.value, "summary": s.summary}
        for i, s in enumerate(signals)
    ]
    return (
        "EXISTING issues:\n"
        + json.dumps(existing_payload, ensure_ascii=False)
        + "\n\nNEW signals:\n"
        + json.dumps(new_payload, ensure_ascii=False)
    )


def _norm_severity(value: object) -> IssueSeverity:
    try:
        return IssueSeverity(str(value).strip().lower())
    except ValueError:
        return IssueSeverity.medium


def parse_clustering_response(
    content: str,
    n_signals: int,
    existing_ids: set[UUID],
) -> list[IssueGroup]:
    """Parse the grouper's JSON into validated ``IssueGroup`` objects.

    Drops out-of-range indices, ignores unknown existing ids (treated as new),
    and assigns any signal the model forgot to a synthetic catch-all group so no
    signal is silently lost.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Clustering response was not valid JSON")
        return []

    raw_groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(raw_groups, list):
        return []

    groups: list[IssueGroup] = []
    seen_indices: set[int] = set()
    for g in raw_groups:
        if not isinstance(g, dict):
            continue
        indices = [
            i for i in (g.get("signal_indices") or [])
            if isinstance(i, int) and 0 <= i < n_signals and i not in seen_indices
        ]
        if not indices:
            continue
        seen_indices.update(indices)

        existing_id = None
        raw_id = g.get("existing_issue_id")
        if raw_id:
            try:
                candidate = UUID(str(raw_id))
                if candidate in existing_ids:
                    existing_id = candidate
            except ValueError:
                pass

        title = str(g.get("title") or "").strip() or "Untitled issue"
        category = g.get("category")
        groups.append(
            IssueGroup(
                title=title[:512],
                severity=_norm_severity(g.get("severity")),
                signal_indices=indices,
                category=str(category)[:128] if category else None,
                existing_issue_id=existing_id,
            )
        )

    # Safety net: bucket any signals the model omitted so nothing is dropped.
    missing = [i for i in range(n_signals) if i not in seen_indices]
    if missing:
        logger.info("Clustering omitted %d signal(s); bucketing as uncategorized", len(missing))
        groups.append(
            IssueGroup(
                title="Uncategorized failures",
                severity=IssueSeverity.low,
                signal_indices=missing,
                category="uncategorized",
            )
        )
    return groups


def fallback_groups_by_fingerprint(signals: list[Signal]) -> list[IssueGroup]:
    """Deterministic grouping by ``fingerprint_hint`` — used when no LLM is available."""
    buckets: dict[str, list[int]] = {}
    for i, s in enumerate(signals):
        buckets.setdefault(s.fingerprint_hint or s.signal_type.value, []).append(i)

    groups: list[IssueGroup] = []
    for hint, indices in buckets.items():
        category = hint.split(":", 1)[-1] if ":" in hint else hint
        groups.append(
            IssueGroup(
                title=f"Recurring {category.replace('_', ' ')} failures",
                severity=IssueSeverity.medium,
                signal_indices=indices,
                category=category[:128],
            )
        )
    return groups


async def cluster_signals(
    signals: list[Signal],
    existing: list[ExistingIssueRef],
    llm: AnalysisLlmService | None,
) -> tuple[list[IssueGroup], LlmUsageInfo | None]:
    """Group signals into issues. Returns ``(groups, usage)``.

    Caps the batch to ``_MAX_SIGNALS_PER_CALL`` to bound prompt size; any
    overflow is grouped deterministically so it still surfaces.
    """
    if not signals:
        return [], None

    head, tail = signals[:_MAX_SIGNALS_PER_CALL], signals[_MAX_SIGNALS_PER_CALL:]

    if llm is None:
        return fallback_groups_by_fingerprint(signals), None

    existing_ids = {e.id for e in existing}
    try:
        content, usage = await llm.tracked_chat_completion(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(head, existing)},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning("Clustering LLM call failed (%s); using deterministic fallback", exc)
        return fallback_groups_by_fingerprint(signals), None

    groups = parse_clustering_response(content, len(head), existing_ids)
    if not groups:
        groups = fallback_groups_by_fingerprint(head)

    # Re-base overflow indices onto the full list and append as fallback groups.
    if tail:
        offset = len(head)
        for fb in fallback_groups_by_fingerprint(tail):
            fb.signal_indices = [i + offset for i in fb.signal_indices]
            groups.append(fb)

    return groups, usage
