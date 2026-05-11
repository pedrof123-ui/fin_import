#!/usr/bin/env python3
"""
Backfill shares_outstanding table in av_financials.duckdb.

Fetches SHARES_OUTSTANDING from Alpha Vantage for all tickers (or a subset)
and stores the diluted/basic share count timeseries.

Usage:
    uv run scripts/av_import_shares.py                   # all tickers in av_financials.duckdb
    uv run scripts/av_import_shares.py AAPL MSFT         # specific tickers
    uv run scripts/av_import_shares.py --force           # re-fetch even if data exists
    uv run scripts/av_import_shares.py --db PATH --verbose

Rate: 1 AV API call per ticker (~18 min for ~1400 tickers at 75/min).
After running, re-run hf_update.py --skip-estimates to refresh PE calculations.
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
    parser = argparse.ArgumentParser(description="Fetch shares_outstanding for all tickers.")
    parser.add_argument("tickers", nargs="*", metavar="TICKER")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if data already exists")
    parser.add_argument("--db", default=None, metavar="PATH")
    parser.add_argument("--verbose", action="store_true")
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
        log.error("ALPHA_VANTAGE_API_KEY not set in .env")
        return 2

    db_path = args.db or os.getenv("AV_DB_PATH") or DEFAULT_DB_PATH
    db = AVFinancialsDB(db_path)
    limiter = RateLimiter()

    tickers = [t.upper() for t in args.tickers] if args.tickers else db.list_tickers()
    if not tickers:
        log.error("No tickers found")
        db.close()
        return 2

    log.info("Fetching shares_outstanding for %d ticker(s)", len(tickers))

    already_have: set[str] = set()
    if not args.force:
        rows = db.conn.execute("SELECT DISTINCT ticker FROM shares_outstanding").fetchall()
        already_have = {r[0] for r in rows}

    ok = skipped = failed = 0
    try:
        for i, ticker in enumerate(tickers, 1):
            prefix = f"[{i}/{len(tickers)}]"
            if not args.force and ticker in already_have:
                log.debug("%s %s — skipped (already have data)", prefix, ticker)
                skipped += 1
                continue
            try:
                n = db.import_shares_outstanding(ticker, api_key, limiter)
                log.info("%s %s — %d rows", prefix, ticker, n)
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
