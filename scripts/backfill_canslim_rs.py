#!/usr/bin/env python3
"""
Backfill CANSLIM 'L' (Leader) factor into monthly_pe: RS Rating.

    rs_raw    = 0.4*ret_3m + 0.2*ret_6m + 0.2*ret_9m + 0.2*ret_12m as of
                month_end, IBD's published weighting (overweights the most
                recent quarter).
    rs_rating = cross-sectional percentile rank of rs_raw within each
                month_end_date, rescaled to IBD's 1-99 range.

Differs from the existing `momentum_12_1` column (raw 12-1 month return, not
cross-sectionally ranked) -- RS Rating is the percentile-ranked version
CANSLIM specifically calls for.

Ranked market-wide (all monthly_pe rows with a valid rs_raw for that month),
same precedent as backfill_greenblatt_factors.py's ebit_ev_yield/greenblatt_roc
-- investable-universe filtering (market cap, sector) is applied downstream in
the IC-test / backtest scripts, not baked into the stored factor column.

Source: trade_systems' prices.duckdb stock_prices, same PRICES_DB_PATH
convention as backfill_canslim_technicals.py.

This is an EXPERIMENTAL feature test -- see CANSLIM_FACTOR_TEST_PLAN.md. This
column is not wired into the live composite score until validated.

Usage:
    uv run scripts/backfill_canslim_rs.py
    uv run scripts/backfill_canslim_rs.py --dry-run
    uv run scripts/backfill_canslim_rs.py --limit 50 --verbose
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)

_PRICES_DB = os.environ.get("PRICES_DB_PATH", "/home/pedro/projects/trade_systems/data/prices.duckdb")

# Trading-day approximations for 3/6/9/12 calendar months.
_WINDOWS = {"ret_3m": 63, "ret_6m": 126, "ret_9m": 189, "ret_12m": 252}
_WEIGHTS = {"ret_3m": 0.4, "ret_6m": 0.2, "ret_9m": 0.2, "ret_12m": 0.2}


def _compute_daily_rs_raw(daily: pd.DataFrame) -> pd.DataFrame:
    """daily: columns date, adj_close, sorted ascending. Adds rs_raw."""
    out = daily.copy()
    c = out["adj_close"]
    rs_raw = pd.Series(0.0, index=out.index)
    valid = pd.Series(True, index=out.index)
    for col, window in _WINDOWS.items():
        ret = c / c.shift(window) - 1
        rs_raw = rs_raw + _WEIGHTS[col] * ret
        valid = valid & ret.notna()
    out["rs_raw"] = rs_raw.where(valid)
    return out


def _compute_for_ticker(ticker: str, month_ends: list, prices_conn) -> pd.DataFrame:
    daily = prices_conn.execute(
        "SELECT date, adj_close FROM stock_prices WHERE ticker = ? ORDER BY date",
        [ticker],
    ).df()
    if daily.empty:
        return pd.DataFrame(columns=["ticker", "month_end_date", "rs_raw"])

    daily["date"] = pd.to_datetime(daily["date"]).astype("datetime64[ns]")
    daily = _compute_daily_rs_raw(daily)

    me = pd.DataFrame({"month_end_date": pd.to_datetime(month_ends).astype("datetime64[ns]")}).sort_values("month_end_date")
    merged = pd.merge_asof(
        me,
        daily[["date", "rs_raw"]],
        left_on="month_end_date",
        right_on="date",
        direction="backward",
        tolerance=pd.Timedelta(days=7),
    )
    merged["ticker"] = ticker
    merged["month_end_date"] = merged["month_end_date"].dt.date
    return merged[["ticker", "month_end_date", "rs_raw"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill CANSLIM 'L' RS Rating into monthly_pe.")
    parser.add_argument("--db", default=None, help="Path to historic_fundamentals.duckdb")
    parser.add_argument("--prices-db", default=None, help="Path to prices.duckdb")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N tickers (testing)")
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not write")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    hf_db = args.db or os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    prices_db = args.prices_db or _PRICES_DB
    log.info("HF_DB: %s", hf_db)
    log.info("PRICES_DB: %s", prices_db)

    hf_conn = duckdb.connect(hf_db)
    hf_conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS rs_rating DOUBLE")

    log.info("Loading monthly_pe (ticker, month_end_date) ...")
    base = hf_conn.execute(
        "SELECT ticker, month_end_date FROM monthly_pe ORDER BY ticker, month_end_date"
    ).df()
    base["month_end_date"] = pd.to_datetime(base["month_end_date"]).dt.date
    log.info("Loaded %d rows, %d tickers", len(base), base["ticker"].nunique())

    tickers = base["ticker"].unique().tolist()
    if args.limit:
        tickers = tickers[: args.limit]
        log.info("Limiting to first %d tickers", len(tickers))

    prices_conn = duckdb.connect(prices_db, read_only=True)

    results = []
    t0 = time.time()
    for i, ticker in enumerate(tickers, 1):
        month_ends = base.loc[base["ticker"] == ticker, "month_end_date"].tolist()
        try:
            res = _compute_for_ticker(ticker, month_ends, prices_conn)
        except Exception as exc:
            log.warning("Ticker %s failed: %s", ticker, exc)
            continue
        results.append(res)
        if i % 200 == 0 or i == len(tickers):
            elapsed = time.time() - t0
            log.info("Processed %d / %d tickers (%.0fs elapsed)", i, len(tickers), elapsed)

    prices_conn.close()

    out = pd.concat(results, ignore_index=True) if results else pd.DataFrame()
    if out.empty:
        log.error("No rows computed -- aborting.")
        hf_conn.close()
        sys.exit(1)

    log.info("Ranking rs_raw cross-sectionally within each month_end_date ...")
    out["rs_rating"] = out.groupby("month_end_date")["rs_raw"].rank(pct=True, method="average") * 98 + 1
    out.loc[out["rs_raw"].isna(), "rs_rating"] = pd.NA

    total = len(out)
    n = out["rs_rating"].notna().sum()
    log.info("  %-10s %d / %d  (%.1f%%)", "rs_rating", n, total, 100 * n / total)

    # Sanity: within a month with N ranked names, rs_rating should span close to [1, 99].
    sample_month = out.loc[out["rs_rating"].notna(), "month_end_date"].max()
    sample = out[out["month_end_date"] == sample_month]
    log.info(
        "Sample month %s: %d ranked names, rs_rating range [%.1f, %.1f]",
        sample_month, sample["rs_rating"].notna().sum(),
        sample["rs_rating"].min(), sample["rs_rating"].max(),
    )

    if args.dry_run:
        log.info("Dry run -- no changes written.")
        hf_conn.close()
        return

    log.info("Writing column back to monthly_pe ...")
    hf_conn.register("_tmp_canslim_rs", out[["ticker", "month_end_date", "rs_rating"]])
    hf_conn.execute("""
        UPDATE monthly_pe
        SET rs_rating = t.rs_rating
        FROM _tmp_canslim_rs t
        WHERE monthly_pe.ticker         = t.ticker
          AND monthly_pe.month_end_date = t.month_end_date
    """)
    hf_conn.execute("DROP VIEW IF EXISTS _tmp_canslim_rs")

    updated = hf_conn.execute(
        "SELECT COUNT(*) FROM monthly_pe WHERE rs_rating IS NOT NULL"
    ).fetchone()[0]
    log.info("Rows with rs_rating populated: %d", updated)

    hf_conn.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
