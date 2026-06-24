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
