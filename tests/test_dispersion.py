"""Tests for historic_fundamentals/dispersion.py — pure functions, no database."""

from datetime import date, timedelta

import pytest

from historic_fundamentals.dispersion import (
    MIN_EPS_ABS,
    compute_metrics,
    percentile,
    select_horizons,
)


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

def test_normal_case_dispersion():
    row = {"eps_avg": 12.7644, "eps_high": 16.00, "eps_low": 9.65}
    m = compute_metrics(row)
    assert m["eps_dispersion"] == pytest.approx(0.4975, abs=1e-3)


def test_eps_floor_near_zero_is_null():
    row = {"eps_avg": 0.05, "eps_high": 1.0, "eps_low": 0.5}
    assert compute_metrics(row)["eps_dispersion"] is None


def test_eps_floor_negative_is_null():
    row = {"eps_avg": -2.0, "eps_high": 1.0, "eps_low": -3.0}
    assert compute_metrics(row)["eps_dispersion"] is None


def test_eps_floor_boundary_is_inclusive():
    row = {"eps_avg": MIN_EPS_ABS, "eps_high": 0.2, "eps_low": 0.05}
    m = compute_metrics(row)
    assert m["eps_dispersion"] == pytest.approx((0.2 - 0.05) / MIN_EPS_ABS)


def test_missing_inputs_yield_null_for_that_metric_only():
    row = {"eps_avg": 10.0, "eps_high": None, "eps_low": 8.0, "eps_count": 12}
    m = compute_metrics(row)
    assert m["eps_dispersion"] is None
    assert m["coverage"] == 12


def test_net_revisions_30d_normal():
    row = {"eps_rev_up_30d": 1, "eps_rev_down_30d": 4}
    assert compute_metrics(row)["net_revisions_30d"] == -3


def test_net_revisions_30d_both_null():
    row = {"eps_rev_up_30d": None, "eps_rev_down_30d": None}
    assert compute_metrics(row)["net_revisions_30d"] is None


def test_net_revisions_30d_both_zero_is_zero_not_null():
    row = {"eps_rev_up_30d": 0, "eps_rev_down_30d": 0}
    assert compute_metrics(row)["net_revisions_30d"] == 0


def test_net_revisions_30d_one_sided_none_treated_as_zero():
    row = {"eps_rev_up_30d": 5, "eps_rev_down_30d": None}
    assert compute_metrics(row)["net_revisions_30d"] == 5


def test_eps_drift_30d_normal():
    row = {"eps_avg": 11.0, "eps_avg_30d": 10.0}
    m = compute_metrics(row)
    assert m["eps_drift_30d"] == pytest.approx(0.10)


def test_eps_drift_30d_null_when_prior_zero():
    row = {"eps_avg": 11.0, "eps_avg_30d": 0.0}
    assert compute_metrics(row)["eps_drift_30d"] is None


def test_eps_drift_30d_null_when_missing():
    row = {"eps_avg": 11.0, "eps_avg_30d": None}
    assert compute_metrics(row)["eps_drift_30d"] is None


def test_rev_dispersion_normal():
    row = {"rev_avg": 100.0, "rev_high": 120.0, "rev_low": 90.0}
    m = compute_metrics(row)
    assert m["rev_dispersion"] == pytest.approx(0.30)


def test_rev_dispersion_null_when_avg_zero():
    row = {"rev_avg": 0.0, "rev_high": 10.0, "rev_low": 5.0}
    assert compute_metrics(row)["rev_dispersion"] is None


def test_rev_dispersion_null_when_avg_negative():
    row = {"rev_avg": -5.0, "rev_high": 10.0, "rev_low": 5.0}
    assert compute_metrics(row)["rev_dispersion"] is None


def test_empty_row_all_null():
    m = compute_metrics({})
    assert m == {
        "eps_dispersion": None,
        "coverage": None,
        "net_revisions_30d": None,
        "eps_drift_30d": None,
        "rev_dispersion": None,
    }


# ---------------------------------------------------------------------------
# select_horizons
# ---------------------------------------------------------------------------

def _d(offset_days: int) -> date:
    return date.today() + timedelta(days=offset_days)


def test_select_horizons_nvda_like_fixture():
    # Mirrors the shape of real NVDA rows (two future fiscal years, several quarters
    # spanning past and future). Uses offsets from today rather than literal 2026 dates
    # so the test stays valid regardless of when it runs.
    rows = [
        {"fiscal_date": _d(400), "horizon": "fiscal year", "eps_avg": 12.7644},
        {"fiscal_date": _d(30), "horizon": "fiscal year", "eps_avg": 8.9727},
        {"fiscal_date": _d(60), "horizon": "fiscal quarter", "eps_avg": 2.3463},
        {"fiscal_date": _d(-10), "horizon": "fiscal quarter", "eps_avg": 2.0793},
        {"fiscal_date": _d(-100), "horizon": "fiscal quarter", "eps_avg": 1.2544},
    ]
    picked = select_horizons(rows)
    assert picked["fy1"]["fiscal_date"] == _d(30)
    assert picked["q1"]["fiscal_date"] == _d(60)


def test_select_horizons_all_past_returns_none_for_both():
    rows = [
        {"fiscal_date": _d(-10), "horizon": "fiscal year", "eps_avg": 1.0},
        {"fiscal_date": _d(-5), "horizon": "fiscal quarter", "eps_avg": 0.5},
    ]
    picked = select_horizons(rows)
    assert picked["fy1"] is None
    assert picked["q1"] is None


def test_select_horizons_empty_list():
    picked = select_horizons([])
    assert picked == {"fy1": None, "q1": None}


def test_select_horizons_missing_fiscal_date_skipped():
    rows = [{"fiscal_date": None, "horizon": "fiscal year", "eps_avg": 1.0}]
    picked = select_horizons(rows)
    assert picked["fy1"] is None


# ---------------------------------------------------------------------------
# percentile
# ---------------------------------------------------------------------------

def test_percentile_none_when_value_is_none():
    assert percentile(None, [1.0] * 100) is None


def test_percentile_none_on_small_population():
    population = list(range(20))
    assert percentile(10, population) is None


def test_percentile_computed_on_large_population():
    population = [float(i) for i in range(200)]
    result = percentile(100.0, population)
    assert result is not None
    assert 0.0 <= result <= 1.0


def test_percentile_max_element_is_one():
    population = [float(i) for i in range(200)]
    assert percentile(199.0, population) == pytest.approx(1.0)


def test_percentile_ignores_nulls_in_population():
    population = [float(i) for i in range(60)] + [None] * 50
    # 60 valid entries clears the 50-entry minimum even though the list has 110 items.
    result = percentile(30.0, population)
    assert result is not None
