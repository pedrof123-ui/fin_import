# Fundamentals Alpha Runbook

This runbook describes how to operate the fundamentals-alpha stock-selection pipeline. It is a reference, not a tutorial. Read the Known Limitations section before acting on any model output.

---

## Prerequisites

**Python:** 3.12+

**Package manager:** uv. All commands in this runbook use `uv run`. Never use `python3` directly.

**Environment variables** — set in a `.env` file at the project root or in the shell before running any script:

| Variable | Description |
|---|---|
| `HF_DB_PATH` | Absolute path to `data/historic_fundamentals.duckdb` |
| `AV_DB_PATH` | Absolute path to `data/av_financials.duckdb` |
| `PRICES_DB_PATH` | Absolute path to prices.duckdb (contains `stock_prices` and SPY data) |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage API key (required for data imports only) |
| `IB_HOST` | TWS hostname (default: `127.0.0.1`) |
| `IB_PORT` | TWS port: `7497` = paper, `7496` = live (default: `7497`) |
| `IB_CLIENT_ID` | TWS client ID, must be unique per connection (default: `1`) |
| `IB_ACCOUNT` | IB account number; auto-detected from TWS if blank |
| `IB_MARKET_DATA_TYPE` | `1` = live data (default for live accounts), `3` = delayed (default for paper) |
| `IB_TRACKER_DB` | Absolute path to the tracker DuckDB. Use `data/ib_tracker_paper.duckdb` while paper trading, `data/ib_tracker_live.duckdb` for live. When set, fills, NAV, and score snapshots are automatically recorded. Leave blank to disable tracking. Override per command with `--tracker-db`. |
| `IB_TRACKER_BENCHMARK` | Benchmark ticker for beta/alpha calculations (default: `SPY`) |

**External databases:**

- `data/av_financials.duckdb` — Alpha Vantage financial statements (income, balance, cashflow, shares, dividends, company overview)
- `data/historic_fundamentals.duckdb` — computed monthly feature table (`monthly_pe`), PE stats, sector stats, earnings estimates
- prices DB at `PRICES_DB_PATH` — daily adjusted close prices and SPY daily returns

---

## Monthly Workflow — Quick Reference

Run once per month on the last trading day of the month.

### Part 1 — Refresh data (morning, any day after earnings season)

```bash
# Refresh raw AV data: statements, shares, dividends, company overview (~115 min)
uv run scripts/av_update.py

# Recompute derived metrics + analyst estimates + sector stats (~20 min)
uv run scripts/hf_update.py
```

### Part 2 — Score and rebalance (last trading day of the month, before 15:50 ET)

```bash
# Step 1 — Generate ranked scores; note the exact filename produced (e.g. docs/live_scores_20260529_rf_vw_gr_top_n_25.csv)
uv run scripts/score_live.py --top 25

# Step 2 — Preview rebalance (dry run, no orders submitted); replace YYYYMMDD with today's date
uv run scripts/rebalance.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --scores docs/live_scores_YYYYMMDD_rf_vw_gr_top_n_25.csv --use-strategy-nav

# Step 3 — Submit MOC orders (before 15:50 ET)
uv run scripts/rebalance.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --scores docs/live_scores_YYYYMMDD_rf_vw_gr_top_n_25.csv --use-strategy-nav --no-dry-run

# Step 4 — Sync confirmed fills (after close, same TWS session)
uv run scripts/sync_fills.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb
```

### Summary table

| Step | Script | When | Time |
|------|--------|------|------|
| Refresh raw AV data | `av_update.py` | Early month | ~115 min |
| Recompute metrics | `hf_update.py` | After av_update | ~20 min |
| Score universe | `score_live.py --top 25` | Rebalance morning | seconds |
| Review CSV + regime signal | — | Before orders | manual |
| Preview orders | `rebalance.py` (dry run) | Midday | seconds |
| Submit MOC orders | `rebalance.py --no-dry-run` | Before 15:50 ET | seconds |
| Sync confirmed fills | `sync_fills.py` | After close | seconds |

**Recommended portfolio:** `vw_gr_top_n_25` — vol-weighted, guardrails on, top 25, sector-neutral scoring.
Backtest (404 months, 1983–2026): 16.7% CAGR, 1.00 Sharpe, -35.4% MaxDD, 67.1% win rate.

---

## Data Pipeline

### Adding new tickers

Use `manage_tickers.py` to add a ticker to all three databases in one command (~8 AV calls per ticker):

