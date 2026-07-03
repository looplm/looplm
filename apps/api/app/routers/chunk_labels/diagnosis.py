"""Per-case retrieval diagnosis: for one test case, why did the retriever miss relevant chunks?

The chunk-level metrics tell you recall@k is low; this tells you *why* for a single case. It splits
the case's judged-relevant chunks into retrieved (top-k) vs missed, then fetches each missed chunk
live from the index and classifies it: a bad chunk (tiny/giant/mojibake/table/markup), one with no
embedding (invisible to vector/hybrid search), one that's clean but ranked past k (a ranking
problem), or one that never surfaces at all (a lexical/semantic gap, or a mislabel). That verdict
split points at whether the fix belongs in the indexer, the retriever, or the labels.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project
from app.db import get_db
from app.index_providers.chunk_quality_common import (
    TEXT_FIELDS,
    TITLE_FIELDS,
    URL_FIELDS,
    as_text,
    pick_field,
    score_chunk,
)
from app.index_providers.registry import build_index_provider
from app.models.chunk_labels import ChunkRelevanceLabel
from app.models.datasets import TestCase, TestDataset
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.schemas.retrieval import CaseDiagnosisResponse, DiagnosedChunk
from app.services.chunk_gold import resolve_project_gold
from app.services.chunk_pool import AGENTIC_RERANK_DEPTH
from app.services.retrieval_metrics_aggregate import STAGE_LABELS, ranked_chunks_for_head

from ._helpers import _dataset_case_agentic_queries, assemble_case_pool

router = APIRouter()

# Retrievers the candidate pool ranks (keyword/vector/hybrid/semantic/agentic/agentic_rerank).
_POOL_HEADS = {head for head, _ in STAGE_LABELS}
_DEFAULT_HEAD = "agentic_rerank"
# Worst-first ordering for the missed list: the actionable-indexer verdicts before the ranking ones.
_VERDICT_ORDER = {
    "not_in_index": 0,
    "missing_embedding": 1,
    "bad_chunk": 2,
    "unretrievable": 3,
    "buried": 4,
}


def _has_vector(doc: dict) -> bool:
    """Whether a live index doc carries a non-empty embedding (a numeric vector of real length)."""
    for value in doc.values():
        if (
            isinstance(value, list)
            and len(value) >= 16
            and all(isinstance(x, (int, float)) for x in value[:8])
        ):
            return True
    return False


def _preview(text: str | None, limit: int = 400) -> str | None:
    if not text:
        return None
    t = as_text(text).strip()
    if not t:
        return None
    return t[:limit] + "…" if len(t) > limit else t


@router.get("/case-diagnosis", response_model=CaseDiagnosisResponse)
async def diagnose_case(
    test_id: str,
    k: int = 10,
    retriever: str = _DEFAULT_HEAD,
    gold_source: str = "human",
    refresh: bool = False,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Diagnose why a case's relevant chunks were missed at top-``k`` under ``retriever``.

    ``retriever`` is one of the pool heads (keyword | vector | hybrid | semantic | agentic |
    agentic_rerank); anything else falls back to ``agentic_rerank``. ``gold_source`` selects whose
    labels are ground truth (human | ai | both). Returns ``available=False`` when the project has no
    index provider, the case has no gold relevant chunks, or the case isn't found.
    """
    head = retriever if retriever in _POOL_HEADS else _DEFAULT_HEAD
    k = max(1, min(k, 50))

    provider_row = (
        await db.execute(
            select(IndexProvider)
            .where(IndexProvider.project_id == project.id)
            .order_by(IndexProvider.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if provider_row is None:
        return CaseDiagnosisResponse(
            provider_connected=False, available=False, test_id=test_id, retriever=head, k=k
        )

    relevant_by_test, _nonrel, grade_by_test = await resolve_project_gold(db, project, gold_source)
    relevant = relevant_by_test.get(test_id) or set()
    grades = grade_by_test.get(test_id, {})
    if not relevant:
        return CaseDiagnosisResponse(
            provider_connected=True, available=False, test_id=test_id, retriever=head, k=k
        )

    row = (
        await db.execute(
            select(TestCase.dataset_id, TestCase.prompt)
            .join(TestDataset, TestCase.dataset_id == TestDataset.id)
            .where(TestDataset.project_id == project.id, TestCase.test_id == test_id)
            .order_by(TestCase.created_at.asc())
            .limit(1)
        )
    ).first()
    if row is None:
        return CaseDiagnosisResponse(
            provider_connected=True, available=False, test_id=test_id, retriever=head, k=k
        )
    dataset_id, query = row
    agentic = await _dataset_case_agentic_queries(db, dataset_id, test_id)

    pool, _computed, connected = await assemble_case_pool(
        db,
        project,
        test_id,
        str(query or ""),
        agentic_queries=agentic,
        rerank_depth=AGENTIC_RERANK_DEPTH,
        refresh=refresh,
    )
    if not connected:
        return CaseDiagnosisResponse(
            provider_connected=False, available=False, test_id=test_id, query=query,
            retriever=head, k=k,
        )

    ranked_ids = [c.chunk_id for c in ranked_chunks_for_head(pool.chunks, head)]
    rank_of = {cid: i for i, cid in enumerate(ranked_ids, start=1)}
    topk = set(ranked_ids[:k])
    retrieved_relevant = relevant & topk
    missed = [cid for cid in relevant if cid not in topk]

    # Label snapshots (content/title/url) — the fallback when a missed chunk is gone from the index.
    snap_rows = (
        await db.execute(
            select(
                ChunkRelevanceLabel.chunk_id,
                ChunkRelevanceLabel.content_preview,
                ChunkRelevanceLabel.title,
                ChunkRelevanceLabel.url,
            ).where(
                ChunkRelevanceLabel.project_id == project.id,
                ChunkRelevanceLabel.test_id == test_id,
                ChunkRelevanceLabel.chunk_id.in_(missed),
            )
        )
    ).all()
    snaps = {cid: (cp, ti, u) for cid, cp, ti, u in snap_rows}

    # Live index docs for the missed chunks — authoritative text + embedding presence, one batch.
    provider = build_index_provider(provider_row)
    try:
        live = await provider.fetch_documents_by_key(missed)
    finally:
        await provider.aclose()

    diagnosed: list[DiagnosedChunk] = []
    for cid in missed:
        doc = live.get(cid)
        snap_cp, snap_title, snap_url = snaps.get(cid, (None, None, None))
        rank = rank_of.get(cid)
        if doc is None:
            diagnosed.append(
                DiagnosedChunk(
                    chunk_id=cid, title=snap_title, url=snap_url, grade=grades.get(cid),
                    rank=rank, verdict="not_in_index", content_preview=_preview(snap_cp),
                )
            )
            continue
        keys = set(doc.keys())
        text_field = pick_field(keys, TEXT_FIELDS)
        text = as_text(doc.get(text_field)) if text_field else ""
        has_vec = _has_vector(doc)
        flags = score_chunk(text, has_vec)
        issues = flags.issues()
        if flags.missing_embedding:
            verdict = "missing_embedding"
        elif issues:
            verdict = "bad_chunk"
        elif rank is not None:
            verdict = "buried"
        else:
            verdict = "unretrievable"
        title_field = pick_field(keys, TITLE_FIELDS)
        url_field = pick_field(keys, URL_FIELDS)
        diagnosed.append(
            DiagnosedChunk(
                chunk_id=cid,
                title=(as_text(doc.get(title_field)) or None) if title_field else snap_title,
                url=(as_text(doc.get(url_field)) or None) if url_field else snap_url,
                grade=grades.get(cid),
                rank=rank,
                verdict=verdict,
                flags=issues,
                token_estimate=flags.token_estimate,
                has_embedding=has_vec,
                content_preview=_preview(text) or _preview(snap_cp),
            )
        )

    diagnosed.sort(key=lambda d: (_VERDICT_ORDER.get(d.verdict, 9), -(d.grade or 0)))
    summary: dict[str, int] = {}
    for d in diagnosed:
        summary[d.verdict] = summary.get(d.verdict, 0) + 1

    return CaseDiagnosisResponse(
        provider_connected=True,
        available=True,
        test_id=test_id,
        query=query,
        retriever=head,
        k=k,
        relevant_count=len(relevant),
        retrieved_count=len(ranked_ids),
        retrieved_relevant_count=len(retrieved_relevant),
        missed_count=len(missed),
        summary=summary,
        missed=diagnosed,
    )
