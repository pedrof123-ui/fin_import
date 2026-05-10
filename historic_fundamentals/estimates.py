"""
Alpha Vantage EARNINGS_ESTIMATES fetcher and forward PE calculator.

Fetches analyst EPS and revenue estimates for a ticker and stores time-series
snapshots in historic_fundamentals.duckdb. Unlike the DCF's internal cache
(financial_statements.duckdb), this table preserves historical snapshots so
estimate revisions can be tracked over time.

Usage:
    import duckdb
    from av_financials_db import RateLimiter
    from historic_fundamentals.db import HistoricFundamentalsDB
    from historic_fundamentals.estimates import (
        fetch_estimates, normalize_estimates, compute_forward_eps
    )

    api_key = "YOUR_AV_KEY"
    limiter = RateLimiter()           # shared 75-calls/min limiter
    db = HistoricFundamentalsDB()

    # Fetch and store estimates for a ticker
    raw   = fetch_estimates("AAPL", api_key, limiter)
    rows  = normalize_estimates("AAPL", raw)
    db.upsert_estimates("AAPL", rows)

    # Compute forward 12M EPS from stored estimates
    fwd_eps = compute_forward_eps(db.conn, "AAPL")
    # fwd_eps = sum of next 4 quarterly eps_avg, or next annual eps_avg as fallback

    db.close()

Rate limit:
    One AV API call per ticker. Use the shared RateLimiter from av_financials_db
    to stay within the 75 calls/minute limit across all scripts.

Forward EPS logic:
    1. Take the next 4 quarterly eps_avg estimates (fiscal_date > today)
    2. If fewer than 4 quarterly estimates are available, fall back to the
       next annual eps_avg
    3. Returns None if no future estimates are present
"""

import logging
from datetime import UTC, date, datetime
from typing import Any

import duckdb
import requests

from av_financials_db import RateLimiter

log = logging.getLogger(__name__)

_AV_URL = "https://www.alphavantage.co/query"


def _f(v: Any) -> float | None:
    if v in (None, "", "None", "nan"):
        return None
    try:
        result = float(v)
        return None if result != result else result  # guard NaN
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    r = _f(v)
    return int(r) if r is not None else None


def fetch_estimates(ticker: str, api_key: str, limiter: RateLimiter) -> list[dict]:
    """Fetch EARNINGS_ESTIMATES from Alpha Vantage. Respects the shared rate limiter."""
    limiter.wait()
    log.debug("GET EARNINGS_ESTIMATES %s", ticker)
    resp = requests.get(
        _AV_URL,
        params={"function": "EARNINGS_ESTIMATES", "symbol": ticker, "apikey": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    for key in ("Error Message", "Information", "Note"):
        if data.get(key):
            raise RuntimeError(f"AV API [EARNINGS_ESTIMATES] {data[key]}")
    estimates = data.get("estimates")
    if not isinstance(estimates, list):
        raise RuntimeError("AV response missing 'estimates' list")
    return estimates


def normalize_estimates(ticker: str, raw: list[dict]) -> list[dict]:
    """Convert raw AV response rows to DB-ready dicts."""
    fetched_at = datetime.now(UTC)
    rows = []
    for item in raw:
        d = item.get("date")
        horizon = item.get("horizon")
        if not d or not horizon:
            continue
        rows.append({
            "ticker": ticker,
            "fiscal_date": d,
            "horizon": horizon,
            "fetched_at": fetched_at,
            "eps_avg":      _f(item.get("eps_estimate_average")),
            "eps_high":     _f(item.get("eps_estimate_high")),
            "eps_low":      _f(item.get("eps_estimate_low")),
            "eps_count":    _i(item.get("eps_estimate_analyst_count")),
            "eps_avg_7d":   _f(item.get("eps_estimate_average_7_days_ago")),
            "eps_avg_30d":  _f(item.get("eps_estimate_average_30_days_ago")),
            "eps_avg_60d":  _f(item.get("eps_estimate_average_60_days_ago")),
            "eps_avg_90d":  _f(item.get("eps_estimate_average_90_days_ago")),
            "eps_rev_up_7d":    _i(item.get("eps_estimate_revision_up_trailing_7_days")),
            "eps_rev_down_7d":  _i(item.get("eps_estimate_revision_down_trailing_7_days")),
            "eps_rev_up_30d":   _i(item.get("eps_estimate_revision_up_trailing_30_days")),
            "eps_rev_down_30d": _i(item.get("eps_estimate_revision_down_trailing_30_days")),
            "rev_avg":   _f(item.get("revenue_estimate_average")),
            "rev_high":  _f(item.get("revenue_estimate_high")),
            "rev_low":   _f(item.get("revenue_estimate_low")),
            "rev_count": _i(item.get("revenue_estimate_analyst_count")),
        })
    return rows


def compute_forward_eps(
    conn: duckdb.DuckDBPyConnection,
    ticker: str,
    as_of_date: date | None = None,
) -> float | None:
    """
    Forward 12M EPS from the most recent estimate snapshot.
    Uses the sum of the next 4 quarterly eps_avg values; falls back to the next
    annual estimate if fewer than 4 quarterly estimates are available.
    """
    if as_of_date is None:
        as_of_date = date.today()

    quarterly = conn.execute("""
        SELECT fiscal_date, eps_avg
        FROM earnings_estimates
        WHERE ticker = ?
          AND horizon = 'fiscal quarter'
          AND fiscal_date > ?
          AND eps_avg IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY fiscal_date ORDER BY fetched_at DESC) = 1
        ORDER BY fiscal_date
        LIMIT 4
    """, [ticker, as_of_date]).fetchall()

    if len(quarterly) >= 4:
        return sum(r[1] for r in quarterly)

    annual = conn.execute("""
        SELECT fiscal_date, eps_avg
        FROM earnings_estimates
        WHERE ticker = ?
          AND horizon = 'fiscal year'
          AND fiscal_date > ?
          AND eps_avg IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY fiscal_date ORDER BY fetched_at DESC) = 1
        ORDER BY fiscal_date
        LIMIT 1
    """, [ticker, as_of_date]).fetchone()

    return annual[1] if annual else None
