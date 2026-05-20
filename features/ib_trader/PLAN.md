# IB Trader — Implementation Plan

## Decisions

| Item | Decision | Rationale |
|---|---|---|
| Library | `ib_async` | Maintained Python 3.12+ fork of ib_insync; already in pyproject.toml |
| Module location | `ib_trader/` at fin_import2 root | Importable by other projects via `uv pip install -e /path/to/fin_import2`; no separate repo needed now |
| Default order type | MOC (Market-on-Close) for buys and sells | Strategy returns are close-to-close; MOC matches the backtest reference for both legs |
| Interface | CLI (batch rebalance) + REPL (ad-hoc orders) | Batch for month-end automation; REPL for manual overrides and emergency exits |
| Rebalance workflow | Full rebalance | Fetch NAV + current positions from IB, diff vs target, place buy/sell orders |
| Config | `.env` + env vars | Consistent with all other scripts in the project |
| Fractional shares | No — `math.floor` to whole shares | IB account does not support fractional shares |
| LMT price (batch) | IB live mid-price | Auto-computed; per-ticker overrides only available in REPL |
| LMT price (REPL) | User-specified per ticker | `sell MSFT 30 LMT 450.00` |
| Auto-exit dropped positions | Yes | Required to match backtest; dry-run shows all exits before confirmation |
| Strategy tag | `orderRef` field on IB Order | Default `"fundamentals_alpha"`; overridable by other callers for multi-strategy auditing |

---

## Module Layout

```
ib_trader/
    __init__.py          # public re-exports: IBClient, rebalance, place_order
    client.py            # IB connection wrapper; account + position fetching
    orders.py            # order factory (market, limit, MOC) + order status
    portfolio.py         # diff current positions vs target → order list
    rebalance.py         # end-to-end rebalance: load scores → diff → submit
    interactive.py       # REPL loop with ad-hoc order commands
    tracker.py           # portfolio tracker DB: fill capture, NAV snapshots, score snapshots
    performance.py       # P&L, risk metrics, IC, backtest comparison
    report.py            # snapshot_report() and Jupyter query functions

scripts/
    rebalance.py         # CLI entry point: --scores, --dry-run, --top, --order-type
    sync_fills.py        # pull IB execDetails → tracker DB (backfill / correct)

notebooks/
    portfolio_tracker.ipynb  # Jupyter interface for queries and reporting

data/
    ib_tracker.duckdb    # persistent multi-strategy trade/position store
```

---

## Configuration (.env additions)

```dotenv
IB_HOST=127.0.0.1
IB_PORT=7497          # paper: 7497 | live: 7496
IB_CLIENT_ID=1
IB_ACCOUNT=           # auto-detect from IB if empty

# Portfolio Tracker
IB_TRACKER_DB=/home/pedro/projects/fin_import2/data/ib_tracker.duckdb
IB_TRACKER_BENCHMARK=SPY   # benchmark for beta / alpha calculations
```

Switch to live by changing `IB_PORT=7496`. All other code is identical.
`IB_TRACKER_DB` can be overridden in other projects (e.g., `trade_systems`) to point at the same shared database file.

---

## Data Contract

The IB trader consumes output from `scripts/score_live.py` in two ways:

**Option A — direct import (preferred for scripts):**
```python
from scripts.score_live import score_universe
ranked = score_universe(hf_db_path, av_db_path, model_path=None)
# Use ranked DataFrame: ticker, alloc_pct (float 0–1 range... see note below)
```

**Option B — read the CSV:**
```python
df = pd.read_csv("docs/live_scores_YYYYMMDD_*.csv", comment="#")
portfolio = df[df["alloc_pct"].notna() & (df["alloc_pct"] != "")].copy()
# Parse formatted strings: portfolio["alloc_pct"] = portfolio["alloc_pct"].str.rstrip("%").astype(float) / 100
# Parse formatted prices: portfolio["price"] = portfolio["price"].astype(float)
```

> Note: `alloc_pct` in the raw DataFrame from `score_universe()` is already a float (0–100). In the CSV it is a formatted string like `"3.0%"`. The CLI will detect which format it is reading.

**Key fields consumed by the trader:**

| Field | Meaning | Trading use |
|---|---|---|
| `ticker` | Symbol | IB contract lookup |
| `alloc_pct` | Target % of NAV (post-regime) | `target_shares = floor(alloc_pct * NAV / price)` |
| `price` | Last known price | Initial share estimate; IB live price used to confirm |
| `weight_pct` | Pre-regime weight | Display / audit only |

