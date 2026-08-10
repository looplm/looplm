"""Generate and verify unanswerable ("negative") synthetic questions.

A benchmark made only of answerable questions cannot tell you whether the assistant knows when
to stop. Negatives are questions a user of *this* knowledge base would plausibly ask, in the
same domain and register, that the corpus does not answer.

The catch is that an LLM asked to invent an unanswerable question is guessing about a corpus it
has only seen a few excerpts of, and it guesses wrong often. An "unanswerable" question that the
index actually answers is worse than no negative at all: it teaches the reviewer to distrust the
dataset. So every candidate is checked against the live index before it is kept — retrieve the
top hits, then ask the model whether any of them answers it, and discard the ones that do.

What negatives do and do not measure: they carry no gold chunk, so the retrieval metrics exclude
them by design (they are tagged ``no-retrieval-expected``). Their value is the end-to-end eval
run (does the assistant say it does not know?) and the reranker's score-threshold sweep.
"""

from __future__ import annotations

import logging
from typing import Sequence

from app.index_providers.base import BaseIndexProvider
from app.services.analysis_llm import AnalysisLlmService, LlmUsageInfo
from app.services.chunk_judge_common import (
    add_usage,
    clean,
    empty_usage,
    extract_json_object,
)
from app.services.query_embedding import QueryEmbedder, embed_query_with
from app.services.synthetic_questions import (
    MIN_QUESTION_CHARS,
    GeneratedQuestion,
    SourceChunk,
)

logger = logging.getLogger(__name__)

# How many chunks are shown as domain context when drafting negatives. Enough to establish the
# subject matter and register, few enough to keep this to one cheap call.
TOPIC_SAMPLE_SIZE = 12

# How deep the index is searched when checking whether a "negative" is actually answerable.
VERIFY_DEPTH = 5

NEGATIVE_SYSTEM_PROMPT = (
    "You are building the negative half of a retrieval benchmark for a knowledge assistant. You "
    "are given excerpts that show what subject matter the knowledge base covers. Write questions "
    "that this assistant's users would plausibly ask, in the same domain and language, that the "
    "knowledge base most likely CANNOT answer.\n\n"
    "Hard rules:\n"
    "1. Stay in the domain. A question about an unrelated subject is trivially unanswerable and "
    "tests nothing; the useful negative is the near miss.\n"
    "2. Prefer questions just outside what the excerpts cover: a neighbouring topic, a level of "
    "detail the material stops short of, a specific case the general guidance does not address.\n"
    "3. Never refer to the excerpts or to any document. The person asking has seen none of it.\n"
    "4. Write in the same language as the excerpts.\n"
    "5. Do not invent fake entities, product names or identifiers. A question about something "
    "that does not exist is unanswerable for the wrong reason.\n"
    '6. Return STRICT JSON: {"questions": [{"text": "..."}]}. No prose outside the JSON.'
)

VERIFY_SYSTEM_PROMPT = (
    "You are checking candidate questions for a retrieval benchmark. Each candidate is supposed "
    "to be UNANSWERABLE from the knowledge base. For each one you are shown the passages the "
    "search index returned for it.\n\n"
    "For each candidate decide: do the passages actually answer the question?\n"
    "answerable = true: a passage contains the information the question asks for, even partially. "
    "When in doubt, answer true — a candidate wrongly discarded costs nothing, a wrong negative "
    "corrupts the benchmark.\n"
    "answerable = false: the passages are about neighbouring topics but none supplies the "
    "requested information.\n"
    '\nReturn STRICT JSON: {"verdicts": [{"candidate": 1, "answerable": true}]}. No prose.'
)


def build_negative_user_prompt(chunks: Sequence[SourceChunk], count: int) -> str:
    """Domain-context excerpts plus the requested number of negatives, as one user message."""
    lines = [
        f"Write {count} questions the knowledge base most likely cannot answer.",
        "",
        "Excerpts showing what the knowledge base covers:",
    ]
    for i, chunk in enumerate(chunks, start=1):
        header = f"[{i}]"
        if chunk.title:
            header += f" ({chunk.title})"
        lines.append(f"\n{header}\n{clean(chunk.text)}")
    lines.append("\nReturn the JSON object now.")
    return "\n".join(lines)


def parse_negatives(content: str, count: int) -> list[GeneratedQuestion]:
    """Parse the negatives response, dropping stubs and capping at ``count``."""
    data = extract_json_object(content)
    entries = data.get("questions") if data else None
    if not isinstance(entries, list):
        logger.warning("Negative generation returned no parsable 'questions' array")
        return []
    out: list[GeneratedQuestion] = []
    for entry in entries:
        if len(out) >= max(0, count):
            break
        text = ""
        if isinstance(entry, dict):
            text = str(entry.get("text") or "").strip()
        elif isinstance(entry, str):
            text = entry.strip()
        if len(text) >= MIN_QUESTION_CHARS:
            out.append(GeneratedQuestion(text=text, style="negative"))
    return out


