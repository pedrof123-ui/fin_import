#!/usr/bin/env python3
"""
Weekly update: check the latest 1-2 earnings call transcript quarters for every
ticker in av_financials.duckdb and fetch any that are not yet cached.

Intended to run once per week (e.g. Sunday night via cron).

Usage:
    uv run scripts/earnings_update.py
    uv run scripts/earnings_update.py --ticker AAPL
    uv run scripts/earnings_update.py --db PATH --verbose

Options:
    --ticker TICKER   Process a single ticker instead of all
    --db PATH         Override earnings_transcripts.duckdb path
    --verbose         Show DEBUG-level output

Rate: up to 2 AV calls per ticker at 75 calls/min.
Already-cached entries are skipped.
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
    p = argparse.ArgumentParser(description="Weekly refresh of earnings call transcripts.")
    p.add_argument("--ticker",  metavar="TICKER", help="Process a single ticker")
    p.add_argument("--db",      metavar="PATH",   help="Override earnings DB path")
    p.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    return p.parse_args()


def get_ticker_latest_quarters(av_conn: duckdb.DuckDBPyConnection, ticker: str | None) -> list[tuple[str, date, int]]:
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
    if not api_key:
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

    log.info("Checking %d tickers for new transcripts", len(ticker_dates))

    today = date.today()
    rate = RateLimiter(max_calls=75, period=60.0)

    fetched = skipped = not_found = errors = 0

    for symbol, latest_date, fy_end_month in tqdm(ticker_dates, desc="Update", unit="ticker"):
        # Check only the 2 most recent quarters — the lookahead + the latest in av_financials
        quarters = fiscal_date_to_quarters(latest_date, today, n_quarters=2, fy_end_month=fy_end_month)
        for quarter in quarters:
            if is_cached(earnings_conn, symbol, quarter):
                skipped += 1
                log.debug("%s %s already cached — skip", symbol, quarter)
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
                    log.info("New transcript: %s %s", symbol, quarter)
            except Exception as exc:
                errors += 1
                log.warning("Error fetching %s %s: %s", symbol, quarter, exc)

    earnings_conn.close()

    log.info(
        "Done — fetched: %d  skipped: %d  not_found: %d  errors: %d",
        fetched, skipped, not_found, errors,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
