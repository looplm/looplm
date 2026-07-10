"""LLM "AI judge" for chunk relevance — a one-click second annotator.

Given a test case's query and the chunks it retrieved, the judge grades each chunk on the same
0..3 relevance scale a human uses (see :mod:`app.models.chunk_labels`). Its grades are stored
under the ``AI`` annotator so they show up as a distinct annotator in inter-annotator agreement,
letting a single human reviewer get a Cohen's kappa against the model without a second person.

Chunks go out in FULL, never truncated — a chunk is already a bounded retrieval unit, so cutting
it off would hide the very text the judge needs to grade. To stay under the model's context
window the pool is split into token-budgeted batches (mirroring the retrieval app's
``ChunkRelevanceJudge``) that are graded in separate calls and merged. The judge is
model-agnostic: it routes through :class:`AnalysisLlmService` like the rest of the analysis code,
so it inherits the project's configured OpenAI / Azure provider.
"""

from __future__ import annotations

from app.models.chunk_labels import GRADE_MAX, GRADE_MIN
from app.services.analysis_llm import AnalysisLlmService, LlmUsageInfo
from app.services.chunk_judge_common import (
    AiJudgeChunk,
    add_usage,
    batch_chunks,
    clean,
    empty_usage,
    extract_json_object,
)

__all__ = [
    "AiJudgeChunk",
    "DEFAULT_AI_JUDGE_INSTRUCTIONS",
    "ai_judge_chunks",
    "build_ai_judge_messages",
    "plan_ai_judge_prompts",
]

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


def _batch_chunks(
    system: str, query: str, chunks: list[AiJudgeChunk], *, expected_answer: str | None = None
) -> list[list[AiJudgeChunk]]:
    """Token-budgeted batches for this judge's fixed prompt parts (see ``batch_chunks``)."""
    return batch_chunks(chunks, fixed_texts=(system, query, expected_answer or ""))


_clean = clean


def _build_user_prompt(
    query: str, chunks: list[AiJudgeChunk], *, expected_answer: str | None = None
) -> str:
    lines = [f"Query:\n{query}\n"]
    # Optional reference answer: context that sharpens what "relevant" means for THIS query,
    # without turning the judge into an answer-matcher (a chunk supporting a valid alternative
    # answer is still relevant).
    if expected_answer and expected_answer.strip():
        lines.append(
            "Reference answer (context only — a known-good answer to the query. Use it to judge "
            "whether a chunk supplies the kind of information an answer needs; do NOT require a "
            "chunk to match it, and do NOT penalize a chunk that supports a different but valid "
            "answer):\n"
            f"{expected_answer.strip()}\n"
        )
    lines.append("Chunks:")
    for i, c in enumerate(chunks, start=1):
        body = _clean(c.text) or "(no text)"
        lines.append(f"\n[{i}]\n{body}")
    lines.append(
        f"\nReturn ONLY a JSON object of the form "
        f'{{"grades": [{{"chunk": 1, "grade": 0}}, ...]}}, one entry per chunk number above, '
        f"each grade an integer {GRADE_MIN}..{GRADE_MAX}. No prose."
    )
    return "\n".join(lines)


def build_ai_judge_messages(
    query: str,
    chunks: list[AiJudgeChunk],
    *,
    instructions: str | None = None,
    expected_answer: str | None = None,
) -> list[dict[str, str]]:
    """The exact ``[system, user]`` messages the judge sends for one batch of ``chunks``.

    Shared by :func:`ai_judge_chunks` and the labeling UI's prompt preview, so the text a
    reviewer inspects (rubric + query + optional reference answer + the full chunk text folded in)
    never drifts from what actually runs.
    """
    system = (instructions or DEFAULT_AI_JUDGE_INSTRUCTIONS).strip()
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": _build_user_prompt(query, chunks, expected_answer=expected_answer),
        },
    ]


def plan_ai_judge_prompts(
    query: str,
    chunks: list[AiJudgeChunk],
    *,
    instructions: str | None = None,
    expected_answer: str | None = None,
) -> tuple[str, list[tuple[str, int]]]:
    """Return ``(system_prompt, [(user_prompt, chunk_count) per batch])`` the judge would send.

    Used by the UI preview so a reviewer sees the full, untruncated chunk text and how the pool
    is split across calls — the same batching :func:`ai_judge_chunks` runs.
    """
    system = (instructions or DEFAULT_AI_JUDGE_INSTRUCTIONS).strip()
    batches = _batch_chunks(system, query, chunks, expected_answer=expected_answer)
    return system, [
        (_build_user_prompt(query, b, expected_answer=expected_answer), len(b)) for b in batches
    ]


def _parse_grades(content: str, chunk_count: int) -> dict[int, int]:
    """Parse the judge's JSON into ``{1-based chunk number: grade}``, dropping anything invalid.

    Tolerates code fences and stray prose by extracting the first JSON object; ignores numbers
    outside the chunk range or grades outside ``GRADE_MIN..GRADE_MAX``.
    """
    data = extract_json_object(content)
    entries = data.get("grades") if data else None
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
    expected_answer: str | None = None,
) -> tuple[dict[str, int], LlmUsageInfo]:
    """Grade each chunk's relevance to ``query`` with the LLM. Returns ``{chunk_id: grade}``.

    Chunks go out in full; the pool is split into context-budgeted batches, each graded in its
    own call, and the grades are merged. Chunks the model omits or returns an invalid grade for
    are simply absent from the result (the caller leaves them unjudged), so a partial response
    never invents grades. ``expected_answer``, when given, is folded into each user message as
    context (never as a match target) so the judge can weigh what an answer actually needs.
    """
    system = (instructions or DEFAULT_AI_JUDGE_INSTRUCTIONS).strip()
    batches = _batch_chunks(system, query, chunks, expected_answer=expected_answer)

    grades: dict[str, int] = {}
    usage = empty_usage()
    for batch in batches:
        content, batch_usage = await llm.tracked_chat_completion(
            messages=build_ai_judge_messages(
                query, batch, instructions=instructions, expected_answer=expected_answer
            ),
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        add_usage(usage, batch_usage)
        for n, g in _parse_grades(content, len(batch)).items():
            grades[batch[n - 1].chunk_id] = g
    return grades, usage
