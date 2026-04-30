"""
Forecasting module for the DCF engine.

Annual income statement data (from 10-K) is used for all forecasting.
US companies file 3 quarterly 10-Qs (each reporting YTD income) + 1 annual 10-K,
so quarterly income totals cover only 9 of 12 months — unreliable for annual aggregation.
The quarterly data is still required (for WACC balance sheet computations).

Forecast methodology:
  Years 1-2: Revenue via blended signal —
             50%/25% quarterly momentum (EWM of last-4-quarter YoY rates + linear trend)
             50%/75% annual EWM growth (exponentially weighted, half-life ~1.4 yrs).
             Ratios (margins, capex%) use ARIMA on annual history.
  Years 3-5: OLS linear regression on (historical annual + Y1/Y2 forecasts).
"""

import warnings
import numpy as np
import pandas as pd


def _arima_forecast(series: pd.Series, n: int) -> np.ndarray:
    """
    ARIMA(0,1,0) with trend on annual data — random walk with drift.
    Falls back to linear extrapolation if fit fails.
    """
    from statsmodels.tsa.arima.model import ARIMA

    values = series.dropna().values.astype(float)
    if len(values) < 3:
        x = np.arange(len(values))
        return np.polyval(np.polyfit(x, values, 1), np.arange(len(values), len(values) + n))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            res = ARIMA(values, order=(0, 1, 0), trend="t").fit()
            return res.forecast(n)
        except Exception:
            pass

    x = np.arange(len(values))
    return np.polyval(np.polyfit(x, values, 1), np.arange(len(values), len(values) + n))


def _linear_forecast(y_hist: np.ndarray, n_future: int) -> np.ndarray:
    """OLS linear regression extrapolation."""
    x = np.arange(len(y_hist))
    coef = np.polyfit(x, y_hist, 1)
    return np.polyval(coef, np.arange(len(y_hist), len(y_hist) + n_future))


def _safe_ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    with np.errstate(divide="ignore", invalid="ignore"):
        r = num.values / den.values
    return pd.Series(r).replace([np.inf, -np.inf], np.nan)


def _ratio_forecast(hist: np.ndarray, n: int) -> np.ndarray:
    if len(hist) < 2:
        return np.full(n, hist.mean() if len(hist) else 0.0)
    return _arima_forecast(pd.Series(hist), n)


def _quarterly_momentum_signal(quarterly_income: pd.DataFrame) -> float | None:
    """
    Annualized revenue growth signal from recent quarterly YoY comparisons.

    US companies file 3 quarterly 10-Qs with YTD-cumulative income (Q1 standalone,
    Q2 = 6-month YTD, Q3 = 9-month YTD) so there are only 3 entries per fiscal year,
    not 4.  A simple positions[i] vs positions[i-4] comparison would mix period types
    (e.g. Q1 standalone vs Q3 YTD from 12 months ago).

    Detection: if two or more consecutive entries drop >35% from the prior entry,
    the data is YTD-cumulative.  In that case the function groups entries by fiscal
    year (reset at each big drop) and compares like-for-like positions across years.
    If no YTD pattern is detected (standalone quarters), direct i vs i-4 is used.
    """
    rev_q = quarterly_income["revenue"].dropna()
    if len(rev_q) < 8:
        return None

    vals = rev_q.values.astype(float)

    # Detect fiscal-year reset boundaries (Q1 standalone << prior Q3 YTD)
    q1_indices = [i for i in range(1, len(vals)) if vals[i] < vals[i - 1] * 0.65]
    ytd_pattern = len(q1_indices) >= 2

    if ytd_pattern:
        # Group entries into fiscal years starting at each Q1 boundary
        groups = []
        for j, start in enumerate(q1_indices):
            end = q1_indices[j + 1] if j + 1 < len(q1_indices) else len(vals)
            groups.append(vals[start:end])

        # Compare same-position entries across consecutive fiscal years
        yoy_list: list[float] = []
        for j in range(len(groups) - 1):
            g_prev, g_curr = groups[j], groups[j + 1]
            for k in range(min(len(g_prev), len(g_curr))):
                if g_prev[k] > 0 and g_curr[k] > 0:
                    yoy_list.append((g_curr[k] - g_prev[k]) / g_prev[k])

        yoy = np.array(yoy_list[-4:]) if len(yoy_list) >= 2 else None
    else:
        # Standalone quarters: direct i vs i-4 is valid
        candidates = [
            (vals[i] - vals[i - 4]) / vals[i - 4]
            for i in range(-4, 0)
            if vals[i - 4] > 0 and vals[i] > 0
        ]
        yoy = np.array(candidates) if len(candidates) >= 2 else None

    if yoy is None or len(yoy) < 2:
        return None

    # EWM: most recent quarter gets highest weight (half-life ~1.4 quarters)
    weights = np.exp(np.arange(len(yoy)) * 0.7)
    weights /= weights.sum()
    ewm_level = float(np.dot(weights, yoy))

    # Linear trend projected one step ahead (captures acceleration / deceleration)
    x = np.arange(len(yoy))
    trend_signal = float(np.polyval(np.polyfit(x, yoy, 1), len(yoy)))

    return 0.6 * ewm_level + 0.4 * trend_signal


