# Import Pipeline

## Overview

The pipeline fetches SEC EDGAR filings for a list of companies, parses XBRL data, maps concepts to standardized financial line items, and stores results in DuckDB.

Two entry points share the same extraction core:

- **CLI** (`run_bulk_import.py`) — bulk import from a ticker CSV, async fan-out
- **HTTP API** (`api/importer.py`) — single-ticker import via `POST /import`

---

## Entry Points

### CLI: `run_bulk_import.py`

```
uv run run_bulk_import.py tickers.csv [options]

Options:
  --periods N       Filings per ticker (default: 20)
  --quarterly       Use 10-Q form instead of 10-K
  --ai              Enable AI fallback for unmapped concepts
  --no-skip         Re-import filings already in DB
  --concurrency N   Parallel tickers (default: 3)
  --db PATH         DuckDB path (default: data/financial_statements.duckdb)
  --output DIR      Reports directory (default: ./bulk_import_results)
  --log FILE        Log file (default: bulk_import.log)
```

Prompts for confirmation, then calls `asyncio.run(bulk_import_10k(...))`. On completion writes four report files to `--output`: `summary_report.csv`, `detailed_log.csv`, `failures.csv`, `overall_statistics.txt`.

### HTTP API: `api/importer.py`

```
POST /import  {"ticker": "AAPL", "periods": 5, "period_type": "FY"}
```

`period_type` is `"FY"` (annual, 10-K) or `"Q"` (quarterly, 10-Q). The API always enables AI fallback (`use_ai_fallback=True`). Returns a JSON summary with counts and up to 10 error messages.

---

## Call Graph

### CLI path

```
run_bulk_import.main()
  asyncio.run(bulk_import_10k(...))              bulk_import_10k.py:350
    read_ticker_csv(csv_path)                    bulk_import_10k.py:99
    FinancialStatementsDB(db_path)               financial_statements_db.py
    asyncio.Semaphore(concurrency)
    asyncio.gather([bounded_process(i, ticker)])
      process_ticker(ticker, ...)                bulk_import_10k.py:245
        Company(ticker)                          [edgartools]
        company.get_filings(form)[:periods]
        db.filing_exists(ticker, period_end)     → skip if True
        extract_and_insert_filing(filing, ...)   bulk_import_10k.py:132
          extract_income_statement(...)
          extract_balance_sheet(...)
          extract_cash_flow(...)
            each calls extract_statement(...)    extractors/statement_extractor.py:97
          db.insert_income_statement/balance_sheet/cash_flow(df)
        clear_company_facts_cache()              [edgartools memory management]
```

### API path

```
POST /import
  import_ticker(ticker, periods, period_type, db)   api/importer.py:17
    asyncio.to_thread(Company(ticker))
    asyncio.to_thread(company.latest(form))           periods == 1
    OR asyncio.to_thread(company.get_filings(form))   periods > 1
    db.filing_exists(ticker, period_end) → skip if not force
    _extract_and_insert(filing, ...)              api/importer.py:73
      extract_income_statement(...)
      extract_balance_sheet(...)
      extract_cash_flow(...)
```

---

## Extraction Core

All three statement extractors (`extractors/income_statement_extractor.py`, `balance_sheet_extractor.py`, `cash_flow_extractor.py`) are thin wrappers around the shared `extract_statement()` in `extractors/statement_extractor.py`. They differ only in: which mapping dict to use, which edgartools method to call, alternative statement names to try, and which fields use aggregation vs. max resolution.

### `extract_statement()` — step by step

1. Resolve `filing_date`, `period_of_report`, `form_type` from filing attributes. Derive `year` and `quarter` if not supplied.
2. `filing.xbrl()` → XBRL object. Raises `ValueError` if None.
3. `get_stmt_fn(xbrl)` → statement object. Falls back through `alt_names` list if the primary method returns None.
4. `stmt.to_dataframe(presentation=False)` → flat DataFrame with columns `concept`, `dimension`, `abstract`, and date-labeled value columns (e.g. `"2024-09-28 (FY)"`).
5. Detect date columns by matching `YYYY-MM-DD` prefix. Sort descending, pick `most_recent_period`.
6. **Mapping enrichment** (free): `XBRLMappingManager.get_enriched_mapping()` appends AI-discovered concepts (confidence >= 0.8) from `xbrl_mappings_multi.duckdb` to the static mapping in memory.
7. **Pass 1 — static lookup**: `_extract_value()` for each field. Filters to `dimension==False, abstract==False`. Strips namespace prefix (`us-gaap_Revenues` → `Revenues`). Three resolution strategies:
   - **default**: first matching concept wins
   - **aggregation_fields** (e.g. `selling_general_admin`, `interest_expense`): sum all matching values — some companies report components separately
   - **max_fields** (e.g. `revenue`, `net_income`): take the maximum — a subtotal cannot exceed the true total (e.g. WMT `Revenues` > `RevenueFromContractWithCustomerExcludingAssessedTax`)
