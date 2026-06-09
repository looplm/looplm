"""Shared helper for the per-project retrieval span-name setting.

The retrieval/RAG step in a trace is identified by its span *name* (e.g.
``retrieval-context``). Different instrumentations name it differently, so the
name is a per-project setting; this module is the single source of truth for the
settings key and the default, mirroring ``observe_filter`` for trace names.
"""

from __future__ import annotations

from app.models.project import Project

SETTINGS_KEY = "retrieval_span_name"
DEFAULT_RETRIEVAL_SPAN_NAME = "retrieval-context"


def get_retrieval_span_name(project: Project) -> str:
    """Span name the project uses for its retrieval/RAG step.

    Falls back to the default when unset or blank.
    """
    raw = (project.settings or {}).get(SETTINGS_KEY)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return DEFAULT_RETRIEVAL_SPAN_NAME