def _rev_forecast_y1y2(
    annual_rev: pd.Series,
    quarterly_income: pd.DataFrame,
) -> tuple[float, float]:
    """
    Y1 = 50% quarterly momentum + 50% annual EWM growth
    Y2 = 25% quarterly momentum + 75% annual EWM growth  (momentum decays)
    Falls back to annual EWM only when quarterly data is insufficient.
    """
    vals = annual_rev.dropna().values.astype(float)
    last = vals[-1]

    # Annual EWM of YoY growth rates (recent years weighted more, half-life ~1.4 yrs)
    if len(vals) >= 2:
        with np.errstate(divide="ignore", invalid="ignore"):
            gr = np.diff(vals) / vals[:-1]
        gr = gr[np.isfinite(gr)]
    else:
        gr = np.array([])

    if len(gr) > 0:
        w = np.exp(np.arange(len(gr)) * 0.5)
        w /= w.sum()
        annual_g = float(np.dot(w, gr))
    else:
        annual_g = 0.03

    q_signal = _quarterly_momentum_signal(quarterly_income)

    if q_signal is not None:
        g1 = 0.5 * q_signal + 0.5 * annual_g
        g2 = 0.25 * q_signal + 0.75 * annual_g
    else:
        g1 = annual_g
        g2 = annual_g

    y1 = last * (1 + g1)
    return y1, y1 * (1 + g2)


def compute_nwc_days(
    balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
) -> "NwcAssumptions":
    """
    Compute DSO, DPO, DIO from annual history.
    DSO = accounts_receivable / revenue * 365
    DPO = accounts_payable / cost_of_revenue * 365
    DIO = inventory / cost_of_revenue * 365
    """
    from dcf.assumptions import NwcAssumptions

    def _col(df, name):
        return df[name] if name in df.columns else pd.Series(np.nan, index=df.index)

    rev = _col(income_df, "revenue").replace(0, np.nan)
    cogs = _col(income_df, "cost_of_revenue").replace(0, np.nan)

    # Fallback: derive cost_of_revenue from gross_profit
    if cogs.isna().all() and "gross_profit" in income_df.columns:
        cogs = (rev - _col(income_df, "gross_profit")).replace(0, np.nan)

    ar = _col(balance_df, "accounts_receivable")
    ap = _col(balance_df, "accounts_payable")
    inv = _col(balance_df, "inventory")

    # Align on common index
    idx = income_df.index.intersection(balance_df.index)
    if len(idx) == 0:
        # Fall back to positional alignment (take min length)
        n = min(len(income_df), len(balance_df))
        rev_v = rev.values[:n]
        cogs_v = cogs.values[:n]
        ar_v = ar.values[:n] if len(ar) >= n else np.full(n, np.nan)
        ap_v = ap.values[:n] if len(ap) >= n else np.full(n, np.nan)
        inv_v = inv.values[:n] if len(inv) >= n else np.full(n, np.nan)
    else:
        rev_v = rev.loc[idx].values
        cogs_v = cogs.loc[idx].values
        ar_v = ar.reindex(idx).values
        ap_v = ap.reindex(idx).values
        inv_v = inv.reindex(idx).values

    with np.errstate(divide="ignore", invalid="ignore"):
        dso_series = np.where(rev_v > 0, ar_v / rev_v * 365, np.nan)
        dpo_series = np.where(cogs_v > 0, ap_v / cogs_v * 365, np.nan)
        dio_series = np.where(cogs_v > 0, inv_v / cogs_v * 365, np.nan)

    def _mean_pos(arr):
        valid = arr[~np.isnan(arr) & (arr >= 0)]
        return float(valid.mean()) if len(valid) > 0 else 0.0

    return NwcAssumptions(
        dso=_mean_pos(dso_series),
        dpo=_mean_pos(dpo_series),
        dio=_mean_pos(dio_series),
    )


