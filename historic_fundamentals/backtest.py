"""
True monthly portfolio backtest for the fundamentals-alpha stock-selection model.

Uses NON-OVERLAPPING 1-month holding-period returns, rebalancing monthly.
Each month: score stocks at month-end, hold to next month-end, compute equal-weight
portfolio return, subtract transaction costs.

Public API
----------
run_monthly_backtest()        Run portfolio backtest for multiple portfolio configs.
portfolio_metrics()           Compute standard performance/risk metrics.
compute_universe_benchmark()  Equal-weight universe return each month.
load_spy_returns()            Load SPY monthly returns from prices.duckdb.

PORTFOLIO_CONFIGS             Default portfolio configurations.
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
import pandas as pd


PORTFOLIO_CONFIGS: dict[str, float | int] = {
    "top_pct_20": 0.20,
    "top_pct_10": 0.10,
    "top_n_50": 50,
    "top_n_25": 25,
}


def _select_top(grp: pd.DataFrame, score_col: str, config_val: float | int) -> pd.DataFrame:
    """Select top stocks from a monthly cross-section by score."""
    grp = grp.dropna(subset=[score_col]).sort_values(score_col, ascending=False)
    if isinstance(config_val, float) and config_val <= 1.0:
        n = max(1, int(np.ceil(len(grp) * config_val)))
    else:
        n = int(config_val)
    return grp.head(n)


def run_monthly_backtest(
    df: pd.DataFrame,
    score_col: str,
    price_col: str = "price",
    date_col: str = "month_end_date",
    ticker_col: str = "ticker",
    tc_bps: float = 10.0,
    portfolios: Optional[dict] = None,
) -> dict[str, pd.DataFrame]:
    """
    Run a true monthly portfolio backtest with non-overlapping 1-month returns.

    Weighting: all portfolios are equal-weight. Capped-weight portfolios
    (e.g., max 5% per position) are deferred to Phase 7 risk diagnostics,
    where position concentration limits are configured as guardrails.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain date_col, ticker_col, score_col, price_col.
        Each row is one stock at one month-end.
    score_col : str
        Column used to rank stocks. Higher = better.
    price_col : str
        Month-end price column.
    date_col : str
        Month-end date column.
    ticker_col : str
        Ticker column.
    tc_bps : float
        One-way transaction cost in basis points per trade. Default 10.
    portfolios : dict or None
        Maps portfolio name -> selection criterion.
        float <= 1.0: top fraction of universe.
        int > 1: top N names.
        Defaults to PORTFOLIO_CONFIGS.

    Returns
    -------
    dict[str, pd.DataFrame]
        One key per portfolio. Each DataFrame has columns:
        date, gross_return, tc_cost, net_return, turnover, n_stocks
    """
    if portfolios is None:
        portfolios = PORTFOLIO_CONFIGS

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])

    # Build a price lookup: ticker -> date -> price
    price_pivot = (
        df[[date_col, ticker_col, price_col]]
        .dropna(subset=[price_col])
        .drop_duplicates(subset=[date_col, ticker_col])
        .pivot(index=date_col, columns=ticker_col, values=price_col)
    )
    sorted_dates = sorted(price_pivot.index)

    results: dict[str, pd.DataFrame] = {}

    for port_name, config_val in portfolios.items():
        rows = []
        prev_holdings: set = set()

        for i, t0 in enumerate(sorted_dates[:-1]):
            t1 = sorted_dates[i + 1]

            # Stocks available at t0 with valid scores
            universe_t0 = df[df[date_col] == t0].copy()
            selected = _select_top(universe_t0, score_col, config_val)
            holdings_t0 = set(selected[ticker_col].tolist())

            if not holdings_t0:
                continue

            # Compute equal-weight 1-month returns: price_{t1} / price_{t0} - 1
            stock_returns = []
            for tkr in holdings_t0:
                p0 = price_pivot.at[t0, tkr] if tkr in price_pivot.columns else np.nan
                p1 = price_pivot.at[t1, tkr] if tkr in price_pivot.columns else np.nan
                if np.isfinite(p0) and np.isfinite(p1) and p0 > 0:
                    stock_returns.append(p1 / p0 - 1.0)

            if not stock_returns:
                prev_holdings = holdings_t0
                continue

            gross_return = float(np.mean(stock_returns))

            # Turnover: fraction of portfolio that changed from prior month
            if prev_holdings:
                unchanged = len(holdings_t0 & prev_holdings)
                n_port = len(holdings_t0)
                turnover = 1.0 - unchanged / n_port
            else:
                # First period: full turnover (buying everything new)
                turnover = 1.0

            tc_cost = turnover * tc_bps * 1e-4
            net_return = gross_return - tc_cost

            rows.append({
                "date": t1,
                "gross_return": gross_return,
                "tc_cost": tc_cost,
                "net_return": net_return,
                "turnover": turnover,
                "n_stocks": len(stock_returns),
            })
            prev_holdings = holdings_t0

        results[port_name] = pd.DataFrame(rows)
        if not results[port_name].empty:
            results[port_name] = results[port_name].set_index("date")

    return results


def portfolio_metrics(
    returns_series: pd.Series,
    spy_returns: Optional[pd.Series] = None,
    rf: float = 0.0,
    periods_per_year: int = 12,
) -> dict:
    """
    Compute standard performance and risk metrics for a monthly returns series.

    Parameters
    ----------
    returns_series : pd.Series
        Monthly net returns (not prices, not cumulative). Each value is
        the portfolio return for that month.
    spy_returns : pd.Series or None
        Monthly SPY returns for benchmark comparison. Must share an index
        compatible with returns_series (intersection used).
    rf : float
        Annual risk-free rate. Default 0.0.
    periods_per_year : int
        Number of return periods per year. Default 12 (monthly).

    Returns
    -------
    dict with keys:
        n_months, total_return, cagr, ann_vol, sharpe, sortino,
        max_drawdown, monthly_win_rate,
        beta (if spy_returns), alpha (if spy_returns),
        info_ratio (if spy_returns), tracking_error (if spy_returns)
    """
    rets = returns_series.dropna()
    n = len(rets)
    if n == 0:
        return {"n_months": 0, "total_return": np.nan, "cagr": np.nan,
                "ann_vol": np.nan, "sharpe": np.nan, "sortino": np.nan,
                "max_drawdown": np.nan, "monthly_win_rate": np.nan}

    total_return = float((1 + rets).prod() - 1.0)
    cagr = float((1.0 + total_return) ** (periods_per_year / n) - 1.0)

    rf_monthly = rf / periods_per_year
    excess = rets - rf_monthly
    ann_vol = float(rets.std(ddof=1) * np.sqrt(periods_per_year))
    sharpe = float(excess.mean() * periods_per_year / (rets.std(ddof=1) * np.sqrt(periods_per_year))) if rets.std() > 0 else np.nan

    # Sortino: use downside deviation (negative excess returns only)
    downside = excess[excess < 0]
    if len(downside) > 1:
        downside_std = float(downside.std(ddof=1))
        sortino = float(excess.mean() * periods_per_year / (downside_std * np.sqrt(periods_per_year))) if downside_std > 0 else np.nan
    else:
        sortino = np.nan

    # Max drawdown on cumulative return series
    cum = (1 + rets).cumprod()
    rolling_max = cum.cummax()
    drawdowns = (cum - rolling_max) / rolling_max
    max_drawdown = float(drawdowns.min())

    monthly_win_rate = float((rets > 0).mean())

    metrics = {
        "n_months": n,
        "total_return": total_return,
        "cagr": cagr,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "monthly_win_rate": monthly_win_rate,
    }

    if spy_returns is not None:
        # Align on overlapping dates
        common = rets.index.intersection(spy_returns.index)
        if len(common) >= 2:
            p = rets.loc[common]
            s = spy_returns.loc[common].dropna()
            common2 = p.index.intersection(s.index)
            p = p.loc[common2]
            s = s.loc[common2]

            if len(common2) >= 2:
                var_spy = float(s.var(ddof=1))
                beta = float(np.cov(p.values, s.values, ddof=1)[0, 1] / var_spy) if var_spy > 0 else np.nan
                # Alpha: annualized excess return relative to beta-adjusted SPY
                spy_cagr = float((1 + s).prod() ** (periods_per_year / len(s)) - 1.0)
                port_cagr = float((1 + p).prod() ** (periods_per_year / len(p)) - 1.0)
                alpha = float(port_cagr - (rf + beta * (spy_cagr - rf))) if np.isfinite(beta) else np.nan

                active = p.values - s.values
                tracking_error = float(np.std(active, ddof=1) * np.sqrt(periods_per_year))
                info_ratio = float(np.mean(active) * periods_per_year / tracking_error) if tracking_error > 0 else np.nan

                metrics["beta"] = beta
                metrics["alpha"] = alpha
                metrics["tracking_error"] = tracking_error
                metrics["info_ratio"] = info_ratio

    return metrics


def compute_universe_benchmark(
    df: pd.DataFrame,
    price_col: str = "price",
    date_col: str = "month_end_date",
    ticker_col: str = "ticker",
) -> pd.Series:
    """
    Compute equal-weight universe benchmark return for each month.

    At each month t0, the universe consists of all stocks in df at t0.
    Return for period [t0, t1] = equal-weight mean of price_{t1}/price_{t0} - 1.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain date_col, ticker_col, price_col.
        Assumed to already be filtered by filter_universe().

    Returns
    -------
    pd.Series
        Monthly returns indexed by t1 (end of holding period).
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])

    price_pivot = (
        df[[date_col, ticker_col, price_col]]
        .dropna(subset=[price_col])
        .drop_duplicates(subset=[date_col, ticker_col])
        .pivot(index=date_col, columns=ticker_col, values=price_col)
    )
    sorted_dates = sorted(price_pivot.index)

    rows = {}
    for i, t0 in enumerate(sorted_dates[:-1]):
        t1 = sorted_dates[i + 1]
        p0 = price_pivot.loc[t0].dropna()
        p1 = price_pivot.loc[t1].reindex(p0.index).dropna()
        common = p0.index.intersection(p1.index)
        if len(common) == 0:
            continue
        stock_rets = p1[common] / p0[common] - 1.0
        rows[t1] = float(stock_rets.mean())

    return pd.Series(rows, name="universe_benchmark")


