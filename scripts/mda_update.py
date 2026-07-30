#!/usr/bin/env python3
"""
Weekly update: check the latest 10-K + latest 10-Q for every ticker in av_financials.duckdb
and fetch MD&A only for filings not yet cached in mda_filings.duckdb.

Intended to run once per week (e.g. Sunday night via cron) — companies file 10-Qs on a
staggered calendar year-round, so a weekly check is needed to catch new quarters promptly.
Most tickers will have nothing new; the underlying cache check (fetch_all_mda_for_ticker)
skips already-cached filings automatically.

Usage:
    uv run scripts/mda_update.py
    uv run scripts/mda_update.py --ticker AAPL
    uv run scripts/mda_update.py --dry-run
    uv run scripts/mda_update.py --db PATH --verbose

Options:
    --ticker TICKER   Process a single ticker instead of all
    --dry-run         Report how many new filings would be fetched, without fetching content
    --db PATH         Override mda_filings.duckdb path
    --verbose         Show DEBUG-level output
"""

import argparse
import logging
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH as AV_DB_PATH  # noqa: E402
from historic_fundamentals.mda import (  # noqa: E402
    DEFAULT_DB_PATH as MDA_DB_PATH,
    fetch_all_mda_for_ticker,
    open_db,
)

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Weekly refresh of MD&A filings from SEC EDGAR.")
    p.add_argument("--ticker",  metavar="TICKER", help="Process a single ticker")
    p.add_argument("--dry-run", action="store_true",
                   help="Report new-filing counts without fetching content")
    p.add_argument("--db",      metavar="PATH", help="Override mda_filings.duckdb path")
    p.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    return p.parse_args()


def get_universe_tickers(av_conn: duckdb.DuckDBPyConnection, ticker: str | None) -> list[str]:
    if ticker:
        return [ticker.upper()]
    rows = av_conn.execute("SELECT DISTINCT ticker FROM company_overview ORDER BY ticker").fetchall()
    return [r[0] for r in rows]


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env", override=True)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    av_conn = duckdb.connect(str(AV_DB_PATH), read_only=True)
    tickers = get_universe_tickers(av_conn, args.ticker)
    av_conn.close()

    if not tickers:
        log.error("No tickers found in av_financials.duckdb")
        return 1

    log.info("Checking %d tickers for new 10-K/10-Q MD&A", len(tickers))

    db_path = Path(args.db) if args.db else MDA_DB_PATH
    conn = open_db(db_path)

    totals = {"10-K": {"ok": 0, "empty": 0, "error": 0, "skipped": 0, "new": 0},
              "10-Q": {"ok": 0, "empty": 0, "error": 0, "skipped": 0, "new": 0}}

    for ticker in tqdm(tickers, desc="MD&A update", unit="ticker"):
        try:
            summary = fetch_all_mda_for_ticker(
                ticker, n_annual=1, n_quarterly=1, conn=conn, dry_run=args.dry_run,
            )
            for form in ("10-K", "10-Q"):
                for status, count in summary[form].items():
                    totals[form][status] = totals[form].get(status, 0) + count
                    if not args.dry_run and status == "ok" and count:
                        log.info("New MD&A: %s %s", ticker, form)
        except Exception as exc:
            log.warning("Error processing %s: %s", ticker, exc)

    conn.close()

    if args.dry_run:
        new_total = totals["10-K"]["new"] + totals["10-Q"]["new"]
        log.info("Dry run — %d new filings would be fetched (10-K: %d, 10-Q: %d)",
                  new_total, totals["10-K"]["new"], totals["10-Q"]["new"])
    else:
        log.info("Done — 10-K: %s  10-Q: %s", totals["10-K"], totals["10-Q"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
