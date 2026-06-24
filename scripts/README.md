# scripts/

CLI scripts for the Alpha Vantage financial statements pipeline and historic fundamentals.

All scripts read configuration from `.env` in the project root and must be run with `uv run`.

## Required .env variables

```
ALPHA_VANTAGE_API_KEY=<premium key>
PRICES_DB_PATH=/path/to/trade_systems/data/prices.duckdb
AV_DB_PATH=data/av_financials.duckdb   # optional; this is the default
HF_DB_PATH=data/historic_fundamentals.duckdb  # optional; this is the default
```

---

## manage_tickers.py

**Recommended script for all ticker add and delete operations.** Manages tickers across all three databases: `prices.duckdb`, `av_financials.duckdb`, and `historic_fundamentals.duckdb`.

### add — full onboarding pipeline

For each ticker, runs in sequence:

1. Backfills price history (AV `TIME_SERIES_DAILY_ADJUSTED`) → `prices.duckdb / stock_prices`
2. Fetches income / balance / cashflow statements → `av_financials.duckdb`
3. Fetches shares outstanding → `av_financials.duckdb`
4. Fetches dividend history → `av_financials.duckdb`
5. Fetches company overview (sector, industry, name) → `av_financials.duckdb`
6. Computes monthly PE timeseries + goal prices → `historic_fundamentals.duckdb / monthly_pe`
7. Fetches analyst earnings estimates → `historic_fundamentals.duckdb`
8. Computes all forward multiples (P/E, P/FCF, EV/EBITDA, P/S, market cap) → `pe_stats`

A ticker added via `manage_tickers.py add` is immediately model-ready: it has prices, sector data, PE history, and all forward multiples.

```bash
uv run scripts/manage_tickers.py add AAPL MSFT NVDA
uv run scripts/manage_tickers.py add --csv data/new_tickers.csv
uv run scripts/manage_tickers.py add AAPL --force           # re-import even if in DB
uv run scripts/manage_tickers.py add AAPL --skip-estimates  # skip EARNINGS_ESTIMATES call
uv run scripts/manage_tickers.py add AAPL --dry-run         # preview without writing
```

Rate: ~8 AV calls/ticker (prices + 3 statements + shares + dividends + overview + estimates). At 75/min: ~9 tickers/min.

### delete — remove from all databases

Removes all rows for the ticker from `stock_prices`, `av_financials.duckdb` (8 tables), and `historic_fundamentals.duckdb` (3 tables). Use for delisted or irrelevant tickers.

```bash
uv run scripts/manage_tickers.py delete GME BB AMC
uv run scripts/manage_tickers.py delete --csv data/delisted.csv
uv run scripts/manage_tickers.py delete AAPL --dry-run      # preview without writing
```

No AV API calls; instant.

### Options (both subcommands)

| Flag | Applies to | Description |
|------|-----------|-------------|
| `--csv FILE` | add, delete | Read tickers from first column of a CSV file |
| `--dry-run` | add, delete | Print plan without modifying any database |
| `--verbose` | add, delete | Show DEBUG-level output |
| `--force` | add | Re-import tickers already present in the DB |
| `--skip-estimates` | add | Skip EARNINGS_ESTIMATES API call (saves 1 AV call/ticker) |

### Using from trade_systems

```python
from utilities.ticker_manager import add_tickers, delete_tickers

add_tickers(["AAPL", "MSFT"])   # full pipeline
delete_tickers(["GME", "BB"])   # all three databases
```

---

## av_import.py

Downloads income statements, balance sheets, cash flow statements, shares outstanding, and
dividend history from Alpha Vantage and stores them in `data/av_financials.duckdb`.

Use `manage_tickers.py add` when you also want historic fundamentals computed. Use `av_import.py`
when you only need raw AV data (e.g., before running `hf_import.py` separately).

### Source (pick one)

```bash
uv run scripts/av_import.py AAPL [MSFT ...]     # one or more tickers
uv run scripts/av_import.py --csv FILE          # first column of a CSV file
uv run scripts/av_import.py --from-prices-db    # all tickers from prices.duckdb
```

