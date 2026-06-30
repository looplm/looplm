"""LLM query planner for agentic retrieval pooling.

Given a test case's question, an LLM decomposes it into several focused, single-aspect search
queries — mirroring how an agentic RAG app issues multiple targeted searches rather than one
broad one. The planned queries are then run against the index and their hits folded into the
labeling pool (see :mod:`app.services.chunk_pool`), so recall is judged against an agentic
retriever, not just the bare question.

Like the AI judge (:mod:`app.services.chunk_ai_judge`) this routes through
:class:`AnalysisLlmService`, so it inherits the project's configured OpenAI / Azure provider, and
its rubric is editable per run.
"""

from __future__ import annotations

import json
import re

from app.services.analysis_llm import AnalysisLlmService, LlmUsageInfo

# Default cap on planned queries — enough to cover a multi-aspect question without ballooning the
# pool (and the judging effort it costs a human). Matches the reference design's max_queries.
DEFAULT_PLANNER_MAX_QUERIES = 6

# Editable in the request; this is the default rubric. Domain-neutral on purpose (LoopLM is
# multi-tenant): a project with domain rules (e.g. always include a product identifier, exactly
# one aspect per query) sets them as the per-run override.
DEFAULT_QUERY_PLANNER_INSTRUCTIONS = (
    "You are a search query planner for a retrieval system. Given a user's question, break it "
    "into a small set of focused search queries that together cover everything needed to answer "
    "it. Rules:\n"
    "- One aspect or sub-question per query; keep each query short and keyword-rich.\n"
    "- Preserve key entities, identifiers and product names from the question verbatim.\n"
    "- Do not invent facts or add aspects the question does not ask about.\n"
    "- No duplicates or near-duplicates.\n"
    'Return ONLY a JSON object of the form {"queries": ["...", "..."]}. No prose.'
)


def _parse_queries(content: str) -> list[str]:
    """Parse the planner's JSON into a deduped (case-insensitive) list of query strings.

    Tolerates code fences and stray prose by extracting the first JSON object; a malformed or
    empty reply yields an empty list (the caller falls back to the bare question).
    """
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return []
    raw = data.get("queries") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for q in raw:
        if not isinstance(q, str):
            continue
        q = q.strip()
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            out.append(q)
    return out


def _build_user_prompt(question: str) -> str:
    return f"Question:\n{question}\n\nReturn the focused search queries as JSON."


async def plan_queries(
    llm: AnalysisLlmService,
    question: str,
    *,
    instructions: str | None = None,
    max_queries: int = DEFAULT_PLANNER_MAX_QUERIES,
) -> tuple[list[str], LlmUsageInfo]:
    """Decompose ``question`` into focused search queries. Returns ``(queries, usage)``.

    Queries are deduped (case-insensitive) and capped at ``max_queries``. A malformed or empty
    model reply yields no queries — the caller falls back to the bare question — never invents any.
    """
    system = (instructions or DEFAULT_QUERY_PLANNER_INSTRUCTIONS).strip()
    content, usage = await llm.tracked_chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": _build_user_prompt(question)},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    queries = _parse_queries(content)[: max(1, max_queries)]
    return queries, usage
