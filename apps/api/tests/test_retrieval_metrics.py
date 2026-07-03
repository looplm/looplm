"""Tests for retrieval-quality metrics (recall@k, precision@k, hit-rate@k)."""

from __future__ import annotations

from app.services.retrieval_metrics import (
    compute_bpref,
    compute_condensed_ndcg_at_k,
    compute_first_relevant_rank,
    compute_hit_rate_at_k,
    compute_mrr,
    compute_ndcg_at_k,
    compute_precision_at_k,
    compute_recall_at_k,
    compute_relevant_retrieved,
    compute_retrieval_metrics,
)


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


# --- precision@k ---

def test_precision_divides_by_cutoff_not_retrieved_count():
    expected = ["https://a.example/p1", "https://b.example/p2"]
    retrieved = ["https://a.example/p1", "https://b.example/p2"]
    # Both retrieved URLs are relevant, but precision@5 divides by the cutoff (5),
    # so two hits in five slots is 0.4 — returning fewer than k still dilutes it.
    assert compute_precision_at_k(expected, retrieved) == {"5": 0.4, "10": 0.2}


def test_precision_counts_only_relevant_in_top_k():
    expected = ["https://a.example/p1"]
    retrieved = ["https://a.example/p1"] + [f"https://x.example/{i}" for i in range(4)]
    # 1 relevant in top-5 -> 0.2; same single hit over top-10 -> 0.1.
    assert compute_precision_at_k(expected, retrieved, ks=(5, 10)) == {"5": 0.2, "10": 0.1}


def test_precision_empty_expected_returns_none():
    assert compute_precision_at_k([], ["https://a.example/p1"]) is None


def test_precision_empty_retrieved_is_zero():
    assert compute_precision_at_k(["https://a.example/p1"], []) == {"5": 0.0, "10": 0.0}


# --- hit-rate@k ---

def test_hit_rate_is_binary_per_k():
    expected = ["https://hit.example/p"]
    # Only relevant URL sits at rank 6: miss within top-5, hit within top-10.
    retrieved = [f"https://miss.example/{i}" for i in range(5)] + ["https://hit.example/p"]
    assert compute_hit_rate_at_k(expected, retrieved) == {"5": 0.0, "10": 1.0}


def test_hit_rate_one_when_any_relevant_present():
    expected = ["https://a.example/p1", "https://b.example/p2"]
    retrieved = ["https://a.example/p1"]
    # A single relevant hit is enough for hit-rate, even though recall would be 0.5.
    assert compute_hit_rate_at_k(expected, retrieved) == {"5": 1.0, "10": 1.0}


def test_hit_rate_empty_expected_returns_none():
    assert compute_hit_rate_at_k([], ["https://a.example/p1"]) is None


def test_hit_rate_empty_retrieved_is_zero():
    assert compute_hit_rate_at_k(["https://a.example/p1"], []) == {"5": 0.0, "10": 0.0}


# --- MRR + first relevant rank ---

def test_mrr_first_position():
    expected = ["https://a.example/p1"]
    retrieved = ["https://a.example/p1", "https://b.example/p2"]
    assert compute_mrr(expected, retrieved) == 1.0


def test_mrr_third_position():
    expected = ["https://hit.example/p"]
    retrieved = ["https://m.example/1", "https://m.example/2", "https://hit.example/p"]
    assert compute_mrr(expected, retrieved) == 1.0 / 3


def test_mrr_zero_when_none_relevant():
    assert compute_mrr(["https://a.example/p1"], ["https://b.example/p2"]) == 0.0


def test_mrr_none_when_no_expected():
    assert compute_mrr([], ["https://a.example/p1"]) is None


def test_first_relevant_rank():
    expected = ["https://hit.example/p"]
    retrieved = ["https://m.example/1", "https://hit.example/p"]
    assert compute_first_relevant_rank(expected, retrieved) == 2
    assert compute_first_relevant_rank(expected, ["https://m.example/1"]) is None


# --- nDCG ---

def test_ndcg_perfect_when_relevant_on_top():
    expected = ["https://a.example/p1", "https://b.example/p2"]
    retrieved = ["https://a.example/p1", "https://b.example/p2", "https://c.example/x"]
    assert compute_ndcg_at_k(expected, retrieved) == {"5": 1.0, "10": 1.0}


def test_ndcg_penalizes_burying_relevant_docs():
    expected = ["https://hit.example/p"]
    # Relevant doc at rank 3 → DCG = 1/log2(4); IDCG = 1/log2(2) = 1.
    buried = ["https://m.example/1", "https://m.example/2", "https://hit.example/p"]
    ndcg = compute_ndcg_at_k(expected, buried)
    import math
    assert ndcg["5"] == (1.0 / math.log2(4))
    assert ndcg["5"] < 1.0