### Options

| Flag | Description |
|------|-------------|
| `--force` | Re-fetch and overwrite tickers already in the DB. Without this, existing tickers are skipped. |
| `--skip-shares` | Skip SHARES_OUTSTANDING calls. |
| `--skip-dividends` | Skip DIVIDENDS calls. |
| `--db PATH` | Use a different DuckDB file instead of `data/av_financials.duckdb`. |
| `--verbose` | Enable DEBUG-level logging (individual API call details). |

### Examples

```bash
uv run scripts/av_import.py AAPL MSFT GOOGL
uv run scripts/av_import.py --csv data/test_tickers.csv --force
uv run scripts/av_import.py --from-prices-db
uv run scripts/av_import.py AAPL --force --db data/custom.duckdb
```

Each ticker costs 5 API calls (3 statements + shares + dividends). At 75/min: ~15 tickers/min.

---

## av_import_shares.py

Standalone backfill for the `shares_outstanding` table. Fetches the SHARES_OUTSTANDING
endpoint for all tickers already in `av_financials.duckdb` (or a specified subset).

```bash
uv run scripts/av_import_shares.py                     # all tickers in av_financials.duckdb
uv run scripts/av_import_shares.py AAPL MSFT           # specific tickers
uv run scripts/av_import_shares.py --force             # re-fetch even if data exists
uv run scripts/av_import_shares.py --db PATH --verbose
```

Rate: 1 AV call/ticker. After running, re-run `hf_update.py --skip-estimates` to recompute PE with updated shares.

---

## av_import_dividends.py

Standalone backfill for the `dividends` table. Fetches the DIVIDENDS endpoint for all tickers
already in `av_financials.duckdb` (or a specified subset).

```bash
uv run scripts/av_import_dividends.py                  # all tickers in av_financials.duckdb
uv run scripts/av_import_dividends.py AAPL MSFT        # specific tickers
uv run scripts/av_import_dividends.py --force          # re-fetch even if data exists
uv run scripts/av_import_dividends.py --db PATH --verbose
```

Rate: 1 AV call/ticker (~18 min for ~1,400 tickers). After running, re-run `hf_update.py --skip-estimates` to refresh `dividend_yield` in `monthly_pe`.

---

## av_query.py

Queries stored financial statements and prints to stdout or exports to CSV.

```bash
uv run scripts/av_query.py AAPL
uv run scripts/av_query.py AAPL MSFT --statement income --period annual
uv run scripts/av_query.py AAPL --start 2020-01-01 --end 2024-12-31
uv run scripts/av_query.py AAPL --statement balance --out output.csv
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--statement` | `all` | `income`, `balance`, `cashflow`, or `all` |
| `--period` | `all` | `annual`, `quarterly`, or `all` |
| `--start` | none | ISO date lower bound on fiscal_date_ending (inclusive) |
| `--end` | none | ISO date upper bound on fiscal_date_ending (inclusive) |
| `--out FILE` | none | Write CSV to FILE; prints to stdout if omitted |
| `--db PATH` | from `.env` | Override DB path |
| `--verbose` | off | Enable DEBUG logging |

---

## av_update.py

Monthly refresh: re-fetches all data (statements + shares + dividends) for every ticker already
in `av_financials.duckdb`. Intended to run once per month after earnings season.

```bash
uv run scripts/av_update.py                    # update all tickers in DB
uv run scripts/av_update.py --ticker AAPL      # update one specific ticker
uv run scripts/av_update.py --skip-shares      # skip SHARES_OUTSTANDING calls
uv run scripts/av_update.py --skip-dividends   # skip DIVIDENDS calls
uv run scripts/av_update.py --db data/custom.duckdb
```

Each ticker costs 5 API calls. At 75/min: ~15 tickers/min; ~95 min for ~1,400 tickers.
All updates use `INSERT OR REPLACE`, so existing rows are overwritten with the latest data.

---

## hf_import.py

Bulk backfill for `data/historic_fundamentals.duckdb`. For each ticker: computes full monthly
PE + dividend yield history from `av_financials.duckdb` (no AV calls), then fetches
`EARNINGS_ESTIMATES` from Alpha Vantage (1 call/ticker) to populate analyst estimates and forward PE.

