# fin_import2

Downloads SEC EDGAR financial statements (10-K annual, 10-Q quarterly) into DuckDB. Includes a web app for single-ticker imports and a CLI tool for bulk imports.

## Architecture

- **FastAPI backend** (`api/`) — REST API for importing and querying statements
- **Next.js frontend** (`web/`) — UI to import a ticker, view all 3 statements, switch FY/Q
- **DuckDB** (`data/financial_statements.duckdb`) — stores income, balance sheet, and cash flow tables
- **Bulk import CLI** (`run_bulk_import.py`) — batch-imports many tickers from a CSV

## Quick Start

### Web app

```bash
# Terminal 1 — backend (port 8000)
uv run uvicorn api.main:app --reload

# Terminal 2 — frontend (port 3000)
cd web && npm run dev
```

Open http://localhost:3000, enter a ticker, choose Annual or Quarterly, set periods, click Import.

### Bulk import (CLI)

```bash
# Annual (default), last 20 filings
uv run run_bulk_import.py tickers.csv

# Quarterly, last 8 quarters
uv run run_bulk_import.py tickers.csv --quarterly --periods 8

# Annual, 10 years, AI fallback for better XBRL coverage
uv run run_bulk_import.py tickers.csv --periods 10 --ai
```

CSV format — any of these column names work: `ticker`, `symbol`, `stock`. First column used if none found.

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tickers` | List all tickers in DB |
| `POST` | `/import` | Import a ticker from SEC EDGAR |
| `GET` | `/statements/{ticker}/{type}` | Query statements (type: `income`, `balance`, `cashflow`) |

Import request body:
```json
{"ticker": "AAPL", "periods": 5, "period_type": "FY"}
```
`period_type` is `"FY"` (annual 10-K) or `"Q"` (quarterly 10-Q).

Statement query params: `?period_type=FY&periods=10`

## Tests

```bash
# Fast tests (no network)
uv run pytest tests/test_api.py -m "not integration"

# Integration tests (hit SEC EDGAR, ~10-30s each)
uv run pytest tests/test_api.py -m integration
```

## Bulk import options

```
uv run run_bulk_import.py tickers.csv [options]

--periods N       Filings per ticker (default: 20)
--quarterly       Import 10-Q instead of 10-K
--db PATH         Database path (default: data/financial_statements.duckdb)
--ai              AI fallback for unmapped XBRL concepts
--no-skip         Re-import existing filings
--delay SECS      Seconds between SEC requests (default: 1.0)
--output DIR      Reports directory (default: ./bulk_import_results)
--log FILE        Log file (default: bulk_import.log)
```

## Project layout

```
api/
  main.py              FastAPI app, routes
  importer.py          Import logic (fetch SEC filings, extract, insert)
  db.py                DuckDB connection wrapper
web/                   Next.js frontend
extractors/            XBRL extractors for each statement type
xbrl_mappings/         Static XBRL concept → field mappings
xbrl_concept_mapper.py AI-assisted fallback mapper (openai-agents)
financial_statements_db.py  DuckDB schema + insert helpers
bulk_import_10k.py     Core bulk import logic
run_bulk_import.py     CLI entry point for bulk imports
tests/                 pytest tests
data/                  DuckDB database files
```
