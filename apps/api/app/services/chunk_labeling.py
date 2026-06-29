"""Build the chunk-labeling view for an eval run from its captured retrieved chunks.

Each eval result stores the ranked chunks it retrieved (``result_metadata["retrieved_chunks"]``,
populated by the eval executor). This module pairs those with any existing human labels so
the UI can show what was retrieved and which chunks have already been judged.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.models.evaluations import EvalResult
from app.schemas.retrieval import (
    ChunkForLabeling,
    LabelingCase,
    LabelingPoolResponse,
    LabelingRunResponse,
    PooledChunkForLabeling,
)
from app.services.chunk_pool import PoolResult


def build_labeling_cases(results: Iterable[EvalResult]) -> tuple[list[LabelingCase], int]:
    """Build the per-case retrieved-chunk skeleton (no labels merged) plus the total case count.

    This is the heavy, *user-independent* half of the labeling view: it dedupes results by
    ``test_id`` (so each query yields one case; pass results newest-run-first so the most recent
    capture wins) and reads each result's ``retrieved_chunks`` JSON into ranked
    :class:`ChunkForLabeling` rows. It touches no per-user state, so the result is identical for
    every annotator and safe to cache per project. Labels and status are layered on later by
    :func:`merge_labeling_view`.
    """
    result_list = list(results)
    cases: list[LabelingCase] = []
    seen_tests: set[str] = set()

    for r in result_list:
        if r.test_id in seen_tests:
            continue
        meta = r.result_metadata if isinstance(r.result_metadata, dict) else {}
        raw_chunks = meta.get("retrieved_chunks")
        if not isinstance(raw_chunks, list) or not raw_chunks:
            continue

        chunks: list[ChunkForLabeling] = []
        for i, c in enumerate(raw_chunks, start=1):
            if not isinstance(c, dict):
                continue
            pdf_page = c.get("pdf_page_number")
            chunks.append(
                ChunkForLabeling(
                    chunk_id=c.get("chunk_id"),
                    title=c.get("title"),
                    url=c.get("url"),
                    content=c.get("content") or c.get("content_preview"),
                    content_preview=c.get("content_preview"),
                    heading_context=c.get("heading_context"),
                    pdf_page_number=pdf_page if isinstance(pdf_page, int) else None,
                    score=c.get("score") if isinstance(c.get("score"), (int, float)) else None,
                    rank=i,
                )
            )
        if not chunks:
            continue
        seen_tests.add(r.test_id)
        cases.append(
            LabelingCase(
                test_id=r.test_id,
                input=(r.input or None) and str(r.input)[:300],
                chunks=chunks,
            )
        )

    return cases, len({r.test_id for r in result_list})


def merge_labeling_view(
    cases: list[LabelingCase],
    total_cases: int,
    labels_by_key: dict[tuple[str, str], int],
    *,
    run_id: str | None = None,
    run_name: str | None = None,
    labeler_by_key: dict[tuple[str, str], str] | None = None,
    complete_by_test: dict[str, bool] | None = None,
    slice_by_test: dict[str, str] | None = None,
    labelers_by_test: dict[str, list[str]] | None = None,
    ai_labels_by_key: dict[tuple[str, str], int] | None = None,
) -> LabelingRunResponse:
    """Layer per-user labels and per-case status onto a :func:`build_labeling_cases` skeleton.

    This is the cheap, *per-request* half: it never touches the (large) result rows, only the
    small label/status maps, so it's fine to run on every request even when ``cases`` came from
    a cache. ``labels_by_key`` maps ``(test_id, chunk_id) -> graded relevance 0..3`` (scoped to
    the viewing user, so each annotator sees and edits their own judgments). ``labeler_by_key``
    maps the same
    key to the display name of who made the shown label; ``complete_by_test`` is the manual
    "labeling complete" flag; ``slice_by_test`` is the risk slice. ``labelers_by_test`` lists
    *every* annotator who has judged any chunk in a case; when omitted it falls back to the
    labelers of the shown labels.
    """
    labeler_by_key = labeler_by_key or {}
    complete_by_test = complete_by_test or {}
    slice_by_test = slice_by_test or {}
    labelers_by_test = labelers_by_test or {}
    ai_labels_by_key = ai_labels_by_key or {}
    out: list[LabelingCase] = []

    for c in cases:
        labeled = 0
        relevant = 0
        labelers: list[str] = []
        merged_chunks: list[ChunkForLabeling] = []
        for ch in c.chunks:
            key = (c.test_id, ch.chunk_id) if ch.chunk_id else None
            label = labels_by_key.get(key) if key else None
            labeler = labeler_by_key.get(key) if key else None
            ai_label = ai_labels_by_key.get(key) if key else None
            if label is not None:
                labeled += 1
                if label >= 1:  # graded: any non-zero grade counts as relevant
                    relevant += 1
                if labeler and labeler not in labelers:
                    labelers.append(labeler)
            merged_chunks.append(
                ch.model_copy(
                    update={"relevance": label, "labeled_by": labeler, "ai_relevance": ai_label}
                )
            )
        out.append(
            c.model_copy(
                update={
                    "chunks": merged_chunks,
                    "labeled_count": labeled,
                    "relevant_count": relevant,
                    "complete": bool(complete_by_test.get(c.test_id)),
                    "slice": slice_by_test.get(c.test_id),
                    "labelers": labelers_by_test.get(c.test_id, labelers),
                }
            )
        )

    # Incomplete first, then least-labeled, so a human always lands on unfinished work.
    out.sort(key=lambda c: (c.complete, c.labeled_count, c.test_id))

    return LabelingRunResponse(
        available=bool(out),
        run_id=run_id,
        run_name=run_name,
        total_cases=total_cases,
        labelable_cases=len(out),
        cases=out,
    )


def build_labeling_view(
    results: Iterable[EvalResult],
    labels_by_key: dict[tuple[str, str], bool],
    *,
    run_id: str | None = None,
    run_name: str | None = None,
    labeler_by_key: dict[tuple[str, str], str] | None = None,
    complete_by_test: dict[str, bool] | None = None,
    slice_by_test: dict[str, str] | None = None,
    labelers_by_test: dict[str, list[str]] | None = None,
) -> LabelingRunResponse:
    """Build the labeling view straight from results (uncached): cases skeleton + label merge.

    Convenience for the run-scoped path and tests. The cached project-wide path instead calls
    :func:`build_labeling_cases` (cacheable) and :func:`merge_labeling_view` separately.
    """
    cases, total_cases = build_labeling_cases(results)
    return merge_labeling_view(
        cases,
        total_cases,
        labels_by_key,
        run_id=run_id,
        run_name=run_name,
        labeler_by_key=labeler_by_key,
        complete_by_test=complete_by_test,
        slice_by_test=slice_by_test,
        labelers_by_test=labelers_by_test,
    )


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
) -> LabelingPoolResponse:
    """Shape an assembled :class:`PoolResult` into the labeling-pool API response.

    Overlays any existing human label (and labeler) onto each pooled chunk, keyed by
    ``(test_id, chunk_id)`` — so a chunk already judged in any run shows its verdict. Pool
    order is preserved (trace-seeded chunks first, then index-discovered).
    """
    labeler_by_key = labeler_by_key or {}
    ai_labels_by_key = ai_labels_by_key or {}
    chunks: list[PooledChunkForLabeling] = []
    for pc in pool.chunks:
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
    )


def retrieved_chunk_ids(result: EvalResult) -> list[str]:
    """Ranked list of chunk ids a result retrieved (order = retrieval rank)."""
    meta = result.result_metadata if isinstance(result.result_metadata, dict) else {}
    raw: Any = meta.get("retrieved_chunks")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for c in raw:
        if isinstance(c, dict) and isinstance(c.get("chunk_id"), str):
            out.append(c["chunk_id"])
    return out
