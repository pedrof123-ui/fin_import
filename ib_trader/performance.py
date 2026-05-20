from __future__ import annotations

import math
from datetime import date, timedelta

import duckdb
import numpy as np
import pandas as pd

_RF_ANNUAL = 0.05  # risk-free rate assumption


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _calc_stats(returns: pd.Series) -> dict:
    """Compute annualised performance stats from a monthly returns Series."""
    n = len(returns)
    if n < 2:
        return {"n_months": n}

    rf_monthly = _RF_ANNUAL / 12
    mean_ret = returns.mean()
    std_ret = returns.std(ddof=1)

    total_return = (1 + returns).prod() - 1
    years = n / 12
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else float("nan")
    ann_vol = std_ret * math.sqrt(12)
    sharpe = ((mean_ret - rf_monthly) / std_ret) * math.sqrt(12) if std_ret > 0 else float("nan")

    downside = returns[returns < rf_monthly] - rf_monthly
    down_std = math.sqrt((downside ** 2).mean()) if len(downside) > 0 else 0.0
    sortino = ((mean_ret - rf_monthly) / down_std) * math.sqrt(12) if down_std > 0 else float("nan")

    wealth = (1 + returns).cumprod()
    peak = wealth.cummax()
    max_dd = float(((wealth - peak) / peak).min())

    return {
        "cagr": cagr,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": max_dd,
        "win_rate": float((returns > 0).mean()),
        "n_months": n,
        "total_return": total_return,
    }


def _get_benchmark_monthly(benchmark: str, start: date, end: date) -> pd.Series:
    """Fetch monthly returns for the benchmark ticker via yfinance."""
    import yfinance as yf

    data = yf.download(
        benchmark,
        start=str(start - timedelta(days=35)),
        end=str(end + timedelta(days=1)),
        auto_adjust=True,
        progress=False,
        actions=False,
    )
    if data.empty:
        return pd.Series(dtype=float)
    close = data["Close"].squeeze()
    monthly = close.resample("ME").last()
    return monthly.pct_change().dropna()