Use `manage_tickers.py add` when adding new tickers from scratch — it runs both AV import and hf_import
in a single pass. Use `hf_import.py` standalone when `av_financials.duckdb` is already populated
and you only need to (re)build the derived metrics.

### Source (pick one)

```bash
uv run scripts/hf_import.py                     # all tickers from av_financials.duckdb
uv run scripts/hf_import.py AAPL MSFT GOOGL    # specific tickers
uv run scripts/hf_import.py --csv tickers.csv  # first column of a CSV file
```

### Options

| Flag | Description |
|------|-------------|
| `--force` | Recalculate and overwrite tickers already in the DB. Without this, tickers with existing PE stats are skipped. |
| `--skip-estimates` | Skip the Alpha Vantage EARNINGS_ESTIMATES fetch. PE + dividend yield history still computed. |
| `--db PATH` | Use a different DuckDB file instead of `data/historic_fundamentals.duckdb`. |
| `--verbose` | Enable DEBUG-level logging. |

### Examples

```bash
uv run scripts/hf_import.py                                        # full initial backfill
uv run scripts/hf_import.py AAPL MSFT --force                     # force-refresh two tickers
uv run scripts/hf_import.py --csv data/sp500.csv --skip-estimates # PE + yield only
```

PE + dividend yield phase is local (no AV calls): a few minutes for all tickers.
Estimates phase: 1 AV call/ticker at 75/min = ~20 min for ~1,400 tickers.

---

## hf_update.py

Monthly refresh for `data/historic_fundamentals.duckdb`. Reads the list of tickers already in
`pe_stats`, recomputes their full monthly PE + dividend yield timeseries from updated
`av_financials.duckdb` data, recomputes revenue and earnings EPS growth CAGRs, and refreshes
analyst estimates from Alpha Vantage. Intended to run at the start of each month after
`av_update.py` has refreshed the raw data.

```bash
uv run scripts/hf_update.py                     # update all tickers already in the DB
uv run scripts/hf_update.py --ticker AAPL       # update a single ticker
uv run scripts/hf_update.py --skip-estimates    # PE + yield refresh only, no AV calls
uv run scripts/hf_update.py --db PATH           # override DB path
```

---

## hf_query.py

Query `data/historic_fundamentals.duckdb` and print results to stdout or a CSV file.

### Views

| View | Description |
|------|-------------|
| `stats` (default) | Snapshot per ticker: current PE, long-term median, percentiles, rolling 5yr median, forward PE, current TTM dividend yield |
| `timeseries` | Monthly history: price, ttm_eps, pe_ratio, rolling_5yr_median, ttm_dividend, dividend_yield |
| `estimates` | Latest analyst EPS and revenue estimates per (ticker, fiscal_date, horizon) |

### Usage

```bash
uv run scripts/hf_query.py AAPL                                 # PE + yield stats for one ticker
uv run scripts/hf_query.py AAPL MSFT                           # PE + yield stats for multiple tickers
uv run scripts/hf_query.py --all                                # PE + yield stats for all tickers
uv run scripts/hf_query.py AAPL --view timeseries              # monthly PE + yield history
uv run scripts/hf_query.py AAPL --view timeseries --start 2020-01-01 --end 2024-12-31
uv run scripts/hf_query.py AAPL --view estimates               # analyst estimates
uv run scripts/hf_query.py AAPL --view estimates --horizon "fiscal quarter"
uv run scripts/hf_query.py --all --view stats --out output.csv # export all to CSV
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--view` | `stats` | `stats`, `timeseries`, or `estimates` |
| `--all` | off | Query all tickers in the DB (mutually exclusive with positional tickers) |
| `--start` | none | ISO date lower bound for timeseries (inclusive) |
| `--end` | none | ISO date upper bound for timeseries (inclusive) |
| `--horizon` | both | Filter estimates by `"fiscal quarter"` or `"fiscal year"` |
| `--out FILE` | none | Write CSV to FILE; prints to stdout if omitted |
| `--db PATH` | from `.env` | Override DB path |
| `--verbose` | off | Enable DEBUG logging |

