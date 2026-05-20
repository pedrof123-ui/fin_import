from __future__ import annotations

import math
from datetime import date

import duckdb
import pandas as pd

from .performance import (
    compare_vs_backtest,
    get_ic_series,
    get_monthly_returns,
    get_open_positions,
    get_performance_stats,
    get_period_returns_table,
    get_pnl_summary,
    get_slippage_summary,
    get_trade_history,
)


def snapshot_report(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    client=None,
) -> None:
    """Print a comprehensive strategy performance report.

    Pass a connected IBClient as `client` to fetch live NAV and prices.
    """
    sep = "=" * 64
    thin = "-" * 64

    # --- Header ---
    print(sep)
    print(f"STRATEGY REPORT: {strategy.upper()}")
    print(sep)

    strat_row = conn.execute(
        "SELECT inception_date, benchmark FROM strategies WHERE name = ?", [strategy]
    ).fetchone()
    inception = strat_row[0] if strat_row else "unknown"
    benchmark = strat_row[1] if strat_row else "SPY"
    print(f"Inception: {inception}  |  Benchmark: {benchmark}  |  Report date: {date.today()}")

    # --- Account summary ---
    nav_row = conn.execute(
        "SELECT nav, cash, equity_value FROM daily_nav WHERE strategy = ? ORDER BY date DESC LIMIT 1",
        [strategy],
    ).fetchone()
    price_map: dict[str, float] = {}

    if client:
        try:
            nav = client.get_nav()
            positions = client.get_positions()
            tickers = list(positions.keys())
            if tickers:
                price_map = client.get_live_prices(tickers)
            equity = sum(price_map.get(t, 0) * q for t, q in positions.items())
            cash = nav - equity
            print(f"\nNAV (live): ${nav:>12,.2f}  |  Cash: ${cash:>10,.2f}  |  Equity: ${equity:>10,.2f}")
        except Exception as exc:
            print(f"\nWarning: could not fetch live IB data: {exc}")
            if nav_row:
                print(f"NAV (last): ${nav_row[0]:>12,.2f}  |  Cash: ${nav_row[1] or 0:>10,.2f}")
    elif nav_row:
        print(f"\nNAV (last): ${nav_row[0]:>12,.2f}  |  Cash: ${nav_row[1] or 0:>10,.2f}  "
              f"|  Equity: ${nav_row[2] or 0:>10,.2f}")
    else:
        print("\nNo NAV data recorded yet.")

    # --- Performance table ---
    print(f"\n{thin}")
    print("PERFORMANCE")
    print(thin)
    period_df = get_period_returns_table(conn, strategy)
    if period_df.empty:
        print("No NAV data yet.")
    else:
        print(f"  {'Period':<12}  {'Return':>9}")
        for _, row in period_df.iterrows():
            ret = row["return"]
            ret_str = f"{ret:+.2%}" if ret is not None and not (isinstance(ret, float) and math.isnan(ret)) else "N/A"
            print(f"  {row['period']:<12}  {ret_str:>9}")

    # --- Risk diagnostics ---
    print(f"\n{thin}")
    print("RISK DIAGNOSTICS (inception)")
    print(thin)
    stats = get_performance_stats(conn, strategy, "inception")
    if stats:
        def _fmt(val, pct=False):
            if val is None or (isinstance(val, float) and math.isnan(val)):
                return "N/A"
            return f"{val:+.2%}" if pct else f"{val:.4f}"

        print(f"  CAGR:      {_fmt(stats.get('cagr'), pct=True):>10}")
        print(f"  Ann Vol:   {_fmt(stats.get('ann_vol'), pct=True):>10}")
        print(f"  Sharpe:    {_fmt(stats.get('sharpe')):>10}")
        print(f"  Sortino:   {_fmt(stats.get('sortino')):>10}")
        print(f"  Max DD:    {_fmt(stats.get('max_dd'), pct=True):>10}")
        print(f"  Beta:      {_fmt(stats.get('beta')):>10}")
        print(f"  Win Rate:  {_fmt(stats.get('win_rate'), pct=True):>10}")
        print(f"  N Months:  {stats.get('n_months', 0):>10}")
    else:
        print("Insufficient data for risk metrics.")

    # --- Live vs backtest ---
    print(f"\n{thin}")
    print("LIVE vs BACKTEST")
    print(thin)
    cmp = compare_vs_backtest(conn, strategy)
    if cmp.empty:
        print("No backtest benchmarks registered. Use load_backtest_benchmarks() to add them.")
    else:
        portfolio = cmp["portfolio"].iloc[0]
        print(f"  Reference portfolio: {portfolio}")
        print(f"\n  {'Metric':<12}  {'Live':>10}  {'Backtest':>10}  {'Delta':>10}")
        pct_metrics = {"cagr", "ann_vol", "max_dd", "alpha", "win_rate"}
        for _, row in cmp.iterrows():
            m = row["metric"]
            fmt = lambda v: f"{v:+.2%}" if m in pct_metrics else f"{v:.4f}"
            live_s = fmt(row["live"]) if not math.isnan(row["live"]) else "N/A"
            bt_s   = fmt(row["backtest"]) if not math.isnan(row["backtest"]) else "N/A"
            dl_s   = fmt(row["delta"]) if not math.isnan(row["delta"]) else "N/A"
            print(f"  {m:<12}  {live_s:>10}  {bt_s:>10}  {dl_s:>10}")

    # --- Open positions ---
    print(f"\n{thin}")
    print("OPEN POSITIONS")
    print(thin)
    pos = get_open_positions(conn, strategy, price_map)
    if pos.empty:
        print("No open positions recorded.")
    else:
        print(f"  {len(pos)} position(s)")
        cols = ["ticker", "qty", "avg_cost", "current_price", "unrealized_pnl", "unrealized_pnl_pct"]
        display = pos[[c for c in cols if c in pos.columns]].copy()
        for col in ["avg_cost", "current_price"]:
            if col in display.columns:
                display[col] = display[col].map(lambda x: f"${x:.2f}" if pd.notna(x) else "N/A")
        if "unrealized_pnl" in display.columns:
            display["unrealized_pnl"] = display["unrealized_pnl"].map(
                lambda x: f"${x:+,.0f}" if pd.notna(x) else "N/A"
            )
        if "unrealized_pnl_pct" in display.columns:
            display["unrealized_pnl_pct"] = display["unrealized_pnl_pct"].map(
                lambda x: f"{x:+.2%}" if pd.notna(x) else "N/A"
            )
        print(display.to_string(index=False))

    # --- Realized P&L and tax ---
    print(f"\n{thin}")
    print("REALIZED P&L & TAX ESTIMATE")
    print(thin)
    pnl = get_pnl_summary(conn, strategy)
    print(f"  Short-term realized:  ${pnl['realized_st']:>12,.2f}  (tax @24%: ${pnl['tax_st']:>10,.2f})")
    print(f"  Long-term realized:   ${pnl['realized_lt']:>12,.2f}  (tax @15%: ${pnl['tax_lt']:>10,.2f})")
    print(f"  Total realized:       ${pnl['total_realized']:>12,.2f}")
    print(f"  Estimated total tax:  ${pnl['total_tax']:>12,.2f}")
    print(f"  Net after-tax gain:   ${pnl['net_after_tax']:>12,.2f}")

    # --- Slippage ---
    print(f"\n{thin}")
    print("SLIPPAGE ANALYSIS")
    print(thin)
    slip = get_slippage_summary(conn, strategy)
    if slip["n_fills"] == 0:
        print("No fills with reference prices yet.")
        print("Reference prices are set from the live_scores CSV at rebalance time.")
    else:
        vs = slip["vs_backtest_bps"]
        vs_label = f"{vs:+.1f} bps {'worse' if vs > 0 else 'better'} than assumed"
        print(f"  Fills with reference price:  {slip['n_fills']}")
        print(f"  Avg slippage:               {slip['avg_slippage_bps']:+.2f} bps")
        print(f"  Median slippage:            {slip['median_slippage_bps']:+.2f} bps")
        print(f"  Total slippage cost:        ${slip['total_slippage_dollars']:>10,.2f}")
        print(f"  Backtest TC assumption:     {slip['backtest_assumption_bps']:.0f} bps")
        print(f"  vs backtest:                {vs_label}")

    # --- Model IC ---
    print(f"\n{thin}")
    print("MODEL IC (last 6 months)")
    print(thin)
    ic_df = get_ic_series(conn, strategy)
    if ic_df.empty:
        print("No score snapshots with forward returns yet.")
        print("Run: update_forward_returns(conn, strategy) after 30 days.")
    else:
        recent = ic_df.tail(6)
        print(f"  {'Month':<12}  {'IC':>8}  {'N':>6}  {'p-value':>10}")
        for _, row in recent.iterrows():
            snap = str(row["snapshot_date"])[:7]
            sig = "*" if row["p_value"] < 0.05 else " "
            print(f"  {snap:<12}  {row['ic']:>+8.4f}  {row['n_stocks']:>6}  {row['p_value']:>10.4f} {sig}")
        mean_ic = ic_df["ic"].mean()
        print(f"\n  Mean IC (all): {mean_ic:+.4f}  ({len(ic_df)} months)")

    print(f"\n{sep}\n")