def _nav_to_daily(conn: duckdb.DuckDBPyConnection, strategy: str) -> pd.Series:
    df = conn.execute(
        "SELECT date, nav FROM daily_nav WHERE strategy = ? ORDER BY date",
        [strategy],
    ).df()
    if df.empty:
        return pd.Series(dtype=float, name="nav")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["nav"].sort_index()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_open_positions(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    price_map: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Return open positions with cost basis and optional unrealised P&L."""
    df = conn.execute(
        "SELECT ticker, SUM(qty_remaining) AS qty, "
        "SUM(open_price * qty_remaining) / SUM(qty_remaining) AS avg_cost "
        "FROM tax_lots "
        "WHERE strategy = ? AND qty_remaining > 0 "
        "GROUP BY ticker "
        "HAVING SUM(qty_remaining) > 0 "
        "ORDER BY ticker",
        [strategy],
    ).df()

    if df.empty:
        return df

    price_map = price_map or {}
    df["current_price"] = df["ticker"].map(price_map)
    df["unrealized_pnl"] = np.where(
        df["current_price"].notna(),
        (df["current_price"] - df["avg_cost"]) * df["qty"],
        float("nan"),
    )
    df["unrealized_pnl_pct"] = np.where(
        df["current_price"].notna(),
        (df["current_price"] - df["avg_cost"]) / df["avg_cost"],
        float("nan"),
    )
    total_equity = (df["current_price"] * df["qty"]).sum()
    df["weight_pct"] = np.where(
        total_equity > 0,
        df["current_price"] * df["qty"] / total_equity,
        float("nan"),
    )
    return df


def get_pnl_summary(conn: duckdb.DuckDBPyConnection, strategy: str) -> dict:
    """Return realised P&L and estimated tax for the strategy."""
    row = conn.execute(
        "SELECT "
        "COALESCE(SUM(CASE WHEN is_long_term = false THEN realized_pnl END), 0) AS realized_st, "
        "COALESCE(SUM(CASE WHEN is_long_term = true  THEN realized_pnl END), 0) AS realized_lt, "
        "COALESCE(SUM(realized_pnl), 0) AS total_realized "
        "FROM tax_lots "
        "WHERE strategy = ? AND close_date IS NOT NULL",
        [strategy],
    ).fetchone()
    realized_st, realized_lt, total_realized = row
    tax_st = max(realized_st, 0) * 0.24
    tax_lt = max(realized_lt, 0) * 0.15
    return {
        "realized_st": realized_st,
        "realized_lt": realized_lt,
        "total_realized": total_realized,
        "tax_st": tax_st,
        "tax_lt": tax_lt,
        "total_tax": tax_st + tax_lt,
        "net_after_tax": total_realized - tax_st - tax_lt,
    }


def get_monthly_returns(conn: duckdb.DuckDBPyConnection, strategy: str) -> pd.Series:
    """Return monthly returns (month-end) derived from daily_nav."""
    nav = _nav_to_daily(conn, strategy)
    if nav.empty:
        return pd.Series(dtype=float)
    monthly = nav.resample("ME").last()
    return monthly.pct_change().dropna()


def get_performance_stats(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    period: str = "inception",
) -> dict:
    """Compute annualised performance stats for the given period.

    period: "inception" | "1y" | "ytd" | "month" | "week"
    Returns dict with cagr, ann_vol, sharpe, sortino, max_dd, beta, win_rate, n_months.
    """
    nav = _nav_to_daily(conn, strategy)
    if nav.empty:
        return {}

    today = pd.Timestamp.now().normalize()
    if period == "1y":
        nav = nav[nav.index >= today - pd.Timedelta(days=365)]
    elif period == "ytd":
        nav = nav[nav.index >= pd.Timestamp(today.year, 1, 1)]
    elif period == "month":
        nav = nav[nav.index >= today - pd.Timedelta(days=30)]
    elif period == "week":
        nav = nav[nav.index >= today - pd.Timedelta(days=7)]
    # inception: use all data

    if len(nav) < 2:
        return {"period": period, "n_months": 0}

    monthly = nav.resample("ME").last().pct_change().dropna()
    stats = _calc_stats(monthly)
    stats["period"] = period

    # Beta vs benchmark
    if len(monthly) >= 2:
        bmark_ticker = conn.execute(
            "SELECT benchmark FROM strategies WHERE name = ?", [strategy]
        ).fetchone()
        benchmark = bmark_ticker[0] if bmark_ticker else "SPY"
        try:
            bmark_ret = _get_benchmark_monthly(benchmark, nav.index[0].date(), nav.index[-1].date())
            aligned = monthly.align(bmark_ret, join="inner")[0], monthly.align(bmark_ret, join="inner")[1]
            strat_a, bmark_a = aligned
            if len(strat_a) >= 2:
                cov = np.cov(strat_a.values, bmark_a.values)
                stats["beta"] = cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else float("nan")
                stats["alpha"] = (strat_a.mean() - stats["beta"] * bmark_a.mean()) * 12
            else:
                stats["beta"] = float("nan")
                stats["alpha"] = float("nan")
        except Exception:
            stats["beta"] = float("nan")
            stats["alpha"] = float("nan")

    return stats


def get_period_returns_table(conn: duckdb.DuckDBPyConnection, strategy: str) -> pd.DataFrame:
    """Return simple returns for week/month/ytd/1y/inception from daily_nav."""
    nav = _nav_to_daily(conn, strategy)
    if nav.empty:
        return pd.DataFrame(columns=["period", "return"])

    last_nav = float(nav.iloc[-1])
    today = pd.Timestamp.now().normalize()

    def _ret(days: int | None = None, since: pd.Timestamp | None = None) -> float | None:
        if since is not None:
            subset = nav[nav.index >= since]
        elif days is not None:
            subset = nav[nav.index >= today - pd.Timedelta(days=days)]
        else:
            subset = nav
        if len(subset) < 2:
            return None
        return (last_nav / float(subset.iloc[0])) - 1

    ytd_start = pd.Timestamp(today.year, 1, 1)
    rows = [
        {"period": "week",      "return": _ret(7)},
        {"period": "month",     "return": _ret(30)},
        {"period": "ytd",       "return": _ret(since=ytd_start)},
        {"period": "1 year",    "return": _ret(365)},
        {"period": "inception", "return": _ret()},
    ]
    return pd.DataFrame(rows)


def get_ic_series(conn: duckdb.DuckDBPyConnection, strategy: str) -> pd.DataFrame:
    """Compute monthly Spearman IC between model scores and forward returns."""
    from scipy import stats as scipy_stats

    df = conn.execute(
        "SELECT snapshot_date, score, forward_return FROM score_snapshots "
        "WHERE strategy = ? AND forward_return IS NOT NULL AND score IS NOT NULL "
        "ORDER BY snapshot_date",
        [strategy],
    ).df()

    if df.empty:
        return pd.DataFrame(columns=["snapshot_date", "ic", "n_stocks", "p_value"])

    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    results = []
    for snap_date, group in df.groupby("snapshot_date"):
        if len(group) < 5:
            continue
        corr, pval = scipy_stats.spearmanr(group["score"], group["forward_return"])
        results.append({
            "snapshot_date": snap_date,
            "ic": float(corr),
            "n_stocks": len(group),
            "p_value": float(pval),
        })

    return pd.DataFrame(results)


def compare_vs_backtest(conn: duckdb.DuckDBPyConnection, strategy: str) -> pd.DataFrame:
    """Compare live performance stats against registered backtest benchmarks."""
    bench_df = conn.execute(
        "SELECT portfolio, cagr, ann_vol, sharpe, sortino, max_dd, beta, alpha, win_rate "
        "FROM backtest_benchmarks WHERE strategy = ?",
        [strategy],
    ).df()

    if bench_df.empty:
        return pd.DataFrame(columns=["metric", "live", "backtest", "delta"])

    live = get_performance_stats(conn, strategy, period="inception")
    metrics = ["cagr", "ann_vol", "sharpe", "sortino", "max_dd", "beta", "alpha", "win_rate"]
    bench_row = bench_df.iloc[0]

    rows = []
    for m in metrics:
        live_val = live.get(m, float("nan"))
        bt_val = bench_row.get(m, float("nan"))
        delta = live_val - bt_val if (not math.isnan(live_val) and not math.isnan(bt_val)) else float("nan")
        rows.append({
            "metric": m,
            "portfolio": bench_row["portfolio"],
            "live": live_val,
            "backtest": bt_val,
            "delta": delta,
        })
    return pd.DataFrame(rows)


def get_slippage_summary(conn: duckdb.DuckDBPyConnection, strategy: str) -> dict:
    """Compute slippage stats vs reference prices (from live_scores CSV).

    Slippage convention: positive = worse than expected (paid more on BUY / received less on SELL).
    BUY slippage  = fill_price - reference_price
    SELL slippage = reference_price - fill_price
    """
    df = conn.execute(
        "SELECT action, qty, fill_price, reference_price FROM fills "
        "WHERE strategy = ? AND reference_price IS NOT NULL AND reference_price > 0",
        [strategy],
    ).df()

    if df.empty:
        return {"n_fills": 0, "note": "No fills with reference prices yet."}

    df["slippage"] = df.apply(
        lambda r: r["fill_price"] - r["reference_price"] if r["action"] == "BUY"
                  else r["reference_price"] - r["fill_price"],
        axis=1,
    )
    df["slippage_bps"] = df["slippage"] / df["reference_price"] * 10_000
    df["slippage_dollars"] = df["slippage"] * df["qty"]

    backtest_assumption_bps = 10.0
    avg_bps = float(df["slippage_bps"].mean())
    return {
        "n_fills": len(df),
        "avg_slippage_bps": avg_bps,
        "median_slippage_bps": float(df["slippage_bps"].median()),
        "total_slippage_dollars": float(df["slippage_dollars"].sum()),
        "backtest_assumption_bps": backtest_assumption_bps,
        "vs_backtest_bps": avg_bps - backtest_assumption_bps,
    }


def get_trade_history(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    ticker: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> pd.DataFrame:
    """Return fill history with realized P&L for SELL fills."""
    where = ["f.strategy = ?"]
    params: list = [strategy]

    if ticker:
        where.append("f.ticker = ?")
        params.append(ticker)
    if from_date:
        where.append("f.fill_time >= ?")
        params.append(str(from_date))
    if to_date:
        where.append("f.fill_time <= ?")
        params.append(str(to_date))

    df = conn.execute(
        f"SELECT f.fill_time, f.ticker, f.action, f.qty, f.fill_price, f.commission, "
        f"COALESCE(SUM(tl.realized_pnl), 0) AS realized_pnl, "
        f"MAX(tl.is_long_term) AS is_long_term, "
        f"CASE WHEN f.action='SELL' THEN "
        f"  MAX(CAST(tl.close_date AS DATE) - CAST(tl.open_date AS DATE)) END AS holding_days "
        f"FROM fills f "
        f"LEFT JOIN tax_lots tl ON tl.strategy = f.strategy AND tl.ticker = f.ticker "
        f"  AND tl.close_date = CAST(f.fill_time AS DATE) "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY f.fill_time, f.ticker, f.action, f.qty, f.fill_price, f.commission "
        f"ORDER BY f.fill_time DESC",
        params,
    ).df()

    if not df.empty:
        df["fill_time"] = pd.to_datetime(df["fill_time"])

    return df