---

## earnings_backfill.py

One-time backfill: fetch the latest N quarters of earnings call transcripts for every ticker in `av_financials.duckdb` and store them in `data/earnings_transcripts.duckdb`. Resume-safe — already-cached `(symbol, quarter)` pairs are always skipped.

```bash
uv run scripts/earnings_backfill.py                    # all tickers, last 4 quarters (~2.5 hrs)
uv run scripts/earnings_backfill.py --ticker AAPL      # single ticker
uv run scripts/earnings_backfill.py --dry-run          # print plan without making API calls
uv run scripts/earnings_backfill.py --quarters 8       # extend to 8 quarters per ticker
uv run scripts/earnings_backfill.py --db PATH          # override DB path
uv run scripts/earnings_backfill.py --verbose          # DEBUG logging
```

Rate: up to `--quarters` AV calls per ticker at 75 calls/min. The 60-day lookahead rule applies: if a ticker's latest `fiscal_date_ending` in `av_financials.duckdb` is more than 60 days ago, the following quarter is also probed (in case the company has already reported but the financials have not been imported yet).

Required: `ALPHA_VANTAGE_API_KEY`.

---

## earnings_calendar_update.py

Weekly refresh of the Earnings Calendar for all tracked tickers. Fetches the AV
`EARNINGS_CALENDAR` endpoint (3-month horizon, single API call), filters to symbols
present in `av_financials.duckdb`, and upserts into the `earnings_calendar` table.
Entries with `report_date` older than 30 days are purged each run.

```bash
uv run scripts/earnings_calendar_update.py
uv run scripts/earnings_calendar_update.py --verbose
uv run scripts/earnings_calendar_update.py --db PATH
```

Rate: 1 AV API call per run. Results appear in the Calendar tab of FinView.

Cron (weekly, Monday 6 AM — run alongside `earnings_update.py`):
```
0 6 * * 1 cd /home/pedro/projects/fin_import2 && uv run scripts/earnings_calendar_update.py >> logs/earnings_calendar.log 2>&1
```

Required: `ALPHA_VANTAGE_API_KEY`.

---

## earnings_update.py

Weekly update: check the latest 1–2 quarters per ticker for new earnings call transcripts. Intended to run once per week (e.g. Sunday night via cron). Skips quarters already cached.

```bash
uv run scripts/earnings_update.py                      # all tickers
uv run scripts/earnings_update.py --ticker MSFT        # single ticker
uv run scripts/earnings_update.py --db PATH            # override DB path
uv run scripts/earnings_update.py --verbose            # DEBUG logging
```

Rate: up to 2 AV calls per ticker at 75 calls/min. Typically faster since most quarters are already cached. Applies the same 60-day lookahead rule as `earnings_backfill.py`.

Required: `ALPHA_VANTAGE_API_KEY`.

---

## rebuild_sector_stats.py

Full rebuild of the `sector_stats` table in `data/historic_fundamentals.duckdb`. Drops and recomputes all sector and industry aggregate rows across all available months (~43K rows covering 11 sectors + ~100 industries).

Run this after:
- Schema changes to `sector_stats` (e.g. adding new columns via `ALTER TABLE`)
- Adding a large batch of new tickers
- Any change to the aggregation SQL in `historic_fundamentals/sector.py`

```bash
uv run scripts/rebuild_sector_stats.py
```

No flags. Uses `HF_DB_PATH` and `AV_FINANCIALS_DB_PATH` from `.env` (defaults to `data/historic_fundamentals.duckdb` and `data/av_financials.duckdb`).

Runtime: ~1-2 minutes for full rebuild. The monthly update script `hf_update.py` also updates sector stats incrementally (latest 3 months) after each ticker refresh.

---

## run_baselines.py

Computes IC, ICIR, Newey-West ICIR, hit rate, and quintile spreads for six single-factor baselines and the composite score. Writes `docs/baseline_results.md`.

