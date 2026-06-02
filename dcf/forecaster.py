"""
Forecasting module for the DCF engine.

Annual income statement data (from 10-K) is used for all forecasting.
US companies file 3 quarterly 10-Qs (each reporting YTD income) + 1 annual 10-K,
so quarterly income totals cover only 9 of 12 months — unreliable for annual aggregation.
The quarterly data is still required (for WACC balance sheet computations).

Forecast methodology:
  Revenue Y1-Y2: blended signal —
             50%/25% quarterly momentum (EWM of last-4-quarter YoY rates + linear trend)
             50%/75% annual EWM growth (exponentially weighted, half-life ~1.4 yrs).
  Revenue Y3-Y10: carry forward Y2's growth rate flat across all remaining years. When a
             user pins a year's revenue, subsequent years carry forward that year's implied
             growth rate. Terminal growth is used only for the terminal value calculation.
  P&L ratios (cogs_pct, sga_pct, rd_pct, interest_pct, other_opex_pct): historical mean
             applied flat across all 10 forecast years. Mean-reversion is the standard DCF
             assumption — ratios are bounded by competitive dynamics over a 10-year horizon.
  D&A and CapEx: normalized 5-year mean from the CF statement, applied flat across all
             growth years. CapEx/revenue and D&A/revenue are mean-reverting; extrapolating
             a spike would distort FCFF in the terminal period.
"""

import numpy as np
import pandas as pd


def _safe_ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    with np.errstate(divide="ignore", invalid="ignore"):
        r = num.values / den.values
    return pd.Series(r).replace([np.inf, -np.inf], np.nan)


def _mean_ratio(hist: np.ndarray, default: float, lo: float, hi: float) -> float:
    """Exponentially weighted mean of a ratio series, clipped to [lo, hi]. Recent years weighted more."""
    if len(hist) == 0:
        return float(np.clip(default, lo, hi))
    w = np.exp(np.arange(len(hist)) * 0.5)
    w /= w.sum()
    val = float(np.dot(w, hist))
    return float(np.clip(val, lo, hi))


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


def _annual_ewm_growth(vals: np.ndarray) -> float:
    """Exponentially weighted mean of YoY growth rates (half-life ~1.4 yrs). Default 3%."""
    if len(vals) >= 2:
        with np.errstate(divide="ignore", invalid="ignore"):
            gr = np.diff(vals) / vals[:-1]
        gr = gr[np.isfinite(gr)]
        if len(gr) > 0:
            w = np.exp(np.arange(len(gr)) * 0.5)
            w /= w.sum()
            return float(np.dot(w, gr))
    return 0.03


