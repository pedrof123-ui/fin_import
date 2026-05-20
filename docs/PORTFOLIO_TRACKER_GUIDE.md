# Portfolio Tracker Guide

The portfolio tracker is a persistent DuckDB ledger that records fills, tracks FIFO tax lots, measures live risk-adjusted returns, and compares them against the backtest benchmark. It is fully optional — all functionality is conditional on the `IB_TRACKER_DB` environment variable being set.

---

## Setup

### 1. Add to `.env`

```dotenv
IB_TRACKER_DB=/home/pedro/projects/fin_import2/data/ib_tracker.duckdb
IB_TRACKER_BENCHMARK=SPY
```

The database is created automatically on first use. No manual schema creation required.

### 2. Register a strategy

Run once per strategy:

```python
from ib_trader.tracker import init_tracker_db, register_strategy

conn = init_tracker_db()
register_strategy(
    conn,
    name="fundamentals_alpha",
    description="Composite fundamentals alpha (vw_gr_top_n_25)",
    inception_date="2026-01-01",
    benchmark="SPY",
)
conn.close()
```

The `benchmark` field controls which ticker is used for beta and alpha calculations.

---

## Monthly Workflow

This is the normal sequence for a monthly rebalance with full tracker integration.

### Step 1 — Score and record snapshot

```
uv run scripts/score_live.py
```

When `IB_TRACKER_DB` is set, this automatically calls `record_score_snapshot()` at the end of the run. The snapshot records each ticker's rank, score, alloc_pct, and current price. These prices become the slippage reference and IC denominator.

### Step 2 — Preview rebalance

```
uv run scripts/rebalance.py
```

Dry-run by default. No tracker writes.

### Step 3 — Submit orders and record estimated fills

```
uv run scripts/rebalance.py --no-dry-run
```

When `IB_TRACKER_DB` is set, this automatically:
- Calls `record_fills_from_blotter()` with blotter quantities and live IB prices
- Calls `record_nav()` with the post-rebalance NAV

These are estimates — actual fill prices from IB are synced in the next step.

### Step 4 — Sync confirmed fills (same TWS session)

```
uv run scripts/sync_fills.py --strategy fundamentals_alpha
```

Pulls actual execution records from IB via `reqExecutions()` and writes them to the tracker with real exec IDs and fill prices. Also records the current NAV.

IB's `reqExecutions()` only returns fills from the current TWS session. Run this before closing TWS.

### Step 5 (monthly) — Update forward returns for IC

```
uv run scripts/sync_fills.py --strategy fundamentals_alpha --update-forward-returns
```

Downloads prices via yfinance and fills in `forward_return` for any score snapshot older than 30 days. The IC (Spearman rank correlation between scores and forward returns) is computed from these values.

---

## Commands Reference

### sync_fills.py

```
uv run scripts/sync_fills.py --strategy fundamentals_alpha
uv run scripts/sync_fills.py --strategy fundamentals_alpha --since 2026-01-01
uv run scripts/sync_fills.py --strategy fundamentals_alpha --dry-run
uv run scripts/sync_fills.py --strategy fundamentals_alpha --update-forward-returns
```

| Flag | Default | Description |
|---|---|---|
| `--strategy NAME` | required | Strategy name in the tracker DB |
| `--since DATE` | 90 days ago | Only process fills after this date |
| `--update-forward-returns` | off | Fill in forward_return for old score snapshots |
| `--dry-run` | off | Preview fills that would be inserted without writing |
| `--verbose` | off | Debug logging |

---

## Viewing Results

### Snapshot report (terminal or Jupyter)

```python
from ib_trader.tracker import init_tracker_db
from ib_trader.report import snapshot_report

conn = init_tracker_db()
snapshot_report(conn, "fundamentals_alpha")
conn.close()
```

**Report sections:**