```bash
uv run scripts/run_baselines.py
uv run scripts/run_baselines.py --min-cap 300e6
```

Required: `HF_DB_PATH`, `AV_DB_PATH`.

---

## validate_model.py

Walk-forward XGBoost validation with embargo. Per-fold and yearly OOS IC, ICIR, NW-ICIR, hit rate, Q5-Q1 spread, and feature importance. Writes `docs/validation_report.md`.

```bash
uv run scripts/validate_model.py
uv run scripts/validate_model.py --train-years 5 --test-years 1 --min-cap 1e9
uv run scripts/validate_model.py --verbose
```

| Flag | Default | Description |
|------|---------|-------------|
| `--train-years` | 5 | Rolling training window in years |
| `--test-years` | 1 | Test fold length in years |
| `--min-cap` | 1e9 | Minimum market cap filter |
| `--verbose` | off | Enable DEBUG logging |

Required: `HF_DB_PATH`, `AV_DB_PATH`.

---

## train_model.py

Trains a final XGBoost model on the full dataset and saves `data/model.joblib`. Run after adding new features or after a significant data refresh.

```bash
uv run scripts/train_model.py
uv run scripts/train_model.py --min-cap 1e9 --verbose
```

| Flag | Default | Description |
|------|---------|-------------|
| `--min-cap` | 1e9 | Minimum market cap filter |
| `--verbose` | off | Enable DEBUG logging |

Required: `HF_DB_PATH`, `AV_DB_PATH`.

---

## run_backtest.py

True monthly non-overlapping portfolio backtest vs SPY. Writes `docs/backtest_results.md`.

```bash
uv run scripts/run_backtest.py
uv run scripts/run_backtest.py --guardrails --vol-weight
uv run scripts/run_backtest.py --guardrails --vol-weight --regime-filter
uv run scripts/run_backtest.py --tc-bps 20 --min-cap 1e9
uv run scripts/run_backtest.py --model --guardrails
```

| Flag | Default | Description |
|------|---------|-------------|
| `--sector-neutral` | off | Z-score factors within (month, sector) instead of market-wide. Sectors with <3 stocks fall back to market-wide. **Recommended** — validated +0.3–0.5pp CAGR, +0.004–0.020 Sharpe, -1 to -5pp MaxDD. Output file gets `_sector_neutral` prefix. |
| `--guardrails` | off | Apply risk guardrails + 25% sector cap; produces `gr_*` portfolios |
| `--vol-weight` | off | Inverse-vol position sizing (12m rolling); produces `vw_gr_*` portfolios |
| `--regime-filter` | off | SPY 12m regime filter (50% exposure when >25% or <-20%); produces `rf_gr_*` |
| `--model` | off | Also backtest saved XGBoost model (requires `data/model.joblib`) |
| `--tc-bps` | 10 | One-way transaction cost in basis points |
| `--score-buffer` | 0.10 | IQR hysteresis buffer for existing holdings |
| `--max-sector-pct` | 0.25 | Maximum sector weight fraction |
| `--save-returns` | off | Save monthly return series CSV alongside results |

Required: `HF_DB_PATH`, `AV_DB_PATH`, `PRICES_DB_PATH`.

**Recommended portfolio variants (sector-neutral, 404 months 1983–2026, 25 stocks):**

| Portfolio | CAGR | Sharpe | MaxDD | Notes |
|---|---|---|---|---|
| `gr_top_n_25` | 17.0% | 0.96 | -39.7% | Equal-weight |
| `vw_gr_top_n_25` | 16.7% | 1.00 | -35.4% | Recommended default |
| `rf_gr_top_n_25` | 15.6% | 1.02 | -25.7% | Capital-preservation, regime filter |

Run with: `uv run scripts/run_backtest.py --sector-neutral --guardrails --vol-weight --regime-filter`

---

## score_live.py

Live scoring pipeline. Produces a ranked, investable portfolio with position sizes and regime signal. Writes `docs/live_scores_YYYYMMDD.csv`.

