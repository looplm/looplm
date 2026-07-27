"""Shared helpers + constants for the chunk-labeling endpoints."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.index_providers.registry import build_index_provider
from app.models.chunk_labels import ChunkRelevanceLabel
from app.models.datasets import TestCase, TestDataset
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.models.user import User
from app.schemas.retrieval import LabelingDatasetOption
from app.services.analysis_llm import (
    AnalysisLlmConfigError,
    AnalysisLlmService,
)
from app.services.llm_usage_tracker import record_llm_usage
from app.services.query_planner import DEFAULT_PLANNER_MAX_QUERIES, plan_queries

logger = logging.getLogger(__name__)

# Key on the test case's metadata under which the planner's agentic queries are persisted, so the
# pool folds them in on every later visit (and the multi-mode eval can reuse them) without
# re-spending an LLM call.
LABELING_QUERIES_META_KEY = "labeling_queries"

# Index-field constants + readers live in the service layer (app.services.index_fields) so both
# routers and background services share them without importing each other. Re-exported here under
# the underscore names this module's callers already use.
from app.services.index_fields import (  # noqa: E402,F401 — re-exported for this package's routers
    INDEX_CHAR_START_FIELDS,
    INDEX_HEADING_FIELDS,
    INDEX_TEXT_FIELDS,
    first_int_field as _first_int_field,
    first_str_field as _first_str_field,
)


def _display_name(email: str | None) -> str | None:
    """Compact display name for a labeler — the local part of their email."""
    if not email:
        return None
    return email.split("@", 1)[0]


def _as_uuid(value: str | None) -> UUID | None:
    """Parse a UUID string, or None for empty/invalid input (caller treats as 'unspecified')."""
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


async def _list_dataset_options(
    db: AsyncSession, project: Project
) -> list[LabelingDatasetOption]:
    """Every dataset in the project with its test-case count, newest first (for the picker)."""
    rows = (
        await db.execute(
            select(TestDataset, func.count(TestCase.id))
            .outerjoin(TestCase, TestCase.dataset_id == TestDataset.id)
            .where(TestDataset.project_id == project.id)
            .group_by(TestDataset.id)
            .order_by(TestDataset.updated_at.desc())
        )
    ).all()
    return [
        LabelingDatasetOption(id=str(ds.id), name=ds.name, test_count=count or 0)
        for ds, count in rows
    ]


async def _resolve_dataset(
    db: AsyncSession, project: Project, dataset_id: UUID | None
) -> TestDataset | None:
    """The requested dataset, or the most recently updated one when unspecified.

    Returns ``None`` when the project has no datasets at all (the labeling view is then empty).
    """
    ds_filter = [TestDataset.project_id == project.id]
    if dataset_id is not None:
        ds_filter.append(TestDataset.id == dataset_id)
    dataset = (
        await db.execute(
            select(TestDataset).where(*ds_filter).order_by(TestDataset.updated_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if dataset is None and dataset_id is not None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Dataset not found"}},
        )
    return dataset


async def _dataset_case_query(db: AsyncSession, dataset_id: UUID, test_id: str) -> str | None:
    """The query text (prompt) for one test case in a dataset, or None if absent."""
    return (
        await db.execute(
            select(TestCase.prompt).where(
                TestCase.dataset_id == dataset_id, TestCase.test_id == test_id
            )
        )
    ).scalar_one_or_none()


async def _dataset_case_tags(db: AsyncSession, dataset_id: UUID, test_id: str) -> list:
    """The tags list for one test case in a dataset, or [] if absent."""
    return (
        await db.execute(
            select(TestCase.tags).where(
                TestCase.dataset_id == dataset_id, TestCase.test_id == test_id
            )
        )
    ).scalar_one_or_none() or []


async def _dataset_case_expected_answer(
    db: AsyncSession, dataset_id: UUID, test_id: str
) -> str | None:
    """The reference answer for one test case, or None if the case has none.

    Passed to the AI judge as optional context so it can judge whether a chunk supplies the
    information an answer needs (not just topical overlap with the query).
    """
    return (
        await db.execute(
            select(TestCase.expected_answer).where(
                TestCase.dataset_id == dataset_id, TestCase.test_id == test_id
            )
        )
    ).scalar_one_or_none()


async def _dataset_case_agentic_queries(
    db: AsyncSession, dataset_id: UUID, test_id: str
) -> list[str]:
    """The planner's persisted agentic sub-queries for a case, or [] if none planned yet."""
    meta = (
        await db.execute(
            select(TestCase.test_case_metadata).where(
                TestCase.dataset_id == dataset_id, TestCase.test_id == test_id
            )
        )
    ).scalar_one_or_none()
    queries = (meta or {}).get(LABELING_QUERIES_META_KEY, {}).get("agentic")
    return [q for q in queries if isinstance(q, str) and q.strip()] if isinstance(queries, list) else []


