"""Compute and store rolling OLS betas for tracked stocks against VTI.

Public API:
    get_beta(ticker, as_of_date, window_days, db_path)  -> float | None
    backfill_betas(tickers, window_days, db_path)        -> int  (rows written)
    refresh_betas(window_days, db_path)                  -> int  (rows written)

CLI:
    uv run features/beta/beta.py backfill [--ticker AAPL] [--window 260]
    uv run features/beta/beta.py refresh [--window 260]   # no --window: refreshes both
    uv run features/beta/beta.py show AAPL
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PRICES_DB = Path("/home/pedro/projects/trade_systems/data/prices.duckdb")
WINDOW_2YR = 104       # 2 years of weekly returns
WINDOW_5YR = 260       # 5 years of weekly returns
# NOTE: `ticker_betas` also holds a window_days=504 series, 1,454 tickers, stale since 2026-06-01.
# NOTHING READS IT — only WINDOW_5YR (drives cost of equity in dcf/wacc.py) and WINDOW_2YR
# (reported in WaccDetail) are ever queried. It is dead data left from an earlier experiment, not
# a maintained series; `refresh` deliberately does not update it. Verified 2026-08-23.
DEFAULT_WINDOW = WINDOW_5YR
MIN_OBS = 26           # ~6 months of weekly data; return None below this threshold

_CREATE_BETAS_SQL = """
CREATE TABLE IF NOT EXISTS ticker_betas (
    ticker        VARCHAR  NOT NULL,
    computed_date DATE     NOT NULL,
    window_days   INTEGER  NOT NULL,
    beta          DOUBLE,
    r_squared     DOUBLE,
    n_obs         INTEGER,
    PRIMARY KEY (ticker, computed_date, window_days)
)
"""

_UPSERT_BETAS_SQL = """
INSERT INTO ticker_betas (ticker, computed_date, window_days, beta, r_squared, n_obs)
    SELECT ticker, computed_date, window_days, beta, r_squared, n_obs
    FROM rows_to_insert
ON CONFLICT (ticker, computed_date, window_days) DO UPDATE SET
    beta      = excluded.beta,
    r_squared = excluded.r_squared,
    n_obs     = excluded.n_obs
"""


def _open(db_path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(db_path), read_only=read_only)
    if not read_only:
        conn.execute(_CREATE_BETAS_SQL)
    return conn


def _load_returns(db_path: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Load weekly log returns for all stock tickers and VTI (Friday close).

    Returns:
        stock_ret: DataFrame (index=date, columns=tickers), weekly log returns
        vti_ret:   Series (index=date), VTI weekly log returns
    """
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        stocks = conn.execute(
            "SELECT ticker, date, adj_close FROM stock_prices ORDER BY ticker, date"
        ).df()
        vti = conn.execute(
            "SELECT date, adj_close FROM etf_prices WHERE ticker = 'VTI' ORDER BY date"
        ).df()
    finally:
        conn.close()

    if vti.empty:
        raise RuntimeError("VTI has no rows in etf_prices — run the VTI backfill first")

    # Pivot to wide, resample to weekly (Friday close), compute log returns
    wide = stocks.pivot(index="date", columns="ticker", values="adj_close")
    wide.index = pd.to_datetime(wide.index)
    wide = wide.resample("W-FRI").last()
    stock_ret = np.log(wide / wide.shift(1)).dropna(how="all")

    vti = vti.set_index("date").sort_index()
    vti.index = pd.to_datetime(vti.index)
    vti_weekly = vti["adj_close"].resample("W-FRI").last().dropna()
    vti_ret = np.log(vti_weekly / vti_weekly.shift(1)).dropna()
    vti_ret.name = "VTI"

    return stock_ret, vti_ret


