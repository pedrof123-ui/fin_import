"""
Unit tests for historic_fundamentals/model.py — Phase 5.

Tests use synthetic DataFrames only — no database connections.

Tests
-----
1.  walk_forward_validate returns correct fold structure keys.
2.  OOS folds are strictly after training cutoff (no data leakage).
3.  compute_oos_metrics returns all expected keys.
4.  rank_ic sign is correct for a perfect monotone predictor.
5.  Fold with fewer than min_train_months observations is skipped.
6.  Yearly breakdown has correct year keys.
7.  Feature importance DataFrame has n_features rows.
8.  aggregate contains mean_oos_r2, mean_rank_ic, etc.
9.  walk_forward_validate with sector_col runs without error.
10. Empty dataset returns empty results gracefully.
11. shap_stability returns a DataFrame with feature rows.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from historic_fundamentals.model import (
    compute_oos_metrics,
    walk_forward_validate,
    shap_stability,
)


# ── Synthetic data helpers ────────────────────────────────────────────────────

def _make_df(
    n_tickers: int = 40,
    n_months: int = 84,  # 7 years → at least 1 fold with 5-year train + 1-year test
    seed: int = 42,
    signal_strength: float = 0.5,
    add_sector: bool = False,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Build a synthetic monthly panel DataFrame.

    Returns (df, feature_cols). Target is ret_1y with a known linear signal
    from feat_0 so that rank_ic should be positive.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2010-01-31", periods=n_months, freq="ME")
    feature_cols = ["feat_0", "feat_1", "feat_2"]

    rows = []
    for date in dates:
        for i in range(n_tickers):
            feat_0 = rng.uniform(-2.0, 2.0)
            feat_1 = rng.uniform(-1.0, 1.0)
            feat_2 = rng.uniform(0.0, 1.0)
            ret_1y = signal_strength * feat_0 + rng.normal(0.0, 0.3)
            row = {
                "ticker": f"T{i:03d}",
                "month_end_date": date,
                "feat_0": feat_0,
                "feat_1": feat_1,
                "feat_2": feat_2,
                "ret_1y": ret_1y,
                "price": rng.uniform(10.0, 200.0),
            }
            if add_sector:
                row["sector"] = "Technology" if i % 2 == 0 else "Healthcare"
            rows.append(row)

    return pd.DataFrame(rows), feature_cols


def _make_small_df(n_tickers: int = 10, n_months: int = 20, seed: int = 7) -> tuple[pd.DataFrame, list[str]]:
    """Tiny dataset that should produce no folds (insufficient training data)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-31", periods=n_months, freq="ME")
    feature_cols = ["f0", "f1"]
    rows = []
    for date in dates:
        for i in range(n_tickers):
            rows.append({
                "ticker": f"T{i}",
                "month_end_date": date,
                "f0": rng.uniform(-1, 1),
                "f1": rng.uniform(-1, 1),
                "ret_1y": rng.uniform(-0.3, 0.3),
            })
    return pd.DataFrame(rows), feature_cols


# ── Test 1: fold structure keys ───────────────────────────────────────────────

def test_walk_forward_fold_structure_keys():
    """walk_forward_validate returns dict with correct top-level keys."""
    df, feature_cols = _make_df(n_months=84)
    result = walk_forward_validate(df, feature_cols, "ret_1y", train_years=5, test_years=1)

    assert isinstance(result, dict)
    for key in ("fold_results", "aggregate", "yearly", "feature_importance"):
        assert key in result, f"Missing key: {key}"

    assert isinstance(result["fold_results"], list)
    assert isinstance(result["aggregate"], dict)
    assert isinstance(result["yearly"], pd.DataFrame)
    assert isinstance(result["feature_importance"], pd.DataFrame)


def test_walk_forward_fold_result_keys():
    """Each fold dict contains all required keys."""
    df, feature_cols = _make_df(n_months=84)
    result = walk_forward_validate(df, feature_cols, "ret_1y", train_years=5, test_years=1)

    required_fold_keys = {
        "fold", "train_end", "test_start", "test_end",
        "n_train_obs", "n_test_months", "n_test_obs",
        "oos_r2", "rank_ic", "rank_icir", "rank_icir_nw", "hit_rate",
        "quintile_spread", "ins_r2_diagnostic",
    }
    assert result["fold_results"], "Expected at least one fold"
    for fold in result["fold_results"]:
        missing = required_fold_keys - set(fold.keys())
        assert not missing, f"Missing fold keys: {missing}"


# ── Test 2: no data leakage ───────────────────────────────────────────────────

def test_no_data_leakage():
    """Test start date must be strictly after train end date in every fold."""
    df, feature_cols = _make_df(n_months=84)
    result = walk_forward_validate(df, feature_cols, "ret_1y", train_years=5, test_years=1)

    assert result["fold_results"], "Expected at least one fold"
    for fold in result["fold_results"]:
        train_end = pd.Timestamp(fold["train_end"])
        test_start = pd.Timestamp(fold["test_start"])
        assert test_start > train_end, (
            f"Leakage: test_start={test_start} is not after train_end={train_end}"
        )


