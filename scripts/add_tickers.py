#!/usr/bin/env python3
"""
DEPRECATED — use manage_tickers.py instead.

    uv run scripts/manage_tickers.py add AAPL MSFT GOOGL
    uv run scripts/manage_tickers.py add --csv data/new_tickers.csv

manage_tickers.py supersedes this script with goal prices, more forward
multiples (P/FCF, EV/EBITDA, P/S), a delete command, and --dry-run support.
"""
import sys

print(
    "ERROR: add_tickers.py is deprecated.\n"
    "Use: uv run scripts/manage_tickers.py add " + " ".join(sys.argv[1:]),
    file=sys.stderr,
)
sys.exit(1)

import argparse
import logging
import os
import sys
from datetime import datetime as _dt
from pathlib import Path

import duckdb
import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH as AV_DB_PATH, AVFinancialsDB, RateLimiter  # noqa: E402
from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH, HistoricFundamentalsDB  # noqa: E402
from historic_fundamentals.pe import process_ticker  # noqa: E402
from historic_fundamentals.estimates import fetch_estimates, normalize_estimates, compute_forward_eps, compute_ntm_revenue  # noqa: E402

log = logging.getLogger(__name__)

_AV_URL = "https://www.alphavantage.co/query"

_ETF_TICKERS: frozenset[str] = frozenset({
    "SPY", "IWM", "IWN", "MDY", "VTI",
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
    "GLD", "SLV", "USO", "CPER", "SDS", "SH", "RWM", "TWM", "SGOV", "SHV",
})

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
    FROM _batch
ON CONFLICT (ticker, date) DO UPDATE SET
    open = excluded.open, high = excluded.high, low = excluded.low,
    close = excluded.close, adj_close = excluded.adj_close, volume = excluded.volume
