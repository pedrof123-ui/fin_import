"""
Unit tests for the sector/industry capex+R&D fallback in dcf/forecaster.py
(PLAN_CAPEX_RD_RATIOS.md Phase 4).
"""

import pandas as pd
import pytest

from dcf.forecaster import forecast_assumptions

_EMPTY_QUARTERLY_INCOME = pd.DataFrame({"revenue": []})


def _annual(n=5, capex=None, rd=None, da=None):
    """5-year annual income+cashflow fixture with sensible defaults.

    capex/rd/da default to a flat, present history; pass a list of NaN to simulate
    a ticker with no history for that line item.
    """
    dates = pd.date_range("2019-12-31", periods=n, freq="YE")
    if capex is None:
        capex = [50.0] * n
    if rd is None:
        rd = [30.0] * n
    if da is None:
        da = [40.0] * n

    income = pd.DataFrame({
        "period_end_date": dates,
        "revenue":                     [1000.0] * n,
        "cost_of_revenue":             [500.0] * n,
        "gross_profit":                [500.0] * n,
        "operating_income":            [200.0] * n,
        "selling_general_admin":       [100.0] * n,
        "research_development":        rd,
        "interest_expense":            [10.0] * n,
        "interest_income":             [0.0] * n,
        "pretax_income":               [190.0] * n,
        "net_income_from_continuing_ops": [150.0] * n,
        "net_income":                  [150.0] * n,
    })
    cashflow = pd.DataFrame({
        "period_end_date": dates,
        "capital_expenditures":     capex,
        "depreciation_amortization": da,
    })
    return {"income": income, "cashflow": cashflow}


def _quarterly():
    return {"income": _EMPTY_QUARTERLY_INCOME.copy()}


def _run(annual, **sector_kwargs):
    forecasts = forecast_assumptions(_quarterly(), annual, **sector_kwargs)
    assert forecasts, "forecast_assumptions returned no years"
    return forecasts[0]


# ── CapEx fallback (4.1) ────────────────────────────────────────────────────────

def test_capex_uses_own_history_when_present():
    # Own capex history exists (50/1000 = 5%) — sector args must be ignored.
    annual = _annual(capex=[50.0] * 5)
    yf = _run(annual, sector_capex_intensity=0.40)
    assert yf.capex_pct_revenue == pytest.approx(0.05, rel=1e-6)


def test_capex_falls_back_to_sector_when_no_own_history():
    annual = _annual(capex=[float("nan")] * 5)
    yf = _run(annual, sector_capex_intensity=0.15)
    assert yf.capex_pct_revenue == pytest.approx(0.15, rel=1e-6)
    assert yf.capex_pct_revenue > 0.05, "sector fallback should differ from the flat constant"


def test_capex_falls_back_to_hardcoded_constant_when_unclassified():
    # No own history AND no sector data (e.g. ticker has no sector classification)
    annual = _annual(capex=[float("nan")] * 5)
    yf = _run(annual, sector_capex_intensity=None)
    assert yf.capex_pct_revenue == pytest.approx(0.05, rel=1e-6)


# ── D&A fallback (4.1) ──────────────────────────────────────────────────────────

def test_da_uses_own_history_when_present():
    annual = _annual(da=[40.0] * 5)
    yf = _run(annual, sector_capex_intensity=0.15, sector_capex_to_da=2.0)
    assert yf.da_pct == pytest.approx(0.04, rel=1e-6)


def test_da_falls_back_to_sector_capex_over_capex_to_da_ratio():
    annual = _annual(da=[float("nan")] * 5)
    yf = _run(annual, sector_capex_intensity=0.20, sector_capex_to_da=4.0)
    assert yf.da_pct == pytest.approx(0.05, rel=1e-6)  # 0.20 / 4.0


def test_da_falls_back_to_hardcoded_constant_when_no_sector_data():
    annual = _annual(da=[float("nan")] * 5)
    yf = _run(annual, sector_capex_intensity=None, sector_capex_to_da=None)
    assert yf.da_pct == pytest.approx(0.03, rel=1e-6)


# ── R&D fallback (4.2) ───────────────────────────────────────────────────────────

def test_rd_uses_own_history_when_present():
    annual = _annual(rd=[30.0] * 5)
    yf = _run(annual, sector_rd_intensity=0.20)
    assert yf.rd_pct == pytest.approx(0.03, rel=1e-6)


def test_rd_falls_back_to_sector_when_meaningfully_nonzero():
    # No own R&D history, but sector clearly does R&D (e.g. Technology) — signal that the
    # ticker's own null is a data gap, not "this company doesn't do R&D".
    annual = _annual(rd=[float("nan")] * 5)
    yf = _run(annual, sector_rd_intensity=0.15)
    assert yf.rd_pct == pytest.approx(0.15, rel=1e-6)


def test_rd_stays_null_when_sector_median_is_near_zero():
    # No own R&D history, and the sector itself doesn't really do R&D (e.g. Real Estate) —
    # must NOT fabricate a near-zero R&D line; rd_pct stays None as before this feature.
    annual = _annual(rd=[float("nan")] * 5)
    yf = _run(annual, sector_rd_intensity=0.001)
    assert yf.rd_pct is None


def test_rd_stays_null_when_no_sector_data():
    annual = _annual(rd=[float("nan")] * 5)
    yf = _run(annual, sector_rd_intensity=None)
    assert yf.rd_pct is None
