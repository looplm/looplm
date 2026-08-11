"""Unit tests for the generation worker's pure parts: negative sizing and chunk sampling."""

import pytest

from app.index_providers.base import CorpusDoc
from app.routers.synthetic_questions_worker import negatives_wanted, sample_chunks


class _FakeProvider:
    def __init__(self, corpus=None, partition_docs=None):
        self.corpus = corpus or []
        self.partition_docs = partition_docs or []
        self.corpus_calls = []
        self.partition_calls = []

    async def sample_corpus(self, n, *, stratify_by=None):
        self.corpus_calls.append(n)
        return self.corpus[:n]

    async def sample_documents(self, key, value, n, filters=None, *, spread=False):
        self.partition_calls.append((key, value, n, spread))
        return self.partition_docs[:n]


# --- negatives_wanted ----------------------------------------------------------


def test_negatives_wanted_is_a_share_of_the_total_not_of_the_positives():
    # 18 negatives out of 118 questions is ~15%; 15 out of 115 would be ~13%.
    assert negatives_wanted(100, 15) == 18
    total = 100 + negatives_wanted(100, 15)
    assert 0.14 < negatives_wanted(100, 15) / total < 0.16


@pytest.mark.parametrize("share", [0, -5])
def test_negatives_wanted_is_zero_when_disabled(share):
    assert negatives_wanted(100, share) == 0


def test_negatives_wanted_is_zero_without_positives():
    assert negatives_wanted(0, 20) == 0


def test_negatives_wanted_rounds_up_to_at_least_one():
    assert negatives_wanted(2, 10) == 1


# --- sample_chunks -------------------------------------------------------------


@pytest.mark.asyncio
async def test_corpus_sampling_overdraws_and_resolves_fields():
    provider = _FakeProvider(
        corpus=[
            {"id": f"page_1_chunk_{i}", "chunk_text": f"Body {i}", "page_title": "T"}
            for i in range(100)
        ]
    )
    chunks, raw = await sample_chunks(
        provider, scope="corpus", partition_key=None, partition_value=None, sample_size=10
    )
    # Junk filtering and the per-document cap both eat into the draw, so it is deliberately
    # much larger than the target.
    assert provider.corpus_calls == [40]
    assert raw == 40
    assert len(chunks) == 40
    assert chunks[0].chunk_id == "page_1_chunk_0"
    assert chunks[0].title == "T"


@pytest.mark.asyncio
async def test_corpus_sampling_skips_documents_with_no_key_or_text():
    provider = _FakeProvider(
        corpus=[
            {"id": "a", "chunk_text": "Body"},
            {"chunk_text": "no key"},
            {"id": "c"},
        ]
    )
    chunks, raw = await sample_chunks(
        provider, scope="corpus", partition_key=None, partition_value=None, sample_size=10
    )
    assert [c.chunk_id for c in chunks] == ["a"]
    assert raw == 3


@pytest.mark.asyncio
async def test_partition_sampling_spreads_across_the_slice():
    provider = _FakeProvider(
        partition_docs=[
            CorpusDoc(id=f"c{i}", snippet=f"Body {i}", title="T", url="https://x")
            for i in range(50)
        ]
    )
    chunks, raw = await sample_chunks(
        provider,
        scope="partition",
        partition_key="tags",
        partition_value="finance",
        sample_size=10,
    )
    # spread=True: without it, one large document supplies the whole sample.
    assert provider.partition_calls == [("tags", "finance", 40, True)]
    assert raw == 40
    assert chunks[0].chunk_id == "c0"
    assert chunks[0].url == "https://x"


@pytest.mark.asyncio
async def test_partition_sampling_requires_a_key_and_value():
    provider = _FakeProvider()
    with pytest.raises(ValueError):
        await sample_chunks(
            provider,
            scope="partition",
            partition_key="tags",
            partition_value=None,
            sample_size=10,
        )
