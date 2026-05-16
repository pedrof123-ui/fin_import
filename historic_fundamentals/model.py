"""
Walk-forward model validation for the fundamentals-alpha stock-selection model.

Public API
----------
walk_forward_validate()   Time-based walk-forward XGBoost validation.
compute_oos_metrics()     OOS R², rank IC, ICIR, NW-ICIR, hit rate.
shap_stability()          SHAP feature importance across folds.

Design notes
------------
- Train/test splits are purely temporal. No shuffle. No random seeds in splits.
- Sector-relative z-scores (if sector_col is provided) are computed on the
  training set only per fold, then applied to the test set using training
  medians/stds. This prevents look-ahead bias from computing cross-sectional
  statistics on the full dataset before the loop.
- Newey-West ICIR uses lag=11 (appropriate for 12-month forward returns where
  returns overlap across 11 months when evaluated monthly).
- In-sample metrics are clearly separated from OOS metrics.
- embargo_months (default 12) ensures training labels do not embed prices from
  the test period. Training rows whose month_end_date is within embargo_months
  of train_end_month are dropped before fitting.
"""

from __future__ import annotations

import warnings
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats
from xgboost import XGBRegressor


# ── Default model params ──────────────────────────────────────────────────────

DEFAULT_MODEL_PARAMS: dict = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 20,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_jobs": -1,
    "verbosity": 0,
}


# ── Newey-West ICIR (reused logic from baselines.py) ─────────────────────────

def _newey_west_icir(ic_arr: np.ndarray, lags: int) -> float:
    """Newey-West HAC ICIR: mean / NW_std_error."""
    n = len(ic_arr)
    if n <= 1:
        return np.nan
    if lags < 1:
        std = np.std(ic_arr, ddof=1)
        return float(np.mean(ic_arr) / std) if std > 0 else np.nan

    try:
        import statsmodels.api as sm
        x = np.ones((n, 1))
        model = sm.OLS(ic_arr, x).fit(
            cov_type="HAC", cov_kwds={"maxlags": lags, "use_correction": True}
        )
        se = float(model.bse[0])
        return float(model.params[0] / se) if se > 0 else np.nan
    except Exception:
        # Fallback: manual Newey-West variance
        mu = np.mean(ic_arr)
        demeaned = ic_arr - mu
        gamma0 = np.dot(demeaned, demeaned) / n
        nw_var = gamma0
        for lag in range(1, lags + 1):
            gamma_l = np.dot(demeaned[lag:], demeaned[:-lag]) / n
            weight = 1.0 - lag / (lags + 1.0)
            nw_var += 2.0 * weight * gamma_l
        nw_var = max(nw_var, 1e-16)
        nw_se = np.sqrt(nw_var / n)
        return float(mu / nw_se) if nw_se > 0 else np.nan


# ── OOS metrics ───────────────────────────────────────────────────────────────

