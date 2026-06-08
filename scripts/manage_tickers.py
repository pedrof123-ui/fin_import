#!/usr/bin/env python3
"""
Unified ticker management for the fundamentals-alpha pipeline.

Manages tickers across all three databases:
  prices.duckdb               — daily price history (owned by trade_systems)
  av_financials.duckdb        — Alpha Vantage raw financial statements
  historic_fundamentals.duckdb — computed PE timeseries, stats, and estimates

Commands
--------
  add     Fully onboard one or more tickers (prices → financials → PE → estimates)
  delete  Remove one or more tickers from all three databases

Quick start
-----------
  # Add new tickers (reads tickers from the command line)
  uv run scripts/manage_tickers.py add AAPL MSFT NVDA

  # Add from a CSV file (tickers in the first column, one per row)
  uv run scripts/manage_tickers.py add --csv data/new_tickers.csv

  # Delete delisted or irrelevant tickers
  uv run scripts/manage_tickers.py delete GME BB AMC
  uv run scripts/manage_tickers.py delete --csv data/delisted.csv

  # Preview changes without touching any database
  uv run scripts/manage_tickers.py add AAPL --dry-run
  uv run scripts/manage_tickers.py delete AAPL --dry-run

  # Re-import a ticker already in the database
  uv run scripts/manage_tickers.py add AAPL --force

  # Skip analyst estimate calls (saves 1 AV call per ticker, useful for bulk adds)
  uv run scripts/manage_tickers.py add AAPL --skip-estimates

What 'add' does per ticker (8 Alpha Vantage API calls)
-------------------------------------------------------
  Step 1  Price history        → prices.duckdb / stock_prices
  Step 2  Income statement     → av_financials.duckdb
          Balance sheet        → av_financials.duckdb
          Cash flow statement  → av_financials.duckdb
  Step 3  Shares outstanding   → av_financials.duckdb
  Step 4  Dividend history     → av_financials.duckdb
  Step 5  Company overview     → av_financials.duckdb  (sector, industry, name)
  Step 6  PE timeseries        → historic_fundamentals.duckdb / monthly_pe
          Goal prices          → historic_fundamentals.duckdb / monthly_pe
  Step 7  Analyst estimates    → historic_fundamentals.duckdb / earnings_estimates
  Step 8  Forward multiples    → historic_fundamentals.duckdb / pe_stats
          (forward P/E, P/FCF, EV/EBITDA, P/S, market cap)

What 'delete' does per ticker (no API calls)
--------------------------------------------
  Removes all rows for the ticker from:
    prices.duckdb               stock_prices (or etf_prices for ETF tickers)
    av_financials.duckdb        companies, income_statements, balance_sheets,
                                cash_flow_statements, shares_outstanding,
                                dividends, company_overview, import_log
    historic_fundamentals.duckdb monthly_pe, pe_stats, earnings_estimates

Rate limits
-----------
The add command makes ~8 Alpha Vantage API calls per ticker.
At 75 calls/minute (Premium plan) that is roughly 9 tickers/minute.
The built-in rate limiter enforces this automatically — no manual throttling needed.

Environment variables (.env)
-----------------------------
  ALPHA_VANTAGE_API_KEY   Required for add (and for delete with --skip-estimates absent)
  PRICES_DB_PATH          Absolute path to trade_systems/data/prices.duckdb
  AV_DB_PATH              Path to av_financials.duckdb  (default: data/av_financials.duckdb)
  HF_DB_PATH              Path to historic_fundamentals.duckdb  (default: data/historic_fundamentals.duckdb)

Using from trade_systems
-------------------------
From the trade_systems project you can call the same logic programmatically:

  from utilities.ticker_manager import add_tickers, delete_tickers

  add_tickers(["AAPL", "MSFT"])
  delete_tickers(["GME", "BB"])

Note
----
add_tickers.py is deprecated and exits with an error pointing here.
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH as AV_DB_PATH, AVFinancialsDB, RateLimiter  # noqa: E402
from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH, HistoricFundamentalsDB  # noqa: E402
from historic_fundamentals.pe import process_ticker, enrich_goals, extract_goal_stats  # noqa: E402
from historic_fundamentals.estimates import (  # noqa: E402
    fetch_estimates,
    normalize_estimates,
    compute_forward_eps,
    compute_ntm_revenue,
)

log = logging.getLogger(__name__)

# ETF tickers are routed to etf_prices instead of stock_prices in prices.duckdb.
# Keep in sync with trade_systems/utilities/etf_tickers.py.
_ETF_TICKERS: frozenset[str] = frozenset({
    "SPY", "IWM", "IWN", "MDY", "VTI",
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
    "GLD", "SLV", "USO", "CPER",
    "SDS", "SH", "RWM", "TWM",
    "SGOV", "SHV",
})

_AV_URL = "https://www.alphavantage.co/query"

_PRICES_INIT_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    ticker    VARCHAR  NOT NULL,
    date      DATE     NOT NULL,
    open      DOUBLE,
    high      DOUBLE,
    low       DOUBLE,
    close     DOUBLE,
    adj_close DOUBLE,
    volume    BIGINT,
    PRIMARY KEY (ticker, date)
)
"""

