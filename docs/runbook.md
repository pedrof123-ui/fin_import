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

**External databases:**

- `data/av_financials.duckdb` — Alpha Vantage financial statements (income, balance, cashflow, shares, dividends, company overview)
- `data/historic_fundamentals.duckdb` — computed monthly feature table (`monthly_pe`), PE stats, sector stats, earnings estimates
- prices DB at `PRICES_DB_PATH` — daily adjusted close prices and SPY daily returns

---

## Data Pipeline

Run the following in order when setting up or refreshing data.

### Step 1 — Import financial statements

```
uv run scripts/av_import.py
```

Fetches income, balance sheet, and cash flow statements from Alpha Vantage for each ticker in the universe. Writes to `av_financials.duckdb`.

**API rate limit:** 75 calls/minute. The importer enforces this limit internally. Do not run multiple import processes in parallel.

### Step 2 — Import company overview

```
uv run scripts/av_import_overview.py
```

Fetches sector, industry, company name, beta, and 41 other OVERVIEW fields per ticker. Required for sector filters and live scoring. Writes to `company_overview` table in `av_financials.duckdb`.

### Step 3 — Incremental update for existing tickers

```
uv run scripts/av_update.py
```

Refreshes statements and overview for tickers already in the database. Use monthly to keep the feature store current.

### Step 4 — Feature computation

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
uv run scripts/run_backtest.py --help
```

Runs a non-overlapping monthly portfolio simulation for four portfolio configurations (top 20%, top 10%, top 50 names, top 25 names), all equal-weight. Computes CAGR, annualized volatility, Sharpe, max drawdown, beta to SPY, information ratio, tracking error, turnover, and transaction cost drag. Writes `docs/backtest_results.md`.

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
3. Applies universe filters: market cap >= $1B, price >= $5, sector must be known.
4. Computes composite baseline score (cross-sectional z-score of six valuation and quality factors).
5. Attempts to load a saved XGBoost model from `model.joblib` next to `HF_DB_PATH`. Falls back to composite baseline score if the file is not found.
6. Ranks tickers by score (1 = highest-scoring).
7. Attaches value-trap flags and missing-data counts per row.

**Output columns:** `rank`, `percentile`, `ticker`, `company_name`, `score`, `sector`, `market_cap`, `price`, `liquidity` (NaN placeholder — see Known Limitations), `pe_ratio`, `fcf_yield`, `earnings_yield`, `ttm_gross_margin`, `ttm_operating_margin`, `debt_to_ebitda`, `roa`, `top_factor`, `value_trap`, `missing_factor_count`, `data_quality`, `feature_available_date`.

Required environment variables: `HF_DB_PATH`, `AV_DB_PATH`.

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

Cross-sectional z-score of six factors within each month:

| Factor | Direction |
|---|---|
| `ps_ratio` | Lower is better |
| `fcf_yield` | Higher is better |
| `ev_ebitda` | Lower is better |
| `earnings_yield` | Higher is better |
| `roic` | Higher is better |
| `roa` | Higher is better |

Factors with the "lower is better" convention are sign-flipped before z-scoring so that a higher composite score always means a better-ranked stock.

**Transaction costs**

Default: 10 basis points one-way per trade. Configurable via `--tc-bps` on the validation scripts. The live scoring script does not apply transaction costs (it ranks, not simulates).

**Rebalancing**

Monthly, equal-weight. No leverage.

---

## Known Limitations

**No filing-date data.** Alpha Vantage does not provide SEC EDGAR `accepted_date`. The conservative fiscal-period-end lag (quarterly +60d, annual +90d) is used as a proxy. This can understate freshness for companies that file early, and may fail to catch late filers. True point-in-time safety would require SEC EDGAR accepted dates.

**No ADV liquidity filter.** The `liquidity` column in live scoring output is always NaN. Alpha Vantage free-tier data does not include daily volume. Illiquid stocks in the $1B+ market-cap universe are not filtered out. A volume-based filter should be added before any live use.

**Sector classification is point-in-time unsafe.** The `company_overview` table stores the most recent sector snapshot per ticker. Historical sector changes are not tracked. Backtest sector exposure is therefore an approximation.

**XGBoost model not auto-saved.** The walk-forward validation script does not persist a model artifact. Live scoring falls back to the composite baseline score unless a `model.joblib` file is manually placed in the same directory as `HF_DB_PATH`.

**`roa_stability_5y` naming is inverted.** This feature is `std(ROA over 5 years)`. A higher value means more volatile ROA — which is worse. The name implies stability but the value is volatility. Use with care in model interpretation.

**Overlapping forward returns are training labels only.** Monthly rows computed at time t with 12-month forward returns naturally overlap across consecutive months. These overlapping returns are used only as training labels for the XGBoost model. They are not compounded into a portfolio equity curve. The backtest uses true non-overlapping monthly holding-period returns.

**In-sample metrics are not final evidence.** Walk-forward results display both in-sample and out-of-sample metrics. Only OOS metrics should be used when assessing model quality.

**Sector concentration is not constrained in the backtest.** The portfolio backtest does not enforce a sector-weight cap. High sector concentration may appear in some periods. Review `docs/risk_report.md` before using the model.

**This model is a research tool until all go/no-go criteria pass.** See the Go/No-Go Criteria section below.

---

## Go/No-Go Criteria

The model should be treated as a research tool until all criteria below are verified. Do not use it to place live trades if any item is unchecked.

- [ ] Walk-forward OOS rank IC > 0.03 (positive predictive power in held-out periods)
- [ ] Walk-forward hit rate > 50%
- [ ] Backtest Sharpe ratio (net of transaction costs) > 0.5
- [ ] No single sector > 40% of live portfolio in the current month
- [ ] No more than 20% of live output flagged as `value_trap = True`
- [ ] All 168 unit tests pass (`uv run pytest tests/ --ignore=tests/test_api.py`)
- [ ] `feature_available_date` <= today for all rows in live scoring output
- [ ] Investable universe contains >= 50 stocks in the current month
- [ ] Live scoring output has been reviewed for obvious data anomalies before acting

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
