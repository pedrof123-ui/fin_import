#!/usr/bin/env python3
"""
Backfill CANSLIM 'N' and 'S' factor columns into monthly_pe.

    pct_off_52wk_high = adj_close / rolling_252trading-day_max(adj_close) - 1
                         0 = at a new high (O'Neil's "N"), same formula
                         historic_fundamentals/technical_indicators.py already
                         uses on-demand, backfilled here across full history.
    vol_surge_ratio    = trailing 10-day avg volume / trailing 63-day (~3mo)
                         avg volume as of month_end. >1 = recent volume pickup.
    up_down_vol_ratio   = sum(volume on up-close days) / sum(volume on down-close
                         days) over the trailing 63 trading days -- accumulation/
                         distribution proxy for "S".

Source: trade_systems' prices.duckdb stock_prices (daily OHLCV, shared
cross-repo, same PRICES_DB_PATH convention as
historic_fundamentals/technical_indicators.py). Price/volume data is publicly
same-day, so no reporting-lag filtering is needed (unlike the fundamentals
factors in backfill_canslim_factors.py).

Known limitation: `volume` in stock_prices is raw (not split-adjusted). A
stock split landing inside a 10/63-day trailing window would show as a
spurious volume discontinuity. Not corrected here -- rare enough for a factor
test spike, would need the stock_splits table to fix properly.

This is an EXPERIMENTAL feature test -- see CANSLIM_FACTOR_TEST_PLAN.md. These
columns are not wired into the live composite score until validated.

Usage:
    uv run scripts/backfill_canslim_technicals.py
    uv run scripts/backfill_canslim_technicals.py --dry-run
    uv run scripts/backfill_canslim_technicals.py --limit 50 --verbose
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


def _compute_daily_features(daily: pd.DataFrame) -> pd.DataFrame:
    """daily: columns date, adj_close, volume, sorted ascending. Adds feature columns."""
    out = daily.copy()
    c = out["adj_close"]
    v = out["volume"].astype(float)

    roll_max = c.rolling(252, min_periods=200).max()
    out["pct_off_52wk_high"] = c / roll_max - 1

    vol_10d = v.rolling(10, min_periods=8).mean()
    vol_63d = v.rolling(63, min_periods=40).mean()
    out["vol_surge_ratio"] = vol_10d / vol_63d.replace(0, pd.NA)

    close_diff = out["close"].diff()
    up_vol = v.where(close_diff > 0, 0.0)
    down_vol = v.where(close_diff < 0, 0.0)
    up_sum = up_vol.rolling(63, min_periods=40).sum()
    down_sum = down_vol.rolling(63, min_periods=40).sum()
    out["up_down_vol_ratio"] = up_sum / down_sum.replace(0, pd.NA)

    return out


def _compute_for_ticker(ticker: str, month_ends: list, prices_conn) -> pd.DataFrame:
    daily = prices_conn.execute(
        "SELECT date, close, adj_close, volume FROM stock_prices WHERE ticker = ? ORDER BY date",
        [ticker],
    ).df()
    if daily.empty:
        return pd.DataFrame(columns=["ticker", "month_end_date", "pct_off_52wk_high", "vol_surge_ratio", "up_down_vol_ratio"])

    daily["date"] = pd.to_datetime(daily["date"]).astype("datetime64[ns]")
    daily = _compute_daily_features(daily)

    me = pd.DataFrame({"month_end_date": pd.to_datetime(month_ends).astype("datetime64[ns]")}).sort_values("month_end_date")
    merged = pd.merge_asof(
        me,
        daily[["date", "pct_off_52wk_high", "vol_surge_ratio", "up_down_vol_ratio"]],
        left_on="month_end_date",
        right_on="date",
        direction="backward",
        tolerance=pd.Timedelta(days=7),
    )
    merged["ticker"] = ticker
    merged["month_end_date"] = merged["month_end_date"].dt.date
    return merged[["ticker", "month_end_date", "pct_off_52wk_high", "vol_surge_ratio", "up_down_vol_ratio"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill CANSLIM 'N'/'S' factors into monthly_pe.")
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
    for col in ("pct_off_52wk_high", "vol_surge_ratio", "up_down_vol_ratio"):
        hf_conn.execute(f"ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS {col} DOUBLE")

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

    total = len(out)
    for col in ("pct_off_52wk_high", "vol_surge_ratio", "up_down_vol_ratio"):
        n = out[col].notna().sum()
        log.info("  %-18s %d / %d  (%.1f%%)", col, n, total, 100 * n / total)

    if args.dry_run:
        log.info("Dry run -- no changes written.")
        hf_conn.close()
        return

    log.info("Writing columns back to monthly_pe ...")
    hf_conn.register("_tmp_canslim_ns", out)
    hf_conn.execute("""
        UPDATE monthly_pe
        SET
            pct_off_52wk_high = t.pct_off_52wk_high,
            vol_surge_ratio   = t.vol_surge_ratio,
            up_down_vol_ratio = t.up_down_vol_ratio
        FROM _tmp_canslim_ns t
        WHERE monthly_pe.ticker         = t.ticker
          AND monthly_pe.month_end_date = t.month_end_date
    """)
    hf_conn.execute("DROP VIEW IF EXISTS _tmp_canslim_ns")

    updated = hf_conn.execute(
        "SELECT COUNT(*) FROM monthly_pe WHERE pct_off_52wk_high IS NOT NULL"
    ).fetchone()[0]
    log.info("Rows with pct_off_52wk_high populated: %d", updated)

    hf_conn.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