"""


def _ticker_has_prices(ticker: str, prices_conn) -> bool:
    try:
        return prices_conn.execute(
            "SELECT 1 FROM stock_prices WHERE ticker = ? LIMIT 1", [ticker]
        ).fetchone() is not None
    except Exception:
        return False


def _import_prices(ticker: str, prices_db_path: str, api_key: str, limiter) -> int:
    """Fetch full AV price history and upsert into prices.duckdb. Returns rows upserted."""
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
            raise RuntimeError(f"AV [TIME_SERIES_DAILY_ADJUSTED] {data[key]}")
    if "Time Series (Daily)" not in data:
        raise ValueError(f"Unexpected AV response for {ticker}: {list(data.keys())}")
    rows = []
    for date_str, v in data["Time Series (Daily)"].items():
        adj = float(v["5. adjusted close"])
        rows.append({
            "ticker": ticker,
            "date": _dt.strptime(date_str, "%Y-%m-%d").date(),
            "open": float(v["1. open"]),
            "high": float(v["2. high"]),
            "low": float(v["3. low"]),
            "close": adj,
            "adj_close": adj,
            "volume": int(v["6. volume"]),
        })
    if not rows:
        log.warning("%s: no price data returned from AV", ticker)
        return 0
    df = pd.DataFrame(rows)
    table = "etf_prices" if ticker in _ETF_TICKERS else "stock_prices"
    conn = duckdb.connect(prices_db_path)
    try:
        conn.execute(_PRICES_INIT_SQL.format(table=table))
        conn.register("_batch", df)
        conn.execute(_PRICES_UPSERT_SQL.format(table=table))
    finally:
        conn.close()
    return len(rows)


def _tickers_from_csv(path: str) -> list[str]:
    tickers: list[str] = []
    with open(path) as f:
        for line in f:
            val = line.split(",")[0].strip().strip('"').upper()
            if val and not val.startswith("#"):
                tickers.append(val)
    if tickers and not tickers[0].isalpha():
        tickers = tickers[1:]
    return tickers


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


def _update_market_cap(hf_db: HistoricFundamentalsDB, av_db, prices_conn, ticker: str) -> None:
    row = prices_conn.execute(
        "SELECT adj_close FROM stock_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    price = row[0] if row else None
    if not price:
        hf_db.update_market_cap(ticker, None)
        return
    row = av_db.conn.execute("""
        SELECT shares_outstanding_diluted FROM shares_outstanding
        WHERE ticker = ? AND shares_outstanding_diluted IS NOT NULL
        ORDER BY date DESC LIMIT 1
    """, [ticker]).fetchone()
    if not row:
        row = av_db.conn.execute("""
            SELECT common_stock_shares_outstanding FROM balance_sheets
            WHERE ticker = ? AND period_type = 'quarterly'
                AND common_stock_shares_outstanding IS NOT NULL
            ORDER BY fiscal_date_ending DESC LIMIT 1
        """, [ticker]).fetchone()
    shares = row[0] if row else None
    market_cap_b = (price * shares / 1e9) if shares and shares > 0 else None
    hf_db.update_market_cap(ticker, market_cap_b)


def _update_rev_ntm_growth_est(hf_db: HistoricFundamentalsDB, av_db, ticker: str) -> None:
    ntm_rev = compute_ntm_revenue(hf_db.conn, ticker)
    if ntm_rev is None:
        hf_db.update_rev_ntm_growth_est(ticker, None)
        return
    row = av_db.conn.execute("""
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add new tickers: fetch all AV data and compute all derived metrics."
    )
    parser.add_argument("tickers", nargs="*", metavar="TICKER")
    parser.add_argument("--csv", metavar="FILE", help="CSV file with tickers in first column")
    parser.add_argument("--force", action="store_true", help="Re-import even if already in DB")
    parser.add_argument("--skip-estimates", action="store_true", help="Skip EARNINGS_ESTIMATES calls")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        log.error("ALPHA_VANTAGE_API_KEY not found in .env")
        return 2

    prices_db_path = os.getenv("PRICES_DB_PATH")
    if not prices_db_path:
        log.error("PRICES_DB_PATH not set in .env")
        return 2

    av_db_path = os.getenv("AV_DB_PATH") or AV_DB_PATH
    hf_db_path = os.getenv("HF_DB_PATH") or HF_DB_PATH

    if args.csv:
        tickers = _tickers_from_csv(args.csv)
        if not tickers:
            log.error("No tickers found in %s", args.csv)
            return 2
        log.info("Loaded %d tickers from %s", len(tickers), args.csv)
    elif args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        log.error("Provide tickers or --csv")
        return 2

    av_db = AVFinancialsDB(av_db_path)
    prices_conn = duckdb.connect(prices_db_path, read_only=True)
    hf_db = HistoricFundamentalsDB(hf_db_path)
    limiter = RateLimiter()

    ok = failed = skipped = 0

    try:
        for i, ticker in enumerate(tickers, 1):
            prefix = f"[{i}/{len(tickers)}]"

            # ── Step 1-3: AV raw data ──────────────────────────────────────────
            if not args.force and av_db.has_ticker(ticker):
                log.info("%s %s — AV data already present (use --force to re-fetch)", prefix, ticker)
                skipped += 1
            else:
                ticker_ok = True
                try:
                    rows = av_db.import_ticker(ticker, api_key, limiter)
                    log.debug("%s %s — statements: %d rows", prefix, ticker, rows)
                except Exception as exc:
                    log.error("%s %s — statements failed: %s", prefix, ticker, exc)
                    ticker_ok = False

                try:
                    n = av_db.import_shares_outstanding(ticker, api_key, limiter)
                    log.debug("%s %s — shares: %d rows", prefix, ticker, n)
                except Exception as exc:
                    log.error("%s %s — shares failed: %s", prefix, ticker, exc)
                    ticker_ok = False

                try:
                    n = av_db.import_dividends(ticker, api_key, limiter)
                    log.debug("%s %s — dividends: %d rows", prefix, ticker, n)
                except Exception as exc:
                    log.error("%s %s — dividends failed: %s", prefix, ticker, exc)
                    ticker_ok = False

                # ── Step 4: Company Overview ───────────────────────────────────
                if not args.force and av_db.has_overview_this_month(ticker):
                    log.debug("%s %s — overview already fetched this month", prefix, ticker)
                else:
                    try:
                        av_db.import_company_overview(ticker, api_key, limiter)
                        log.debug("%s %s — overview: ok", prefix, ticker)
                    except Exception as exc:
                        log.warning("%s %s — overview failed (non-fatal): %s", prefix, ticker, exc)

                if not ticker_ok:
                    log.error("%s %s — AV import failed; skipping derived metrics", prefix, ticker)
                    failed += 1
                    continue

            # ── Step 5: Price history ──────────────────────────────────────────
            if args.force or not _ticker_has_prices(ticker, prices_conn):
                try:
                    n = _import_prices(ticker, prices_db_path, api_key, limiter)
                    log.debug("%s %s — prices: %d rows", prefix, ticker, n)
                except Exception as exc:
                    log.error("%s %s — price import failed: %s", prefix, ticker, exc)
                    failed += 1
                    continue
            else:
                log.debug("%s %s — prices already in DB", prefix, ticker)

            # ── Step 6: PE timeseries ──────────────────────────────────────────
            try:
                monthly_pe, stats = process_ticker(ticker, av_db.conn, prices_conn)
                if monthly_pe.empty:
                    log.warning("%s %s — no PE data computed (missing financials or prices?)", prefix, ticker)
                else:
                    hf_db.upsert_monthly_pe(ticker, monthly_pe)
                    if stats:
                        hf_db.upsert_pe_stats(stats)
                    log.debug("%s %s — PE: %d months", prefix, ticker, len(monthly_pe))
            except Exception as exc:
                log.error("%s %s — PE computation failed: %s", prefix, ticker, exc)
                failed += 1
                continue

            # ── Step 7-8: Estimates + forward PE ──────────────────────────────
            if not args.skip_estimates:
                try:
                    raw = fetch_estimates(ticker, api_key, limiter)
                    est_rows = normalize_estimates(ticker, raw)
                    hf_db.upsert_estimates(ticker, est_rows)
                    _update_forward_pe(hf_db, prices_conn, ticker)
                    _update_rev_ntm_growth_est(hf_db, av_db, ticker)
                    _update_earn_ntm_growth_est(hf_db, ticker)
                    _update_market_cap(hf_db, av_db, prices_conn, ticker)
                    log.debug("%s %s — estimates: %d rows", prefix, ticker, len(est_rows))
                except Exception as exc:
                    log.error("%s %s — estimates failed: %s", prefix, ticker, exc)
                    failed += 1
                    continue

            ok += 1
            log.info("%s %s — done", prefix, ticker)

    finally:
        av_db.close()
        prices_conn.close()
        hf_db.close()

    log.info("Done: %d ok, %d skipped (already in DB), %d failed", ok, skipped, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