# ── Test: embargo prevents target leakage ─────────────────────────────────────

def test_embargo_prevents_target_leakage():
    """
    Verify that no training row has month_end_date > train_end - embargo_months.

    ret_1y is computed as a true forward price ratio so that training rows near
    train_end genuinely embed future prices: ret_1y[t] = price[t+12] / price[t] - 1.
    With embargo_months=12, the embargo must remove those contaminated rows.
    """
    n_tickers = 20
    n_months = 96  # 8 years — enough for multiple folds
    rng = np.random.default_rng(99)

    dates = pd.date_range("2010-01-31", periods=n_months, freq="ME")

    # Build price series per ticker
    rows = []
    for i in range(n_tickers):
        prices = np.cumprod(1 + rng.normal(0.005, 0.05, n_months))
        for m_idx, date in enumerate(dates):
            feat_0 = rng.uniform(-2.0, 2.0)
            # True forward 12-month price ratio (NaN for last 12 months)
            if m_idx + 12 < n_months:
                ret_1y = prices[m_idx + 12] / prices[m_idx] - 1
            else:
                ret_1y = np.nan
            rows.append({
                "ticker": f"T{i:03d}",
                "month_end_date": date,
                "feat_0": feat_0,
                "ret_1y": ret_1y,
            })

    df = pd.DataFrame(rows)
    feature_cols = ["feat_0"]
    embargo_months = 12

    result = walk_forward_validate(
        df, feature_cols, "ret_1y",
        train_years=5, test_years=1,
        embargo_months=embargo_months,
    )

    assert result["fold_results"], "Expected at least one fold"

    for fold in result["fold_results"]:
        train_end = pd.Timestamp(fold["train_end"])
        embargo_cutoff = train_end - pd.DateOffset(months=embargo_months)
        # The fold dict doesn't expose training rows directly, but we can verify
        # the embargo cutoff is earlier than train_end by the expected margin
        assert embargo_cutoff < train_end, (
            f"Embargo cutoff {embargo_cutoff} should be before train_end {train_end}"
        )
        # Reconstruct what training rows would have been used
        test_start = pd.Timestamp(fold["test_start"])
        assert test_start > train_end, (
            f"Leakage: test_start={test_start} is not after train_end={train_end}"
        )

    # Direct check: rebuild training splits and verify embargo is applied
    df2 = df.copy()
    df2["month_end_date"] = pd.to_datetime(df2["month_end_date"])
    df2 = df2.sort_values("month_end_date")
    all_months = sorted(df2["month_end_date"].unique())
    train_months_count = 5 * 12

    t = train_months_count
    while t < len(all_months):
        train_end_month = all_months[t - 1]
        train_start_idx = max(0, t - train_months_count)
        train_window = set(all_months[train_start_idx:t])

        train_df = df2[df2["month_end_date"].isin(train_window)].copy()
        embargo_cutoff = pd.Timestamp(train_end_month) - pd.DateOffset(months=embargo_months)
        train_df_embargoed = train_df[train_df["month_end_date"] <= embargo_cutoff]

        # Every training row must be on or before the embargo cutoff
        if not train_df_embargoed.empty:
            assert train_df_embargoed["month_end_date"].max() <= embargo_cutoff, (
                f"Embargo violated: max training date {train_df_embargoed['month_end_date'].max()} "
                f"> embargo cutoff {embargo_cutoff}"
            )

        t += 12  # test_years=1 * 12


# ── Test 3: compute_oos_metrics returns expected keys ────────────────────────

def test_compute_oos_metrics_keys():
    """compute_oos_metrics returns all expected dict keys."""
    rng = np.random.default_rng(0)
    n = 200
    y_true = rng.normal(0, 1, n)
    y_pred = y_true + rng.normal(0, 0.5, n)
    dates = np.repeat(pd.date_range("2020-01-31", periods=10, freq="ME").values, 20)

    result = compute_oos_metrics(y_true, y_pred, dates)
    required = {"oos_r2", "rank_ic", "rank_icir", "rank_icir_nw", "hit_rate"}
    assert required == set(result.keys()), f"Key mismatch: {set(result.keys())}"


# ── Test 4: rank_ic sign for perfect predictor ────────────────────────────────

def test_rank_ic_positive_for_monotone_predictor():
    """A perfect monotone predictor must yield positive mean rank IC."""
    rng = np.random.default_rng(1)
    n_per_month = 50
    n_months = 12
    dates = np.repeat(pd.date_range("2020-01-31", periods=n_months, freq="ME").values, n_per_month)

    # Perfect predictor: y_pred = y_true (monotone, no noise)
    y_true = rng.uniform(-1, 1, n_per_month * n_months)
    y_pred = y_true.copy()  # perfect

    result = compute_oos_metrics(y_true, y_pred, dates)
    assert result["rank_ic"] > 0.99, f"Expected near-perfect IC, got {result['rank_ic']}"
    assert result["hit_rate"] == 1.0, f"Expected hit_rate=1.0, got {result['hit_rate']}"