def _rev_forecast_y1y2(
    annual_rev: pd.Series,
    quarterly_income: pd.DataFrame,
) -> tuple[float, float, float]:
    """
    Y1 = 50% quarterly momentum + 50% annual EWM growth
    Y2 = 25% quarterly momentum + 75% annual EWM growth  (momentum decays)
    Falls back to annual EWM only when quarterly data is insufficient.
    Returns (y1_revenue, y2_revenue, annual_ewm_growth).
    """
    vals = annual_rev.dropna().values.astype(float)
    last = vals[-1]

    annual_g = _annual_ewm_growth(vals)

    q_signal = _quarterly_momentum_signal(quarterly_income)

    if q_signal is not None:
        g1 = 0.5 * q_signal + 0.5 * annual_g
        g2 = 0.25 * q_signal + 0.75 * annual_g
    else:
        g1 = annual_g
        g2 = annual_g

    y1 = last * (1 + g1)
    return y1, y1 * (1 + g2), annual_g


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

    # Align on common index — cap at 7 years (one full business cycle).
    # Median over the full history incorporates stale structural data for companies
    # whose working capital model has shifted (e.g. AAPL receivables, CAT inventory).
    # 7 years is long enough to span a cyclical peak-to-trough-to-peak while staying
    # within the current operating era.
    _LOOKBACK = 7
    idx = income_df.index.intersection(balance_df.index)
    if len(idx) == 0:
        # Fall back to positional alignment (take min length)
        n = min(len(income_df), len(balance_df), _LOOKBACK)
        rev_v = rev.values[:n]
        cogs_v = cogs.values[:n]
        ar_v = ar.values[:n] if len(ar) >= n else np.full(n, np.nan)
        ap_v = ap.values[:n] if len(ap) >= n else np.full(n, np.nan)
        inv_v = inv.values[:n] if len(inv) >= n else np.full(n, np.nan)
    else:
        idx = idx[:_LOOKBACK]
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
        return float(np.median(valid)) if len(valid) > 0 else 0.0

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
    rev_y1, rev_y2, g_lr = _rev_forecast_y1y2(rev, quarterly["income"])
    g_lr = float(np.clip(g_lr, -0.10, 0.15))
    rev_y = [rev_y1, rev_y2]

    # COGS % of revenue.
    # A company is treated as not reporting COGS when both cost_of_revenue and gross_profit
    # are missing in the most recent annual period (e.g. service cos. like UPS that file only
    # SG&A + other operating expenses). In that case cogs_pct = 0 and the operating cost
    # structure is anchored to operating_income via the other_opex residual below.
    cogs_ser = inc_a["cost_of_revenue"] if "cost_of_revenue" in inc_a.columns else pd.Series(dtype=float)
    gp_ser = inc_a["gross_profit"] if "gross_profit" in inc_a.columns else pd.Series(dtype=float)
    latest_cogs = cogs_ser.iloc[-1] if len(cogs_ser) else np.nan
    latest_gp = gp_ser.iloc[-1] if len(gp_ser) else np.nan
    reports_cogs = pd.notna(latest_cogs) or pd.notna(latest_gp)

    if reports_cogs:
        if cogs_ser.isna().all() and not gp_ser.isna().all():
            cogs_ser = inc_a["revenue"] - gp_ser
        hist_cogs = _safe_ratio(cogs_ser.reindex(inc_a.index), inc_a["revenue"]).dropna().values
    else:
        hist_cogs = np.array([])

    # SG&A % of revenue — fall back to gross_profit - operating_income when not reported separately
    sga_ser = inc_a["selling_general_admin"] if "selling_general_admin" in inc_a.columns else pd.Series(dtype=float)
    hist_sga = _safe_ratio(sga_ser.reindex(inc_a.index), inc_a["revenue"]).dropna().values
    _sga_fallback_used = False
    if len(hist_sga) < 2 and reports_cogs and "operating_income" in inc_a.columns:
        residual = (gp_ser - inc_a["operating_income"]).clip(lower=0)
        inferred = _safe_ratio(residual, inc_a["revenue"]).dropna().values
        if len(inferred) >= 2:
            hist_sga = inferred
            _sga_fallback_used = True

    # Guard against AV double-counting: some companies (e.g. UPS) have AV reporting
    # total operating expenses in the SGA field while also reporting cost_of_revenue
    # separately. When the two together exceed 100% of revenue on a profitable company,
    # recompute SGA as gross_profit − operating_income (the true below-gross-profit
    # operating cost residual) instead of the raw AV figure.
    if (
        reports_cogs
        and not _sga_fallback_used
        and len(hist_cogs) >= 2
        and len(hist_sga) >= 2
        and not gp_ser.isna().all()
        and "operating_income" in inc_a.columns
    ):
        _trial_cogs = _mean_ratio(hist_cogs, 0.5, 0.0, 1.0)
        _trial_sga  = _mean_ratio(hist_sga,  0.1, 0.0, 0.8)
        _ebit_hist  = _safe_ratio(
            inc_a["operating_income"].reindex(inc_a.index), inc_a["revenue"]
        ).dropna().values
        if _trial_cogs + _trial_sga > 1.0 and len(_ebit_hist) >= 2 and float(np.median(_ebit_hist)) > 0:
            sga_ser = (gp_ser - inc_a["operating_income"].reindex(inc_a.index)).clip(lower=0)
            hist_sga = _safe_ratio(sga_ser, inc_a["revenue"]).dropna().values
            _sga_fallback_used = True

    # R&D % of revenue — may be all-null for many companies
    rd_ser = inc_a["research_development"] if "research_development" in inc_a.columns else pd.Series(dtype=float)
    hist_rd = _safe_ratio(rd_ser.reindex(inc_a.index), inc_a["revenue"]).dropna().values
    has_rd = len(hist_rd) > 0 and not np.all(hist_rd == 0)

    # Net interest cost = gross interest expense − interest income, floored at 0.
    # For cash-rich companies (e.g. AAPL, MSFT) interest income substantially offsets
    # borrowing costs; using net avoids overstating the below-the-line financing drag.
    # Falls back to gross interest expense when interest_income is absent or all-NaN.
    int_gross = inc_a["interest_expense"] if "interest_expense" in inc_a.columns else pd.Series(dtype=float)
    int_income = inc_a["interest_income"] if "interest_income" in inc_a.columns else pd.Series(dtype=float)
    int_ser = (
        int_gross.abs().reindex(inc_a.index)
        - int_income.abs().reindex(inc_a.index).fillna(0)
    ).clip(lower=0)
    hist_int = _safe_ratio(int_ser, inc_a["revenue"]).dropna().values

    # Other operating expense % — residual that absorbs costs not captured by COGS/SGA/R&D.
    # Anchor depends on what the company reports:
    #   - reports_cogs: residual against gross profit (captures e.g. Amazon fulfillment, S&M)
    #   - !reports_cogs: residual against revenue (anchors EBIT margin to actual op_income for
    #     service cos. that don't split cost of services from SG&A)
    # Skipped when SGA fallback already absorbed the full gross-to-operating residual.
    op_inc_ser = inc_a["operating_income"] if "operating_income" in inc_a.columns else pd.Series(dtype=float)
    if not _sga_fallback_used and not op_inc_ser.isna().all():
        # ffill propagates the last known SGA/R&D amount into periods where the
        # provider hasn't yet published the line item (common in AV for the most
        # recent fiscal year). Without this, the NaN would be treated as zero and
        # the entire SGA amount would fall through into other_opex, spiking it.
        sga_raw = sga_ser.abs().reindex(inc_a.index).ffill().fillna(0)
        rd_raw = rd_ser.abs().reindex(inc_a.index).ffill().fillna(0)
        if reports_cogs and not gp_ser.isna().all():
            other_opex_ser = (gp_ser - op_inc_ser - sga_raw - rd_raw).clip(lower=0)
        elif not reports_cogs:
            other_opex_ser = (inc_a["revenue"] - op_inc_ser - sga_raw - rd_raw).clip(lower=0)
        else:
            other_opex_ser = pd.Series(dtype=float)
        hist_other_opex = _safe_ratio(other_opex_ser, inc_a["revenue"]).dropna().values
    else:
        hist_other_opex = np.array([])
    has_other_opex = len(hist_other_opex) >= 2 and np.any(hist_other_opex > 0.005)

    # Other non-operating income/loss % of revenue.
    # = (pretax_income − operating_income + |interest_expense|) / revenue
    # Captures recurring below-the-line items: investment income, equity method earnings,
    # pension credits, net FX, etc.  Clipped to ±5% of revenue to limit the effect of
    # one-time events (large write-offs, asset-sale gains) on the 10-year forecast.
    pretax_ser = inc_a["pretax_income"] if "pretax_income" in inc_a.columns else pd.Series(dtype=float)
    if not pretax_ser.isna().all() and not op_inc_ser.isna().all():
        int_abs = int_ser.reindex(inc_a.index).fillna(0)   # int_ser is already net & ≥0
        other_income_ser = pretax_ser.reindex(inc_a.index) - op_inc_ser + int_abs
        hist_other_pct = _safe_ratio(other_income_ser, inc_a["revenue"]).dropna().values
    else:
        hist_other_pct = np.array([])

    # CapEx % of revenue — normalized 5-year mean from CF statement.
    cx_denom = inc_a["revenue"].reindex(cf_a.index).values
    hist_cx = _safe_ratio(cf_a["capital_expenditures"].abs(), pd.Series(cx_denom)).dropna().values
    cx_norm = hist_cx[hist_cx > 0]
    cx_pct_norm = float(cx_norm.mean()) if len(cx_norm) > 0 else 0.05

    # D&A % of revenue — normalized 5-year mean from CF statement.
    da_ser = cf_a["depreciation_amortization"].abs() if "depreciation_amortization" in cf_a.columns else pd.Series(dtype=float)
    hist_da = _safe_ratio(da_ser.reindex(cf_a.index), pd.Series(cx_denom)).dropna()
    hist_da = hist_da[hist_da > 0]
    da_pct_norm = float(hist_da.mean()) if not hist_da.empty else 0.03

    # P&L ratios: historical mean applied flat across all 5 forecast years.
    cogs_flat = _mean_ratio(hist_cogs, 0.5, 0.0, 1.0) if reports_cogs else 0.0
    sga_flat  = _mean_ratio(hist_sga,  0.1, 0.0, 0.8)
    rd_flat   = _mean_ratio(hist_rd,   0.0, 0.0, 0.5) if has_rd else None
    int_flat  = _mean_ratio(hist_int,  0.02, 0.0, 0.3)
    other_opex_flat = _mean_ratio(hist_other_opex, 0.0, 0.0, 0.8) if has_other_opex else 0.0
    other_flat = _mean_ratio(hist_other_pct, 0.0, -0.05, 0.05) if len(hist_other_pct) >= 2 else 0.0

    # Revenue Y3-Y10: placeholder using flat g_lr; overwritten by extend_growth_years() in model.py
    # after analyst estimates and user overrides are fully resolved.
    rev_y3_10 = []
    prev = rev_y2
    for _ in range(8):
        nxt = prev * (1 + g_lr)
        rev_y3_10.append(nxt)
        prev = nxt

    rev_all = list(rev_y) + rev_y3_10
    cogs_all = [cogs_flat] * 10
    sga_all  = [sga_flat]  * 10
    rd_all   = [rd_flat]   * 10 if has_rd else [None] * 10
    int_all  = [int_flat]  * 10
    other_all = [other_flat] * 10
    other_opex_all = [other_opex_flat] * 10

    prev_rev = [last_rev] + list(rev_all)

    forecasts = []
    for i in range(10):
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
                other_pct=float(other_all[i]),
                other_opex_pct=float(other_opex_all[i]),
                capex_pct_revenue=cx_pct_norm,
                da_pct=da_pct_norm,
                reports_cogs=reports_cogs,
            )
        )

    return forecasts


