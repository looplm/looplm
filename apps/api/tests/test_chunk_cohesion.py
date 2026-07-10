"""Unit tests for embedding cohesion (fake embedder, pure vector math)."""

import pytest

from app.services.chunk_cohesion import (
    HIGH_SPREAD_THRESHOLD,
    analyze_cohesion,
    cosine,
    smear_score,
    split_sentences,
)


# ── Sentence splitting ───────────────────────────────────────────────────────

def test_split_sentences_english_and_german():
    text = (
        "The reactor must be cooled before maintenance. Die Wartung erfolgt "
        "quartalsweise durch Fachpersonal. Safety goggles are required at all times."
    )
    sentences = split_sentences(text, max_sentences=10)
    assert len(sentences) == 3
    assert sentences[1].startswith("Die Wartung")


def test_split_sentences_drops_short_fragments_and_caps():
    text = "Ok. " + " ".join(f"This is a proper sentence number {i} indeed." for i in range(10))
    sentences = split_sentences(text, max_sentences=4)
    assert len(sentences) == 4
    assert all(len(s) >= 20 for s in sentences)


def test_split_on_hard_breaks():
    text = "First paragraph talks about topic one.\n\nSecond paragraph is different."
    assert len(split_sentences(text, max_sentences=10)) == 2


# ── Vector math ──────────────────────────────────────────────────────────────

def test_cosine_identical_and_orthogonal():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0  # zero vector guarded


def test_smear_score_tight_vs_smeared():
    tight = [[1.0, 0.0]] * 4
    assert smear_score(tight) == pytest.approx(0.0)
    smeared = [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0], [0.0, 1.0]]
    # 4 of 6 pairs are orthogonal (distance 1), 2 identical (distance 0).
    assert smear_score(smeared) == pytest.approx(4 / 6, abs=1e-4)
    assert smear_score([[1.0, 0.0]]) == 0.0  # under two vectors: no spread


# ── Corpus pass with a fake embedder ─────────────────────────────────────────

class FakeEmbedder:
    """Maps sentences to axis vectors by keyword so spread is deterministic."""

    async def embed_batch(self, texts):
        return [[0.0, 1.0] if "veterinary" in t else [1.0, 0.0] for t in texts]


def _sentences(topic: str, n: int) -> str:
    return " ".join(f"This sentence number {i} is about {topic} procedures." for i in range(n))


@pytest.mark.asyncio
async def test_analyze_cohesion_flags_multi_topic_chunks():
    docs = [
        {"id": "tight", "chunk_text": _sentences("reactor", 4)},
        {
            "id": "smeared",
            "chunk_text": (
                "This sentence number 0 is about reactor procedures. "
                "This sentence number 1 is about veterinary procedures. "
                "This sentence number 2 is about reactor procedures. "
                "This sentence number 3 is about veterinary procedures."
            ),
        },
        {"id": "short", "chunk_text": "Too short to score."},
    ]
    metrics, findings = await analyze_cohesion(
        FakeEmbedder(), docs,
        text_field="chunk_text", id_field="id", sample_size=10, max_sentences=30,
    )
    assert metrics["available"]
    assert metrics["sampled"] == 2      # the short chunk is skipped (< 3 sentences)
    assert metrics["scored"] == 2
    assert metrics["high_spread"] == 1
    assert metrics["high_spread_pct"] == 50.0
    assert metrics["threshold"] == HIGH_SPREAD_THRESHOLD
    assert metrics["examples"][0]["chunk_id"] == "smeared"
    assert any(f.title == "Multi-topic chunks" for f in findings)


@pytest.mark.asyncio
async def test_analyze_cohesion_respects_sample_size():
    docs = [{"id": str(i), "chunk_text": _sentences("reactor", 3)} for i in range(5)]
    metrics, _ = await analyze_cohesion(
        FakeEmbedder(), docs,
        text_field="chunk_text", id_field="id", sample_size=2, max_sentences=30,
    )
    assert metrics["sampled"] == 2
    assert metrics["sentences_embedded"] == 6