Stocks not in the top-N portfolio have `alloc_pct = NaN` and are treated as target weight = 0 (exit position if held).

---

## Rebalancing Algorithm

```
1. Connect to IB (client.py)
2. Fetch NetLiquidation (account NAV) from accountSummary
3. Fetch current positions → Dict[ticker, current_shares]
4. Load target portfolio from CSV or score_universe()
   → Dict[ticker, alloc_pct]   (only non-NaN rows)
5. For each ticker in union(current, target):
     target_shares  = floor(alloc_pct * NAV / live_price)   if in target else 0
     current_shares = current positions map                   if in current else 0
     delta          = target_shares - current_shares
     if delta > 0:  generate BUY  order for delta shares
     if delta < 0:  generate SELL order for |delta| shares
     if delta == 0: no action
6. Preview order blotter (dry-run)
7. On confirmation, submit all orders
8. Log fills, rejections, and remaining open orders
```

> Live prices for step 5 are fetched from IB market data to get accurate share counts. If market data is unavailable (outside hours), the CSV `price` column is used as a fallback.

---

## Phase Plan

### Phase 1 — Client foundation (`ib_trader/client.py`)

**Goal:** Connect, fetch account info and positions.

Deliverables:
- `IBClient` class: `connect()`, `disconnect()`, context manager (`__enter__`/`__exit__`)
- `get_nav() -> float` — NetLiquidation from `accountSummary`
- `get_positions() -> dict[str, float]` — ticker → shares held
- `get_live_price(ticker) -> float | None` — snapshot market data; returns None on timeout
- `qualify_contract(ticker) -> Contract` — resolves US stock contract via `qualifyContracts`

Config loaded from env: `IB_HOST`, `IB_PORT`, `IB_CLIENT_ID`, `IB_ACCOUNT`.

Connection test: `uv run -c "from ib_trader.client import IBClient; ib = IBClient(); ib.connect(); print(ib.get_nav()); ib.disconnect()"`

---

### Phase 2 — Order factory (`ib_trader/orders.py`)

**Goal:** Generate and place IB orders for all three types.

Deliverables:
- `make_order(action, qty, order_type, limit_price=None, strategy="fundamentals_alpha") -> Order`
  - `order_type` in `{"MKT", "LMT", "MOC"}`
  - For LMT: `limit_price` required (REPL: user-specified; batch CLI: IB live mid-price)
  - For MOC: time-in-force = `"DAY"`, orderType = `"MOC"` (used for both buys and sells)
  - `strategy` written to IB `orderRef` field for blotter attribution
- `place_order(ib, ticker, action, qty, order_type, limit_price=None, strategy="fundamentals_alpha") -> Trade`
- `get_live_midprice(ib, contract) -> float | None` — used as auto limit price in batch LMT mode
- `cancel_all_open_orders(ib)` — safety utility
- `get_order_status(ib) -> list[dict]` — open orders summary

---

### Phase 3 — Portfolio reconciliation (`ib_trader/portfolio.py`)

**Goal:** Compute diff between current IB state and target portfolio.

Deliverables:
- `build_target(ranked_df, nav, price_override=None) -> dict[str, int]`
  - Input: raw DataFrame from `score_universe()` (or parsed CSV)
  - Computes target shares per ticker using `alloc_pct * nav / price`
  - `price_override`: dict of live IB prices (falls back to CSV price column)
- `diff_portfolio(current, target) -> list[OrderSpec]`
  - `OrderSpec = namedtuple("OrderSpec", ["ticker", "action", "qty"])`
  - Returns BUY specs (target > current) and SELL specs (target < current)
  - Tickers in `current` but not in `target` → target = 0 → full SELL (auto-exit dropped positions)
  - Excludes zero-delta positions
- `summarise_diff(specs, prices) -> pd.DataFrame` — human-readable blotter for preview

---

### Phase 4 — End-to-end rebalancer (`ib_trader/rebalance.py`)

**Goal:** Orchestrate the full rebalance: load scores → diff → submit.

Deliverables:
- `run_rebalance(scores_path, order_type="MOC", dry_run=True, top_n=25) -> pd.DataFrame`
  - Loads scores from CSV path (or calls `score_universe()` if path is None)
  - Connects to IB, fetches NAV + positions + live prices
  - Builds target, diffs, submits orders (or prints blotter if dry_run=True)
  - Returns filled blotter DataFrame for logging