async def _persist_case_agentic_queries(
    db: AsyncSession, dataset_id: UUID, test_id: str, *, base: str, agentic: list[str]
) -> None:
    """Persist the planned queries onto the case's metadata so later pools fold them in.

    Stored under ``metadata.labeling_queries = {base, agentic}``. JSONB needs a fresh dict assigned
    for SQLAlchemy to flag the column dirty, so we copy-update rather than mutate in place.
    """
    case = (
        await db.execute(
            select(TestCase).where(
                TestCase.dataset_id == dataset_id, TestCase.test_id == test_id
            )
        )
    ).scalar_one_or_none()
    if case is None:
        return
    meta = dict(case.test_case_metadata or {})
    meta[LABELING_QUERIES_META_KEY] = {"base": [base], "agentic": agentic}
    case.test_case_metadata = meta
    await db.flush()


async def _case_planned(db: AsyncSession, dataset_id: UUID, test_id: str) -> bool:
    """Whether the planner has already run for this case (the key is present, even if it planned
    zero queries). Lets the auto-pool path plan exactly once and not re-spend an LLM call every
    time a case with genuinely no useful sub-queries is opened.
    """
    meta = (
        await db.execute(
            select(TestCase.test_case_metadata).where(
                TestCase.dataset_id == dataset_id, TestCase.test_id == test_id
            )
        )
    ).scalar_one_or_none()
    return isinstance(meta, dict) and LABELING_QUERIES_META_KEY in meta


async def plan_and_persist_case_queries(
    db: AsyncSession,
    project: Project,
    user: User,
    *,
    dataset_id: UUID,
    test_id: str,
    query: str,
    instructions: str | None = None,
    max_queries: int | None = None,
) -> list[str]:
    """Plan a case's agentic sub-queries with the LLM, record usage, persist them, and return them.

    The single place planning happens — shared by the manual "plan queries" endpoint and the
    auto-plan-on-first-pool path. Raises :class:`AnalysisLlmConfigError` when no LLM is configured
    and propagates planner failures; the manual endpoint maps those to HTTP, the auto path swallows
    them and falls back to base-only pooling.
    """
    llm = AnalysisLlmService(user_settings=user.settings, project_settings=project.settings)
    queries, usage = await plan_queries(
        llm,
        query,
        instructions=instructions,
        max_queries=max_queries or DEFAULT_PLANNER_MAX_QUERIES,
    )
    await record_llm_usage(
        db,
        project_id=project.id,
        service_name="chunk_labeling",
        function_name="plan_queries",
        provider=llm.provider,
        model=llm.model,
        usage=usage,
        request_metadata={"test_id": test_id, "planned": len(queries)},
    )
    await _persist_case_agentic_queries(db, dataset_id, test_id, base=query, agentic=queries)
    return queries


async def ensure_case_agentic_queries(
    db: AsyncSession,
    project: Project,
    user: User,
    *,
    dataset_id: UUID,
    test_id: str,
    query: str,
) -> list[str]:
    """The case's agentic sub-queries, auto-planning them once if they were never planned.

    Mirrors the labeling-pool view's auto-plan-on-first-pool (runs once, persisted even when it
    plans nothing). Sharing it with the AI judge guarantees the judge grades the *same* agentic
    candidates the labeler later sees, not a base-only pool when a case is judged in batch before
    it's ever opened. Falls back to base-only (``[]``) when no LLM is configured or planning fails.
    """
    agentic = await _dataset_case_agentic_queries(db, dataset_id, test_id)
    if not agentic and not await _case_planned(db, dataset_id, test_id):
        try:
            agentic = await plan_and_persist_case_queries(
                db, project, user, dataset_id=dataset_id, test_id=test_id, query=query
            )
        except AnalysisLlmConfigError:
            agentic = []  # no LLM yet — pool base-only, auto-plan once one is configured
        except Exception:  # noqa: BLE001
            logger.exception("Auto query-planning failed for test_id=%s", test_id)
            agentic = []
    return agentic


