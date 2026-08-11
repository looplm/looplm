"""A by-stage head that returned no ranking must report as unavailable, never as a scored 0."""

from app.services.retrieval_metrics_aggregate import build_by_stage_metrics

CASES = [("t1", "query one"), ("t2", "query two")]
RELEVANT = {"t1": {"c1"}, "t2": {"c2"}}
GRADES = {"t1": {"c1": 3}, "t2": {"c2": 3}}


def _build(retrieved_by_stage):
    return build_by_stage_metrics(
        CASES,
        retrieved_by_stage,
        RELEVANT,
        {},
        GRADES,
        {},
        stage_labels=(("hybrid", "RRF"), ("cohere_rerank", "Cohere rerank")),
    )


def test_stage_with_no_rankings_is_unavailable():
    stages, _rows, _evaluated = _build({"hybrid": {"t1": ["c1"], "t2": ["c2"]}})
    by_stage = {s.stage: s for s in stages}
    assert by_stage["hybrid"].available is True
    # Cohere returned nothing for any case: unconfigured, failed, or nothing to run.
    assert by_stage["cohere_rerank"].available is False
    assert by_stage["cohere_rerank"].evaluated_cases == 0


def test_unavailable_stage_does_not_count_toward_evaluated_cases():
    _stages, _rows, evaluated = _build({"cohere_rerank": {}})
    assert evaluated == 0


def test_unavailable_stage_leaves_per_case_cells_empty():
    _stages, rows, _evaluated = _build({"hybrid": {"t1": ["c1"], "t2": ["c2"]}})
    for row in rows:
        assert "hybrid" in row.recall_by_stage
        # An empty cell, not a 0.0 that reads as "this stage scored nothing".
        assert "cohere_rerank" not in row.recall_by_stage
        assert "cohere_rerank" not in row.ndcg_by_stage


def test_a_stage_that_ran_and_genuinely_missed_stays_available():
    # Retrieved the wrong chunks everywhere: a real 0, which must NOT be hidden as unavailable.
    stages, _rows, evaluated = _build(
        {"hybrid": {"t1": ["c1"], "t2": ["c2"]}, "cohere_rerank": {"t1": ["zz"], "t2": ["zz"]}}
    )
    cohere = next(s for s in stages if s.stage == "cohere_rerank")
    assert cohere.available is True
    assert cohere.evaluated_cases == 2
    assert (cohere.recall_at_k or {}).get("10") == 0.0
    assert evaluated == 2
