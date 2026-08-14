#!/usr/bin/env python3
"""
Backfill Fibonacci-retracement factor columns into monthly_pe.

Swing high/low use the same "auto-fib" convention most charting tools default
to (TradingView's auto Fib-retracement tool, etc.): highest-high and lowest-low
of a trailing lookback window, not a strictly sequenced up-leg. This keeps the
computation vectorized (rolling max/min) instead of an O(n * window) search for
the true pre-high swing low, and matches how a discretionary trader would
actually draw the tool on a chart.

    fib_swing_high      = rolling 252-trading-day max(adj_close)  (52wk high)
    fib_swing_low       = rolling 252-trading-day min(adj_close)  (52wk low)
    fib_retracement_pct = (swing_high - price) / (swing_high - swing_low)
                          0.0 = sitting at the 52wk high, 1.0 = sitting at the
                          52wk low. This is "how much of the range has been
                          given back", which is what a Fibonacci retracement
                          level describes.
    fib_618_proximity   = -abs(fib_retracement_pct - 0.618)
                          Higher (closer to 0) = closer to the golden-ratio
                          61.8% pullback level -- the single most cited
                          Fibonacci entry level. Sign flipped so higher = better,
                          matching the rest of monthly_pe's factor convention.
    fib_in_golden_zone  = 1.0 if retracement is within the 38.2%-61.8% "golden
                          zone" band, else 0.0.
    above_200dma        = 1.0 if price > trailing 200-day SMA, else 0.0.
                          Context/filter column: textbook Fibonacci usage
                          restricts retracement entries to stocks already in an
                          established uptrend.

Source: trade_systems' prices.duckdb stock_prices (daily OHLCV), same
PRICES_DB_PATH convention as scripts/backfill_canslim_technicals.py. Price data
is publicly same-day, so no reporting-lag filtering is needed.

This is an EXPERIMENTAL feature test -- see docs/fibonacci_factors_test.md for
the IC/backtest results. These columns are not wired into the live composite
score (historic_fundamentals/baselines.py _VALUE_COLS/_QUALITY_COLS) until
validated.

Usage:
    uv run scripts/backfill_fibonacci_factors.py
    uv run scripts/backfill_fibonacci_factors.py --dry-run
    uv run scripts/backfill_fibonacci_factors.py --limit 50 --verbose
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

FIB_LEVELS = (0.236, 0.382, 0.5, 0.618, 0.786)


def _compute_daily_features(daily: pd.DataFrame) -> pd.DataFrame:
    """daily: columns date, adj_close, sorted ascending. Adds feature columns."""
    out = daily.copy()
    c = out["adj_close"]

    swing_high = c.rolling(252, min_periods=200).max()
    swing_low = c.rolling(252, min_periods=200).min()
    rng = (swing_high - swing_low).replace(0, pd.NA)

    out["fib_swing_high"] = swing_high
    out["fib_swing_low"] = swing_low
    out["fib_retracement_pct"] = (swing_high - c) / rng
    out["fib_618_proximity"] = -(out["fib_retracement_pct"] - 0.618).abs()
    out["fib_in_golden_zone"] = (
        (out["fib_retracement_pct"] >= 0.382) & (out["fib_retracement_pct"] <= 0.618)
    ).astype(float)
    out.loc[out["fib_retracement_pct"].isna(), "fib_in_golden_zone"] = pd.NA

    sma200 = c.rolling(200, min_periods=150).mean()
    out["above_200dma"] = (c > sma200).astype(float)
    out.loc[sma200.isna(), "above_200dma"] = pd.NA

    return out


_OUT_COLS = [
    "ticker", "month_end_date",
    "fib_retracement_pct", "fib_618_proximity", "fib_in_golden_zone", "above_200dma",
]


def _compute_for_ticker(ticker: str, month_ends: list, prices_conn) -> pd.DataFrame:
    daily = prices_conn.execute(
        "SELECT date, adj_close FROM stock_prices WHERE ticker = ? ORDER BY date",
        [ticker],
    ).df()
    if daily.empty:
        return pd.DataFrame(columns=_OUT_COLS)

    daily["date"] = pd.to_datetime(daily["date"]).astype("datetime64[ns]")
    daily = _compute_daily_features(daily)

    me = pd.DataFrame({"month_end_date": pd.to_datetime(month_ends).astype("datetime64[ns]")}).sort_values("month_end_date")
    merged = pd.merge_asof(
        me,
        daily[["date"] + _OUT_COLS[2:]],
        left_on="month_end_date",
        right_on="date",
        direction="backward",
        tolerance=pd.Timedelta(days=7),
    )
    merged["ticker"] = ticker
    merged["month_end_date"] = merged["month_end_date"].dt.date
    return merged[_OUT_COLS]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Fibonacci-retracement factors into monthly_pe.")
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
    for col in ("fib_retracement_pct", "fib_618_proximity", "fib_in_golden_zone", "above_200dma"):
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
    for col in ("fib_retracement_pct", "fib_618_proximity", "fib_in_golden_zone", "above_200dma"):
        n = out[col].notna().sum()
        log.info("  %-20s %d / %d  (%.1f%%)", col, n, total, 100 * n / total)

    if args.dry_run:
        log.info("Dry run -- no changes written.")
        hf_conn.close()
        return

    log.info("Writing columns back to monthly_pe ...")
    hf_conn.register("_tmp_fib", out)
    hf_conn.execute("""
        UPDATE monthly_pe
        SET
            fib_retracement_pct = t.fib_retracement_pct,
            fib_618_proximity   = t.fib_618_proximity,
            fib_in_golden_zone  = t.fib_in_golden_zone,
            above_200dma        = t.above_200dma
        FROM _tmp_fib t
        WHERE monthly_pe.ticker         = t.ticker
          AND monthly_pe.month_end_date = t.month_end_date
    """)
    hf_conn.execute("DROP VIEW IF EXISTS _tmp_fib")

    updated = hf_conn.execute(
        "SELECT COUNT(*) FROM monthly_pe WHERE fib_retracement_pct IS NOT NULL"
    ).fetchone()[0]
    log.info("Rows with fib_retracement_pct populated: %d", updated)

    hf_conn.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
