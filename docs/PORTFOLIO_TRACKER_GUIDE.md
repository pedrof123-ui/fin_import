# Portfolio Tracker Guide

The portfolio tracker is a persistent DuckDB ledger that records fills, tracks FIFO tax lots, measures live risk-adjusted returns, and compares them against the backtest benchmark. It is fully optional — all functionality is conditional on the `IB_TRACKER_DB` environment variable being set.

---

## Setup

### 1. Choose your databases

Use separate databases for paper and live trading. Each is created automatically on first use.

| Mode | Database path |
|---|---|
| Paper | `data/ib_tracker_paper.duckdb` |
| Live | `data/ib_tracker_live.duckdb` |

Add to `.env` (use the paper path while paper trading):

```dotenv
IB_TRACKER_DB=/home/pedro/projects/fin_import2/data/ib_tracker_paper.duckdb
IB_TRACKER_BENCHMARK=SPY
```

When running both paper and live simultaneously, use `--tracker-db` per command to target the correct database regardless of the env var:

```
uv run scripts/rebalance.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --no-dry-run
uv run scripts/rebalance.py --strategy fundamentals_alpha --tracker-db data/ib_tracker_live.duckdb --no-dry-run
```

### 2. Register a strategy

Run once per strategy per database:

```python
from ib_trader.tracker import init_tracker_db, register_strategy

# Paper strategy
conn = init_tracker_db("data/ib_tracker_paper.duckdb")
register_strategy(
    conn,
    name="vw_gr_top_n_25",
    description="Vol-weighted guardrails top-25, paper $100K",
    inception_date="2026-05-29",
    benchmark="SPY",
)
conn.close()

# Live strategy (when ready)
conn = init_tracker_db("data/ib_tracker_live.duckdb")
register_strategy(
    conn,
    name="fundamentals_alpha",
    description="Composite fundamentals alpha, live",
    inception_date="2026-XX-XX",
    benchmark="SPY",
)
conn.close()
```

The `benchmark` field controls which ticker is used for beta and alpha calculations.

---

## Monthly Workflow

Run on the first trading day of each month before 15:50 ET — not the last trading day. This is automated via cron: the data/scoring pipeline fires at 2:00 AM ET on the 1st, and the rebalance fires at 15:30 ET on whichever of the 1st-4th is the actual first trading day (`rebalance.py` gates on this internally). Trading same-day as the refresh keeps the score's price/fundamentals basis to hours old instead of letting it go stale for weeks. Use `--tracker-db` to target the correct database explicitly.

### Paper trading — `vw_gr_top_n_25`

| Step | When | Command |
|---|---|---|
| 1. Generate scores | Morning | `uv run scripts/score_live.py --guardrails --vol-weight --top 25` |
| 2. Preview rebalance | Midday | `uv run scripts/rebalance.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb` |
| 3. Submit MOC orders | Before 15:50 ET | `uv run scripts/rebalance.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --no-dry-run` |
| 4. Sync confirmed fills | After close (same TWS session) | `uv run scripts/sync_fills.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb` |
| 5. Update forward returns | After step 4, every month | `uv run scripts/sync_fills.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --update-forward-returns` |

Step 5 backfills the **prior month's** score snapshots with the 30-day returns that have since occurred. Run it after step 4 each month — it has no time pressure and does not require TWS to be open. It skips rows already filled, so running it more than once is harmless. It will find nothing to update the first month (no snapshot is yet 30 days old); from month 2 onward it fills in the previous month's IC data.

### Live trading — general pattern

Replace `vw_gr_top_n_25` with the live strategy name and `ib_tracker_paper.duckdb` with `ib_tracker_live.duckdb`. Set `IB_PORT=7496` in `.env` for the live account.

### What each step records

| Step | Function called | Data written |
|---|---|---|
| Step 1 (`score_live.py`) | `record_score_snapshot()` | Ticker ranks, scores, prices — IC reference |
| Step 3 (`--no-dry-run`) | `record_fills_from_blotter()`, `record_nav()` | Estimated fills + post-rebalance NAV |
| Step 4 (`sync_fills.py`) | `sync_ib_fills()`, `record_nav()` | Confirmed fills with real exec IDs + current NAV |
| Step 5 (`--update-forward-returns`) | `update_forward_returns()` | 30-day forward returns for prior month's score snapshots (IC calculation) |

Step 3 fills are estimates (blotter qty × live IB price). Step 4 overwrites them with IB's actual execution records, enabling accurate slippage calculation.

IB's `reqExecutions()` only returns fills from the current TWS session. Run step 4 before closing TWS.

---

## Commands Reference

### rebalance.py

```
uv run scripts/rebalance.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb
uv run scripts/rebalance.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --no-dry-run
uv run scripts/rebalance.py --strategy fundamentals_alpha --tracker-db data/ib_tracker_live.duckdb --no-dry-run
```

| Flag | Default | Description |
|---|---|---|
| `--strategy NAME` | `fundamentals_alpha` | Strategy name written to IB orderRef and tracker DB |
| `--tracker-db PATH` | `IB_TRACKER_DB` env var | Tracker DuckDB path — use to target paper or live DB explicitly |
| `--dry-run` / `--no-dry-run` | dry-run on | Preview orders without submitting |
| `--order-type MOC\|MKT\|LMT` | `MOC` | Order type |
| `--scores PATH` | latest `docs/live_scores_*.csv` | Explicit scores CSV path |
| `--status` | off | Print account summary and exit |
| `--cancel-all` | off | Cancel all open orders and exit |

### sync_fills.py

```
uv run scripts/sync_fills.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb
uv run scripts/sync_fills.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --since 2026-01-01
uv run scripts/sync_fills.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --dry-run
uv run scripts/sync_fills.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --update-forward-returns
```

| Flag | Default | Description |
|---|---|---|
| `--strategy NAME` | required | Strategy name in the tracker DB |
| `--tracker-db PATH` | `IB_TRACKER_DB` env var | Tracker DuckDB path — use to target paper or live DB explicitly |
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

# Paper
conn = init_tracker_db("data/ib_tracker_paper.duckdb")
snapshot_report(conn, "vw_gr_top_n_25")
conn.close()

# Live
conn = init_tracker_db("data/ib_tracker_live.duckdb")
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

Each database supports multiple strategies. All tables include a `strategy` column as part of the primary key, so fills, NAV, and snapshots are fully isolated per strategy name within a database.

```python
# Multiple paper strategies in one database
conn = init_tracker_db("data/ib_tracker_paper.duckdb")
snapshot_report(conn, "vw_gr_top_n_25")
snapshot_report(conn, "ibd_50_paper")
conn.close()
```

### Paper vs live databases summary

| | Paper | Live |
|---|---|---|
| Database | `data/ib_tracker_paper.duckdb` | `data/ib_tracker_live.duckdb` |
| `IB_PORT` | `7497` | `7496` |
| Strategy name | `vw_gr_top_n_25` | `fundamentals_alpha` |
| Reset safely? | Yes — delete the file | No — preserve carefully |
| `--tracker-db` flag | `data/ib_tracker_paper.duckdb` | `data/ib_tracker_live.duckdb` |

To use the same database from another project, import `ib_trader` from `fin_import2` (installable with `uv pip install -e /path/to/fin_import2`) and pass the absolute DB path to `init_tracker_db()`.
