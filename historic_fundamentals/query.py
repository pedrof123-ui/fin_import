"""
Notebook-friendly query functions for historic fundamentals.

No SQL required. Each function opens and closes its own DB connection.

Setup in a notebook (one-time, first cell):
    import sys
    sys.path.insert(0, "..")   # path to project root from notebooks/
    from historic_fundamentals import get_pe_stats, get_pe_history, get_estimates

Usage:
    # PE statistics — one ticker
    get_pe_stats("AAPL")

    # PE statistics — multiple tickers
    get_pe_stats(["AAPL", "MSFT", "GOOGL"])

    # PE statistics — all tickers in the database
    get_pe_stats()

    # Monthly PE history
    get_pe_history("AAPL")
    get_pe_history("AAPL", start="2020-01-01", end="2024-12-31")

    # Analyst estimates
    get_estimates("AAPL")
    get_estimates(["AAPL", "MSFT"], horizon="fiscal quarter")
"""

import os
from datetime import date as _date

import pandas as pd
from dotenv import load_dotenv

from historic_fundamentals.db import DEFAULT_DB_PATH, HistoricFundamentalsDB


def _open_db() -> HistoricFundamentalsDB:
    load_dotenv()
    path = os.getenv("HF_DB_PATH") or DEFAULT_DB_PATH
    return HistoricFundamentalsDB(path)


def _tickers(t) -> list[str] | None:
    if t is None:
        return None
    if isinstance(t, str):
        return [t.upper()]
    return [x.upper() for x in t]


def get_pe_stats(tickers=None) -> pd.DataFrame:
    """
    Statistics snapshot: PE, P/FCF, EV/EBITDA, growth metrics.

    Args:
        tickers: str, list[str], or None (returns all tickers)

    Returns DataFrame with columns:
        ticker, market_cap_b,
        current_pe, pe_lt_median, pe_p25, pe_p75, pe_p10, pe_p90,
        pe_rolling_5yr_median, forward_pe, forward_12m_eps, current_ttm_eps,
        months_available, ttm_dividend, dividend_yield,
        rev_growth_1yr, rev_cagr_3yr, rev_cagr_5yr, rev_ntm_growth_est,
        earn_growth_1yr, earn_cagr_3yr, earn_cagr_5yr, earn_ntm_growth_est,
        current_pfcf, pfcf_lt_median, pfcf_p25, pfcf_p75,
        pfcf_rolling_5yr_median, current_fcf_yield, forward_pfcf,
        fcf_growth_1yr, fcf_cagr_3yr, fcf_cagr_5yr, fcf_margin_5yr_median,
        current_evebitda, evebitda_lt_median, evebitda_p25, evebitda_p75,
        evebitda_rolling_5yr_median

    Examples:
        get_pe_stats("AAPL")
        get_pe_stats(["AAPL", "MSFT"])
        get_pe_stats()
    """
    db = _open_db()
    try:
        df = db.query_pe_stats(_tickers(tickers))
    finally:
        db.close()

    cols = [
        "ticker", "market_cap_b", "current_price",
        "current_pe", "pe_lt_median", "pe_p25", "pe_p75", "pe_p10", "pe_p90",
        "pe_rolling_5yr_median", "normalized_pe_5y",
        "current_earnings_yield", "earnings_yield_3y_avg", "earnings_yield_5y_avg",
        "forward_pe", "forward_12m_eps", "forward_earnings_yield",
        "current_ttm_eps", "months_available",
        "ttm_dividend", "dividend_yield",
        "rev_growth_1yr", "rev_cagr_3yr", "rev_cagr_5yr", "rev_ntm_growth_est",
        "earn_growth_1yr", "earn_cagr_3yr", "earn_cagr_5yr", "earn_ntm_growth_est",
        "current_pfcf", "pfcf_lt_median", "pfcf_p25", "pfcf_p75",
        "pfcf_rolling_5yr_median", "current_fcf_yield", "forward_pfcf",
        "fcf_growth_1yr", "fcf_cagr_3yr", "fcf_cagr_5yr", "fcf_margin_5yr_median",
        "current_evebitda", "evebitda_lt_median", "evebitda_p25", "evebitda_p75",
        "evebitda_rolling_5yr_median", "ebitda_margin_5yr_median", "forward_evebitda",
        "current_ps", "ps_lt_median", "ps_p25", "ps_p75", "ps_rolling_5yr_median", "forward_ps",
        "current_roa", "roa_lt_median", "roa_p25", "roa_p75", "roa_rolling_5yr_median",
        "current_roe", "roe_lt_median", "roe_p25", "roe_p75", "roe_rolling_5yr_median",
        "current_roic", "roic_lt_median", "roic_p25", "roic_p75", "roic_rolling_5yr_median",
        "current_pbv", "pbv_lt_median", "pbv_p25", "pbv_p75", "pbv_rolling_5yr_median",
        "current_ptbv", "ptbv_lt_median", "ptbv_p25", "ptbv_p75", "ptbv_rolling_5yr_median",
        "goal_pe", "goal_pcf", "goal_peg", "goal_bv", "goal_2x", "goal_low", "goal_high",
    ]
    return df[[c for c in cols if c in df.columns]]


