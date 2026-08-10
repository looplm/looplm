"""Persist generated questions as a test dataset with its ground truth attached.

Generation produces questions; this turns them into the rows the rest of LoopLM already knows
how to evaluate:

* a :class:`TestDataset` + one :class:`TestCase` per question;
* for every answerable question, a :class:`ChunkRelevanceLabel` on its source chunk at the
  highest grade, under the ``Synthetic`` annotator. That label *is* the ground truth: it feeds
  ``resolve_project_gold(gold_source="synthetic")``, which is what lets the by-stage retrieval
  metrics score the dataset against a live index with no eval run and no human labeling;
* a :class:`TestCaseLabelingStatus` marking each case complete, so synthetic cases do not sit
  in the labeling workbench's in-progress tab asking for judgments they do not need.

Negative (unanswerable) questions get a case and the ``no-retrieval-expected`` tag but no label:
there is no chunk that should be retrieved, which is the point.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk_labels import (
    DEFAULT_SLICE,
    GRADE_MAX,
    SYNTHETIC_ANNOTATOR,
    ChunkRelevanceLabel,
    TestCaseLabelingStatus,
)
from app.models.datasets import NO_RETRIEVAL_TAG, TestCase, TestDataset
from app.services.synthetic_questions import GeneratedQuestion

# Tag every generated case carries, so a synthetic dataset is filterable and a reviewer can tell
# at a glance that a case was not written by a person.
SYNTHETIC_TAG = "synthetic"
NEGATIVE_TAG = "synthetic-negative"


def default_dataset_name(scope: str, partition_key: str | None, partition_value: str | None) -> str:
    """A readable dataset name describing what the run covered."""
    if scope == "partition" and partition_key and partition_value:
        label = f"{partition_key} = {partition_value}"
    else:
        label = "Whole index"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"Synthetic · {label} · {today}"[:255]


def build_test_id(run_id: UUID, index: int) -> str:
    """Stable per-question identity, unique across runs.

    Chunk labels are keyed by ``(project, test_id, chunk_id)`` and are not scoped to a dataset,
    so two runs reusing a test_id would silently share ground truth. The run's id prefix keeps
    them apart.
    """
    return f"syn-{run_id.hex[:8]}-{index:04d}"


async def resolve_dataset(
    db: AsyncSession,
    project_id: UUID,
    *,
    dataset_id: UUID | None,
    dataset_name: str | None,
    scope: str,
    partition_key: str | None,
    partition_value: str | None,
) -> TestDataset:
    """The dataset to write into: an existing one when given, else a newly created one.

    Raises ``ValueError`` when ``dataset_id`` names a dataset in another project, rather than
    creating a second one silently.
    """
    if dataset_id is not None:
        dataset = (
            await db.execute(
                select(TestDataset).where(
                    TestDataset.id == dataset_id, TestDataset.project_id == project_id
                )
            )
        ).scalar_one_or_none()
        if dataset is None:
            raise ValueError("Target dataset not found")
        return dataset

    name = (dataset_name or "").strip() or default_dataset_name(
        scope, partition_key, partition_value
    )
    dataset = TestDataset(
        project_id=project_id,
        name=name[:255],
        description=(
            "Generated from indexed chunks. Each answerable question's source chunk is its "
            "ground truth, labeled under the Synthetic annotator."
        ),
        tags=[SYNTHETIC_TAG],
    )
    db.add(dataset)
    await db.flush()
    return dataset


async def persist_questions(
    db: AsyncSession,
    *,
    project_id: UUID,
    dataset: TestDataset,
    run_id: UUID,
    questions: Sequence[GeneratedQuestion],
    scope: str,
    partition_key: str | None,
    partition_value: str | None,
) -> tuple[int, int]:
    """Write cases + gold labels for ``questions``. Returns ``(cases, labels)``.

    Does not commit — the caller owns the transaction so a failure halfway through leaves no
    half-populated dataset behind.
    """
    cases = 0
    labels = 0
    for i, question in enumerate(questions, start=1):
        test_id = build_test_id(run_id, i)
        is_negative = question.style == "negative"
        tags = [SYNTHETIC_TAG, NEGATIVE_TAG, NO_RETRIEVAL_TAG] if is_negative else [
            SYNTHETIC_TAG,
            question.style,
        ]
        db.add(
            TestCase(
                dataset_id=dataset.id,
                test_id=test_id,
                prompt=question.text,
                tags=tags,
                test_case_metadata={
                    "synthetic": {
                        "run_id": str(run_id),
                        "style": question.style,
                        "source_chunk_id": question.source_chunk_id,
                        "source_title": question.source_title,
                        "source_url": question.source_url,
                        "scope": scope,
                        "partition_key": partition_key,
                        "partition_value": partition_value,
                    }
                },
                # Generated, not reviewed. The dataset's normal review flow applies.
                validated=False,
            )
        )
        cases += 1

        if not is_negative and question.source_chunk_id:
            db.add(
                ChunkRelevanceLabel(
                    project_id=project_id,
                    test_id=test_id,
                    chunk_id=question.source_chunk_id,
                    relevance=GRADE_MAX,
                    content_preview=question.source_preview,
                    url=question.source_url,
                    title=question.source_title,
                    annotator=SYNTHETIC_ANNOTATOR,
                    labeled_by=None,
                )
            )
            labels += 1

        # The gold is definitional, so there is nothing left for a human to judge on this case.
        db.add(
            TestCaseLabelingStatus(
                project_id=project_id,
                test_id=test_id,
                complete=True,
                slice=DEFAULT_SLICE,
                marked_by=None,
            )
        )
    return cases, labels
