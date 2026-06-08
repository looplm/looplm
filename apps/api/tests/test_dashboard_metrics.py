"""Tests for the dashboard latency-percentile and thread aggregations.

These exercise the pure helpers directly. The full ``/api/dashboard/stats``
endpoint relies on Postgres ``cast(..., Date)`` in its daily-trend query, which
the SQLite test database does not support — see CLAUDE.md on Postgres-only
behavior not being exercised in tests.
"""

from app.routers.dashboard import (
    _compute_latency,
    _compute_regressions,
    _compute_thread_metrics,
    _percentile,
    _regression_flag,
)


def test_percentile_basic():
    vals = list(range(1, 101))  # 1..100, pre-sorted
    assert _percentile([], 50) is None
    assert _percentile([42], 95) == 42
    assert _percentile(vals, 50) == 50  # interpolated median of 1..100
    assert _percentile(vals, 99) == 99


def test_compute_latency():
    lat = _compute_latency([300, 100, 900, 200])
    assert lat.count == 4
    assert lat.p50_ms is not None
    assert lat.p99_ms >= lat.p95_ms >= lat.p50_ms
    assert lat.p99_ms <= 900

    empty = _compute_latency([])
    assert empty.count == 0
    assert empty.p50_ms is None


def test_compute_thread_metrics():
    # Thread A: 3 traces incl. 1 failure (continued → retry). Thread B: single turn.
    rows = [(3, 1), (1, 0)]
    m = _compute_thread_metrics(rows)
    assert m.total_threads == 2
    assert m.multi_turn_threads == 1
    assert m.multi_turn_rate == 0.5
    assert m.avg_thread_length == 2.0  # (3 + 1) / 2
    assert m.retry_rate == 1.0  # the one failing thread continued past the failure


def test_compute_thread_metrics_no_retry():
    # A thread whose only traces are all failures did not continue → no retry.
    m = _compute_thread_metrics([(2, 2), (1, 0)])
    assert m.retry_rate == 0.0


def test_compute_thread_metrics_empty():
    m = _compute_thread_metrics([])
    assert m.total_threads == 0
    assert m.multi_turn_rate == 0.0
    assert m.avg_thread_length == 0.0
    assert m.p95_thread_length == 0
    assert m.retry_rate == 0.0


def test_regression_flag_detects_material_increase():
    flag = _regression_flag("failure_rate", "Failure rate", current=0.30, previous=0.10)
    assert flag.regressed is True
    assert flag.change_pct == 2.0  # +200%


def test_regression_flag_ignores_small_change_and_no_baseline():
    assert _regression_flag("latency_p95", "p95", 1050.0, 1000.0).regressed is False  # +5%
    # No baseline → never flagged (avoids noise on first-ever window).
    assert _regression_flag("failure_rate", "Failure rate", 0.5, 0.0).regressed is False


def test_compute_regressions_returns_only_regressed():
    flags = _compute_regressions(
        cur_failure_rate=0.4, prev_failure_rate=0.1,  # regressed
        cur_p95=1000, prev_p95=1000,                  # flat
    )
    assert [f.metric for f in flags] == ["failure_rate"]
