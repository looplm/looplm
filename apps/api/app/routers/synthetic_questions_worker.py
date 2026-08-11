"""Background worker for a synthetic-question generation run.

Mirrors ``chunk_quality_worker``: spawned via ``asyncio.create_task`` from the router, owns its
DB sessions through the session factory, and drives a ``SyntheticQuestionRun`` row through
pending → running → completed/failed/cancelled.

Steps:
  1. mark ``running``, build the index provider
  2. sample chunks (whole corpus, or one partition value) and drop the unusable ones
  3. draft questions per chunk, in batches, updating ``processed`` as batches land
  4. draft and verify the negative share
  5. persist a dataset + cases + gold labels (skipped entirely for a preview run)

A provider that cannot sample its corpus is a failure here, not a soft "unavailable": without
chunks there is nothing to generate from, and reporting success with zero questions would be
misleading.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.index_providers.base import BaseIndexProvider
from app.index_providers.registry import build_index_provider
from app.models.index_providers import IndexProvider
from app.models.synthetic_questions import SyntheticQuestionRun
from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService
from app.services.chunk_judge_common import add_usage, empty_usage, usage_dict
from app.services.llm_usage_tracker import record_llm_usage
from app.services.query_embedding import build_query_embedder
from app.services.synthetic_dataset import persist_questions, resolve_dataset
from app.services.synthetic_negatives import generate_negatives, verify_negatives
from app.services.synthetic_questions import (
    DEFAULT_PER_DOCUMENT_CAP,
    ChunkSelection,
    GeneratedQuestion,
    SourceChunk,
    chunk_from_document,
    dedupe_questions,
    diversify,
    generate_questions,
    select_chunks,
)

logger = logging.getLogger(__name__)

SERVICE_NAME = "synthetic_questions_worker"

# Sampling overdraw. Two things eat into the draw before it becomes a benchmark: junk chunks are
# filtered out, and the per-document cap discards the tail of any document that is over-represented
# in the sample. Drawing 4x the target leaves enough material for both without a second round trip.
# The request schema caps ``sample_size``, so this needs no cap of its own.
OVERDRAW = 4.0


def negatives_wanted(positives: int, negative_share: int) -> int:
    """How many negatives to draft so they are ``negative_share`` percent of the final set.

    ``share`` is a share of the *total*, not a multiplier on the positives: with 100 positives
    and a 15% share the run wants ~18 negatives (18/118 ≈ 15%), not 15.
    """
    share = max(0, min(int(negative_share), 99))
    if share == 0 or positives <= 0:
        return 0
    return max(1, round(positives * share / (100 - share)))


async def sample_chunks(
    provider: BaseIndexProvider,
    *,
    scope: str,
    partition_key: str | None,
    partition_value: str | None,
    sample_size: int,
) -> tuple[list[SourceChunk], int]:
    """Draw candidate chunks for the run. Returns ``(candidates, raw_sampled)``.

    Both paths deliberately spread the sample across their slice rather than taking its head:
    chunks of one document sit next to each other in the index, so an unspread sample of a slice
    containing one large document is a benchmark about that document.
    """
    want = max(1, int(sample_size * OVERDRAW))

    if scope == "partition":
        if not partition_key or partition_value is None:
            raise ValueError("Partition scope requires a partition key and value")
        docs = await provider.sample_documents(
            partition_key, partition_value, want, spread=True
        )
        candidates = [
            SourceChunk(chunk_id=d.id, text=d.snippet or "", title=d.title, url=d.url)
            for d in docs
            if d.id
        ]
        return candidates, len(docs)

    raw = await provider.sample_corpus(want)
    candidates = [c for c in (chunk_from_document(doc) for doc in raw) if c is not None]
    return candidates, len(raw)


async def _set_state(db_factory, run_id: UUID, **fields) -> None:
    """Patch the run row in its own short-lived session, so progress is visible while running."""
    async with db_factory() as db:
        run = (
            await db.execute(select(SyntheticQuestionRun).where(SyntheticQuestionRun.id == run_id))
        ).scalar_one_or_none()
        if run is None:
            return
        for key, value in fields.items():
            setattr(run, key, value)
        await db.commit()


async def run_synthetic_question_generation(
    *,
    run_id: UUID,
    project_id: UUID,
    provider_id: UUID,
    scope: str,
    partition_key: str | None,
    partition_value: str | None,
    sample_size: int,
    questions_per_chunk: int,
    negative_share: int,
    verify: bool,
    persist: bool,
    per_document_cap: int = DEFAULT_PER_DOCUMENT_CAP,
    dataset_id: UUID | None,
    dataset_name: str | None,
    user_settings: dict | None,
    db_factory,
) -> None:
    provider_obj = None
    embedder = None
    usage = empty_usage()
    try:
        async with db_factory() as db:
            run = (
                await db.execute(
                    select(SyntheticQuestionRun).where(SyntheticQuestionRun.id == run_id)
                )
            ).scalar_one_or_none()
            if run is None:
                raise ValueError(f"Synthetic question run {run_id} not found")
            run.status = "running"
            run.stage = "sampling"
            run.started_at = datetime.now(timezone.utc)

            provider_row = (
                await db.execute(
                    select(IndexProvider).where(
                        IndexProvider.id == provider_id, IndexProvider.project_id == project_id
                    )
                )
            ).scalar_one_or_none()
            if provider_row is None:
                raise ValueError("Index provider not found")
            project_settings = await AnalysisLlmService.load_project_settings(db, project_id)
            await db.commit()

        try:
            llm = AnalysisLlmService(
                user_settings=user_settings, project_settings=project_settings
            )
        except AnalysisLlmConfigError as exc:
            # Nothing can be generated without a model. Fail loudly rather than completing
            # with an empty dataset the user would have to debug themselves.
            raise ValueError(f"No analysis LLM configured: {exc}") from exc

        provider_obj = build_index_provider(provider_row)

        candidates, raw_sampled = await sample_chunks(
            provider_obj,
            scope=scope,
            partition_key=partition_key,
            partition_value=partition_value,
            sample_size=sample_size,
        )
        selection: ChunkSelection = select_chunks(candidates)
        # Spread the pick across documents instead of slicing the head of the sample. Slicing
        # produced benchmarks made of two PDFs, because a backend returns one document's chunks
        # adjacent to each other and its last stratum gets truncated away entirely.
        chunks = diversify(selection.kept, sample_size, per_document_cap=per_document_cap)
        if not chunks:
            raise ValueError(
                "No usable chunks were sampled. Every sampled chunk was empty, too short, "
                "mis-decoded or markup. Check the index and the chunk quality report."
            )
        documents = len({c.document for c in chunks})
        logger.info(
            "Synthetic run %s sampled %d chunks from %d documents (%d raw, %d filtered)",
            run_id, len(chunks), documents, raw_sampled, selection.skipped_total,
        )

        await _set_state(db_factory, run_id, stage="generating", total=len(chunks), processed=0)

        progress = {"done": 0}
        progress_lock = asyncio.Lock()

        async def on_progress(count: int) -> None:
            async with progress_lock:
                progress["done"] += count
                done = progress["done"]
            await _set_state(db_factory, run_id, processed=done)

        questions, gen_usage = await generate_questions(
            llm, chunks, questions_per_chunk, on_progress=on_progress
        )
        add_usage(usage, gen_usage)
        questions, duplicates_dropped = dedupe_questions(questions)

        negatives: list[GeneratedQuestion] = []
        negatives_dropped = 0
        wanted = negatives_wanted(len(questions), negative_share)
        if wanted:
            await _set_state(db_factory, run_id, stage="negatives")
            negatives, neg_usage = await generate_negatives(llm, chunks, wanted)
            add_usage(usage, neg_usage)
            generated_negatives = len(negatives)
            if negatives and verify:
                await _set_state(db_factory, run_id, stage="verifying")
                embedder = build_query_embedder(project_settings)
                negatives, negatives_dropped, verify_usage = await verify_negatives(
                    llm, provider_obj, negatives, embedder=embedder
                )
                add_usage(usage, verify_usage)
        else:
            generated_negatives = 0

        all_questions = questions + negatives
        counts = {
            "chunks_sampled": raw_sampled,
            "chunks_used": len(chunks),
            "documents_used": documents,
            "chunks_skipped": selection.skipped,
            "questions_generated": len(questions),
            "duplicates_dropped": duplicates_dropped,
            "negatives_generated": generated_negatives,
            "negatives_dropped": negatives_dropped,
            "cases_created": 0,
            "labels_created": 0,
        }

        final_dataset_id = dataset_id
        final_dataset_name = dataset_name
        if persist and all_questions:
            await _set_state(db_factory, run_id, stage="persisting")
            async with db_factory() as db:
                dataset = await resolve_dataset(
                    db,
                    project_id,
                    dataset_id=dataset_id,
                    dataset_name=dataset_name,
                    scope=scope,
                    partition_key=partition_key,
                    partition_value=partition_value,
                )
                cases, labels = await persist_questions(
                    db,
                    project_id=project_id,
                    dataset=dataset,
                    run_id=run_id,
                    questions=all_questions,
                    scope=scope,
                    partition_key=partition_key,
                    partition_value=partition_value,
                )
                final_dataset_id = dataset.id
                final_dataset_name = dataset.name
                counts["cases_created"] = cases
                counts["labels_created"] = labels
                await db.commit()

        async with db_factory() as db:
            if usage.total_tokens:
                await record_llm_usage(
                    db,
                    project_id=project_id,
                    service_name=SERVICE_NAME,
                    function_name="run_synthetic_question_generation",
                    provider=llm.provider,
                    model=llm.model,
                    usage=usage,
                    request_metadata={"run_id": str(run_id), "scope": scope},
                )
            final_run = (
                await db.execute(
                    select(SyntheticQuestionRun).where(SyntheticQuestionRun.id == run_id)
                )
            ).scalar_one_or_none()
            # Don't resurrect a run the user cancelled while we were finishing.
            if final_run is not None and final_run.status != "cancelled":
                final_run.results = {
                    "questions": [q.to_dict() for q in all_questions],
                    "counts": counts,
                    "usage": usage_dict(usage),
                }
                final_run.dataset_id = final_dataset_id
                final_run.dataset_name = final_dataset_name
                final_run.processed = len(chunks)
                final_run.status = "completed"
                final_run.stage = None
                final_run.completed_at = datetime.now(timezone.utc)
            await db.commit()
    except asyncio.CancelledError:
        # The cancel endpoint already flipped the row to 'cancelled' before cancelling the task;
        # just stamp the end time.
        logger.info("Synthetic question run %s cancelled", run_id)
        try:
            await _set_state(
                db_factory,
                run_id,
                status="cancelled",
                stage=None,
                completed_at=datetime.now(timezone.utc),
            )
        except Exception:
            logger.exception("Failed to record synthetic question cancellation for %s", run_id)
    except Exception as e:
        logger.exception("Synthetic question run %s failed", run_id)
        try:
            await _set_state(
                db_factory,
                run_id,
                status="failed",
                stage=None,
                error=str(e)[:2000],
                completed_at=datetime.now(timezone.utc),
            )
        except Exception:
            logger.exception("Failed to record synthetic question run error for %s", run_id)
    finally:
        if embedder is not None:
            try:
                await embedder.aclose()
            except Exception:
                logger.debug("Embedder aclose failed", exc_info=True)
        if provider_obj is not None:
            try:
                await provider_obj.aclose()
            except Exception:
                logger.debug("Provider aclose failed", exc_info=True)