8. Collect `unfound_fields` — fields with no value after Pass 1.
9. **Pass 2 — AI fallback** (only if `use_ai_fallback=True` and `unfound_fields` is non-empty):
   - Phase A: `XBRLMappingManager.get_prior_discoveries()` — free DB lookup, returns most-frequent concept→field pairs from `ai_discovery_queue`
   - Phase B: `batch_classify_concepts()` — sends remaining unmapped concepts to Claude Haiku in chunks of 20; side effect: calls `write_concept_to_mapping()` to append the discovery to the static `.py` file
10. Build result DataFrame with metadata columns (`Ticker`, `Fiscal_Year`, `Period_End_Date`, `Filing_Date`, `Filing_Type`, `Period_Type`, `Quarter`, `Status`, `Field`, `Value`, `Concept`).
11. Log AI discoveries to `ai_discovery_queue` in `xbrl_mappings_multi.duckdb`.
12. Warn if `found / total < 50%`.

---

## XBRL Mapping Layer

### Static mappings (`xbrl_mappings/`)

Three Python dicts, one per statement type. Each field maps to an ordered list of XBRL concept strings (without namespace prefix). Order is frequency-based — most common concept across the 460+ companies surveyed is first.

| File | Dict | Fields |
|------|------|--------|
| `income_statement_xbrl_mapping.py` | `INCOME_STATEMENT_MAPPING` | ~30 |
| `balance_sheet_xbrl_mapping.py` | `BALANCE_SHEET_MAPPING` | ~48 |
| `cash_flow_xbrl_mapping.py` | `CASH_FLOW_MAPPING` | ~40 |

Company-specific concepts (e.g. `bk_TotalRevenuesIncluding...`, `elv_OperatingRevenue`) are included inline with a comment.

AI-discovered concepts are appended to these files at runtime by `write_concept_to_mapping()`, tagged with `# ticker (AI-discovered)`.

### Dynamic layer (`data/xbrl_mappings_multi.duckdb`)

Managed by `XBRLMappingManager` in `xbrl_mapping_manager_multi_statement.py`. Seven tables:

| Table | Purpose |
|-------|---------|
| `core_concept_mappings` | Snapshot of static `.py` files synced at first init |
| `ai_discovered_mappings` | Per-concept AI discoveries with usage stats and confidence |
| `company_specific_mappings` | Ticker-level overrides (currently populated via API only) |
| `ai_discovery_queue` | Raw per-filing AI match log (ticker, concept, field, value, date) |
| `extraction_log` | Extraction attempt audit trail |
| `concept_metadata` | Concept descriptions and occurrence tracking |
| `statement_coverage_stats` | Per-filing field coverage percentages |

Key methods used at runtime:
- `get_enriched_mapping(statement_type, static_mapping)` — enriches static dict with AI discoveries before Pass 1
- `get_prior_discoveries(statement_type)` — returns `{concept: field}` for Phase A of Pass 2

---

## AI Layer (`xbrl_concept_mapper.py`)

Used only during Pass 2, Phase B.

- Provider: OpenRouter (`https://openrouter.ai/api/v1`) via `openai.AsyncOpenAI`
- Model: `anthropic/claude-haiku-4-5`
- Auth: `OPENROUTER_API_KEY` from `.env` (raises `RuntimeError` if missing)
- Concepts chunked in groups of 20 per API call
- System prompt: full text of the relevant static mapping `.py` file + valid field name list
- User message: plain list of concept names
- Response: JSON `{ConceptName: field_name}` — entries with `"no_match"` or invalid field names are discarded
- Side effect: `write_concept_to_mapping()` appends matched concepts directly to the `.py` mapping file

The self-improving loop:
1. New concept classified by AI → written to `.py` file + logged to `ai_discovery_queue`
2. Next extraction for same statement type: `get_enriched_mapping()` injects it into the in-memory mapping
3. Pass 1 resolves it statically; the `.py` file on disk handles any subsequent run

---

## Storage (`financial_statements_db.py`)

Single DuckDB file at `data/financial_statements.duckdb`. Five tables:

| Table | PK | Rows |
|-------|----|------|
| `companies` | `ticker` | master record |
| `income_statements` | `(ticker, filing_date, period_end_date)` | ~39 financial columns |
| `balance_sheets` | same | ~48 financial columns |
| `cash_flow_statements` | same | ~40 financial columns |
| `extraction_log` | sequence | audit trail (not yet populated by insert methods) |

All three statement insert methods use upsert semantics (`INSERT OR REPLACE`), so re-importing the same filing is safe.

`filing_exists(ticker, period_end)` checks all three statement tables with AND logic — a filing is considered complete only when all three are present. A partial import (e.g. balance sheet failed) will be retried in full on the next run.

---

## Concurrency and Error Handling

### CLI

- `asyncio.Semaphore(concurrency)` gates ticker-level parallelism (default: 3)
- `asyncio.gather(return_exceptions=True)` — a failed ticker does not abort others
- Within a filing: each of the three statements has its own `try/except`, so a balance sheet failure does not prevent cash flow from being stored
- `clear_company_facts_cache()` is called in `finally` to release edgartools memory

### API

