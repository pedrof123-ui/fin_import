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

## av_import.py

Downloads income statements, balance sheets, and cash flow statements from Alpha Vantage and stores them in `data/av_financials.duckdb`.

### Source (pick one)

```bash
uv run scripts/av_import.py AAPL [MSFT ...]     # one or more tickers
uv run scripts/av_import.py --csv FILE          # first column of a CSV file
uv run scripts/av_import.py --from-prices-db    # all tickers from prices.duckdb
```

### Options (work with any source)

| Flag | Description |
|------|-------------|
| `--force` | Re-fetch and overwrite tickers already in the DB. Without this, existing tickers are skipped. |
| `--db PATH` | Use a different DuckDB file instead of `data/av_financials.duckdb`. |
| `--verbose` | Enable DEBUG-level logging (individual API call details). |

### Examples

```bash
uv run scripts/av_import.py AAPL MSFT GOOGL
uv run scripts/av_import.py --csv data/test_tickers.csv --force
uv run scripts/av_import.py --from-prices-db
uv run scripts/av_import.py --from-prices-db --force
uv run scripts/av_import.py AAPL --force --db data/custom.duckdb
```

Each ticker costs 3 API calls. The rate limiter enforces ~0.8s between calls (75/min premium limit), giving ~25 tickers/minute sustained throughput.

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

Refreshes all tickers already in `av_financials.duckdb` with the latest data from Alpha Vantage. Intended to run on a cron schedule (e.g., weekly after earnings season).

```bash
uv run scripts/av_update.py                    # update all tickers in DB
uv run scripts/av_update.py --ticker AAPL      # update one specific ticker
uv run scripts/av_update.py --db data/custom.duckdb
```

All updates use `INSERT OR REPLACE`, so existing rows are overwritten with the latest data. The full history is re-fetched on each run (Alpha Vantage returns all periods in a single call).

---

## update_alpha_vantage_estimates.py

Downloads analyst EPS and revenue estimates for a single ticker and stores them in `data/financial_statements.duckdb` (the SEC EDGAR database).

```bash
uv run scripts/update_alpha_vantage_estimates.py AAPL
uv run scripts/update_alpha_vantage_estimates.py          # prompts for ticker
```

---

## hf_import.py

Bulk backfill for `data/historic_fundamentals.duckdb`. For each ticker: computes full monthly PE history from `av_financials.duckdb` (no AV calls), then fetches `EARNINGS_ESTIMATES` from Alpha Vantage (1 call/ticker) to populate analyst estimates and forward PE.

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
| `--skip-estimates` | Skip the Alpha Vantage EARNINGS_ESTIMATES fetch. PE history and stats are still computed. |
| `--db PATH` | Use a different DuckDB file instead of `data/historic_fundamentals.duckdb`. |
| `--verbose` | Enable DEBUG-level logging. |

### Examples

```bash
uv run scripts/hf_import.py                                 # full initial backfill
uv run scripts/hf_import.py AAPL MSFT --force              # force-refresh two tickers
uv run scripts/hf_import.py --csv data/sp500.csv --skip-estimates  # PE only
uv run scripts/hf_import.py AAPL --db data/custom_hf.duckdb
```

PE phase is local (no AV calls); throughput is memory-bound, typically < 5 min for all tickers. Estimates phase: 1 AV call/ticker at 75/min = ~20 min for 1,465 tickers.

---

## hf_update.py

Monthly refresh for `data/historic_fundamentals.duckdb`. Reads the list of tickers already in `pe_stats`, recomputes their full monthly PE timeseries from updated `av_financials.duckdb` data, and refreshes analyst estimates from Alpha Vantage. Intended to run at the start of each month after new financial data is available.

```bash
uv run scripts/hf_update.py                     # update all tickers already in the DB
uv run scripts/hf_update.py --ticker AAPL       # update a single ticker
uv run scripts/hf_update.py --skip-estimates    # PE refresh only, no AV calls
uv run scripts/hf_update.py --db PATH           # override DB path
```

---

## hf_query.py

Query `data/historic_fundamentals.duckdb` and print results to stdout or a CSV file.

### Views

| View | Description |
|------|-------------|
| `stats` (default) | PE statistics snapshot: current PE, long-term median, percentiles, rolling 5yr median, forward PE |
| `timeseries` | Monthly PE history with optional date filter |
| `estimates` | Latest analyst EPS and revenue estimates per (ticker, fiscal_date, horizon) |

### Usage

```bash
uv run scripts/hf_query.py AAPL                                 # PE stats for one ticker
uv run scripts/hf_query.py AAPL MSFT                           # PE stats for multiple tickers
uv run scripts/hf_query.py --all                                # PE stats for all tickers
uv run scripts/hf_query.py AAPL --view timeseries              # monthly PE history
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
