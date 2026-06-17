"""Tests for retrieval-quality metrics (recall@k)."""

from __future__ import annotations

from app.services.retrieval_metrics import compute_recall_at_k


def test_recall_full_hit():
    expected = ["https://a.example/p1", "https://b.example/p2"]
    retrieved = ["https://a.example/p1", "https://b.example/p2"]
    assert compute_recall_at_k(expected, retrieved) == {"5": 1.0, "10": 1.0}


def test_recall_partial():
    expected = ["https://a.example/p1", "https://b.example/p2"]
    retrieved = ["https://a.example/p1", "https://c.example/other"]
    assert compute_recall_at_k(expected, retrieved) == {"5": 0.5, "10": 0.5}


def test_recall_respects_k_cutoff():
    expected = ["https://hit.example/p"]
    # The only relevant URL sits at rank 6, so recall@5 misses it, recall@10 finds it.
    retrieved = [f"https://miss.example/{i}" for i in range(5)] + ["https://hit.example/p"]
    assert compute_recall_at_k(expected, retrieved) == {"5": 0.0, "10": 1.0}


def test_recall_empty_expected_returns_none():
    assert compute_recall_at_k([], ["https://a.example/p1"]) is None


def test_recall_empty_retrieved_is_zero():
    assert compute_recall_at_k(["https://a.example/p1"], []) == {"5": 0.0, "10": 0.0}


def test_recall_normalizes_confluence_slugs_on_both_sides():
    # Expected carries a trailing slug; retrieved is already trimmed. Normalization
    # on both sides makes them match instead of registering a false miss.
    expected = ["https://co.example/wiki/spaces/AB/pages/123/Some-Title"]
    retrieved = ["https://co.example/wiki/spaces/AB/pages/123"]
    assert compute_recall_at_k(expected, retrieved) == {"5": 1.0, "10": 1.0}


def test_recall_dedupes_expected():
    expected = ["https://a.example/p1", "https://a.example/p1"]
    retrieved = ["https://a.example/p1"]
    # Duplicate expected collapses to one relevant doc — recall is 1.0, not 0.5.
    assert compute_recall_at_k(expected, retrieved) == {"5": 1.0, "10": 1.0}


def test_recall_custom_ks():
    expected = ["https://a.example/p1"]
    retrieved = ["https://a.example/p1"]
    assert compute_recall_at_k(expected, retrieved, ks=(1, 3)) == {"1": 1.0, "3": 1.0}