```
uv run scripts/manage_tickers.py add AAPL MSFT NVDA
uv run scripts/manage_tickers.py add --csv data/new_tickers.csv
uv run scripts/manage_tickers.py add AAPL --dry-run     # preview without writing
```

The `add` pipeline runs automatically: price backfill → financials + shares + dividends → company overview → PE timeseries + goal prices → analyst estimates → all forward multiples. The ticker is immediately model-ready.

From `trade_systems`, use the programmatic bridge:

```python
from utilities.ticker_manager import add_tickers
add_tickers(["AAPL", "MSFT"])
```

### Removing tickers (delisted or irrelevant)

```
uv run scripts/manage_tickers.py delete GME BB
uv run scripts/manage_tickers.py delete --csv data/delisted.csv
```

Deletes from all three databases: `stock_prices`, `av_financials.duckdb` (8 tables), and `historic_fundamentals.duckdb` (3 tables). No AV API calls required.

---

### Monthly refresh for existing tickers

Run the following in order when refreshing data for tickers already in the pipeline.

#### Step 1 — Import financial statements

```
uv run scripts/av_import.py
```

Fetches income, balance sheet, and cash flow statements from Alpha Vantage for each ticker in the universe. Writes to `av_financials.duckdb`.

**API rate limit:** 75 calls/minute. The importer enforces this limit internally. Do not run multiple import processes in parallel.

#### Step 2 — Import company overview

```
uv run scripts/av_import_overview.py
```

Fetches sector, industry, company name, beta, and 41 other OVERVIEW fields per ticker. Required for sector filters and live scoring. Writes to `company_overview` table in `av_financials.duckdb`.

#### Step 3 — Incremental update for existing tickers

```
uv run scripts/av_update.py
```

Refreshes statements and overview for tickers already in the database. Use monthly to keep the feature store current.

#### Step 4 — Feature computation

Feature computation is not a standalone script. It is performed by calling `HistoricFundamentalsDB.upsert_monthly_pe()`, which internally calls `build_monthly_pe()` from `historic_fundamentals/pe.py`.

The bulk-compute helper scripts are:

```
uv run scripts/hf_import.py     # full backfill for all tickers
uv run scripts/hf_update.py     # monthly incremental update (preferred for production)
```

`hf_update.py` accepts `--skip-sector` and `--full-sector-rebuild` flags.

After this step, `monthly_pe` in `historic_fundamentals.duckdb` contains all computed features up to the current month.

---

## Validation Pipeline

Run the following after a data refresh to evaluate model quality. Each script writes a markdown results file to `docs/`.

### Baseline factors

```
uv run scripts/run_baselines.py
uv run scripts/run_baselines.py --min-cap 300e6   # alternative cap threshold
```

Computes IC, ICIR, Newey-West ICIR, hit rate, and quintile spreads for six single-factor baselines and a composite value score. Writes `docs/baseline_results.md`.

Required environment variables: `HF_DB_PATH`, `AV_DB_PATH`.

### Walk-forward validation

```
uv run scripts/run_walkforward.py
uv run scripts/run_walkforward.py --train-years 5 --test-years 1 --min-cap 1e9
uv run scripts/run_walkforward.py --verbose
```

Trains an XGBoost model using time-based walk-forward splits with a 12-month embargo. Reports OOS R², rank IC, ICIR, Newey-West ICIR, hit rate, quintile spreads, and SHAP feature stability across folds. Writes `docs/walkforward_results.md`.

In-sample metrics appear only as a sanity check. Out-of-sample metrics are the primary evidence.

Required environment variables: `HF_DB_PATH`, `AV_DB_PATH`.

### True monthly portfolio backtest

```
uv run scripts/run_backtest.py
uv run scripts/run_backtest.py --tc-bps 20 --min-cap 1e9
uv run scripts/run_backtest.py --guardrails --vol-weight
uv run scripts/run_backtest.py --guardrails --vol-weight --regime-filter
uv run scripts/run_backtest.py --help
```

Runs a non-overlapping monthly portfolio simulation. Computes CAGR, annualized volatility, Sharpe, max drawdown, beta to SPY, information ratio, tracking error, turnover, and transaction cost drag.

Key flags:

