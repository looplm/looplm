"""Build the chunk-labeling view for a dataset's test cases.

Labeling operates on a :class:`TestDataset`'s test cases (a query + ``test_id``). The chunks
to judge are pooled live from the connected index per case (see :mod:`app.services.chunk_pool`),
so the per-case skeleton here carries only the query; this module layers in any existing human
labels, status and AI judgments, keyed by ``test_id``.
"""

from __future__ import annotations

from typing import Iterable

from app.models.datasets import TestCase
from app.schemas.retrieval import (
    LabelingCase,
    LabelingPoolResponse,
    LabelingQueries,
    LabelingRunResponse,
    PooledChunkForLabeling,
)
from app.services.chunk_pool import PoolResult


def build_labeling_cases(test_cases: Iterable[TestCase]) -> tuple[list[LabelingCase], int]:
    """Build the per-case skeleton (query only, no chunks) from a dataset's test cases.

    Dedupes by ``test_id`` (first wins) and carries just the query — the chunks to judge are
    pooled live per case, not stored on the case. User-independent and cheap, so it's safe to
    rebuild on every request. Labels, status and the labeler list are layered on by
    :func:`merge_labeling_view`.
    """
    cases: list[LabelingCase] = []
    seen: set[str] = set()
    for tc in test_cases:
        tid = tc.test_id
        if not tid or tid in seen:
            continue
        seen.add(tid)
        cases.append(
            LabelingCase(test_id=tid, input=(tc.prompt or None) and str(tc.prompt)[:300])
        )
    return cases, len(seen)


def merge_labeling_view(
    cases: list[LabelingCase],
    total_cases: int,
    labels_by_key: dict[tuple[str, str], int],
    *,
    dataset_id: str | None = None,
    dataset_name: str | None = None,
    datasets: list | None = None,
    complete_by_test: dict[str, bool] | None = None,
    slice_by_test: dict[str, str] | None = None,
    labelers_by_test: dict[str, list[str]] | None = None,
) -> LabelingRunResponse:
    """Layer per-user label counts and per-case status onto a case skeleton.

    The chunks themselves are loaded per case from the pool endpoint, so here we only derive
    the per-case summary. ``labels_by_key`` maps ``(test_id, chunk_id) -> graded relevance``
    scoped to the viewing user; ``labeled_count`` is how many distinct chunks that user has
    graded for the case and ``relevant_count`` how many of those are relevant (grade >= 1).
    ``labelers_by_test`` lists every annotator (humans + the AI judge) who has judged any chunk
    in the case; ``complete_by_test`` / ``slice_by_test`` carry the per-case status.
    """
    complete_by_test = complete_by_test or {}
    slice_by_test = slice_by_test or {}
    labelers_by_test = labelers_by_test or {}

    # Per-case label tallies from the viewer's own labels (test_id -> [grades]).
    grades_by_test: dict[str, list[int]] = {}
    for (tid, _chunk_id), grade in labels_by_key.items():
        grades_by_test.setdefault(tid, []).append(grade)

    out: list[LabelingCase] = []
    for c in cases:
        grades = grades_by_test.get(c.test_id, [])
        out.append(
            c.model_copy(
                update={
                    "labeled_count": len(grades),
                    "relevant_count": sum(1 for g in grades if g >= 1),
                    "complete": bool(complete_by_test.get(c.test_id)),
                    "slice": slice_by_test.get(c.test_id),
                    "labelers": labelers_by_test.get(c.test_id, []),
                }
            )
        )

    # Incomplete first, then least-labeled, so a human always lands on unfinished work.
    out.sort(key=lambda c: (c.complete, c.labeled_count, c.test_id))

    return LabelingRunResponse(
        available=bool(out),
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        datasets=datasets or [],
        total_cases=total_cases,
        labelable_cases=len(out),
        cases=out,
    )


def build_labeling_view(
    test_cases: Iterable[TestCase],
    labels_by_key: dict[tuple[str, str], int],
    *,
    dataset_id: str | None = None,
    dataset_name: str | None = None,
    datasets: list | None = None,
    complete_by_test: dict[str, bool] | None = None,
    slice_by_test: dict[str, str] | None = None,
    labelers_by_test: dict[str, list[str]] | None = None,
) -> LabelingRunResponse:
    """Build the labeling view straight from a dataset's test cases: skeleton + label merge."""
    cases, total_cases = build_labeling_cases(test_cases)
    return merge_labeling_view(
        cases,
        total_cases,
        labels_by_key,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        datasets=datasets,
        complete_by_test=complete_by_test,
        slice_by_test=slice_by_test,
        labelers_by_test=labelers_by_test,
    )


# Head priority for ordering the pool: the semantic reranker is the system's final ranking, then
# hybrid (RRF), then vector, then keyword, then agentic. A chunk sorts by the best (highest-
# priority) head that returned it, at that head's rank — so reranked chunks lead, in reranked
# order, and chunks only an agentic sub-query surfaced sort last (by their agentic rank).
_POOL_ORDER_HEADS = ("semantic", "hybrid", "vector", "keyword", "agentic")


def _pool_order_key(ranks: dict[str, int]) -> tuple[int, int]:
    for priority, head in enumerate(_POOL_ORDER_HEADS):
        if head in ranks:
            return (priority, ranks[head])
    return (len(_POOL_ORDER_HEADS), 0)  # heads we don't rank on (e.g. trace) sort last


def build_pool_view(
    test_id: str,
    input_text: str | None,
    pool: PoolResult,
    *,
    provider_connected: bool,
    labels_by_key: dict[tuple[str, str], int],
    labeler_by_key: dict[tuple[str, str], str] | None = None,
    ai_labels_by_key: dict[tuple[str, str], int] | None = None,
    computed_at: str | None = None,
    queries: LabelingQueries | None = None,
) -> LabelingPoolResponse:
    """Shape an assembled :class:`PoolResult` into the labeling-pool API response.

    Overlays any existing human label (and labeler) onto each pooled chunk, keyed by
    ``(test_id, chunk_id)``. Chunks are ordered reranked-first: by the rank the semantic reranker
    gave them, falling back to hybrid → vector → keyword → agentic for chunks a higher-priority
    head didn't return — so the list mirrors the system's true final ranking, with judged-relevant
    candidates near the top. ``queries`` carries the base question and any agentic sub-queries that
    were run, so the UI can show exactly what was sent to the index.
    """
    labeler_by_key = labeler_by_key or {}
    ai_labels_by_key = ai_labels_by_key or {}
    chunks: list[PooledChunkForLabeling] = []
    for pc in sorted(pool.chunks, key=lambda c: _pool_order_key(c.ranks)):
        key = (test_id, pc.chunk_id)
        chunks.append(
            PooledChunkForLabeling(
                chunk_id=pc.chunk_id,
                title=pc.title,
                url=pc.url,
                content_preview=pc.content_preview,
                score=pc.score,
                provenance=pc.provenance,
                ranks=pc.ranks,
                agentic_queries=pc.agentic_queries,
                relevance=labels_by_key.get(key),
                labeled_by=labeler_by_key.get(key),
                ai_relevance=ai_labels_by_key.get(key),
            )
        )
    return LabelingPoolResponse(
        test_id=test_id,
        input=input_text,
        provider_connected=provider_connected,
        pool_size=len(chunks),
        heads_ran=pool.heads_ran,
        heads_failed=pool.heads_failed,
        chunks=chunks,
        computed_at=computed_at,
        queries=queries,
    )
