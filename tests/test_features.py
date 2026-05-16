"""
Unit tests for Phase 3 feature formulas in historic_fundamentals/pe.py.

Each test uses synthetic DataFrames with hand-calculated expected values.
"""

import numpy as np
import pandas as pd
import pytest

from historic_fundamentals.pe import build_monthly_pe, _rolling_slope


# ── Synthetic data helpers ────────────────────────────────────────────────────

def _quarterly(n=4, **overrides):
    """Build n identical quarterly rows with sensible defaults."""
    base = {
        "fiscal_date_ending": pd.date_range("2023-01-01", periods=n, freq="QE"),
        "net_income":           [100.0] * n,
        "total_revenue":        [1000.0] * n,
        "gross_profit":         [400.0] * n,   # gross_margin = 0.40
        "operating_income":     [200.0] * n,   # operating_margin = 0.20
        # AV reports interest_expense as negative (outflow convention)
        "interest_expense":     [-10.0] * n,   # TTM abs = 40
        "ebitda":               [300.0] * n,
        "ebit":                 [250.0] * n,   # TTM = 1000
        "income_tax_expense":   [25.0] * n,
        "income_before_tax":    [240.0] * n,
        "shares":               [1000.0] * n,
        "total_assets":         [5000.0] * n,
        "total_shareholder_equity": [2000.0] * n,
        "intangible_assets_excl_goodwill": [0.0] * n,
        "goodwill":             [0.0] * n,
        "long_term_debt_noncurrent": [800.0] * n,
        "short_term_debt":      [200.0] * n,
        "current_long_term_debt": [0.0] * n,
        "cash_and_short_term_investments": [500.0] * n,
    }
    base.update(overrides)
    return pd.DataFrame(base)


def _cashflow(n=4, ocf=200.0, capex=50.0):
    return pd.DataFrame({
        "fiscal_date_ending": pd.date_range("2023-01-01", periods=n, freq="QE"),
        "operating_cashflow":    [ocf] * n,
        "capital_expenditures":  [capex] * n,  # AV reports as positive
    })


def _prices(date="2024-01-31", price=50.0):
    return pd.DataFrame({"month_end_date": [date], "price": [price]})


def _run(quarterly=None, annual=None, prices=None, cashflow_q=None, cashflow_a=None):
    q  = quarterly if quarterly is not None else _quarterly()
    a  = annual    if annual    is not None else pd.DataFrame()
    p  = prices    if prices    is not None else _prices()
    cq = cashflow_q if cashflow_q is not None else _cashflow()
    ca = cashflow_a if cashflow_a is not None else pd.DataFrame()
    df = build_monthly_pe(q, a, p, cashflow_q=cq, cashflow_a=ca)
    assert not df.empty, "build_monthly_pe returned empty DataFrame"
    return df.iloc[0]


# ── Margin formulas ───────────────────────────────────────────────────────────

def test_gross_margin():
    # gross_margin = TTM gross_profit / TTM revenue = 1600/4000 = 0.40
    row = _run()
    assert row["ttm_gross_margin"] == pytest.approx(0.40, rel=1e-6)


def test_operating_margin():
    # operating_margin = TTM operating_income / TTM revenue = 800/4000 = 0.20
    row = _run()
    assert row["ttm_operating_margin"] == pytest.approx(0.20, rel=1e-6)


def test_fcf_margin():
    # FCF = (200-50)*4 = 600; revenue = 4000; fcf_margin = 0.15
    row = _run()
    assert row["ttm_fcf_margin"] == pytest.approx(0.15, rel=1e-6)


def test_gross_margin_zero_revenue():
    q = _quarterly(total_revenue=[0.0] * 4)
    row = _run(quarterly=q)
    assert row["ttm_gross_margin"] is None or np.isnan(row["ttm_gross_margin"])


# ── Leverage features ─────────────────────────────────────────────────────────

