"""Retrieval-frequency analysis over the chunk population — dead and hot tails.

Over a window of real traffic (trace retrieval spans) or a keyword probe of a
gold dataset's questions, count how often each chunk id shows up in retrieval
results. Both tails of that histogram point at content or chunking problems:

* **dead** chunks — in the index sample but never retrieved. Junk, mis-indexed,
  or genuinely uncovered by the query distribution.
* **hot** chunks — retrieved across a large share of queries. Usually too
  generic (preambles, disclaimers) or too long (diluted embedding); they drag
  precision everywhere.

``analyze_frequency`` is pure so the tails and histogram are unit-testable;
only the two counters hit the DB / index.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.index_providers.base import BaseIndexProvider
from app.index_providers.chunk_quality_common import Finding, as_text, pct
from app.models.base import SpanType
from app.models.datasets import TestCase, TestDataset, is_no_retrieval_expected
from app.models.integrations import Integration, Span, Trace
from app.models.project import Project
from app.services.chunk_pool import assemble_pool
from app.services.retrieval_config import (
    extract_rag_pipeline_sources,
    get_retrieval_span_name,
)

logger = logging.getLogger(__name__)

# A chunk retrieved in at least this share of scanned events counts as hot.
HOT_SHARE = 0.20
# ...but never with fewer than this many hits (small windows are noisy).
HOT_MIN_COUNT = 10
# Keyword-probe depth per query (roughly one retrieval pool's worth).
_PROBE_DEPTH = 20

_HIST_BUCKETS = ((0, "0"), (1, "1-2"), (3, "3-9"), (10, "10-24"), (25, "25+"))
_MAX_TOP_HOT = 10


async def frequency_from_traces(
    db: AsyncSession, project: Project, *, window_days: int
) -> tuple[Counter[str], int]:
    """``(chunk_id -> retrieval count, retrieval events scanned)`` from trace spans.

    One event = one retrieval span. Chunks are identified the same way the
    sources panel identifies them (``extract_rag_pipeline_sources``).
    """
    span_name = get_retrieval_span_name(project)
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    project_integration_ids = select(Integration.id).where(
        Integration.project_id == project.id
    )
    rows = (
        await db.execute(
            select(Span.output)
            .join(Trace, Span.trace_id == Trace.id)
            .where(
                Trace.integration_id.in_(project_integration_ids),
                Trace.start_time >= since,
                # Same retrieval-span selection as analytics: the configured span
                # name, plus the `retriever` type for LangSmith traces.
                or_(Span.name == span_name, Span.type == SpanType.retriever),
            )
        )
    ).all()

    counter: Counter[str] = Counter()
    events = 0
    for (output,) in rows:
        sources = extract_rag_pipeline_sources(output)
        if not sources:
            continue
        events += 1
        # Count each chunk once per event: frequency across queries, not rank depth.
        for cid in {s.get("chunk_id") for s in sources if s.get("chunk_id")}:
            counter[str(cid)] += 1
    return counter, events


async def frequency_from_probe(
    db: AsyncSession,
    provider: BaseIndexProvider,
    project_id: UUID,
    *,
    dataset_id: UUID | None,
    max_queries: int,
    progress_cb=None,
) -> tuple[Counter[str], int]:
    """``(chunk_id -> count, queries probed)`` from a keyword-only index probe.

    Keyword-only keeps the probe free (no embedding calls). Uses the given
    dataset's active test cases, or all of the project's datasets when none is
    given; negative cases (no retrieval expected) are skipped.
    """
    stmt = (
        select(TestCase.prompt, TestCase.tags)
        .join(TestDataset, TestCase.dataset_id == TestDataset.id)
        .where(TestDataset.project_id == project_id, TestCase.status == "active")
    )
    if dataset_id is not None:
        stmt = stmt.where(TestCase.dataset_id == dataset_id)
    rows = (await db.execute(stmt)).all()

    counter: Counter[str] = Counter()
    queries = 0
    target = min(max_queries, len(rows))
    for prompt, tags in rows:
        if queries >= max_queries:
            break
        if not as_text(prompt).strip() or is_no_retrieval_expected(tags):
            continue
        result = await assemble_pool(
            provider, prompt, modes=("keyword",), per_head_depth=_PROBE_DEPTH
        )
        queries += 1
        for chunk in result.chunks:
            counter[chunk.chunk_id] += 1
        if progress_cb is not None:
            await progress_cb(queries, target)
    return counter, queries


def _bucket_label(count: int) -> str:
    label = _HIST_BUCKETS[0][1]
    for lo, name in _HIST_BUCKETS:
        if count >= lo:
            label = name
    return label


def analyze_frequency(
    counter: Counter[str],
    sampled_ids: set[str],
    *,
    source: str,
    window_days: int | None,
    events_scanned: int,
    titles_by_id: dict[str, str] | None = None,
) -> tuple[dict, list[Finding]]:
    """The ``retrieval_frequency`` family dict + findings.

    Dead/hot are computed over ``sampled_ids`` (the run's index sample) so the
    denominators stay comparable across runs; retrieved chunks outside the
    sample still count toward ``unique_chunks_retrieved``.
    """
    findings: list[Finding] = []
    n = len(sampled_ids)
    if n == 0 or events_scanned == 0:
        reason = "no retrieval events in the window" if n else "no sampled chunk ids"
        return {"available": False, "reason": reason, "source": source}, findings

    hot_threshold = max(HOT_MIN_COUNT, int(events_scanned * HOT_SHARE))
    dead = sum(1 for cid in sampled_ids if counter.get(cid, 0) == 0)
    hot_ids = [cid for cid in sampled_ids if counter.get(cid, 0) >= hot_threshold]
    hot_ids.sort(key=lambda cid: -counter[cid])

    hist_counts: dict[str, int] = {name: 0 for _, name in _HIST_BUCKETS}
    for cid in sampled_ids:
        hist_counts[_bucket_label(counter.get(cid, 0))] += 1

    dead_pct = pct(dead, n)
    hot_pct = pct(len(hot_ids), n)

    if dead_pct >= 50:
        findings.append(Finding(
            family="retrieval_frequency", severity="warn",
            title="Large dead-chunk fraction",
            message=(
                f"{dead_pct}% of sampled chunks never appeared in any retrieval result "
                f"({source}, {events_scanned} events). Junk, mis-indexed, or uncovered content."
            ),
            count=dead,
        ))
    if hot_ids:
        findings.append(Finding(
            family="retrieval_frequency", severity="info",
            title="Hot generic chunks",
            message=(
                f"{len(hot_ids)} chunk(s) appear in ≥{hot_threshold} of {events_scanned} "
                "retrieval events — likely boilerplate or over-generic content dragging precision."
            ),
            count=len(hot_ids),
        ))

    metrics = {
        "available": True,
        "source": source,
        "window_days": window_days,
        "events_scanned": events_scanned,
        "unique_chunks_retrieved": len(counter),
        "sampled_chunks": n,
        "dead": dead, "dead_pct": dead_pct,
        "hot": len(hot_ids), "hot_pct": hot_pct,
        "hot_threshold": hot_threshold,
        "histogram": [{"label": name, "count": hist_counts[name]} for _, name in _HIST_BUCKETS],
        "top_hot": [
            {
                "chunk_id": cid,
                "count": counter[cid],
                "title": (titles_by_id or {}).get(cid, ""),
            }
            for cid in hot_ids[:_MAX_TOP_HOT]
        ],
    }
    return metrics, findings
