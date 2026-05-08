#!/usr/bin/env python3
"""
Refresh all tickers in data/av_financials.duckdb with the latest Alpha Vantage data.

Intended to run on a cron schedule (e.g., weekly after earnings season).

Usage:
    uv run scripts/av_update.py
    uv run scripts/av_update.py --ticker AAPL
    uv run scripts/av_update.py --db data/custom.duckdb --verbose
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH, AVFinancialsDB, RateLimiter  # noqa: E402

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Alpha Vantage financial statements for all tickers in DB.")
    parser.add_argument("--ticker", metavar="TICKER", help="Update a single ticker instead of all")
    parser.add_argument("--db",     metavar="PATH",   help="Override DB path")
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

    db_path = args.db or os.getenv("AV_DB_PATH") or DEFAULT_DB_PATH
    db = AVFinancialsDB(db_path)

    if args.ticker:
        tickers = [args.ticker.upper()]
    else:
        tickers = db.list_tickers()

    if not tickers:
        log.warning("No tickers in DB. Run av_import.py first.")
        db.close()
        return 1

    log.info("Updating %d ticker(s)", len(tickers))
    limiter = RateLimiter()

    succeeded = 0
    failed = 0
    total_rows = 0

    try:
        for i, ticker in enumerate(tickers, 1):
            prefix = f"[{i}/{len(tickers)}]"
            try:
                rows = db.import_ticker(ticker, api_key, limiter)
                total_rows += rows
                succeeded += 1
                log.info("%s %s — updated (%d rows)", prefix, ticker, rows)
            except Exception as exc:
                log.error("%s %s — failed: %s", prefix, ticker, exc)
                failed += 1
    finally:
        db.close()

    log.info(
        "Update complete: %d succeeded, %d failed, %d total rows upserted",
        succeeded, failed, total_rows,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
