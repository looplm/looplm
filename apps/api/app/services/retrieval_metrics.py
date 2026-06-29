"""Retrieval-quality metrics computed from retrieved vs. expected source URLs.

All metrics here are deterministic set/rank arithmetic over two lists — a query's
expected (ground-truth) URLs and the URLs actually retrieved — so no LLM judge is
involved. URLs on both sides are passed through ``normalize_source_url`` so
Confluence slug trimming (see ``retrieval_config``) doesn't cause false misses.

- Recall@k: fraction of expected URLs that appear in the top-k retrieved.
- Precision@k: fraction of the top-k retrieved that are expected.
- Hit-rate@k: 1.0 if any expected URL appears in the top-k, else 0.0 (per query;
  macro-averaged across a run it becomes the share of queries that landed at
  least one relevant doc).

Recall/precision/hit-rate are robust to retrieval order: they only depend on *which*
URLs fall inside the top-k slice, not their arrangement within it.

MRR and nDCG additionally weight by rank position, so they require the retrieved
list to be ordered by relevance. ``extract_retrieved_urls`` preserves the order of
the structured ``sources`` array (post-rerank rank order in the Azure AI Search
path), which makes the rank-weighted metrics meaningful; on the regex text fallback
the order is best-effort document order, so treat MRR/nDCG as indicative there.
"""

from __future__ import annotations

import math
from typing import Iterable

from app.services.retrieval_config import normalize_source_url

DEFAULT_KS: tuple[int, ...] = (5, 10)


