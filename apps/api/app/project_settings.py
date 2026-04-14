"""Helpers for canonicalizing project settings keys."""

from __future__ import annotations

from typing import Any

LEGACY_PROJECT_SETTING_ALIASES = {
    "eval_rde_gpt_endpoint": "eval_target_endpoint",
}


def normalize_project_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Promote legacy settings keys to their canonical names."""
    normalized = dict(settings or {})

    for legacy_key, canonical_key in LEGACY_PROJECT_SETTING_ALIASES.items():
        legacy_value = normalized.pop(legacy_key, None)
        if canonical_key not in normalized and legacy_value not in (None, ""):
            normalized[canonical_key] = legacy_value

    return normalized