| Flag | Description |
|---|---|
| `--sector-neutral` | Z-score factors within (month, sector) instead of market-wide. Sectors with <3 stocks fall back to market-wide. **Recommended for all `gr_*` portfolios.** Output file gets `_sector_neutral` prefix. |
| `--guardrails` | Apply risk guardrails and 25% sector cap; produces `gr_*` portfolios |
| `--vol-weight` | Inverse-volatility position sizing (12-month rolling); produces `vw_gr_*` portfolios |
| `--regime-filter` | SPY 12-month regime filter (50% exposure when SPY 12m >25% or <-20%); produces `rf_gr_*` portfolios |
| `--model` | Also backtest the saved XGBoost model alongside composite baseline |
| `--tc-bps` | One-way transaction cost in basis points (default: 10) |
| `--score-buffer` | IQR hysteresis buffer for existing holdings (default: 10%) |

**Results files** — each flag combination writes a separate file:

| Command | Output file |
|---|---|
| `run_backtest.py` | `docs/backtest_results.md` — equal-weight composite baseline |
| `run_backtest.py --sector-neutral --guardrails --vol-weight --regime-filter` | `docs/backtest_results_sector_neutral_guardrails.md` — **recommended** sector-neutral `gr_*`, `vw_gr_*`, `rf_gr_*` |
| `run_backtest.py --guardrails --vol-weight` | `docs/backtest_results_guardrails.md` — market-wide `gr_*` and `vw_gr_*` (historical reference) |
| `run_backtest.py --model` | `docs/backtest_results_model.md` — XGBoost model, equal-weight |
| `run_backtest.py --model --guardrails --vol-weight` | `docs/backtest_results_model_guardrails.md` — XGBoost model with guardrails |

To view pre-computed results without re-running, open the file directly:

```
cat docs/backtest_results_sector_neutral_guardrails.md
```

Recommended production portfolio variants (sector-neutral composite score, 404 months 1983–2026, 25-stock):

| Portfolio | CAGR | Sharpe | MaxDD | Notes |
|---|---|---|---|---|
| `gr_top_n_25` | 17.0% | 0.96 | -39.7% | Equal-weight |
| `vw_gr_top_n_25` | 16.7% | 1.00 | -35.4% | Recommended default — best risk-adjusted |
| `rf_gr_top_n_25` | 15.6% | 1.02 | -25.7% | Capital-preservation priority; regime filter active |

Sector-neutral scoring validated in Phase 3: +0.3–0.5pp CAGR, +0.004–0.020 Sharpe, -1 to -5pp MaxDD vs market-wide z-score over the same period. Turnover unchanged.

Required environment variables: `HF_DB_PATH`, `AV_DB_PATH`, `PRICES_DB_PATH`.

### Risk diagnostics

```
uv run scripts/run_risk.py
uv run scripts/run_risk.py --tc-bps 20 --min-cap 1e9 --verbose
```

Generates sector exposure, market-cap exposure, position concentration, value-trap flags, guardrail violation counts, detailed drawdown statistics, and rolling beta decomposition. Writes `docs/risk_report.md`.

Required environment variables: `HF_DB_PATH`, `AV_DB_PATH`, `PRICES_DB_PATH`.

---

## Live Scoring

```
uv run scripts/score_live.py
uv run scripts/score_live.py --top 25
uv run scripts/score_live.py --top 50 --verbose
uv run scripts/score_live.py --output /path/to/scores.csv
uv run scripts/score_live.py --model /path/to/model.joblib
```

Produces a ranked list of investable stocks as of today. Output is printed to the terminal and written to `docs/live_scores_YYYYMMDD.csv`.

**What the script does:**

1. Loads the most recent `month_end_date` per ticker from `monthly_pe`, filtered to rows where `feature_available_date <= today`.
2. Joins sector, industry, and company name from `company_overview`.
3. Applies universe filters: market cap >= $1B, price >= $5, sector must be known, avg daily volume >= $5M.
4. Computes composite baseline score (cross-sectional z-score of six valuation and quality factors plus momentum and earnings quality).
5. Attempts to load a saved XGBoost model from `model.joblib` next to `HF_DB_PATH`. Falls back to composite baseline score if the file is not found.
6. Ranks tickers by score (1 = highest-scoring). Applies 25% per-sector cap.
7. Attaches value-trap flags and missing-data counts per row.
8. Computes inverse-volatility position weights (12-month rolling vol, 10% per-position cap). Falls back to equal-weight when `PRICES_DB_PATH` is unavailable.
9. Checks SPY 12-month trailing return for regime. Prints a regime banner and scales `alloc_pct` by 50% exposure in extreme regimes (SPY 12m >25% or <-20%).

