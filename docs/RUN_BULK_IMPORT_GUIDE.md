# run_bulk_import.py — Quick Reference

CLI entry point for bulk SEC EDGAR imports.

## Basic usage

```bash
# Annual, last 20 filings (AI on by default)
uv run run_bulk_import.py tickers.csv

# Quarterly, last 8 quarters
uv run run_bulk_import.py tickers.csv --quarterly --periods 8

# Disable AI fallback (faster, lower coverage)
uv run run_bulk_import.py tickers.csv --no-ai

# Force re-import everything
uv run run_bulk_import.py tickers.csv --no-skip
```

## All flags

```
--periods N       Filings per ticker (default: 20)
--quarterly       Import 10-Q instead of 10-K
--db PATH         Database path (default: data/financial_statements.duckdb)
--no-ai           Disable AI fallback for unmapped XBRL concepts
--no-skip         Re-import existing filings
--delay SECS      Extra delay between filings per ticker (default: 0)
--concurrency N   Tickers to process in parallel (default: 3)
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
AI Fallback:      Enabled
Skip Existing:    Yes
Rate Limit:       0.0s extra
Concurrency:      3 tickers in parallel
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

Every processed filing also writes one row to `extraction_log` in
`data/financial_statements.duckdb`. Unresolved XBRL concepts are logged to
`missed_concepts` in `data/xbrl_mappings_multi.duckdb`.
