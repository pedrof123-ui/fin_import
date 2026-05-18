"""
Rank-based single-factor and composite-factor baseline models.

These baselines are designed to be compared against the XGBoost walk-forward
model to assess how much value the ML model adds over simple factor rules.

All functions take pre-loaded DataFrames and never make database connections.

Public API
----------
BASELINE_FACTORS        Dict of factor definitions with expected sign.
compute_factor_ic()     Cross-sectional Spearman IC by month.
ic_summary()            IC mean, std, ICIR, Newey-West ICIR, hit rate, t-stat.
quintile_returns()      Mean return by quintile per month.
composite_score()       Cross-sectional z-score composite.
run_all_baselines()     Run all factors and composites; return summary table.
compute_forward_returns()  Forward return computation matching notebook Cell 3.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import stats


# ── Factor definitions ────────────────────────────────────────────────────────

# (column_in_monthly_pe, lower_is_better)
BASELINE_FACTORS: dict[str, tuple[str, bool]] = {
    "low_ps":              ("ps_ratio",        True),
    "high_fcf_yield":      ("fcf_yield",       False),
    "high_div_yield":      ("dividend_yield",  False),
    "low_evebitda":        ("ev_ebitda",       True),
    "low_pe":              ("pe_ratio",        True),
    "high_earnings_yield": ("earnings_yield",  False),
}

# Composite groupings
_VALUE_COLS = ["ps_ratio", "fcf_yield", "ev_ebitda", "earnings_yield"]
_VALUE_SIGN = {"ps_ratio": True, "fcf_yield": False, "ev_ebitda": True, "earnings_yield": False}

_QUALITY_COLS = ["roic", "roa", "operating_margin_slope_5y", "earnings_quality"]
# lower_is_better=False for quality factors: higher roic/roa/margin slope/earnings_quality = better
_QUALITY_SIGN = {"roic": False, "roa": False, "operating_margin_slope_5y": False, "earnings_quality": False}

_MOMENTUM_COL = "momentum_12_1"


# ── Forward return computation (mirrors notebook Cell 3) ──────────────────────

def compute_forward_returns(
    df: pd.DataFrame,
    horizons: dict[str, int],
    tolerance_days: int = 45,
) -> pd.DataFrame:
    """
    Add forward return columns to df using a vectorized merge approach.

    For each horizon (name -> months ahead), find the closest future price
    within tolerance_days of the target date and compute:
        ret_N = future_price / price - 1

    Parameters
    ----------
    df : pd.DataFrame
        Must contain 'ticker', 'month_end_date', 'price'.
    horizons : dict[str, int]
        Mapping from column name to months ahead, e.g. {'ret_1y': 12}.
    tolerance_days : int
        Maximum calendar-day difference allowed between target date and
        nearest available price. Default 45.

    Returns
    -------
    pd.DataFrame
        Copy of df with one new column per horizon. NaN where no future
        price is found within tolerance.
    """
    df = df.sort_values(["ticker", "month_end_date"]).reset_index(drop=True).copy()

    for col, months in horizons.items():
        df["_target"] = df["month_end_date"] + pd.DateOffset(months=months)

        left = df[["ticker", "month_end_date", "price", "_target"]].copy()
        right = (
            df[["ticker", "month_end_date", "price"]]
            .rename(columns={"month_end_date": "future_date", "price": "future_price"})
        )

        merged = left.merge(right, on="ticker", how="left")
        merged["day_diff"] = (merged["future_date"] - merged["_target"]).abs().dt.days
        merged = merged[merged["day_diff"] <= tolerance_days]

        merged = (
            merged.sort_values("day_diff")
            .groupby(["ticker", "month_end_date"], sort=False)
            .first()
            .reset_index()[["ticker", "month_end_date", "future_price"]]
        )

        df = df.merge(merged, on=["ticker", "month_end_date"], how="left")
        df[col] = df["future_price"] / df["price"] - 1
        df = df.drop(columns=["future_price", "_target"])

    return df


# ── IC computation ────────────────────────────────────────────────────────────

def compute_factor_ic(
    df: pd.DataFrame,
    factor_col: str,
    return_col: str,
    lower_is_better: bool = False,
    min_stocks: int = 20,
) -> pd.Series:
    """
    For each month in df, compute Spearman rank IC between factor_col and return_col.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain 'month_end_date', factor_col, return_col.
    factor_col : str
        Name of the factor column.
    return_col : str
        Name of the forward return column.
    lower_is_better : bool
        If True, invert the factor sign so that IC is positive when the
        factor predicts returns correctly. Default False.
    min_stocks : int
        Months with fewer than this many valid observations produce NaN.
        Default 20.

    Returns
    -------
    pd.Series
        Spearman IC values indexed by month_end_date. NaN for months with
        insufficient data.
    """
    sign = -1.0 if lower_is_better else 1.0

    results: dict = {}
    for date, grp in df.groupby("month_end_date"):
        valid = grp[[factor_col, return_col]].dropna()
        if len(valid) < min_stocks:
            results[date] = np.nan
            continue
        factor_vals = sign * valid[factor_col].values
        ret_vals = valid[return_col].values
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ic, _ = stats.spearmanr(factor_vals, ret_vals)
        results[date] = float(ic) if np.isfinite(ic) else np.nan

    return pd.Series(results, name=factor_col).sort_index()


# ── IC summary statistics ─────────────────────────────────────────────────────

def ic_summary(ic_series: pd.Series, nw_lags: int = 11) -> dict:
    """
    Compute IC summary statistics for a monthly IC series.

    Parameters
    ----------
    ic_series : pd.Series
        Monthly IC values (NaN months excluded from calculations).
    nw_lags : int
        Number of lags for Newey-West HAC standard error adjustment.
        Default 11 (appropriate for 12-month forward returns).

    Returns
    -------
    dict with keys:
        mean_ic, std_ic, icir, icir_nw, hit_rate, t_stat, n_months
    """
    clean = ic_series.dropna()
    n = len(clean)
    if n == 0:
        return {
            "mean_ic": np.nan, "std_ic": np.nan, "icir": np.nan,
            "icir_nw": np.nan, "hit_rate": np.nan, "t_stat": np.nan,
            "n_months": 0,
        }

    mean_ic = float(clean.mean())
    std_ic = float(clean.std(ddof=1)) if n > 1 else 0.0
    icir = mean_ic / std_ic if std_ic > 0 else np.nan
    hit_rate = float((clean > 0).mean())
    t_stat = float(stats.ttest_1samp(clean, 0.0).statistic) if n > 1 else np.nan

    # Newey-West adjusted ICIR
    icir_nw = _newey_west_icir(clean.values, lags=min(nw_lags, n - 1))

    return {
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "icir": icir,
        "icir_nw": icir_nw,
        "hit_rate": hit_rate,
        "t_stat": t_stat,
        "n_months": n,
    }


def _newey_west_icir(ic_arr: np.ndarray, lags: int) -> float:
    """Newey-West HAC ICIR: mean / NW_std_error."""
    n = len(ic_arr)
    if n <= 1 or lags < 1:
        return float(np.mean(ic_arr) / np.std(ic_arr, ddof=1)) if n > 1 else np.nan

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


# ── Quintile return analysis ──────────────────────────────────────────────────

def quintile_returns(
    df: pd.DataFrame,
    factor_col: str,
    return_col: str,
    lower_is_better: bool = False,
    n_bins: int = 5,
    min_stocks: int = 20,
) -> pd.DataFrame:
    """
    For each month, rank stocks into n_bins by factor_col and compute mean return.

    Q1 = best bucket (lowest value if lower_is_better, else highest).
    Q5 = worst bucket.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain 'month_end_date', factor_col, return_col.
    factor_col : str
        Factor column to rank on.
    return_col : str
        Forward return column.
    lower_is_better : bool
        If True, rank ascending so lowest factor value = Q1 (best).
        If False, rank descending so highest factor value = Q1 (best).
    n_bins : int
        Number of buckets. Default 5 (quintiles).
    min_stocks : int
        Months with fewer valid observations are excluded.

    Returns
    -------
    pd.DataFrame
        Index = month_end_date. Columns Q1..Qn + 'spread' (Q1 - Qn).
    """
    bin_cols = [f"Q{i}" for i in range(1, n_bins + 1)]
    rows = {}

    for date, grp in df.groupby("month_end_date"):
        valid = grp[[factor_col, return_col]].dropna()
        if len(valid) < min_stocks:
            continue

        # Rank factor: ascending if lower_is_better (low = Q1 = best)
        factor_rank = valid[factor_col].rank(
            ascending=lower_is_better, method="average", na_option="keep"
        )
        # Flip so that Q1 = best in both cases
        # When lower_is_better=True: ascending rank → low factor = rank 1 = Q1 (best). Correct.
        # When lower_is_better=False: descending rank → high factor = rank 1 = Q1 (best). Correct.
        labels = pd.qcut(factor_rank, q=n_bins, labels=bin_cols, duplicates="drop")
        row_data = {}
        for b in bin_cols:
            mask = labels == b
            row_data[b] = float(valid.loc[mask, return_col].mean()) if mask.any() else np.nan
        rows[date] = row_data

    if not rows:
        empty = pd.DataFrame(columns=bin_cols + ["spread"])
        empty.index.name = "month_end_date"
        return empty

    result = pd.DataFrame(rows).T
    result.index.name = "month_end_date"
    # Ensure all Q columns exist even if some months had no data
    for col in bin_cols:
        if col not in result.columns:
            result[col] = np.nan
    result = result[bin_cols]
    result["spread"] = result["Q1"] - result[f"Q{n_bins}"]
    return result.sort_index()


# ── Composite factor score ────────────────────────────────────────────────────

def composite_score(
    df: pd.DataFrame,
    factor_cols: list[str],
    lower_is_better_map: dict[str, bool],
    group_col: str = "month_end_date",
) -> pd.Series:
    """
    Cross-sectional z-score composite.

    For each month, z-score each factor, flip sign for lower_is_better
    factors (so that higher z-score always means "better"), then average
    across factors. NaN factor values contribute 0 to the composite.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain group_col and all columns in factor_cols.
    factor_cols : list[str]
        List of factor columns to include.
    lower_is_better_map : dict[str, bool]
        Maps factor column name -> whether lower value is better.
    group_col : str
        Column to group by for cross-sectional normalization. Default
        'month_end_date'.

    Returns
    -------
    pd.Series
        Composite scores indexed like df. Higher is always better.
    """
    def _xsec_zscore(x: pd.Series) -> pd.Series:
        mu = x.mean()
        sd = x.std(ddof=1)
        if sd == 0 or pd.isna(sd):
            return pd.Series(0.0, index=x.index)
        return (x - mu) / sd

    present_cols = [c for c in factor_cols if c in df.columns]
    scores = pd.Series(0.0, index=df.index)
    counts = pd.Series(0.0, index=df.index)

    for col in present_cols:
        sign = -1.0 if lower_is_better_map.get(col, False) else 1.0
        zscored = df.groupby(group_col)[col].transform(_xsec_zscore)
        # NaN values contribute 0 to the composite score
        zscored = zscored.fillna(0.0)
        scores += sign * zscored
        # Track how many non-NaN factors contributed per row
        counts += df[col].notna().astype(float)

    # Divide by number of contributing factors per row to keep scale consistent
    safe_counts = counts.replace(0.0, np.nan)
    scores = scores / safe_counts
    scores = scores.fillna(0.0)
    return scores


# ── Run all baselines ─────────────────────────────────────────────────────────

def run_all_baselines(
    df: pd.DataFrame,
    return_col: str = "ret_1y",
    min_stocks: int = 20,
) -> pd.DataFrame:
    """
    Run IC analysis for all BASELINE_FACTORS plus composite factors.

    Composites:
      value_composite : low_ps, high_fcf_yield, low_evebitda, high_earnings_yield
      value_quality   : value_composite + roic, roa, operating_margin_slope_5y
      value_momentum  : value_composite + momentum_12_1 (skipped if column absent)

    Parameters
    ----------
    df : pd.DataFrame
        Monthly universe DataFrame with factor columns and return_col.
    return_col : str
        Forward return column name. Default 'ret_1y'.
    min_stocks : int
        Minimum stocks per month for IC computation. Default 20.

    Returns
    -------
    pd.DataFrame
        One row per factor/composite with columns:
        factor, mean_ic, icir, icir_nw, hit_rate, t_stat, n_months,
        q1_mean_ret, q5_mean_ret, spread
    """
    nw_lags = 11  # appropriate for 12-month returns; caller can adjust via ic_summary directly

    rows = []

    # ── Single factors ────────────────────────────────────────────────────────
    for factor_name, (col, lower_is_better) in BASELINE_FACTORS.items():
        if col not in df.columns:
            continue
        ic = compute_factor_ic(df, col, return_col, lower_is_better=lower_is_better, min_stocks=min_stocks)
        summary = ic_summary(ic, nw_lags=nw_lags)
        qt = quintile_returns(df, col, return_col, lower_is_better=lower_is_better, min_stocks=min_stocks)
        rows.append({
            "factor": factor_name,
            **summary,
            "q1_mean_ret": float(qt["Q1"].mean()) if not qt.empty else np.nan,
            "q5_mean_ret": float(qt["Q5"].mean()) if not qt.empty else np.nan,
            "spread": float(qt["spread"].mean()) if not qt.empty else np.nan,
        })

    # ── Composite factors ─────────────────────────────────────────────────────
    composites = _build_composites(df)

    for comp_name, (comp_scores, lib) in composites.items():
        temp = df.copy()
        temp["_comp"] = comp_scores
        ic = compute_factor_ic(temp, "_comp", return_col, lower_is_better=False, min_stocks=min_stocks)
        summary = ic_summary(ic, nw_lags=nw_lags)
        qt = quintile_returns(temp, "_comp", return_col, lower_is_better=False, min_stocks=min_stocks)
        rows.append({
            "factor": comp_name,
            **summary,
            "q1_mean_ret": float(qt["Q1"].mean()) if not qt.empty else np.nan,
            "q5_mean_ret": float(qt["Q5"].mean()) if not qt.empty else np.nan,
            "spread": float(qt["spread"].mean()) if not qt.empty else np.nan,
        })

    result = pd.DataFrame(rows, columns=[
        "factor", "mean_ic", "std_ic", "icir", "icir_nw", "hit_rate", "t_stat", "n_months",
        "q1_mean_ret", "q5_mean_ret", "spread",
    ])
    return result


def _build_composites(df: pd.DataFrame) -> dict[str, tuple[pd.Series, dict]]:
    """Build composite score series from df. Returns dict of name -> (scores, lib)."""
    value_cols = [c for c in _VALUE_COLS if c in df.columns]
    value_sign = {c: _VALUE_SIGN[c] for c in value_cols}

    value_scores = composite_score(df, value_cols, value_sign)

    quality_cols = [c for c in _QUALITY_COLS if c in df.columns]
    quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}

    composites: dict[str, tuple[pd.Series, dict]] = {}

    if value_cols:
        composites["value_composite"] = (value_scores, {})

    if value_cols and quality_cols:
        vq_cols = value_cols + quality_cols
        vq_sign = {**value_sign, **quality_sign}
        composites["value_quality"] = (composite_score(df, vq_cols, vq_sign), {})

    if value_cols and _MOMENTUM_COL in df.columns:
        vm_cols = value_cols + [_MOMENTUM_COL]
        vm_sign = {**value_sign, _MOMENTUM_COL: False}
        composites["value_momentum"] = (composite_score(df, vm_cols, vm_sign), {})

    return composites