**Output columns:** `rank`, `percentile`, `ticker`, `company_name`, `score`, `sector`, `market_cap`, `price`, `liquidity`, `weight_pct` (inverse-vol portfolio weight), `alloc_pct` (regime-adjusted allocation), `pe_ratio`, `fcf_yield`, `earnings_yield`, `ttm_gross_margin`, `ttm_operating_margin`, `debt_to_ebitda`, `roa`, `top_factor`, `value_trap`, `missing_factor_count`, `data_quality`, `feature_available_date`.

**Portfolio tracker integration:** When `IB_TRACKER_DB` is set in `.env`, `score_live.py` automatically records a score snapshot of all ranked tickers (ticker, rank, score, alloc_pct, price) to `data/ib_tracker.duckdb`. These snapshots are used to compute the model's live Information Coefficient (IC) 30 days later.

**Regime banner example:**

```
Regime:   REDUCED (SPY 12m: +26.6%)
Cash:     50.0%
```

Required environment variables: `HF_DB_PATH`, `AV_DB_PATH`. `PRICES_DB_PATH` is optional but required for vol-weighted sizing and the regime signal.

---

## Trade Execution

Requires TWS or IB Gateway running locally with API enabled. Set IB env vars in `.env` before running any script below.

### Paper vs live accounts

Use separate tracker databases for paper and live so the ledgers never mix. The `--tracker-db` flag overrides `IB_TRACKER_DB` per command, letting you run both simultaneously from different terminals.

| Mode | `IB_PORT` | Tracker DB | Typical strategy name |
|---|---|---|---|
| Paper | `7497` | `data/ib_tracker_paper.duckdb` | `vw_gr_top_n_25` |
| Live | `7496` | `data/ib_tracker_live.duckdb` | `fundamentals_alpha` |

---

### Paper trading pipeline — `vw_gr_top_n_25`

Run on the last trading day of each month (before 15:50 ET for steps 3–4). Set `IB_PORT=7497` in `.env` for all paper commands.

| Step | When | Command |
|---|---|---|
| 1. Generate scores | Morning | `uv run scripts/score_live.py --top 25` |
| 2. Preview rebalance | Midday | `uv run scripts/rebalance.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --scores docs/live_scores_YYYYMMDD_rf_vw_gr_top_n_25.csv --use-strategy-nav` |
| 3. Submit MOC orders | Before 15:50 ET | `uv run scripts/rebalance.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --scores docs/live_scores_YYYYMMDD_rf_vw_gr_top_n_25.csv --use-strategy-nav --no-dry-run` |
| 4. Sync confirmed fills | After close (same session) | `uv run scripts/sync_fills.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb` |
| 5. Update forward returns | 30+ days after first rebalance | `uv run scripts/sync_fills.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --update-forward-returns` |
| 6. View report | Anytime | `snapshot_report(conn, "vw_gr_top_n_25")` in Jupyter |

**NAV sizing — shared paper account:** Account DUE946835 is shared with other strategies. Never use the raw account NAV — it inflates position sizes. Use `--use-strategy-nav` (as above) once a correct strategy NAV is recorded in the tracker after the first successful `sync_fills.py` run. For the very first rebalance, or after a NAV reset, use `--nav-override 100000` instead of `--use-strategy-nav`.

**Scores file — always pass `--scores` explicitly:** The auto-finder picks the newest CSV by date, which may be a different strategy variant (e.g. `top_n_5`). Always pass the exact filename produced in step 1 to avoid loading the wrong portfolio.

**One-time setup (before first rebalance):**

```python
from ib_trader.tracker import init_tracker_db, register_strategy, load_backtest_benchmarks

conn = init_tracker_db("data/ib_tracker_paper.duckdb")
register_strategy(conn, "vw_gr_top_n_25",
                  description="Vol-weighted guardrails top-25, paper $100K",
                  inception_date="2026-05-29", benchmark="SPY")
load_backtest_benchmarks(conn, "vw_gr_top_n_25", "vw_gr_top_n_25", {
    "cagr": 0.167, "ann_vol": 0.169, "sharpe": 1.00, "sortino": 1.37,
    "max_dd": -0.354, "beta": 0.735, "alpha": 0.10, "win_rate": 0.671,
})
# Sector-neutral composite score, 404 months 1983–2026
conn.close()
```

**Start at month-end.** The strategy is calibrated on month-end to month-end returns. Starting mid-month creates a partial first period that does not match the backtest methodology.

---

### Live trading pipeline — general workflow

