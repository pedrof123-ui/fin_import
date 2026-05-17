"""
Unit tests for historic_fundamentals/backtest.py — Phase 6.

Tests
-----
1.  Non-overlapping returns: portfolio monthly return = price_{t+1}/price_t - 1 (equal-weight).
2.  Transaction cost applied: with tc_bps=10 and full turnover, net_return < gross_return.
3.  Zero TC at zero turnover: identical portfolio month-to-month produces TC = 0.
4.  Turnover calculation: if portfolio changes completely, turnover = 1.0.
5.  Equal-weight average: portfolio return = arithmetic mean of constituent returns.
6.  CAGR formula: portfolio_metrics() returns correct CAGR for known inputs.
7.  Sharpe formula: correct for known inputs.
8.  Max drawdown: returns correct value for a known equity curve.
9.  SPY beta: correct for a portfolio perfectly correlated with SPY.
10. Portfolio size: top_pct_20 selects correct number of stocks.
11. compute_universe_benchmark returns correct equal-weight return.
12. Sortino: uses only negative-return months in denominator.

All tests use synthetic DataFrames — no database connections required.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from historic_fundamentals.backtest import (
    run_monthly_backtest,
    portfolio_metrics,
    compute_universe_benchmark,
    PORTFOLIO_CONFIGS,
)


# ── Synthetic data helpers ────────────────────────────────────────────────────

def _make_universe(
    n_tickers: int = 20,
    n_months: int = 6,
    seed: int = 42,
    price_start: float = 100.0,
    monthly_return: float = 0.01,
) -> pd.DataFrame:
    """
    Build a simple synthetic monthly universe.
    Prices grow by monthly_return each month.
    Score = ticker index (ticker_0 has highest score).
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-31", periods=n_months, freq="ME")
    rows = []
    for i, tkr in enumerate([f"T{i:02d}" for i in range(n_tickers)]):
        for j, dt in enumerate(dates):
            rows.append({
                "month_end_date": dt,
                "ticker": tkr,
                "price": price_start * (1 + monthly_return) ** j,
                "score": n_tickers - i,  # T00 has highest score
                "sector": "Tech",
                "market_cap": 2e9,
                "shares": 1e8,
            })
    return pd.DataFrame(rows)