- edgartools calls are wrapped in `asyncio.to_thread()` to avoid blocking the event loop
- Same per-statement isolation: `_extract_and_insert` loops with individual `try/except` per statement

### What is not handled

- **No retry logic**: the docstring mentions it but it is not implemented; a transient network error on any filing counts as a failure
- **No rate limiting**: `--delay` / `rate_limit_delay` is accepted and logged but never applied (the parameter is not used inside `process_ticker`)

---

## Known Issues

| # | Location | Issue | Status |
|---|----------|-------|--------|
| 1 | `bulk_import_10k.py` | Docstring claims "Automatic retry logic" — no retry is implemented | open |
| 2 | `xbrl_mapping_manager_multi_statement.py` | Multiple concurrent connections to `xbrl_mappings_multi.duckdb` under `--concurrency > 1`; DuckDB 1.4+ serializes writes but errors are possible under very high load | open |

## Fixed Issues

| # | Location | Fix |
|---|----------|-----|
| 1 | `bulk_import_10k.py` | `rate_limit_delay` now applied via `asyncio.sleep()` between filings |
| 2 | `xbrl_concept_mapper.py` | `write_concept_to_mapping()` removed from the runtime hot path; DB is the sole persistence layer for new discoveries |
| 3 | `extractors/statement_extractor.py` | `filing.xbrl()` wrapped in `asyncio.to_thread()` — blocking SEC call no longer holds the event loop |
| 4 | `bulk_import_10k.py` | `Company()` and `get_filings()` wrapped in `asyncio.to_thread()` — true async parallelism under `--concurrency` |
| 5 | `xbrl_mapping_manager_multi_statement.py` | `get_enriched_mapping()` now reads `ai_discovery_queue` with `HAVING COUNT(*) >= 2` — enrichment loop is live |
| 6 | `financial_statements_db.py` | `log_extraction()` method added; called from both CLI and API paths after each filing |
| 7 | `xbrl_concept_mapper.py` | Clear `RuntimeError` raised when `OPENROUTER_API_KEY` is missing |
| 8 | `run_bulk_import.py` | `--ai` (opt-in) replaced with `--no-ai` (opt-out); AI fallback is now the default |
| 9 | `xbrl_mapping_manager_multi_statement.py` | `missed_concepts` table added; every unresolved field and every AI no_match/api_failure concept is logged with reason and filing context |
| 10 | `extractors/statement_extractor.py` | Single `XBRLMappingManager` instance per extraction (was two); handles enrichment, pass 2, AI discovery logging, and miss logging |
| 11 | `dcf/wacc.py` | Cost of debt now uses **annual** income statement for interest expense — quarterly IE divided by total debt gave a quarterly rate (~1/4 of the true annual rate), systematically understating kd |
| 12 | `dcf/wacc.py` | Diluted shares: three-level fallback (quarterly → annual income statement → derived from `net_income / diluted_eps`). Previously `market_cap = 0` when shares were absent, making D_w = 100% and WACC = kd × (1 − tax) only |
| 13 | `dcf/model.py` | `diluted_shares` for the equity bridge now consistent with `wacc_detail.market_cap` — previously used a separate lookup that fell back to 1, inflating intrinsic value by ~300M× |
| 14 | `dcf/model.py` | `DcfResult.warnings` added; surfaces data quality issues (zero market cap, high D_w, low WACC, terminal growth clamped). Displayed as amber banners in `DcfViewer.tsx` |
| 15 | `dcf/model.py` | Historical EBIT fallback: when `operating_income` is null (common with pharma/healthcare XBRL filers), EBIT is derived as `gross_profit − SG&A − R&D` so historical EBIT/EBITDA rows populate instead of showing "—" |

---

## File Map

```
run_bulk_import.py                   CLI entry point
bulk_import_10k.py                   Bulk import engine (process_ticker, extract_and_insert_filing)
api/
  main.py                            FastAPI app and routes
  importer.py                        Single-ticker import logic
extractors/
  statement_extractor.py             Shared extraction core (extract_statement, _extract_value)
  ai_batch_helper.py                 Pass 2 orchestration (DB lookup + batch AI)
  income_statement_extractor.py      Wrapper for income statement
  balance_sheet_extractor.py         Wrapper for balance sheet
  cash_flow_extractor.py             Wrapper for cash flow
xbrl_concept_mapper.py               Claude Haiku client + write_concept_to_mapping
xbrl_mappings/
  __init__.py                        Exports all three mapping dicts
  income_statement_xbrl_mapping.py   INCOME_STATEMENT_MAPPING (~30 fields)
  balance_sheet_xbrl_mapping.py      BALANCE_SHEET_MAPPING (~48 fields)
  cash_flow_xbrl_mapping.py          CASH_FLOW_MAPPING (~40 fields)
xbrl_mapping_manager_multi_statement.py  XBRLMappingManager (dynamic DB layer)
financial_statements_db.py           FinancialStatementsDB (output storage)
data/
  financial_statements.duckdb        Primary output database
  xbrl_mappings_multi.duckdb         AI discovery and analytics database
```
