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
    PE statistics snapshot: long-term median, percentiles, current and forward PE.

    Args:
        tickers: str, list[str], or None (returns all tickers)

    Returns DataFrame with columns:
        ticker, market_cap_b, current_pe, pe_lt_median, pe_p25, pe_p75, pe_p10, pe_p90,
        pe_rolling_5yr_median, forward_pe, forward_12m_eps,
        current_ttm_eps, months_available, ttm_dividend, dividend_yield,
        rev_growth_1yr, rev_cagr_3yr, rev_cagr_5yr, rev_ntm_growth_est

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
        "ticker", "market_cap_b", "current_pe", "pe_lt_median",
        "pe_p25", "pe_p75", "pe_p10", "pe_p90",
        "pe_rolling_5yr_median", "forward_pe", "forward_12m_eps",
        "current_ttm_eps", "months_available",
        "ttm_dividend", "dividend_yield",
        "rev_growth_1yr", "rev_cagr_3yr", "rev_cagr_5yr", "rev_ntm_growth_est",
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
        "pe_ratio", "pe_rolling_5yr_median", "ttm_source",
        "ttm_dividend", "dividend_yield", "ttm_revenue",
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