def forecast_assumptions(
    quarterly: dict[str, pd.DataFrame],
    annual: dict[str, pd.DataFrame],
) -> list:
    """
    Returns model-computed YearForecast for years 1-5 using annual income data.
    """
    from dcf.assumptions import YearForecast

    inc_a = annual["income"].sort_values("period_end_date").tail(5).reset_index(drop=True)
    cf_a = annual["cashflow"].sort_values("period_end_date").tail(5).reset_index(drop=True)

    rev = inc_a["revenue"].dropna()

    # --- Y1, Y2: EWM annual growth + quarterly momentum blend ---
    last_rev = float(rev.iloc[-1])
    rev_y1, rev_y2 = _rev_forecast_y1y2(rev, quarterly["income"])
    rev_y = [rev_y1, rev_y2]

    # COGS % of revenue
    cogs_ser = inc_a["cost_of_revenue"] if "cost_of_revenue" in inc_a.columns else pd.Series(dtype=float)
    if cogs_ser.isna().all() and "gross_profit" in inc_a.columns:
        # Derive from gross_profit
        cogs_ser = inc_a["revenue"] - inc_a["gross_profit"]
    hist_cogs = _safe_ratio(cogs_ser.reindex(inc_a.index), inc_a["revenue"]).dropna().values

    # SG&A % of revenue
    sga_ser = inc_a["selling_general_admin"] if "selling_general_admin" in inc_a.columns else pd.Series(dtype=float)
    hist_sga = _safe_ratio(sga_ser.reindex(inc_a.index), inc_a["revenue"]).dropna().values

    # R&D % of revenue — may be all-null for many companies
    rd_ser = inc_a["research_development"] if "research_development" in inc_a.columns else pd.Series(dtype=float)
    hist_rd = _safe_ratio(rd_ser.reindex(inc_a.index), inc_a["revenue"]).dropna().values
    has_rd = len(hist_rd) > 0 and not np.all(hist_rd == 0)

    # Interest expense % of revenue (below-the-line; display only)
    int_ser = inc_a["interest_expense"] if "interest_expense" in inc_a.columns else pd.Series(dtype=float)
    hist_int = _safe_ratio(int_ser.abs().reindex(inc_a.index), inc_a["revenue"]).dropna().values

    # Other % of revenue — residual between operating income and (revenue - cogs - sga - rd)
    # Computed as: (EBIT - op_income_reported) / revenue; treat as zero if uncertain
    hist_other = np.zeros(len(rev))

    # CapEx % of revenue
    cx_denom = inc_a["revenue"].reindex(cf_a.index).values
    hist_cx = _safe_ratio(cf_a["capital_expenditures"].abs(), pd.Series(cx_denom)).dropna().values

    # Y1/Y2 via ARIMA
    cogs_fc2 = _ratio_forecast(hist_cogs if len(hist_cogs) >= 2 else np.array([0.5, 0.5]), 2)
    sga_fc2 = _ratio_forecast(hist_sga if len(hist_sga) >= 2 else np.array([0.1, 0.1]), 2)
    rd_fc2 = _ratio_forecast(hist_rd, 2) if has_rd else np.zeros(2)
    int_fc2 = _ratio_forecast(hist_int if len(hist_int) >= 2 else np.array([0.02, 0.02]), 2)
    cx_fc2 = _ratio_forecast(hist_cx if len(hist_cx) >= 2 else np.array([0.05, 0.05]), 2)

    def _clip(arr, lo, hi):
        return [float(np.clip(v, lo, hi)) for v in arr]

    cogs_2 = _clip(cogs_fc2, 0.0, 1.0)
    sga_2 = _clip(sga_fc2, 0.0, 0.8)
    rd_2 = _clip(rd_fc2, 0.0, 0.5)
    int_2 = _clip(int_fc2, 0.0, 0.3)
    cx_2 = _clip(cx_fc2, 0.0, 0.5)

    # Y3-Y5 via linear regression on (history + Y1/Y2)
    rev_combined = np.append(rev.values.astype(float), rev_y)

    def _extend(hist, y2_vals):
        return np.append(hist, y2_vals) if len(hist) else np.array(y2_vals)

    cogs_combined = _extend(hist_cogs, cogs_2)
    sga_combined = _extend(hist_sga, sga_2)
    rd_combined = _extend(hist_rd, rd_2) if has_rd else np.array(rd_2)
    int_combined = _extend(hist_int, int_2)
    cx_combined = _extend(hist_cx, cx_2)

    # Revenue Y3-Y5: use OLS slope anchored at Y2 so momentum years don't cause a stall.
    # The slope captures the long-run annual increment; applying it from Y2 ensures a
    # smooth continuation rather than mean-reverting to the trend line level.
    rev_slope = float(np.polyfit(np.arange(len(rev_combined)), rev_combined, 1)[0])
    rev_y3_5 = np.array([rev_y[1] + rev_slope * i for i in range(1, 4)])
    cogs_y3_5 = _clip(_linear_forecast(cogs_combined, 3), 0.0, 1.0)
    sga_y3_5 = _clip(_linear_forecast(sga_combined, 3), 0.0, 0.8)
    rd_y3_5 = _clip(_linear_forecast(rd_combined, 3), 0.0, 0.5) if has_rd else [0.0, 0.0, 0.0]
    int_y3_5 = _clip(_linear_forecast(int_combined, 3), 0.0, 0.3)
    cx_y3_5 = _clip(_linear_forecast(cx_combined, 3), 0.0, 0.5)

    rev_all = rev_y + list(rev_y3_5)
    cogs_all = cogs_2 + cogs_y3_5
    sga_all = sga_2 + sga_y3_5
    rd_all = (rd_2 + rd_y3_5) if has_rd else [None] * 5
    int_all = int_2 + int_y3_5
    cx_all = cx_2 + cx_y3_5

    prev_rev = [last_rev] + list(rev_all)

    forecasts = []
    for i in range(5):
        rev_i = float(rev_all[i])
        g = (rev_i - prev_rev[i]) / prev_rev[i] if prev_rev[i] != 0 else 0.0
        forecasts.append(
            YearForecast(
                year=i + 1,
                revenue=rev_i,
                revenue_growth=float(g),
                cogs_pct=float(cogs_all[i]),
                sga_pct=float(sga_all[i]),
                rd_pct=float(rd_all[i]) if rd_all[i] is not None else None,
                interest_pct=float(int_all[i]),
                other_pct=0.0,
                capex_pct_revenue=float(cx_all[i]),
            )
        )

    return forecasts