def compute_oos_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    dates: np.ndarray,
    nw_lags: int = 11,
) -> dict:
    """
    Compute out-of-sample metrics for a set of predictions.

    Cross-sectional Spearman IC is computed per month (unique value in dates),
    then aggregated. This is the standard quant-finance IC definition.

    Parameters
    ----------
    y_true : np.ndarray
        Actual forward returns.
    y_pred : np.ndarray
        Model predictions (scores).
    dates : np.ndarray
        Month-end dates (one per observation), used to group into cross-sections.
    nw_lags : int
        Newey-West lags for ICIR. Default 11 (12-month returns).

    Returns
    -------
    dict with keys:
        oos_r2, rank_ic, rank_icir, rank_icir_nw, hit_rate
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    dates = np.asarray(dates)

    # OOS R² (global, not cross-sectional)
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if mask.sum() < 2:
        return {
            "oos_r2": np.nan,
            "rank_ic": np.nan,
            "rank_icir": np.nan,
            "rank_icir_nw": np.nan,
            "hit_rate": np.nan,
        }

    ss_res = np.sum((y_true[mask] - y_pred[mask]) ** 2)
    ss_tot = np.sum((y_true[mask] - y_true[mask].mean()) ** 2)
    oos_r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else np.nan

    # Cross-sectional Spearman IC per month
    unique_dates = np.unique(dates[mask])
    monthly_ics = []
    for d in unique_dates:
        idx = (dates == d) & mask
        if idx.sum() < 5:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ic, _ = stats.spearmanr(y_pred[idx], y_true[idx])
        if np.isfinite(ic):
            monthly_ics.append(float(ic))

    if not monthly_ics:
        return {
            "oos_r2": oos_r2,
            "rank_ic": np.nan,
            "rank_icir": np.nan,
            "rank_icir_nw": np.nan,
            "hit_rate": np.nan,
        }

    ic_arr = np.array(monthly_ics)
    mean_ic = float(np.mean(ic_arr))
    std_ic = float(np.std(ic_arr, ddof=1)) if len(ic_arr) > 1 else 0.0
    rank_icir = mean_ic / std_ic if std_ic > 0 else np.nan
    rank_icir_nw = _newey_west_icir(ic_arr, lags=min(nw_lags, len(ic_arr) - 1))
    hit_rate = float(np.mean(ic_arr > 0))

    return {
        "oos_r2": oos_r2,
        "rank_ic": mean_ic,
        "rank_icir": rank_icir,
        "rank_icir_nw": rank_icir_nw,
        "hit_rate": hit_rate,
    }


# ── Quintile spread ───────────────────────────────────────────────────────────

def _quintile_spread(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    dates: np.ndarray,
    n_bins: int = 5,
) -> float:
    """
    Compute mean quintile spread across months.

    Stocks are ranked by y_pred into n_bins per month. Spread = Q5 mean return
    minus Q1 mean return (Q5 = highest predicted score, Q1 = lowest).
    """
    df = pd.DataFrame({"date": dates, "y_true": y_true, "y_pred": y_pred})
    q_spreads = []
    for _, grp in df.groupby("date"):
        if len(grp) < n_bins * 2:
            continue
        grp = grp.copy()
        grp["q"] = pd.qcut(grp["y_pred"], n_bins, labels=False, duplicates="drop")
        qmeans = grp.groupby("q")["y_true"].mean()
        if qmeans.index.min() == 0 and qmeans.index.max() == n_bins - 1:
            q_spreads.append(qmeans.iloc[-1] - qmeans.iloc[0])
    return float(np.mean(q_spreads)) if q_spreads else np.nan


# ── Sector-relative z-score (fold-safe) ──────────────────────────────────────

def _apply_sector_zscore(
    train: pd.DataFrame,
    test: pd.DataFrame,
    feature_cols: list[str],
    sector_col: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compute sector-relative z-scores on train, then apply to test.

    Training sector medians and stds are computed from train only — test
    sector statistics are never used. This avoids look-ahead bias that
    arises from computing cross-sectional normalizations on the full dataset.

    For each feature, within each sector, subtract the training sector median
    and divide by the training sector std. Tickers in sectors not seen during
    training fall back to the global training median/std for that feature.
    """
    train = train.copy()
    test = test.copy()

    for col in feature_cols:
        if col not in train.columns:
            continue

        # Compute sector stats from training data only
        sector_stats = (
            train.groupby(sector_col)[col]
            .agg(["median", "std"])
            .rename(columns={"median": "sec_med", "std": "sec_std"})
        )

        # Global fallback from training data
        global_med = float(train[col].median())
        global_std = float(train[col].std(ddof=1))
        if global_std == 0 or np.isnan(global_std):
            global_std = 1.0

        def _zscore(row_col: pd.Series, sec: pd.Series) -> pd.Series:
            result = row_col.copy()
            for sector, grp_idx in sec.groupby(sec).groups.items():
                if sector in sector_stats.index:
                    med = sector_stats.loc[sector, "sec_med"]
                    std = sector_stats.loc[sector, "sec_std"]
                else:
                    med = global_med
                    std = global_std
                if std == 0 or np.isnan(std):
                    std = global_std
                result.loc[grp_idx] = (row_col.loc[grp_idx] - med) / std
            return result

        train[col] = _zscore(train[col], train[sector_col])
        test[col] = _zscore(test[col], test[sector_col])

    return train, test


# ── Walk-forward validation ───────────────────────────────────────────────────