| Step | When | Command |
|---|---|---|
| 1. Generate scores | Morning | `uv run scripts/score_live.py --guardrails --vol-weight --top 25` |
| 2. Preview rebalance | Midday | `uv run scripts/rebalance.py --strategy STRATEGY --tracker-db data/ib_tracker_live.duckdb` |
| 3. Submit MOC orders | Before 15:50 ET | `uv run scripts/rebalance.py --strategy STRATEGY --tracker-db data/ib_tracker_live.duckdb --no-dry-run` |
| 4. Sync confirmed fills | After close (same session) | `uv run scripts/sync_fills.py --strategy STRATEGY --tracker-db data/ib_tracker_live.duckdb` |
| 5. Update forward returns | Monthly | `uv run scripts/sync_fills.py --strategy STRATEGY --tracker-db data/ib_tracker_live.duckdb --update-forward-returns` |

Set `IB_PORT=7496` in `.env` when targeting the live account.

---

### Step 1 — Generate live scores

```
uv run scripts/score_live.py --top 25
```

Writes `docs/live_scores_YYYYMMDD_rf_vw_gr_top_n_25.csv` with `alloc_pct` populated for the top-25 portfolio positions. Always regenerate scores before rebalancing to ensure the allocation reflects the latest data and regime signal.

When `IB_TRACKER_DB` is set (or `--tracker-db` is passed to the downstream scripts), the score snapshot is recorded automatically for IC tracking.

### Step 2 — Preview the rebalance

```
uv run scripts/rebalance.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb
```

Dry-run by default. Connects to TWS, fetches live prices, computes target shares from `alloc_pct × NAV / price` (whole shares), diffs against current holdings, and prints a blotter. No orders are submitted.

### Step 3 — Submit orders

```
uv run scripts/rebalance.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --no-dry-run
```

Cancels any open orders for affected tickers, then submits MOC orders for all buy/sell changes. Positions in current holdings that are not in the new portfolio are auto-exited (full SELL).

**MOC cutoff:** orders must be submitted before 15:50 ET. A warning is printed if you run after 15:45 ET.

Automatically records estimated fills (blotter quantities × live prices) and the post-rebalance NAV to the tracker database.

### Step 4 — Sync confirmed fills (same IB session)

```
uv run scripts/sync_fills.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb
```

Pulls actual execution records from IB (`reqExecutions`) and writes them to the tracker database with real exec IDs. Also records the current NAV. Run this in the same TWS session where orders were placed, as IB only returns fills from the current session.

```
uv run scripts/sync_fills.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --since 2026-01-01
uv run scripts/sync_fills.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --dry-run
```

### Additional CLI flags

| Flag | Description |
|---|---|
| `--scores PATH` | Explicit scores CSV path (default: latest `docs/live_scores_*.csv`) |
| `--dry-run` / `--no-dry-run` | Dry run (default) or live submission |
| `--order-type MOC\|MKT\|LMT` | Order type (default: MOC) |
| `--strategy TAG` | Strategy name written to IB `orderRef` and tracker DB |
| `--tracker-db PATH` | Tracker DuckDB path (overrides `IB_TRACKER_DB` env var) |
| `--status` | Print NAV, positions, open orders and exit |
| `--cancel-all` | Cancel all open orders and exit |
| `--verbose` | DEBUG-level logging |

### Interactive REPL

```
uv run scripts/ib_repl.py
```

For ad-hoc orders and inspection. Available commands:

```
status                         Show NAV, positions, and open orders
buy  TICKER QTY [TYPE [PRICE]] Buy shares  (default: MOC)
sell TICKER QTY [TYPE [PRICE]] Sell shares (default: MOC)
quote TICKER                   Show live bid / ask / last
cancel ORDER_ID                Cancel a specific open order
cancel all                     Cancel all open orders
preview [PATH]                 Show rebalance diff without submitting
rebalance [PATH]               Dry-run rebalance (latest CSV if no PATH)
rebalance [PATH] --confirm     Submit rebalance orders
help                           Show this help
quit / exit                    Disconnect and exit
```

Order types: `MOC` (default), `MKT`, `LMT`. Limit example: `sell MSFT 30 LMT 450.00`.

---

## Portfolio Tracker

The portfolio tracker is a persistent DuckDB ledger that records every fill, tracks FIFO tax lots, measures live risk-adjusted returns, and compares them against the backtest benchmark. It is optional — all integration is conditional on `IB_TRACKER_DB` being set or `--tracker-db` being passed.

### Paper vs live databases

Use separate databases for paper and live trading so the ledgers never mix. Each database is created automatically on first use.