def test_debt_to_ebitda():
    # total_debt = 800+200+0 = 1000; TTM EBITDA = 300*4 = 1200
    # debt_to_ebitda = 1000/1200 ≈ 0.8333
    row = _run()
    assert row["debt_to_ebitda"] == pytest.approx(1000 / 1200, rel=1e-6)


def test_debt_to_ebitda_zero_ebitda():
    q = _quarterly(ebitda=[0.0] * 4)
    row = _run(quarterly=q)
    assert row["debt_to_ebitda"] is None or np.isnan(row["debt_to_ebitda"])


def test_interest_coverage():
    # EBIT TTM = 250*4 = 1000; interest_expense per AV = -10/qtr → TTM = -40; abs = 40
    # interest_coverage = 1000/40 = 25.0
    row = _run()
    assert row["interest_coverage"] == pytest.approx(25.0, rel=1e-6)


def test_interest_coverage_negative_ebit():
    # Negative EBIT — coverage should still compute (no guard on EBIT sign)
    q = _quarterly(ebit=[-100.0] * 4)
    row = _run(quarterly=q)
    # TTM EBIT = -400; abs(interest) = 40; coverage = -400/40 = -10
    assert row["interest_coverage"] == pytest.approx(-10.0, rel=1e-6)


def test_interest_coverage_zero_interest():
    # Zero interest — coverage must be None (no division by zero)
    q = _quarterly(interest_expense=[0.0] * 4)
    row = _run(quarterly=q)
    assert row["interest_coverage"] is None or np.isnan(row["interest_coverage"])


def test_interest_coverage_positive_interest_expense():
    # Some data sources report interest as positive — abs() handles both conventions
    q = _quarterly(interest_expense=[10.0] * 4)
    row = _run(quarterly=q)
    assert row["interest_coverage"] == pytest.approx(25.0, rel=1e-6)


# ── Quality / profitability features ─────────────────────────────────────────

def test_roa():
    # TTM net_income = 100*4 = 400; total_assets = 5000; roa = 0.08
    row = _run()
    assert row["roa"] == pytest.approx(400 / 5000, rel=1e-6)


def test_roe():
    # TTM net_income = 400; equity = 2000; roe = 0.20
    row = _run()
    assert row["roe"] == pytest.approx(400 / 2000, rel=1e-6)


# ── Earnings yield and normalized PE ─────────────────────────────────────────

def test_earnings_yield():
    # TTM EPS = 400/1000 = 0.40; price = 50; earnings_yield = 0.40/50 = 0.008
    row = _run()
    assert row["earnings_yield"] == pytest.approx(0.40 / 50.0, rel=1e-6)


def test_pe_ratio():
    # pe_ratio = price / TTM_EPS = 50 / 0.40 = 125
    row = _run()
    assert row["pe_ratio"] == pytest.approx(125.0, rel=1e-6)


# ── FCF and EBITDA/EV yield ───────────────────────────────────────────────────

def test_fcf_yield():
    # fcf_per_share = 600/1000 = 0.60; fcf_yield = 0.60/50 = 0.012
    row = _run()
    assert row["fcf_yield"] == pytest.approx(0.60 / 50.0, rel=1e-6)


def test_pfcf_ratio():
    # pfcf_ratio = price / fcf_per_share = 50/0.60 ≈ 83.33
    row = _run()
    assert row["pfcf_ratio"] == pytest.approx(50.0 / 0.60, rel=1e-4)


# ── roa_stability_5y (std, not stability score — higher = less stable) ────────

def test_roa_stability_requires_36_months():
    # With only 1 price row we get 1 roa value → rolling std of 1 is NaN
    row = _run()
    # Single-month timeseries: roa_stability_5y must be NaN
    assert row["roa_stability_5y"] is None or np.isnan(row["roa_stability_5y"])


