"""Gold resolution for synthetic labels, and the dataset persistence that writes them."""

import pytest
from sqlalchemy import select

from app.models.chunk_labels import (
    AI_ANNOTATOR,
    GRADE_MAX,
    SYNTHETIC_ANNOTATOR,
    ChunkRelevanceLabel,
    TestCaseLabelingStatus,
)
from app.models.datasets import NO_RETRIEVAL_TAG, TestCase
from app.services.chunk_gold import resolve_project_gold
from app.services.synthetic_dataset import (
    NEGATIVE_TAG,
    SYNTHETIC_TAG,
    build_test_id,
    default_dataset_name,
    persist_questions,
    resolve_dataset,
)
from app.services.synthetic_questions import GeneratedQuestion


async def _label(db, project_id, test_id, chunk_id, relevance, *, annotator=None, user_id=None):
    db.add(
        ChunkRelevanceLabel(
            project_id=project_id,
            test_id=test_id,
            chunk_id=chunk_id,
            relevance=relevance,
            annotator=annotator,
            labeled_by=user_id,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_synthetic_gold_source_sees_only_synthetic_labels(
    db_session, test_project, test_user
):
    await _label(db_session, test_project.id, "t1", "chunk-syn", GRADE_MAX,
                 annotator=SYNTHETIC_ANNOTATOR)
    await _label(db_session, test_project.id, "t1", "chunk-human", 3, user_id=test_user.id)
    await _label(db_session, test_project.id, "t1", "chunk-ai", 3, annotator=AI_ANNOTATOR)

    relevant, _non, grades = await resolve_project_gold(db_session, test_project, "synthetic")
    assert relevant == {"t1": {"chunk-syn"}}
    assert grades["t1"]["chunk-syn"] == GRADE_MAX


@pytest.mark.asyncio
async def test_human_ai_and_both_exclude_synthetic_labels(db_session, test_project, test_user):
    await _label(db_session, test_project.id, "t1", "chunk-syn", GRADE_MAX,
                 annotator=SYNTHETIC_ANNOTATOR)
    await _label(db_session, test_project.id, "t1", "chunk-human", 3, user_id=test_user.id)
    await _label(db_session, test_project.id, "t1", "chunk-ai", 3, annotator=AI_ANNOTATOR)

    human, _n, _g = await resolve_project_gold(db_session, test_project, "human")
    ai, _n, _g = await resolve_project_gold(db_session, test_project, "ai")
    both, _n, _g = await resolve_project_gold(db_session, test_project, "both")

    assert human == {"t1": {"chunk-human"}}
    assert ai == {"t1": {"chunk-ai"}}
    assert both == {"t1": {"chunk-human", "chunk-ai"}}


@pytest.mark.asyncio
async def test_synthetic_source_is_empty_without_synthetic_labels(
    db_session, test_project, test_user
):
    await _label(db_session, test_project.id, "t1", "chunk-human", 3, user_id=test_user.id)
    relevant, _non, _grades = await resolve_project_gold(db_session, test_project, "synthetic")
    assert relevant == {}


# --- persistence ---------------------------------------------------------------


def test_default_dataset_name_describes_the_scope():
    assert default_dataset_name("partition", "tags", "finance").startswith(
        "Synthetic · tags = finance · "
    )
    assert default_dataset_name("corpus", None, None).startswith("Synthetic · Whole index · ")


def test_test_ids_are_unique_across_runs():
    from uuid import uuid4

    run_a, run_b = uuid4(), uuid4()
    assert build_test_id(run_a, 1) != build_test_id(run_b, 1)
    assert build_test_id(run_a, 1) != build_test_id(run_a, 2)


@pytest.mark.asyncio
async def test_persist_writes_cases_gold_labels_and_completion(db_session, test_project):
    from uuid import uuid4

    run_id = uuid4()
    dataset = await resolve_dataset(
        db_session,
        test_project.id,
        dataset_id=None,
        dataset_name=None,
        scope="corpus",
        partition_key=None,
        partition_value=None,
    )
    questions = [
        GeneratedQuestion(
            text="Innerhalb welcher Frist werden Reisekosten erstattet?",
            style="factual",
            source_chunk_id="page_1_chunk_0",
            source_title="Policy",
            source_url="https://intranet/policy",
            source_preview="Die Erstattung erfolgt in 14 Tagen.",
        ),
        GeneratedQuestion(text="Wie hoch ist die Pauschale in Japan?", style="negative"),
    ]
    cases, labels = await persist_questions(
        db_session,
        project_id=test_project.id,
        dataset=dataset,
        run_id=run_id,
        questions=questions,
        scope="corpus",
        partition_key=None,
        partition_value=None,
    )
    await db_session.commit()

    assert (cases, labels) == (2, 1)
    assert SYNTHETIC_TAG in (dataset.tags or [])

    rows = (
        await db_session.execute(
            select(TestCase).where(TestCase.dataset_id == dataset.id).order_by(TestCase.test_id)
        )
    ).scalars().all()
    assert [r.prompt for r in rows] == [q.text for q in questions]
    assert rows[0].test_case_metadata["synthetic"]["source_chunk_id"] == "page_1_chunk_0"
    assert rows[0].validated is False
    # The negative is excluded from retrieval aggregation by the existing tag.
    assert NO_RETRIEVAL_TAG in rows[1].tags
    assert NEGATIVE_TAG in rows[1].tags
    assert NO_RETRIEVAL_TAG not in rows[0].tags

    label_rows = (
        await db_session.execute(
            select(ChunkRelevanceLabel).where(ChunkRelevanceLabel.project_id == test_project.id)
        )
    ).scalars().all()
    assert len(label_rows) == 1
    assert label_rows[0].chunk_id == "page_1_chunk_0"
    assert label_rows[0].relevance == GRADE_MAX
    assert label_rows[0].annotator == SYNTHETIC_ANNOTATOR
    assert label_rows[0].labeled_by is None

    statuses = (
        await db_session.execute(
            select(TestCaseLabelingStatus).where(
                TestCaseLabelingStatus.project_id == test_project.id
            )
        )
    ).scalars().all()
    assert len(statuses) == 2
    assert all(s.complete for s in statuses)


@pytest.mark.asyncio
async def test_persisted_labels_resolve_as_synthetic_gold(db_session, test_project):
    from uuid import uuid4

    run_id = uuid4()
    dataset = await resolve_dataset(
        db_session,
        test_project.id,
        dataset_id=None,
        dataset_name="Synthetic set",
        scope="corpus",
        partition_key=None,
        partition_value=None,
    )
    await persist_questions(
        db_session,
        project_id=test_project.id,
        dataset=dataset,
        run_id=run_id,
        questions=[
            GeneratedQuestion(
                text="Innerhalb welcher Frist werden Reisekosten erstattet?",
                style="factual",
                source_chunk_id="page_1_chunk_0",
            )
        ],
        scope="corpus",
        partition_key=None,
        partition_value=None,
    )
    await db_session.commit()

    relevant, _non, _grades = await resolve_project_gold(db_session, test_project, "synthetic")
    assert relevant == {build_test_id(run_id, 1): {"page_1_chunk_0"}}


@pytest.mark.asyncio
async def test_resolve_dataset_rejects_a_dataset_from_another_project(db_session, test_project):
    from uuid import uuid4

    with pytest.raises(ValueError):
        await resolve_dataset(
            db_session,
            test_project.id,
            dataset_id=uuid4(),
            dataset_name=None,
            scope="corpus",
            partition_key=None,
            partition_value=None,
        )
