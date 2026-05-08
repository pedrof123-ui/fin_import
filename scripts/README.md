# scripts/

CLI scripts for the Alpha Vantage financial statements pipeline.

All scripts read configuration from `.env` in the project root and must be run with `uv run`.

## Required .env variables

```
ALPHA_VANTAGE_API_KEY=<premium key>
PRICES_DB_PATH=/path/to/trade_systems/data/prices.duckdb
AV_DB_PATH=data/av_financials.duckdb   # optional; this is the default
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