def load_spy_returns(
    prices_db_path: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.Series:
    """
    Load SPY monthly returns from prices.duckdb.

    Computes month-end SPY prices (last trading day of each month) and
    returns the month-over-month return series.

    Parameters
    ----------
    prices_db_path : str or None
        Path to prices.duckdb. Defaults to env var PRICES_DB_PATH.
    start_date : str or None
        Optional ISO date string to filter from.
    end_date : str or None
        Optional ISO date string to filter to.

    Returns
    -------
    pd.Series
        Monthly returns indexed by month-end date (last trading day of each month).
    """
    if prices_db_path is None:
        prices_db_path = os.environ.get("PRICES_DB_PATH")
    if not prices_db_path:
        raise ValueError("prices_db_path must be provided or PRICES_DB_PATH env var must be set.")

    import duckdb
    conn = duckdb.connect(prices_db_path, read_only=True)

    where_clauses = ["ticker = 'SPY'"]
    params = []
    if start_date:
        where_clauses.append("date >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where_clauses)

    spy = conn.execute(
        f"SELECT date, adj_close FROM stock_prices WHERE {where_sql} ORDER BY date",
        params,
    ).df()
    conn.close()

    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.set_index("date").sort_index()

    # Month-end prices: last available trading day per calendar month
    spy_monthly = spy["adj_close"].resample("ME").last().dropna()

    # Month-over-month return
    spy_returns = spy_monthly.pct_change().dropna()
    spy_returns.index.name = "month_end_date"
    spy_returns.name = "spy_return"

    return spy_returns
