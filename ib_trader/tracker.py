from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_DEFAULT_DB = str(Path(__file__).resolve().parents[1] / "data" / "ib_tracker.duckdb")

_DDL = [
    "CREATE SEQUENCE IF NOT EXISTS fills_seq START 1",
    "CREATE SEQUENCE IF NOT EXISTS tax_lots_seq START 1",
    """CREATE TABLE IF NOT EXISTS strategies (
        name             VARCHAR PRIMARY KEY,
        description      VARCHAR,
        inception_date   DATE,
        benchmark        VARCHAR DEFAULT 'SPY',
        initial_capital  DOUBLE
    )""",
    "ALTER TABLE strategies ADD COLUMN IF NOT EXISTS initial_capital DOUBLE",
    """CREATE TABLE IF NOT EXISTS fills (
        id              BIGINT    DEFAULT nextval('fills_seq') PRIMARY KEY,
        strategy        VARCHAR   NOT NULL,
        ticker          VARCHAR   NOT NULL,
        action          VARCHAR   NOT NULL,
        qty             DOUBLE    NOT NULL,
        fill_price      DOUBLE    NOT NULL,
        reference_price DOUBLE,
        fill_time       TIMESTAMP NOT NULL,
        exec_id         VARCHAR,
        commission      DOUBLE    DEFAULT 0.0
    )""",
    # Migration: add reference_price to existing databases
    "ALTER TABLE fills ADD COLUMN IF NOT EXISTS reference_price DOUBLE",
    """CREATE TABLE IF NOT EXISTS tax_lots (
        id            BIGINT  DEFAULT nextval('tax_lots_seq') PRIMARY KEY,
        strategy      VARCHAR NOT NULL,
        ticker        VARCHAR NOT NULL,
        open_date     DATE    NOT NULL,
        open_price    DOUBLE  NOT NULL,
        qty           DOUBLE  NOT NULL,
        qty_remaining DOUBLE  NOT NULL,
        close_date    DATE,
        close_price   DOUBLE,
        realized_pnl  DOUBLE,
        is_long_term  BOOLEAN,
        tax_rate      DOUBLE
    )""",
    """CREATE TABLE IF NOT EXISTS daily_nav (
        strategy     VARCHAR NOT NULL,
        date         DATE    NOT NULL,
        nav          DOUBLE  NOT NULL,
        cash         DOUBLE,
        equity_value DOUBLE,
        PRIMARY KEY (strategy, date)
    )""",
    """CREATE TABLE IF NOT EXISTS score_snapshots (
        strategy       VARCHAR NOT NULL,
        snapshot_date  DATE    NOT NULL,
        ticker         VARCHAR NOT NULL,
        rank           INTEGER,
        score          DOUBLE,
        alloc_pct      DOUBLE,
        price_at_score DOUBLE,
        forward_return DOUBLE,
        PRIMARY KEY (strategy, snapshot_date, ticker)
    )""",
    """CREATE TABLE IF NOT EXISTS backtest_benchmarks (
        strategy  VARCHAR NOT NULL,
        portfolio VARCHAR NOT NULL,
        cagr      DOUBLE,
        ann_vol   DOUBLE,
        sharpe    DOUBLE,
        sortino   DOUBLE,
        max_dd    DOUBLE,
        beta      DOUBLE,
        alpha     DOUBLE,
        win_rate  DOUBLE,
        PRIMARY KEY (strategy, portfolio)
    )""",
]


