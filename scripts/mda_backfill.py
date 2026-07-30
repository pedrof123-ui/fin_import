#!/usr/bin/env python3
"""
One-time backfill: fetch up to 20 years of 10-K MD&A + 20 quarters of 10-Q MD&A for every
ticker in av_financials.duckdb and store them in mda_filings.duckdb.

Resume-safe: already-cached (ticker, form, fiscal_period_end) rows are skipped automatically,
so the script can be Ctrl-C'd and re-run to pick up where it left off.

Usage:
    uv run scripts/mda_backfill.py
    uv run scripts/mda_backfill.py --ticker AAPL
    uv run scripts/mda_backfill.py --csv data/new_tickers.csv
    uv run scripts/mda_backfill.py --limit 10
    uv run scripts/mda_backfill.py --dry-run
    uv run scripts/mda_backfill.py --force

Options:
    --ticker TICKER   Process a single ticker instead of all
    --csv FILE        Process tickers from a CSV file (first column)
    --limit N         Process only the first N tickers (smoke-testing)
    --n-annual N      10-K filings to attempt per ticker (default: 20)
    --n-quarterly N   10-Q filings to attempt per ticker (default: 20)
    --force           Re-fetch even if already cached
    --dry-run         Print ticker/request-count plan without calling EDGAR
    --db PATH         Override mda_filings.duckdb path
    --verbose         Show DEBUG-level output

Rate: edgartools self-throttles to SEC's 9 requests/sec fair-access limit. Up to
(n_annual + n_quarterly + 2) requests per ticker — a full-universe run takes several hours.
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
from scripts.manage_tickers import _tickers_from_csv  # noqa: E402

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill MD&A text from SEC EDGAR.")
    p.add_argument("--ticker",      metavar="TICKER", help="Process a single ticker")
    p.add_argument("--csv",         metavar="FILE", help="CSV file with tickers in first column")
    p.add_argument("--limit",       type=int, metavar="N", help="Process only the first N tickers")
    p.add_argument("--n-annual",    type=int, default=20, metavar="N", help="10-K filings per ticker (default: 20)")
    p.add_argument("--n-quarterly", type=int, default=20, metavar="N", help="10-Q filings per ticker (default: 20)")
    p.add_argument("--force",       action="store_true", help="Re-fetch even if already cached")
    p.add_argument("--dry-run",     action="store_true", help="Print plan without calling EDGAR")
    p.add_argument("--db",          metavar="PATH", help="Override mda_filings.duckdb path")
    p.add_argument("--verbose",     action="store_true", help="Enable DEBUG logging")
    return p.parse_args()


def get_universe_tickers(av_conn: duckdb.DuckDBPyConnection) -> list[str]:
    rows = av_conn.execute(
        "SELECT DISTINCT ticker FROM company_overview ORDER BY ticker"
    ).fetchall()
    return [r[0] for r in rows]


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env", override=True)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.ticker:
        tickers = [args.ticker.upper()]
    elif args.csv:
        tickers = _tickers_from_csv(args.csv)
        if not tickers:
            log.error("No tickers found in %s", args.csv)
            return 1
    else:
        av_conn = duckdb.connect(str(AV_DB_PATH), read_only=True)
        tickers = get_universe_tickers(av_conn)
        av_conn.close()

    if args.limit:
        tickers = tickers[:args.limit]

    if not tickers:
        log.error("No tickers to process")
        return 1

    max_requests = len(tickers) * (args.n_annual + args.n_quarterly + 2)
    log.info(
        "Processing %d tickers, up to %d 10-K + %d 10-Q each (~%d EDGAR requests max)",
        len(tickers), args.n_annual, args.n_quarterly, max_requests,
    )

    if args.dry_run:
        for t in tickers:
            print(f"WOULD FETCH  {t}")
        return 0

    db_path = Path(args.db) if args.db else MDA_DB_PATH
    conn = open_db(db_path)

    totals = {"10-K": {"ok": 0, "empty": 0, "error": 0, "skipped": 0, "new": 0},
              "10-Q": {"ok": 0, "empty": 0, "error": 0, "skipped": 0, "new": 0}}

    for ticker in tqdm(tickers, desc="MD&A backfill", unit="ticker"):
        try:
            summary = fetch_all_mda_for_ticker(
                ticker, n_annual=args.n_annual, n_quarterly=args.n_quarterly,
                force=args.force, conn=conn,
            )
            for form in ("10-K", "10-Q"):
                for status, count in summary[form].items():
                    totals[form][status] = totals[form].get(status, 0) + count
            log.debug("%s: %s", ticker, summary)
        except Exception as exc:
            log.warning("Error processing %s: %s", ticker, exc)

    conn.close()

    log.info("Done — 10-K: %s  10-Q: %s", totals["10-K"], totals["10-Q"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