# ---------------------------------------------------------------------------
# Jupyter query functions
# ---------------------------------------------------------------------------

def get_trades(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    ticker: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> pd.DataFrame:
    return get_trade_history(conn, strategy, ticker=ticker, from_date=from_date, to_date=to_date)


def get_positions(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    price_map: dict[str, float] | None = None,
) -> pd.DataFrame:
    return get_open_positions(conn, strategy, price_map=price_map)


def get_performance(conn: duckdb.DuckDBPyConnection, strategy: str) -> pd.DataFrame:
    return get_period_returns_table(conn, strategy)


def get_tax_summary(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    year: int | None = None,
) -> pd.DataFrame:
    """Return closed lot details for tax reporting.

    Columns: ticker, open_date, close_date, holding_days, cost_basis, proceeds,
             realized_pnl, is_long_term, tax_rate, tax_owed
    """
    where = ["strategy = ? AND close_date IS NOT NULL"]
    params: list = [strategy]
    if year:
        where.append("YEAR(close_date) = ?")
        params.append(year)

    df = conn.execute(
        f"SELECT ticker, open_date, close_date, qty, open_price, close_price, "
        f"realized_pnl, is_long_term, tax_rate, "
        f"CAST(close_date AS DATE) - CAST(open_date AS DATE) AS holding_days "
        f"FROM tax_lots "
        f"WHERE {' AND '.join(where)} "
        f"ORDER BY close_date, ticker",
        params,
    ).df()

    if df.empty:
        return df

    df["cost_basis"] = df["open_price"] * df["qty"]
    df["proceeds"]   = df["close_price"] * df["qty"]
    df["tax_owed"]   = df["realized_pnl"].clip(lower=0) * df["tax_rate"]
    df["open_date"]  = pd.to_datetime(df["open_date"])
    df["close_date"] = pd.to_datetime(df["close_date"])

    return df[[
        "ticker", "open_date", "close_date", "holding_days", "qty",
        "cost_basis", "proceeds", "realized_pnl", "is_long_term", "tax_rate", "tax_owed",
    ]]