def init_tracker_db(db_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Open (or create) the tracker database. Returns an open connection."""
    path = db_path or os.getenv("IB_TRACKER_DB", _DEFAULT_DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    for stmt in _DDL:
        conn.execute(stmt)
    return conn


def register_strategy(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    description: str | None = None,
    inception_date: date | None = None,
    benchmark: str = "SPY",
    initial_capital: float | None = None,
) -> None:
    conn.execute(
        "INSERT INTO strategies (name, description, inception_date, benchmark, initial_capital) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (name) DO UPDATE SET "
        "initial_capital = COALESCE(excluded.initial_capital, strategies.initial_capital)",
        [name, description, inception_date, benchmark, initial_capital],
    )


def record_fill(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    ticker: str,
    action: str,
    qty: float,
    fill_price: float,
    fill_time: datetime,
    exec_id: str | None = None,
    commission: float = 0.0,
    reference_price: float | None = None,
) -> None:
    """Record a fill and update FIFO tax lots. Skips duplicate exec_ids.

    reference_price: the closing price from the live_scores CSV at rebalance time.
    Slippage = (fill_price - reference_price) for BUY; (reference_price - fill_price) for SELL.
    """
    if exec_id is not None:
        if conn.execute("SELECT 1 FROM fills WHERE exec_id = ?", [exec_id]).fetchone():
            return
    conn.execute(
        "INSERT INTO fills "
        "(strategy, ticker, action, qty, fill_price, reference_price, fill_time, exec_id, commission) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [strategy, ticker, action.upper(), qty, fill_price, reference_price, fill_time, exec_id, commission],
    )
    fill_date = fill_time.date() if isinstance(fill_time, datetime) else fill_time
    _apply_fifo_lot(conn, strategy, ticker, action.upper(), qty, fill_price, fill_date)


def _apply_fifo_lot(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    ticker: str,
    action: str,
    qty: float,
    fill_price: float,
    fill_date: date,
) -> None:
    if action == "BUY":
        conn.execute(
            "INSERT INTO tax_lots (strategy, ticker, open_date, open_price, qty, qty_remaining) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [strategy, ticker, fill_date, fill_price, qty, qty],
        )
        return

    # SELL: close open lots oldest-first (FIFO)
    remaining = qty
    lots = conn.execute(
        "SELECT id, open_date, open_price, qty, qty_remaining FROM tax_lots "
        "WHERE strategy = ? AND ticker = ? AND qty_remaining > 0 "
        "ORDER BY open_date ASC, id ASC",
        [strategy, ticker],
    ).fetchall()

    for lot_id, open_date, open_price, lot_qty, lot_remaining in lots:
        if remaining <= 0:
            break
        close_qty = min(remaining, lot_remaining)
        new_remaining = lot_remaining - close_qty
        holding_days = (fill_date - open_date).days
        is_lt = holding_days >= 365
        realized_pnl = (fill_price - open_price) * close_qty
        tax_rate = 0.15 if is_lt else 0.24

        if close_qty == lot_qty:
            # Whole lot closed in one sell — update in place, no duplicate row.
            conn.execute(
                "UPDATE tax_lots SET qty_remaining = 0, close_date = ?, close_price = ?, "
                "realized_pnl = ?, is_long_term = ?, tax_rate = ? WHERE id = ?",
                [fill_date, fill_price, realized_pnl, is_lt, tax_rate, lot_id],
            )
        else:
            # Partial close — shrink the open lot, record the closed slice separately.
            conn.execute(
                "UPDATE tax_lots SET qty_remaining = ? WHERE id = ?",
                [new_remaining, lot_id],
            )
            conn.execute(
                "INSERT INTO tax_lots "
                "(strategy, ticker, open_date, open_price, qty, qty_remaining, "
                " close_date, close_price, realized_pnl, is_long_term, tax_rate) "
                "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)",
                [strategy, ticker, open_date, open_price, close_qty,
                 fill_date, fill_price, realized_pnl, is_lt, tax_rate],
            )
        remaining -= close_qty


def sync_ib_fills(
    client,
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    since_date: date | str | None = None,
) -> int:
    """Pull fills from IB execution history and insert new ones. Returns count inserted.

    Note: IB's reqExecutions returns fills from the current TWS session only.
    For fills from prior sessions, use the TWS Account Management portal or
    call this function in the same session where the orders were placed.
    """
    if isinstance(since_date, str):
        since_date = datetime.strptime(since_date, "%Y-%m-%d").date()

    fills = client.ib.reqExecutions()
    count = 0
    for fill in fills:
        # Only process fills whose orderRef matches this strategy tag.
        # This prevents fills from other strategies sharing the same IB account
        # from being recorded under the wrong strategy.
        order_ref = getattr(fill.execution, "orderRef", "") or ""
        if order_ref != strategy:
            continue

        exec_id = fill.execution.execId
        ticker = fill.contract.symbol
        action = "BUY" if fill.execution.side == "BOT" else "SELL"
        qty = float(fill.execution.shares)
        fill_price = float(fill.execution.price)
        raw_time = fill.execution.time
        fill_time = raw_time if isinstance(raw_time, datetime) else datetime.strptime(raw_time, "%Y%m%d %H:%M:%S")
        commission = float(getattr(fill.commissionReport, "commission", 0.0) or 0.0)

        if since_date and fill_time.date() < since_date:
            continue

        existing = conn.execute("SELECT 1 FROM fills WHERE exec_id = ?", [exec_id]).fetchone()
        if existing:
            continue

        # Reference price: most recent score snapshot price for this ticker on or before the fill date
        ref_row = conn.execute(
            "SELECT price_at_score FROM score_snapshots "
            "WHERE strategy = ? AND ticker = ? AND snapshot_date <= ? "
            "ORDER BY snapshot_date DESC LIMIT 1",
            [strategy, ticker, fill_time.date()],
        ).fetchone()
        reference_price = float(ref_row[0]) if ref_row and ref_row[0] else None

        record_fill(conn, strategy, ticker, action, qty, fill_price, fill_time,
                    exec_id, commission, reference_price)
        count += 1

    return count


def record_nav(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    nav: float,
    cash: float | None = None,
    equity_value: float | None = None,
    nav_date: date | None = None,
) -> None:
    """Upsert a daily NAV snapshot for the strategy."""
    nav_date = nav_date or date.today()
    conn.execute(
        "INSERT INTO daily_nav (strategy, date, nav, cash, equity_value) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (strategy, date) DO UPDATE SET nav=excluded.nav, cash=excluded.cash, "
        "equity_value=excluded.equity_value",
        [strategy, nav_date, nav, cash, equity_value],
    )


def record_score_snapshot(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    scores_df: pd.DataFrame,
    snapshot_date: date | None = None,
) -> None:
    """Insert score snapshot rows. Skips tickers already recorded for this date."""
    snapshot_date = snapshot_date or date.today()
    for _, row in scores_df.iterrows():
        ticker = row.get("ticker")
        if not ticker:
            continue
        rank = int(row["rank"]) if "rank" in row and pd.notna(row.get("rank")) else None
        score = float(row["score"]) if "score" in row and pd.notna(row.get("score")) else None
        alloc_pct = float(row["alloc_pct"]) if "alloc_pct" in row and pd.notna(row.get("alloc_pct")) else None
        price = float(row["price"]) if "price" in row and pd.notna(row.get("price")) else None
        conn.execute(
            "INSERT INTO score_snapshots "
            "(strategy, snapshot_date, ticker, rank, score, alloc_pct, price_at_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (strategy, snapshot_date, ticker) DO NOTHING",
            [strategy, snapshot_date, ticker, rank, score, alloc_pct, price],
        )


def update_forward_returns(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    lookback_days: int = 30,
) -> int:
    """Fetch 30-day-forward prices via yfinance and fill in forward_return. Returns count updated."""
    import yfinance as yf

    cutoff = date.today() - timedelta(days=lookback_days)
    rows = conn.execute(
        "SELECT snapshot_date, ticker, price_at_score FROM score_snapshots "
        "WHERE strategy = ? AND forward_return IS NULL AND snapshot_date <= ? "
        "ORDER BY ticker, snapshot_date",
        [strategy, cutoff],
    ).fetchall()

    if not rows:
        return 0

    tickers = list(set(r[1] for r in rows))
    min_date = min(r[0] for r in rows)
    end_date = date.today() + timedelta(days=1)

    price_cache: dict[str, pd.Series] = {}
    for ticker in tickers:
        try:
            data = yf.download(
                ticker, start=str(min_date), end=str(end_date),
                auto_adjust=True, progress=False, actions=False,
            )
            if not data.empty and "Close" in data.columns:
                price_cache[ticker] = data["Close"].squeeze()
        except Exception:
            pass

    count = 0
    for snapshot_date, ticker, price_at_score in rows:
        if ticker not in price_cache or not price_at_score:
            continue
        forward_date = snapshot_date + timedelta(days=lookback_days)
        series = price_cache[ticker]
        future = series[series.index >= pd.Timestamp(forward_date)]
        if future.empty:
            continue
        fwd_price = float(future.iloc[0])
        fwd_return = (fwd_price - price_at_score) / price_at_score
        conn.execute(
            "UPDATE score_snapshots SET forward_return = ? "
            "WHERE strategy = ? AND snapshot_date = ? AND ticker = ?",
            [fwd_return, strategy, snapshot_date, ticker],
        )
        count += 1

    return count


def record_fills_from_blotter(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    blotter_df: pd.DataFrame,
    price_map: dict[str, float] | None = None,
    fill_time: datetime | None = None,
    reference_price_map: dict[str, float] | None = None,
) -> int:
    """Record estimated fills from a rebalance blotter. Returns count recorded.

    blotter_df: output of summarise_diff() — columns: ticker, action, qty, est_price
    price_map: live IB prices {ticker: price} used as fill_price (estimated)
    reference_price_map: CSV closing prices {ticker: price} used as reference for slippage
    """
    if fill_time is None:
        fill_time = datetime.utcnow()
    price_map = price_map or {}
    reference_price_map = reference_price_map or {}
    count = 0

    for _, row in blotter_df.iterrows():
        ticker = row["ticker"]
        action = row["action"]
        qty = float(row["qty"])

        price = price_map.get(ticker)
        if price is None:
            est_price_str = str(row.get("est_price", ""))
            if est_price_str not in ("N/A", "", "nan"):
                try:
                    price = float(est_price_str.replace("$", "").replace(",", ""))
                except ValueError:
                    pass

        if not price or price <= 0:
            continue

        reference_price = reference_price_map.get(ticker)
        record_fill(conn, strategy, ticker, action, qty, price, fill_time,
                    exec_id=None, reference_price=reference_price)
        count += 1

    return count


def get_strategy_positions(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
) -> dict[str, float]:
    """Return {ticker: qty_remaining} for all open lots of this strategy."""
    rows = conn.execute(
        "SELECT ticker, SUM(qty_remaining) FROM tax_lots "
        "WHERE strategy = ? AND qty_remaining > 0 "
        "GROUP BY ticker",
        [strategy],
    ).fetchall()
    return {row[0]: float(row[1]) for row in rows}


def get_latest_strategy_nav(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
) -> float | None:
    """Return the most recently recorded NAV for this strategy, or None if not yet recorded."""
    row = conn.execute(
        "SELECT nav, date FROM daily_nav WHERE strategy = ? ORDER BY date DESC LIMIT 1",
        [strategy],
    ).fetchone()
    return float(row[0]) if row else None


def compute_strategy_nav(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    price_map: dict[str, float],
) -> tuple[float, float | None, float]:
    """Compute strategy NAV = equity + cash.

    Cash is derived from initial_capital (set via register_strategy) plus cumulative
    sell proceeds minus cumulative buy costs recorded in fills. Returns None for cash
    if initial_capital is not set, falling back to equity-only NAV.

    Returns (nav, cash, equity_value).
    """
    positions = get_strategy_positions(conn, strategy)
    equity = sum(qty * price_map[t] for t, qty in positions.items() if t in price_map)

    row = conn.execute(
        "SELECT initial_capital FROM strategies WHERE name = ?", [strategy]
    ).fetchone()
    initial_capital = float(row[0]) if row and row[0] is not None else None

    if initial_capital is None:
        return equity, None, equity

    cash_row = conn.execute(
        "SELECT SUM(CASE WHEN action='SELL' THEN qty * fill_price ELSE -(qty * fill_price) END) "
        "FROM fills WHERE strategy = ?",
        [strategy],
    ).fetchone()
    net_cash_flow = float(cash_row[0]) if cash_row and cash_row[0] is not None else 0.0
    cash = initial_capital + net_cash_flow

    return equity + cash, cash, equity


def load_backtest_benchmarks(
    conn: duckdb.DuckDBPyConnection,
    strategy: str,
    portfolio: str,
    stats: dict,
) -> None:
    """Register backtest reference stats for a strategy/portfolio pair.

    Example:
        load_backtest_benchmarks(conn, "fundamentals_alpha", "vw_gr_top_n_25", {
            "cagr": 0.252, "ann_vol": 0.225, "sharpe": 1.35, "sortino": 1.62,
            "max_dd": -0.216, "beta": 1.32, "alpha": 0.10, "win_rate": 0.67
        })
    """
    conn.execute(
        "INSERT INTO backtest_benchmarks "
        "(strategy, portfolio, cagr, ann_vol, sharpe, sortino, max_dd, beta, alpha, win_rate) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (strategy, portfolio) DO UPDATE SET "
        "cagr=excluded.cagr, ann_vol=excluded.ann_vol, sharpe=excluded.sharpe, "
        "sortino=excluded.sortino, max_dd=excluded.max_dd, beta=excluded.beta, "
        "alpha=excluded.alpha, win_rate=excluded.win_rate",
        [
            strategy, portfolio,
            stats.get("cagr"), stats.get("ann_vol"), stats.get("sharpe"),
            stats.get("sortino"), stats.get("max_dd"), stats.get("beta"),
            stats.get("alpha"), stats.get("win_rate"),
        ],
    )
