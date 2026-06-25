"""Build the chunk-labeling view for an eval run from its captured retrieved chunks.

Each eval result stores the ranked chunks it retrieved (``result_metadata["retrieved_chunks"]``,
populated by the eval executor). This module pairs those with any existing human labels so
the UI can show what was retrieved and which chunks have already been judged.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.models.evaluations import EvalResult, EvalRun
from app.schemas.retrieval import (
    ChunkForLabeling,
    LabelingCase,
    LabelingPoolResponse,
    LabelingRunResponse,
    PooledChunkForLabeling,
)
from app.services.chunk_pool import PoolResult


def build_labeling_view(
    run: EvalRun,
    results: Iterable[EvalResult],
    labels_by_key: dict[tuple[str, str], bool],
    *,
    labeler_by_key: dict[tuple[str, str], str] | None = None,
    complete_by_test: dict[str, bool] | None = None,
    slice_by_test: dict[str, str] | None = None,
) -> LabelingRunResponse:
    """Assemble per-case retrieved chunks with their current relevance labels.

    ``labels_by_key`` maps ``(test_id, chunk_id) -> relevant`` for the project, so a label
    made in any run shows up here (labels are pooled across runs). ``labeler_by_key`` maps
    the same key to the display name of who made it; ``complete_by_test`` maps test_id to
    the manual "labeling complete" flag; ``slice_by_test`` maps test_id to its risk slice.
    """
    labeler_by_key = labeler_by_key or {}
    complete_by_test = complete_by_test or {}
    slice_by_test = slice_by_test or {}
    result_list = list(results)
    cases: list[LabelingCase] = []

    for r in result_list:
        meta = r.result_metadata if isinstance(r.result_metadata, dict) else {}
        raw_chunks = meta.get("retrieved_chunks")
        if not isinstance(raw_chunks, list) or not raw_chunks:
            continue

        chunks: list[ChunkForLabeling] = []
        labeled = 0
        relevant = 0
        labelers: list[str] = []
        for i, c in enumerate(raw_chunks, start=1):
            if not isinstance(c, dict):
                continue
            chunk_id = c.get("chunk_id")
            key = (r.test_id, chunk_id) if chunk_id else None
            label = labels_by_key.get(key) if key else None
            labeler = labeler_by_key.get(key) if key else None
            if label is not None:
                labeled += 1
                if label:
                    relevant += 1
                if labeler and labeler not in labelers:
                    labelers.append(labeler)
            pdf_page = c.get("pdf_page_number")
            chunks.append(
                ChunkForLabeling(
                    chunk_id=chunk_id,
                    title=c.get("title"),
                    url=c.get("url"),
                    content=c.get("content") or c.get("content_preview"),
                    content_preview=c.get("content_preview"),
                    heading_context=c.get("heading_context"),
                    pdf_page_number=pdf_page if isinstance(pdf_page, int) else None,
                    score=c.get("score") if isinstance(c.get("score"), (int, float)) else None,
                    rank=i,
                    relevant=label,
                    labeled_by=labeler,
                )
            )
        if not chunks:
            continue
        cases.append(
            LabelingCase(
                test_id=r.test_id,
                input=(r.input or None) and str(r.input)[:300],
                chunks=chunks,
                labeled_count=labeled,
                relevant_count=relevant,
                complete=bool(complete_by_test.get(r.test_id)),
                slice=slice_by_test.get(r.test_id),
                labelers=labelers,
            )
        )

    # Incomplete first, then least-labeled, so a human always lands on unfinished work.
    cases.sort(key=lambda c: (c.complete, c.labeled_count, c.test_id))

    return LabelingRunResponse(
        available=bool(cases),
        run_id=str(run.id),
        run_name=run.name,
        total_cases=len(result_list),
        labelable_cases=len(cases),
        cases=cases,
    )


def build_pool_view(
    test_id: str,
    input_text: str | None,
    pool: PoolResult,
    *,
    provider_connected: bool,
    labels_by_key: dict[tuple[str, str], bool],
    labeler_by_key: dict[tuple[str, str], str] | None = None,
) -> LabelingPoolResponse:
    """Shape an assembled :class:`PoolResult` into the labeling-pool API response.

    Overlays any existing human label (and labeler) onto each pooled chunk, keyed by
    ``(test_id, chunk_id)`` — so a chunk already judged in any run shows its verdict. Pool
    order is preserved (trace-seeded chunks first, then index-discovered).
    """
    labeler_by_key = labeler_by_key or {}
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
                relevant=labels_by_key.get(key),
                labeled_by=labeler_by_key.get(key),
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