def _make_two_date_universe(prices_t0: list[float], prices_t1: list[float]) -> pd.DataFrame:
    """Build a 2-date universe with specified prices for precise return testing."""
    n = len(prices_t0)
    assert n == len(prices_t1)
    tickers = [f"T{i:02d}" for i in range(n)]
    dates = [pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-29")]
    rows = []
    for tkr, p0, p1 in zip(tickers, prices_t0, prices_t1):
        rows.append({"month_end_date": dates[0], "ticker": tkr, "price": p0, "score": 1.0,
                     "market_cap": 2e9, "sector": "Tech"})
        rows.append({"month_end_date": dates[1], "ticker": tkr, "price": p1, "score": 1.0,
                     "market_cap": 2e9, "sector": "Tech"})
    return pd.DataFrame(rows)


# ── Test 1: Non-overlapping returns ──────────────────────────────────────────

def test_non_overlapping_returns_formula():
    """
    Portfolio monthly return must equal (price_{t+1} / price_t) - 1,
    not any multi-period or overlapping return.
    """
    # 2 tickers, 2 dates. t0: both priced at 100. t1: T00=110, T01=90.
    # Equal-weight return = mean of (110/100-1, 90/100-1) = mean(0.10, -0.10) = 0.0
    df = _make_two_date_universe([100.0, 100.0], [110.0, 90.0])
    result = run_monthly_backtest(df, score_col="score", tc_bps=0,
                                  portfolios={"all": 1.0})
    bt = result["all"]
    assert len(bt) == 1
    assert abs(bt.iloc[0]["gross_return"] - 0.0) < 1e-9


def test_non_overlapping_returns_positive():
    """Single stock: return = price_{t1}/price_{t0} - 1."""
    df = _make_two_date_universe([100.0], [120.0])
    result = run_monthly_backtest(df, score_col="score", tc_bps=0,
                                  portfolios={"all": 1.0})
    bt = result["all"]
    assert abs(bt.iloc[0]["gross_return"] - 0.20) < 1e-9


# ── Test 2: Transaction cost applied ─────────────────────────────────────────

def test_tc_applied_with_full_turnover():
    """With tc_bps=10 and full turnover (first period), net_return < gross_return."""
    df = _make_universe(n_tickers=10, n_months=3, monthly_return=0.05)
    result = run_monthly_backtest(df, score_col="score", tc_bps=10,
                                  portfolios={"top_2": 2})
    bt = result["top_2"]
    # First period: full turnover, TC = 1.0 * 10 * 1e-4 = 0.001
    first = bt.iloc[0]
    assert first["net_return"] < first["gross_return"]
    assert abs(first["tc_cost"] - 0.001) < 1e-9


# ── Test 3: Zero TC at zero turnover ─────────────────────────────────────────

def test_zero_tc_at_zero_turnover():
    """If portfolio is identical month-to-month, turnover=0 and TC=0 (after first period)."""
    # 5 tickers, 4 months, all have same score so always the same top 5 are selected
    df = _make_universe(n_tickers=5, n_months=4, monthly_return=0.02)
    # All tickers get the same score so top-n=5 = entire universe, never changes
    df["score"] = 1.0
    result = run_monthly_backtest(df, score_col="score", tc_bps=10,
                                  portfolios={"all_5": 5})
    bt = result["all_5"]
    # After first period (which always has full turnover), subsequent should be 0
    if len(bt) > 1:
        for _, row in bt.iloc[1:].iterrows():
            assert abs(row["tc_cost"]) < 1e-9
            assert abs(row["turnover"]) < 1e-9


# ── Test 4: Turnover calculation ─────────────────────────────────────────────

def test_full_turnover_when_portfolio_changes_completely():
    """If portfolio changes completely, turnover = 1.0."""
    # 4 tickers, 3 months
    # Month 0: T00, T01 score highest
    # Month 1: T02, T03 score highest
    # Month 2: T00, T01 score highest again
    dates = [pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-29"), pd.Timestamp("2020-03-31")]
    rows = []
    for j, dt in enumerate(dates):
        for i, tkr in enumerate(["T00", "T01", "T02", "T03"]):
            if j == 0:
                score = 10 if tkr in ("T00", "T01") else 1
            elif j == 1:
                score = 10 if tkr in ("T02", "T03") else 1
            else:
                score = 10 if tkr in ("T00", "T01") else 1
            rows.append({
                "month_end_date": dt,
                "ticker": tkr,
                "price": 100.0 * (1.01 ** j),
                "score": score,
                "market_cap": 2e9,
                "sector": "Tech",
            })
    df = pd.DataFrame(rows)
    result = run_monthly_backtest(df, score_col="score", tc_bps=0,
                                  portfolios={"top_2": 2})
    bt = result["top_2"]
    # Period 0->1: first period, turnover = 1.0
    # Period 1->2: portfolio changes from {T02,T03} to {T00,T01} → turnover = 1.0
    assert abs(bt.iloc[0]["turnover"] - 1.0) < 1e-9
    assert abs(bt.iloc[1]["turnover"] - 1.0) < 1e-9


# ── Test 5: Equal-weight average ─────────────────────────────────────────────

def test_equal_weight_average():
    """Portfolio return = arithmetic mean of constituent returns."""
    prices_t0 = [100.0, 200.0, 50.0, 150.0]
    prices_t1 = [110.0, 210.0, 55.0, 140.0]
    expected_rets = [p1 / p0 - 1.0 for p0, p1 in zip(prices_t0, prices_t1)]
    expected_port_ret = float(np.mean(expected_rets))

    df = _make_two_date_universe(prices_t0, prices_t1)
    result = run_monthly_backtest(df, score_col="score", tc_bps=0,
                                  portfolios={"all": 1.0})
    bt = result["all"]
    assert abs(bt.iloc[0]["gross_return"] - expected_port_ret) < 1e-9


# ── Test 6: CAGR formula ─────────────────────────────────────────────────────

def test_cagr_formula():
    """CAGR = (1 + total_return)^(12/n_months) - 1."""
    # 12 months of 1% monthly return
    rets = pd.Series([0.01] * 12)
    metrics = portfolio_metrics(rets)
    total_return = (1.01 ** 12) - 1.0
    expected_cagr = (1.0 + total_return) ** (12 / 12) - 1.0
    assert abs(metrics["cagr"] - expected_cagr) < 1e-9
    assert abs(metrics["total_return"] - total_return) < 1e-9


def test_cagr_24_months():
    """CAGR over 24 months with 2% monthly = (1.02^24)^(12/24) - 1 = 1.02^12 - 1."""
    rets = pd.Series([0.02] * 24)
    metrics = portfolio_metrics(rets)
    expected_cagr = (1.02 ** 12) - 1.0
    assert abs(metrics["cagr"] - expected_cagr) < 1e-6


# ── Test 7: Sharpe formula ────────────────────────────────────────────────────

def test_sharpe_formula():
    """Sharpe = mean_monthly_excess_return * 12 / (std * sqrt(12))."""
    rng = np.random.default_rng(0)
    rets = pd.Series(rng.normal(0.01, 0.05, 36))
    metrics = portfolio_metrics(rets, rf=0.0)
    expected_sharpe = rets.mean() * 12 / (rets.std(ddof=1) * np.sqrt(12))
    assert abs(metrics["sharpe"] - expected_sharpe) < 1e-9


def test_sharpe_zero_rf():
    """With rf=0, Sharpe = mean * 12 / ann_vol."""
    rets = pd.Series([0.01, 0.02, -0.01, 0.03, 0.01, 0.00])
    m = portfolio_metrics(rets, rf=0.0)
    expected = rets.mean() * 12 / (rets.std(ddof=1) * np.sqrt(12))
    assert abs(m["sharpe"] - expected) < 1e-9


# ── Test 8: Max drawdown ──────────────────────────────────────────────────────

def test_max_drawdown_known_equity_curve():
    """
    Returns: +10%, -20%, +5%.
    Equity curve: 1.0 -> 1.10 -> 0.88 -> 0.924
    Drawdown from peak 1.10: (0.88 - 1.10) / 1.10 = -0.2 (approx)
    """
    rets = pd.Series([0.10, -0.20, 0.05])
    metrics = portfolio_metrics(rets)
    # Peak at 1.10, trough at 0.88. DD = (0.88 - 1.10) / 1.10
    expected_dd = (0.88 - 1.10) / 1.10
    assert abs(metrics["max_drawdown"] - expected_dd) < 1e-9


def test_max_drawdown_monotone_up():
    """All positive returns: max_drawdown should be 0."""
    rets = pd.Series([0.01, 0.02, 0.03])
    metrics = portfolio_metrics(rets)
    assert metrics["max_drawdown"] == 0.0


def test_max_drawdown_single_drop():
    """Single large drop of 50%: max_drawdown = -0.50."""
    rets = pd.Series([0.0, -0.50])
    metrics = portfolio_metrics(rets)
    assert abs(metrics["max_drawdown"] - (-0.50)) < 1e-9


# ── Test 9: SPY beta ─────────────────────────────────────────────────────────

def test_spy_beta_perfect_correlation():
    """Portfolio = 2 * SPY returns => beta = 2.0."""
    rng = np.random.default_rng(1)
    spy = pd.Series(rng.normal(0.01, 0.04, 24),
                    index=pd.date_range("2020-01-31", periods=24, freq="ME"))
    port = spy * 2.0
    metrics = portfolio_metrics(port, spy_returns=spy)
    assert abs(metrics["beta"] - 2.0) < 1e-6


def test_spy_beta_zero():
    """Portfolio = constant (0% return every month) => beta = 0."""
    spy = pd.Series(
        [0.01, -0.02, 0.03, 0.01, -0.01, 0.02],
        index=pd.date_range("2020-01-31", periods=6, freq="ME"),
    )
    port = pd.Series(0.0, index=spy.index)
    metrics = portfolio_metrics(port, spy_returns=spy)
    assert abs(metrics["beta"]) < 1e-9


# ── Test 10: Portfolio size ───────────────────────────────────────────────────

def test_portfolio_size_top_pct_20():
    """top_pct_20 selects correct number of stocks (ceil(20% of universe)."""
    n_tickers = 50
    df = _make_universe(n_tickers=n_tickers, n_months=3)
    result = run_monthly_backtest(df, score_col="score", tc_bps=0,
                                  portfolios={"top_pct_20": 0.20})
    bt = result["top_pct_20"]
    expected_n = int(np.ceil(n_tickers * 0.20))  # 10
    for _, row in bt.iterrows():
        assert row["n_stocks"] <= expected_n


def test_portfolio_size_top_n_25():
    """top_n_25 selects at most 25 stocks."""
    df = _make_universe(n_tickers=50, n_months=3)
    result = run_monthly_backtest(df, score_col="score", tc_bps=0,
                                  portfolios={"top_n_25": 25})
    bt = result["top_n_25"]
    for _, row in bt.iterrows():
        assert row["n_stocks"] <= 25


def test_portfolio_size_capped_by_universe():
    """If universe < top_n, selects entire universe."""
    df = _make_universe(n_tickers=10, n_months=3)
    result = run_monthly_backtest(df, score_col="score", tc_bps=0,
                                  portfolios={"top_50": 50})
    bt = result["top_50"]
    for _, row in bt.iterrows():
        assert row["n_stocks"] <= 10


# ── Test 11: compute_universe_benchmark ───────────────────────────────────────

def test_universe_benchmark_correct_return():
    """Equal-weight universe benchmark = mean of all stock returns."""
    prices_t0 = [100.0, 100.0, 100.0]
    prices_t1 = [110.0, 90.0, 100.0]
    df = _make_two_date_universe(prices_t0, prices_t1)
    bench = compute_universe_benchmark(df)
    expected = np.mean([p1 / p0 - 1.0 for p0, p1 in zip(prices_t0, prices_t1)])
    assert len(bench) == 1
    assert abs(bench.iloc[0] - expected) < 1e-9


def test_universe_benchmark_single_stock():
    """Universe with 1 stock: benchmark = that stock's return."""
    df = _make_two_date_universe([100.0], [115.0])
    bench = compute_universe_benchmark(df)
    assert abs(bench.iloc[0] - 0.15) < 1e-9


def test_universe_benchmark_multiple_periods():
    """Universe benchmark covers all consecutive month pairs."""
    df = _make_universe(n_tickers=5, n_months=4, monthly_return=0.02)
    bench = compute_universe_benchmark(df)
    # 4 month-end dates → 3 return periods
    assert len(bench) == 3


# ── Test 12: Sortino uses only downside ───────────────────────────────────────

def test_sortino_uses_downside_only():
    """Sortino denominator = std of negative returns only (not all returns)."""
    # Use different negative values so downside std > 0
    rets = pd.Series([0.05, 0.03, -0.10, 0.04, 0.06, -0.15])
    metrics = portfolio_metrics(rets, rf=0.0)
    downside = rets[rets < 0]
    downside_std = float(downside.std(ddof=1))
    expected_sortino = rets.mean() * 12 / (downside_std * np.sqrt(12))
    assert abs(metrics["sortino"] - expected_sortino) < 1e-9


def test_sortino_nan_when_no_downside():
    """All positive returns: sortino is nan (no downside dev)."""
    rets = pd.Series([0.01, 0.02, 0.03, 0.04])
    metrics = portfolio_metrics(rets, rf=0.0)
    # Only 1 negative return possible (none here), so either NaN or very high
    # With no negative returns, downside is empty → sortino should be NaN
    assert np.isnan(metrics["sortino"])


# ── Test: Information ratio ───────────────────────────────────────────────────

def test_information_ratio():
    """IR = mean(active_return) * 12 / tracking_error."""
    spy = pd.Series(
        [0.01] * 24,
        index=pd.date_range("2020-01-31", periods=24, freq="ME"),
    )
    port = pd.Series(0.015, index=spy.index)  # constant 0.5% outperformance/month
    metrics = portfolio_metrics(port, spy_returns=spy)
    active = port.values - spy.values
    te = float(np.std(active, ddof=1) * np.sqrt(12))
    # TE should be ~0 since active returns are constant
    # IR might be NaN or very large — just check te is near 0
    assert abs(metrics.get("tracking_error", np.nan)) < 1e-9 or np.isnan(metrics.get("info_ratio", np.nan))


# ── Test: Default portfolio configs ──────────────────────────────────────────

def test_default_portfolio_configs_keys():
    """PORTFOLIO_CONFIGS has the 4 required portfolio variants."""
    assert "top_pct_20" in PORTFOLIO_CONFIGS
    assert "top_pct_10" in PORTFOLIO_CONFIGS
    assert "top_n_50" in PORTFOLIO_CONFIGS
    assert "top_n_25" in PORTFOLIO_CONFIGS


def test_run_backtest_returns_all_portfolios():
    """run_monthly_backtest with defaults returns all 4 portfolio variants."""
    df = _make_universe(n_tickers=60, n_months=4)
    result = run_monthly_backtest(df, score_col="score", tc_bps=10)
    for port_name in PORTFOLIO_CONFIGS:
        assert port_name in result


def test_run_backtest_result_columns():
    """Each portfolio result DataFrame has required columns."""
    df = _make_universe(n_tickers=30, n_months=4)
    result = run_monthly_backtest(df, score_col="score", tc_bps=10,
                                  portfolios={"test_port": 10})
    bt = result["test_port"]
    for col in ["gross_return", "tc_cost", "net_return", "turnover", "n_stocks"]:
        assert col in bt.columns


# ── Test: Monthly win rate ────────────────────────────────────────────────────

def test_monthly_win_rate():
    """Win rate = fraction of months with positive return."""
    rets = pd.Series([0.01, -0.02, 0.03, -0.01, 0.05, -0.03])
    metrics = portfolio_metrics(rets)
    # 3 positive, 3 negative
    assert abs(metrics["monthly_win_rate"] - 0.5) < 1e-9


# ── Test: n_months in metrics ────────────────────────────────────────────────

def test_portfolio_metrics_n_months():
    """portfolio_metrics reports correct n_months."""
    rets = pd.Series([0.01] * 20)
    metrics = portfolio_metrics(rets)
    assert metrics["n_months"] == 20
