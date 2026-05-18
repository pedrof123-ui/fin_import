"""
Risk diagnostics and guardrails for the fundamentals-alpha stock-selection model.

Public API
----------
exposure_report()       Sector, market-cap bucket, and concentration exposures per month.
value_trap_flags()      Flag stocks that are cheap but fundamentally deteriorating.
apply_guardrails()      Detect guardrail violations (diagnostic only — does not modify portfolio).
constrained_holdings()  Apply guardrails to produce an actionable filtered holdings set.
drawdown_analysis()     Detailed drawdown statistics beyond the scalar max_drawdown.
beta_decomposition()    Market beta and rolling beta decomposition.

GUARDRAIL_DEFAULTS      Default guardrail thresholds (all configurable).
VTF_DEFAULTS            Default value-trap-flags thresholds (all configurable).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


GUARDRAIL_DEFAULTS: dict = {
    "max_sector_weight": 0.40,
    "max_position_weight": 0.10,
    "max_debt_to_ebitda": 10.0,
    "min_operating_margin": None,
    "max_value_trap_pct": 0.20,
}

VTF_DEFAULTS: dict = {
    "vtf_max_debt_to_ebitda": 10.0,
    "vtf_min_operating_margin": 0.0,
    "vtf_min_roa": -0.05,
    "vtf_min_earnings_yield": -0.05,
    "vtf_top_quintile_cutoff": 0.80,
}


def exposure_report(
    portfolio_df: pd.DataFrame,
    date_col: str = "month_end_date",
    ticker_col: str = "ticker",
    sector_col: str = "sector",
    industry_col: str = "industry",
    market_cap_col: str = "market_cap",
) -> dict:
    """
    Compute per-month sector, market-cap bucket, and concentration exposures.

    Parameters
    ----------
    portfolio_df : pd.DataFrame
        One row per (date, ticker) in the portfolio. Must have date_col and
        ticker_col. sector_col, industry_col, and market_cap_col are optional.
    date_col, ticker_col, sector_col, industry_col, market_cap_col : str
        Column names.

    Returns
    -------
    dict with keys:
        sector            : DataFrame of per-month sector weights (fraction of portfolio).
        market_cap_bucket : DataFrame of per-month small/mid/large weights.
        concentration     : Series of per-month HHI (equal-weight: 1/n_stocks).
        industry          : DataFrame of per-month industry weights (if industry_col present).
    """
    df = portfolio_df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    result: dict = {}

    # Sector exposure
    if sector_col in df.columns:
        counts = (
            df.groupby([date_col, sector_col])[ticker_col]
            .count()
            .unstack(fill_value=0)
        )
        result["sector"] = counts.div(counts.sum(axis=1), axis=0)
    else:
        result["sector"] = pd.DataFrame()

    # Industry exposure (optional — only add key if column exists)
    if industry_col in df.columns:
        ind_counts = (
            df.groupby([date_col, industry_col])[ticker_col]
            .count()
            .unstack(fill_value=0)
        )
        result["industry"] = ind_counts.div(ind_counts.sum(axis=1), axis=0)

    # Market-cap bucket exposure
    if market_cap_col in df.columns:
        def _bucket(cap: float) -> str:
            if pd.isna(cap):
                return "unknown"
            if cap < 2e9:
                return "small"
            if cap <= 10e9:
                return "mid"
            return "large"

        df["_mcap_bucket"] = df[market_cap_col].map(_bucket)
        mc_counts = (
            df.groupby([date_col, "_mcap_bucket"])[ticker_col]
            .count()
            .unstack(fill_value=0)
        )
        result["market_cap_bucket"] = mc_counts.div(mc_counts.sum(axis=1), axis=0)
    else:
        result["market_cap_bucket"] = pd.DataFrame()

    # Concentration: HHI = 1/n for an equal-weight portfolio
    n_per_month = df.groupby(date_col)[ticker_col].count()
    result["concentration"] = (1.0 / n_per_month).rename("hhi")

    return result


def value_trap_flags(
    df: pd.DataFrame,
    score_col: str,
    sector_col: str = "sector",
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Flag stocks that are cheap (top quintile by score) but fundamentally deteriorating.

    A value trap: top score quintile AND at least one of:
        - ttm_operating_margin < vtf_min_operating_margin (default 0)
        - debt_to_ebitda > vtf_max_debt_to_ebitda (default 10)
        - roa < vtf_min_roa (default -0.05)
        - earnings_yield < vtf_min_earnings_yield (default -0.05)

    Parameters
    ----------
    df : pd.DataFrame
        Monthly feature DataFrame with score_col. Should also have
        ttm_operating_margin, debt_to_ebitda, roa where available.
    score_col : str
        Column used for ranking. Higher = better.
    sector_col : str
        Sector column name.
    config : dict or None
        Override any VTF_DEFAULTS key. Merged over defaults.

    Returns
    -------
    pd.DataFrame
        Rows where at least one flag is triggered. Columns:
        ticker, month_end_date (if present), score_col, flags, sector (if present).
    """
    cfg = {**VTF_DEFAULTS, **(config or {})}
    df = df.copy()
    date_col = "month_end_date"

    # Top quintile threshold per month (or global if no date column)
    cutoff = float(cfg["vtf_top_quintile_cutoff"])
    if date_col in df.columns:
        df["_q_thresh"] = df.groupby(date_col)[score_col].transform(
            lambda x: x.quantile(cutoff)
        )
    else:
        df["_q_thresh"] = df[score_col].quantile(cutoff)

    in_top_quintile = df[score_col] >= df["_q_thresh"]

    # Build individual flag columns
    flag_names: list[str] = []
    if "ttm_operating_margin" in df.columns:
        df["_flag_neg_operating_margin"] = df["ttm_operating_margin"] < float(cfg["vtf_min_operating_margin"])
        flag_names.append("_flag_neg_operating_margin")
    if "debt_to_ebitda" in df.columns:
        df["_flag_high_debt_to_ebitda"] = df["debt_to_ebitda"] > float(cfg["vtf_max_debt_to_ebitda"])
        flag_names.append("_flag_high_debt_to_ebitda")
    if "roa" in df.columns:
        df["_flag_negative_roa"] = df["roa"] < float(cfg["vtf_min_roa"])
        flag_names.append("_flag_negative_roa")
    if "earnings_yield" in df.columns:
        df["_flag_negative_earnings_yield"] = df["earnings_yield"] < float(cfg["vtf_min_earnings_yield"])
        flag_names.append("_flag_negative_earnings_yield")

    if not flag_names:
        return pd.DataFrame()

    any_flag = df[flag_names].any(axis=1)
    mask_flagged = in_top_quintile & any_flag

    out = df.loc[mask_flagged].copy()

    # Build human-readable flags string
    label_map = {
        "_flag_neg_operating_margin": "neg_operating_margin",
        "_flag_high_debt_to_ebitda": "high_debt_to_ebitda",
        "_flag_negative_roa": "negative_roa",
        "_flag_negative_earnings_yield": "negative_earnings_yield",
    }
    out["flags"] = out[flag_names].apply(
        lambda row: ", ".join(label_map[c] for c in flag_names if row[c]),
        axis=1,
    )

    # Select output columns
    keep = []
    if "ticker" in out.columns:
        keep.append("ticker")
    if date_col in out.columns:
        keep.append(date_col)
    keep.append(score_col)
    keep.append("flags")
    if sector_col in out.columns:
        keep.append(sector_col)

    return out[keep].reset_index(drop=True)