def get_pe_history(tickers, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """
    Monthly PE history for one or more tickers.

    Args:
        tickers: str or list[str]
        start:   "YYYY-MM-DD" inclusive start date (optional)
        end:     "YYYY-MM-DD" inclusive end date (optional)

    Returns DataFrame with columns:
        ticker, month_end_date, price, ttm_eps, pe_ratio,
        pe_rolling_5yr_median, ttm_source, ttm_dividend, dividend_yield, ttm_revenue

    Examples:
        get_pe_history("AAPL")
        get_pe_history(["AAPL", "MSFT"], start="2020-01-01")
        get_pe_history("AAPL", start="2015-01-01", end="2024-12-31")
    """
    db = _open_db()
    try:
        df = db.query_pe_timeseries(
            _tickers(tickers),
            start_date=_date.fromisoformat(start) if start else None,
            end_date=_date.fromisoformat(end) if end else None,
        )
    finally:
        db.close()

    cols = [
        "ticker", "month_end_date", "price", "ttm_eps",
        "pe_ratio", "pe_rolling_5yr_median", "normalized_pe_5y",
        "earnings_yield", "earnings_yield_3y_avg", "earnings_yield_5y_avg",
        "ttm_source", "ttm_dividend", "dividend_yield", "ttm_revenue",
        "ttm_fcf", "pfcf_ratio", "pfcf_rolling_5yr_median", "fcf_yield",
        "ttm_ebitda", "ev_ebitda", "ev_ebitda_rolling_5yr_median",
        "ps_ratio", "ps_rolling_5yr_median",
        "roa", "roa_rolling_5yr_median",
        "roe", "roe_rolling_5yr_median",
        "roic", "roic_rolling_5yr_median",
        "pbv", "pbv_rolling_5yr_median",
        "ptbv", "ptbv_rolling_5yr_median",
        "goal_pe", "goal_pcf", "goal_peg", "goal_bv", "goal_2x", "goal_low", "goal_high",
    ]
    return df[[c for c in cols if c in df.columns]]


def get_estimates(tickers, horizon: str | None = None) -> pd.DataFrame:
    """
    Latest analyst EPS and revenue estimates for one or more tickers.

    Returns only the most recently fetched snapshot per (ticker, fiscal_date, horizon),
    so each period appears once.

    Args:
        tickers: str or list[str]
        horizon: "fiscal quarter", "fiscal year", or None (returns both)

    Returns DataFrame with columns:
        ticker, fiscal_date, horizon,
        eps_avg, eps_high, eps_low, eps_count,
        rev_avg, rev_high, rev_low, fetched_at

    Examples:
        get_estimates("AAPL")
        get_estimates(["AAPL", "MSFT"])
        get_estimates("AAPL", horizon="fiscal quarter")
    """
    db = _open_db()
    try:
        df = db.query_estimates(_tickers(tickers), horizon=horizon)
    finally:
        db.close()

    if df.empty:
        return df

    df = (
        df.sort_values("fetched_at", ascending=False)
          .groupby(["ticker", "fiscal_date", "horizon"], sort=False)
          .first()
          .reset_index()
          .sort_values(["ticker", "fiscal_date"])
          .reset_index(drop=True)
    )

    cols = [
        "ticker", "fiscal_date", "horizon",
        "eps_avg", "eps_high", "eps_low", "eps_count",
        "rev_avg", "rev_high", "rev_low", "fetched_at",
    ]
    return df[[c for c in cols if c in df.columns]]
