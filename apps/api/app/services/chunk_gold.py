"""Project-level gold resolution for chunk relevance labels (DB-aware).

Wraps the pure :func:`app.services.chunk_agreement.resolve_gold` with the query that loads a
project's labels + adjudicated overrides and the ``gold_source`` filter (human | ai | both). Kept
in its own leaf module — depending only on the models and the pure resolver — so both the metrics
computation and the per-case diagnosis endpoint can use it without importing each other's modules
(which would form an import cycle through the labeling router helpers).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk_labels import GRADE_MAX, RELEVANT_GRADE, ChunkGoldLabel, ChunkRelevanceLabel
from app.models.project import Project
from app.services.chunk_agreement import resolve_gold
from app.services.retrieval_config import normalize_source_url


async def resolve_project_gold(
    db: AsyncSession, project: Project, gold_source: str, min_grade: int = RELEVANT_GRADE
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, dict[str, int]]]:
    """Resolve gold chunk relevance for the project from the chosen annotator source.

    ``gold_source`` picks whose labels count: ``human`` (default, human labels only), ``ai`` (the
    AI judge's labels only), or ``both`` (as independent annotators). Human labels carry
    ``annotator=None`` (keyed by user); the AI judge carries ``annotator="AI"``. Adjudicated gold
    overrides always win. ``min_grade`` (clamped to 1..3) is the binary-metrics strictness — see
    :func:`app.services.chunk_agreement.resolve_gold` for the exact semantics. Returns
    ``(relevant_by_test, nonrelevant_by_test, grade_by_test)``.
    """
    # Select only the scalar fields gold resolution needs — not full ORM rows. The label table
    # carries Text snapshots (content_preview/url/title) that would otherwise load the whole
    # project's judged-chunk text into memory on every metrics request.
    labels = (
        await db.execute(
            select(
                ChunkRelevanceLabel.test_id,
                ChunkRelevanceLabel.chunk_id,
                ChunkRelevanceLabel.relevance,
                ChunkRelevanceLabel.annotator,
                ChunkRelevanceLabel.labeled_by,
            ).where(ChunkRelevanceLabel.project_id == project.id)
        )
    ).all()
    golds = (
        await db.execute(
            select(
                ChunkGoldLabel.test_id, ChunkGoldLabel.chunk_id, ChunkGoldLabel.relevance
            ).where(ChunkGoldLabel.project_id == project.id)
        )
    ).all()
    overrides = {(test_id, chunk_id): relevance for test_id, chunk_id, relevance in golds}

    def _included(annotator: str | None) -> bool:
        is_ai = annotator is not None
        if gold_source == "ai":
            return is_ai
        if gold_source == "both":
            return True
        return not is_ai  # "human"

    return resolve_gold(
        (
            (test_id, chunk_id, relevance, labeled_by if annotator is None else annotator)
            for test_id, chunk_id, relevance, annotator, labeled_by in labels
            if _included(annotator)
        ),
        overrides,
        min_grade=max(RELEVANT_GRADE, min(min_grade, GRADE_MAX)),
    )


async def gold_relevant_urls_by_test(
    db: AsyncSession, project: Project, gold_source: str = "human"
) -> dict[str, list[str]]:
    """Expected source URLs per test case, derived from its gold-relevant chunk labels.

    Resolves gold with :func:`resolve_project_gold`, then maps each gold-relevant chunk to the
    URL snapshot on its label rows. URLs are deduped by ``normalize_source_url`` (keeping the
    raw form, matching how expected_page_urls are stored) and ordered by gold grade descending,
    then URL, so the most relevant documents lead. Chunks without a URL snapshot are skipped —
    not every index document carries a source URL. Test cases with no usable URL are absent
    from the result, so callers can tell "nothing labeled relevant" from "empty list".
    """
    relevant_by_test, _nonrelevant, grade_by_test = await resolve_project_gold(
        db, project, gold_source
    )
    if not relevant_by_test:
        return {}

    rows = (
        await db.execute(
            select(
                ChunkRelevanceLabel.test_id,
                ChunkRelevanceLabel.chunk_id,
                ChunkRelevanceLabel.url,
            ).where(
                ChunkRelevanceLabel.project_id == project.id,
                ChunkRelevanceLabel.url.is_not(None),
            )
        )
    ).all()
    url_by_key: dict[tuple[str, str], str] = {}
    for test_id, chunk_id, url in rows:
        if isinstance(url, str) and url.strip():
            url_by_key.setdefault((test_id, chunk_id), url.strip())

    out: dict[str, list[str]] = {}
    for test_id, chunk_ids in relevant_by_test.items():
        grades = grade_by_test.get(test_id, {})
        # normalized URL -> (best gold grade across its chunks, raw URL to store)
        best: dict[str, tuple[int, str]] = {}
        for chunk_id in chunk_ids:
            raw = url_by_key.get((test_id, chunk_id))
            if not raw:
                continue
            norm = normalize_source_url(raw)
            if not norm:
                continue
            grade = grades.get(chunk_id, RELEVANT_GRADE)
            current = best.get(norm)
            if current is None or grade > current[0]:
                best[norm] = (grade, raw)
        if best:
            out[test_id] = [url for _grade, url in sorted(best.values(), key=lambda t: (-t[0], t[1]))]
    return out
