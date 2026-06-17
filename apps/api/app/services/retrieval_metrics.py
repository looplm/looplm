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

These three are robust to retrieval order: they only depend on *which* URLs fall
inside the top-k slice, not their arrangement within it.

MRR and nDCG are intentionally not implemented yet: they weight by rank position,
which requires the retrieved list to be ordered by relevance. That holds for the
structured ``sources`` path but not the regex fallback in
``extract_retrieved_urls``. Verify rank order against real payloads before adding
them.
"""

from __future__ import annotations

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