| Mode | Database path | `.env` setting |
|---|---|---|
| Paper | `data/ib_tracker_paper.duckdb` | `IB_TRACKER_DB=.../data/ib_tracker_paper.duckdb` |
| Live | `data/ib_tracker_live.duckdb` | `IB_TRACKER_DB=.../data/ib_tracker_live.duckdb` |

When running paper and live simultaneously from different terminals, use `--tracker-db` per command instead of relying on the env var:

```
# Paper terminal
uv run scripts/rebalance.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb --no-dry-run

# Live terminal
uv run scripts/rebalance.py --strategy fundamentals_alpha --tracker-db data/ib_tracker_live.duckdb --no-dry-run
```

### First-time setup

Add to `.env` (use the paper path while paper trading):

```
IB_TRACKER_DB=/home/pedro/projects/fin_import2/data/ib_tracker_paper.duckdb
IB_TRACKER_BENCHMARK=SPY
```

Register each strategy once:

```python
from ib_trader.tracker import init_tracker_db, register_strategy

conn = init_tracker_db("data/ib_tracker_paper.duckdb")
register_strategy(conn, "vw_gr_top_n_25",
                  description="Vol-weighted guardrails top-25, paper $100K",
                  inception_date="2026-05-29", benchmark="SPY")
conn.close()
```

### What gets recorded automatically

| Event | Trigger | Function called |
|---|---|---|
| Score snapshot | `score_live.py` finishes | `record_score_snapshot()` |
| Estimated fills | `rebalance.py --no-dry-run` | `record_fills_from_blotter()` |
| NAV (post-rebalance) | `rebalance.py --no-dry-run` | `record_nav()` |
| Confirmed fills + NAV | `sync_fills.py` | `sync_ib_fills()`, `record_nav()` |
| Forward returns (IC) | `sync_fills.py --update-forward-returns` | `update_forward_returns()` |

### Syncing confirmed fills

Immediately after a live rebalance, pull actual IB execution records:

```
uv run scripts/sync_fills.py --strategy fundamentals_alpha
uv run scripts/sync_fills.py --strategy fundamentals_alpha --since 2026-01-01
uv run scripts/sync_fills.py --strategy fundamentals_alpha --dry-run
```

This replaces the blotter estimates with IB's actual exec IDs, quantities, and fill prices, enabling slippage calculation.

IB's `reqExecutions()` only returns fills from the current TWS session. Run sync_fills.py in the same session where orders were placed.

### Updating forward returns (IC)

Once a month, fill in 30-day forward returns for old score snapshots:

```
uv run scripts/sync_fills.py --strategy fundamentals_alpha --update-forward-returns
```

This downloads prices via yfinance and computes `(price_30d_later / price_at_score) - 1` for every snapshot row older than 30 days where `forward_return IS NULL`.

### Viewing the report

Open `notebooks/portfolio_tracker.ipynb` in Jupyter:

```python
from ib_trader.tracker import init_tracker_db
from ib_trader.report import snapshot_report

conn = init_tracker_db()
snapshot_report(conn, "fundamentals_alpha")
```

The report prints eight sections: account summary, performance (week/month/YTD/1yr/inception), risk diagnostics (Sharpe/Sortino/MaxDD/Beta), live vs backtest comparison, open positions with unrealized P&L, realized P&L and estimated tax, slippage analysis, and model IC time series.

### Jupyter query functions

| Function | Returns |
|---|---|
| `get_trades(conn, strategy)` | All fills with realized P&L per SELL |
| `get_positions(conn, strategy)` | Open positions: qty, avg cost, unrealized P&L |
| `get_performance(conn, strategy)` | Week/month/YTD/1yr/inception returns + Sharpe |
| `get_tax_summary(conn, strategy, year=2026)` | Tax lots: ST/LT classification, proceeds, tax owed |
| `compare_vs_backtest(conn, strategy)` | Live CAGR/Sharpe/MaxDD vs backtest benchmark |
| `get_ic_series(conn, strategy)` | Spearman IC per snapshot month |
| `get_slippage_summary(conn, strategy)` | Avg bps, median bps, total dollars vs 10 bps backtest assumption |

### Slippage tracking

Every fill stores a `reference_price` — the CSV closing price from the live scores file. Slippage is computed as:

```
BUY  slippage_bps = (fill_price - reference_price) / reference_price * 10000
SELL slippage_bps = (reference_price - fill_price) / reference_price * 10000
```

