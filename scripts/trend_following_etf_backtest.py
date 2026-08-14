#!/usr/bin/env python3
"""
Prototype: Covel/Trading-Recipes style Donchian breakout trend system,
ported from futures to a diversified ETF basket (equities, duration,
gold, broad commodities, dollar).

System (from "Trend Following" Appendix C):
    - Entry:  89-day price breakout (long above prior 89-day high,
              short below prior 89-day low)
    - Exit:   13-day channel breakdown (trailing stop, no profit target)
    - Sizing: risk 2% of equity per trade, position = lesser of
              (2% equity / |entry - initial 13-day stop|) or
              (2% equity / (2 * 15-day ATR)), capped at 1x equity notional
              (no margin/leverage, unlike the original futures system)

Data: yfinance daily OHLC, cached locally as parquet.

Usage:
    uv run scripts/trend_following_etf_backtest.py
    uv run scripts/trend_following_etf_backtest.py --refresh
    uv run scripts/trend_following_etf_backtest.py --tickers SPY,GLD,TLT
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "trend_following_etf_prices.parquet"

DEFAULT_TICKERS = ["SPY", "QQQ", "TLT", "IEF", "GLD", "DBC", "UUP"]

ENTRY_LOOKBACK = 89
EXIT_LOOKBACK = 13
ATR_LOOKBACK = 15
RISK_PCT = 0.02
COST_BPS = 5  # per side, applied to fill price
START_EQUITY = 1_000_000.0


def load_prices(tickers: list[str], refresh: bool) -> pd.DataFrame:
    if CACHE.exists() and not refresh:
        return pd.read_parquet(CACHE)

    frames = []
    for t in tickers:
        df = yf.download(t, start="2000-01-01", auto_adjust=True, progress=False)
        if df.empty:
            print(f"  no data for {t}, skipping")
            continue
        df = df[["Open", "High", "Low", "Close"]].copy()
        df.columns = ["open", "high", "low", "close"]
        df["ticker"] = t
        frames.append(df)

    prices = pd.concat(frames).reset_index().rename(columns={"Date": "date"})
    prices.to_parquet(CACHE)
    return prices


def compute_signals(g: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker Donchian channels, ATR, computed with a 1-day lag to avoid lookahead."""
    g = g.sort_values("date").reset_index(drop=True)

    prev_close = g["close"].shift(1)
    tr = pd.concat(
        [
            g["high"] - g["low"],
            (g["high"] - prev_close).abs(),
            (g["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    g["atr"] = tr.rolling(ATR_LOOKBACK).mean()

    g["upper_entry"] = g["high"].rolling(ENTRY_LOOKBACK).max().shift(1)
    g["lower_entry"] = g["low"].rolling(ENTRY_LOOKBACK).min().shift(1)
    g["upper_exit"] = g["high"].rolling(EXIT_LOOKBACK).max().shift(1)
    g["lower_exit"] = g["low"].rolling(EXIT_LOOKBACK).min().shift(1)
    return g


def run_backtest(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_ticker = {
        t: compute_signals(g).set_index("date")
        for t, g in prices.groupby("ticker")
    }
    all_dates = sorted(set().union(*[g.index for g in by_ticker.values()]))

    cash = START_EQUITY
    positions: dict[str, dict] = {}  # ticker -> {shares, entry_price, risk_dollars}
    equity_curve = []
    trades = []
    cost = COST_BPS / 10_000

    for dt in all_dates:
        # mark-to-market equity as of yesterday's close, used for today's sizing
        equity = cash + sum(
            pos["shares"] * by_ticker[t].loc[:dt].iloc[-1]["close"]
            for t, pos in positions.items()
            if dt in by_ticker[t].index or by_ticker[t].index[by_ticker[t].index <= dt].size
        )

        for t, g in by_ticker.items():
            if dt not in g.index:
                continue
            row = g.loc[dt]
            if pd.isna(row.get("atr")):
                continue

            if t in positions:
                pos = positions[t]
                exit_price = None
                if pos["shares"] > 0 and row["low"] <= row["lower_exit"]:
                    exit_price = min(row["lower_exit"], row["high"])
                elif pos["shares"] < 0 and row["high"] >= row["upper_exit"]:
                    exit_price = max(row["upper_exit"], row["low"])

                if exit_price is not None:
                    fill = exit_price * (1 - cost * np.sign(pos["shares"]))
                    cash += pos["shares"] * fill
                    pnl = pos["shares"] * (fill - pos["entry_price"])
                    trades.append(
                        {
                            "ticker": t,
                            "entry_date": pos["entry_date"],
                            "exit_date": dt,
                            "side": "long" if pos["shares"] > 0 else "short",
                            "pnl": pnl,
                            "r_multiple": pnl / pos["risk_dollars"],
                        }
                    )
                    del positions[t]
                continue

            # flat: look for a breakout entry
            side = 0
            if row["high"] >= row["upper_entry"]:
                side = 1
            elif row["low"] <= row["lower_entry"]:
                side = -1
            if side == 0:
                continue

            entry_price = row["upper_entry"] if side == 1 else row["lower_entry"]
            fill = entry_price * (1 + cost * side)
            initial_stop = row["lower_exit"] if side == 1 else row["upper_exit"]
            stop_distance = abs(fill - initial_stop)
            atr_distance = 2 * row["atr"]
            if stop_distance <= 0 or atr_distance <= 0:
                continue

            risk_dollars = RISK_PCT * equity
            shares_by_stop = risk_dollars / stop_distance
            shares_by_atr = risk_dollars / atr_distance
            raw_shares = min(shares_by_stop, shares_by_atr)
            max_shares_unlevered = equity / fill  # no margin/leverage
            shares = np.floor(min(raw_shares, max_shares_unlevered)) * side
            if abs(shares) < 1:
                continue

            cash -= shares * fill
            positions[t] = {
                "shares": shares,
                "entry_price": fill,
                "entry_date": dt,
                "risk_dollars": risk_dollars,
            }

        mtm = cash + sum(
            pos["shares"] * by_ticker[t].loc[dt]["close"]
            for t, pos in positions.items()
            if dt in by_ticker[t].index
        )
        equity_curve.append({"date": dt, "equity": mtm})

    return pd.DataFrame(equity_curve).set_index("date"), pd.DataFrame(trades)


def benchmark_stats(prices: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """SPY buy-and-hold over the same dates, for CAGR/Sharpe/MaxDD/correlation context."""
    spy = prices[prices["ticker"] == "SPY"].set_index("date")["close"].reindex(index).ffill()
    return spy


def summarize(equity: pd.DataFrame, trades: pd.DataFrame, prices: pd.DataFrame) -> pd.Series:
    eq = equity["equity"]
    ret = eq.pct_change().dropna()
    years = (eq.index[-1] - eq.index[0]).days / 365.25

    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else float("nan")
    running_max = eq.cummax()
    dd = eq / running_max - 1
    max_dd = dd.min()

    wins = trades[trades["pnl"] > 0]["pnl"]
    losses = trades[trades["pnl"] <= 0]["pnl"]
    profit_factor = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("nan")
    r_expectancy = trades["r_multiple"].mean()
    hit_rate = len(wins) / len(trades) if len(trades) else float("nan")

    print(f"\nPeriod: {eq.index[0].date()} -> {eq.index[-1].date()}  ({years:.1f}y)")
    print(f"Starting equity:  ${eq.iloc[0]:,.0f}")
    print(f"Ending equity:    ${eq.iloc[-1]:,.0f}")
    print(f"CAGR:             {cagr:.2%}")
    print(f"Sharpe:           {sharpe:.2f}")
    print(f"Max drawdown:     {max_dd:.2%}")
    print(f"Trades:           {len(trades)}")
    print(f"Hit rate:         {hit_rate:.1%}")
    print(f"Profit factor:    {profit_factor:.2f}")
    print(f"R-expectancy:     {r_expectancy:.2f}R per trade")

    print("\nPer-ticker trade count and R-expectancy:")
    print(
        trades.groupby("ticker")
        .agg(trades=("pnl", "size"), win_rate=("pnl", lambda s: (s > 0).mean()), avg_r=("r_multiple", "mean"))
        .round(2)
        .to_string()
    )

    spy = benchmark_stats(prices, eq.index)
    spy_ret = spy.pct_change().dropna()
    spy_cagr = (spy.iloc[-1] / spy.iloc[0]) ** (1 / years) - 1
    spy_sharpe = spy_ret.mean() / spy_ret.std() * np.sqrt(252)
    spy_dd = (spy / spy.cummax() - 1).min()
    corr = ret.reindex(spy_ret.index).corr(spy_ret)

    print(f"\nSPY buy-and-hold, same period:")
    print(f"  CAGR:         {spy_cagr:.2%}")
    print(f"  Sharpe:       {spy_sharpe:.2f}")
    print(f"  Max drawdown: {spy_dd:.2%}")
    print(f"\nDaily-return correlation (strategy vs SPY): {corr:.2f}")
    return spy


def plot(equity: pd.DataFrame, out_path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(equity.index, equity["equity"])
    ax.set_yscale("log")
    ax.set_title("Trend Following ETF Basket - Equity Curve (log scale)")
    ax.set_ylabel("Equity ($)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"\nSaved equity curve chart to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--refresh", action="store_true", help="Re-download prices instead of using cache")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    print(f"Loading prices for: {tickers}")
    prices = load_prices(tickers, args.refresh)

    equity, trades = run_backtest(prices)
    summarize(equity, trades, prices)
    plot(equity, ROOT / "data" / "trend_following_etf_equity_curve.png")


if __name__ == "__main__":
    main()
