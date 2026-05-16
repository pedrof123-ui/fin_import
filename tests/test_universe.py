"""
Unit tests for historic_fundamentals/universe.py — Phase 2.

Tests
-----
1. filter_universe removes rows below min_market_cap.
2. filter_universe removes rows below min_price.
3. filter_universe removes rows where market_cap is NaN.
4. filter_universe removes rows where sector is NaN when require_sector=True.
5. filter_universe keeps rows where sector is NaN when require_sector=False.
6. filter_universe with min_market_cap=0, min_price=0, require_sector=False returns all rows.
7. report_universe_counts returns one row per month with correct ticker counts.
8. sensitivity_analysis returns one row per threshold with the correct threshold values.
"""

import numpy as np
import pandas as pd
import pytest

from historic_fundamentals.universe import (
    UNIVERSE_DEFAULTS,
    filter_universe,
    report_universe_counts,
    sensitivity_analysis,
)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_df(**overrides) -> pd.DataFrame:
    """Build a small universe DataFrame with sensible defaults."""
    base = {
        "ticker":      ["AAPL", "MSFT", "TINY", "CHEAP", "NOSEC"],
        "month_end_date": pd.to_datetime(["2024-01-31"] * 5),
        "price":       [180.0, 400.0, 3.0, 2.0, 50.0],
        "shares":      [15_000e6, 7_000e6, 50e6, 80e6, 200e6],
        "sector":      ["Technology", "Technology", "Healthcare", "Financials", None],
    }
    base.update(overrides)
    df = pd.DataFrame(base)
    df["market_cap"] = df["shares"] * df["price"]
    return df


# ── Test 1: market_cap filter ─────────────────────────────────────────────────

def test_filter_universe_removes_below_min_market_cap():
    df = _make_df()
    # AAPL: 2.7T, MSFT: 2.8T pass; TINY: 150M, CHEAP: 160M fail
    result = filter_universe(df, min_market_cap=1e9, min_price=0.0, require_sector=False)
    assert "AAPL" in result["ticker"].values
    assert "MSFT" in result["ticker"].values
    assert "TINY" not in result["ticker"].values
    assert "CHEAP" not in result["ticker"].values


# ── Test 2: price filter ──────────────────────────────────────────────────────

def test_filter_universe_removes_below_min_price():
    df = _make_df()
    # CHEAP price=2.0, TINY price=3.0 — both below min_price=5.0
    result = filter_universe(df, min_market_cap=0.0, min_price=5.0, require_sector=False)
    assert "AAPL" in result["ticker"].values
    assert "CHEAP" not in result["ticker"].values
    assert "TINY" not in result["ticker"].values


# ── Test 3: NaN market_cap does not bypass filter ─────────────────────────────

def test_filter_universe_removes_nan_market_cap():
    df = _make_df()
    df.loc[df["ticker"] == "AAPL", "market_cap"] = np.nan
    result = filter_universe(df, min_market_cap=1e9, min_price=0.0, require_sector=False)
    assert "AAPL" not in result["ticker"].values


# ── Test 4: sector filter when require_sector=True ───────────────────────────

def test_filter_universe_removes_nan_sector_when_required():
    df = _make_df()
    # NOSEC has sector=None
    result = filter_universe(df, min_market_cap=0.0, min_price=0.0, require_sector=True)
    assert "NOSEC" not in result["ticker"].values


# ── Test 5: sector filter when require_sector=False ──────────────────────────

def test_filter_universe_keeps_nan_sector_when_not_required():
    df = _make_df()
    result = filter_universe(df, min_market_cap=0.0, min_price=0.0, require_sector=False)
    assert "NOSEC" in result["ticker"].values


# ── Test 6: passthrough with all thresholds at zero ──────────────────────────

def test_filter_universe_passthrough_all_rows():
    df = _make_df()
    result = filter_universe(df, min_market_cap=0.0, min_price=0.0, require_sector=False)
    assert len(result) == len(df)


# ── Test 7: report_universe_counts one row per month ─────────────────────────

