"""Response schemas for GET /api/overview/sources.

Note a product limitation that shows up here: nothing snapshots the index's document
count over time. ``/api/index-explorer/summary`` reads it live on every request, so the
only real history available for a "sources over time" chart is the gap-run series below.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

# Collapsed gap-run statuses. The raw run also distinguishes covered_url from
# covered_title; both mean covered.
COVERAGE_STATUSES = ("covered", "review", "missing", "acked", "unknown")


class RegistryDimensionValue(BaseModel):
    """One value of a registry metadata field, with its coverage cross-tab."""

    # None means the field is unset on those sources, which is itself worth seeing.
    value: Optional[str] = None
    label: str
    count: int
    covered: int
    review: int
    missing: int
    acked: int
    unknown: int


class RegistryDimension(BaseModel):
    key: str
    label: str
    values: list[RegistryDimensionValue]
    distinct_values: int
    # True when values beyond the top-N were folded into an "other" row.
    truncated: bool


class RegistrySummary(BaseModel):
    total_sources: int
    dimensions: list[RegistryDimension]


class CoveragePoint(BaseModel):
    """One completed gap run. Coverage is a level, not a flow, so runs are never summed."""

    run_id: UUID
    created_at: datetime
    total: int
    covered: int
    review: int
    missing: int
    acked: int
    covered_rate: float


class CoverageBlock(BaseModel):
    latest: Optional[CoveragePoint] = None
    # Oldest first, one point per completed run.
    history: list[CoveragePoint]
    # True when the latest run predates the current expectation list or is over two
    # weeks old, so the UI can say the numbers are out of date instead of implying they
    # are current.
    stale: bool
    stale_reason: Optional[str] = None


class ProviderRef(BaseModel):
    id: UUID
    name: str
    type: str
    source_count: int


class ProviderTypeAggregate(BaseModel):
    type: str
    provider_count: int


class SourcesOverviewResponse(BaseModel):
    providers: list[ProviderRef]
    by_type: list[ProviderTypeAggregate]
    registry: RegistrySummary
    coverage: CoverageBlock