- Prints: NAV, regime, current portfolio value, target portfolio, order blotter

---

### Phase 5 — CLI entry point (`scripts/rebalance.py`)

**Goal:** One command to do a full rebalance.

```
uv run scripts/rebalance.py --scores docs/live_scores_20260519_rf_vw_gr_top_n_25.csv
uv run scripts/rebalance.py --dry-run
uv run scripts/rebalance.py --order-type LMT
uv run scripts/rebalance.py --top 10
uv run scripts/rebalance.py --cancel-all    # cancel all open orders
uv run scripts/rebalance.py --status        # show current positions + open orders
```

Flags:
| Flag | Default | Description |
|---|---|---|
| `--scores PATH` | None (runs scorer live) | Path to live_scores CSV |
| `--dry-run` | on | Preview only; no orders submitted |
| `--order-type` | MOC | MKT, LMT, or MOC |
| `--top N` | 25 | Portfolio size |
| `--cancel-all` | off | Cancel all open IB orders and exit |
| `--status` | off | Show positions + open orders and exit |
| `--verbose` | off | Debug logging |

Always defaults to `--dry-run`. Requires explicit `--no-dry-run` to submit real orders.

---

### Phase 6 — Interactive REPL (`ib_trader/interactive.py` + `scripts/ib_repl.py`)

**Goal:** Ad-hoc order placement and inspection without editing scripts.

Commands:
```
> status                        — show positions, NAV, open orders
> buy AAPL 50 MOC               — buy 50 shares of AAPL at MOC
> sell MSFT 30 LMT 450.00       — sell 30 MSFT with $450 limit
> cancel <order_id>             — cancel a specific open order
> cancel all                    — cancel all open orders
> preview                       — show rebalance diff without submitting
> rebalance                     — run full rebalance (dry-run by default)
> rebalance --confirm            — submit orders after preview
> quote AAPL                    — show live bid/ask/last
> help                          — list commands
> quit / exit
```

Launch: `uv run scripts/ib_repl.py`

---

## Safety Controls

1. **Dry-run by default** — no order is submitted unless `--no-dry-run` (CLI) or `--confirm` (REPL) is explicitly passed
2. **Paper vs live gate** — REPL prints a warning banner when `IB_PORT=7496` (live account)
3. **Max order size** — configurable `MAX_SINGLE_ORDER_SHARES` env var (default 10,000); orders above this require manual confirmation
4. **MOC cutoff warning** — warn if submitting MOC orders after 15:45 ET (IB cutoff is 15:50 ET)
5. **Cancel-before-rebalance** — `run_rebalance()` cancels any existing open orders for tickers in the target before submitting new ones

---

---

## Portfolio Tracker

### Overview

A persistent, multi-strategy trading ledger that records fills, tracks tax lots (FIFO), computes realized and unrealized P&L, measures live risk-adjusted returns, and compares them against the backtest benchmark and the model's live IC (score rank → forward return correlation).

The database (`data/ib_tracker.duckdb`) is accessed by both `fin_import2` and `trade_systems` via the `IB_TRACKER_DB` env var.

### Database Schema