1. **Account summary** — strategy name, inception date, NAV, cash, equity value
2. **Performance** — week/month/YTD/1yr/inception returns, Sharpe ratio
3. **Risk diagnostics** — MaxDD, Beta, Sortino, Sharpe
4. **Live vs backtest** — CAGR, Sharpe, MaxDD, Alpha compared to backtest reference
5. **Open positions** — ticker, qty, avg cost, current price, unrealized P&L, weight %
6. **Realized P&L and tax** — ST and LT realized gains, estimated tax owed
7. **Slippage analysis** — avg bps, median bps, total dollar slippage vs 10 bps backtest assumption
8. **Model IC** — last 6 months of Spearman IC with mean; n_stocks per snapshot

### Jupyter notebook

Open `notebooks/portfolio_tracker.ipynb`. It connects to `IB_TRACKER_DB` automatically via the `.env` file.

### Query functions

All functions accept a `duckdb.Connection` and a `strategy` string.

```python
from ib_trader.tracker import init_tracker_db
from ib_trader.report import (
    get_trades,
    get_positions,
    get_performance,
    get_tax_summary,
)
from ib_trader.performance import (
    compare_vs_backtest,
    get_ic_series,
    get_slippage_summary,
)

conn = init_tracker_db()

# All fills with realized P&L on SELL rows
get_trades(conn, "fundamentals_alpha")
get_trades(conn, "fundamentals_alpha", ticker="AAPL")
get_trades(conn, "fundamentals_alpha", from_date="2026-01-01")

# Open positions
get_positions(conn, "fundamentals_alpha")

# Period returns table
get_performance(conn, "fundamentals_alpha")

# Tax lot detail for Schedule D
get_tax_summary(conn, "fundamentals_alpha", year=2026)

# Live CAGR/Sharpe/MaxDD vs backtest benchmark
compare_vs_backtest(conn, "fundamentals_alpha")

# Monthly IC time series
get_ic_series(conn, "fundamentals_alpha")

# Slippage vs 10 bps backtest assumption
get_slippage_summary(conn, "fundamentals_alpha")

conn.close()
```

---

## Database Schema

The tracker database lives at the path set in `IB_TRACKER_DB`. It contains six tables:

### strategies

One row per registered strategy.

| Column | Type | Description |
|---|---|---|
| `name` | VARCHAR PK | Strategy identifier (e.g. `fundamentals_alpha`) |
| `description` | VARCHAR | Human-readable description |
| `inception_date` | DATE | Date strategy started trading |
| `benchmark` | VARCHAR | Benchmark ticker for beta/alpha (default: `SPY`) |

### fills

Raw execution records. One row per fill.

| Column | Type | Description |
|---|---|---|
| `id` | BIGINT PK | Auto-incrementing sequence |
| `strategy` | VARCHAR | Strategy name |
| `ticker` | VARCHAR | Stock symbol |
| `action` | VARCHAR | `BUY` or `SELL` |
| `qty` | DOUBLE | Shares filled |
| `fill_price` | DOUBLE | Actual fill price |
| `fill_time` | TIMESTAMP | Fill timestamp |
| `exec_id` | VARCHAR UNIQUE | IB exec ID (NULL for blotter estimates) |
| `commission` | DOUBLE | Commission paid |
| `reference_price` | DOUBLE | CSV closing price at time of scoring (slippage reference) |

Blotter estimates (from `rebalance.py --no-dry-run`) have `exec_id = NULL`. Once `sync_fills.py` runs, IB's confirmed fills are inserted with real exec IDs.

### tax_lots

FIFO lot tracking. One row per lot open or close event.

| Column | Type | Description |
|---|---|---|
| `id` | BIGINT PK | Auto-incrementing sequence |
| `strategy` | VARCHAR | Strategy name |
| `ticker` | VARCHAR | Stock symbol |
| `open_date` | DATE | Date the lot was opened (BUY date) |
| `open_price` | DOUBLE | Cost basis per share |
| `qty` | DOUBLE | Total shares in this lot |
| `qty_remaining` | DOUBLE | Shares not yet sold (0 when fully closed) |
| `close_date` | DATE | Date the lot was closed (NULL if still open) |
| `close_price` | DOUBLE | Sale price per share |
| `realized_pnl` | DOUBLE | `(close_price - open_price) * qty_closed` |
| `is_long_term` | BOOLEAN | Holding period >= 365 days at close |
| `tax_rate` | DOUBLE | 0.15 (LT) or 0.24 (ST) |

