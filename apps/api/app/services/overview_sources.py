"""Number and type of indexed data sources, across four dimensions.

Three of the four are pure Postgres and live here: registry business metadata, coverage
status, and provider type. The fourth (the index's own file/content-type facet) needs a
live call into the index and stays in ``/api/index-explorer/file-types``, which the
browser fetches lazily per provider. Keeping live I/O out of this endpoint means one
expired index credential cannot slow down or blank the Overview page.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.models.source_registry import SourceExpectation, SourceGapRun
from app.schemas.overview_sources import (
    CoverageBlock,
    CoveragePoint,
    ProviderRef,
    ProviderTypeAggregate,
    RegistryDimension,
    RegistryDimensionValue,
    RegistrySummary,
    SourcesOverviewResponse,
)
from app.services.time_buckets import safe_rate

# The registry metadata fields worth counting by, with their display labels.
REGISTRY_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("typ", "Type"),
    ("sparte", "Sparte"),
    ("publisher", "Publisher"),
    ("hierarchie", "Hierarchie"),
    ("adapter_tag", "Adapter tag"),
)

# Free-text fields can have a long tail; everything past this folds into "other".
DEFAULT_TOP = 20

# Latest gap run older than this is called out as stale.
STALE_AFTER = timedelta(days=14)

UNSET_LABEL = "(not set)"
OTHER_KEY = "__other__"

# How many completed gap runs to return as history.
HISTORY_LIMIT = 50


def collapse_gap_status(status: str | None) -> str:
    """Map a raw gap-run row status onto the four buckets the UI shows.

    Mirrors the client-side collapse in ``source-registry-shared.ts``. Ported here so the
    two cannot disagree about what "covered" means.
    """
    if status in ("covered_url", "covered_title", "covered"):
        return "covered"
    if status in ("review", "missing", "acked"):
        return status
    return "unknown"


def gap_run_counts(run: SourceGapRun) -> dict[str, int]:
    """The coverage counts persisted on a gap run.

    The single reader for these keys. ``routers/source_registry._summary_from_run`` uses it
    too, so the Overview and the Data Sources page can never disagree about the numbers
    for the same run even though they wrap them in different response shapes.
    """
    summary = (run.results or {}).get("summary", {}) or {}
    return {
        "total": int(summary.get("total") or run.total or 0),
        "covered": int(summary.get("covered") or 0),
        "review": int(summary.get("review") or 0),
        "missing": int(summary.get("missing") or 0),
        "acked": int(summary.get("acked") or 0),
    }


def gap_run_summary(run: SourceGapRun) -> CoveragePoint:
    """Read a completed gap run into a coverage point."""
    counts = gap_run_counts(run)
    return CoveragePoint(
        run_id=run.id,
        created_at=run.created_at,
        covered_rate=safe_rate(counts["covered"], counts["total"]),
        **counts,
    )


def _status_by_expectation(run: SourceGapRun | None) -> dict[str, str]:
    """expectation_id -> collapsed status, from a gap run's persisted rows."""
    if run is None:
        return {}
    rows = (run.results or {}).get("rows") or []
    out: dict[str, str] = {}
    for row in rows:
        expectation_id = row.get("expectation_id")
        if expectation_id:
            out[str(expectation_id)] = collapse_gap_status(row.get("status"))
    return out


def _build_dimension(
    key: str,
    label: str,
    rows: list[dict],
    statuses: dict[str, str],
    top: int,
) -> RegistryDimension:
    """Count sources by one metadata field, cross-tabbed against coverage status."""
    buckets: dict[str | None, dict[str, int]] = defaultdict(
        lambda: {"count": 0, "covered": 0, "review": 0, "missing": 0, "acked": 0, "unknown": 0}
    )
    for row in rows:
        raw = row.get(key)
        value = raw.strip() if isinstance(raw, str) and raw.strip() else None
        entry = buckets[value]
        entry["count"] += 1
        entry[statuses.get(str(row["id"]), "unknown")] += 1

    ordered = sorted(buckets.items(), key=lambda kv: (-kv[1]["count"], kv[0] or ""))
    distinct = len(ordered)
    truncated = distinct > top
    kept, overflow = ordered[:top], ordered[top:]

    values = [
        RegistryDimensionValue(
            value=value,
            label=value if value is not None else UNSET_LABEL,
            **counts,
        )
        for value, counts in kept
    ]
    if overflow:
        merged = {"count": 0, "covered": 0, "review": 0, "missing": 0, "acked": 0, "unknown": 0}
        for _value, counts in overflow:
            for k, v in counts.items():
                merged[k] += v
        values.append(
            RegistryDimensionValue(
                value=OTHER_KEY, label=f"{len(overflow)} more", **merged
            )
        )

    return RegistryDimension(
        key=key,
        label=label,
        values=values,
        distinct_values=distinct,
        truncated=truncated,
    )