def test_report_universe_counts_one_row_per_month():
    # 3 months, 2 tickers each — expect 3 rows with ticker_count=2
    months = pd.to_datetime(["2024-01-31", "2024-01-31",
                              "2024-02-29", "2024-02-29",
                              "2024-03-31", "2024-03-31"])
    df = pd.DataFrame({
        "ticker": ["AAPL", "MSFT", "AAPL", "MSFT", "AAPL", "MSFT"],
        "month_end_date": months,
        "sector": ["Technology"] * 6,
    })
    result = report_universe_counts(df)
    assert len(result) == 3
    assert list(result.columns) == ["month_end_date", "ticker_count", "sector_count"]
    assert (result["ticker_count"] == 2).all()


def test_report_universe_counts_correct_ticker_count():
    # Month 1: 3 tickers; Month 2: 1 ticker
    df = pd.DataFrame({
        "ticker": ["A", "B", "C", "A"],
        "month_end_date": pd.to_datetime(["2024-01-31", "2024-01-31", "2024-01-31", "2024-02-29"]),
        "sector": ["Tech", "Tech", "Finance", "Tech"],
    })
    result = report_universe_counts(df)
    assert len(result) == 2
    jan_row = result[result["month_end_date"].dt.month == 1].iloc[0]
    feb_row = result[result["month_end_date"].dt.month == 2].iloc[0]
    assert jan_row["ticker_count"] == 3
    assert feb_row["ticker_count"] == 1


# ── Test 8: sensitivity_analysis one row per threshold ───────────────────────

def test_sensitivity_analysis_returns_one_row_per_threshold():
    df = _make_df()
    thresholds = [300e6, 1e9, 5e9]
    result = sensitivity_analysis(df, thresholds=thresholds, min_price=0.0)
    assert len(result) == 3
    assert list(result["threshold_b"]) == [0.3, 1.0, 5.0]


def test_sensitivity_analysis_default_thresholds():
    df = _make_df()
    result = sensitivity_analysis(df)
    assert len(result) == 3
    assert set(result["threshold_b"]) == {0.3, 1.0, 5.0}


def test_sensitivity_analysis_columns():
    df = _make_df()
    result = sensitivity_analysis(df, thresholds=[1e9])
    expected_cols = ["threshold_b", "total_rows", "unique_tickers",
                     "months_with_data", "avg_monthly_universe_size"]
    assert list(result.columns) == expected_cols


def test_sensitivity_analysis_larger_threshold_has_fewer_tickers():
    # Stricter threshold should keep fewer or equal tickers
    df = _make_df()
    result = sensitivity_analysis(df, thresholds=[300e6, 1e9, 5e9], min_price=0.0)
    assert result.iloc[0]["unique_tickers"] >= result.iloc[1]["unique_tickers"]
    assert result.iloc[1]["unique_tickers"] >= result.iloc[2]["unique_tickers"]


# ── Test: market_cap computed from shares * price when not present ────────────

def test_filter_universe_computes_market_cap_from_shares_and_price():
    df = pd.DataFrame({
        "ticker": ["BIG", "SMALL"],
        "month_end_date": pd.to_datetime(["2024-01-31", "2024-01-31"]),
        "price": [100.0, 3.0],
        "shares": [20_000e6, 50e6],  # 2T vs 150M
        "sector": ["Technology", "Technology"],
    })
    # No market_cap column — must be computed internally
    assert "market_cap" not in df.columns
    result = filter_universe(df, min_market_cap=1e9, min_price=0.0, require_sector=False)
    assert "BIG" in result["ticker"].values
    assert "SMALL" not in result["ticker"].values


# ── Test: UNIVERSE_DEFAULTS dict ─────────────────────────────────────────────

def test_universe_defaults_values():
    assert UNIVERSE_DEFAULTS["min_market_cap"] == 1_000_000_000
    assert UNIVERSE_DEFAULTS["min_price"] == 5.0
    assert UNIVERSE_DEFAULTS["require_sector"] is True