```sql
-- One row per registered strategy
CREATE TABLE strategies (
    name        VARCHAR PRIMARY KEY,
    description VARCHAR,
    inception_date DATE,
    benchmark   VARCHAR DEFAULT 'SPY'
);

-- Raw IB execution records; exec_id is the IB unique fill ID (dedup key)
CREATE TABLE fills (
    id          INTEGER PRIMARY KEY,
    strategy    VARCHAR NOT NULL,
    ticker      VARCHAR NOT NULL,
    action      VARCHAR NOT NULL,     -- BUY | SELL
    qty         DOUBLE  NOT NULL,
    fill_price  DOUBLE  NOT NULL,
    fill_time   TIMESTAMP NOT NULL,
    exec_id     VARCHAR UNIQUE,       -- IB execId; NULL for manual entries
    commission  DOUBLE  DEFAULT 0.0
);

-- FIFO lots; qty_remaining decreases as sell fills close the lot
CREATE TABLE tax_lots (
    id           INTEGER PRIMARY KEY,
    strategy     VARCHAR NOT NULL,
    ticker       VARCHAR NOT NULL,
    open_date    DATE    NOT NULL,
    open_price   DOUBLE  NOT NULL,
    qty          DOUBLE  NOT NULL,
    qty_remaining DOUBLE NOT NULL,
    close_date   DATE,
    close_price  DOUBLE,
    realized_pnl DOUBLE,
    is_long_term BOOLEAN,            -- holding period > 365 days at close
    tax_rate     DOUBLE              -- 0.15 LT | 0.24 ST
);

-- End-of-day NAV snapshots (equity value + cash = NAV)
CREATE TABLE daily_nav (
    strategy     VARCHAR NOT NULL,
    date         DATE    NOT NULL,
    nav          DOUBLE  NOT NULL,
    cash         DOUBLE,
    equity_value DOUBLE,
    PRIMARY KEY (strategy, date)
);

-- Score snapshots for IC tracking; forward_return filled 30 days after snapshot
CREATE TABLE score_snapshots (
    strategy       VARCHAR NOT NULL,
    snapshot_date  DATE    NOT NULL,
    ticker         VARCHAR NOT NULL,
    rank           INTEGER,
    score          DOUBLE,
    alloc_pct      DOUBLE,
    price_at_score DOUBLE,
    forward_return DOUBLE,           -- NULL until 30d later
    PRIMARY KEY (strategy, snapshot_date, ticker)
);

-- Backtest reference stats loaded from docs/backtest_results_model.md
CREATE TABLE backtest_benchmarks (
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
);
```

---

### Phase 7 — Tracker DB & Fill Capture (`ib_trader/tracker.py`) [IMPLEMENTED]

**Goal:** Initialize the database and record fills automatically from `rebalance.py`, with a separate sync path for backfill.

Deliverables:
- `init_tracker_db(db_path=None) -> duckdb.Connection`
  - Creates all tables if not exists; reads path from `IB_TRACKER_DB` env var
- `register_strategy(conn, name, description=None, inception_date=None, benchmark="SPY") -> None`
- `record_fill(conn, strategy, ticker, action, qty, fill_price, fill_time, exec_id=None, commission=0.0) -> None`
  - Inserts into `fills`; runs `_apply_fifo_lot(conn, ...)` to update `tax_lots`
  - exec_id dedup: silently skips if exec_id already present
- `_apply_fifo_lot(conn, strategy, ticker, action, qty, fill_price, fill_date) -> None`
  - BUY: inserts a new lot with `qty_remaining = qty`
  - SELL: walks open lots oldest-first, closes or partial-closes each
    - Sets `close_date`, `close_price`, `realized_pnl`, `is_long_term`, `tax_rate`
- `sync_ib_fills(client, conn, strategy, since_date=None) -> int`
  - Calls `client.ib.reqExecutions(ExecutionFilter())` to fetch IB execution history
  - Filters to fills after `since_date`; calls `record_fill()` for each
  - Returns count of new fills inserted
- `record_nav(conn, strategy, nav, cash=None, equity_value=None, date=None) -> None`
  - Upserts into `daily_nav`; date defaults to today
- `record_score_snapshot(conn, strategy, scores_df, snapshot_date=None) -> None`
  - Inserts rows into `score_snapshots` from `scores_df` (output of `load_scores_csv()`)
  - snapshot_date defaults to today
- `update_forward_returns(conn, strategy, prices_df, lookback_days=30) -> int`
  - Finds snapshots where `forward_return IS NULL` and snapshot_date ≤ today − 30d
  - Looks up realized prices from `prices_df`; fills in `forward_return`
  - Returns count of rows updated

**Integration with `rebalance.py`:**
After each non-dry-run rebalance, `run_rebalance()` calls a hook:
```python
from ib_trader.tracker import record_fills_from_blotter
record_fills_from_blotter(conn, strategy, blotter_df, fill_time=datetime.utcnow())
```
The hook writes fills to the tracker DB automatically.

---

### Phase 8 — Performance & P&L Engine (`ib_trader/performance.py`) [IMPLEMENTED]

**Goal:** Compute P&L, risk-adjusted returns, and IC from tracker data.

Deliverables:
- `get_open_positions(conn, strategy) -> pd.DataFrame`
  - Columns: ticker, qty, avg_cost, current_price (None if offline), unrealized_pnl, unrealized_pnl_pct
  - Derives qty and avg_cost from `tax_lots` where `qty_remaining > 0`
- `get_pnl_summary(conn, strategy) -> dict`
  - Returns: unrealized_pnl, realized_pnl_st, realized_pnl_lt, tax_owed_st (24%), tax_owed_lt (15%), total_realized, net_after_tax