def walk_forward_validate(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    train_years: int = 5,
    test_years: int = 1,
    min_train_months: int = 36,
    model_params: Optional[dict] = None,
    sector_col: Optional[str] = None,
    embargo_months: int = 12,
) -> dict:
    """
    Time-based walk-forward XGBoost validation.

    Each fold:
      - Train on [fold_start : train_end - embargo_months)
      - Test  on [train_end  : test_end)

    The embargo ensures that training labels (forward returns) do not embed
    prices from inside the test window. With ret_1y targets, the last 12
    months of the training window have forward return periods that extend into
    the test period, so those rows are dropped before fitting.

    No data from the test period leaks into training. No random splits.
    In-sample metrics are computed but clearly labelled as diagnostic only.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain 'month_end_date', 'ticker', feature_cols, target_col.
    feature_cols : list[str]
        Feature column names.
    target_col : str
        Target return column (primary: 'ret_1y').
    train_years : int
        Years of history to use for each training window. Default 5.
    test_years : int
        Years per test fold. Default 1.
    min_train_months : int
        Minimum months required to train. Folds with fewer are skipped.
    model_params : dict or None
        XGBoost parameters. Falls back to DEFAULT_MODEL_PARAMS.
    sector_col : str or None
        If provided, sector-relative z-scores are computed on train and
        applied to test using training sector statistics only. This prevents
        the look-ahead bias present when sector normalization is computed on
        the full dataset before the loop.
    embargo_months : int
        Number of months to exclude from the end of the training window to
        prevent forward-return target leakage into the test period. Default 12
        (appropriate for ret_1y targets).

    Returns
    -------
    dict with keys:
        fold_results  : list of per-fold dicts
        aggregate     : aggregate stats across all folds
        yearly        : DataFrame indexed by year with mean rank_IC, mean hit_rate,
                        mean oos_r2 per year
        feature_importance : DataFrame of mean feature importance across folds
                             (shape: n_features rows, folds as columns)
    """
    params = {**DEFAULT_MODEL_PARAMS, **(model_params or {})}

    df = df.copy()
    df["month_end_date"] = pd.to_datetime(df["month_end_date"])
    df = df.sort_values("month_end_date").reset_index(drop=True)

    all_months = sorted(df["month_end_date"].unique())
    if not all_months:
        return {"fold_results": [], "aggregate": {}, "yearly": pd.DataFrame(), "feature_importance": pd.DataFrame()}

    train_months = train_years * 12
    test_months = test_years * 12

    fold_results = []
    importance_records = {}  # fold_label -> Series of feature importances

    # Walk through time: advance by test_months each step
    fold_idx = 0
    t = train_months  # index into all_months where test starts

    while t < len(all_months):
        train_end_month = all_months[t - 1]         # last training month
        test_start_month = all_months[t]             # first test month

        # Training window: at most train_months before test start
        train_start_idx = max(0, t - train_months)
        train_window = all_months[train_start_idx:t]

        if len(train_window) < min_train_months:
            t += test_months
            continue

        # Test window
        test_end_idx = min(t + test_months, len(all_months))
        test_window = all_months[t:test_end_idx]

        if not test_window:
            break

        test_end_month = test_window[-1]

        # Split data — strict temporal: train months strictly before test start
        train_mask = df["month_end_date"].isin(set(train_window))
        test_mask = df["month_end_date"].isin(set(test_window))

        train_df = df[train_mask].copy()
        test_df = df[test_mask].copy()

        # Embargo: drop training rows whose forward-return target embeds prices
        # from the test period. For ret_1y, any row within 12 months of
        # train_end_month has a return period that extends into the test window.
        if embargo_months > 0:
            embargo_cutoff = pd.Timestamp(train_end_month) - pd.DateOffset(months=embargo_months)
            train_df = train_df[train_df["month_end_date"] <= embargo_cutoff].copy()

        # Drop rows missing target
        train_df = train_df[train_df[target_col].notna()].copy()
        test_df = test_df[test_df[target_col].notna()].copy()

        if len(train_df) < min_train_months or len(test_df) == 0:
            t += test_months
            continue

        # Sector-relative z-score (fold-safe: training stats only)
        if sector_col and sector_col in train_df.columns:
            train_df, test_df = _apply_sector_zscore(train_df, test_df, feature_cols, sector_col)

        # Prepare arrays
        present_features = [c for c in feature_cols if c in train_df.columns]
        X_train = train_df[present_features].to_numpy(dtype=float, copy=True)
        y_train = train_df[target_col].to_numpy(dtype=float, copy=True)
        X_test = test_df[present_features].to_numpy(dtype=float, copy=True)
        y_test = test_df[target_col].to_numpy(dtype=float, copy=True)
        test_dates = test_df["month_end_date"].to_numpy()

        # Fill NaN with column median from training data (prevent XGBoost NaN issues)
        col_medians = np.nanmedian(X_train, axis=0)
        for j in range(X_train.shape[1]):
            X_train[np.isnan(X_train[:, j]), j] = col_medians[j]
            X_test[np.isnan(X_test[:, j]), j] = col_medians[j]

        # Train
        model = XGBRegressor(**params)
        model.fit(X_train, y_train)

        # OOS predictions
        y_pred_oos = model.predict(X_test)

        # In-sample (diagnostic only — not final evidence)
        y_pred_ins = model.predict(X_train)
        ss_res_ins = np.sum((y_train - y_pred_ins) ** 2)
        ss_tot_ins = np.sum((y_train - y_train.mean()) ** 2)
        ins_r2 = float(1.0 - ss_res_ins / ss_tot_ins) if ss_tot_ins > 0 else np.nan

        # OOS metrics
        oos_metrics = compute_oos_metrics(y_test, y_pred_oos, test_dates)

        # Quintile spread: Q5 mean return - Q1 mean return per month, averaged
        q_spread = _quintile_spread(y_test, y_pred_oos, test_dates)

        fold_label = f"fold_{fold_idx:02d}"
        fold_results.append({
            "fold": fold_label,
            "train_end": str(train_end_month)[:10],
            "test_start": str(test_start_month)[:10],
            "test_end": str(test_end_month)[:10],
            "n_train_obs": len(train_df),
            "n_test_months": len(test_window),
            "n_test_obs": len(test_df),
            # OOS metrics (these are the valid results)
            **oos_metrics,
            "quintile_spread": q_spread,
            # In-sample R² is diagnostic only
            "ins_r2_diagnostic": ins_r2,
        })

        # Feature importance for this fold
        importance_records[fold_label] = pd.Series(
            model.feature_importances_, index=present_features
        )

        fold_idx += 1
        t += test_months

    if not fold_results:
        return {
            "fold_results": fold_results,
            "aggregate": {},
            "yearly": pd.DataFrame(),
            "feature_importance": pd.DataFrame(),
        }

    # Aggregate stats across folds
    metric_keys = ["oos_r2", "rank_ic", "rank_icir", "rank_icir_nw", "hit_rate"]
    aggregate = {}
    for k in metric_keys:
        vals = [f[k] for f in fold_results if f[k] is not None and np.isfinite(f[k])]
        aggregate[f"mean_{k}"] = float(np.mean(vals)) if vals else np.nan
        aggregate[f"std_{k}"] = float(np.std(vals, ddof=1)) if len(vals) > 1 else np.nan

    qs_vals = [f["quintile_spread"] for f in fold_results if f["quintile_spread"] is not None and np.isfinite(f["quintile_spread"])]
    aggregate["mean_quintile_spread"] = float(np.mean(qs_vals)) if qs_vals else np.nan
    aggregate["n_folds"] = len(fold_results)

    # Yearly breakdown: mean rank_IC, mean hit_rate, mean oos_r2 per calendar year
    year_data: dict[int, dict[str, list]] = {}
    for fold in fold_results:
        # Use test_start year to attribute metrics to year
        year = int(fold["test_start"][:4])
        entry = year_data.setdefault(year, {"rank_ic": [], "hit_rate": [], "oos_r2": []})
        for key in ("rank_ic", "hit_rate", "oos_r2"):
            val = fold[key]
            if val is not None and np.isfinite(val):
                entry[key].append(val)

    yearly_rows = {}
    for yr, data in sorted(year_data.items()):
        row: dict = {"n_folds": len(data["rank_ic"]) or len(data["hit_rate"]) or len(data["oos_r2"])}
        row["mean_rank_ic"] = float(np.mean(data["rank_ic"])) if data["rank_ic"] else np.nan
        row["mean_hit_rate"] = float(np.mean(data["hit_rate"])) if data["hit_rate"] else np.nan
        row["mean_oos_r2"] = float(np.mean(data["oos_r2"])) if data["oos_r2"] else np.nan
        yearly_rows[yr] = row
    yearly = pd.DataFrame(yearly_rows).T
    yearly.index.name = "year"

    # Feature importance DataFrame: features as rows, folds as columns
    if importance_records:
        feature_importance = pd.DataFrame(importance_records).fillna(0.0)
        feature_importance["mean_importance"] = feature_importance.mean(axis=1)
        feature_importance = feature_importance.sort_values("mean_importance", ascending=False)
    else:
        feature_importance = pd.DataFrame()

    return {
        "fold_results": fold_results,
        "aggregate": aggregate,
        "yearly": yearly,
        "feature_importance": feature_importance,
    }