def test_roa_stability_computed_for_long_series():
    # Build 40 months of stable ROA → roa_stability_5y should be near 0 (min_periods=36)
    n_months = 40
    prices = pd.DataFrame({
        "month_end_date": pd.date_range("2020-01-31", periods=n_months, freq="ME"),
        "price": [50.0] * n_months,
    })
    # Each price row needs a quarterly anchor ≤ month_end; supply 10 years of quarters
    q = pd.DataFrame({
        "fiscal_date_ending": pd.date_range("2010-01-01", periods=40, freq="QE"),
        "net_income":           [100.0] * 40,
        "total_revenue":        [1000.0] * 40,
        "gross_profit":         [400.0] * 40,
        "operating_income":     [200.0] * 40,
        "interest_expense":     [-10.0] * 40,
        "ebitda":               [300.0] * 40,
        "ebit":                 [250.0] * 40,
        "income_tax_expense":   [25.0] * 40,
        "income_before_tax":    [240.0] * 40,
        "shares":               [1000.0] * 40,
        "total_assets":         [5000.0] * 40,
        "total_shareholder_equity": [2000.0] * 40,
        "intangible_assets_excl_goodwill": [0.0] * 40,
        "goodwill":             [0.0] * 40,
        "long_term_debt_noncurrent": [800.0] * 40,
        "short_term_debt":      [200.0] * 40,
        "current_long_term_debt": [0.0] * 40,
        "cash_and_short_term_investments": [500.0] * 40,
    })
    cf = pd.DataFrame({
        "fiscal_date_ending": pd.date_range("2010-01-01", periods=40, freq="QE"),
        "operating_cashflow":   [200.0] * 40,
        "capital_expenditures": [50.0] * 40,
    })
    df = build_monthly_pe(q, pd.DataFrame(), prices, cashflow_q=cf)
    assert not df.empty
    # Last row should have roa_stability_5y computed (40 months, min_periods=36 met)
    last = df.iloc[-1]
    assert last["roa_stability_5y"] is not None and not np.isnan(last["roa_stability_5y"])
    # Constant ROA → std ≈ 0
    assert last["roa_stability_5y"] == pytest.approx(0.0, abs=1e-10)


# ── _rolling_slope NaN handling ───────────────────────────────────────────────

def test_rolling_slope_nan_propagation_fixed():
    # A series with occasional NaN should still produce slope values,
    # not propagate NaN through every window that contains a gap.
    s = pd.Series([0.1, 0.2, np.nan, 0.3, 0.4] * 12)  # 60 values, 12 NaN
    result = _rolling_slope(s, window=60, min_periods=36)
    valid = result.dropna()
    # With NaN exclusion, the last window (60 values with 12 NaN, 48 valid) should produce a slope
    assert len(valid) >= 1, "slope should be computable when enough non-NaN points exist"


def test_rolling_slope_all_nan_returns_nan():
    s = pd.Series([np.nan] * 60)
    result = _rolling_slope(s, window=60, min_periods=36)
    assert result.isna().all()


def test_rolling_slope_monotone_increasing():
    # Linearly increasing series → slope should be positive
    s = pd.Series(np.arange(60, dtype=float))
    result = _rolling_slope(s, window=60, min_periods=36)
    valid = result.dropna()
    assert len(valid) >= 1
    assert (valid > 0).all()


# ── None propagation: missing data should not produce false signal ────────────

def test_no_revenue_means_no_margins():
    q = _quarterly(total_revenue=[None] * 4)
    row = _run(quarterly=q)
    assert row["ttm_gross_margin"] is None or np.isnan(row["ttm_gross_margin"])
    assert row["ttm_operating_margin"] is None or np.isnan(row["ttm_operating_margin"])
    assert row["ttm_fcf_margin"] is None or np.isnan(row["ttm_fcf_margin"])


def test_no_ebitda_means_no_debt_ratio():
    q = _quarterly(ebitda=[None] * 4)
    row = _run(quarterly=q)
    assert row["debt_to_ebitda"] is None or np.isnan(row["debt_to_ebitda"])