- `get_monthly_returns(conn, strategy) -> pd.Series`
  - Month-end NAV pct changes from `daily_nav`
  - Index: period end date; values: float return
- `get_performance_stats(conn, strategy, period="inception") -> dict`
  - Computes: CAGR, AnnVol, Sharpe, Sortino, MaxDD, Beta (vs benchmark), Win Rate
  - Periods: `"week"`, `"month"`, `"ytd"`, `"1y"`, `"inception"`
  - Beta and Alpha use daily returns of strategy vs SPY (fetched from Alpha Vantage or DuckDB daily_nav)
- `get_period_returns_table(conn, strategy) -> pd.DataFrame`
  - One row per period: week, month, ytd, 1y, inception; columns: return, annualized_vol, sharpe
- `get_ic_series(conn, strategy) -> pd.DataFrame`
  - Ranks scores and forward_return within each snapshot_date
  - Computes rank correlation (Spearman) per snapshot — one IC value per month
  - Columns: snapshot_date, ic, n_stocks, p_value
- `compare_vs_backtest(conn, strategy) -> pd.DataFrame`
  - Loads corresponding row from `backtest_benchmarks`
  - Pairs live stats vs backtest stats for CAGR, Sharpe, MaxDD, etc.
  - Columns: metric, live_value, backtest_value, delta
- `get_trade_history(conn, strategy, ticker=None, from_date=None, to_date=None) -> pd.DataFrame`
  - Columns: fill_time, ticker, action, qty, fill_price, commission, realized_pnl (for SELL fills), holding_days, is_long_term

---

### Phase 9 — Jupyter Interface & Snapshot Report (`ib_trader/report.py`) [IMPLEMENTED]

**Goal:** Clean Python functions for querying the tracker from a Jupyter notebook and a single-call snapshot report.

Deliverables:
- `snapshot_report(conn, strategy, client=None) -> None`
  - Prints a full strategy report to stdout / notebook output
  - Sections:
    1. **Account summary**: strategy name, inception date, NAV, cash, equity value (live from IB if client provided)
    2. **Performance**: week/month/YTD/1yr/since-inception returns + Sharpe
    3. **Risk diagnostics**: MaxDD, Beta, Sortino, Sharpe
    4. **vs Backtest**: live vs backtest CAGR, Sharpe, MaxDD, Alpha
    5. **Open positions**: ticker, qty, avg cost, current price, unrealized P&L, weight %
    6. **Realized P&L & Tax**: ST and LT realized gains, estimated tax owed
    7. **Model IC**: last 6 months of score IC values with mean
- `get_trades(conn, strategy, ticker=None, from_date=None, to_date=None) -> pd.DataFrame`
- `get_positions(conn, strategy) -> pd.DataFrame`
- `get_performance(conn, strategy) -> pd.DataFrame`  — weekly/monthly/YTD/1yr/inception table
- `get_tax_summary(conn, strategy, year=None) -> pd.DataFrame`
  - Columns: ticker, open_date, close_date, holding_days, cost_basis, proceeds, realized_pnl, is_long_term, tax_rate, tax_owed
- `compare_vs_backtest(conn, strategy) -> pd.DataFrame`
- `get_ic_series(conn, strategy) -> pd.DataFrame`

Example Jupyter usage:
```python
import duckdb, os
from ib_trader.report import snapshot_report, get_trades, get_tax_summary

conn = duckdb.connect(os.environ["IB_TRACKER_DB"])
snapshot_report(conn, "fundamentals_alpha")
get_tax_summary(conn, "fundamentals_alpha", year=2026)
```

---

### Phase 10 — Fill Sync Script & Notebook (`scripts/sync_fills.py`, `notebooks/portfolio_tracker.ipynb`) [IMPLEMENTED]

**Goal:** Standalone sync script for backfilling fills and an example Jupyter notebook.

`scripts/sync_fills.py` deliverables:
```
uv run scripts/sync_fills.py --strategy fundamentals_alpha
uv run scripts/sync_fills.py --strategy fundamentals_alpha --since 2026-01-01
uv run scripts/sync_fills.py --strategy ibd_50 --since 2026-04-01
uv run scripts/sync_fills.py --update-forward-returns   # fill in 30d returns for IC
```
Flags:
| Flag | Default | Description |
|---|---|---|
| `--strategy NAME` | required | Strategy name to sync |
| `--since DATE` | 90 days ago | Only sync fills after this date |
| `--update-forward-returns` | off | Fill in forward_return for old score snapshots |
| `--dry-run` | off | Print fills that would be inserted; do not write |

