#!/usr/bin/env python3
"""
One-time backfill: fetch the latest 4 earnings call transcript quarters for every
ticker in av_financials.duckdb and store them in earnings_transcripts.duckdb.

Resume-safe: already-cached (symbol, quarter) pairs are skipped automatically.

Usage:
    uv run scripts/earnings_backfill.py
    uv run scripts/earnings_backfill.py --ticker AAPL
    uv run scripts/earnings_backfill.py --dry-run
    uv run scripts/earnings_backfill.py --quarters 8

Options:
    --ticker TICKER   Process a single ticker instead of all
    --quarters N      Number of recent quarters to attempt per ticker (default: 4)
    --dry-run         Print what would be fetched without making API calls
    --db PATH         Override earnings_transcripts.duckdb path
    --verbose         Show DEBUG-level output

Rate: up to N calls per ticker at 75 calls/min (AV limit).
Already-cached entries are skipped; the script is safe to re-run.
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH as AV_DB_PATH, RateLimiter  # noqa: E402
from historic_fundamentals.earnings_transcripts import (  # noqa: E402
    DEFAULT_DB_PATH as EARNINGS_DB_PATH,
    fetch_from_av,
    fiscal_date_to_quarters,
    is_cached,
    open_db,
    save_transcript,
)

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill earnings call transcripts from Alpha Vantage.")
    p.add_argument("--ticker",   metavar="TICKER", help="Process a single ticker")
    p.add_argument("--quarters", type=int, default=4, metavar="N",
                   help="Quarters of history per ticker (default: 4)")
    p.add_argument("--dry-run",  action="store_true", help="Print plan without fetching")
    p.add_argument("--db",       metavar="PATH", help="Override earnings DB path")
    p.add_argument("--verbose",  action="store_true", help="Enable DEBUG logging")
    return p.parse_args()


def get_ticker_latest_quarters(av_conn: duckdb.DuckDBPyConnection, ticker: str | None) -> list[tuple[str, date, int]]:
    """Return [(ticker, latest_fiscal_date_ending, fy_end_month)] from av_financials."""
    where = "AND ticker = ?" if ticker else ""
    t = ticker.upper() if ticker else None
    params = [t, t] if t else []
    rows = av_conn.execute(
        f"""
        WITH q AS (
            SELECT ticker, MAX(fiscal_date_ending) AS latest_date
            FROM income_statements WHERE period_type = 'quarterly' {where}
            GROUP BY ticker
        ),
        a AS (
            SELECT ticker, MONTH(MAX(fiscal_date_ending)) AS fy_end_month
            FROM income_statements WHERE period_type = 'annual' {where}
            GROUP BY ticker
        )
        SELECT q.ticker, q.latest_date, COALESCE(a.fy_end_month, 12)
        FROM q LEFT JOIN a ON q.ticker = a.ticker
        ORDER BY q.ticker
        """,
        params,
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows if row[1] is not None]


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env", override=True)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key and not args.dry_run:
        log.error("ALPHA_VANTAGE_API_KEY not set")
        return 1

    db_path = Path(args.db) if args.db else EARNINGS_DB_PATH
    earnings_conn = open_db(db_path)
    av_conn = duckdb.connect(str(AV_DB_PATH), read_only=True)

    ticker_dates = get_ticker_latest_quarters(av_conn, args.ticker)
    av_conn.close()

    if not ticker_dates:
        log.error("No tickers found in av_financials.duckdb")
        return 1

    log.info("Processing %d tickers, up to %d quarters each", len(ticker_dates), args.quarters)

    today = date.today()
    rate = RateLimiter(max_calls=75, period=60.0)

    fetched = skipped = not_found = errors = 0

    for symbol, latest_date, fy_end_month in tqdm(ticker_dates, desc="Backfill", unit="ticker"):
        quarters = fiscal_date_to_quarters(latest_date, today, args.quarters, fy_end_month)
        for quarter in quarters:
            if is_cached(earnings_conn, symbol, quarter):
                skipped += 1
                log.debug("%s %s already cached — skip", symbol, quarter)
                continue

            if args.dry_run:
                print(f"WOULD FETCH  {symbol:8s}  {quarter}")
                continue

            rate.wait()
            try:
                result = fetch_from_av(symbol, quarter, api_key)
                if result is None:
                    not_found += 1
                    log.debug("%s %s not found on AV", symbol, quarter)
                else:
                    transcript_text, api_json = result
                    save_transcript(earnings_conn, symbol, quarter, transcript_text, api_json)
                    fetched += 1
                    log.debug("Saved %s %s", symbol, quarter)
            except Exception as exc:
                errors += 1
                log.warning("Error fetching %s %s: %s", symbol, quarter, exc)

    earnings_conn.close()

    if not args.dry_run:
        log.info(
            "Done — fetched: %d  skipped: %d  not_found: %d  errors: %d",
            fetched, skipped, not_found, errors,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
