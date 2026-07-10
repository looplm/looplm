"""Shared plumbing for chunk-level LLM judges.

Both the relevance judge (:mod:`chunk_ai_judge`, grades chunks against a query)
and the standalone-interpretability judge (:mod:`chunk_standalone_judge`, no
query) send full untruncated chunks in token-budgeted batches and parse a small
JSON verdict object back. The batching, usage accumulation and tolerant JSON
extraction live here so the two judges cannot drift apart.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Sequence

from app.config import settings
from app.services.analysis_llm import LlmUsageInfo

# Rough token cost of the per-chunk scaffolding (the ``[n]`` marker and blank-line separator).
PER_CHUNK_OVERHEAD_TOKENS = 8


@dataclass
class AiJudgeChunk:
    """A chunk to be judged: its index-key plus the text the judge reads."""

    chunk_id: str
    text: str


def clean(text: str | None) -> str:
    """Collapse runs of whitespace so a chunk sits on as few tokens as possible without loss."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def estimate_tokens(text: str) -> int:
    """Conservative char-based token estimate (deliberately under-fills the budget)."""
    per_token = max(1.0, float(settings.ai_judge_chars_per_token))
    return math.ceil(len(text) / per_token)


def batch_chunks(chunks: list[AiJudgeChunk], *, fixed_texts: Sequence[str]) -> list[list[AiJudgeChunk]]:
    """Greedy-pack chunks into the fewest calls that fit the judge model's context window.

    ``fixed_texts`` are the parts repeated in every call (system prompt, query,
    reference answer, ...); their token estimate is subtracted from the budget.
    A chunk larger than the whole budget still goes out on its own rather than
    being dropped. ``ai_judge_max_batch_chunks`` caps how many chunks share one
    call so grading quality does not degrade on pools of many short chunks.
    """
    budget = max(
        1,
        int(settings.ai_judge_context_tokens)
        - int(settings.ai_judge_response_reserve_tokens)
        - sum(estimate_tokens(t or "") for t in fixed_texts),
    )
    max_per_batch = max(1, int(settings.ai_judge_max_batch_chunks))

    batches: list[list[AiJudgeChunk]] = []
    current: list[AiJudgeChunk] = []
    tokens = 0
    for chunk in chunks:
        cost = estimate_tokens(clean(chunk.text)) + PER_CHUNK_OVERHEAD_TOKENS
        if current and (tokens + cost > budget or len(current) >= max_per_batch):
            batches.append(current)
            current = []
            tokens = 0
        current.append(chunk)
        tokens += cost
    if current:
        batches.append(current)
    return batches


def extract_json_object(content: str) -> dict | None:
    """The first JSON object in a model response, tolerating code fences and stray prose."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def empty_usage() -> LlmUsageInfo:
    return LlmUsageInfo(
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        cost_usd=None,
        cached_tokens=0,
        reasoning_tokens=0,
        duration_ms=0,
    )


def add_usage(acc: LlmUsageInfo, one: LlmUsageInfo) -> None:
    acc.input_tokens += one.input_tokens
    acc.output_tokens += one.output_tokens
    acc.total_tokens += one.total_tokens
    acc.cached_tokens += one.cached_tokens
    acc.reasoning_tokens += one.reasoning_tokens
    acc.duration_ms += one.duration_ms
    if one.cost_usd is not None:
        acc.cost_usd = (acc.cost_usd or 0.0) + one.cost_usd


def usage_dict(usage: LlmUsageInfo) -> dict:
    """The serialized per-pass usage summary stored in ``results['usage']``."""
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cost_usd": round(usage.cost_usd, 6) if usage.cost_usd is not None else None,
    }
