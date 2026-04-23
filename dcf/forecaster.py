"""
Forecasting module for the DCF engine.

Annual income statement data (from 10-K) is used for all forecasting.
US companies file 3 quarterly 10-Qs (each reporting YTD income) + 1 annual 10-K,
so quarterly income totals cover only 9 of 12 months — unreliable for annual aggregation.
The quarterly data is still required (for WACC balance sheet computations).

Forecast methodology:
  Years 1-2: SARIMAX(0,1,0) on annual revenue levels (random-walk-with-drift);
             ratios (margins, capex%) use ARIMA on annual history.
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


def forecast_assumptions(
    quarterly: dict[str, pd.DataFrame],  # noqa: ARG001 — kept for API compatibility
    annual: dict[str, pd.DataFrame],
) -> list:
    """
    Returns model-computed YearForecast for years 1-5 using annual income data.
    """
    from dcf.assumptions import YearForecast

    inc_a = annual["income"].sort_values("period_end_date")
    cf_a = annual["cashflow"].sort_values("period_end_date")

    rev = inc_a["revenue"].dropna()
    gp = inc_a["gross_profit"].dropna()
    oi = inc_a["operating_income"].dropna()

    # --- Y1, Y2 via ARIMA on annual revenue levels ---
    rev_fc2 = _arima_forecast(rev, 2)

    last_rev = float(rev.iloc[-1])
    rev_y = [float(rev_fc2[0]), float(rev_fc2[1])]

    # Ratios from annual history
    hist_gm = _safe_ratio(inc_a["gross_profit"], inc_a["revenue"]).dropna().values
    hist_om = _safe_ratio(inc_a["operating_income"], inc_a["revenue"]).dropna().values
    cx_denom = inc_a["revenue"].reindex(cf_a.index).values
    hist_cx = _safe_ratio(cf_a["capital_expenditures"].abs(), pd.Series(cx_denom)).dropna().values

    # Y1/Y2 margin forecasts via ARIMA
    def _ratio_forecast(hist: np.ndarray, n: int) -> np.ndarray:
        if len(hist) < 2:
            return np.full(n, hist.mean() if len(hist) else 0.0)
        return _arima_forecast(pd.Series(hist), n)

    gm_fc2 = _ratio_forecast(hist_gm, 2)
    om_fc2 = _ratio_forecast(hist_om, 2)
    cx_fc2 = _ratio_forecast(hist_cx, 2)

    rev_2 = rev_y
    gm_2 = [float(np.clip(v, 0.0, 1.0)) for v in gm_fc2]
    om_2 = [float(np.clip(v, -0.5, 0.8)) for v in om_fc2]
    cx_2 = [float(np.clip(v, 0.0, 0.5)) for v in cx_fc2]

    # --- Y3-Y5 via linear regression on (history + Y1/Y2) ---
    rev_combined = np.append(rev.values.astype(float), rev_2)
    gm_combined = np.append(hist_gm, gm_2) if len(hist_gm) else np.array(gm_2)
    om_combined = np.append(hist_om, om_2) if len(hist_om) else np.array(om_2)
    cx_combined = np.append(hist_cx, cx_2) if len(hist_cx) else np.array(cx_2)

    rev_y3_5 = _linear_forecast(rev_combined, 3)
    gm_y3_5 = _linear_forecast(gm_combined, 3)
    om_y3_5 = _linear_forecast(om_combined, 3)
    cx_y3_5 = _linear_forecast(cx_combined, 3)

    rev_all = rev_2 + list(rev_y3_5)
    gm_all = gm_2 + [float(np.clip(v, 0.0, 1.0)) for v in gm_y3_5]
    om_all = om_2 + [float(np.clip(v, -0.5, 0.8)) for v in om_y3_5]
    cx_all = cx_2 + [float(np.clip(v, 0.0, 0.5)) for v in cx_y3_5]

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
                gross_margin=float(gm_all[i]),
                operating_margin=float(om_all[i]),
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
                gross_margin=yo.gross_margin if yo.gross_margin is not None else yf.gross_margin,
                operating_margin=yo.operating_margin if yo.operating_margin is not None else yf.operating_margin,
                capex_pct_revenue=yo.capex_pct_revenue if yo.capex_pct_revenue is not None else yf.capex_pct_revenue,
            )
        )

    # Recompute revenue levels from (possibly overridden) growth rates
    last_rev = base[0].revenue / (1 + base[0].revenue_growth) if (1 + base[0].revenue_growth) != 0 else base[0].revenue
    for yf in result:
        yf.revenue = last_rev * (1 + yf.revenue_growth)
        last_rev = yf.revenue

    return result
