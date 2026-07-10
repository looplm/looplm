"""Claim-boundary analysis — do gold answers fit inside single chunks?

For each gold test case, decompose its expected answer into atomic claims and
check whether each claim's full evidence lives in ONE labeled-relevant chunk or
is split across chunk boundaries. A systematic pattern of claims landing across
borders means the chunking is too aggressive for that query type — a signal no
reranker can fix, cleanly separated from embedding/reranking quality.

Chunk selection per case: the adjudicated gold labels (grade >= 2), falling
back to the highest human/AI relevance grade per chunk. Texts come from the
live index (``fetch_documents_by_key``). Cases without a usable answer or
labeled chunks are skipped and counted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.index_providers.base import BaseIndexProvider
from app.index_providers.chunk_quality_common import (
    ORDINAL_FIELDS,
    PARENT_FIELDS,
    TEXT_FIELDS,
    Finding,
    as_text,
    pct,
    pick_field,
)
from app.models.chunk_labels import ChunkGoldLabel, ChunkRelevanceLabel
from app.models.datasets import TestCase, TestDataset, is_no_retrieval_expected
from app.services.analysis_llm import AnalysisLlmService, LlmUsageInfo
from app.services.chunk_judge_common import (
    AiJudgeChunk,
    add_usage,
    clean,
    empty_usage,
    extract_json_object,
)

logger = logging.getLogger(__name__)

# Only chunks labeled at least "relevant" carry answer evidence worth checking.
_MIN_LABEL_GRADE = 2
# Cap the chunks shown per case so decompose+ground stays a single call each.
_MAX_CHUNKS_PER_CASE = 12
_MAX_CLAIMS_PER_CASE = 12
_MAX_EXAMPLES = 8

_DECOMPOSE_INSTRUCTIONS = (
    "You decompose an answer into atomic factual claims. Each claim must be a single, "
    "self-contained factual statement that can be verified independently. Do not add facts "
    "that are not in the answer; do not merge distinct facts into one claim."
)

_GROUND_INSTRUCTIONS = (
    "You check where each claim's evidence lives among the given chunks. For every claim, "
    "return the MINIMAL set of chunk numbers whose text together contains the full evidence "
    "for the claim. If any single chunk alone contains the full evidence, return exactly that "
    "one chunk. If no combination of chunks supports the claim, return an empty list. Never "
    "pad the list with merely related chunks."
)

GroundingStatus = Literal["single", "cross_boundary", "unsupported"]


@dataclass
class ClaimGrounding:
    claim: str
    chunk_ids: list[str]
    status: GroundingStatus


async def decompose_claims(
    llm: AnalysisLlmService, expected_answer: str
) -> tuple[list[str], LlmUsageInfo]:
    """Split ``expected_answer`` into atomic claims (capped)."""
    content, usage = await llm.tracked_chat_completion(
        messages=[
            {"role": "system", "content": _DECOMPOSE_INSTRUCTIONS},
            {
                "role": "user",
                "content": (
                    f"Answer:\n{expected_answer.strip()}\n\n"
                    'Return ONLY a JSON object of the form {"claims": ["...", ...]} with at '
                    f"most {_MAX_CLAIMS_PER_CASE} claims. No prose outside the JSON."
                ),
            },
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    data = extract_json_object(content)
    entries = data.get("claims") if data else None
    claims = [
        str(c).strip()
        for c in (entries if isinstance(entries, list) else [])
        if isinstance(c, str) and str(c).strip()
    ]
    return claims[:_MAX_CLAIMS_PER_CASE], usage


async def ground_claims(
    llm: AnalysisLlmService, claims: list[str], chunks: list[AiJudgeChunk]
) -> tuple[list[ClaimGrounding], LlmUsageInfo]:
    """Map each claim to the minimal chunk set containing its full evidence."""
    lines = ["Claims:"]
    for i, c in enumerate(claims, start=1):
        lines.append(f"[{i}] {c}")
    lines.append("\nChunks:")
    for i, c in enumerate(chunks, start=1):
        lines.append(f"\n[{i}]\n{clean(c.text) or '(no text)'}")
    lines.append(
        '\nReturn ONLY a JSON object of the form {"groundings": [{"claim": 1, "chunks": [2]}, '
        '...]}, one entry per claim number above; "chunks" is the minimal chunk-number set per '
        "the instructions (empty if unsupported). No prose outside the JSON."
    )

    content, usage = await llm.tracked_chat_completion(
        messages=[
            {"role": "system", "content": _GROUND_INSTRUCTIONS},
            {"role": "user", "content": "\n".join(lines)},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    by_claim: dict[int, list[str]] = {}
    data = extract_json_object(content)
    entries = data.get("groundings") if data else None
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        n = e.get("claim")
        refs = e.get("chunks")
        if not (isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(claims)):
            continue
        ids: list[str] = []
        for r in refs if isinstance(refs, list) else []:
            if isinstance(r, int) and not isinstance(r, bool) and 1 <= r <= len(chunks):
                cid = chunks[r - 1].chunk_id
                if cid not in ids:
                    ids.append(cid)
        by_claim[n] = ids

    groundings: list[ClaimGrounding] = []
    for i, claim in enumerate(claims, start=1):
        ids = by_claim.get(i, [])
        status: GroundingStatus = (
            "unsupported" if not ids else "single" if len(ids) == 1 else "cross_boundary"
        )
        groundings.append(ClaimGrounding(claim=claim, chunk_ids=ids, status=status))
    return groundings, usage


def has_adjacent_pair(
    chunk_ids: list[str], docs_by_id: dict[str, dict],
    *, parent_field: str | None, ordinal_field: str | None,
) -> bool:
    """True when any two of the chunks are consecutive chunks of the same parent."""
    if not parent_field or not ordinal_field or len(chunk_ids) < 2:
        return False
    keyed: list[tuple[str, float]] = []
    for cid in chunk_ids:
        doc = docs_by_id.get(cid)
        if not doc:
            continue
        parent = as_text(doc.get(parent_field)).strip()
        try:
            ordinal = float(doc.get(ordinal_field))
        except (TypeError, ValueError):
            continue
        if parent:
            keyed.append((parent, ordinal))
    keyed.sort()
    return any(
        a[0] == b[0] and b[1] == a[1] + 1 for a, b in zip(keyed, keyed[1:])
    )


def analyze_claim_boundary(
    rows: list[dict],
    *,
    dataset_id: str | None,
    cases_analyzed: int,
    cases_skipped: int,
) -> tuple[dict, list[Finding]]:
    """The ``claim_boundary`` family dict + findings.

    ``rows`` are flat per-claim records: ``{test_case_id, claim, chunk_ids,
    status, adjacent}``.
    """
    findings: list[Finding] = []
    total = len(rows)
    single = sum(1 for r in rows if r["status"] == "single")
    cross = [r for r in rows if r["status"] == "cross_boundary"]
    unsupported = sum(1 for r in rows if r["status"] == "unsupported")
    cross_adjacent = sum(1 for r in cross if r.get("adjacent"))
    cross_pct = pct(len(cross), total)

    if total and cross_pct >= 25:
        findings.append(Finding(
            family="claim_boundary", severity="warn",
            title="Claims split across chunk boundaries",
            message=(
                f"{cross_pct}% of gold-answer claims need more than one chunk for their full "
                f"evidence ({cross_adjacent} across adjacent chunks) — the chunking splits "
                "atomic facts, which no reranker can repair."
            ),
            count=len(cross),
        ))

    metrics = {
        "available": True,
        "dataset_id": dataset_id,
        "cases_analyzed": cases_analyzed,
        "cases_skipped": cases_skipped,
        "claims_total": total,
        "single_chunk": single,
        "cross_boundary": len(cross),
        "cross_boundary_pct": cross_pct,
        "cross_adjacent": cross_adjacent,
        "unsupported": unsupported,
        "examples": [
            {
                "test_case_id": r["test_case_id"],
                "claim": r["claim"][:200],
                "chunk_ids": r["chunk_ids"],
                "adjacent": bool(r.get("adjacent")),
            }
            for r in cross[:_MAX_EXAMPLES]
        ],
    }
    return metrics, findings


async def _relevant_chunk_ids(
    db: AsyncSession, project_id: UUID, test_id: str
) -> list[str]:
    """Chunk ids labeled relevant for a test case — gold first, else best human/AI grade."""
    gold = (
        await db.execute(
            select(ChunkGoldLabel.chunk_id, ChunkGoldLabel.relevance).where(
                ChunkGoldLabel.project_id == project_id, ChunkGoldLabel.test_id == test_id
            )
        )
    ).all()
    gold_grades = {cid: grade for cid, grade in gold}

    labels = (
        await db.execute(
            select(ChunkRelevanceLabel.chunk_id, ChunkRelevanceLabel.relevance).where(
                ChunkRelevanceLabel.project_id == project_id,
                ChunkRelevanceLabel.test_id == test_id,
            )
        )
    ).all()
    best: dict[str, int] = {}
    for cid, grade in labels:
        if cid not in gold_grades and grade > best.get(cid, -1):
            best[cid] = grade

    merged = {**best, **gold_grades}
    relevant = [(cid, g) for cid, g in merged.items() if g >= _MIN_LABEL_GRADE]
    relevant.sort(key=lambda x: -x[1])
    return [cid for cid, _ in relevant[:_MAX_CHUNKS_PER_CASE]]


async def run_claim_boundary_pass(
    db: AsyncSession,
    llm: AnalysisLlmService,
    provider: BaseIndexProvider,
    project_id: UUID,
    *,
    dataset_id: UUID | None,
    max_cases: int,
) -> tuple[dict, list[Finding], LlmUsageInfo]:
    """Run the whole pass: select cases, fetch labels + chunk texts, decompose, ground."""
    stmt = (
        select(TestCase)
        .join(TestDataset, TestCase.dataset_id == TestDataset.id)
        .where(TestDataset.project_id == project_id, TestCase.status == "active")
    )
    if dataset_id is not None:
        stmt = stmt.where(TestCase.dataset_id == dataset_id)
    cases = (await db.execute(stmt)).scalars().all()

    usage = empty_usage()
    rows: list[dict] = []
    analyzed = 0
    skipped = 0
    for case in cases:
        if analyzed >= max_cases:
            break
        answer = as_text(case.expected_answer).strip()
        if not answer or is_no_retrieval_expected(case.tags):
            skipped += 1
            continue
        chunk_ids = await _relevant_chunk_ids(db, project_id, case.test_id)
        if not chunk_ids:
            skipped += 1
            continue
        docs_by_id = await provider.fetch_documents_by_key(chunk_ids)
        keys: set[str] = set().union(*(d.keys() for d in docs_by_id.values())) if docs_by_id else set()
        text_field = pick_field(keys, TEXT_FIELDS)
        parent_field = pick_field(keys, PARENT_FIELDS)
        ordinal_field = pick_field(keys, ORDINAL_FIELDS)
        chunks = [
            AiJudgeChunk(chunk_id=cid, text=as_text(docs_by_id[cid].get(text_field)))
            for cid in chunk_ids
            if cid in docs_by_id and text_field
        ]
        if not chunks:
            skipped += 1
            continue

        claims, decompose_usage = await decompose_claims(llm, answer)
        add_usage(usage, decompose_usage)
        if not claims:
            skipped += 1
            continue
        groundings, ground_usage = await ground_claims(llm, claims, chunks)
        add_usage(usage, ground_usage)
        analyzed += 1
        for g in groundings:
            rows.append({
                "test_case_id": case.test_id,
                "claim": g.claim,
                "chunk_ids": g.chunk_ids,
                "status": g.status,
                "adjacent": g.status == "cross_boundary"
                and has_adjacent_pair(
                    g.chunk_ids, docs_by_id,
                    parent_field=parent_field, ordinal_field=ordinal_field,
                ),
            })

    metrics, findings = analyze_claim_boundary(
        rows,
        dataset_id=str(dataset_id) if dataset_id else None,
        cases_analyzed=analyzed,
        cases_skipped=skipped,
    )
    if analyzed == 0:
        metrics = {
            "available": False,
            "reason": "no gold cases with labeled relevant chunks and an expected answer",
        }
        findings = []
    return metrics, findings, usage
