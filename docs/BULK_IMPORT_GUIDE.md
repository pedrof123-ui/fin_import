# Bulk Import Guide

Downloads annual (10-K) or quarterly (10-Q) SEC filings for a list of tickers and stores all three statements in DuckDB.

## Quick start

```bash
# Annual, last 20 filings (default)
uv run run_bulk_import.py tickers.csv

# Quarterly, last 8 quarters
uv run run_bulk_import.py tickers.csv --quarterly --periods 8

# Annual, 10 years, AI fallback
uv run run_bulk_import.py tickers.csv --periods 10 --ai

# 5 tickers processed in parallel
uv run run_bulk_import.py tickers.csv --concurrency 5
```

The script prompts for confirmation before starting, then prints progress and writes reports to `./bulk_import_results/`.

## Ticker CSV format

Any of these column names work: `ticker`, `symbol`, `stock`. First column used if none found.

```csv
ticker
AAPL
MSFT
GOOGL
```

## All options

```
uv run run_bulk_import.py tickers.csv [options]

positional:
  tickers.csv         CSV file with ticker list

options:
  --periods N         Filings per ticker (default: 20)
  --quarterly         Import 10-Q instead of 10-K
  --db PATH           Database path (default: data/financial_statements.duckdb)
  --ai                AI fallback for unmapped XBRL concepts (slower)
  --no-skip           Re-import filings already in DB (default: skip existing)
  --delay SECS        Extra seconds between SEC requests (default: 0)
                      edgartools has a built-in rate limiter; only set this if
                      you're hitting 429s from the SEC.
  --concurrency N     Tickers to process in parallel (default: 3)
  --output DIR        Reports directory (default: ./bulk_import_results)
  --log FILE          Log file (default: bulk_import.log)
```

## Output reports

Written to `--output` directory after each run:

| File | Contents |
|------|----------|
| `summary_report.csv` | One row per ticker with filing counts |
| `detailed_log.csv` | Every log entry |
| `failures.csv` | Error entries only |
| `overall_statistics.txt` | Aggregate stats and success rate |

## Time estimates

The pipeline processes tickers concurrently (default: 3 at a time). edgartools' built-in
rate limiter handles SEC's 9 req/s cap, so per-request throttling is automatic.

| Tickers | Periods | Concurrency | AI | Approx time |
|---------|---------|-------------|----|-------------|
| 10 | 10 | 3 | No | 2-4 min |
| 10 | 20 | 3 | No | 4-8 min |
| 50 | 10 | 3 | No | 10-20 min |
| 10 | 20 | 3 | Yes | 8-16 min |

## Using the Python API directly

```python
import asyncio
from bulk_import_10k import bulk_import_10k

results = asyncio.run(bulk_import_10k(
    ticker_csv='tickers.csv',
    periods=20,
    form='10-K',           # or '10-Q'
    db_path='data/financial_statements.duckdb',
    use_ai_fallback=False,
    skip_existing=True,
    rate_limit_delay=0.0,  # edgartools handles rate limiting internally
    concurrency=3,
))
```

`results` dict keys: `total_tickers_processed`, `total_filings_found`, `total_filings_processed`, `total_filings_skipped`, `total_filings_failed`, `total_statements_success`, `total_statements_failed`.