Negative slippage means a better-than-reference fill. `get_slippage_summary()` compares mean live slippage against the 10 bps backtest TC assumption.

### Tax lot accounting

The tracker uses FIFO (first-in, first-out) lot assignment. Each BUY creates a new lot; each SELL walks the oldest open lots and closes them in order, splitting partial quantities automatically. Tax treatment:

- Short-term (held < 365 days): taxed at 24%
- Long-term (held >= 365 days): taxed at 15%

`get_tax_summary()` exports a per-lot breakdown ready for Schedule D filing.

---

## Running Tests

**Unit tests (no database, no network):**

```
uv run pytest tests/ --ignore=tests/test_api.py
```

Runs approximately 168 unit tests. All tests should pass. Failing tests must not be hidden or suppressed.

**Integration tests (requires network and AV API key):**

```
uv run pytest tests/ -m integration
```

---

## Model Assumptions

**Point-in-time safety**

All features enforce a conservative reporting-lag policy. No SEC filing-date data is stored in the database. Instead:

- Quarterly data: available at `fiscal_period_end + 60 days`
- Annual data: available at `fiscal_period_end + 90 days`

The feature engine logs a warning if any data row would have been included at an earlier date without this lag. `feature_available_date` is stored per row and used by the live scoring script to prevent forward-looking data.

**Universe filters**

| Filter | Default |
|---|---|
| Market cap | >= $1,000,000,000 ($1B) |
| Price | >= $5.00 |
| Sector | Must be known (not NULL, not empty) |
| Volume | Not implemented (see Known Limitations) |

All filters are configurable. Missing market cap, price, or sector fails the filter — it does not bypass it.

**Walk-forward configuration**

| Parameter | Default |
|---|---|
| Training window | 5 years |
| Test window | 1 year |
| Embargo | 12 months before test start |
| Primary target | 1-year forward return (`ret_1y`) |

The 12-month embargo ensures that training labels do not embed prices from the test period (forward return targets use future prices; dropping the embargo period prevents leakage of those future prices into training).

**Composite baseline score**

Sector-neutral z-score composite of ten factors. Each factor is z-scored within `(month_end_date, sector)` — i.e. Apple is compared against tech peers, not against ExxonMobil. Sectors with fewer than 3 stocks in a month fall back to market-wide z-score for that group.

| Factor | Direction | Group |
|---|---|---|
| `ps_ratio` | Lower is better | Value |
| `fcf_yield` | Higher is better | Value |
| `ev_ebitda` | Lower is better | Value |
| `earnings_yield` | Higher is better | Value |
| `roic` | Higher is better | Quality |
| `roa` | Higher is better | Quality |
| `operating_margin_slope_5y` | Higher is better | Quality |
| `earnings_quality` | Higher is better | Quality (Sloan accruals: OCF−NI / avg_assets; higher = less accrual = more cash-backed) |
| `asset_growth` | Lower is better | Quality (Titman 2004: overinvestment predicts underperformance) |
| `momentum_12_1` | Higher is better | Momentum |

Factors with the "lower is better" convention are sign-flipped before z-scoring so that a higher composite score always means a better-ranked stock.

Implemented in `historic_fundamentals/baselines.py:composite_score()` with `sector_neutral=True` (default). Pass `sector_neutral=False` to revert to market-wide z-scores.

**XGBoost model features (35 total)**

The XGBoost model uses all composite factors plus additional features: normalized multiples (`earnings_yield_norm`, `fcf_yield_norm`, `ev_ebitda_norm`, `ps_ratio_norm`), margin levels and stability (gross/operating/FCF margins, 5y medians and slopes), leverage (`debt_to_ebitda`, `interest_coverage`), return-on-capital stability (`roa_stability_5y`), asset growth (`asset_growth`, YoY total_assets growth — XGBoost only, not in composite), and rolling median multiples.

**Transaction costs**

Default: 10 basis points one-way per trade. Configurable via `--tc-bps` on the validation scripts. The live scoring script does not apply transaction costs (it ranks, not simulates).

**Rebalancing**

Monthly. Position sizing depends on variant:
- `gr_top_n_25`: Equal-weight, 25% per-sector cap, 10% IQR score buffer for current holdings.
- `vw_gr_top_n_25`: Inverse-volatility weighted (12-month rolling monthly std), 10% per-position cap, same guardrails.
- `rf_gr_top_n_25`: Same as `vw_gr_top_n_25` with SPY 12m regime filter (50% exposure in extreme regimes).

No leverage in any variant.