# ── SHAP stability ────────────────────────────────────────────────────────────

def shap_stability(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    train_years: int = 5,
    test_years: int = 1,
    model_params: Optional[dict] = None,
    sector_col: Optional[str] = None,
    embargo_months: int = 12,
) -> pd.DataFrame:
    """
    Compute SHAP feature importance stability across walk-forward folds.

    For each fold, SHAP values are computed on the test set. Returns a
    DataFrame of mean |SHAP| per feature per fold.

    Parameters
    ----------
    df : pd.DataFrame
        Same format as walk_forward_validate().
    feature_cols : list[str]
        Feature column names.
    target_col : str
        Target column.
    train_years : int
        Years of training history per fold. Default 5.
    test_years : int
        Years per test fold. Default 1.
    model_params : dict or None
        XGBoost parameters.
    sector_col : str or None
        Sector column for fold-safe sector normalization.
    embargo_months : int
        Number of months to exclude from the end of the training window to
        prevent forward-return target leakage into the test period. Default 12.

    Returns
    -------
    pd.DataFrame
        Index = feature names. Columns = fold labels. Values = mean |SHAP|.
        Also includes a 'mean_abs_shap' column averaged across folds.
    """
    import shap

    params = {**DEFAULT_MODEL_PARAMS, **(model_params or {})}

    df = df.copy()
    df["month_end_date"] = pd.to_datetime(df["month_end_date"])
    df = df.sort_values("month_end_date").reset_index(drop=True)

    all_months = sorted(df["month_end_date"].unique())
    if not all_months:
        return pd.DataFrame()

    train_months = train_years * 12
    test_months = test_years * 12
    min_train_months = 36

    shap_records: dict[str, pd.Series] = {}
    fold_idx = 0
    t = train_months

    while t < len(all_months):
        train_start_idx = max(0, t - train_months)
        train_window = all_months[train_start_idx:t]

        if len(train_window) < min_train_months:
            t += test_months
            continue

        test_end_idx = min(t + test_months, len(all_months))
        test_window = all_months[t:test_end_idx]

        if not test_window:
            break

        train_end_month = all_months[t - 1]

        train_df = df[df["month_end_date"].isin(set(train_window))].copy()
        test_df = df[df["month_end_date"].isin(set(test_window))].copy()

        # Embargo: drop training rows whose forward-return label embeds future prices
        if embargo_months > 0:
            embargo_cutoff = pd.Timestamp(train_end_month) - pd.DateOffset(months=embargo_months)
            train_df = train_df[train_df["month_end_date"] <= embargo_cutoff].copy()

        train_df = train_df[train_df[target_col].notna()].copy()
        test_df = test_df[test_df[target_col].notna()].copy()

        if len(train_df) < min_train_months or len(test_df) == 0:
            t += test_months
            continue

        if sector_col and sector_col in train_df.columns:
            train_df, test_df = _apply_sector_zscore(train_df, test_df, feature_cols, sector_col)

        present_features = [c for c in feature_cols if c in train_df.columns]
        X_train = train_df[present_features].to_numpy(dtype=float, copy=True)
        y_train = train_df[target_col].to_numpy(dtype=float, copy=True)
        X_test = test_df[present_features].to_numpy(dtype=float, copy=True)

        col_medians = np.nanmedian(X_train, axis=0)
        for j in range(X_train.shape[1]):
            X_train[np.isnan(X_train[:, j]), j] = col_medians[j]
            X_test[np.isnan(X_test[:, j]), j] = col_medians[j]

        model = XGBRegressor(**params)
        model.fit(X_train, y_train)

        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_test)
        mean_abs_shap = np.abs(shap_values).mean(axis=0)

        fold_label = f"fold_{fold_idx:02d}"
        shap_records[fold_label] = pd.Series(mean_abs_shap, index=present_features)

        fold_idx += 1
        t += test_months

    if not shap_records:
        return pd.DataFrame()

    result = pd.DataFrame(shap_records).fillna(0.0)
    result["mean_abs_shap"] = result.mean(axis=1)
    result = result.sort_values("mean_abs_shap", ascending=False)
    result.index.name = "feature"
    return result