async def fetch_full_chunk_texts(
    db: AsyncSession, project: Project, chunk_ids: list[str]
) -> dict[str, str]:
    """Full index body text for each chunk id, fetched live from the project's index provider.

    The pool's ``content_preview`` is a snapshot taken when the pool was built, so it can be
    stale (re-indexed or edited chunk) and, for pools built before the provider stopped
    truncating, cut off at 600 characters. The AI judge must grade the whole current chunk, so it
    resolves the text live from the index. Ids the index can't resolve (chunk gone, no index, no
    text field) are omitted, so the caller falls back to the snapshot.
    """
    ids = [c for c in dict.fromkeys(chunk_ids) if c]
    if not ids:
        return {}
    provider_row = (
        await db.execute(
            select(IndexProvider)
            .where(IndexProvider.project_id == project.id)
            .order_by(IndexProvider.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if provider_row is None:
        return {}
    provider = build_index_provider(provider_row)
    try:
        docs = await provider.fetch_documents_by_key(ids)
    except Exception:  # noqa: BLE001 — capability gap / transient error → fall back to previews
        logger.exception("Fetching full chunk text failed for %d ids", len(ids))
        return {}
    finally:
        await provider.aclose()

    out: dict[str, str] = {}
    for cid, fields in docs.items():
        if not isinstance(fields, dict):
            continue
        for f in INDEX_TEXT_FIELDS:
            v = fields.get(f)
            if isinstance(v, str) and v.strip():
                out[cid] = v
                break
    return out


async def fetch_chunk_fields(
    db: AsyncSession, project: Project, chunk_id: str
) -> tuple[dict | None, bool]:
    """One chunk's full index document, fetched live from the project's index provider.

    Returns ``(fields, provider_connected)``: ``fields`` is the ``{field: value}`` document, or
    ``None`` when there's no provider or the chunk isn't found; ``provider_connected`` distinguishes
    "no index" from "index has no such chunk" so the passage panel can be honest. Powers the local
    (A) passage split, which needs the chunk's current full body + heading, not the pool snapshot.
    """
    provider_row = (
        await db.execute(
            select(IndexProvider)
            .where(IndexProvider.project_id == project.id)
            .order_by(IndexProvider.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if provider_row is None:
        return None, False
    provider = build_index_provider(provider_row)
    try:
        docs = await provider.fetch_documents_by_key([chunk_id])
    except Exception:  # noqa: BLE001 — capability gap / transient error → treat as not found
        logger.exception("Fetching chunk fields failed for chunk_id=%s", chunk_id)
        return None, True
    finally:
        await provider.aclose()
    fields = docs.get(chunk_id)
    return (fields if isinstance(fields, dict) else None), True


async def _project_labels(
    db: AsyncSession, project: Project, *, user_id: UUID | None = None
) -> tuple[
    dict[tuple[str, str], int],
    dict[tuple[str, str], str],
    dict[str, list[str]],
    dict[tuple[str, str], int],
]:
    """Load chunk labels for the labeling view, scoped to one annotator's own judgments.

    Returns ``(labels_by_key, labeler_by_key, labelers_by_test, ai_labels_by_key)``. The first
    two are scoped to the human ``user_id`` (so each annotator sees and edits their *own* graded
    verdicts), keyed by ``(test_id, chunk_id)`` — ``labels_by_key`` maps to the 0..3 grade. AI
    judge labels (``annotator`` set) are never the viewer's own; they are returned separately in
    ``ai_labels_by_key`` so the UI can show the model's grade as a read-only second opinion.
    ``labelers_by_test`` lists every annotator (humans by name + the AI judge) who has judged any
    chunk in a test case, for the per-case "who labeled" display.
    """
    labels = (
        await db.execute(
            select(ChunkRelevanceLabel).where(ChunkRelevanceLabel.project_id == project.id)
        )
    ).scalars().all()

    labeler_ids = {lbl.labeled_by for lbl in labels if lbl.labeled_by and not lbl.annotator}
    names: dict = {}
    if labeler_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(labeler_ids)))
        ).scalars().all()
        names = {u.id: _display_name(u.email) for u in users}

    # The viewer's own labels are human rows (annotator NULL) authored by user_id.
    scoped = [
        lbl
        for lbl in labels
        if not lbl.annotator and (user_id is None or lbl.labeled_by == user_id)
    ]
    labels_by_key = {(lbl.test_id, lbl.chunk_id): lbl.relevance for lbl in scoped}
    labeler_by_key = {
        (lbl.test_id, lbl.chunk_id): names.get(lbl.labeled_by)
        for lbl in scoped
        if lbl.labeled_by and names.get(lbl.labeled_by)
    }

    ai_labels_by_key = {
        (lbl.test_id, lbl.chunk_id): lbl.relevance for lbl in labels if lbl.annotator
    }

    labelers_by_test: dict[str, list[str]] = {}
    for lbl in labels:
        # A non-human label is attributed to its annotator name (e.g. "AI"); a human label to
        # the display name of the user who made it.
        name = lbl.annotator or names.get(lbl.labeled_by)
        if name and name not in labelers_by_test.setdefault(lbl.test_id, []):
            labelers_by_test[lbl.test_id].append(name)
    return labels_by_key, labeler_by_key, labelers_by_test, ai_labels_by_key


# Pool assembly lives in the service layer (app.services.labeling_pool) so the by-stage metrics
# service can reuse it without importing a router. Re-exported here under the name this
# package's routers already import.
from app.services.labeling_pool import (  # noqa: E402,F401 — re-exported for this package
    assemble_case_pool,
)
