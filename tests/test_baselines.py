"""
Unit tests for historic_fundamentals/baselines.py — Phase 4.

Tests
-----
1. compute_factor_ic returns a Series with correct length (one value per month
   with enough stocks).
2. compute_factor_ic returns NaN for months with fewer than min_stocks stocks.
3. ic_summary returns all required keys.
4. quintile_returns returns the correct number of quintile columns and a spread column.
5. quintile_returns Q1 has higher mean return than Q5 for a synthetic factor
   with a known monotone signal.
6. composite_score returns expected z-score direction for a simple case.
7. run_all_baselines returns one row per baseline factor/composite.

All tests use synthetic DataFrames — no real database connections.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from historic_fundamentals.baselines import (
    BASELINE_FACTORS,
    compute_factor_ic,
    composite_score,
    ic_summary,
    quintile_returns,
    run_all_baselines,
)


# ── Synthetic data helpers ────────────────────────────────────────────────────

def _make_universe(
    n_tickers: int = 50,
    n_months: int = 24,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Build a synthetic monthly universe DataFrame with all BASELINE_FACTORS columns,
    quality columns, momentum, and a known ret_1y signal.

    The return signal is: ret_1y = -0.3 * ps_ratio + noise
    (i.e., low ps_ratio -> higher return, matching lower_is_better=True for low_ps).
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-31", periods=n_months, freq="ME")

    rows = []
    for date in dates:
        for i in range(n_tickers):
            ticker = f"T{i:03d}"
            ps = rng.uniform(0.5, 20.0)
            fcf_yield = rng.uniform(-0.05, 0.15)
            div_yield = rng.uniform(0.0, 0.06)
            ev_ebitda = rng.uniform(3.0, 30.0)
            pe = rng.uniform(5.0, 50.0)
            ey = 1.0 / pe
            roic = rng.uniform(0.02, 0.30)
            roa = rng.uniform(0.01, 0.20)
            om_slope = rng.uniform(-0.02, 0.04)
            momentum = rng.uniform(-0.20, 0.40)
            # Monotone signal: low ps -> high ret_1y
            ret_1y = -0.3 * ps + rng.normal(0.0, 0.5)
            ret_6m = -0.15 * ps + rng.normal(0.0, 0.3)
            rows.append({
                "ticker": ticker,
                "month_end_date": date,
                "price": rng.uniform(10.0, 200.0),
                "shares": rng.uniform(1e8, 1e10),
                "ps_ratio": ps,
                "fcf_yield": fcf_yield,
                "dividend_yield": div_yield,
                "ev_ebitda": ev_ebitda,
                "pe_ratio": pe,
                "earnings_yield": ey,
                "roic": roic,
                "roa": roa,
                "operating_margin_slope_5y": om_slope,
                "momentum_12_1": momentum,
                "ret_1y": ret_1y,
                "ret_6m": ret_6m,
            })

    return pd.DataFrame(rows)


def _make_sparse_universe(
    n_tickers_full: int = 50,
    n_tickers_sparse: int = 5,
    seed: int = 7,
) -> pd.DataFrame:
    """
    Two months: one with n_tickers_full stocks, one with n_tickers_sparse.
    Used to test min_stocks threshold.
    """
    rng = np.random.default_rng(seed)
    dates = [pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-29")]
    sizes = [n_tickers_full, n_tickers_sparse]
    rows = []
    for date, n in zip(dates, sizes):
        for i in range(n):
            rows.append({
                "ticker": f"T{i:03d}",
                "month_end_date": date,
                "ps_ratio": rng.uniform(1.0, 10.0),
                "ret_1y": rng.uniform(-0.2, 0.5),
            })
    return pd.DataFrame(rows)


# ── Test 1 ────────────────────────────────────────────────────────────────────

def test_compute_factor_ic_length():
    """IC series has one entry per month with enough stocks."""
    df = _make_universe(n_tickers=50, n_months=12)
    ic = compute_factor_ic(df, "ps_ratio", "ret_1y", lower_is_better=True, min_stocks=20)
    assert isinstance(ic, pd.Series), "IC must be a pd.Series"
    # All 12 months have 50 tickers, all should be non-NaN
    assert len(ic) == 12, f"Expected 12 IC values, got {len(ic)}"
    assert ic.notna().all(), "All months with 50 tickers should have valid IC"


# ── Test 2 ────────────────────────────────────────────────────────────────────

def test_compute_factor_ic_min_stocks_nan():
    """Months with fewer than min_stocks produce NaN IC."""
    df = _make_sparse_universe(n_tickers_full=50, n_tickers_sparse=5)
    ic = compute_factor_ic(df, "ps_ratio", "ret_1y", lower_is_better=True, min_stocks=20)
    # Month with 50 tickers -> valid IC
    # Month with 5 tickers -> NaN
    assert len(ic) == 2
    valid_month = pd.Timestamp("2020-01-31")
    sparse_month = pd.Timestamp("2020-02-29")
    assert np.isfinite(ic.loc[valid_month]), "Month with 50 tickers should have valid IC"
    assert np.isnan(ic.loc[sparse_month]), "Month with 5 tickers should be NaN"


# ── Test 3 ────────────────────────────────────────────────────────────────────

def test_ic_summary_keys():
    """ic_summary returns all required keys."""
    required_keys = {"mean_ic", "std_ic", "icir", "icir_nw", "hit_rate", "t_stat", "n_months"}
    df = _make_universe(n_tickers=50, n_months=12)
    ic = compute_factor_ic(df, "ps_ratio", "ret_1y", lower_is_better=True, min_stocks=20)
    result = ic_summary(ic, nw_lags=3)
    missing = required_keys - set(result.keys())
    assert not missing, f"Missing keys in ic_summary result: {missing}"


def test_ic_summary_empty():
    """ic_summary handles all-NaN series gracefully."""
    ic = pd.Series([np.nan, np.nan, np.nan])
    result = ic_summary(ic)
    required_keys = {"mean_ic", "std_ic", "icir", "icir_nw", "hit_rate", "t_stat", "n_months"}
    assert set(result.keys()) >= required_keys
    assert result["n_months"] == 0


# ── Test 4 ────────────────────────────────────────────────────────────────────

def test_quintile_returns_columns():
    """quintile_returns returns Q1..Q5 columns plus 'spread'."""
    df = _make_universe(n_tickers=50, n_months=6)
    qt = quintile_returns(df, "ps_ratio", "ret_1y", lower_is_better=True, n_bins=5, min_stocks=20)
    assert isinstance(qt, pd.DataFrame)
    for col in ["Q1", "Q2", "Q3", "Q4", "Q5", "spread"]:
        assert col in qt.columns, f"Missing column: {col}"


# ── Test 5 ────────────────────────────────────────────────────────────────────

def test_quintile_returns_q1_beats_q5():
    """
    With a known monotone signal (low ps_ratio -> high ret_1y),
    Q1 (best = lowest ps) should have higher mean return than Q5 (worst = highest ps).
    """
    df = _make_universe(n_tickers=100, n_months=36, seed=0)
    qt = quintile_returns(df, "ps_ratio", "ret_1y", lower_is_better=True, n_bins=5, min_stocks=20)
    q1_mean = qt["Q1"].mean()
    q5_mean = qt["Q5"].mean()
    assert q1_mean > q5_mean, (
        f"Q1 mean return ({q1_mean:.4f}) should be > Q5 mean return ({q5_mean:.4f}) "
        f"for a monotone factor"
    )
    assert (qt["spread"] > 0).mean() >= 0.6, "Spread should be positive in most months"


# ── Test 6 ────────────────────────────────────────────────────────────────────

def test_composite_score_direction():
    """
    composite_score: a stock with low ps_ratio should score higher (better)
    than a stock with high ps_ratio when lower_is_better=True.
    """
    # Single month with two tickers: one cheap (low ps), one expensive (high ps)
    df = pd.DataFrame({
        "ticker": ["CHEAP", "EXPENSIVE"],
        "month_end_date": [pd.Timestamp("2020-01-31")] * 2,
        "ps_ratio": [1.0, 20.0],
    })
    scores = composite_score(
        df,
        factor_cols=["ps_ratio"],
        lower_is_better_map={"ps_ratio": True},
    )
    assert len(scores) == 2
    cheap_score = scores.loc[df["ticker"] == "CHEAP"].iloc[0]
    exp_score = scores.loc[df["ticker"] == "EXPENSIVE"].iloc[0]
    assert cheap_score > exp_score, (
        f"Cheap stock (low ps) should score higher: {cheap_score:.4f} vs {exp_score:.4f}"
    )


def test_composite_score_nan_contributes_zero():
    """NaN factor values contribute 0 to the composite (stock still gets a score)."""
    df = pd.DataFrame({
        "ticker": ["A", "B", "C"],
        "month_end_date": [pd.Timestamp("2020-01-31")] * 3,
        "fcf_yield": [0.10, 0.05, np.nan],
        "ps_ratio": [2.0, 5.0, 1.0],
    })
    scores = composite_score(
        df,
        factor_cols=["fcf_yield", "ps_ratio"],
        lower_is_better_map={"fcf_yield": False, "ps_ratio": True},
    )
    # All three stocks must receive a score (no NaN in output)
    assert scores.notna().all(), "All stocks should receive a composite score"


def test_composite_score_sector_neutral_false_identical():
    """sector_neutral=False (default) must produce bit-for-bit identical results."""
    df = pd.DataFrame({
        "ticker": ["A", "B", "C", "D"],
        "month_end_date": [pd.Timestamp("2020-01-31")] * 4,
        "sector": ["Tech", "Tech", "Energy", "Energy"],
        "ps_ratio": [1.0, 5.0, 2.0, 8.0],
    })
    scores_default = composite_score(df, ["ps_ratio"], {"ps_ratio": True})
    scores_explicit = composite_score(df, ["ps_ratio"], {"ps_ratio": True}, sector_neutral=False)
    pd.testing.assert_series_equal(scores_default, scores_explicit)


def test_composite_score_sector_neutral_independent_per_sector():
    """
    With sector_neutral=True, each sector is z-scored independently.

    Sector A: ps_ratio [1, 2, 3, 4, 5]  (values 1-5)
    Sector B: ps_ratio [10, 20, 30, 40, 50]  (values 10-50, same relative spread)

    Market-wide: all of Sector A falls below the overall mean, so Sector A
    stocks would all get positive z-scores (lower ps is better → inverted).
    Sector-neutral: both sectors are scored relative to their own peers, so
    Sector A and Sector B should have the same rank order and similar z-score
    magnitudes (since they have the same relative spread within each sector).
    """
    rng = np.random.default_rng(0)
    month = pd.Timestamp("2020-01-31")
    # Same relative ordering in both sectors — sector-neutral should produce
    # nearly equal z-scores for rank-matched stocks across sectors.
    df = pd.DataFrame({
        "ticker": [f"A{i}" for i in range(5)] + [f"B{i}" for i in range(5)],
        "month_end_date": [month] * 10,
        "sector": ["Tech"] * 5 + ["Energy"] * 5,
        "ps_ratio": [1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 20.0, 30.0, 40.0, 50.0],
    })

    market_scores = composite_score(df, ["ps_ratio"], {"ps_ratio": True}, sector_neutral=False)
    sector_scores = composite_score(df, ["ps_ratio"], {"ps_ratio": True}, sector_neutral=True)

    # Scores must differ (sector-neutral is not identical to market-wide here)
    assert not np.allclose(market_scores.values, sector_scores.values), (
        "Sector-neutral scores should differ from market-wide when sectors have "
        "very different factor distributions"
    )

    # Within each sector, relative ordering is preserved
    tech_idx = df[df["sector"] == "Tech"].index
    energy_idx = df[df["sector"] == "Energy"].index
    assert sector_scores[tech_idx].is_monotonic_decreasing, (
        "Higher ps_ratio (lower_is_better) → lower score within Tech sector"
    )
    assert sector_scores[energy_idx].is_monotonic_decreasing, (
        "Higher ps_ratio (lower_is_better) → lower score within Energy sector"
    )

    # No NaN in output
    assert sector_scores.notna().all(), "Sector-neutral must not produce NaN scores"


def test_composite_score_sector_neutral_small_sector_fallback():
    """
    Stocks in a sector with < 3 peers fall back to market-wide z-score.
    """
    month = pd.Timestamp("2020-01-31")
    # Sector A: 5 stocks (eligible), Sector B: 2 stocks (too small → fallback)
    df = pd.DataFrame({
        "ticker": [f"A{i}" for i in range(5)] + ["B0", "B1"],
        "month_end_date": [month] * 7,
        "sector": ["Tech"] * 5 + ["Energy", "Energy"],
        "ps_ratio": [1.0, 2.0, 3.0, 4.0, 5.0, 2.5, 3.5],
    })

    sector_scores = composite_score(df, ["ps_ratio"], {"ps_ratio": True}, sector_neutral=True)
    market_scores = composite_score(df, ["ps_ratio"], {"ps_ratio": True}, sector_neutral=False)

    # Sector B stocks must use market-wide fallback → scores equal to market-wide
    b_idx = df[df["sector"] == "Energy"].index
    np.testing.assert_allclose(
        sector_scores[b_idx].values,
        market_scores[b_idx].values,
        err_msg="Small-sector stocks must use market-wide fallback",
    )

    # Sector A stocks must use sector z-score → different from market-wide
    a_idx = df[df["sector"] == "Tech"].index
    assert not np.allclose(sector_scores[a_idx].values, market_scores[a_idx].values), (
        "Stocks in a full sector should get sector z-scores, not market-wide"
    )


# ── Test 7 ────────────────────────────────────────────────────────────────────

def test_run_all_baselines_row_count():
    """
    run_all_baselines returns one row per factor/composite.
    Expected rows: 6 BASELINE_FACTORS + value_composite + value_quality + value_momentum.
    """
    df = _make_universe(n_tickers=60, n_months=24)
    result = run_all_baselines(df, return_col="ret_1y", min_stocks=20)
    assert isinstance(result, pd.DataFrame)

    expected_factors = set(BASELINE_FACTORS.keys())
    # Composites that should appear given the synthetic data has all columns
    expected_composites = {"value_composite", "value_quality", "value_momentum"}
    expected_all = expected_factors | expected_composites
    result_factors = set(result["factor"].tolist())

    missing = expected_all - result_factors
    assert not missing, f"Missing baseline rows: {missing}"


def test_run_all_baselines_columns():
    """run_all_baselines returns the required summary columns."""
    df = _make_universe(n_tickers=50, n_months=12)
    result = run_all_baselines(df, return_col="ret_1y", min_stocks=20)
    required_cols = {
        "factor", "mean_ic", "icir", "icir_nw", "hit_rate",
        "t_stat", "n_months", "q1_mean_ret", "q5_mean_ret", "spread",
    }
    missing = required_cols - set(result.columns)
    assert not missing, f"Missing columns in run_all_baselines output: {missing}"


def test_run_all_baselines_missing_factor_col():
    """
    run_all_baselines skips factors whose column is absent in df rather than raising.
    """
    df = _make_universe(n_tickers=50, n_months=12)
    # Drop dividend_yield so high_div_yield cannot be computed
    df = df.drop(columns=["dividend_yield"])
    result = run_all_baselines(df, return_col="ret_1y", min_stocks=20)
    assert "high_div_yield" not in result["factor"].values
    # All other factors should still appear
    remaining = set(BASELINE_FACTORS.keys()) - {"high_div_yield"}
    for f in remaining:
        assert f in result["factor"].values, f"Factor {f} should still appear"
