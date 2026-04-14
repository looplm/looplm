"""Static pricing table for LLM models (USD per 1M tokens)."""

from __future__ import annotations

# Prices in USD per 1 million tokens.
# Source: provider pricing pages as of 2025-05.
MODEL_PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-2024-11-20": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    "gpt-5.4": {"input": 2.50, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
    "gpt-5.2": {"input": 1.75, "output": 14.00},
    "gpt-5.1": {"input": 1.25, "output": 10.00},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
    "o3": {"input": 10.00, "output": 40.00},
    "o4-mini": {"input": 1.10, "output": 4.40},
    # Anthropic (for Claude Agent SDK cost passthrough)
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-3-5-20241022": {"input": 0.80, "output": 4.00},
}


def _normalize_model(model: str) -> str | None:
    """Try to match an Azure deployment name or versioned model to a known key."""
    lower = model.lower()
    for key in MODEL_PRICING:
        if lower.startswith(key) or key.startswith(lower):
            return key
    # Common Azure deployment naming patterns
    for base in ("gpt-5.4", "gpt-5.2", "gpt-5.1", "gpt-4.1-nano", "gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"):
        if base in lower:
            return base
    return None


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Calculate cost in USD for a given model and token counts.

    Returns None if the model is not in the pricing table.
    """
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        normalized = _normalize_model(model)
        pricing = MODEL_PRICING.get(normalized) if normalized else None
    if not pricing:
        return None
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
