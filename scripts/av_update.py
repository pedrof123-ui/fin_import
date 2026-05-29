#!/usr/bin/env python3
"""
Refresh all tickers in data/av_financials.duckdb with the latest Alpha Vantage data.

Fetches financial statements (income, balance, cashflow), shares outstanding,
dividend history, and company overview for every ticker in the database.

Usage:
    uv run scripts/av_update.py                    # update all tickers, all data
    uv run scripts/av_update.py --ticker AAPL      # single ticker
    uv run scripts/av_update.py --skip-shares      # skip SHARES_OUTSTANDING calls
    uv run scripts/av_update.py --skip-dividends   # skip DIVIDENDS calls
    uv run scripts/av_update.py --skip-overview    # skip OVERVIEW calls
    uv run scripts/av_update.py --db PATH --verbose

Rate: 6 AV API calls per ticker (3 statements + 1 shares + 1 dividends + 1 overview).
At 75 calls/min: ~115 min for ~1400 tickers.
After running, execute hf_update.py to recompute derived metrics in historic_fundamentals.duckdb.
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH, AVFinancialsDB, RateLimiter  # noqa: E402

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh all Alpha Vantage data for all tickers in DB.")
    parser.add_argument("--ticker",          metavar="TICKER", help="Update a single ticker instead of all")
    parser.add_argument("--skip-shares",     action="store_true", help="Skip SHARES_OUTSTANDING calls")
    parser.add_argument("--skip-dividends",  action="store_true", help="Skip DIVIDENDS calls")
    parser.add_argument("--skip-overview",   action="store_true", help="Skip OVERVIEW calls")
    parser.add_argument("--db",              metavar="PATH",   help="Override DB path")
    parser.add_argument("--verbose",         action="store_true", help="Enable DEBUG logging")
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_fmt = "%(asctime)s %(levelname)s %(message)s"
    log_datefmt = "%H:%M:%S"

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"av_update_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=log_level,
        format=log_fmt,
        datefmt=log_datefmt,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path),
        ],
    )
    log.info("Log file: %s", log_path)

    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        log.error("ALPHA_VANTAGE_API_KEY not found in .env")
        return 2

    db_path = args.db or os.getenv("AV_DB_PATH") or DEFAULT_DB_PATH
    db = AVFinancialsDB(db_path)

    tickers = [args.ticker.upper()] if args.ticker else db.list_tickers()
    if not tickers:
        log.warning("No tickers in DB. Run av_import.py first.")
        db.close()
        return 1

    phases = ["statements"]
    if not args.skip_shares:
        phases.append("shares")
    if not args.skip_dividends:
        phases.append("dividends")
    if not args.skip_overview:
        phases.append("overview")
    log.info("Updating %d ticker(s): %s", len(tickers), ", ".join(phases))

    limiter = RateLimiter()
    ok = failed = 0

    try:
        for i, ticker in enumerate(tickers, 1):
            prefix = f"[{i}/{len(tickers)}]"
            ticker_ok = True

            try:
                rows = db.import_ticker(ticker, api_key, limiter)
                log.debug("%s %s — statements: %d rows", prefix, ticker, rows)
            except Exception as exc:
                log.error("%s %s — statements failed: %s", prefix, ticker, exc)
                ticker_ok = False

            if not args.skip_shares:
                try:
                    n = db.import_shares_outstanding(ticker, api_key, limiter)
                    log.debug("%s %s — shares: %d rows", prefix, ticker, n)
                except Exception as exc:
                    log.error("%s %s — shares failed: %s", prefix, ticker, exc)
                    ticker_ok = False

            if not args.skip_dividends:
                try:
                    n = db.import_dividends(ticker, api_key, limiter)
                    log.debug("%s %s — dividends: %d rows", prefix, ticker, n)
                except Exception as exc:
                    log.error("%s %s — dividends failed: %s", prefix, ticker, exc)
                    ticker_ok = False

            if not args.skip_overview:
                try:
                    db.import_company_overview(ticker, api_key, limiter)
                    log.debug("%s %s — overview: ok", prefix, ticker)
                except Exception as exc:
                    log.error("%s %s — overview failed: %s", prefix, ticker, exc)
                    ticker_ok = False

            if ticker_ok:
                ok += 1
                log.info("%s %s — ok", prefix, ticker)
            else:
                failed += 1
                log.info("%s %s — partial failure (see errors above)", prefix, ticker)

    finally:
        db.close()

    log.info("Update complete: %d ok, %d failed", ok, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