def test_ndcg_none_when_no_expected():
    assert compute_ndcg_at_k([], ["https://a.example/p1"]) is None


# --- combined helper ---

def test_compute_retrieval_metrics_bundles_all():
    expected = ["https://a.example/p1"]
    retrieved = ["https://a.example/p1"]
    m = compute_retrieval_metrics(expected, retrieved)
    assert m is not None
    assert set(m) == {
        "recall_at_k",
        "precision_at_k",
        "hit_rate_at_k",
        "ndcg_at_k",
        "mrr",
        "first_relevant_rank",
        "relevant_count",
        "relevant_retrieved_at_k",
        "relevant_retrieved_total",
    }
    assert m["mrr"] == 1.0
    assert m["first_relevant_rank"] == 1
    assert m["relevant_count"] == 1
    assert m["relevant_retrieved_total"] == 1


def test_compute_retrieval_metrics_none_without_truth():
    assert compute_retrieval_metrics([], ["https://a.example/p1"]) is None


def test_compute_relevant_retrieved_ceiling_vs_at_k():
    # 3 relevant docs; one sits at rank 5 (past k=3), one is never retrieved.
    expected = ["r1", "r2", "r3"]
    retrieved = ["r1", "x", "x2", "x3", "r2"]  # r1@1, r2@5, r3 missing
    rr = compute_relevant_retrieved(expected, retrieved, ks=(3, 20))
    assert rr is not None
    assert rr["relevant_count"] == 3
    assert rr["at_k"]["3"] == 1  # only r1 inside top-3
    assert rr["at_k"]["20"] == 2  # r1 + r2 within the full list
    assert rr["total"] == 2  # ceiling: r1 + r2 surfaced anywhere, r3 never retrieved


def test_compute_relevant_retrieved_none_without_truth():
    assert compute_relevant_retrieved([], ["r1"]) is None


# --- bpref (incomplete-judgment-safe) ---

def test_bpref_perfect_when_relevant_ranked_above_nonrelevant():
    # Both relevant chunks retrieved, no judged-non-relevant ranked above them.
    assert compute_bpref({"r1", "r2"}, {"n1"}, ["r1", "r2", "n1"]) == 1.0


def test_bpref_ignores_unjudged_chunks():
    # "u1"/"u2" are unjudged — dropped from scoring, so this scores like ["r1"].
    rel, nonrel = {"r1"}, {"n1"}
    with_unjudged = compute_bpref(rel, nonrel, ["u1", "r1", "u2", "n1"])
    without = compute_bpref(rel, nonrel, ["r1", "n1"])
    assert with_unjudged == without == 1.0


def test_bpref_penalizes_nonrelevant_ranked_above_relevant():
    # R=1, N=1, denom=1; one non-relevant ranked above the relevant chunk → term 1-1/1 = 0.
    assert compute_bpref({"r1"}, {"n1"}, ["n1", "r1"]) == 0.0


def test_bpref_unretrieved_relevant_lowers_score():
    # R=2 but only one relevant retrieved, no non-relevant → 1/2.
    assert compute_bpref({"r1", "r2"}, set(), ["r1"]) == 0.5


def test_bpref_no_nonrelevant_reduces_to_relevant_fraction():
    # denom=0 → penalty term vanishes; both relevant retrieved → 1.0.
    assert compute_bpref({"r1", "r2"}, set(), ["r1", "r2"]) == 1.0


def test_bpref_none_without_relevant():
    assert compute_bpref(set(), {"n1"}, ["n1"]) is None


# --- condensed nDCG (incomplete-judgment-safe) ---

def test_condensed_ndcg_drops_unjudged_before_discount():
    # "u1" at rank 1 is unjudged: condensed away, so the relevant chunk is effectively rank 1
    # → perfect, unlike raw nDCG which would discount it for sitting at rank 2.
    out = compute_condensed_ndcg_at_k({"r1"}, {"n1"}, ["u1", "r1", "n1"])
    assert out == {"5": 1.0, "10": 1.0}


def test_condensed_ndcg_penalizes_nonrelevant_above_relevant():
    import math
    # Condensed ranking is [n1, r1] (both judged); relevant at condensed rank 2.
    out = compute_condensed_ndcg_at_k({"r1"}, {"n1"}, ["n1", "r1"])
    assert out["5"] == 1.0 / math.log2(3)
    assert out["5"] < 1.0


def test_condensed_ndcg_none_without_relevant():
    assert compute_condensed_ndcg_at_k(set(), {"n1"}, ["n1"]) is None
