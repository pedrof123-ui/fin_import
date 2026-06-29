#!/usr/bin/env python3
"""
Backfill fcf_growth_1yr, earn_growth_1yr, rev_growth_1yr in monthly_pe.

Computes YoY TTM growth from the existing ttm_fcf, ttm_eps, ttm_revenue columns
already present in monthly_pe. Point-in-time safe: shift(12) uses only past rows
per ticker. NaN when base value is zero or negative.

Usage:
    uv run scripts/backfill_growth_rates.py
    uv run scripts/backfill_growth_rates.py --db data/historic_fundamentals.duckdb --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)


def compute_growth(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["ticker", "month_end_date"]).copy()

    for col, base_col in [
        ("fcf_growth_1yr",  "ttm_fcf"),
        ("earn_growth_1yr", "ttm_eps"),
        ("rev_growth_1yr",  "ttm_revenue"),
    ]:
        base = df.groupby("ticker")[base_col].shift(12)
        df[col] = (df[base_col] / base - 1).where(base > 0)

    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill growth rate columns in monthly_pe.")
    parser.add_argument("--db", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not write.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    db_path = args.db or os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    log.info("Database: %s", db_path)

    conn = duckdb.connect(db_path)

    # Ensure columns exist (idempotent)
    for col in ("fcf_growth_1yr", "earn_growth_1yr", "rev_growth_1yr"):
        conn.execute(f"ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS {col} DOUBLE")

    log.info("Loading monthly_pe ...")
    df = conn.execute(
        "SELECT ticker, month_end_date, ttm_fcf, ttm_eps, ttm_revenue FROM monthly_pe ORDER BY ticker, month_end_date"
    ).df()
    log.info("Loaded %d rows, %d tickers", len(df), df["ticker"].nunique())

    df = compute_growth(df)

    # Coverage report
    total = len(df)
    for col in ("fcf_growth_1yr", "earn_growth_1yr", "rev_growth_1yr"):
        n = df[col].notna().sum()
        log.info("  %-20s %d / %d  (%.1f%%)", col, n, total, 100 * n / total)

    if args.dry_run:
        log.info("Dry run — no changes written.")
        conn.close()
        return

    log.info("Writing growth columns back to monthly_pe ...")
    growth_cols = ["ticker", "month_end_date", "fcf_growth_1yr", "earn_growth_1yr", "rev_growth_1yr"]
    conn.register("_tmp_growth", df[growth_cols])
    conn.execute("""
        UPDATE monthly_pe
        SET
            fcf_growth_1yr  = g.fcf_growth_1yr,
            earn_growth_1yr = g.earn_growth_1yr,
            rev_growth_1yr  = g.rev_growth_1yr
        FROM _tmp_growth g
        WHERE monthly_pe.ticker         = g.ticker
          AND monthly_pe.month_end_date = g.month_end_date
    """)
    conn.execute("DROP VIEW IF EXISTS _tmp_growth")

    updated = conn.execute(
        "SELECT COUNT(*) FROM monthly_pe WHERE fcf_growth_1yr IS NOT NULL"
    ).fetchone()[0]
    log.info("Rows with fcf_growth_1yr populated: %d", updated)

    conn.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
