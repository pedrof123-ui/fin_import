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

## add_tickers.py

All-in-one script for onboarding new tickers. For each ticker it runs in sequence:

1. Fetches income / balance / cashflow statements → `av_financials.duckdb`
2. Fetches shares outstanding → `av_financials.duckdb`
3. Fetches dividend history → `av_financials.duckdb`
4. Computes monthly PE + dividend yield timeseries → `historic_fundamentals.duckdb`
5. Fetches analyst earnings estimates → `historic_fundamentals.duckdb`
6. Computes forward PE → `pe_stats`

This is the recommended way to add new tickers. Running `av_import.py` + `hf_import.py` separately is equivalent but requires two commands.

### Usage

```bash
uv run scripts/add_tickers.py AAPL MSFT GOOGL
uv run scripts/add_tickers.py --csv data/new_tickers.csv
uv run scripts/add_tickers.py AAPL --force           # re-import even if already in DB
uv run scripts/add_tickers.py AAPL --skip-estimates  # skip EARNINGS_ESTIMATES call
```

### Options

| Flag | Description |
|------|-------------|
| `--force` | Re-import tickers already in av_financials and recompute all derived metrics. |
| `--skip-estimates` | Skip the Alpha Vantage EARNINGS_ESTIMATES call. PE + dividend yield still computed. |
| `--verbose` | Enable DEBUG-level logging. |

Rate: 6 AV calls/ticker (3 statements + shares + dividends + estimates). At 75/min: ~12 tickers/min.

---

## av_import.py

Downloads income statements, balance sheets, cash flow statements, shares outstanding, and
dividend history from Alpha Vantage and stores them in `data/av_financials.duckdb`.

Use `add_tickers.py` when you also want historic fundamentals computed. Use `av_import.py`
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

Use `add_tickers.py` when adding new tickers from scratch — it runs both AV import and hf_import
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
`av_financials.duckdb` data, and refreshes analyst estimates from Alpha Vantage. Intended to
run at the start of each month after `av_update.py` has refreshed the raw data.

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