`notebooks/portfolio_tracker.ipynb` deliverables:
- Cell 1: Imports and DB connection setup
- Cell 2: `snapshot_report(conn, "fundamentals_alpha")`
- Cell 3: `get_trades(conn, "fundamentals_alpha")` — filterable by ticker / date
- Cell 4: `get_tax_summary(conn, "fundamentals_alpha", year=2026)`
- Cell 5: `compare_vs_backtest(conn, "fundamentals_alpha")` — live vs backtest table
- Cell 6: `get_ic_series(conn, "fundamentals_alpha")` — model IC time series plot

---

### Tracker Testing Checklist

- [ ] `init_tracker_db()` creates all tables; second call is idempotent
- [ ] `record_fill()` + `_apply_fifo_lot()`: BUY creates a lot; SELL closes oldest lot(s) first
- [ ] ST lot (held < 365 days) taxed at 24%; LT lot (held ≥ 365 days) taxed at 15%
- [ ] Duplicate exec_id is silently skipped (no duplicate fill rows)
- [ ] `sync_ib_fills()` inserts new fills from IB execution history without duplicates
- [ ] `get_monthly_returns()` matches manual NAV calculation from daily_nav
- [ ] `snapshot_report()` runs without error from a Jupyter cell
- [ ] Multi-strategy: fills for `fundamentals_alpha` and `ibd_50` in same DB do not mix

---

## Paper Testing Checklist (pre-live)

- [ ] Connect to paper TWS (127.0.0.1:7497) and verify `get_nav()` returns expected value
- [ ] Verify `get_positions()` matches TWS Portfolio tab
- [ ] Place a MOC order for 1 share of a liquid stock and confirm it fills at close
- [ ] Place a LMT order and verify cancel works
- [ ] Run full dry-run rebalance against last live_scores CSV; verify blotter is sensible
- [ ] Run full paper rebalance with `--no-dry-run`; verify fills match blotter
- [ ] Verify REPL `status` and `buy/sell` commands work end-to-end
- [ ] Verify REPL `cancel all` clears all open orders

---

## Open Questions (already answered)

| Question | Answer |
|---|---|
| Module location | `ib_trader/` at fin_import2 root |
| Primary workflow | Full rebalance |
| Default order type | MOC |
| Interface | CLI + REPL |

## All Decisions Resolved

| Question | Decision | Rationale |
|---|---|---|
| LMT price source | User-specified per ticker (REPL: `sell MSFT 30 LMT 450.00`); live mid-price auto-used in batch CLI `--order-type LMT` | Per-ticker control in REPL; mid-price is the only sensible batch fallback |
| Fractional shares | No — round down to whole shares (`math.floor`) | IB account does not use fractional shares |
| MOC for sells | Yes — use MOC for sells by default | Backtest returns are close-to-close; exiting at MOC matches the performance baseline. REPL allows `sell TICKER QTY MKT` for emergency overrides |
| Position exits | Auto-exit dropped positions (full rebalance) | The backtest exits anything not in top-N each month; deviating from this breaks strategy fidelity. Dry-run preview shows all exits before confirmation |
| Strategy tag | Yes — populate IB `orderRef` with strategy name | One field, zero cost, enables multi-strategy auditing in TWS blotter and account statements. Default: `"fundamentals_alpha"` |
| Trade capture | Both: auto-log fills in `rebalance.py` hook + `scripts/sync_fills.py` for backfill | Auto-log is primary; sync script corrects missed fills and covers manual trades |
| Tax lot method | FIFO | Simplest and default for most brokers; correct for cost basis and ST/LT determination |
| Tracker DB location | `data/ib_tracker.duckdb` in fin_import2; path from `IB_TRACKER_DB` env var | Consistent with project conventions; `trade_systems` sets env var to the same file |
| Predicted performance | Both IC tracking + live vs backtest comparison | IC measures whether model rankings still work; backtest comparison shows if strategy returns are on track |
| ST capital gains tax rate | 24% | Per user specification |
| LT capital gains tax rate | 15% | Per user specification; holding period threshold is 365 days |
| Benchmark | SPY (configurable via `IB_TRACKER_BENCHMARK`) | Consistent with backtest results; configurable per strategy |
