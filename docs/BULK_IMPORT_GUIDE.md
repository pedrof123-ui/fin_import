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
  tickers.csv       CSV file with ticker list

options:
  --periods N       Filings per ticker (default: 20)
  --quarterly       Import 10-Q instead of 10-K
  --db PATH         Database path (default: data/financial_statements.duckdb)
  --ai              AI fallback for unmapped XBRL concepts (slower)
  --no-skip         Re-import filings already in DB (default: skip existing)
  --delay SECS      Seconds between SEC requests (default: 1.0)
  --output DIR      Reports directory (default: ./bulk_import_results)
  --log FILE        Log file (default: bulk_import.log)
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

| Tickers | Periods | AI | Approx time |
|---------|---------|----|-------------|
| 10 | 10 | No | 5-10 min |
| 10 | 20 | No | 10-20 min |
| 50 | 10 | No | 25-50 min |
| 10 | 20 | Yes | 20-40 min |

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
    rate_limit_delay=1.0,
))
```

`results` dict keys: `total_tickers_processed`, `total_filings_found`, `total_filings_processed`, `total_filings_skipped`, `total_filings_failed`, `total_statements_success`, `total_statements_failed`.
