"""LLM "AI judge" for chunk relevance — a one-click second annotator.

Given a test case's query and the chunks it retrieved, the judge grades each chunk on the same
0..3 relevance scale a human uses (see :mod:`app.models.chunk_labels`). Its grades are stored
under the ``AI`` annotator so they show up as a distinct annotator in inter-annotator agreement,
letting a single human reviewer get a Cohen's kappa against the model without a second person.

The judge is deliberately model-agnostic: it routes through :class:`AnalysisLlmService` like the
rest of the analysis code, so it inherits the project's configured OpenAI / Azure provider.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.models.chunk_labels import GRADE_MAX, GRADE_MIN
from app.services.analysis_llm import AnalysisLlmService, LlmUsageInfo

# Per-chunk text budget sent to the judge — enough to assess relevance without ballooning the
# prompt when a case retrieved many long chunks.
_MAX_CHUNK_CHARS = 1200

# Editable in the request; this is the default rubric. Mirrors the human grading scale exactly
# so AI and human judgments are directly comparable.
DEFAULT_AI_JUDGE_INSTRUCTIONS = (
    "You are an expert relevance assessor for a retrieval system. For the user's query, judge "
    "how relevant each retrieved chunk is on this 0-3 scale:\n"
    "0 = irrelevant: does not help answer the query.\n"
    "1 = marginally relevant: mentions the topic but does not contribute to an answer.\n"
    "2 = relevant: contains information that helps answer the query.\n"
    "3 = highly relevant: directly and substantially answers the query.\n"
    "Judge each chunk only on whether it helps answer THIS query, not on general quality."
)


@dataclass
class AiJudgeChunk:
    """A chunk to be judged: its index-key plus the text the judge reads."""

    chunk_id: str
    text: str


def _build_user_prompt(query: str, chunks: list[AiJudgeChunk]) -> str:
    lines = [f"Query:\n{query}\n", "Chunks:"]
    for i, c in enumerate(chunks, start=1):
        body = (c.text or "").strip()[:_MAX_CHUNK_CHARS] or "(no text)"
        lines.append(f"\n[{i}]\n{body}")
    lines.append(
        f"\nReturn ONLY a JSON object of the form "
        f'{{"grades": [{{"chunk": 1, "grade": 0}}, ...]}}, one entry per chunk number above, '
        f"each grade an integer {GRADE_MIN}..{GRADE_MAX}. No prose."
    )
    return "\n".join(lines)


def _parse_grades(content: str, chunk_count: int) -> dict[int, int]:
    """Parse the judge's JSON into ``{1-based chunk number: grade}``, dropping anything invalid.

    Tolerates code fences and stray prose by extracting the first JSON object; ignores numbers
    outside the chunk range or grades outside ``GRADE_MIN..GRADE_MAX``.
    """
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return {}
    entries = data.get("grades") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return {}
    out: dict[int, int] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        n, g = e.get("chunk"), e.get("grade")
        if (
            isinstance(n, int)
            and not isinstance(n, bool)
            and 1 <= n <= chunk_count
            and isinstance(g, int)
            and not isinstance(g, bool)
            and GRADE_MIN <= g <= GRADE_MAX
        ):
            out[n] = g
    return out


async def ai_judge_chunks(
    llm: AnalysisLlmService,
    query: str,
    chunks: list[AiJudgeChunk],
    *,
    instructions: str | None = None,
) -> tuple[dict[str, int], LlmUsageInfo]:
    """Grade each chunk's relevance to ``query`` with the LLM. Returns ``{chunk_id: grade}``.

    Chunks the model omits or returns an invalid grade for are simply absent from the result
    (the caller leaves them unjudged), so a partial response never invents grades.
    """
    system = (instructions or DEFAULT_AI_JUDGE_INSTRUCTIONS).strip()
    content, usage = await llm.tracked_chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": _build_user_prompt(query, chunks)},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    by_number = _parse_grades(content, len(chunks))
    grades = {chunks[n - 1].chunk_id: g for n, g in by_number.items()}
    return grades, usage
