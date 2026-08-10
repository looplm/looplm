"""Overview endpoints — the single stakeholder-facing summary of the whole project.

Answers four questions that were previously spread across five pages, or not answered at
all: how is feedback trending, is adoption growing, how is the eval suite doing, and what
is actually indexed.

Split into two endpoints on purpose. ``/summary`` is pure Postgres and carries the three
time series on one shared bucket axis, so the charts and the KPI sparklines line up
column for column. ``/sources`` is also Postgres-only; the live index reads it would
otherwise need stay in ``/api/index-explorer/*``, which the browser calls lazily per
provider. That way one expired index credential degrades a single card instead of
blanking the page.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.auth import require_section

from . import sources, summary

router = APIRouter(
    prefix="/api/overview",
    tags=["overview"],
    dependencies=[require_section("observe", "overview")],
)

router.include_router(summary.router)
router.include_router(sources.router)

__all__ = ["router"]
