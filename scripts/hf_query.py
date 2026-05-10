#!/usr/bin/env python3
"""
Query historic PE fundamentals from data/historic_fundamentals.duckdb.

Usage:
    uv run scripts/hf_query.py AAPL                                   # PE stats snapshot
    uv run scripts/hf_query.py AAPL MSFT GOOGL                        # multiple tickers
    uv run scripts/hf_query.py --all                                   # all tickers
    uv run scripts/hf_query.py AAPL --view timeseries                 # full monthly PE history
    uv run scripts/hf_query.py AAPL --view timeseries --start 2020-01-01 --end 2024-12-31
    uv run scripts/hf_query.py AAPL --view estimates                   # analyst estimates
    uv run scripts/hf_query.py --all --out pe_stats.csv               # export all stats to CSV

Options:
    --view   stats        PE statistics snapshot per ticker (default)
             timeseries   Monthly PE history with rolling 5yr median
             estimates    Latest analyst EPS and revenue estimates
    --all                 Query all tickers in the DB
    --start  YYYY-MM-DD   Start date filter (timeseries only)
    --end    YYYY-MM-DD   End date filter (timeseries only)
    --out    FILE         Write output to CSV instead of stdout
    --db     PATH         Override data/historic_fundamentals.duckdb path

Columns returned per view:
    stats       ticker, current_pe, lt_median, p25, p75, p10, p90,
                rolling_5yr_median, forward_pe, forward_12m_eps,
                current_ttm_eps, months_available, updated_at
    timeseries  ticker, month_end_date, price, ttm_eps, pe_ratio,
                rolling_5yr_median, ttm_source (quarterly|annual)
    estimates   ticker, fiscal_date, horizon, eps_avg/high/low,
                eps_count, rev_avg/high/low, fetched_at
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from historic_fundamentals.db import DEFAULT_DB_PATH, HistoricFundamentalsDB  # noqa: E402

log = logging.getLogger(__name__)


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query historic PE fundamentals and analyst estimates.",
    )
    parser.add_argument("tickers", nargs="*", metavar="TICKER", help="One or more ticker symbols")
    parser.add_argument("--all", action="store_true", help="Query all tickers in the DB")
    parser.add_argument(
        "--view", choices=["stats", "timeseries", "estimates"], default="stats",
        help="What to show: stats (default), timeseries, or estimates",
    )
    parser.add_argument("--start", metavar="YYYY-MM-DD", help="Start date for timeseries (inclusive)")
    parser.add_argument("--end",   metavar="YYYY-MM-DD", help="End date for timeseries (inclusive)")
    parser.add_argument("--out",   metavar="FILE", help="Write output to CSV instead of stdout")
    parser.add_argument("--db",    metavar="PATH", help="Override DB path")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    return parser.parse_args()


def _display(df: pd.DataFrame, out: str | None) -> None:
    if out:
        df.to_csv(out, index=False)
        log.info("Wrote %d rows to %s", len(df), out)
    else:
        print(df.to_string(index=False))


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.all and not args.tickers:
        print("Provide ticker symbols or use --all", file=sys.stderr)
        return 2

    db_path = args.db or os.getenv("HF_DB_PATH") or DEFAULT_DB_PATH
    db = HistoricFundamentalsDB(db_path)

    try:
        if args.all:
            tickers = db.list_tickers()
            if not tickers:
                print("No tickers in DB. Run hf_import.py first.", file=sys.stderr)
                return 1
        else:
            tickers = [t.upper() for t in args.tickers]

        if args.view == "stats":
            df = db.query_pe_stats(tickers if not args.all else None)
            if df.empty:
                print(f"No stats found for {', '.join(tickers)}", file=sys.stderr)
                return 1
            cols = [
                "ticker", "current_pe", "lt_median",
                "p25", "p75", "p10", "p90",
                "rolling_5yr_median", "forward_pe", "forward_12m_eps",
                "current_ttm_eps", "months_available", "updated_at",
            ]
            _display(df[[c for c in cols if c in df.columns]], args.out)

        elif args.view == "timeseries":
            df = db.query_pe_timeseries(
                tickers,
                start_date=_parse_date(args.start),
                end_date=_parse_date(args.end),
            )
            if df.empty:
                print(f"No timeseries data found for {', '.join(tickers)}", file=sys.stderr)
                return 1
            cols = [
                "ticker", "month_end_date", "price", "ttm_eps",
                "pe_ratio", "rolling_5yr_median", "ttm_source",
            ]
            _display(df[[c for c in cols if c in df.columns]], args.out)

        elif args.view == "estimates":
            df = db.query_estimates(tickers)
            if df.empty:
                print(f"No estimates found for {', '.join(tickers)}", file=sys.stderr)
                return 1
            # Show latest snapshot per (ticker, fiscal_date, horizon) only
            df = (
                df.sort_values("fetched_at", ascending=False)
                  .groupby(["ticker", "fiscal_date", "horizon"], sort=False)
                  .first()
                  .reset_index()
                  .sort_values(["ticker", "fiscal_date"])
            )
            cols = [
                "ticker", "fiscal_date", "horizon",
                "eps_avg", "eps_high", "eps_low", "eps_count",
                "rev_avg", "rev_high", "rev_low", "fetched_at",
            ]
            _display(df[[c for c in cols if c in df.columns]], args.out)

    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