```bash
uv run scripts/score_live.py
uv run scripts/score_live.py --top 25
uv run scripts/score_live.py --top 50 --verbose
uv run scripts/score_live.py --output /tmp/scores.csv
uv run scripts/score_live.py --model /path/to/model.joblib
uv run scripts/score_live.py --no-model     # composite score only
uv run scripts/score_live.py --no-guardrails
```

| Flag | Default | Description |
|------|---------|-------------|
| `--top` | 25 | Number of portfolio positions to display and size |
| `--model` | auto-detect | Path to model.joblib; auto-loads from HF_DB_PATH directory |
| `--no-model` | off | Force composite baseline score only |
| `--guardrails` | on | Apply value-trap and quality guardrails |
| `--no-guardrails` | off | Disable guardrails |
| `--max-sector-pct` | 0.25 | Maximum sector weight in portfolio |
| `--max-missing` | 2 | Max allowed missing factors per stock |
| `--output` | auto | Override output CSV path |

**What it outputs:**

- Regime banner: SPY 12-month trailing return and current exposure level (FULL = 100%, REDUCED = 50%).
- Portfolio table with `weight_pct` (inverse-vol position weight) and `alloc_pct` (regime-adjusted allocation).
- CSV with all ranked universe stocks; `weight_pct`/`alloc_pct` populated only for top-N portfolio.

**Scoring:** Composite baseline uses sector-neutral z-scores by default — each factor is z-scored within `(month_end_date, sector)` so stocks are compared only against sector peers. Sectors with <3 stocks fall back to market-wide z-score. Validated improvement: +0.3pp CAGR, +0.004 Sharpe, -1pp MaxDD on `rf_gr_top_n_25` (404 months).

Required: `HF_DB_PATH`, `AV_DB_PATH`. `PRICES_DB_PATH` optional but required for vol-weighted sizing and regime signal.

---

## run_risk.py

Risk diagnostics: sector exposure, position concentration, value-trap flags, drawdown statistics, rolling beta. Writes `docs/risk_report.md`.

```bash
uv run scripts/run_risk.py
uv run scripts/run_risk.py --tc-bps 20 --verbose
```

Required: `HF_DB_PATH`, `AV_DB_PATH`, `PRICES_DB_PATH`.

---

## rebalance.py

CLI rebalancer for Interactive Brokers. Connects to TWS, fetches live prices, computes target shares from `alloc_pct × NAV / price` (whole shares), diffs against current holdings, and submits MOC orders. Dry-run by default — no orders submitted unless `--no-dry-run` is given.

Scores are loaded from the latest `docs/live_scores_*.csv` (written by `score_live.py`) unless `--scores` is given. Only rows with a non-empty `alloc_pct` are treated as portfolio positions. Positions in the current account but absent from the scores CSV are auto-exited.

```bash
uv run scripts/rebalance.py                           # dry run, latest scores CSV
uv run scripts/rebalance.py --scores PATH             # dry run, explicit CSV
uv run scripts/rebalance.py --no-dry-run              # submit orders
uv run scripts/rebalance.py --status                  # print NAV + positions + open orders and exit
uv run scripts/rebalance.py --cancel-all              # cancel all open orders and exit
```

| Flag | Default | Description |
|------|---------|-------------|
| `--scores PATH` | latest `docs/live_scores_*.csv` | Explicit scores CSV path |
| `--dry-run` / `--no-dry-run` | dry-run on | Preview only / submit orders |
| `--order-type` | `MOC` | `MOC`, `MKT`, or `LMT` |
| `--strategy` | `fundamentals_alpha` | IB `orderRef` tag for order tracking |
| `--status` | off | Print account status and exit |
| `--cancel-all` | off | Cancel all open orders and exit |
| `--verbose` | off | DEBUG-level logging |

Required: `IB_HOST`, `IB_PORT`, `IB_CLIENT_ID`. `IB_ACCOUNT` auto-detected if not set.

---

## ib_repl.py

Interactive REPL for ad-hoc IB orders and account inspection. Connects to TWS on startup and disconnects on exit.

```bash
uv run scripts/ib_repl.py
```

Available commands:

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

Required: `IB_HOST`, `IB_PORT`, `IB_CLIENT_ID`.
