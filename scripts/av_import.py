#!/usr/bin/env python3
"""
Download Alpha Vantage financial statements into data/av_financials.duckdb.

Source (pick one):
    uv run scripts/av_import.py AAPL [MSFT ...]     # one or more tickers
    uv run scripts/av_import.py --csv FILE          # first column of a CSV file
    uv run scripts/av_import.py --from-prices-db    # all tickers from prices.duckdb

Options (work with any source):
    --force     Re-fetch and overwrite tickers already in the DB.
                Without this, existing tickers are skipped.
    --verbose   Show DEBUG-level output (individual API call details).
    --db PATH   Use a different DuckDB file instead of data/av_financials.duckdb.

Examples:
    uv run scripts/av_import.py AAPL MSFT GOOGL
    uv run scripts/av_import.py --csv data/test_tickers.csv --force
    uv run scripts/av_import.py --from-prices-db --verbose
    uv run scripts/av_import.py AAPL --force --verbose --db data/custom.duckdb
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH, AVFinancialsDB, RateLimiter  # noqa: E402

log = logging.getLogger(__name__)


def _tickers_from_csv(path: str) -> list[str]:
    tickers: list[str] = []
    with open(path) as f:
        for line in f:
            val = line.split(",")[0].strip().strip('"').upper()
            if val and not val.startswith("#"):
                tickers.append(val)
    # Drop header if first value looks like a label rather than a ticker
    if tickers and not tickers[0].isalpha():
        tickers = tickers[1:]
    return tickers


def _tickers_from_prices_db(prices_db_path: str) -> list[str]:
    conn = duckdb.connect(prices_db_path, read_only=True)
    try:
        rows = conn.execute("SELECT DISTINCT ticker FROM stocks ORDER BY ticker").fetchall()
        return [r[0] for r in rows if r[0]]
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Alpha Vantage financial statements.")
    parser.add_argument("tickers", nargs="*", metavar="TICKER", help="One or more ticker symbols")
    parser.add_argument("--csv", metavar="FILE", help="CSV file with tickers in the first column")
    parser.add_argument("--from-prices-db", action="store_true", help="Import all tickers from prices.duckdb")
    parser.add_argument("--force", action="store_true", help="Re-import tickers already in the DB")
    parser.add_argument("--db", default=None, metavar="PATH", help="Override DB path")
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

    # Resolve ticker list (tickers, --csv, and --from-prices-db are mutually exclusive)
    sources = sum([bool(args.tickers), bool(args.csv), args.from_prices_db])
    if sources > 1:
        log.error("Provide only one of: tickers, --csv, or --from-prices-db")
        return 2

    if args.csv:
        tickers = _tickers_from_csv(args.csv)
        if not tickers:
            log.error("No tickers found in %s", args.csv)
            return 2
        log.info("Loaded %d tickers from %s", len(tickers), args.csv)
    elif args.from_prices_db:
        prices_db = os.getenv("PRICES_DB_PATH")
        if not prices_db:
            log.error("PRICES_DB_PATH not set in .env")
            return 2
        tickers = _tickers_from_prices_db(prices_db)
        if not tickers:
            log.error("No tickers found in %s", prices_db)
            return 2
        log.info("Loaded %d tickers from prices.duckdb", len(tickers))
    else:
        tickers = [t.upper() for t in args.tickers]
        if not tickers:
            log.error("Provide tickers, --csv, or --from-prices-db")
            return 2

    db = AVFinancialsDB(db_path)
    limiter = RateLimiter()

    succeeded = 0
    skipped = 0
    failed = 0
    total_rows = 0

    try:
        for i, ticker in enumerate(tickers, 1):
            prefix = f"[{i}/{len(tickers)}]"

            if not args.force and db.has_ticker(ticker):
                log.info("%s %s — skipped (already in DB; use --force to re-import)", prefix, ticker)
                skipped += 1
                continue

            try:
                rows = db.import_ticker(ticker, api_key, limiter)
                total_rows += rows
                succeeded += 1
                log.info("%s %s — done (%d rows)", prefix, ticker, rows)
            except Exception as exc:
                log.error("%s %s — failed: %s", prefix, ticker, exc)
                failed += 1

    finally:
        db.close()

    log.info(
        "Import complete: %d succeeded, %d skipped, %d failed, %d total rows",
        succeeded, skipped, failed, total_rows,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
