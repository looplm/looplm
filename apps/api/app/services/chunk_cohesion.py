"""Embedding-space cohesion of chunks — flags multi-topic "smeared" chunks.

A chunk spanning several topics gets an embedding that lands between them and
retrieves poorly for any specific query. That is measurable without labels:
split the chunk into sentences, embed each sentence, and take the mean pairwise
cosine *distance* of the sentence vectors. High spread means the chunk tries to
say too many unrelated things and probably wants splitting.

The vector math is pure Python (a few thousand 3072-float vectors — no numpy
dependency needed); only ``analyze_cohesion`` is async because it embeds.
"""

from __future__ import annotations

import logging
import re

from app.index_providers.chunk_quality_common import (
    Finding,
    as_text,
    distribution,
    pct,
)
from app.services.query_embedding import QueryEmbedder

logger = logging.getLogger(__name__)

# Mean pairwise cosine distance above which a chunk counts as high-spread.
# Sentences of a single-topic chunk in text-embedding-3-class models typically
# sit well below this; unrelated topics land around 0.5+.
HIGH_SPREAD_THRESHOLD = 0.35
# Sentences shorter than this are headings/fragments that would add noise.
_MIN_SENTENCE_CHARS = 20
# A chunk needs at least this many usable sentences for a meaningful spread.
_MIN_SENTENCES = 3
# Embedding API batch size (request-size bound, not a rate limit).
_EMBED_BATCH = 64

_MAX_EXAMPLES = 8
_SNIPPET_CHARS = 140

# Sentence boundary: terminal punctuation followed by whitespace and an
# uppercase/digit start (German nouns capitalize, so this splits DE text well),
# or a hard line break.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÄÖÜ0-9])|\n{2,}|\n(?=[-*•#]|\d+[.)])")


def split_sentences(text: str, max_sentences: int) -> list[str]:
    """Sentence-ish units of ``text``, capped at ``max_sentences``.

    Best-effort regex splitting (abbreviations may over-split; that only adds a
    little noise to the spread, never a systematic bias). Drops fragments under
    ``_MIN_SENTENCE_CHARS``.
    """
    parts = _SENTENCE_SPLIT_RE.split(as_text(text))
    sentences = [p.strip() for p in parts if p and len(p.strip()) >= _MIN_SENTENCE_CHARS]
    return sentences[:max_sentences]


def cosine(a: list[float], b: list[float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / ((norm_a**0.5) * (norm_b**0.5))


def smear_score(vectors: list[list[float]]) -> float:
    """Mean pairwise cosine distance of sentence vectors — 0 tight, higher smeared."""
    n = len(vectors)
    if n < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += 1.0 - cosine(vectors[i], vectors[j])
            pairs += 1
    return round(total / pairs, 4)


async def analyze_cohesion(
    embedder: QueryEmbedder,
    docs: list[dict],
    *,
    text_field: str,
    id_field: str | None,
    sample_size: int,
    max_sentences: int,
    progress_cb=None,
) -> tuple[dict, list[Finding]]:
    """Embed sentence sets for up to ``sample_size`` chunks and score their spread.

    Chunks with fewer than ``_MIN_SENTENCES`` usable sentences are skipped (a
    two-sentence chunk cannot meaningfully smear). Embedding failures abort the
    pass — the caller reports the family unavailable rather than a half-sample.
    """
    candidates: list[tuple[str, str, list[str]]] = []  # (chunk_id, text, sentences)
    for d in docs:
        text = as_text(d.get(text_field))
        sentences = split_sentences(text, max_sentences)
        if len(sentences) >= _MIN_SENTENCES:
            cid = as_text(d.get(id_field)) if id_field else ""
            candidates.append((cid, text, sentences))
        if len(candidates) >= sample_size:
            break

    scored: list[tuple[str, str, float]] = []  # (chunk_id, text, smear)
    sentences_embedded = 0
    for cid, text, sentences in candidates:
        vectors: list[list[float]] = []
        for start in range(0, len(sentences), _EMBED_BATCH):
            vectors.extend(await embedder.embed_batch(sentences[start : start + _EMBED_BATCH]))
        sentences_embedded += len(sentences)
        scored.append((cid, text, smear_score(vectors)))
        if progress_cb is not None:
            await progress_cb(len(scored), len(candidates))

    n = len(scored)
    high = [(cid, text, s) for cid, text, s in scored if s >= HIGH_SPREAD_THRESHOLD]
    high.sort(key=lambda x: -x[2])
    high_pct = pct(len(high), n)

    findings: list[Finding] = []
    if n and high_pct >= 15:
        findings.append(Finding(
            family="cohesion", severity="warn",
            title="Multi-topic chunks",
            message=(
                f"{high_pct}% of scored chunks have high internal embedding spread "
                f"(mean sentence distance ≥ {HIGH_SPREAD_THRESHOLD}) — they mix topics and "
                "their vectors land in no-man's-land."
            ),
            count=len(high),
        ))

    metrics = {
        "available": True,
        "sampled": len(candidates),
        "scored": n,
        "sentences_embedded": sentences_embedded,
        "smear": distribution([s for _, _, s in scored]),
        "high_spread": len(high),
        "high_spread_pct": high_pct,
        "threshold": HIGH_SPREAD_THRESHOLD,
        "examples": [
            {
                "chunk_id": cid,
                "smear": s,
                "snippet": re.sub(r"\s+", " ", text).strip()[:_SNIPPET_CHARS],
            }
            for cid, text, s in high[:_MAX_EXAMPLES]
        ],
    }
    return metrics, findings