def apply_guardrails(
    portfolio_df: pd.DataFrame,
    holdings_df: pd.DataFrame,
    config: dict | None = None,
) -> dict:
    """
    Detect guardrail violations across the backtest (diagnostic only).

    This function does NOT modify portfolio returns. It identifies months and
    guardrails where thresholds were breached so the analyst can assess impact.

    Parameters
    ----------
    portfolio_df : pd.DataFrame
        Monthly returns DataFrame from run_monthly_backtest(). Unused directly
        but included for API consistency; violations are assessed from holdings_df.
    holdings_df : pd.DataFrame
        One row per (date, ticker) in each month's portfolio. Must have a date
        column ('date' or 'month_end_date') and 'ticker'. Optionally: 'sector',
        'debt_to_ebitda', 'ttm_operating_margin'.
    config : dict or None
        Guardrail thresholds. Defaults to GUARDRAIL_DEFAULTS.

    Returns
    -------
    dict with keys:
        violations : list of dicts {date, guardrail, value, threshold, detail}
        summary    : DataFrame of per-month sector weights (informational).
    """
    cfg = {**GUARDRAIL_DEFAULTS, **(config or {})}
    violations: list[dict] = []

    holdings = holdings_df.copy()
    if "date" not in holdings.columns and "month_end_date" in holdings.columns:
        holdings = holdings.rename(columns={"month_end_date": "date"})
    holdings["date"] = pd.to_datetime(holdings["date"])

    summary = pd.DataFrame()

    # Sector weight guardrail
    if "sector" in holdings.columns:
        sec_counts = (
            holdings.groupby(["date", "sector"])["ticker"].count().unstack(fill_value=0)
        )
        sector_wts = sec_counts.div(sec_counts.sum(axis=1), axis=0)
        summary = sector_wts
        max_sw = float(cfg["max_sector_weight"])
        for dt, row in sector_wts.iterrows():
            for sec, wt in row.items():
                if float(wt) > max_sw:
                    violations.append({
                        "date": dt,
                        "guardrail": "max_sector_weight",
                        "value": float(wt),
                        "threshold": max_sw,
                        "detail": str(sec),
                    })

    # Debt-to-EBITDA guardrail
    if "debt_to_ebitda" in holdings.columns:
        max_d2e = float(cfg["max_debt_to_ebitda"])
        flagged = holdings[holdings["debt_to_ebitda"] > max_d2e]
        for dt, grp in flagged.groupby("date"):
            n_total = len(holdings[holdings["date"] == dt])
            n_bad = len(grp)
            violations.append({
                "date": dt,
                "guardrail": "max_debt_to_ebitda",
                "value": float(n_bad / n_total),
                "threshold": max_d2e,
                "detail": f"{n_bad}/{n_total} stocks exceed threshold",
            })

    # Operating margin guardrail
    min_margin = cfg.get("min_operating_margin")
    if min_margin is not None and "ttm_operating_margin" in holdings.columns:
        min_m = float(min_margin)
        flagged = holdings[holdings["ttm_operating_margin"] < min_m]
        for dt, grp in flagged.groupby("date"):
            n_total = len(holdings[holdings["date"] == dt])
            n_bad = len(grp)
            violations.append({
                "date": dt,
                "guardrail": "min_operating_margin",
                "value": float(n_bad / n_total),
                "threshold": min_m,
                "detail": f"{n_bad}/{n_total} stocks below threshold",
            })

    return {"violations": violations, "summary": summary}


