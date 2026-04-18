"""Shared helper for the per-project 'included trace types' filter used across Observe endpoints."""

from __future__ import annotations

from app.models.project import Project


SETTINGS_KEY = "observe_trace_names"


def get_observe_trace_names(project: Project) -> list[str]:
    """Return the sanitized list of trace names the project wants included in Observe metrics.

    Empty list = no filter (include every trace name).
    """
    raw = (project.settings or {}).get(SETTINGS_KEY)
    if not isinstance(raw, list):
        return []
    return [n for n in raw if isinstance(n, str) and n]
