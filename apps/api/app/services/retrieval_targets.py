"""Per-project target values for retrieval-quality metrics.

Targets are stored as fractions in ``Project.settings["retrieval_targets"]`` and merged
over sensible defaults, so a project shows meaningful pass/fail colouring before anyone
configures anything. Each metric is judged at the panel's largest k (recall/ndcg/
hit_rate/precision @10); MRR is rank-based and judged on its own 0-1 scale.
"""

from __future__ import annotations

from typing import Any

SETTINGS_KEY = "retrieval_targets"

# Reasonable starting bars for an agentic-RAG setup; users override per project.
DEFAULT_TARGETS: dict[str, float] = {
    "recall": 0.80,
    "ndcg": 0.70,
    "mrr": 0.70,
    "hit_rate": 0.95,
    "precision": 0.50,
}
METRIC_KEYS: tuple[str, ...] = tuple(DEFAULT_TARGETS)


def _clamp(value: Any, fallback: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    return fallback


def get_retrieval_targets(settings: dict[str, Any] | None) -> dict[str, float]:
    """Targets merged over defaults, each clamped to [0, 1]."""
    raw = (settings or {}).get(SETTINGS_KEY)
    raw = raw if isinstance(raw, dict) else {}
    return {k: _clamp(raw.get(k), DEFAULT_TARGETS[k]) for k in METRIC_KEYS}


def sanitize_targets(raw: dict[str, Any] | None) -> dict[str, float]:
    """Normalize an incoming targets payload to the known keys, clamped to [0, 1]."""
    return {k: _clamp((raw or {}).get(k), DEFAULT_TARGETS[k]) for k in METRIC_KEYS}
