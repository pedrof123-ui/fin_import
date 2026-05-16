"""
Point-in-time alignment tests for build_monthly_pe().

Verifies that:
1. _feature_available_date() applies the correct reporting lags.
2. build_monthly_pe() excludes quarterly observations that are within the
   60-day lag window relative to the prediction date (month_end_date).
3. build_monthly_pe() includes the same observation once the lag window has passed.
4. feature_available_date column is present in the output DataFrame.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from historic_fundamentals.pe import _feature_available_date, build_monthly_pe

# Lag constants (must match pe.py)
_LAG_Q = 60
_LAG_A = 90


# ── Test 1: _feature_available_date lag values ────────────────────────────────

def test_feature_available_date_quarterly():
    fde = date(2024, 1, 31)
    result = _feature_available_date(fde, "quarterly")
    assert result == fde + timedelta(days=_LAG_Q)


def test_feature_available_date_annual():
    fde = date(2023, 12, 31)
    result = _feature_available_date(fde, "annual")
    assert result == fde + timedelta(days=_LAG_A)


def test_feature_available_date_quarterly_generic():
    # Generic: any fiscal_date_ending should return + 60 days for quarterly
    for fde in [date(2022, 3, 31), date(2022, 6, 30), date(2022, 9, 30), date(2022, 12, 31)]:
        assert _feature_available_date(fde, "quarterly") == fde + timedelta(days=_LAG_Q)


def test_feature_available_date_annual_generic():
    for year in [2020, 2021, 2022, 2023]:
        fde = date(year, 12, 31)
        assert _feature_available_date(fde, "annual") == fde + timedelta(days=_LAG_A)


# ── Shared synthetic data helpers ─────────────────────────────────────────────

def _make_quarterly_with_dates(dates) -> pd.DataFrame:
    """Build quarterly DataFrame from an explicit list of fiscal_date_ending dates."""
    n = len(dates)
    return pd.DataFrame({
        "fiscal_date_ending":              dates,
        "net_income":                      [100.0] * n,
        "total_revenue":                   [1000.0] * n,
        "gross_profit":                    [400.0] * n,
        "operating_income":                [200.0] * n,
        "interest_expense":                [-10.0] * n,
        "ebitda":                          [300.0] * n,
        "ebit":                            [250.0] * n,
        "income_tax_expense":              [25.0] * n,
        "income_before_tax":               [240.0] * n,
        "shares":                          [1000.0] * n,
        "total_assets":                    [5000.0] * n,
        "total_shareholder_equity":        [2000.0] * n,
        "intangible_assets_excl_goodwill": [0.0] * n,
        "goodwill":                        [0.0] * n,
        "long_term_debt_noncurrent":       [800.0] * n,
        "short_term_debt":                 [200.0] * n,
        "current_long_term_debt":          [0.0] * n,
        "cash_and_short_term_investments": [500.0] * n,
    })


def _make_cashflow_with_dates(dates) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame({
        "fiscal_date_ending":   dates,
        "operating_cashflow":   [200.0] * n,
        "capital_expenditures": [50.0] * n,
    })


def _make_prices(month_end_date: str, price: float = 50.0) -> pd.DataFrame:
    return pd.DataFrame({
        "month_end_date": [month_end_date],
        "price":          [price],
    })


# Quarter-end dates preceding 2024-01-31 at standard 3-month intervals
# (non-standard quarter-end: Jan/Apr/Jul/Oct fiscal year)
_FISCAL_DATES_JAN = [
    date(2023, 1, 31),
    date(2023, 4, 30),
    date(2023, 7, 31),
    date(2023, 10, 31),
    date(2024, 1, 31),
]


# ── Test 2: Quarterly observation within 60-day lag is EXCLUDED ───────────────

def test_quarterly_obs_excluded_within_lag_window():
    """
    The most recent quarter ends 2024-01-31. feature_available_date = 2024-01-31 + 60d.
    At month_end = 2024-02-28 (28 days after quarter end), data should be excluded
    because feature_available_date > 2024-02-28.
    """
    fiscal_end = date(2024, 1, 31)
    fad = fiscal_end + timedelta(days=_LAG_Q)
    prediction_date = "2024-02-28"

    q = _make_quarterly_with_dates(_FISCAL_DATES_JAN)
    cfq = _make_cashflow_with_dates(_FISCAL_DATES_JAN)
    prices = _make_prices(prediction_date)

    df = build_monthly_pe(q, pd.DataFrame(), prices, cashflow_q=cfq)
    # At 2024-02-28, fad=fiscal_end+60d is still in the future, so the most
    # recent quarter must be excluded. The prior quarters ending Oct 2023 are
    # available (Oct 31 + 60d = Dec 30, 2023 <= Feb 28, 2024), so there should
    # still be 4 available quarters. But the task-specified scenario requires
    # checking that the 2024-01-31 quarter is NOT used.
    # Verify: the most recent fiscal_date_ending used does not include 2024-01-31.
    if not df.empty:
        # If the result is non-empty, it must not have used the 2024-01-31 quarter
        # as the most recent period — check feature_available_date < prediction_date.
        pred = pd.Timestamp(prediction_date).date()
        for _, row in df.iterrows():
            fad_row = row.get("feature_available_date")
            if fad_row is not None and not pd.isna(fad_row):
                assert fad_row <= pred, (
                    f"feature_available_date {fad_row} > prediction_date {pred}"
                )


def test_quarterly_obs_latest_excluded_when_within_lag():
    """
    Strict scenario: ONLY the 2024-01-31 quarter exists (no prior data).
    At month_end = 2024-02-28, result must be empty.
    """
    fiscal_end = date(2024, 1, 31)
    prediction_date = "2024-02-28"

    q = _make_quarterly_with_dates([fiscal_end])
    cfq = _make_cashflow_with_dates([fiscal_end])
    prices = _make_prices(prediction_date)

    df = build_monthly_pe(q, pd.DataFrame(), prices, cashflow_q=cfq)
    assert df.empty, (
        f"Expected empty DataFrame at {prediction_date} but got {len(df)} rows. "
        f"The only quarterly obs ends {fiscal_end} (fad={fiscal_end + timedelta(days=_LAG_Q)}), "
        f"which is not yet available at {prediction_date}."
    )


# ── Test 3: Same quarterly observation IS included after lag window ───────────

def test_quarterly_obs_included_after_lag_window():
    """
    Quarter ends 2024-01-31. feature_available_date = 2024-01-31 + 60d.
    At month_end = 2024-04-30, data should be included.

    Supply 4 quarters so TTM EPS can be computed (requires >= 4 quarters).
    All 4 quarters must be available at 2024-04-30 (their fad <= 2024-04-30).
    """
    # 4 quarters ending at 2024-01-31 at 3-month intervals
    dates_4q = [date(2023, 4, 30), date(2023, 7, 31), date(2023, 10, 31), date(2024, 1, 31)]
    # Verify all are available at 2024-04-30
    for d in dates_4q:
        fad = d + timedelta(days=_LAG_Q)
        assert fad <= date(2024, 4, 30), f"Pre-condition failed: {d} fad={fad}"

    prediction_date = "2024-04-30"
    q = _make_quarterly_with_dates(dates_4q)
    cfq = _make_cashflow_with_dates(dates_4q)
    prices = _make_prices(prediction_date)

    df = build_monthly_pe(q, pd.DataFrame(), prices, cashflow_q=cfq)
    assert not df.empty, (
        f"Expected non-empty DataFrame at {prediction_date}. "
        f"All 4 quarterly obs should be available (fad <= {prediction_date})"
    )
    assert len(df) == 1


# ── Test 3b: Boundary — exactly one day before the lag crosses month-end ──────

def test_quarterly_obs_boundary_before_and_after():
    """
    4 quarters with most recent ending 2023-09-30.
    feature_available_date for the most recent = 2023-09-30 + 60d = 2023-11-29.

    At month_end = 2023-10-31: the most recent quarter is still in lag window
    (fad=2023-11-29 > 2023-10-31), so it must be excluded from the pit-filtered set.
    The 3 earlier quarters (ending Dec 2022, Mar 2023, Jun 2023) have fads of
    Mar 2023, May 2023, Aug 2023 — all <= Oct 31, 2023. With only 3 available
    quarters (< 4 required for TTM), the function falls back to annual data.
    Since no annual data is provided, the result should be empty.

    At month_end = 2023-11-30: all 4 quarters are now available (fad=2023-11-29 <= 2023-11-30),
    TTM can be computed, result should be non-empty.
    """
    dates_4q = [date(2022, 12, 31), date(2023, 3, 31), date(2023, 6, 30), date(2023, 9, 30)]
    fiscal_end = dates_4q[-1]
    fad = fiscal_end + timedelta(days=_LAG_Q)

    q = _make_quarterly_with_dates(dates_4q)
    cfq = _make_cashflow_with_dates(dates_4q)

    # 2023-10-31: most recent quarter (Sep 30) excluded (fad=Nov 29 > Oct 31)
    # → only 3 quarters available for TTM → empty (no annual fallback)
    prices_before = _make_prices("2023-10-31")
    df_before = build_monthly_pe(q, pd.DataFrame(), prices_before, cashflow_q=cfq)
    assert df_before.empty, (
        f"Expected empty at 2023-10-31: most recent Q (fad={fad}) not yet available, "
        f"only 3 prior quarters present, TTM requires 4"
    )

    # 2023-11-30: fad=2023-11-29 <= 2023-11-30 → all 4 quarters available
    prices_after = _make_prices("2023-11-30")
    df_after = build_monthly_pe(q, pd.DataFrame(), prices_after, cashflow_q=cfq)
    assert not df_after.empty, f"Expected non-empty at 2023-11-30 (fad={fad} <= 2023-11-30)"


# ── Test 4: feature_available_date column is present ─────────────────────────

def test_feature_available_date_column_present():
    """
    build_monthly_pe() must return a DataFrame with a feature_available_date column.
    Supply 4 quarters all available well before the prediction date.
    """
    dates_4q = [date(2022, 12, 31), date(2023, 3, 31), date(2023, 6, 30), date(2023, 9, 30)]
    prediction_date = "2024-01-31"

    # All fads <= prediction_date
    for d in dates_4q:
        assert d + timedelta(days=_LAG_Q) <= date(2024, 1, 31), f"Pre-condition: {d} not available"

    q = _make_quarterly_with_dates(dates_4q)
    cfq = _make_cashflow_with_dates(dates_4q)
    prices = _make_prices(prediction_date)

    df = build_monthly_pe(q, pd.DataFrame(), prices, cashflow_q=cfq)
    assert not df.empty
    assert "feature_available_date" in df.columns, (
        "build_monthly_pe() output must contain a 'feature_available_date' column"
    )


def test_feature_available_date_is_lte_month_end():
    """
    For every row in the output, feature_available_date must be <= month_end_date.
    """
    n_months = 12
    prices = pd.DataFrame({
        "month_end_date": pd.date_range("2023-01-31", periods=n_months, freq="ME"),
        "price":          [50.0] * n_months,
    })
    q = pd.DataFrame({
        "fiscal_date_ending":              pd.date_range("2019-01-01", periods=20, freq="QE"),
        "net_income":                      [100.0] * 20,
        "total_revenue":                   [1000.0] * 20,
        "gross_profit":                    [400.0] * 20,
        "operating_income":                [200.0] * 20,
        "interest_expense":                [-10.0] * 20,
        "ebitda":                          [300.0] * 20,
        "ebit":                            [250.0] * 20,
        "income_tax_expense":              [25.0] * 20,
        "income_before_tax":               [240.0] * 20,
        "shares":                          [1000.0] * 20,
        "total_assets":                    [5000.0] * 20,
        "total_shareholder_equity":        [2000.0] * 20,
        "intangible_assets_excl_goodwill": [0.0] * 20,
        "goodwill":                        [0.0] * 20,
        "long_term_debt_noncurrent":       [800.0] * 20,
        "short_term_debt":                 [200.0] * 20,
        "current_long_term_debt":          [0.0] * 20,
        "cash_and_short_term_investments": [500.0] * 20,
    })
    cfq = pd.DataFrame({
        "fiscal_date_ending":   pd.date_range("2019-01-01", periods=20, freq="QE"),
        "operating_cashflow":   [200.0] * 20,
        "capital_expenditures": [50.0] * 20,
    })
    df = build_monthly_pe(q, pd.DataFrame(), prices, cashflow_q=cfq)

    assert not df.empty
    assert "feature_available_date" in df.columns

    # Every non-null feature_available_date must be <= its month_end_date
    mask = df["feature_available_date"].notna()
    violations = df[mask & (df["feature_available_date"] > df["month_end_date"])]
    assert violations.empty, (
        f"feature_available_date > month_end_date for {len(violations)} rows:\n"
        f"{violations[['month_end_date', 'feature_available_date']]}"
    )
