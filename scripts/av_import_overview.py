#!/usr/bin/env python3
"""
Fetch and store Alpha Vantage Company Overview for all tickers in av_financials.duckdb.

Stores one snapshot per (ticker, date) for historical tracking. Skips tickers already
fetched this calendar month unless --force is specified.

Usage:
    uv run scripts/av_import_overview.py             # all tickers, skip if fetched this month
    uv run scripts/av_import_overview.py --ticker AAPL
    uv run scripts/av_import_overview.py --force     # re-fetch even if fetched this month
    uv run scripts/av_import_overview.py --db PATH --verbose

Rate: 1 AV API call per ticker. ~19 min for 1,400 tickers at 75 calls/min.
After running, execute hf_update.py to refresh derived metrics in historic_fundamentals.duckdb.
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
    parser = argparse.ArgumentParser(description="Import Alpha Vantage Company Overview for all tickers.")
    parser.add_argument("--ticker",  metavar="TICKER", help="Import a single ticker instead of all")
    parser.add_argument("--force",   action="store_true", help="Re-fetch even if already fetched this month")
    parser.add_argument("--db",      metavar="PATH",   help="Override DB path")
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

    tickers = [args.ticker.upper()] if args.ticker else db.list_tickers()
    if not tickers:
        log.warning("No tickers in DB. Run av_import.py first.")
        db.close()
        return 1

    log.info("Importing overview for %d ticker(s) (force=%s)", len(tickers), args.force)

    limiter = RateLimiter()
    ok = skipped = failed = 0

    try:
        for i, ticker in enumerate(tickers, 1):
            prefix = f"[{i}/{len(tickers)}]"

            if not args.force and db.has_overview_this_month(ticker):
                log.debug("%s %s — skipped (already fetched this month)", prefix, ticker)
                skipped += 1
                continue

            try:
                db.import_company_overview(ticker, api_key, limiter)
                log.info("%s %s — ok", prefix, ticker)
                ok += 1
            except Exception as exc:
                log.error("%s %s — failed: %s", prefix, ticker, exc)
                failed += 1
    finally:
        db.close()

    log.info("Done: %d ok, %d skipped, %d failed", ok, skipped, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
