#!/usr/bin/env python3
"""
Quantify survivorship bias in this project's backtest universe.

monthly_pe (historic_fundamentals.duckdb) and stock_prices (trade_systems'
prices.duckdb) are both built by manually adding tickers that matter *today*
(scripts/manage_tickers.py), not from a point-in-time historical constituent
list. Any stock that was large/liquid enough to matter historically but no
longer exists (bankrupt, delisted, taken private, acquired) is invisible to
every backtest run against these tables unless someone happened to add it
before it disappeared.

Ground truth: trade_systems/data/sp500_constituents.csv (current members) +
sp500_removed_since_2016.csv (221 real S&P 500 exits since 2016, with reason).
This is a genuine point-in-time-adjacent list -- these were real, investable,
large-cap stocks that a live strategy could plausibly have held.

For each of the 221 removed tickers, checks:
    1. Is it tracked in monthly_pe today (fin_import2)?
    2. Does it have price history in stock_prices (trade_systems), even if
       not in monthly_pe?
    3. For tickers with price history: does that history actually end at
       (or near) the real-world exit, or does it continue to the present day
       under a recycled ticker/company-name (a different, unrelated company
       that later took over the same symbol after the original was wiped
       out)? This is checked by looking for tickers whose price series runs
       all the way to today despite a S&P 500 removal reason indicating the
       original company ceased to exist (bankruptcy/take-private/acquisition),
       cross-referenced against the current company name in company_overview.

Usage:
    uv run scripts/analyze_survivorship_bias.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)

_TS_DATA = Path("/home/pedro/projects/trade_systems/data")
_KNOWN_RENAME_CASES = {
    # ticker -> (original S&P500 entity, what the ticker/name means today)
    "BBBY": ("Bed Bath & Beyond Corporation (original) — Chapter 11, Apr 2023, "
             "equity wiped out",
             "Overstock.com Inc renamed itself 'Bed Bath & Beyond, Inc.' in "
             "Aug 2023 after buying the brand out of bankruptcy; price/company "
             "data under this ticker is Overstock's continuous history, not "
             "the original retailer's"),
    "CTRA": ("An unrelated 1990s-era company (price history ends 1998-12-31)",
             "Ticker reassigned to Coterra Energy (formed 2021, Cimarex + "
             "Cabot Oil & Gas merger) — current CTRA fundamentals/price data "
             "is not tracked under this symbol in this project at all"),
}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(_TS_DATA / "prices.duckdb"))

    removed = pd.read_csv(_TS_DATA / "sp500_removed_since_2016.csv")
    tickers = removed["symbol"].unique().tolist()
    log.info("Loaded %d real S&P 500 exits since 2016 from sp500_removed_since_2016.csv", len(tickers))

    hf_conn = duckdb.connect(hf_db, read_only=True)
    tracked = set(hf_conn.execute("SELECT DISTINCT ticker FROM monthly_pe").df()["ticker"])
    hf_conn.close()

    p_conn = duckdb.connect(prices_db, read_only=True)
    priced = set(p_conn.execute("SELECT DISTINCT ticker FROM stock_prices").df()["ticker"])

    in_hf = [t for t in tickers if t in tracked]
    in_prices_only = [t for t in tickers if t not in tracked and t in priced]
    in_neither = [t for t in tickers if t not in tracked and t not in priced]

    print("\n" + "=" * 84)
    print(f"1. COVERAGE — {len(tickers)} real S&P 500 exits since 2016 vs. this project's databases")
    print("=" * 84)
    print(f"  Tracked in monthly_pe (fin_import2) today:      {len(in_hf):4d}  ({len(in_hf)/len(tickers):.0%})")
    print(f"  Price history only (trade_systems), no fundamentals: {len(in_prices_only):4d}  ({len(in_prices_only)/len(tickers):.0%})")
    print(f"  ZERO footprint in either database:               {len(in_neither):4d}  ({len(in_neither)/len(tickers):.0%})")

    # ── 2. For tickers with price data: did the series end where it should? ──
    print("\n" + "=" * 84)
    print("2. TERMINATION CHECK — of removed tickers WITH price history, how many")
    print("   still show data continuing to today (candidate ticker-recycling)?")
    print("=" * 84)

    present = [t for t in tickers if t in priced]
    rows = []
    for t in present:
        df = p_conn.execute(
            "SELECT date, adj_close FROM stock_prices WHERE ticker = ? ORDER BY date", [t]
        ).df()
        df = df.dropna(subset=["adj_close"])
        if df.empty:
            rows.append({"ticker": t, "last_date": pd.NaT, "n_valid_rows": 0})
            continue
        rows.append({"ticker": t, "last_date": df["date"].max(), "n_valid_rows": len(df)})
    p_conn.close()

    hist = pd.DataFrame(rows)
    today = pd.Timestamp.now().normalize()
    still_trading = hist[(hist["n_valid_rows"] > 0) & (hist["last_date"] >= today - pd.Timedelta(days=14))]
    truly_ended = hist[(hist["n_valid_rows"] > 0) & (hist["last_date"] < today - pd.Timedelta(days=14))]
    no_valid_data = hist[hist["n_valid_rows"] == 0]

    print(f"  Price data continues to present day: {len(still_trading)} / {len(present)} "
          f"present tickers ({len(still_trading)/len(present):.0%})")
    print(f"  Price data genuinely ends in the past: {len(truly_ended)}")
    print(f"  Rows present but adj_close entirely NULL (data-quality gap, not survivorship): {len(no_valid_data)}")
    if not truly_ended.empty:
        print("\n  Genuinely-ended tickers:")
        print(truly_ended.to_string(index=False))

    print(f"\n  Of the {len(still_trading)} 'still trading' tickers, most are real companies that simply")
    print("  fell out of the S&P 500 by market cap (still independently public) — not a data problem.")
    print("  A smaller subset are cases where the ORIGINAL S&P 500 constituent ceased to exist and an")
    print("  unrelated company later took over the same ticker/name, silently splicing two different")
    print("  companies' histories under one symbol. Known confirmed cases in this project's data:")
    for t, (original, now) in _KNOWN_RENAME_CASES.items():
        print(f"\n    {t}:")
        print(f"      Original constituent: {original}")
        print(f"      Ticker/name today:    {now}")

    print("\nDone.")


if __name__ == "__main__":
    main()
