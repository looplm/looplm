"""Generate synthetic evaluation questions from indexed chunks.

The technique: for every sampled chunk, ask an LLM to write questions that chunk answers.
The chunk it was written from *is* the ground truth, by construction, so a labeled retrieval
benchmark falls out with no human labeling and no production traffic. Scoring it afterwards is
pure retrieval (no LLM in the loop), which is what makes iterating on chunking, embedding
models and search modes fast.

Two things decide whether the resulting benchmark is honest rather than flattering:

* **Which chunks are used.** A fragment, a bare heading or a mojibake chunk yields a question
  no retriever should be graded on. Junk is filtered deterministically with ``score_chunk``
  before an LLM ever sees it, and what was dropped is reported rather than swallowed.
* **How the questions are worded.** A question that reuses the chunk's exact terminology is
  trivially found by BM25, which makes every retriever look good and makes the keyword-vs-vector
  comparison meaningless. So each chunk yields a ``factual`` question (its own terms allowed)
  *and* ``paraphrase`` questions that deliberately avoid them.

This module is deliberately free of DB and provider IO — it takes chunks in and returns
questions out — so it can be unit-tested without an index or a database.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable, Sequence

from app.index_providers.chunk_quality_common import (
    ChunkFlags,
    as_text,
    jaccard,
    normalize_text,
    pick_field,
    score_chunk,
    shingles,
    words,
)
from app.models.synthetic_questions import STYLE_VALUES
from app.services.analysis_llm import AnalysisLlmService, LlmUsageInfo
from app.services.chunk_judge_common import (
    AiJudgeChunk,
    add_usage,
    batch_chunks,
    clean,
    empty_usage,
    extract_json_object,
)

logger = logging.getLogger(__name__)

# How many generation calls run at once. Matches the retrieval probes' concurrency: high enough
# that a 200-chunk run finishes in a reasonable time, low enough not to trip provider rate limits.
GENERATION_CONCURRENCY = 4

# Quality flags that disqualify a chunk from producing a question. ``table_heavy`` is deliberately
# NOT here: a table chunk is awkward but genuinely retrievable, and excluding it would hide a real
# part of the corpus from the benchmark. ``missing_embedding`` is also kept — a chunk invisible to
# vector search is exactly the kind of thing this benchmark should expose.
DISQUALIFYING_FLAGS = ("empty", "tiny", "mojibake", "markup_heavy")

# Questions shorter than this are never a real information need (an LLM stub, a stray fragment).
MIN_QUESTION_CHARS = 12

# Near-duplicate threshold over 3-word shingles. Generated questions are short, so the shingle
# sets are small and the measure is coarse; 0.8 catches rewordings of one question without
# collapsing two genuinely different questions about the same chunk.
DUPLICATE_JACCARD = 0.8
QUESTION_SHINGLE_K = 3

# The classic failure mode: a question that only makes sense to someone already looking at the
# chunk. A user asking the assistant has never seen it, so such a question tests nothing.
_ARTIFACT_RE = re.compile(
    r"\b("
    r"this (document|text|chunk|excerpt|passage|section|page|article)"
    r"|the (document|text|chunk|excerpt|passage|above|below)"
    r"|according to the (text|document|passage|excerpt)"
    r"|as (stated|mentioned|described) (above|below|here)"
    r"|dies(em|es|er)? (dokument|text|abschnitt|auszug)"
    r"|laut (dem )?(text|dokument|abschnitt)"
    r"|im (obigen|vorliegenden) (text|dokument|abschnitt)"
    r")\b",
    re.IGNORECASE,
)

# Index field names a chunk's parts may live under, most specific first. Resolved per document
# rather than hardcoded so a non-Azure backend with different field names still works.
_TEXT_FIELDS = ["chunk_text", "content", "text", "body", "page_content"]
_TITLE_FIELDS = ["attachment_filename", "page_title", "title", "name", "filename"]
_URL_FIELDS = ["page_url", "attachment_url", "url", "source_url", "link"]
_ID_FIELDS = ["id", "chunk_id", "key", "doc_id"]


@dataclass
class SourceChunk:
    """One indexed chunk a question can be generated from."""

    chunk_id: str
    text: str
    title: str | None = None
    url: str | None = None

    def preview(self, limit: int = 500) -> str:
        """Short body snapshot, for the label row and the results table."""
        body = clean(self.text)
        return body if len(body) <= limit else body[: limit - 1] + "…"


@dataclass
class GeneratedQuestion:
    """A generated question plus the chunk it is grounded in.

    ``source_chunk_id`` is the ground truth: the chunk that must be retrieved for this question.
    Negative (unanswerable) questions carry ``None`` — see :mod:`synthetic_negatives`.
    """

    text: str
    style: str
    source_chunk_id: str | None = None
    source_title: str | None = None
    source_url: str | None = None
    source_preview: str | None = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "style": self.style,
            "source_chunk_id": self.source_chunk_id,
            "source_title": self.source_title,
            "source_url": self.source_url,
            "source_preview": self.source_preview,
        }


@dataclass
class ChunkSelection:
    """Which sampled chunks are usable, and why the rest were dropped."""

    kept: list[SourceChunk] = field(default_factory=list)
    # flag slug -> how many chunks it disqualified (first disqualifying flag wins)
    skipped: dict[str, int] = field(default_factory=dict)

    @property
    def skipped_total(self) -> int:
        return sum(self.skipped.values())


def chunk_from_document(doc: dict) -> SourceChunk | None:
    """Build a :class:`SourceChunk` from a raw index document, resolving field names.

    Returns None when the document carries no usable key or no text at all — there is nothing
    to ground a question in, and nothing to score a retriever against.
    """
    keys = set(doc.keys())
    id_field = pick_field(keys, _ID_FIELDS)
    text_field = pick_field(keys, _TEXT_FIELDS)
    if not id_field or not text_field:
        return None
    chunk_id = as_text(doc.get(id_field)).strip()
    text = as_text(doc.get(text_field))
    if not chunk_id or not text.strip():
        return None
    title_field = pick_field(keys, _TITLE_FIELDS)
    url_field = pick_field(keys, _URL_FIELDS)
    return SourceChunk(
        chunk_id=chunk_id,
        text=text,
        title=as_text(doc.get(title_field)).strip() or None if title_field else None,
        url=as_text(doc.get(url_field)).strip() or None if url_field else None,
    )


def select_chunks(candidates: Iterable[SourceChunk]) -> ChunkSelection:
    """Drop chunks that cannot yield a fair question, counting each reason.

    Deterministic and LLM-free: the flags come from :func:`score_chunk`, the same thresholds the
    corpus-wide chunk-quality report uses, so "skipped as tiny here" and "flagged as tiny there"
    always agree. Chunks with a duplicate id are collapsed — the same chunk sampled twice would
    otherwise produce two questions with identical ground truth.
    """
    selection = ChunkSelection()
    seen: set[str] = set()
    for chunk in candidates:
        if chunk.chunk_id in seen:
            selection.skipped["duplicate"] = selection.skipped.get("duplicate", 0) + 1
            continue
        seen.add(chunk.chunk_id)
        flags: ChunkFlags = score_chunk(chunk.text)
        disqualifying = next((f for f in DISQUALIFYING_FLAGS if getattr(flags, f)), None)
        if disqualifying:
            selection.skipped[disqualifying] = selection.skipped.get(disqualifying, 0) + 1
            continue
        selection.kept.append(chunk)
    return selection


def style_plan(questions_per_chunk: int) -> list[str]:
    """Styles to request for one chunk: one factual, the rest paraphrased.

    The single factual question anchors the chunk's own vocabulary; every additional question is
    a paraphrase, because paraphrases are what separate a retriever that understands the question
    from one that pattern-matches its words.
    """
    n = max(1, int(questions_per_chunk))
    return ["factual"] + ["paraphrase"] * (n - 1)


SYSTEM_PROMPT = (
    "You are building a retrieval benchmark for a knowledge assistant. You are given numbered "
    "excerpts from a search index; each excerpt is exactly ONE indexed chunk. For each excerpt, "
    "write questions a real user of the assistant would ask that THAT excerpt answers.\n\n"
    "Hard rules:\n"
    "1. Each question must be answerable from its own excerpt alone. Never combine excerpts.\n"
    "2. Each question must be specific enough that its excerpt is the best source for it. Avoid "
    "questions so generic that most of the knowledge base would answer them equally well.\n"
    "3. Never refer to the artifact. No 'according to this document', 'in the excerpt', 'the "
    "section above'. The person asking has never seen the excerpt.\n"
    "4. Write each question in the same language as its excerpt.\n"
    "5. Styles:\n"
    "   - 'factual': may use the excerpt's own terminology.\n"
    "   - 'paraphrase': expresses the same information need in the user's own words, avoiding the "
    "excerpt's distinctive wording wherever a natural synonym exists. This is what stops keyword "
    "search from being flattered by the benchmark, so make the wording genuinely different.\n"
    "6. If an excerpt cannot support such a question, return an EMPTY question list for it. "
    "Excerpts that cannot: fragments that start or end mid-thought, bare headings, navigation or "
    "link lists, boilerplate/disclaimers, and anything whose subject is never named in the "
    "excerpt itself. Returning nothing for an excerpt is always better than returning a weak "
    "question.\n"
    '7. Return STRICT JSON: {"chunks": [{"chunk": 1, "questions": [{"text": "...", '
    '"style": "factual"}]}]}. No prose outside the JSON.'
)


def build_user_prompt(chunks: Sequence[SourceChunk], questions_per_chunk: int) -> str:
    """Numbered excerpts plus the per-excerpt style quota, as one user message."""
    plan = style_plan(questions_per_chunk)
    factual = plan.count("factual")
    paraphrase = plan.count("paraphrase")
    quota = f"{factual} factual"
    if paraphrase:
        quota += f" and {paraphrase} paraphrase"

    lines = [
        f"For each excerpt below produce at most {len(plan)} questions: {quota}.",
        "",
        "Excerpts:",
    ]
    for i, chunk in enumerate(chunks, start=1):
        header = f"[{i}]"
        if chunk.title:
            header += f" ({chunk.title})"
        # Chunks go out whole. A chunk is already a bounded retrieval unit, and truncating it
        # would have the model write questions about text the retriever will never be scored on.
        lines.append(f"\n{header}\n{clean(chunk.text)}")
    lines.append("\nReturn the JSON object now.")
    return "\n".join(lines)


def parse_questions(
    content: str, chunks: Sequence[SourceChunk], questions_per_chunk: int
) -> list[GeneratedQuestion]:
    """Parse one batch response into questions, dropping anything unusable.

    Tolerant by design: ``analysis_llm`` silently retries without ``response_format`` when the
    provider rejects it, so the response is not guaranteed to be bare JSON. Entries referencing
    an out-of-range excerpt, empty/stub questions, and questions that talk about the excerpt as
    an artifact are all discarded rather than allowed to pollute the dataset.
    """
    data = extract_json_object(content)
    entries = data.get("chunks") if data else None
    if not isinstance(entries, list):
        logger.warning("Synthetic question batch returned no parsable 'chunks' array")
        return []

    allowed_styles = {s for s in STYLE_VALUES if s != "negative"}
    out: list[GeneratedQuestion] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        n = entry.get("chunk")
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= len(chunks):
            continue
        chunk = chunks[n - 1]
        raw_questions = entry.get("questions")
        if not isinstance(raw_questions, list):
            continue
        kept = 0
        for q in raw_questions:
            if kept >= max(1, questions_per_chunk):
                break
            if not isinstance(q, dict):
                continue
            text = str(q.get("text") or "").strip()
            if len(text) < MIN_QUESTION_CHARS or _ARTIFACT_RE.search(text):
                continue
            style = str(q.get("style") or "").strip().lower()
            out.append(
                GeneratedQuestion(
                    text=text,
                    style=style if style in allowed_styles else "factual",
                    source_chunk_id=chunk.chunk_id,
                    source_title=chunk.title,
                    source_url=chunk.url,
                    source_preview=chunk.preview(),
                )
            )
            kept += 1
    return out


def dedupe_questions(
    questions: Sequence[GeneratedQuestion],
) -> tuple[list[GeneratedQuestion], int]:
    """Drop repeated questions, returning ``(kept, dropped_count)``.

    Two chunks covering the same topic reliably produce the same question, and a duplicate
    question with a *different* gold chunk is worse than useless: whichever chunk the retriever
    returns, one of the two cases is scored as a miss. Exact matches go first, then near
    matches by shingle overlap.
    """
    kept: list[GeneratedQuestion] = []
    seen_exact: set[str] = set()
    seen_shingles: list[set[str]] = []
    dropped = 0

    for q in questions:
        norm = normalize_text(q.text)
        if norm in seen_exact:
            dropped += 1
            continue
        sh = shingles(words(norm), k=QUESTION_SHINGLE_K)
        if any(jaccard(sh, prev) >= DUPLICATE_JACCARD for prev in seen_shingles):
            dropped += 1
            continue
        seen_exact.add(norm)
        seen_shingles.append(sh)
        kept.append(q)
    return kept, dropped


async def generate_questions(
    llm: AnalysisLlmService,
    chunks: Sequence[SourceChunk],
    questions_per_chunk: int,
    *,
    on_progress: Callable[[int], Awaitable[None]] | None = None,
    concurrency: int = GENERATION_CONCURRENCY,
) -> tuple[list[GeneratedQuestion], LlmUsageInfo]:
    """Draft questions for every chunk, in token-budgeted batches run concurrently.

    ``on_progress`` is awaited with the number of chunks finished after each batch, so the run
    row's counter tracks real work rather than a guess. A batch that fails is logged and skipped:
    losing one batch's questions is much better than losing the whole run.
    """
    usage = empty_usage()
    if not chunks:
        return [], usage

    system = SYSTEM_PROMPT
    # Reuse the judges' greedy packer so a batch never exceeds the model's context window. It
    # partitions the list in order, so the batch sizes alone map the result back onto ``chunks``
    # (mapping by chunk_id would break on a repeated id).
    judge_chunks = [AiJudgeChunk(chunk_id=c.chunk_id, text=c.text) for c in chunks]
    batches: list[list[SourceChunk]] = []
    cursor = 0
    for packed in batch_chunks(judge_chunks, fixed_texts=(system, "")):
        batches.append(list(chunks[cursor : cursor + len(packed)]))
        cursor += len(packed)

    sem = asyncio.Semaphore(max(1, concurrency))
    lock = asyncio.Lock()
    results: list[list[GeneratedQuestion]] = [[] for _ in batches]

    async def _run_batch(index: int, batch: list[SourceChunk]) -> None:
        async with sem:
            try:
                content, one_usage = await llm.tracked_chat_completion(
                    messages=[
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": build_user_prompt(batch, questions_per_chunk),
                        },
                    ],
                    temperature=0.4,
                    response_format={"type": "json_object"},
                )
            except Exception:  # noqa: BLE001 — one lost batch must not lose the whole run
                logger.exception("Synthetic question generation failed for a batch of %d", len(batch))
                if on_progress is not None:
                    await on_progress(len(batch))
                return
            async with lock:
                add_usage(usage, one_usage)
            results[index] = parse_questions(content, batch, questions_per_chunk)
            if on_progress is not None:
                await on_progress(len(batch))

    await asyncio.gather(*(_run_batch(i, b) for i, b in enumerate(batches)))
    return [q for batch_result in results for q in batch_result], usage