def _ols_beta(y: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    """OLS beta and R² from aligned return arrays."""
    cov = np.cov(y, x, ddof=1)
    beta = cov[0, 1] / cov[1, 1]
    corr = np.corrcoef(y, x)[0, 1]
    r2 = corr ** 2
    return float(beta), float(r2)


def _month_ends(index: pd.DatetimeIndex | pd.Index) -> list[date]:
    """Return sorted list of month-end dates present in index."""
    dt = pd.to_datetime(index)
    series = pd.Series(dt, index=dt)
    # resample to month-end, pick the last actual trading day in each month
    ends = series.resample("ME").last().dropna()
    return [d.date() for d in ends]


def _compute_snapshots(
    ticker: str,
    stock_ret: pd.DataFrame,
    vti_ret: pd.Series,
    window_days: int,
) -> list[dict]:
    """Return list of beta-row dicts for all month-ends with sufficient data."""
    if ticker not in stock_ret.columns:
        return []

    s = stock_ret[ticker].dropna()
    aligned = pd.concat([s, vti_ret], axis=1, join="inner").dropna()
    if len(aligned) < MIN_OBS:
        return []

    aligned.columns = ["stock", "vti"]
    dates = _month_ends(aligned.index)
    rows = []
    for d in dates:
        window = aligned[aligned.index.date <= d].tail(window_days)
        n = len(window)
        if n < MIN_OBS:
            continue
        beta, r2 = _ols_beta(window["stock"].values, window["vti"].values)
        rows.append({
            "ticker": ticker,
            "computed_date": d,
            "window_days": window_days,
            "beta": beta,
            "r_squared": r2,
            "n_obs": n,
        })
    return rows


def backfill_betas(
    tickers: list[str] | None = None,
    window_days: int = DEFAULT_WINDOW,
    db_path: Path = PRICES_DB,
) -> int:
    """Compute monthly beta snapshots from inception to today for all (or given) tickers.

    Returns the number of rows written.
    """
    stock_ret, vti_ret = _load_returns(db_path)

    if tickers is None:
        tickers = list(stock_ret.columns)
    else:
        tickers = [t for t in tickers if t in stock_ret.columns]

    all_rows: list[dict] = []
    for ticker in tickers:
        all_rows.extend(_compute_snapshots(ticker, stock_ret, vti_ret, window_days))

    if not all_rows:
        print("No beta rows to write.")
        return 0

    df = pd.DataFrame(all_rows)
    conn = _open(db_path)
    try:
        conn.register("rows_to_insert", df)
        conn.execute(_UPSERT_BETAS_SQL)
    finally:
        conn.close()

    print(f"Wrote {len(df)} beta rows for {len(tickers)} ticker(s).")
    return len(df)


def refresh_betas(
    window_days: int = DEFAULT_WINDOW,
    db_path: Path = PRICES_DB,
) -> int:
    """Compute the current month-end beta for all tracked tickers.

    Called by the daily cron job. Upserts one row per ticker.
    """
    stock_ret, vti_ret = _load_returns(db_path)
    today = date.today()
    rows = []
    no_data = []

    for ticker in stock_ret.columns:
        s = stock_ret[ticker].dropna()
        aligned = pd.concat([s, vti_ret], axis=1, join="inner").dropna()
        aligned.columns = ["stock", "vti"]
        window = aligned[aligned.index.date <= today].tail(window_days)
        n = len(window)
        if n < MIN_OBS:
            no_data.append(ticker)
            continue
        beta, r2 = _ols_beta(window["stock"].values, window["vti"].values)
        rows.append({
            "ticker": ticker,
            "computed_date": today,
            "window_days": window_days,
            "beta": beta,
            "r_squared": r2,
            "n_obs": n,
        })

    if no_data:
        print(f"Skipped {len(no_data)} tickers with insufficient history: {no_data[:10]}{'...' if len(no_data) > 10 else ''}")

    if not rows:
        print("No beta rows to write.")
        return 0

    df = pd.DataFrame(rows)
    conn = _open(db_path)
    try:
        conn.register("rows_to_insert", df)
        conn.execute(_UPSERT_BETAS_SQL)
    finally:
        conn.close()

    print(f"Refreshed {len(df)} beta rows.")
    return len(df)


def get_beta(
    ticker: str,
    as_of_date: date | None = None,
    window_days: int = DEFAULT_WINDOW,
    db_path: Path = PRICES_DB,
) -> float | None:
    """Return the stored beta for ticker as of as_of_date (latest if None)."""
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        if as_of_date is None:
            row = conn.execute(
                """
                SELECT beta FROM ticker_betas
                WHERE ticker = ? AND window_days = ?
                ORDER BY computed_date DESC LIMIT 1
                """,
                [ticker, window_days],
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT beta FROM ticker_betas
                WHERE ticker = ? AND window_days = ? AND computed_date <= ?
                ORDER BY computed_date DESC LIMIT 1
                """,
                [ticker, window_days, as_of_date],
            ).fetchone()
    finally:
        conn.close()

    return float(row[0]) if row else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_backfill(args: argparse.Namespace) -> None:
    tickers = [args.ticker] if args.ticker else None
    backfill_betas(tickers=tickers, window_days=args.window, db_path=PRICES_DB)


def _cmd_refresh(args: argparse.Namespace) -> None:
    # Both windows: wacc.get_betas() reads 260d (drives cost of equity) and 104d
    # (reported in WaccDetail). Refreshing only the default left the 2yr series stale.
    for window in (WINDOW_5YR, WINDOW_2YR) if args.window is None else (args.window,):
        refresh_betas(window_days=window, db_path=PRICES_DB)


def _cmd_show(args: argparse.Namespace) -> None:
    beta = get_beta(args.ticker, db_path=PRICES_DB)
    if beta is None:
        print(f"{args.ticker}: no stored beta (run backfill first)")
    else:
        print(f"{args.ticker}: beta = {beta:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Beta computation and storage")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_back = sub.add_parser("backfill", help="Compute monthly historical betas")
    p_back.add_argument("--ticker", help="Limit to a single ticker")
    p_back.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="Window in weeks of returns")

    p_ref = sub.add_parser("refresh", help="Compute current-month betas (cron mode)")
    p_ref.add_argument("--window", type=int, default=None, help="Single window; default refreshes both")

    p_show = sub.add_parser("show", help="Print latest stored beta for a ticker")
    p_show.add_argument("ticker")

    args = parser.parse_args()
    {"backfill": _cmd_backfill, "refresh": _cmd_refresh, "show": _cmd_show}[args.cmd](args)


if __name__ == "__main__":
    main()
