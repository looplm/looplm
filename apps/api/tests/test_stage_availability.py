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


# --- errored cases leave a stage's average, empty rankings stay as misses -------


def _build_with_failures(retrieved_by_stage, failed_by_stage):
    return build_by_stage_metrics(
        CASES,
        retrieved_by_stage,
        RELEVANT,
        {},
        GRADES,
        {},
        stage_labels=(("hybrid", "RRF"), ("cohere_rerank", "Cohere rerank")),
        failed_by_stage=failed_by_stage,
    )


def test_errored_case_is_excluded_not_scored_as_a_miss():
    # Cohere answered t1 correctly and errored on t2. Scoring t2 as a miss would report 50%;
    # excluding it reports 100% over the one case it actually measured.
    stages, _rows, _evaluated = _build_with_failures(
        {"hybrid": {"t1": ["c1"], "t2": ["c2"]}, "cohere_rerank": {"t1": ["c1"]}},
        {"cohere_rerank": {"t2": "HTTP 429: RateLimitReached"}},
    )
    cohere = next(s for s in stages if s.stage == "cohere_rerank")
    assert cohere.available is True
    assert cohere.cases_failed == 1
    assert cohere.evaluated_cases == 1
    assert (cohere.recall_at_k or {}).get("10") == 1.0
    assert "RateLimit" in (cohere.failure_reason or "")


def test_a_stage_that_returned_nothing_still_takes_the_miss():
    # No failure recorded: the head ran and produced nothing for t2, which is a real miss.
    stages, _rows, _evaluated = _build_with_failures(
        {"hybrid": {"t1": ["c1"], "t2": ["c2"]}, "cohere_rerank": {"t1": ["c1"]}}, {}
    )
    cohere = next(s for s in stages if s.stage == "cohere_rerank")
    assert cohere.cases_failed == 0
    assert cohere.evaluated_cases == 2
    assert (cohere.recall_at_k or {}).get("10") == 0.5


def test_failures_on_one_stage_do_not_touch_another():
    stages, _rows, _evaluated = _build_with_failures(
        {"hybrid": {"t1": ["c1"], "t2": ["c2"]}, "cohere_rerank": {"t1": ["c1"]}},
        {"cohere_rerank": {"t2": "boom"}},
    )
    hybrid = next(s for s in stages if s.stage == "hybrid")
    assert hybrid.cases_failed == 0
    assert hybrid.evaluated_cases == 2
    assert (hybrid.recall_at_k or {}).get("10") == 1.0


def test_stage_failing_every_case_reports_no_evaluated_cases():
    stages, _rows, _evaluated = _build_with_failures(
        {"hybrid": {"t1": ["c1"], "t2": ["c2"]}},
        {"cohere_rerank": {"t1": "boom", "t2": "boom"}},
    )
    cohere = next(s for s in stages if s.stage == "cohere_rerank")
    assert cohere.available is False
    assert cohere.cases_failed == 2
    assert cohere.evaluated_cases == 0