---

## Known Limitations

**No filing-date data.** Alpha Vantage does not provide SEC EDGAR `accepted_date`. The conservative fiscal-period-end lag (quarterly +60d, annual +90d) is used as a proxy. This can understate freshness for companies that file early, and may fail to catch late filers. True point-in-time safety would require SEC EDGAR accepted dates.

**Liquidity filter uses historical ADV.** The backtest computes 30-day rolling average daily dollar volume from price history and requires >= $5M ADV. Live scoring reads the `liquidity` column from `monthly_pe` when available; if volume data is absent for a ticker it is excluded from the filtered universe. ADV data is sourced from `PRICES_DB_PATH`.

**Sector classification is point-in-time unsafe.** The `company_overview` table stores the most recent sector snapshot per ticker. Historical sector changes are not tracked. Backtest sector exposure is therefore an approximation.

**XGBoost model artifact.** `train_model.py` trains a final model on the full dataset and saves `data/model.joblib`. Live scoring loads this file automatically from the same directory as `HF_DB_PATH`. The model is retrained manually after adding new features; it is not auto-refreshed by `hf_update.py`.

**`roa_stability_5y` naming is inverted.** This feature is `std(ROA over 5 years)`. A higher value means more volatile ROA — which is worse. The name implies stability but the value is volatility. Use with care in model interpretation.

**Overlapping forward returns are training labels only.** Monthly rows computed at time t with 12-month forward returns naturally overlap across consecutive months. These overlapping returns are used only as training labels for the XGBoost model. They are not compounded into a portfolio equity curve. The backtest uses true non-overlapping monthly holding-period returns.

**In-sample metrics are not final evidence.** Walk-forward results display both in-sample and out-of-sample metrics. Only OOS metrics should be used when assessing model quality.

**Sector concentration is not constrained in the backtest.** The portfolio backtest does not enforce a sector-weight cap. High sector concentration may appear in some periods. Review `docs/risk_report.md` before using the model.

**This model is a research tool until all go/no-go criteria pass.** See the Go/No-Go Criteria section below.

---

## Go/No-Go Criteria

The model should be treated as a research tool until all criteria below are verified. Do not use it to place live trades if any item is unchecked.

- [x] Walk-forward OOS rank IC > 0.03 — **PASSED** (mean IC = 0.035, NW-ICIR = 3.33 across 16 folds)
- [x] Walk-forward hit rate > 50% — **PASSED** (58.3%)
- [x] Backtest Sharpe ratio (net of transaction costs) > 0.5 — **PASSED** (vw_gr_top_n_25: 1.00, sector-neutral, 404 months)
- [ ] No single sector > 40% of live portfolio in the current month
- [ ] No more than 20% of live output flagged as `value_trap = True`
- [ ] All unit tests pass (`uv run pytest tests/ --ignore=tests/test_api.py`)
- [ ] `feature_available_date` <= today for all rows in live scoring output
- [ ] Investable universe contains >= 50 stocks in the current month
- [ ] Live scoring output has been reviewed for obvious data anomalies before acting

**Note on survivorship bias:** The historical universe is built from currently-active tickers. Bankruptcies, acquisitions, and delistings are absent. Estimated inflation: 0.5–1.5 pp/year CAGR. This does not change the go/no-go decision given 15+ pp outperformance versus SPY. See `docs/survivorship_bias_report.md`.

---

## Reviewer Workflow

Phases requiring methodology approval must go through the reviewer gate documented in `REVIEWER_APPROVAL_CRITERIA.md`. The approval matrix is:

| Phase | Reviewer | Approval required |
|---|---|---|
| Phase 0: Repository Discovery | Code Reviewer | Yes |
| Phase 1: Point-in-Time Audit | Quant Reviewer | Yes |
| Phase 2: Universe/Liquidity Filters | Quant Reviewer | Yes |
| Phase 3: Feature Engineering | Code + Quant Reviewer | Yes |
| Phase 4: Baseline Factors | Quant Reviewer | Yes |
| Phase 5: Walk-Forward ML | Quant Reviewer | Yes |
| Phase 6: Monthly Portfolio Backtest | Quant Reviewer | Yes |
| Phase 7: Risk Diagnostics | Quant Reviewer | Yes |
| Phase 8: Live Scoring | Code + Quant Reviewer | Yes |
| Phase 9: Documentation | Code Reviewer | No, unless methodology changed |

No phase marked "Yes" may proceed without an explicit `APPROVE` decision from the required reviewer.
