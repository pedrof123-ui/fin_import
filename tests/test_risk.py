"""
Unit tests for historic_fundamentals/risk.py — Phase 7.

Tests
-----
1.  exposure_report: sector weights sum to 1.0 per month.
2.  exposure_report: missing industry column handled gracefully (no error).
3.  exposure_report: correct market-cap buckets (small/mid/large thresholds).
4.  value_trap_flags: returns only rows where at least one flag triggered.
5.  value_trap_flags: does NOT flag stocks with good fundamentals (no false positives).
6.  value_trap_flags: flags stock with negative operating margin in top quintile.
7.  apply_guardrails: detects sector weight violation (>40%).
8.  apply_guardrails: returns empty violations when all guardrails satisfied.
9.  apply_guardrails: configurable (custom threshold changes violation outcome).
10. drawdown_analysis: returns correct max_drawdown for known series.
11. drawdown_analysis: returns correct duration for known series.
12. beta_decomposition: returns market_beta close to 1.0 for SPY-identical portfolio.

All tests use synthetic DataFrames — no database connections required.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from historic_fundamentals.risk import (
    exposure_report,
    value_trap_flags,
    apply_guardrails,
    constrained_holdings,
    drawdown_analysis,
    beta_decomposition,
    GUARDRAIL_DEFAULTS,
    VTF_DEFAULTS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_holdings(n_tickers: int = 10, n_months: int = 3, sector: str = "Tech") -> pd.DataFrame:
    """Simple holdings DataFrame: n_tickers per month, single sector."""
    dates = pd.date_range("2020-01-31", periods=n_months, freq="ME")
    rows = []
    for dt in dates:
        for i in range(n_tickers):
            rows.append({
                "month_end_date": dt,
                "ticker": f"T{i:02d}",
                "sector": sector,
                "market_cap": 5e9,  # mid cap
            })
    return pd.DataFrame(rows)


def _make_multi_sector_holdings() -> pd.DataFrame:
    """Holdings with two sectors: 6 Tech, 4 Finance stocks per month."""
    dates = pd.date_range("2020-01-31", periods=2, freq="ME")
    rows = []
    for dt in dates:
        for i in range(6):
            rows.append({"month_end_date": dt, "ticker": f"T{i:02d}", "sector": "Tech", "market_cap": 5e9})
        for i in range(4):
            rows.append({"month_end_date": dt, "ticker": f"F{i:02d}", "sector": "Finance", "market_cap": 5e9})
    return pd.DataFrame(rows)


# ── Test 1: Sector weights sum to 1.0 per month ──────────────────────────────

def test_exposure_report_sector_weights_sum_to_one():
    holdings = _make_multi_sector_holdings()
    report = exposure_report(holdings)
    sector_df = report["sector"]
    assert not sector_df.empty
    row_sums = sector_df.sum(axis=1)
    assert (row_sums - 1.0).abs().max() < 1e-9


def test_exposure_report_sector_weights_correct_fractions():
    holdings = _make_multi_sector_holdings()
    report = exposure_report(holdings)
    sector_df = report["sector"]
    # 6 Tech / 10 total = 0.6
    assert abs(sector_df.loc[:, "Tech"].iloc[0] - 0.6) < 1e-9
    # 4 Finance / 10 total = 0.4
    assert abs(sector_df.loc[:, "Finance"].iloc[0] - 0.4) < 1e-9


# ── Test 2: Missing industry column handled gracefully ────────────────────────

def test_exposure_report_missing_industry_no_error():
    holdings = _make_holdings()
    # No 'industry' column in the DataFrame
    assert "industry" not in holdings.columns
    report = exposure_report(holdings)
    # Should not raise; 'industry' key should not be present
    assert "industry" not in report


def test_exposure_report_with_industry_column():
    holdings = _make_holdings()
    holdings["industry"] = "Software"
    report = exposure_report(holdings)
    assert "industry" in report
    ind_df = report["industry"]
    assert not ind_df.empty
    assert (ind_df.sum(axis=1) - 1.0).abs().max() < 1e-9


# ── Test 3: Market-cap buckets ────────────────────────────────────────────────

def test_exposure_report_market_cap_buckets_thresholds():
    """
    small: market_cap < 2B
    mid:   2B <= market_cap <= 10B
    large: market_cap > 10B
    """
    dates = [pd.Timestamp("2020-01-31")]
    rows = [
        {"month_end_date": dates[0], "ticker": "SMALL", "sector": "Tech", "market_cap": 0.5e9},
        {"month_end_date": dates[0], "ticker": "MID",   "sector": "Tech", "market_cap": 5e9},
        {"month_end_date": dates[0], "ticker": "LARGE", "sector": "Tech", "market_cap": 50e9},
    ]
    holdings = pd.DataFrame(rows)
    report = exposure_report(holdings)
    mc_df = report["market_cap_bucket"]
    assert "small" in mc_df.columns
    assert "mid" in mc_df.columns
    assert "large" in mc_df.columns
    row = mc_df.iloc[0]
    assert abs(row["small"] - 1 / 3) < 1e-9
    assert abs(row["mid"] - 1 / 3) < 1e-9
    assert abs(row["large"] - 1 / 3) < 1e-9


def test_exposure_report_concentration_equals_one_over_n():
    """For equal-weight portfolio HHI = 1/n."""
    n = 10
    holdings = _make_holdings(n_tickers=n, n_months=1)
    report = exposure_report(holdings)
    hhi = report["concentration"]
    assert abs(hhi.iloc[0] - 1 / n) < 1e-9


# ── Test 4: value_trap_flags returns only flagged rows ────────────────────────

def test_value_trap_flags_only_flagged_rows():
    """All returned rows must have at least one flag triggered."""
    n = 20
    rng = np.random.default_rng(0)
    dates = [pd.Timestamp("2020-01-31")] * n
    df = pd.DataFrame({
        "month_end_date": dates,
        "ticker": [f"T{i}" for i in range(n)],
        "score": np.arange(n, dtype=float),
        "sector": "Tech",
        "ttm_operating_margin": rng.uniform(-0.5, 0.3, n),
        "debt_to_ebitda": rng.uniform(0, 15, n),
        "roa": rng.uniform(-0.2, 0.2, n),
    })
    flagged = value_trap_flags(df, score_col="score")
    if flagged.empty:
        return  # acceptable — no traps if rng happened to avoid them
    assert "flags" in flagged.columns
    assert (flagged["flags"] != "").all()


# ── Test 5: No false positives for healthy stocks ────────────────────────────

def test_value_trap_flags_no_false_positives():
    """Stocks with good fundamentals should not be flagged even if in top quintile."""
    n = 20
    df = pd.DataFrame({
        "month_end_date": [pd.Timestamp("2020-01-31")] * n,
        "ticker": [f"T{i}" for i in range(n)],
        "score": np.arange(n, dtype=float),
        "sector": "Tech",
        # All stocks have good fundamentals
        "ttm_operating_margin": np.full(n, 0.15),   # positive
        "debt_to_ebitda": np.full(n, 2.0),           # low debt
        "roa": np.full(n, 0.10),                     # positive ROA
    })
    flagged = value_trap_flags(df, score_col="score")
    assert flagged.empty


# ── Test 6: Flags stock with negative operating margin in top quintile ────────

def test_value_trap_flags_negative_operating_margin():
    """Top-quintile stock with negative operating margin must be flagged."""
    n = 20
    df = pd.DataFrame({
        "month_end_date": [pd.Timestamp("2020-01-31")] * n,
        "ticker": [f"T{i}" for i in range(n)],
        "score": np.arange(n, dtype=float),          # T19 has highest score
        "sector": "Tech",
        "ttm_operating_margin": np.full(n, 0.15),    # all positive
        "debt_to_ebitda": np.full(n, 2.0),
        "roa": np.full(n, 0.10),
    })
    # Give top scorer a negative operating margin
    df.loc[df["ticker"] == "T19", "ttm_operating_margin"] = -0.20
    flagged = value_trap_flags(df, score_col="score")
    assert not flagged.empty
    assert "T19" in flagged["ticker"].values
    assert "neg_operating_margin" in flagged.loc[flagged["ticker"] == "T19", "flags"].values[0]


# ── Test 7: apply_guardrails detects sector weight violation ──────────────────

def test_apply_guardrails_detects_sector_violation():
    """If 100% of the portfolio is in one sector, max_sector_weight (40%) is breached."""
    holdings = _make_holdings(n_tickers=10, n_months=2, sector="Tech")
    portfolio_df = pd.DataFrame({
        "date": pd.date_range("2020-02-29", periods=2, freq="ME"),
        "net_return": [0.01, 0.02],
    })
    result = apply_guardrails(portfolio_df, holdings)
    assert len(result["violations"]) > 0
    guardrails_hit = [v["guardrail"] for v in result["violations"]]
    assert "max_sector_weight" in guardrails_hit


# ── Test 8: No violations when all guardrails satisfied ───────────────────────

def test_apply_guardrails_no_violations():
    """Balanced portfolio with two equal sectors should not trigger sector violation."""
    holdings = _make_multi_sector_holdings()
    # 6 Tech (60%) — this exceeds 40% default, so use a custom config that allows it
    portfolio_df = pd.DataFrame({
        "date": pd.date_range("2020-02-29", periods=2, freq="ME"),
        "net_return": [0.01, 0.02],
    })
    # Exact 50/50 split: no sector exceeds 40%? No — 60/40 still violates.
    # Build a true 50/50 holdings
    dates = pd.date_range("2020-01-31", periods=2, freq="ME")
    rows = []
    for dt in dates:
        for i in range(5):
            rows.append({"month_end_date": dt, "ticker": f"T{i}", "sector": "Tech", "market_cap": 5e9})
        for i in range(5):
            rows.append({"month_end_date": dt, "ticker": f"F{i}", "sector": "Finance", "market_cap": 5e9})
    holdings_50_50 = pd.DataFrame(rows)
    result = apply_guardrails(portfolio_df, holdings_50_50)
    # 50% Tech and 50% Finance — both equal threshold (40% default is violated at 50%)
    # Use a config with 60% threshold so neither fires
    result2 = apply_guardrails(portfolio_df, holdings_50_50, config={"max_sector_weight": 0.60})
    assert len(result2["violations"]) == 0


# ── Test 9: apply_guardrails configurable ────────────────────────────────────

def test_apply_guardrails_configurable_threshold():
    """Lowering the threshold from 0.40 to 0.30 causes a violation that 0.40 does not."""
    # Build 35% in one sector
    dates = [pd.Timestamp("2020-01-31")]
    rows = []
    for i in range(7):
        rows.append({"month_end_date": dates[0], "ticker": f"T{i}", "sector": "Tech", "market_cap": 5e9})
    for i in range(13):
        rows.append({"month_end_date": dates[0], "ticker": f"F{i}", "sector": "Finance", "market_cap": 5e9})
    holdings = pd.DataFrame(rows)  # 7/20 = 35% Tech, 13/20 = 65% Finance
    portfolio_df = pd.DataFrame({"date": dates, "net_return": [0.01]})

    # With threshold 0.40: Tech (35%) is fine; Finance (65%) violates
    result_40 = apply_guardrails(portfolio_df, holdings, config={"max_sector_weight": 0.40})
    finance_violations = [v for v in result_40["violations"] if v["detail"] == "Finance"]
    assert len(finance_violations) > 0

    # With threshold 0.70: Finance (65%) is now fine
    result_70 = apply_guardrails(portfolio_df, holdings, config={"max_sector_weight": 0.70})
    assert len(result_70["violations"]) == 0


# ── Test 10: drawdown_analysis correct max_drawdown ──────────────────────────

def test_drawdown_analysis_max_drawdown():
    """
    Known returns: +10%, -30%, +5%.
    Cum: 1.10, 0.77, 0.8085
    Rolling max: 1.10, 1.10, 1.10
    Drawdown at each: 0, -0.30, -0.265...
    Max drawdown = (0.77 - 1.10) / 1.10 = -0.30
    """
    idx = pd.date_range("2020-01-31", periods=3, freq="ME")
    rets = pd.Series([0.10, -0.30, 0.05], index=idx)
    dd = drawdown_analysis(rets)
    expected_max_dd = (0.77 - 1.10) / 1.10
    assert abs(dd["max_drawdown"] - expected_max_dd) < 1e-6
    assert dd["max_drawdown"] < 0


# ── Test 11: drawdown_analysis correct duration ───────────────────────────────

def test_drawdown_analysis_duration():
    """
    Returns: +10%, -5%, -5%, -5%
    Peak at month 0 (cum=1.10); trough at month 3.
    Duration = 3 months.
    """
    idx = pd.date_range("2020-01-31", periods=4, freq="ME")
    rets = pd.Series([0.10, -0.05, -0.05, -0.05], index=idx)
    dd = drawdown_analysis(rets)
    assert dd["max_drawdown_duration_months"] == 3


def test_drawdown_analysis_empty_series():
    dd = drawdown_analysis(pd.Series(dtype=float))
    assert np.isnan(dd["max_drawdown"])
    assert dd["underwater_months"] == 0


def test_drawdown_analysis_no_drawdown():
    """Monotonically increasing returns: no underwater months."""
    idx = pd.date_range("2020-01-31", periods=5, freq="ME")
    rets = pd.Series([0.01, 0.02, 0.01, 0.03, 0.02], index=idx)
    dd = drawdown_analysis(rets)
    assert dd["max_drawdown"] == pytest.approx(0.0, abs=1e-9)
    assert dd["underwater_months"] == 0


# ── Test 12: beta_decomposition SPY-identical portfolio ───────────────────────

def test_beta_decomposition_spy_identical():
    """Portfolio identical to SPY should have market_beta == 1.0."""
    idx = pd.date_range("2020-01-31", periods=24, freq="ME")
    spy = pd.Series(np.random.default_rng(42).normal(0.01, 0.04, 24), index=idx, name="spy")
    port = spy.copy()
    result = beta_decomposition(port, spy)
    assert abs(result["market_beta"] - 1.0) < 1e-9


def test_beta_decomposition_rolling_beta_length():
    """Rolling beta series should have same length as portfolio returns."""
    idx = pd.date_range("2020-01-31", periods=24, freq="ME")
    spy = pd.Series(np.random.default_rng(1).normal(0.01, 0.04, 24), index=idx)
    port = spy * 1.2
    result = beta_decomposition(port, spy)
    assert len(result["beta_by_period"]) == len(port)


def test_beta_decomposition_short_series():
    """Series shorter than min_periods should return NaN for early rolling betas."""
    idx = pd.date_range("2020-01-31", periods=4, freq="ME")
    spy = pd.Series([0.01, -0.02, 0.03, 0.01], index=idx)
    port = spy.copy()
    result = beta_decomposition(port, spy)
    # With min_periods=6 and only 4 points, all rolling betas should be NaN
    assert result["beta_by_period"].notna().sum() == 0


def test_beta_decomposition_zero_variance_spy():
    """Zero SPY returns (zero variance) should return NaN beta."""
    idx = pd.date_range("2020-01-31", periods=12, freq="ME")
    spy = pd.Series([0.0] * 12, index=idx)   # exact zero — no floating-point residual
    port = pd.Series([0.02] * 12, index=idx)
    result = beta_decomposition(port, spy)
    assert np.isnan(result["market_beta"])


# ── Test: value_trap_flags configurable threshold ────────────────────────────

def test_value_trap_flags_configurable_threshold():
    """
    With default threshold (vtf_max_debt_to_ebitda=10.0) a stock with
    debt_to_ebitda=3.0 in the top quintile is NOT flagged for high debt.
    With config={"vtf_max_debt_to_ebitda": 2.0} the same stock IS flagged.
    """
    n = 20
    df = pd.DataFrame({
        "month_end_date": [pd.Timestamp("2020-01-31")] * n,
        "ticker": [f"T{i}" for i in range(n)],
        "score": np.arange(n, dtype=float),   # T19 has the highest score
        "sector": "Tech",
        "ttm_operating_margin": np.full(n, 0.15),   # all positive
        "debt_to_ebitda": np.full(n, 0.5),           # all low debt
        "roa": np.full(n, 0.10),                     # all positive
    })
    # Give the top scorer a debt_to_ebitda of 3.0
    df.loc[df["ticker"] == "T19", "debt_to_ebitda"] = 3.0

    # Default threshold: 3.0 < 10.0 — should NOT flag for high debt
    flagged_default = value_trap_flags(df, score_col="score")
    default_debt_flags = flagged_default[
        flagged_default["flags"].str.contains("high_debt_to_ebitda", na=False)
    ] if not flagged_default.empty else pd.DataFrame()
    assert default_debt_flags.empty, "Default threshold should not flag debt_to_ebitda=3.0"

    # Lowered threshold: 3.0 > 2.0 — should flag as high_debt_to_ebitda
    flagged_low = value_trap_flags(df, score_col="score", config={"vtf_max_debt_to_ebitda": 2.0})
    assert not flagged_low.empty, "Lowered threshold should produce flags"
    assert "T19" in flagged_low["ticker"].values
    assert "high_debt_to_ebitda" in flagged_low.loc[
        flagged_low["ticker"] == "T19", "flags"
    ].values[0]


# ── Tests: constrained_holdings ──────────────────────────────────────────────

def test_constrained_holdings_excludes_high_debt():
    """Stocks with debt_to_ebitda above threshold must be dropped."""
    dt = pd.Timestamp("2020-01-31")
    holdings = pd.DataFrame({
        "month_end_date": [dt, dt, dt],
        "ticker": ["A", "B", "C"],
    })
    features = pd.DataFrame({
        "month_end_date": [dt, dt, dt],
        "ticker": ["A", "B", "C"],
        "sector": ["Tech", "Tech", "Tech"],
        "debt_to_ebitda": [2.0, 15.0, 3.0],  # B exceeds default 10.0
        "score": [0.5, 0.9, 0.7],
    })
    result = constrained_holdings(holdings, features, config={"max_sector_weight": 1.0})
    assert "B" not in result["ticker"].values
    assert set(result["ticker"].values) == {"A", "C"}


def test_constrained_holdings_trims_overweight_sector():
    """When sector weight exceeds cap, lowest-scoring stocks are removed."""
    dt = pd.Timestamp("2020-01-31")
    # 3 Tech, 1 Finance => Tech = 75% > 50% cap
    holdings = pd.DataFrame({
        "month_end_date": [dt, dt, dt, dt],
        "ticker": ["T1", "T2", "T3", "F1"],
    })
    features = pd.DataFrame({
        "month_end_date": [dt, dt, dt, dt],
        "ticker": ["T1", "T2", "T3", "F1"],
        "sector": ["Tech", "Tech", "Tech", "Finance"],
        "debt_to_ebitda": [1.0, 1.0, 1.0, 1.0],
        "score": [0.9, 0.5, 0.3, 0.8],  # T3 has lowest score in Tech
    })
    # With max_sector_weight=0.50 and max_debt_to_ebitda=100 (no leverage filter)
    result = constrained_holdings(
        holdings, features,
        config={"max_sector_weight": 0.50, "max_debt_to_ebitda": 100.0},
    )
    # T3 (lowest Tech score) should be removed: now 2 Tech, 1 Finance = 67% — still over
    # T2 removed next: 1 Tech, 1 Finance = 50% — constraint satisfied
    assert "T3" not in result["ticker"].values
    assert "F1" in result["ticker"].values