async def generate_negatives(
    llm: AnalysisLlmService,
    chunks: Sequence[SourceChunk],
    count: int,
) -> tuple[list[GeneratedQuestion], LlmUsageInfo]:
    """Draft ``count`` unanswerable questions from a sample of the corpus, in one call."""
    usage = empty_usage()
    if count <= 0 or not chunks:
        return [], usage
    topic_sample = list(chunks[:TOPIC_SAMPLE_SIZE])
    try:
        content, one_usage = await llm.tracked_chat_completion(
            messages=[
                {"role": "system", "content": NEGATIVE_SYSTEM_PROMPT},
                {"role": "user", "content": build_negative_user_prompt(topic_sample, count)},
            ],
            temperature=0.6,
            response_format={"type": "json_object"},
        )
    except Exception:  # noqa: BLE001 — negatives are one part of the run, not the whole of it
        logger.exception("Negative question generation failed")
        return [], usage
    add_usage(usage, one_usage)
    return parse_negatives(content, count), usage


def parse_verdicts(content: str, count: int) -> dict[int, bool]:
    """Parse the verification response into ``{1-based candidate: answerable}``.

    Candidates missing from the response are absent from the map; the caller treats a missing
    verdict as "answerable", so an unparsable check discards rather than admits.
    """
    data = extract_json_object(content)
    entries = data.get("verdicts") if data else None
    if not isinstance(entries, list):
        return {}
    out: dict[int, bool] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        n, answerable = entry.get("candidate"), entry.get("answerable")
        if (
            isinstance(n, int)
            and not isinstance(n, bool)
            and 1 <= n <= count
            and isinstance(answerable, bool)
        ):
            out[n] = answerable
    return out


async def _retrieve_for(
    provider: BaseIndexProvider,
    embedder: QueryEmbedder | None,
    query: str,
) -> list[str]:
    """Top passages the index returns for ``query``, best effort.

    Tries hybrid first (the ranking a real assistant would see) and falls back to keyword when
    the index has no vector head or no vectorizer, so verification still runs on a keyword-only
    index instead of silently passing everything.
    """
    vector = await embed_query_with(embedder, query)
    for mode in ("hybrid", "keyword"):
        try:
            docs = await provider.search_documents(query, VERIFY_DEPTH, mode=mode, query_vector=vector)
        except Exception:  # noqa: BLE001 — try the next mode, then give up
            continue
        return [clean(d.snippet) for d in docs if d.snippet]
    logger.warning("Could not search the index while verifying a negative candidate")
    return []


async def verify_negatives(
    llm: AnalysisLlmService,
    provider: BaseIndexProvider,
    candidates: Sequence[GeneratedQuestion],
    *,
    embedder: QueryEmbedder | None = None,
) -> tuple[list[GeneratedQuestion], int, LlmUsageInfo]:
    """Drop candidates the index actually answers. Returns ``(kept, dropped, usage)``.

    One retrieval per candidate, then a single LLM call over all of them. A candidate whose
    verdict cannot be determined is dropped, not kept: the whole point of this pass is that an
    unverified negative is not trustworthy.
    """
    usage = empty_usage()
    if not candidates:
        return [], 0, usage

    passages: list[list[str]] = []
    for candidate in candidates:
        passages.append(await _retrieve_for(provider, embedder, candidate.text))

    # Nothing retrieved for any candidate means the index is unreachable, not that every
    # candidate is a good negative. Keep them and let the reviewer decide, rather than silently
    # discarding the entire negative half of the run.
    if not any(passages):
        logger.warning("Negative verification retrieved nothing; keeping candidates unverified")
        return list(candidates), 0, usage

    lines = ["Candidates and what the index returned for each:"]
    for i, (candidate, hits) in enumerate(zip(candidates, passages), start=1):
        lines.append(f"\n[{i}] Question: {candidate.text}")
        if hits:
            for j, hit in enumerate(hits, start=1):
                lines.append(f"  Passage {j}: {hit}")
        else:
            lines.append("  (the index returned nothing)")
    lines.append("\nReturn the JSON object now.")

    try:
        content, one_usage = await llm.tracked_chat_completion(
            messages=[
                {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(lines)},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Negative verification call failed; dropping unverified candidates")
        return [], len(candidates), usage
    add_usage(usage, one_usage)

    verdicts = parse_verdicts(content, len(candidates))
    kept = [c for i, c in enumerate(candidates, start=1) if verdicts.get(i, True) is False]
    return kept, len(candidates) - len(kept), usage