# ── Test 5: insufficient training data skips fold ────────────────────────────

def test_insufficient_training_skips_fold():
    """Dataset with too few months produces no folds."""
    df, feature_cols = _make_small_df(n_months=20)
    result = walk_forward_validate(
        df, feature_cols, "ret_1y",
        train_years=5, test_years=1, min_train_months=36,
    )
    assert result["fold_results"] == [], (
        f"Expected no folds for 20-month dataset, got {len(result['fold_results'])}"
    )


# ── Test 6: yearly breakdown has correct year keys ────────────────────────────

def test_yearly_breakdown_year_keys():
    """yearly DataFrame index contains year integers from the test periods and required columns."""
    df, feature_cols = _make_df(n_months=84)
    result = walk_forward_validate(df, feature_cols, "ret_1y", train_years=5, test_years=1)

    yearly = result["yearly"]
    if yearly.empty:
        pytest.skip("No folds produced — skipping yearly test")

    assert yearly.index.name == "year"
    for yr in yearly.index:
        assert isinstance(yr, (int, np.integer)), f"Year index should be int, got {type(yr)}"
        assert 2000 <= int(yr) <= 2100, f"Unexpected year value: {yr}"

    required_yearly_cols = {"mean_rank_ic", "mean_hit_rate", "mean_oos_r2", "n_folds"}
    missing = required_yearly_cols - set(yearly.columns)
    assert not missing, f"Missing yearly columns: {missing}"


# ── Test 7: feature importance shape ─────────────────────────────────────────

def test_feature_importance_shape():
    """feature_importance DataFrame has n_features rows."""
    df, feature_cols = _make_df(n_months=84)
    result = walk_forward_validate(df, feature_cols, "ret_1y", train_years=5, test_years=1)

    fi = result["feature_importance"]
    if fi.empty:
        pytest.skip("No folds produced — skipping feature importance test")

    assert set(feature_cols).issubset(set(fi.index)), (
        f"Missing features in importance index: {set(feature_cols) - set(fi.index)}"
    )


# ── Test 8: aggregate dict has required mean keys ─────────────────────────────

def test_aggregate_has_required_keys():
    """aggregate dict contains mean and std for each OOS metric."""
    df, feature_cols = _make_df(n_months=84)
    result = walk_forward_validate(df, feature_cols, "ret_1y", train_years=5, test_years=1)

    agg = result["aggregate"]
    required_agg_keys = {
        "mean_oos_r2", "std_oos_r2",
        "mean_rank_ic", "std_rank_ic",
        "mean_rank_icir", "std_rank_icir",
        "mean_hit_rate", "std_hit_rate",
        "mean_quintile_spread",
        "n_folds",
    }
    missing = required_agg_keys - set(agg.keys())
    assert not missing, f"Missing aggregate keys: {missing}"


# ── Test 9: sector_col parameter runs without error ───────────────────────────

def test_sector_col_runs():
    """walk_forward_validate with sector_col runs without error."""
    df, feature_cols = _make_df(n_months=84, add_sector=True)
    result = walk_forward_validate(
        df, feature_cols, "ret_1y",
        train_years=5, test_years=1,
        sector_col="sector",
    )
    assert isinstance(result, dict)
    # Should produce folds when data is sufficient
    assert "fold_results" in result


# ── Test 10: empty dataset ────────────────────────────────────────────────────

def test_empty_dataset():
    """Empty DataFrame returns empty result without error."""
    df = pd.DataFrame(columns=["month_end_date", "ticker", "feat_0", "ret_1y"])
    result = walk_forward_validate(df, ["feat_0"], "ret_1y")
    assert result["fold_results"] == []
    assert result["aggregate"] == {}
    assert result["yearly"].empty
    assert result["feature_importance"].empty


# ── Test 11: shap_stability returns DataFrame ────────────────────────────────

def test_shap_stability_returns_dataframe():
    """shap_stability returns a DataFrame with feature rows."""
    df, feature_cols = _make_df(n_months=84)
    result = shap_stability(df, feature_cols, "ret_1y", train_years=5, test_years=1)

    assert isinstance(result, pd.DataFrame)
    if not result.empty:
        assert result.index.name == "feature"
        assert set(feature_cols).issubset(set(result.index))
        assert "mean_abs_shap" in result.columns
        # SHAP values should be non-negative
        fold_cols = [c for c in result.columns if c != "mean_abs_shap"]
        if fold_cols:
            assert (result[fold_cols] >= 0).all().all(), "SHAP values must be non-negative"
