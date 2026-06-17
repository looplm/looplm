"""Retrieval-quality metrics computed from retrieved vs. expected source URLs.

Recall@k measures how many of a query's expected (ground-truth) URLs appear in
the top-k retrieved URLs. URLs on both sides are passed through
``normalize_source_url`` so Confluence slug trimming (see ``retrieval_config``)
doesn't cause false misses.

MRR and nDCG are intentionally not implemented yet: they depend on the retrieved
list being ordered by relevance, which holds for the structured ``sources`` path
but not the regex fallback in ``extract_retrieved_urls``. Verify rank order
against real payloads before adding them.
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
