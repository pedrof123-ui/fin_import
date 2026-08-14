#!/usr/bin/env python3
"""
Does adding a hard stop-loss to IBD50 Strategy F improve on the current
fixed-30-day-hold, no-stop exit rule?

Replicates the live selection logic (traderbot/ibd50/analysis.py: strat_F,
strength_score, max 4 concurrent tranches, skip already-held tickers,
$2,000/stock, top 10 picks/week by strength_score) against the historical
`ibd50` signal table, then runs the same trade sequence under two exit rules:

    A) baseline  - current production rule: exit at expiry (entry + 30
                   calendar days), no stop-loss, ever.
    B) stop-loss - same entries, but exit early if price closes/prints
                   through an 8% stop (O'Neil's own CANSLIM rule), else
                   same 30-day expiry.

Data: ibd50 + stock_prices tables in trade_systems/data/prices.duckdb.

Usage:
    uv run scripts/ibd50_stoploss_backtest.py
    uv run scripts/ibd50_stoploss_backtest.py --stop-pct 0.07
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PRICES_DB = Path("/home/pedro/projects/trade_systems/data/prices.duckdb")

GRADE_MAP = {
    "A+": 12, "A": 11, "A-": 10,
    "B+": 9, "B": 8, "B-": 7,
    "C+": 6, "C": 5, "C-": 4,
    "D+": 3, "D": 2, "D-": 1,
    "E": 0,
}

ALLOC_PER_STOCK = 2_000
MAX_PICKS = 10
MAX_TRANCHES = 4
HOLD_DAYS = 30
START_EQUITY = 100_000.0


def load_signals() -> pd.DataFrame:
    con = duckdb.connect(str(PRICES_DB), read_only=True)
    df = con.execute("SELECT * FROM ibd50 ORDER BY date, rank").df()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df["group_rel_str_rating_num"] = df["group_rel_str_rating"].map(GRADE_MAP)
    df["acc_dis_rating_num"] = df["acc_dis_rating"].map(GRADE_MAP)
    df["strength_score"] = (
        df["composite_rating"] / 99 * 0.35
        + df["rs_rating"] / 99 * 0.30
        + df["eps_rating"] / 99 * 0.20
        + df["acc_dis_rating_num"] / 12 * 0.15
    ) * 100
    strat_f = df[(df["composite_rating"] >= 98) & (df["group_rel_str_rating_num"] >= 10)]
    return strat_f.sort_values(["date", "strength_score"], ascending=[True, False])


def load_daily_prices(tickers: list[str], start: str) -> dict[str, pd.DataFrame]:
    con = duckdb.connect(str(PRICES_DB), read_only=True)
    placeholders = ", ".join(f"'{t}'" for t in tickers)
    df = con.execute(f"""
        SELECT ticker, date, open, close, low
        FROM stock_prices
        WHERE ticker IN ({placeholders}) AND date >= '{start}'
        ORDER BY ticker, date
    """).df()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return {t: g.set_index("date") for t, g in df.groupby("ticker")}


def run_variant(signals: pd.DataFrame, prices: dict[str, pd.DataFrame], stop_pct: float | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """stop_pct=None => baseline (30-day hold only). Otherwise => stop-loss variant."""
    all_dates = sorted(set().union(*[p.index for p in prices.values()]))
    weeks = sorted(signals["date"].unique())

    cash = START_EQUITY
    positions: dict[str, dict] = {}
    trades = []
    equity_curve = []

    for dt in all_dates:
        # Exits first (so a name that expires today frees a tranche slot,
        # mirroring exits.py running before entry.py each day).
        for t in list(positions):
            pos = positions[t]
            if t not in prices or dt not in prices[t].index:
                continue
            row = prices[t].loc[dt]
            exit_price = None
            stopped = False

            if stop_pct is not None and row["low"] <= pos["entry_price"] * (1 - stop_pct):
                stop_price = pos["entry_price"] * (1 - stop_pct)
                exit_price = min(row["open"], stop_price)
                stopped = True
            elif dt >= pos["expiry_date"]:
                exit_price = row["close"]

            if exit_price is not None:
                cash += pos["shares"] * exit_price
                pnl = pos["shares"] * (exit_price - pos["entry_price"])
                risk_dollars = pos["entry_price"] * 0.08 * pos["shares"]  # fixed 8% reference R, both variants
                trades.append({
                    "ticker": t, "tranche_week": pos["tranche_week"],
                    "entry_date": pos["entry_date"], "exit_date": dt,
                    "pnl": pnl, "ret_pct": exit_price / pos["entry_price"] - 1,
                    "r_multiple": pnl / risk_dollars, "stopped": stopped,
                })
                del positions[t]

        equity = cash + sum(
            pos["shares"] * prices[t].loc[:dt].iloc[-1]["close"]
            for t, pos in positions.items() if t in prices and not prices[t].loc[:dt].empty
        )

        for w in weeks:
            entry_date = w + pd.Timedelta(days=3)
            # snap to next trading day
            candidates = [d for d in all_dates if d >= entry_date]
            if not candidates or candidates[0] != dt:
                continue

            held = set(positions)
            open_tranches = len({p["tranche_week"] for p in positions.values()})
            if open_tranches >= MAX_TRANCHES:
                continue

            week_picks = signals[signals["date"] == w]
            week_picks = week_picks[~week_picks["ticker"].isin(held)].head(MAX_PICKS)

            for _, r in week_picks.iterrows():
                t = r["ticker"]
                if t not in prices or dt not in prices[t].index:
                    continue
                entry_price = prices[t].loc[dt]["open"]
                if not np.isfinite(entry_price) or entry_price <= 0:
                    continue
                shares = np.floor(ALLOC_PER_STOCK / entry_price)
                if shares < 1:
                    continue
                cash -= shares * entry_price
                positions[t] = {
                    "shares": shares, "entry_price": entry_price, "entry_date": dt,
                    "expiry_date": dt + pd.Timedelta(days=HOLD_DAYS), "tranche_week": w,
                }

        equity_curve.append({"date": dt, "equity": equity})

    return pd.DataFrame(equity_curve).set_index("date"), pd.DataFrame(trades)


def compute_stats(equity: pd.DataFrame, trades: pd.DataFrame) -> dict:
    eq = equity["equity"]
    ret = eq.pct_change().dropna()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else float("nan")
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else float("nan")
    max_dd = (eq / eq.cummax() - 1).min()

    closed = trades
    wins = closed[closed["pnl"] > 0]["pnl"]
    losses = closed[closed["pnl"] <= 0]["pnl"]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("nan")
    hit_rate = len(wins) / len(closed) if len(closed) else float("nan")

    return {
        "trades": len(closed),
        "stopped": int(closed["stopped"].sum()) if "stopped" in closed else 0,
        "hit_rate": hit_rate,
        "profit_factor": pf,
        "r_expectancy": closed["r_multiple"].mean(),
        "avg_loss_pct": closed[closed["ret_pct"] < 0]["ret_pct"].mean(),
        "worst_pct": closed["ret_pct"].min(),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "years": years,
    }


def summarize(label: str, stats: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"Closed trades:     {stats['trades']}  (stopped early: {stats['stopped']})")
    print(f"Hit rate:          {stats['hit_rate']:.1%}")
    print(f"Profit factor:     {stats['profit_factor']:.2f}")
    print(f"R-expectancy:      {stats['r_expectancy']:.2f}R/trade  (R = 8% x $2,000 = $160, fixed reference across all variants)")
    print(f"Avg losing trade:  {stats['avg_loss_pct']:.1%}")
    print(f"Worst trade:       {stats['worst_pct']:.1%}")
    print(f"CAGR (annualized, {stats['years']:.1f}y window - noisy): {stats['cagr']:.2%}")
    print(f"Sharpe:            {stats['sharpe']:.2f}")
    print(f"Max drawdown:      {stats['max_dd']:.2%}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop-pct", type=float, default=0.08)
    parser.add_argument("--sweep", action="store_true", help="Run a stop-pct sensitivity sweep instead of a single comparison")
    args = parser.parse_args()

    signals = load_signals()
    tickers = signals["ticker"].unique().tolist()
    prices = load_daily_prices(tickers, start="2025-12-01")

    eq_a, trades_a = run_variant(signals, prices, stop_pct=None)
    stats_a = compute_stats(eq_a, trades_a)
    summarize("A) Baseline - 30-day hold, no stop (current production rule)", stats_a)

    if not args.sweep:
        eq_b, trades_b = run_variant(signals, prices, stop_pct=args.stop_pct)
        summarize(f"B) With {args.stop_pct:.0%} stop-loss", compute_stats(eq_b, trades_b))
        return

    rows = [{"stop_pct": "none (baseline)", **stats_a}]
    for pct in (0.05, 0.07, 0.08, 0.10, 0.12, 0.15):
        eq, trades = run_variant(signals, prices, stop_pct=pct)
        s = compute_stats(eq, trades)
        rows.append({"stop_pct": f"{pct:.0%}", **s})

    table = pd.DataFrame(rows)[
        ["stop_pct", "trades", "stopped", "hit_rate", "profit_factor",
         "r_expectancy", "avg_loss_pct", "worst_pct", "cagr", "sharpe", "max_dd"]
    ]
    for col in ("hit_rate", "avg_loss_pct", "worst_pct", "cagr", "max_dd"):
        table[col] = (table[col] * 100).round(1)
    for col in ("profit_factor", "r_expectancy", "sharpe"):
        table[col] = table[col].round(2)

    print("\n\n=== Stop-loss sensitivity sweep ===")
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
