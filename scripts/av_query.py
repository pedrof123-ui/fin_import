#!/usr/bin/env python3
"""
Query Alpha Vantage financial statements and company overview from data/av_financials.duckdb.

Usage:
    uv run scripts/av_query.py AAPL
    uv run scripts/av_query.py AAPL MSFT --statement income --period annual
    uv run scripts/av_query.py AAPL --start 2020-01-01 --end 2024-12-31
    uv run scripts/av_query.py AAPL --statement balance --out aapl_balance.csv
    uv run scripts/av_query.py AAPL --overview                   # latest company overview snapshot
    uv run scripts/av_query.py AAPL --overview --history         # all monthly overview snapshots
    uv run scripts/av_query.py AAPL --verbose
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH, AVFinancialsDB  # noqa: E402

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query Alpha Vantage financial statements.")
    parser.add_argument("tickers", nargs="+", metavar="TICKER", help="One or more ticker symbols")
    parser.add_argument(
        "--statement", choices=["income", "balance", "cashflow", "all"], default="all",
        help="Statement type to retrieve (default: all)",
    )
    parser.add_argument(
        "--period", choices=["annual", "quarterly", "all"], default="all",
        help="Period type to retrieve (default: all)",
    )
    parser.add_argument("--start", metavar="YYYY-MM-DD", help="Start date (inclusive)")
    parser.add_argument("--end",   metavar="YYYY-MM-DD", help="End date (inclusive)")
    parser.add_argument("--overview", action="store_true", help="Show company overview instead of financial statements")
    parser.add_argument("--history",  action="store_true", help="With --overview: show all monthly snapshots instead of latest only")
    parser.add_argument("--out",   metavar="FILE", help="CSV output path (default: print to stdout)")
    parser.add_argument("--db",    metavar="PATH", help="Override DB path")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    return parser.parse_args()


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return date.fromisoformat(s)


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    db_path = args.db or os.getenv("AV_DB_PATH") or DEFAULT_DB_PATH
    tickers = [t.upper() for t in args.tickers]

    import pandas as pd  # noqa: PLC0415

    db = AVFinancialsDB(db_path)
    try:
        if args.overview:
            combined = db.query_company_overview(tickers, latest_only=not args.history)
        else:
            results = db.query(
                tickers=tickers,
                statement=args.statement,
                period_type=args.period,
                start_date=_parse_date(args.start),
                end_date=_parse_date(args.end),
            )
            frames = []
            for stmt_name, df in results.items():
                if not df.empty:
                    df = df.copy()
                    df.insert(0, "statement", stmt_name)
                    frames.append(df)
            combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    finally:
        db.close()

    if combined.empty:
        log.warning("No data found for %s", ", ".join(tickers))
        return 1

    if args.out:
        combined.to_csv(args.out, index=False)
        log.info("Wrote %d rows to %s", len(combined), args.out)
    else:
        print(combined.to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