def merge_overrides(base: list, overrides) -> list:
    """Apply per-year user overrides onto model-computed forecasts."""
    from dcf.assumptions import YearForecast

    if overrides is None:
        return base

    result = []
    for yf in base:
        yo = overrides.years.get(yf.year)
        if yo is None:
            result.append(yf)
            continue
        result.append(
            YearForecast(
                year=yf.year,
                revenue=yf.revenue,
                revenue_growth=yo.revenue_growth if yo.revenue_growth is not None else yf.revenue_growth,
                cogs_pct=yo.cogs_pct if yo.cogs_pct is not None else yf.cogs_pct,
                sga_pct=yo.sga_pct if yo.sga_pct is not None else yf.sga_pct,
                rd_pct=yo.rd_pct if yo.rd_pct is not None else yf.rd_pct,
                interest_pct=yo.interest_pct if yo.interest_pct is not None else yf.interest_pct,
                other_pct=yo.other_pct if yo.other_pct is not None else yf.other_pct,
                capex_pct_revenue=yo.capex_pct_revenue if yo.capex_pct_revenue is not None else yf.capex_pct_revenue,
            )
        )

    # Recompute revenue levels from (possibly overridden) growth rates
    last_rev = base[0].revenue / (1 + base[0].revenue_growth) if (1 + base[0].revenue_growth) != 0 else base[0].revenue
    for yf in result:
        yf.revenue = last_rev * (1 + yf.revenue_growth)
        last_rev = yf.revenue

    return result