async def count_indexed_sources(
    db: AsyncSession, project: Project
) -> tuple[int, int]:
    """(registry source count, provider count) for the KPI tile.

    Two cheap counts so the summary endpoint can fill the whole KPI row in one request
    without waiting on the sources breakdown. A project with no provider gets (0, 0),
    which the UI renders as "not configured" rather than an empty index.
    """
    sources = (
        await db.execute(
            select(func.count(SourceExpectation.id)).where(
                SourceExpectation.project_id == project.id
            )
        )
    ).scalar()
    providers = (
        await db.execute(
            select(func.count(IndexProvider.id)).where(IndexProvider.project_id == project.id)
        )
    ).scalar()
    return int(sources or 0), int(providers or 0)


async def compute_sources_overview(
    db: AsyncSession,
    project: Project,
    *,
    provider_id: UUID | None = None,
    top: int = DEFAULT_TOP,
) -> SourcesOverviewResponse:
    providers = (
        (
            await db.execute(
                select(IndexProvider)
                .where(IndexProvider.project_id == project.id)
                .order_by(IndexProvider.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    exp_query = select(
        SourceExpectation.id,
        SourceExpectation.provider_id,
        SourceExpectation.typ,
        SourceExpectation.sparte,
        SourceExpectation.publisher,
        SourceExpectation.hierarchie,
        SourceExpectation.adapter_tag,
    ).where(SourceExpectation.project_id == project.id)
    if provider_id:
        exp_query = exp_query.where(SourceExpectation.provider_id == provider_id)
    exp_rows = [dict(r._mapping) for r in (await db.execute(exp_query)).all()]

    per_provider: dict[UUID, int] = defaultdict(int)
    for row in exp_rows:
        per_provider[row["provider_id"]] += 1

    by_type: dict[str, int] = defaultdict(int)
    provider_refs: list[ProviderRef] = []
    for p in providers:
        type_name = p.type.value if hasattr(p.type, "value") else str(p.type)
        by_type[type_name] += 1
        provider_refs.append(
            ProviderRef(
                id=p.id,
                name=p.name,
                type=type_name,
                source_count=per_provider.get(p.id, 0),
            )
        )

    # Coverage history. Only completed runs carry a usable summary.
    gap_query = (
        select(SourceGapRun)
        .where(SourceGapRun.project_id == project.id, SourceGapRun.status == "completed")
        .order_by(SourceGapRun.created_at.desc())
        .limit(HISTORY_LIMIT)
    )
    if provider_id:
        gap_query = gap_query.where(SourceGapRun.provider_id == provider_id)
    gap_runs = (await db.execute(gap_query)).scalars().all()

    latest_run = gap_runs[0] if gap_runs else None
    history = [gap_run_summary(r) for r in reversed(gap_runs)]
    latest = gap_run_summary(latest_run) if latest_run else None

    stale = False
    stale_reason: str | None = None
    if latest is None:
        stale = True
        stale_reason = "No gap analysis has run yet"
    else:
        age = datetime.now(timezone.utc) - _as_utc(latest.created_at)
        if latest.total != len(exp_rows):
            stale = True
            stale_reason = (
                f"The source list has changed since the last run "
                f"({len(exp_rows)} sources now, {latest.total} then)"
            )
        elif age > STALE_AFTER:
            stale = True
            stale_reason = f"Last analysed {age.days} days ago"

    statuses = _status_by_expectation(latest_run)
    dimensions = [
        _build_dimension(key, label, exp_rows, statuses, top)
        for key, label in REGISTRY_DIMENSIONS
    ]

    return SourcesOverviewResponse(
        providers=provider_refs,
        by_type=[
            ProviderTypeAggregate(type=t, provider_count=c)
            for t, c in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        registry=RegistrySummary(total_sources=len(exp_rows), dimensions=dimensions),
        coverage=CoverageBlock(
            latest=latest, history=history, stale=stale, stale_reason=stale_reason
        ),
    )


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