def _normalize_unique(urls: list[str]) -> list[str]:
    """Normalize URLs and drop blanks/duplicates, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if not isinstance(url, str):
            continue
        norm = normalize_source_url(url.strip())
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def compute_recall_at_k(
    expected: list[str], retrieved: list[str], ks: tuple[int, ...] = DEFAULT_KS
) -> dict[str, float] | None:
    """Recall@k for each k in ``ks``.

    Recall@k is the fraction of a query's expected (ground-truth) URLs that
    appear in the top-k retrieved URLs. ``retrieved`` is assumed to be in rank
    order (as returned by ``extract_retrieved_urls``).

    Returns ``None`` when there are no expected URLs — recall is undefined with
    nothing to recall, and the caller should skip rather than record a zero.
    Keys are stringified k values so the result is JSON-serializable.
    """
    relevant = set(_normalize_unique(expected))
    if not relevant:
        return None
    ranked = _normalize_unique(retrieved)
    return {
        str(k): len(relevant.intersection(ranked[:k])) / len(relevant)
        for k in ks
    }


def compute_precision_at_k(
    expected: list[str], retrieved: list[str], ks: tuple[int, ...] = DEFAULT_KS
) -> dict[str, float] | None:
    """Precision@k for each k in ``ks``.

    Precision@k is the fraction of the top-k retrieved URLs that are expected
    (ground-truth). It is divided by ``k`` — the cutoff — not by the number of
    URLs actually retrieved, which is the standard definition: returning fewer
    than k results still dilutes precision.

    Returns ``None`` when there are no expected URLs — with no ground truth there
    is nothing to call relevant, so the caller should skip rather than record a
    zero. Keys are stringified k values so the result is JSON-serializable.
    """
    relevant = set(_normalize_unique(expected))
    if not relevant:
        return None
    ranked = _normalize_unique(retrieved)
    return {
        str(k): len(relevant.intersection(ranked[:k])) / k
        for k in ks
    }


def compute_hit_rate_at_k(
    expected: list[str], retrieved: list[str], ks: tuple[int, ...] = DEFAULT_KS
) -> dict[str, float] | None:
    """Hit-rate@k for each k in ``ks``.

    Per query, hit-rate@k is 1.0 if at least one expected URL appears in the
    top-k retrieved, else 0.0. Macro-averaged across a run (see
    ``eval_helpers``) it becomes the fraction of queries where retrieval surfaced
    at least one relevant doc.

    Returns ``None`` when there are no expected URLs — there is nothing to hit, so
    the caller should skip rather than record a zero. Keys are stringified k
    values so the result is JSON-serializable.
    """
    relevant = set(_normalize_unique(expected))
    if not relevant:
        return None
    ranked = _normalize_unique(retrieved)
    return {
        str(k): 1.0 if relevant.intersection(ranked[:k]) else 0.0
        for k in ks
    }


def compute_mrr(expected: list[str], retrieved: list[str]) -> float | None:
    """Reciprocal rank of the first relevant retrieved URL.

    ``1 / rank`` of the first retrieved URL that is in the expected set (rank
    1-indexed), or ``0.0`` if no relevant URL was retrieved. Rank-sensitive, so it
    rewards surfacing a relevant doc *early*. Returns ``None`` when there are no
    expected URLs (nothing to rank against).
    """
    rank = compute_first_relevant_rank(expected, retrieved)
    if rank is None and not _normalize_unique(expected):
        return None
    return 1.0 / rank if rank else 0.0


def compute_first_relevant_rank(
    expected: list[str], retrieved: list[str]
) -> int | None:
    """1-indexed rank of the first relevant retrieved URL, or ``None`` if none.

    ``None`` also when there are no expected URLs. Used for per-case drill-down
    ("how deep did the user have to look before hitting a relevant doc").
    """
    relevant = set(_normalize_unique(expected))
    if not relevant:
        return None
    for i, url in enumerate(_normalize_unique(retrieved), start=1):
        if url in relevant:
            return i
    return None


def compute_ndcg_at_k(
    expected: list[str], retrieved: list[str], ks: tuple[int, ...] = DEFAULT_KS
) -> dict[str, float] | None:
    """Normalized discounted cumulative gain at k, with binary relevance.

    DCG@k discounts each relevant hit by ``1 / log2(rank + 1)`` (rank 1-indexed) and
    is normalized by the ideal DCG (all relevant docs packed at the top). 1.0 means
    every relevant doc sits as high as it possibly could within the top-k; lower
    values mean relevant docs are buried beneath irrelevant ones.

    Returns ``None`` when there are no expected URLs. Keys are stringified k values
    so the result is JSON-serializable.
    """
    relevant = set(_normalize_unique(expected))
    if not relevant:
        return None
    ranked = _normalize_unique(retrieved)
    out: dict[str, float] = {}
    for k in ks:
        dcg = sum(
            1.0 / math.log2(i + 1)
            for i, url in enumerate(ranked[:k], start=1)
            if url in relevant
        )
        ideal_hits = min(len(relevant), k)
        idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
        out[str(k)] = dcg / idcg if idcg > 0 else 0.0
    return out


# --- Incomplete-judgment-safe metrics --------------------------------------------
#
# Recall/precision/nDCG above assume the ground truth is complete: any retrieved doc
# not in the relevant set counts as a miss. That holds for the URL path (expected_sources
# is curated) but breaks for *pooled chunk labels*, where most retrieved chunks in a fresh
# run are simply *unjudged* — neither confirmed relevant nor confirmed irrelevant. Scoring
# unjudged as irrelevant punishes retrieval for surfacing things nobody has labeled yet.
#
# bpref and condensed nDCG fix this by operating only over the *judged* set (relevant +
# judged-non-relevant): unjudged retrieved docs are dropped from the ranking before scoring
# rather than penalized. They take chunk ids (opaque keys), so — unlike the URL metrics —
# they are *not* run through ``normalize_source_url``.


def compute_bpref(
    relevant: Iterable[str],
    judged_nonrelevant: Iterable[str],
    retrieved: list[str],
) -> float | None:
    """Binary preference (Buckley & Voorhees 2004) — robust to incomplete judgments.

    ``bpref = (1/R) Σ_r (1 − min(n_above_r, denom) / denom)`` where R is the number of
    judged-relevant docs for the query, n_above_r the count of judged-non-relevant docs
    ranked above relevant doc ``r``, and ``denom = min(R, N)`` with N the judged-non-relevant
    count. Unjudged retrieved docs are skipped (neither rewarded nor penalized). Relevant
    docs never retrieved contribute 0, so bpref still drops when recall is poor. When there
    are no judged-non-relevant docs (N=0) the penalty term vanishes and bpref reduces to the
    fraction of relevant docs retrieved.

    Returns ``None`` when there are no judged-relevant docs (nothing to measure).
    """
    rel = set(relevant)
    if not rel:
        return None
    nonrel = set(judged_nonrelevant) - rel  # a chunk can't be both; relevant wins
    R = len(rel)
    denom = min(R, len(nonrel))

    seen: set[str] = set()
    nonrel_above = 0
    total = 0.0
    for cid in retrieved:
        if cid in seen:
            continue
        seen.add(cid)
        if cid in rel:
            total += 1.0 - (min(nonrel_above, denom) / denom if denom else 0.0)
        elif cid in nonrel:
            nonrel_above += 1
        # unjudged → ignored
    return total / R


def compute_graded_ndcg_at_k(
    gains: dict[str, float],
    retrieved: list[str],
    ks: tuple[int, ...] = DEFAULT_KS,
) -> dict[str, float] | None:
    """nDCG@k with *graded* gains — gain(doc) = its relevance grade (1..3), not a flat 1.

    For the chunk-label path: ``gains`` maps a judged-relevant chunk id to its gold grade, so a
    highly-relevant chunk ranked first scores higher than a marginally-relevant one in the same
    slot, and the ideal DCG packs the highest grades at the top. Keys are opaque chunk ids, so
    — like bpref / condensed nDCG — they are NOT run through ``normalize_source_url``.

    Returns ``None`` when there are no graded-relevant docs. Keys are stringified k values.
    """
    if not gains:
        return None
    seen: set[str] = set()
    ranked: list[str] = []
    for cid in retrieved:
        if cid not in seen:
            seen.add(cid)
            ranked.append(cid)
    ideal = sorted(gains.values(), reverse=True)
    out: dict[str, float] = {}
    for k in ks:
        dcg = sum(
            gains.get(cid, 0.0) / math.log2(i + 1)
            for i, cid in enumerate(ranked[:k], start=1)
        )
        idcg = sum(g / math.log2(i + 1) for i, g in enumerate(ideal[:k], start=1))
        out[str(k)] = dcg / idcg if idcg > 0 else 0.0
    return out


def compute_condensed_ndcg_at_k(
    relevant: Iterable[str],
    judged_nonrelevant: Iterable[str],
    retrieved: list[str],
    ks: tuple[int, ...] = DEFAULT_KS,
    gains: dict[str, float] | None = None,
) -> dict[str, float] | None:
    """nDCG@k over the *condensed* ranking — unjudged docs removed before scoring.

    Same nDCG as :func:`compute_ndcg_at_k`, but the retrieved list is first condensed to judged
    docs only (relevant ∪ judged-non-relevant), so an unjudged chunk sitting at rank 2 doesn't
    push a relevant chunk down to rank 3 in the discount. This is the inferred/condensed-nDCG
    idea (Sakai 2007) for incomplete pools. When ``gains`` is given the relevant docs are scored
    by their graded gain (gain = grade); otherwise relevance is binary (gain 1).

    Returns ``None`` when there are no judged-relevant docs. Keys are stringified k values.
    """
    rel = set(relevant)
    if not rel:
        return None
    judged = rel | set(judged_nonrelevant)

    seen: set[str] = set()
    condensed: list[str] = []
    for cid in retrieved:
        if cid in judged and cid not in seen:
            seen.add(cid)
            condensed.append(cid)

    def gain(cid: str) -> float:
        if gains is not None:
            return gains.get(cid, 0.0)
        return 1.0 if cid in rel else 0.0

    ideal = (
        sorted((gains.get(c, 0.0) for c in rel), reverse=True)
        if gains is not None
        else [1.0] * len(rel)
    )

    out: dict[str, float] = {}
    for k in ks:
        dcg = sum(gain(cid) / math.log2(i + 1) for i, cid in enumerate(condensed[:k], start=1))
        idcg = sum(g / math.log2(i + 1) for i, g in enumerate(ideal[:k], start=1))
        out[str(k)] = dcg / idcg if idcg > 0 else 0.0
    return out


def compute_retrieval_metrics(
    expected: list[str], retrieved: list[str], ks: tuple[int, ...] = DEFAULT_KS
) -> dict | None:
    """All retrieval-quality metrics for one query in a single dict.

    Returns ``None`` when there are no expected URLs (nothing to measure), so callers
    can skip the case rather than record zeros. The dict is JSON-serializable and is
    what the ``contains_urls`` grader stores and the run-level aggregation reads.
    """
    if not _normalize_unique(expected):
        return None
    return {
        "recall_at_k": compute_recall_at_k(expected, retrieved, ks),
        "precision_at_k": compute_precision_at_k(expected, retrieved, ks),
        "hit_rate_at_k": compute_hit_rate_at_k(expected, retrieved, ks),
        "ndcg_at_k": compute_ndcg_at_k(expected, retrieved, ks),
        "mrr": compute_mrr(expected, retrieved),
        "first_relevant_rank": compute_first_relevant_rank(expected, retrieved),
    }