def extend_growth_years(year_forecasts: list, overrides) -> list:
    """
    Y3-Y10 carry forward Y2's revenue growth rate (no fade to terminal growth).
    When a user overrides a year's revenue, subsequent non-overridden years carry
    forward that year's implied growth rate instead.
    Called after analyst estimates and user overrides are fully applied.
    """
    g = year_forecasts[1].revenue_growth
    prev_rev = year_forecasts[1].revenue
    for yf in year_forecasts[2:]:
        if _has_rev_override(overrides, yf.year):
            if prev_rev > 0:
                g = yf.revenue / prev_rev - 1
            prev_rev = yf.revenue
            continue
        yf.revenue_growth = float(g)
        yf.revenue = float(prev_rev * (1 + g))
        prev_rev = yf.revenue
    return year_forecasts


def _has_rev_override(overrides, year: int) -> bool:
    if overrides is None:
        return False
    yo = overrides.years.get(year)
    return yo is not None and (yo.revenue is not None or yo.revenue_growth is not None)


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
                other_opex_pct=yo.other_opex_pct if yo.other_opex_pct is not None else yf.other_opex_pct,
                capex_pct_revenue=yo.capex_pct_revenue if yo.capex_pct_revenue is not None else yf.capex_pct_revenue,
                da_pct=yo.da_pct if yo.da_pct is not None else yf.da_pct,
                reports_cogs=yf.reports_cogs,
            )
        )

    # Recompute revenue levels. When yo.revenue is set, use it as the absolute anchor;
    # otherwise chain from growth rates. Update revenue_growth to stay internally consistent
    # so that extend_growth_years (which reads year_forecasts[1].revenue_growth) is correct.
    last_rev = base[0].revenue / (1 + base[0].revenue_growth) if (1 + base[0].revenue_growth) != 0 else base[0].revenue
    for yf in result:
        yo = overrides.years.get(yf.year)
        if yo is not None and yo.revenue is not None:
            yf.revenue = yo.revenue
        else:
            yf.revenue = last_rev * (1 + yf.revenue_growth)
        if last_rev > 0:
            yf.revenue_growth = yf.revenue / last_rev - 1
        last_rev = yf.revenue

    return result