**Open positions:** `WHERE qty_remaining > 0`
**Closed lots:** `WHERE close_date IS NOT NULL`

### daily_nav

End-of-day NAV snapshots.

| Column | Type | Description |
|---|---|---|
| `strategy` | VARCHAR | Strategy name |
| `date` | DATE | Snapshot date (PK with strategy) |
| `nav` | DOUBLE | Total net asset value |
| `cash` | DOUBLE | Cash component (optional) |
| `equity_value` | DOUBLE | Equity component (optional) |

### score_snapshots

Live scoring output per ticker per date, used for IC calculation.

| Column | Type | Description |
|---|---|---|
| `strategy` | VARCHAR | Strategy name |
| `snapshot_date` | DATE | Date scores were computed (PK with strategy+ticker) |
| `ticker` | VARCHAR | Stock symbol |
| `rank` | INTEGER | Rank in scored universe (1 = best) |
| `score` | DOUBLE | Model composite score |
| `alloc_pct` | DOUBLE | Target allocation (NaN for non-portfolio tickers) |
| `price_at_score` | DOUBLE | Closing price at time of scoring (slippage reference) |
| `forward_return` | DOUBLE | 30-day return from snapshot date (filled in by `update_forward_returns`) |

### backtest_benchmarks

Reference statistics from the backtest, loaded manually.

| Column | Type | Description |
|---|---|---|
| `strategy` | VARCHAR | Strategy name |
| `portfolio` | VARCHAR | Portfolio variant (e.g. `vw_gr_top_n_25`) |
| `cagr` | DOUBLE | Backtest CAGR |
| `ann_vol` | DOUBLE | Annualized volatility |
| `sharpe` | DOUBLE | Sharpe ratio |
| `sortino` | DOUBLE | Sortino ratio |
| `max_dd` | DOUBLE | Maximum drawdown |
| `beta` | DOUBLE | Beta to benchmark |
| `alpha` | DOUBLE | Annualized alpha |
| `win_rate` | DOUBLE | Fraction of months with positive return |

---

## Slippage Tracking

Every fill records `reference_price` — the CSV closing price from the live scores file that was used when the rebalance order was sized. Slippage is the difference between the actual fill price and this reference:

```
BUY  slippage_bps = (fill_price - reference_price) / reference_price * 10000
SELL slippage_bps = (reference_price - fill_price) / reference_price * 10000
```

Negative slippage means a better-than-reference fill (filled below reference on a BUY, or above reference on a SELL).

`get_slippage_summary(conn, strategy)` returns average and median slippage in basis points, total dollar slippage, and a comparison against the 10 bps one-way backtest TC assumption.

---

## FIFO Tax Lot Accounting

The tracker uses FIFO (first-in, first-out) lot assignment per ticker per strategy:

- **BUY**: inserts a new lot with `qty_remaining = qty`
- **SELL**: walks the oldest open lots first, reducing `qty_remaining` until the sell quantity is exhausted. If a lot is partially consumed, a separate closed row is inserted for the closed portion while the original row reflects the remaining open quantity.

Tax treatment at close:
- Held **< 365 days**: short-term, taxed at 24%
- Held **>= 365 days**: long-term, taxed at 15%

`get_tax_summary()` exports a per-lot breakdown with cost basis, proceeds, holding days, and estimated tax owed — suitable for Schedule D preparation.

---

## Multi-Strategy Usage

The tracker database supports multiple strategies. All tables include a `strategy` column as part of the primary key. Functions that query data always filter by the strategy argument:

```python
conn = init_tracker_db()
snapshot_report(conn, "fundamentals_alpha")
snapshot_report(conn, "ibd_50")
```

To use the same database from another project, set `IB_TRACKER_DB` to the same absolute path and import `ib_trader` from `fin_import2` (installable with `uv pip install -e /path/to/fin_import2`).
