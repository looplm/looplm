"""Shared pieces of the Overview response payloads."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.time_buckets import Bucket

__all__ = ["Bucket", "Delta", "OverviewPeriod"]


class OverviewPeriod(BaseModel):
    """The resolved window, echoed back so the UI can label the axis."""

    start: datetime
    end: datetime
    bucket: Bucket
    buckets: int
    previous_start: datetime
    previous_end: datetime


class Delta(BaseModel):
    """A metric compared against the equally-long window immediately before this one.

    ``change_pct`` is None when there is no usable baseline (a zero or missing previous
    value). The UI renders nothing in that case rather than inventing a 0% or +100%.
    """

    current: float | None = None
    previous: float | None = None
    change_pct: float | None = None
