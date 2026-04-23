# run_bulk_import.py — Quick Reference

CLI entry point for bulk SEC EDGAR imports.

## Basic usage

```bash
# Annual, last 20 filings
uv run run_bulk_import.py tickers.csv

# Quarterly, last 8 quarters
uv run run_bulk_import.py tickers.csv --quarterly --periods 8

# Annual, 10 years, AI fallback
uv run run_bulk_import.py tickers.csv --periods 10 --ai

# Force re-import everything
uv run run_bulk_import.py tickers.csv --no-skip
```

## All flags

```
--periods N       Filings per ticker (default: 20)
--quarterly       Import 10-Q instead of 10-K
--db PATH         Database path (default: data/financial_statements.duckdb)
--ai              AI fallback for unmapped XBRL concepts
--no-skip         Re-import existing filings
--delay SECS      Delay between SEC requests (default: 1.0)
--output DIR      Reports directory (default: ./bulk_import_results)
--log FILE        Log file (default: bulk_import.log)
```

## Example session

```
$ uv run run_bulk_import.py tickers.csv --periods 5 --quarterly

================================================================================
BULK IMPORT CONFIGURATION
================================================================================
Ticker CSV:       tickers.csv
Form:             10-Q
Periods:          5
Database:         data/financial_statements.duckdb
AI Fallback:      Disabled
Skip Existing:    Yes
Rate Limit:       1.0s
Output Dir:       ./bulk_import_results
Log File:         bulk_import.log
================================================================================

Proceed with import? [y/N]: y
```

## Output files

```
bulk_import_results/
  summary_report.csv       Per-ticker filing counts
  detailed_log.csv         Full log
  failures.csv             Errors only
  overall_statistics.txt   Summary stats
bulk_import.log            Raw log file
```
