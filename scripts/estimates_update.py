#!/usr/bin/env python3
"""
Weekly update of analyst EPS and revenue estimates for all tickers.

Fetches AV EARNINGS_ESTIMATES for every ticker in historic_fundamentals.duckdb
and upserts new time-series snapshots into the earnings_estimates table.
Each run adds a new fetched_at snapshot, preserving history for trend analysis.

Usage:
    uv run scripts/estimates_update.py                  # all tickers
    uv run scripts/estimates_update.py --ticker AAPL    # single ticker
    uv run scripts/estimates_update.py --dry-run        # fetch but don't write
    uv run scripts/estimates_update.py --verbose

Cron (weekly, Monday 6 AM):
    0 6 * * 1 cd /home/pedro/projects/fin_import2 && uv run scripts/estimates_update.py >> logs/estimates_update.log 2>&1
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import RateLimiter  # noqa: E402
from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH, HistoricFundamentalsDB  # noqa: E402
from historic_fundamentals.estimates import fetch_estimates, normalize_estimates  # noqa: E402

log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly analyst estimates update.")
    parser.add_argument("--ticker", help="Update a single ticker instead of all")
    parser.add_argument("--db", default=str(HF_DB_PATH), help="Path to historic_fundamentals.duckdb")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but do not write to DB")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    load_dotenv(ROOT / ".env", override=True)
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        log.error("ALPHA_VANTAGE_API_KEY not set in .env")
        return 2

    hf_db = HistoricFundamentalsDB(args.db)
    tickers = [args.ticker.upper()] if args.ticker else hf_db.list_tickers()
    if not tickers:
        log.warning("No tickers found. Run hf_import.py first.")
        hf_db.close()
        return 1

    log.info("Updating estimates for %d ticker(s) (dry_run=%s)", len(tickers), args.dry_run)
    limiter = RateLimiter()
    ok = failed = 0

    for i, ticker in enumerate(tickers, 1):
        prefix = f"[{i}/{len(tickers)}]"
        try:
            raw = fetch_estimates(ticker, api_key, limiter)
            rows = normalize_estimates(ticker, raw)
            if args.dry_run:
                log.info("%s %s — would write %d rows", prefix, ticker, len(rows))
            else:
                hf_db.upsert_estimates(ticker, rows)
                log.info("%s %s — wrote %d rows", prefix, ticker, len(rows))
            ok += 1
        except Exception as exc:
            log.error("%s %s — failed: %s", prefix, ticker, exc)
            failed += 1

    hf_db.close()
    log.info("Done: %d ok, %d failed", ok, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