def constrained_holdings(
    holdings_df: pd.DataFrame,
    features_df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Apply guardrails to produce an actionable filtered holdings set.

    For each month:
    1. Exclude tickers with debt_to_ebitda > config["max_debt_to_ebitda"].
    2. If any sector exceeds config["max_sector_weight"], remove the
       lowest-scoring tickers from that sector until the constraint is met.

    Parameters
    ----------
    holdings_df : pd.DataFrame
        Columns: month_end_date (or date), ticker.
    features_df : pd.DataFrame
        Columns: month_end_date (or date), ticker, sector, debt_to_ebitda, score.
        Used to look up attributes and scores for each held stock.
    config : dict or None
        Guardrail config merged over GUARDRAIL_DEFAULTS.

    Returns
    -------
    pd.DataFrame
        Filtered holdings with the same columns as holdings_df.
    """
    cfg = {**GUARDRAIL_DEFAULTS, **(config or {})}
    max_d2e = float(cfg["max_debt_to_ebitda"])
    max_sw = float(cfg["max_sector_weight"])

    # Normalise date column
    h = holdings_df.copy()
    if "date" not in h.columns and "month_end_date" in h.columns:
        h = h.rename(columns={"month_end_date": "date"})
    h["date"] = pd.to_datetime(h["date"])

    f = features_df.copy()
    if "date" not in f.columns and "month_end_date" in f.columns:
        f = f.rename(columns={"month_end_date": "date"})
    f["date"] = pd.to_datetime(f["date"])

    # Join features onto holdings
    merge_cols = ["date", "ticker"]
    feat_cols = [c for c in ["sector", "debt_to_ebitda", "score"] if c in f.columns]
    merged = h.merge(f[merge_cols + feat_cols], on=["date", "ticker"], how="left")

    # Step 1: exclude high-leverage stocks
    if "debt_to_ebitda" in merged.columns:
        merged = merged[
            merged["debt_to_ebitda"].isna() | (merged["debt_to_ebitda"] <= max_d2e)
        ]

    # Step 2: trim overweight sectors per month
    if "sector" in merged.columns and "score" in merged.columns:
        months = merged["date"].unique()
        kept_rows = []
        for dt in months:
            month_df = merged[merged["date"] == dt].copy()
            n_total = len(month_df)
            if n_total == 0:
                continue
            # Iterate until no sector exceeds max_sw
            while True:
                n_now = len(month_df)
                if n_now == 0:
                    break
                sec_counts = month_df["sector"].value_counts()
                sec_weights = sec_counts / n_now
                over = sec_weights[sec_weights > max_sw]
                if over.empty:
                    break
                # Remove the lowest-scoring stock from the most overweight sector
                worst_sector = over.idxmax()
                sector_stocks = month_df[month_df["sector"] == worst_sector].sort_values(
                    "score", ascending=True
                )
                drop_idx = sector_stocks.index[0]
                month_df = month_df.drop(index=drop_idx)
            kept_rows.append(month_df)
        if kept_rows:
            merged = pd.concat(kept_rows, ignore_index=True)
        else:
            merged = merged.iloc[0:0]

    # Return only the original holdings_df columns
    original_cols = [c for c in holdings_df.columns if c in merged.columns or c == "month_end_date"]
    # Restore original date column name if needed
    if "month_end_date" in holdings_df.columns and "date" in merged.columns:
        merged = merged.rename(columns={"date": "month_end_date"})
    out_cols = [c for c in holdings_df.columns if c in merged.columns]
    return merged[out_cols].reset_index(drop=True)


def drawdown_analysis(returns_series: pd.Series) -> dict:
    """
    Detailed drawdown analysis beyond the scalar max_drawdown.

    Parameters
    ----------
    returns_series : pd.Series
        Monthly returns (not cumulative). Index should be dates.

    Returns
    -------
    dict with keys:
        max_drawdown              : float (negative, e.g. -0.25 = -25%)
        max_drawdown_start        : index value at the last peak before trough
        max_drawdown_end          : index value at the trough
        max_drawdown_duration_months : int (months from peak to trough)
        recovery_date             : index value when equity recovers to prior peak
                                    (None if not recovered within the series)
        avg_drawdown              : float (mean of all underwater months)
        underwater_months         : int (months with cum return below prior peak)
    """
    rets = returns_series.dropna()
    if len(rets) == 0:
        return {
            "max_drawdown": np.nan,
            "max_drawdown_start": None,
            "max_drawdown_end": None,
            "max_drawdown_duration_months": 0,
            "recovery_date": None,
            "avg_drawdown": np.nan,
            "underwater_months": 0,
        }

    cum = (1 + rets).cumprod()
    rolling_max = cum.cummax()
    drawdowns = (cum - rolling_max) / rolling_max

    max_drawdown = float(drawdowns.min())
    max_dd_end_idx = drawdowns.idxmin()

    # Start of the worst drawdown: last peak before the trough
    pre_trough_cum = cum.loc[:max_dd_end_idx]
    pre_trough_max = rolling_max.loc[:max_dd_end_idx]
    at_peak = pre_trough_cum >= pre_trough_max
    max_dd_start_idx = at_peak[at_peak].index[-1] if at_peak.any() else rets.index[0]

    # Duration: number of months from peak to trough
    idx_list = rets.index.tolist()
    try:
        start_pos = idx_list.index(max_dd_start_idx)
        end_pos = idx_list.index(max_dd_end_idx)
        duration = end_pos - start_pos
    except ValueError:
        duration = 0

    # Recovery: first date strictly after trough where cum >= peak at trough
    peak_val = float(rolling_max.loc[max_dd_end_idx])
    post_trough = cum.loc[max_dd_end_idx:]
    # Skip the trough itself (first element)
    recovered_after = post_trough.iloc[1:][post_trough.iloc[1:] >= peak_val]
    recovery_date = recovered_after.index[0] if len(recovered_after) > 0 else None

    underwater = drawdowns < 0
    avg_drawdown = float(drawdowns[underwater].mean()) if underwater.any() else 0.0
    underwater_months = int(underwater.sum())

    return {
        "max_drawdown": max_drawdown,
        "max_drawdown_start": max_dd_start_idx,
        "max_drawdown_end": max_dd_end_idx,
        "max_drawdown_duration_months": duration,
        "recovery_date": recovery_date,
        "avg_drawdown": avg_drawdown,
        "underwater_months": underwater_months,
    }


def beta_decomposition(
    portfolio_returns: pd.Series,
    spy_returns: pd.Series,
    sector_col: str | None = None,
    portfolio_df: pd.DataFrame | None = None,
) -> dict:
    """
    Compute full-period market beta and rolling 12-month beta.

    Parameters
    ----------
    portfolio_returns : pd.Series
        Monthly portfolio returns. Index = dates.
    spy_returns : pd.Series
        Monthly SPY returns. Index = dates.
    sector_col : str or None
        If provided with portfolio_df, compute per-sector betas.
    portfolio_df : pd.DataFrame or None
        Holdings DataFrame with date column and sector_col.

    Returns
    -------
    dict with keys:
        market_beta    : float (full-period OLS beta vs SPY)
        beta_by_period : pd.Series (rolling 12-month beta, min 6 periods)
        sector_betas   : dict {sector -> beta} (only present if sector_col given)
    """
    common = portfolio_returns.index.intersection(spy_returns.index)
    p = portfolio_returns.loc[common].dropna()
    s = spy_returns.loc[common].reindex(p.index).dropna()
    p = p.loc[s.index]

    if len(p) < 2:
        return {"market_beta": np.nan, "beta_by_period": pd.Series(dtype=float)}

    var_spy = float(s.var(ddof=1))
    market_beta = (
        float(np.cov(p.values, s.values, ddof=1)[0, 1] / var_spy)
        if var_spy > 0
        else np.nan
    )

    # Rolling 12-month beta (min 6 periods)
    window = 12
    min_periods = 6
    betas: dict = {}
    for i, idx in enumerate(p.index):
        start = max(0, i - window + 1)
        p_w = p.iloc[start: i + 1]
        s_w = s.iloc[start: i + 1]
        valid = p_w.notna() & s_w.notna()
        if valid.sum() < min_periods:
            betas[idx] = np.nan
            continue
        pv = p_w[valid].values
        sv = s_w[valid].values
        vr = float(np.var(sv, ddof=1))
        betas[idx] = float(np.cov(pv, sv, ddof=1)[0, 1] / vr) if vr > 0 else np.nan

    beta_by_period = pd.Series(betas, name="rolling_beta")
    result: dict = {"market_beta": market_beta, "beta_by_period": beta_by_period}

    # Optional sector betas
    if sector_col is not None and portfolio_df is not None:
        date_col = "date" if "date" in portfolio_df.columns else "month_end_date"
        sector_betas: dict = {}
        for sector, grp in portfolio_df.groupby(sector_col):
            dates = pd.to_datetime(grp[date_col]).unique()
            mask = p.index.isin(dates)
            if mask.sum() < 2:
                continue
            ps = p[mask]
            ss = s.reindex(ps.index).dropna()
            ps = ps.reindex(ss.index)
            if len(ps) < 2:
                continue
            vs = float(ss.var(ddof=1))
            sector_betas[sector] = (
                float(np.cov(ps.values, ss.values, ddof=1)[0, 1] / vs)
                if vs > 0
                else np.nan
            )
        result["sector_betas"] = sector_betas

    return result