_PRICES_UPSERT_SQL = """
INSERT INTO {table} (ticker, date, open, high, low, close, adj_close, volume)
    SELECT ticker, date, open, high, low, close, adj_close, volume
    FROM df_to_insert
ON CONFLICT (ticker, date) DO UPDATE SET
    open      = excluded.open,
    high      = excluded.high,
    low       = excluded.low,
    close     = excluded.close,
    adj_close = excluded.adj_close,
    volume    = excluded.volume
"""


# ---------------------------------------------------------------------------
# CSV reader
# ---------------------------------------------------------------------------

import re as _re
_TICKER_RE = _re.compile(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$')


def _tickers_from_csv(path: str) -> list[str]:
    """Read tickers from a CSV file.

    Handles three common formats:
      plain list:       AAPL / MSFT / GOOGL (no header, first column)
      header row:       ticker / AAPL / MSFT (first column with header word)
      pandas export:    ,tickers / 0,AAPL / 1,MSFT (integer index → tickers in second column)

    A valid ticker is 1-5 uppercase letters with an optional dot-suffix (e.g. BRK.B).
    Anything that doesn't match that pattern is treated as a header or non-ticker row
    and skipped.
    """
    df = pd.read_csv(path, header=None, dtype=str)
    tickers: list[str] = []
    for col in df.columns:
        candidates = [
            v.strip().strip('"').upper()
            for v in df[col].dropna()
            if _TICKER_RE.match(v.strip().strip('"').upper())
        ]
        if candidates:
            return candidates
    return tickers


# ---------------------------------------------------------------------------
# Price backfill helpers (self-contained; no dependency on trade_systems)
# ---------------------------------------------------------------------------

def _fetch_prices_av(ticker: str, api_key: str, limiter: RateLimiter) -> pd.DataFrame:
    limiter.wait()
    resp = requests.get(
        _AV_URL,
        params={
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": ticker,
            "outputsize": "full",
            "datatype": "json",
            "apikey": api_key,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    for key in ("Error Message", "Information", "Note"):
        if data.get(key):
            raise RuntimeError(f"AV API [TIME_SERIES_DAILY_ADJUSTED] {data[key]}")
    if "Time Series (Daily)" not in data:
        raise ValueError(f"Unexpected AV response for {ticker}: {list(data.keys())}")
    rows = []
    for date_str, v in data["Time Series (Daily)"].items():
        adj = float(v["5. adjusted close"])
        rows.append({
            "ticker": ticker,
            "date": datetime.strptime(date_str, "%Y-%m-%d").date(),
            "open": float(v["1. open"]),
            "high": float(v["2. high"]),
            "low": float(v["3. low"]),
            "close": adj,
            "adj_close": adj,
            "volume": int(v["6. volume"]),
        })
    return pd.DataFrame(rows)


def _backfill_prices(ticker: str, prices_db_path: str, api_key: str, limiter: RateLimiter) -> int:
    """Fetch full AV price history and upsert into prices.duckdb. Returns rows upserted."""
    df = _fetch_prices_av(ticker, api_key, limiter)
    if df.empty:
        log.warning("%s: no price data returned from AV", ticker)
        return 0
    table = "etf_prices" if ticker in _ETF_TICKERS else "stock_prices"
    conn = duckdb.connect(prices_db_path)
    try:
        conn.execute(_PRICES_INIT_SQL.format(table=table))
        conn.register("df_to_insert", df)
        conn.execute(_PRICES_UPSERT_SQL.format(table=table))
    finally:
        conn.close()
    log.debug("%s: %d price rows upserted into %s", ticker, len(df), table)
    return len(df)


def _delete_prices(ticker: str, prices_db_path: str) -> int:
    """Delete all price rows for ticker from prices.duckdb. Returns rows deleted."""
    table = "etf_prices" if ticker in _ETF_TICKERS else "stock_prices"
    conn = duckdb.connect(prices_db_path)
    try:
        conn.execute(_PRICES_INIT_SQL.format(table="stock_prices"))
        conn.execute(_PRICES_INIT_SQL.format(table="etf_prices"))
        before = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE ticker = ?", [ticker]).fetchone()[0]
        conn.execute(f"DELETE FROM {table} WHERE ticker = ?", [ticker])
        deleted = before
    finally:
        conn.close()
    log.debug("%s: %d price rows deleted from %s", ticker, deleted, table)
    return deleted


# ---------------------------------------------------------------------------
# Forward multiple helpers (mirrors hf_update.py)
# ---------------------------------------------------------------------------

def _update_forward_pe(hf_db: HistoricFundamentalsDB, prices_conn, ticker: str) -> None:
    forward_eps = compute_forward_eps(hf_db.conn, ticker)
    if forward_eps and forward_eps > 0:
        row = prices_conn.execute(
            "SELECT adj_close FROM stock_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            [ticker],
        ).fetchone()
        price = row[0] if row else None
        forward_pe = price / forward_eps if price else None
    else:
        forward_pe = None
    hf_db.update_forward_pe(ticker, forward_pe, forward_eps)


def _update_market_cap(hf_db: HistoricFundamentalsDB, av_conn, prices_conn, ticker: str) -> None:
    row = prices_conn.execute(
        "SELECT adj_close FROM stock_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    price = row[0] if row else None
    if not price:
        hf_db.update_market_cap(ticker, None)
        return
    row = av_conn.execute("""
        SELECT shares_outstanding_diluted FROM shares_outstanding
        WHERE ticker = ? AND shares_outstanding_diluted IS NOT NULL
        ORDER BY date DESC LIMIT 1
    """, [ticker]).fetchone()
    if not row:
        row = av_conn.execute("""
            SELECT common_stock_shares_outstanding FROM balance_sheets
            WHERE ticker = ? AND period_type = 'quarterly'
                AND common_stock_shares_outstanding IS NOT NULL
            ORDER BY fiscal_date_ending DESC LIMIT 1
        """, [ticker]).fetchone()
    shares = row[0] if row else None
    market_cap_b = (price * shares / 1e9) if shares and shares > 0 else None
    hf_db.update_market_cap(ticker, market_cap_b)


def _update_rev_ntm_growth_est(hf_db: HistoricFundamentalsDB, av_conn, ticker: str) -> None:
    ntm_rev = compute_ntm_revenue(hf_db.conn, ticker)
    if ntm_rev is None:
        hf_db.update_rev_ntm_growth_est(ticker, None)
        return
    row = av_conn.execute("""
        SELECT SUM(total_revenue) FROM (
            SELECT total_revenue FROM income_statements
            WHERE ticker = ? AND period_type = 'quarterly' AND total_revenue IS NOT NULL
            ORDER BY fiscal_date_ending DESC LIMIT 4
        )
    """, [ticker]).fetchone()
    ttm_rev = row[0] if row and row[0] else None
    growth = (ntm_rev / ttm_rev - 1.0) if ttm_rev and ttm_rev > 0 else None
    hf_db.update_rev_ntm_growth_est(ticker, growth)


def _update_earn_ntm_growth_est(hf_db: HistoricFundamentalsDB, ticker: str) -> None:
    row = hf_db.conn.execute(
        "SELECT forward_12m_eps, current_ttm_eps FROM pe_stats WHERE ticker = ?", [ticker]
    ).fetchone()
    if not row or row[0] is None:
        hf_db.update_earn_ntm_growth_est(ticker, None)
        return
    forward_eps, current_ttm_eps = row
    growth = (forward_eps / current_ttm_eps - 1.0) if current_ttm_eps and current_ttm_eps > 0 else None
    hf_db.update_earn_ntm_growth_est(ticker, growth)


def _update_forward_pfcf(hf_db: HistoricFundamentalsDB, av_conn, prices_conn, ticker: str) -> None:
    row = hf_db.conn.execute(
        "SELECT fcf_margin_5yr_median FROM pe_stats WHERE ticker = ?", [ticker]
    ).fetchone()
    if not row or row[0] is None:
        hf_db.update_forward_pfcf(ticker, None)
        return
    fcf_margin = row[0]
    ntm_rev = compute_ntm_revenue(hf_db.conn, ticker)
    if not ntm_rev or ntm_rev <= 0:
        hf_db.update_forward_pfcf(ticker, None)
        return
    forward_fcf = ntm_rev * fcf_margin
    if forward_fcf <= 0:
        hf_db.update_forward_pfcf(ticker, None)
        return
    price_row = prices_conn.execute(
        "SELECT adj_close FROM stock_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    if not price_row:
        hf_db.update_forward_pfcf(ticker, None)
        return
    price = price_row[0]
    shares_row = av_conn.execute("""
        SELECT shares_outstanding_diluted FROM shares_outstanding
        WHERE ticker = ? AND shares_outstanding_diluted IS NOT NULL
        ORDER BY date DESC LIMIT 1
    """, [ticker]).fetchone()
    if not shares_row:
        shares_row = av_conn.execute("""
            SELECT common_stock_shares_outstanding FROM balance_sheets
            WHERE ticker = ? AND period_type = 'quarterly'
                AND common_stock_shares_outstanding IS NOT NULL
            ORDER BY fiscal_date_ending DESC LIMIT 1
        """, [ticker]).fetchone()
    shares = shares_row[0] if shares_row else None
    if not shares or shares <= 0:
        hf_db.update_forward_pfcf(ticker, None)
        return
    forward_fcf_per_share = forward_fcf / shares
    hf_db.update_forward_pfcf(ticker, price / forward_fcf_per_share if forward_fcf_per_share > 0 else None)


def _update_forward_evebitda(hf_db: HistoricFundamentalsDB, av_conn, prices_conn, ticker: str) -> None:
    row = hf_db.conn.execute(
        "SELECT ebitda_margin_5yr_median FROM pe_stats WHERE ticker = ?", [ticker]
    ).fetchone()
    if not row or row[0] is None:
        hf_db.update_forward_evebitda(ticker, None)
        return
    ebitda_margin = row[0]
    ntm_rev = compute_ntm_revenue(hf_db.conn, ticker)
    if not ntm_rev or ntm_rev <= 0:
        hf_db.update_forward_evebitda(ticker, None)
        return
    forward_ebitda = ntm_rev * ebitda_margin
    if forward_ebitda <= 0:
        hf_db.update_forward_evebitda(ticker, None)
        return
    price_row = prices_conn.execute(
        "SELECT adj_close FROM stock_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    if not price_row:
        hf_db.update_forward_evebitda(ticker, None)
        return
    price = price_row[0]
    shares_row = av_conn.execute("""
        SELECT shares_outstanding_diluted FROM shares_outstanding
        WHERE ticker = ? AND shares_outstanding_diluted IS NOT NULL
        ORDER BY date DESC LIMIT 1
    """, [ticker]).fetchone()
    if not shares_row:
        shares_row = av_conn.execute("""
            SELECT common_stock_shares_outstanding FROM balance_sheets
            WHERE ticker = ? AND period_type = 'quarterly'
                AND common_stock_shares_outstanding IS NOT NULL
            ORDER BY fiscal_date_ending DESC LIMIT 1
        """, [ticker]).fetchone()
    shares = shares_row[0] if shares_row else None
    if not shares or shares <= 0:
        hf_db.update_forward_evebitda(ticker, None)
        return
    debt_row = av_conn.execute("""
        SELECT
            COALESCE(long_term_debt_noncurrent, 0) +
            COALESCE(short_term_debt, 0) +
            COALESCE(current_long_term_debt, 0) AS total_debt,
            cash_and_short_term_investments
        FROM balance_sheets
        WHERE ticker = ? AND period_type = 'quarterly'
            AND (long_term_debt_noncurrent IS NOT NULL
                 OR short_term_debt IS NOT NULL
                 OR current_long_term_debt IS NOT NULL)
        ORDER BY fiscal_date_ending DESC LIMIT 1
    """, [ticker]).fetchone()
    if not debt_row:
        hf_db.update_forward_evebitda(ticker, None)
        return
    ev = price * shares + (debt_row[0] or 0.0) - (debt_row[1] or 0.0)
    if ev <= 0:
        hf_db.update_forward_evebitda(ticker, None)
        return
    hf_db.update_forward_evebitda(ticker, ev / forward_ebitda)


def _update_forward_ps(hf_db: HistoricFundamentalsDB, av_conn, prices_conn, ticker: str) -> None:
    ntm_rev = compute_ntm_revenue(hf_db.conn, ticker)
    if not ntm_rev or ntm_rev <= 0:
        hf_db.update_forward_ps(ticker, None)
        return
    price_row = prices_conn.execute(
        "SELECT adj_close FROM stock_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    if not price_row:
        hf_db.update_forward_ps(ticker, None)
        return
    price = price_row[0]
    shares_row = av_conn.execute("""
        SELECT shares_outstanding_diluted FROM shares_outstanding
        WHERE ticker = ? AND shares_outstanding_diluted IS NOT NULL
        ORDER BY date DESC LIMIT 1
    """, [ticker]).fetchone()
    if not shares_row:
        shares_row = av_conn.execute("""
            SELECT common_stock_shares_outstanding FROM balance_sheets
            WHERE ticker = ? AND period_type = 'quarterly'
                AND common_stock_shares_outstanding IS NOT NULL
            ORDER BY fiscal_date_ending DESC LIMIT 1
        """, [ticker]).fetchone()
    shares = shares_row[0] if shares_row else None
    if not shares or shares <= 0:
        hf_db.update_forward_ps(ticker, None)
        return
    hf_db.update_forward_ps(ticker, price * shares / ntm_rev)


# ---------------------------------------------------------------------------
# add command
# ---------------------------------------------------------------------------

def _add_ticker(
    ticker: str,
    av_db: AVFinancialsDB,
    hf_db: HistoricFundamentalsDB,
    prices_db_path: str,
    api_key: str,
    limiter: RateLimiter,
    force: bool,
    skip_estimates: bool,
) -> bool:
    """Run the full add pipeline for one ticker. Returns True on success."""

    # Step 1 — Price backfill (opens its own R/W connection; must complete before
    # any read-only connection is opened to the same file)
    try:
        n = _backfill_prices(ticker, prices_db_path, api_key, limiter)
        log.info("  prices: %d rows upserted", n)
    except Exception as exc:
        log.error("  prices: FAILED — %s", exc)
        return False

    # Steps 2–8 need a read-only prices connection; open it after the R/W backfill
    prices_conn = duckdb.connect(prices_db_path, read_only=True)
    try:
        # Step 2-4 — Financial statements, shares, dividends
        if not force and av_db.has_ticker(ticker):
            log.info("  av_financials: already present (use --force to re-import)")
        else:
            try:
                rows = av_db.import_ticker(ticker, api_key, limiter)
                log.debug("  statements: %d rows", rows)
            except Exception as exc:
                log.error("  statements: FAILED — %s", exc)
                return False
            try:
                av_db.import_shares_outstanding(ticker, api_key, limiter)
            except Exception as exc:
                log.error("  shares: FAILED — %s", exc)
                return False
            try:
                av_db.import_dividends(ticker, api_key, limiter)
            except Exception as exc:
                log.error("  dividends: FAILED — %s", exc)
                return False

        # Step 5 — Company overview (sector/industry)
        try:
            av_db.import_company_overview(ticker, api_key, limiter)
            log.debug("  overview: imported")
        except Exception as exc:
            log.warning("  overview: failed (scoring will lack sector data) — %s", exc)

        # Step 6 — PE timeseries + goal prices
        try:
            monthly_pe, stats = process_ticker(ticker, av_db.conn, prices_conn)
            if monthly_pe.empty:
                log.warning("  pe: no data computed (missing financials or prices?)")
            else:
                if stats:
                    monthly_pe = enrich_goals(monthly_pe, stats, hf_db.conn, ticker)
                    stats.update(extract_goal_stats(monthly_pe))
                hf_db.upsert_monthly_pe(ticker, monthly_pe)
                if stats:
                    hf_db.upsert_pe_stats(stats)
                log.debug("  pe: %d months", len(monthly_pe))
        except Exception as exc:
            log.error("  pe timeseries: FAILED — %s", exc)
            return False

        # Step 7 — Analyst estimates
        if not skip_estimates:
            try:
                raw = fetch_estimates(ticker, api_key, limiter)
                est_rows = normalize_estimates(ticker, raw)
                hf_db.upsert_estimates(ticker, est_rows)
                log.debug("  estimates: %d rows", len(est_rows))
            except Exception as exc:
                log.warning("  estimates: failed — %s", exc)

        # Step 8 — Forward multiples
        try:
            _update_forward_pe(hf_db, prices_conn, ticker)
            _update_rev_ntm_growth_est(hf_db, av_db.conn, ticker)
            _update_earn_ntm_growth_est(hf_db, ticker)
            _update_forward_pfcf(hf_db, av_db.conn, prices_conn, ticker)
            _update_forward_evebitda(hf_db, av_db.conn, prices_conn, ticker)
            _update_forward_ps(hf_db, av_db.conn, prices_conn, ticker)
            _update_market_cap(hf_db, av_db.conn, prices_conn, ticker)
            log.debug("  forward multiples: updated")
        except Exception as exc:
            log.warning("  forward multiples: failed — %s", exc)
    finally:
        prices_conn.close()

    return True


def cmd_add(args: argparse.Namespace, tickers: list[str]) -> int:
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        log.error("ALPHA_VANTAGE_API_KEY not set in .env")
        return 2

    prices_db_path = os.getenv("PRICES_DB_PATH")
    if not prices_db_path:
        log.error("PRICES_DB_PATH not set in .env")
        return 2

    av_db_path = os.getenv("AV_DB_PATH") or AV_DB_PATH
    hf_db_path = os.getenv("HF_DB_PATH") or HF_DB_PATH

    if args.dry_run:
        log.info("[dry-run] Would add %d ticker(s): %s", len(tickers), ", ".join(tickers))
        log.info("[dry-run] Databases: prices=%s  av=%s  hf=%s", prices_db_path, av_db_path, hf_db_path)
        return 0

    av_db = AVFinancialsDB(av_db_path)
    hf_db = HistoricFundamentalsDB(hf_db_path)
    limiter = RateLimiter()

    ok = failed = 0
    try:
        for i, ticker in enumerate(tickers, 1):
            log.info("[%d/%d] %s", i, len(tickers), ticker)
            success = _add_ticker(
                ticker, av_db, hf_db, prices_db_path,
                api_key, limiter, args.force, args.skip_estimates,
            )
            if success:
                ok += 1
                log.info("[%d/%d] %s — done", i, len(tickers), ticker)
            else:
                failed += 1
                log.error("[%d/%d] %s — failed", i, len(tickers), ticker)
    finally:
        av_db.close()
        hf_db.close()

    log.info("add complete: %d ok, %d failed", ok, failed)
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# delete command
# ---------------------------------------------------------------------------

def cmd_delete(args: argparse.Namespace, tickers: list[str]) -> int:
    prices_db_path = os.getenv("PRICES_DB_PATH")
    if not prices_db_path:
        log.error("PRICES_DB_PATH not set in .env")
        return 2

    av_db_path = os.getenv("AV_DB_PATH") or AV_DB_PATH
    hf_db_path = os.getenv("HF_DB_PATH") or HF_DB_PATH

    if args.dry_run:
        log.info("[dry-run] Would delete %d ticker(s): %s", len(tickers), ", ".join(tickers))
        log.info("[dry-run] Databases: prices=%s  av=%s  hf=%s", prices_db_path, av_db_path, hf_db_path)
        return 0

    av_db = AVFinancialsDB(av_db_path)
    hf_db = HistoricFundamentalsDB(hf_db_path)

    ok = failed = 0
    try:
        for i, ticker in enumerate(tickers, 1):
            log.info("[%d/%d] %s — deleting", i, len(tickers), ticker)
            try:
                prices_deleted = _delete_prices(ticker, prices_db_path)
                av_deleted = av_db.delete_ticker(ticker)
                hf_deleted = hf_db.delete_ticker(ticker)
                log.info(
                    "[%d/%d] %s — deleted: %d price rows, %d av rows, %d hf rows",
                    i, len(tickers), ticker, prices_deleted, av_deleted, hf_deleted,
                )
                ok += 1
            except Exception as exc:
                log.error("[%d/%d] %s — FAILED: %s", i, len(tickers), ticker, exc)
                failed += 1
    finally:
        av_db.close()
        hf_db.close()

    log.info("delete complete: %d ok, %d failed", ok, failed)
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="manage_tickers",
        description="Unified ticker management for the fundamentals-alpha pipeline.",
        epilog=(
            "Examples:\n"
            "  uv run scripts/manage_tickers.py add AAPL MSFT NVDA\n"
            "  uv run scripts/manage_tickers.py add --csv data/new_tickers.csv\n"
            "  uv run scripts/manage_tickers.py add AAPL --force --skip-estimates\n"
            "  uv run scripts/manage_tickers.py delete GME BB\n"
            "  uv run scripts/manage_tickers.py delete --csv data/delisted.csv\n"
            "  uv run scripts/manage_tickers.py add AAPL --dry-run\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # -- add subcommand
    add_p = sub.add_parser(
        "add",
        help="Fully onboard new tickers (~8 AV API calls each)",
        description=(
            "Add one or more tickers to all three databases:\n"
            "  prices.duckdb, av_financials.duckdb, historic_fundamentals.duckdb\n\n"
            "The full pipeline runs automatically: price backfill, financial statements,\n"
            "company overview, PE timeseries, analyst estimates, and forward multiples."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run scripts/manage_tickers.py add AAPL MSFT\n"
            "  uv run scripts/manage_tickers.py add --csv data/new_tickers.csv\n"
            "  uv run scripts/manage_tickers.py add AAPL --force\n"
            "  uv run scripts/manage_tickers.py add AAPL --skip-estimates --dry-run\n"
        ),
    )
    add_p.add_argument("tickers", nargs="*", metavar="TICKER", help="One or more ticker symbols")
    add_p.add_argument("--csv", metavar="FILE", help="CSV file with tickers in first column")
    add_p.add_argument("--force", action="store_true", help="Re-import even if already in AV database")
    add_p.add_argument("--skip-estimates", action="store_true", help="Skip EARNINGS_ESTIMATES API call")
    add_p.add_argument("--dry-run", action="store_true", help="Print plan without modifying any database")
    add_p.add_argument("--verbose", action="store_true", help="Show DEBUG-level output")

    # -- delete subcommand
    del_p = sub.add_parser(
        "delete",
        help="Remove tickers from all three databases (no AV API calls)",
        description=(
            "Delete one or more tickers from all three databases:\n"
            "  prices.duckdb, av_financials.duckdb, historic_fundamentals.duckdb\n\n"
            "Use this for delisted tickers or tickers no longer in the model universe.\n"
            "This operation is irreversible — re-run 'add' to restore a ticker."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run scripts/manage_tickers.py delete GME BB AMC\n"
            "  uv run scripts/manage_tickers.py delete --csv data/delisted.csv\n"
            "  uv run scripts/manage_tickers.py delete AAPL --dry-run\n"
        ),
    )
    del_p.add_argument("tickers", nargs="*", metavar="TICKER", help="One or more ticker symbols")
    del_p.add_argument("--csv", metavar="FILE", help="CSV file with tickers in first column")
    del_p.add_argument("--dry-run", action="store_true", help="Print plan without modifying any database")
    del_p.add_argument("--verbose", action="store_true", help="Show DEBUG-level output")

    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.csv:
        tickers = _tickers_from_csv(args.csv)
        if not tickers:
            log.error("No tickers found in %s", args.csv)
            return 2
        log.info("Loaded %d tickers from %s", len(tickers), args.csv)
    elif args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        log.error("Provide tickers as arguments or use --csv FILE")
        return 2

    if args.command == "add":
        return cmd_add(args, tickers)
    if args.command == "delete":
        return cmd_delete(args, tickers)

    log.error("Unknown command: %s", args.command)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
