#!/usr/bin/env python3
"""
Build monthly point-in-time snapshots of analyst estimate dispersion into
historic_fundamentals.duckdb's estimates_dispersion table.

For each calendar month present in earnings_estimates, takes each ticker's LAST
fetched_at snapshot within that month, picks its FY1/Q1 rows (see
historic_fundamentals.dispersion.select_horizons), and upserts one row per horizon
slot with month_end_date = the last day of that month. Idempotent — re-running
overwrites with identical values.

Stores raw estimate components (eps_avg/high/low/count, rev_avg/high/low/count,
revision counts) rather than derived dispersion ratios, so a future normalisation
(coverage-adjustment, winsorisation) can be recomputed from source without
re-fetching from Alpha Vantage. See PLAN_DISPERSION.md Phase 2.

Months whose largest single fetched_at snapshot covers fewer than MIN_TICKERS_PER_MONTH
tickers are skipped and logged — early months in earnings_estimates history are ad-hoc
single-ticker test runs, not real full-universe snapshots, and must not become a "month"
in the archive.

Usage:
    uv run scripts/build_dispersion_snapshots.py                # all months
    uv run scripts/build_dispersion_snapshots.py --month 2026-08 # one month
    uv run scripts/build_dispersion_snapshots.py --verbose
"""

from __future__ import annotations

import argparse
import logging
import sys
from calendar import monthrange
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH, HistoricFundamentalsDB  # noqa: E402
from historic_fundamentals.dispersion import select_horizons  # noqa: E402

log = logging.getLogger(__name__)

MIN_TICKERS_PER_MONTH = 500


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _list_months(db: HistoricFundamentalsDB) -> list[tuple[int, int]]:
    rows = db.conn.execute("""
        SELECT DISTINCT date_trunc('month', fetched_at) AS m
        FROM earnings_estimates
        ORDER BY m
    """).fetchall()
    return [(r[0].year, r[0].month) for r in rows]


def _build_month(db: HistoricFundamentalsDB, year: int, month: int) -> int:
    """Build (or refresh) the estimates_dispersion rows for one calendar month.

    "Latest snapshot" is per-ticker, not one shared batch timestamp: estimates_update.py
    stamps fetched_at = now() separately for each ticker as it's processed (a ~37-minute
    run across ~2,650 tickers has ~2,650 distinct fetched_at values, one per ticker), so
    there is no single fetched_at value that all — or even most — tickers share. Each
    ticker's own most-recent fetched_at within the month is what "current" means here.

    Returns the number of distinct tickers with a fetch in that month (0 if skipped).
    """
    month_end = _month_end(year, month)
    month_start = date(year, month, 1)

    ticker_count = db.conn.execute("""
        SELECT COUNT(DISTINCT ticker) FROM earnings_estimates
        WHERE date_trunc('month', fetched_at) = ?
    """, [month_start]).fetchone()[0]
    if ticker_count < MIN_TICKERS_PER_MONTH:
        log.info("Skipping %04d-%02d — only %d ticker(s) fetched this month (< %d)",
                  year, month, ticker_count, MIN_TICKERS_PER_MONTH)
        return 0

    df = db.conn.execute("""
        WITH latest_per_ticker AS (
            SELECT ticker, MAX(fetched_at) AS fetched_at
            FROM earnings_estimates
            WHERE date_trunc('month', fetched_at) = ?
            GROUP BY ticker
        )
        SELECT ee.ticker, ee.fiscal_date, ee.horizon, ee.fetched_at,
               ee.eps_avg, ee.eps_high, ee.eps_low, ee.eps_count, ee.eps_avg_30d,
               ee.eps_rev_up_30d, ee.eps_rev_down_30d, ee.rev_avg, ee.rev_high, ee.rev_low, ee.rev_count
        FROM earnings_estimates ee
        INNER JOIN latest_per_ticker lpt
            ON lpt.ticker = ee.ticker AND lpt.fetched_at = ee.fetched_at
    """, [month_start]).df()

    rows_out = []
    for ticker, group in df.groupby("ticker"):
        ticker_rows = group.to_dict("records")
        # DuckDB's .df() returns pandas Timestamps for DATE columns, but select_horizons
        # compares fiscal_date against datetime.date.today() — normalize before calling it.
        for r in ticker_rows:
            if r.get("fiscal_date") is not None:
                r["fiscal_date"] = r["fiscal_date"].date()
        picked = select_horizons(ticker_rows)
        for slot_name, slot_key in (("FY1", "fy1"), ("Q1", "q1")):
            r = picked[slot_key]
            if r is None:
                continue
            rows_out.append({
                "ticker": ticker,
                "month_end_date": month_end,
                "horizon_slot": slot_name,
                "fiscal_date": r.get("fiscal_date"),
                "snapshot_at": r.get("fetched_at"),
                "eps_avg": r.get("eps_avg"),
                "eps_high": r.get("eps_high"),
                "eps_low": r.get("eps_low"),
                "eps_count": r.get("eps_count"),
                "eps_avg_30d": r.get("eps_avg_30d"),
                "eps_rev_up_30d": r.get("eps_rev_up_30d"),
                "eps_rev_down_30d": r.get("eps_rev_down_30d"),
                "rev_avg": r.get("rev_avg"),
                "rev_high": r.get("rev_high"),
                "rev_low": r.get("rev_low"),
                "rev_count": r.get("rev_count"),
            })

    n = db.upsert_dispersion_snapshots(rows_out)
    log.info("%04d-%02d — %d rows from %d tickers (each at its own latest fetch that month)",
              year, month, n, ticker_count)
    return ticker_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Build monthly analyst-estimate dispersion snapshots.")
    parser.add_argument("--month", help="Single month to build, format YYYY-MM (default: all months)")
    parser.add_argument("--db", default=str(HF_DB_PATH), help="Path to historic_fundamentals.duckdb")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    db = HistoricFundamentalsDB(args.db)
    try:
        if args.month:
            year, month = (int(x) for x in args.month.split("-"))
            months = [(year, month)]
        else:
            months = _list_months(db)

        built = skipped = 0
        for year, month in months:
            n = _build_month(db, year, month)
            if n >= MIN_TICKERS_PER_MONTH:
                built += 1
            else:
                skipped += 1

        log.info("Done: %d month(s) built, %d skipped", built, skipped)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
