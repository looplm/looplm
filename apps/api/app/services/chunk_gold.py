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

from app.models.chunk_labels import ChunkGoldLabel, ChunkRelevanceLabel
from app.models.project import Project
from app.services.chunk_agreement import resolve_gold


async def resolve_project_gold(
    db: AsyncSession, project: Project, gold_source: str
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, dict[str, int]]]:
    """Resolve gold chunk relevance for the project from the chosen annotator source.

    ``gold_source`` picks whose labels count: ``human`` (default, human labels only), ``ai`` (the
    AI judge's labels only), or ``both`` (as independent annotators). Human labels carry
    ``annotator=None`` (keyed by user); the AI judge carries ``annotator="AI"``. Adjudicated gold
    overrides always win. Returns ``(relevant_by_test, nonrelevant_by_test, grade_by_test)``.
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
    )
