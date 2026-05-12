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
| 16 | `extractors/statement_extractor.py` | Company-specific XBRL concepts stored with namespace prefix (e.g. `bk_TotalRevenues...`) were never matching because prefix stripping only ran on raw filing concepts, not on mapping entries. Fix: strip prefix from mapping entries before comparison |
| 17 | `extractors/ai_batch_helper.py` | Same prefix-stripping bug: company-specific concepts were included in the "unmapped" set sent to AI, triggering spurious AI calls. Fix: strip namespace prefix when building `all_mapped_concepts` |
| 18 | `api/importer.py`, `extractors/filing.py` | Quarter labels were computed from the calendar month (always Q1=Jan–Mar, Q4=Oct–Dec) instead of the company's fiscal year end. Non-December FYE companies (e.g. Sep FYE: Q1=Oct–Dec) received wrong quarter numbers. Fix: `_fye_month()` reads `company.fiscal_year_end`; `_fiscal_quarter(period_month, fye_month)` uses the formula `((period_month - fye_month - 1) % 12) // 3 + 1` |
| 19 | `extractors/cash_flow_extractor.py` | Beginning-of-period cash was reading from the same date column as end-of-period cash, making them identical. Fix: added `prior_period_fields` support to `extract_statement()`; cash flow extractor passes `cash_beginning_of_period` in that set to read from the prior date column |
| 20 | `xbrl_mappings/balance_sheet_xbrl_mapping.py` | ASC 842 operating lease right-of-use assets (mandatory since 2019) were not mapped, causing them to be omitted from the balance sheet. Fix: added `OperatingLeaseRightOfUseAsset`, `FinanceLeaseRightOfUseAsset` to `other_noncurrent_assets`; `OperatingLeaseLiabilityCurrent/Noncurrent` and `FinanceLeaseLiabilityCurrent/Noncurrent` to their respective liability fields |
| 21 | `xbrl_mappings/income_statement_xbrl_mapping.py` | `AntidilutiveSecuritiesExcludedFromComputationOfEarningsPerShareByAntidilutiveSecuritiesAxis` was listed under `antidilutive_securities` — it is a presentation axis, not a fact concept, and would never match. Removed |
| 22 | `dcf/assumptions.py`, `dcf/forecaster.py`, `dcf/model.py` | Proforma EBIT was overstated for companies with material operating costs outside COGS/SG&A/R&D (e.g. Amazon: EBIT jumped from $80B to $418B in Y1). Fix: added `other_opex_pct` — residual `(gross_profit − operating_income − SG&A − R&D).clip(0) / revenue` — to `YearForecast`, `YearOverride`, and both EBIT formulas in `model.py` |
| 23 | `dcf/forecaster.py` | P&L ratio forecasting used ARIMA(0,1,0) for Y1-Y2 and OLS linear extrapolation for Y3-Y5. Both methods can extrapolate transient margin trends into forecast years, violating the mean-reversion assumption standard in DCF. Fix: replaced with historical mean applied flat across all 5 forecast years |
| 24 | `dcf/forecaster.py`, `dcf/model.py` | Revenue Y3-Y5 used an OLS dollar-level slope anchored at model Y2. For companies with recent divestitures (e.g. KMB, -18% FY2025), the negative slope produced accelerating declines (-10%, -11%, -12%) and oscillation when analyst estimates overrode Y1/Y2 with a different base. Root cause: fade was computed before analyst estimates were applied, creating a base mismatch. Fix: removed Y3-Y5 logic from `forecast_assumptions`; added `fade_y3_y5()` called in `model.py` after all Y1/Y2 are settled. Fades linearly from actual Y2 growth rate toward terminal growth rate: Y3 = 2/3·g_y2 + 1/3·g_terminal, Y4 = 1/3·g_y2 + 2/3·g_terminal, Y5 = g_terminal |
| 25 | `dcf/forecaster.py` | P&L ratio forecasting used a simple equal-weight mean of the last 5 years, giving stale data equal weight to recent years. Fix: `_mean_ratio` now uses EWM (half-life ~1.4 yrs, same decay as the revenue model) so recent years are weighted more, while flat application across all 5 forecast years is preserved |
| 26 | `dcf/model.py` | Default terminal growth rate was 2.5%. Updated to 3% to better reflect long-run nominal GDP growth |

---

---

## Alpha Vantage Raw Data Pipeline

Downloads and refreshes all Alpha Vantage raw data into `data/av_financials.duckdb`.

### Entry points

| Script | Purpose | AV calls/ticker |
|--------|---------|----------------|
| `scripts/add_tickers.py` | Add new tickers: all AV data + all derived metrics in one pass | 6 (statements + shares + dividends + estimates) |
| `scripts/av_update.py` | Monthly refresh for all tickers in DB | 5 |

`add_tickers.py` is the recommended way to onboard new tickers. It fetches all AV raw data and
immediately computes PE history, dividend yield, and analyst estimates so the ticker is fully
populated in both `av_financials.duckdb` and `historic_fundamentals.duckdb` after a single command.
It skips tickers already in the DB unless `--force` is passed.

`scripts/av_import.py` and `scripts/hf_import.py` remain available as standalone tools for
targeted raw-data or derived-metrics work respectively.

### Tables in av_financials.duckdb

| Table | Source endpoint | Key |
|-------|----------------|-----|
| `income_statements` | INCOME_STATEMENT | (ticker, fiscal_date_ending, period_type) |
| `balance_sheets` | BALANCE_SHEET | (ticker, fiscal_date_ending, period_type) |
| `cash_flow_statements` | CASH_FLOW | (ticker, fiscal_date_ending, period_type) |
| `shares_outstanding` | SHARES_OUTSTANDING | (ticker, date) |
| `dividends` | DIVIDENDS | (ticker, ex_dividend_date) |
| `companies` | — | ticker registry |
| `import_log` | — | audit trail |

### Rate limit

5 AV calls per ticker × 75/min ≈ 95 min for ~1,400 tickers.

---

## Historic Fundamentals Pipeline

Computes derived metrics for all tickers and stores them in `data/historic_fundamentals.duckdb`.

### Entry points

| Script | Purpose | AV calls/ticker |
|--------|---------|----------------|
| `scripts/hf_import.py` | Initial backfill: PE history + estimates | 1 (estimates only) |
| `scripts/hf_update.py` | Monthly refresh: recompute all metrics + refresh estimates | 1 |

`hf_import.py` skips tickers already in the DB unless `--force` is passed.
Both scripts support `--skip-estimates` to skip the AV estimates call (PE/dividend recompute only, no API calls).

### Data sources

| Data | Source | Notes |
|------|--------|-------|
| Net income (TTM) | `av_financials.duckdb / income_statements` | Sum of last 4 quarterly; annual fallback |
| EBITDA (TTM) | `av_financials.duckdb / income_statements.ebitda` | Sum of last 4 quarterly; annual fallback |
| Revenue (TTM) | `av_financials.duckdb / income_statements.total_revenue` | Sum of last 4 quarterly; annual fallback |
| FCF (TTM) | `av_financials.duckdb / cash_flow_statements` | operating_cashflow − capital_expenditures; sum of last 4 quarterly; annual fallback |
| EV debt | `av_financials.duckdb / balance_sheets` | long_term_debt_noncurrent + short_term_debt + current_long_term_debt; most recent quarter ≤ month_end |
| EV cash | `av_financials.duckdb / balance_sheets.cash_and_short_term_investments` | Most recent quarter ≤ month_end |
| Shares (primary) | `av_financials.duckdb / shares_outstanding.shares_outstanding_diluted` | Most recent entry ≤ month_end |
| Shares (fallback) | `av_financials.duckdb / balance_sheets.common_stock_shares_outstanding` | Used when shares_outstanding table has no data |
| Month-end price | `prices.duckdb / stock_prices.adj_close` | Last trading day of each calendar month |
| Dividends | `av_financials.duckdb / dividends` | TTM sum of ex_dividend_date ≤ month_end |
| Analyst estimates | Alpha Vantage EARNINGS_ESTIMATES | 1 AV call/ticker; stored as time-series snapshots |

### Tables in historic_fundamentals.duckdb

| Table | Key | Computed columns |
|-------|-----|-----------------|
| `monthly_pe` | (ticker, month_end_date) | price, ttm_eps, pe_ratio, pe_rolling_5yr_median, shares, ttm_dividend, dividend_yield, ttm_revenue, ttm_fcf, pfcf_ratio, pfcf_rolling_5yr_median, fcf_yield, ttm_ebitda, ev_ebitda, ev_ebitda_rolling_5yr_median |
| `pe_stats` | ticker | market_cap_b, current_pe, pe_lt_median, pe_p10/p25/p75/p90, pe_rolling_5yr_median, forward_pe, forward_12m_eps, current_ttm_eps, months_available, ttm_dividend, dividend_yield, rev_growth_1yr, rev_cagr_3yr/5yr, rev_ntm_growth_est, earn_growth_1yr, earn_cagr_3yr/5yr, earn_ntm_growth_est, current_pfcf, pfcf_lt_median, pfcf_p25/p75, pfcf_rolling_5yr_median, current_fcf_yield, forward_pfcf, fcf_margin_5yr_median, fcf_growth_1yr, fcf_cagr_3yr/5yr, current_evebitda, evebitda_lt_median, evebitda_p25/p75, evebitda_rolling_5yr_median, ebitda_margin_5yr_median, forward_evebitda |
| `earnings_estimates` | (ticker, fiscal_date, horizon, fetched_at) | eps_avg/high/low, rev_avg/high/low, revision counts |

### Call graph

```
hf_import.py / hf_update.py
  ├── for each ticker:
  │   ├── computation phase (no AV calls — reads local DBs)
  │   │   ├── _load_av_data(av_conn, ticker)
  │   │   │     → quarterly + annual: net_income, total_revenue, ebitda, shares,
  │   │   │       long_term_debt_noncurrent, short_term_debt, current_long_term_debt, cash
  │   │   ├── _load_cashflow_data(av_conn, ticker)
  │   │   │     → quarterly + annual: operating_cashflow, capital_expenditures
  │   │   ├── _load_shares_ts(av_conn, ticker)          → shares_outstanding timeseries
  │   │   ├── _load_dividends(av_conn, ticker)          → dividend event history
  │   │   ├── _load_monthly_prices(prices_conn, ticker) → month_end_date, adj_close
  │   │   ├── build_monthly_pe(quarterly, annual, prices, shares_ts, dividends, cashflow_q, cashflow_a)
  │   │   │   ├── shares: shares_outstanding_diluted (fallback: balance sheet)
  │   │   │   ├── TTM EPS: sum last 4 quarterly net_income / shares (or annual fallback)
  │   │   │   ├── pe_ratio = price / ttm_eps (NULL when ttm_eps ≤ 0)
  │   │   │   ├── pe_rolling_5yr_median: rolling(60, min_periods=60).median()
  │   │   │   ├── ttm_dividend: sum dividends with ex_date in trailing 365 days
  │   │   │   ├── dividend_yield: ttm_dividend / price
  │   │   │   ├── ttm_revenue: sum last 4 quarterly total_revenue (or annual fallback)
  │   │   │   ├── ttm_fcf: sum last 4 quarterly (operating_cashflow − capital_expenditures)
  │   │   │   │     (AV reports capex as positive; annual fallback)
  │   │   │   ├── pfcf_ratio = price / (ttm_fcf / shares) (NULL when TTM FCF ≤ 0)
  │   │   │   ├── fcf_yield = (ttm_fcf / shares) / price (NULL when TTM FCF ≤ 0)
  │   │   │   ├── pfcf_rolling_5yr_median: rolling(60, min_periods=60).median()
  │   │   │   ├── ttm_ebitda: sum last 4 quarterly ebitda (or annual fallback)
  │   │   │   ├── ev = price × shares + total_debt − cash (most recent balance sheet ≤ month_end)
  │   │   │   ├── ev_ebitda = ev / ttm_ebitda (NULL when EBITDA ≤ 0 or EV ≤ 0)
  │   │   │   └── ev_ebitda_rolling_5yr_median: rolling(60, min_periods=60).median()
  │   │   ├── compute_pe_stats(ticker, monthly_pe)
  │   │   │     → PE percentiles + current snapshot + FCF/EV/EBITDA lt_median/p25/p75
  │   │   ├── compute_revenue_stats(annual)   → rev_growth_1yr, rev_cagr_3yr, rev_cagr_5yr
  │   │   ├── compute_earnings_stats(annual)  → earn_growth_1yr, earn_cagr_3yr, earn_cagr_5yr
  │   │   ├── compute_fcf_stats(cashflow_a, annual)
  │   │   │     → fcf_growth_1yr, fcf_cagr_3yr, fcf_cagr_5yr, fcf_margin_5yr_median,
  │   │   │       ebitda_margin_5yr_median
  │   │   │       (only positive FCF/EBITDA years used; margins = metric / revenue, last 5 annual)
  │   │   └── hf_db.upsert_monthly_pe() + hf_db.upsert_pe_stats()
  │   ├── estimates phase (1 AV call per ticker, skipped with --skip-estimates)
  │   │   ├── fetch_estimates(ticker, api_key, limiter)  → AV EARNINGS_ESTIMATES response
  │   │   ├── normalize_estimates(ticker, raw)            → DB-ready dicts
  │   │   └── hf_db.upsert_estimates(ticker, rows)
  │   └── snapshot update phase (no AV calls — reads local DBs)
  │       ├── _update_forward_pe()         → forward_pe, forward_12m_eps from stored estimates
  │       ├── _update_rev_ntm_growth_est() → NTM rev estimate / TTM actual revenue − 1
  │       ├── _update_earn_ntm_growth_est() → forward_12m_eps / current_ttm_eps − 1
  │       ├── _update_forward_pfcf()       → price / (NTM_revenue × fcf_margin_5yr_median / shares)
  │       │     (NULL when no NTM revenue estimate or fcf_margin_5yr_median is unavailable)
  │       ├── _update_forward_evebitda()   → current_EV / (NTM_revenue × ebitda_margin_5yr_median)
  │       │     current_EV = price × shares + total_debt − cash (latest quarterly balance sheet)
  │       │     (NULL when EV ≤ 0, no NTM revenue estimate, or ebitda_margin_5yr_median unavailable)
  │       └── _update_market_cap()         → latest price × diluted shares / 1e9 (billions)
  └── hf_db.close()
```

Note: `upsert_pe_stats` uses `COALESCE` for estimate-derived and externally-set fields
(`forward_pe`, `forward_12m_eps`, `forward_pfcf`, `forward_evebitda`, `rev_ntm_growth_est`,
`earn_ntm_growth_est`, `market_cap_b`) so `--skip-estimates` runs preserve existing analyst data.
The snapshot update phase always runs regardless of `--skip-estimates`.

### Rate limit

PE + revenue phase is local (no AV calls): a few minutes for all tickers.
Estimates phase: 1 call/ticker at 75/min ≈ 20 min.

### Notebook usage

```python
import sys
sys.path.insert(0, "..")   # path to project root from notebooks/
from historic_fundamentals import get_pe_stats, get_pe_history, get_estimates

import pandas as pd
pd.set_option('display.max_columns', None)   # 39 columns — prevent truncation

get_pe_stats("AAPL")                          # snapshot: PE, P/FCF, EV/EBITDA, FCF yield,
                                              #   market cap, dividends, revenue/earnings/FCF growth
get_pe_stats(["AAPL", "MSFT", "GOOGL"])      # multiple tickers
get_pe_stats()                                # all tickers

get_pe_history("AAPL", start="2020-01-01")   # monthly: PE, P/FCF, EV/EBITDA, FCF yield,
                                              #   dividend yield, TTM revenue/FCF/EBITDA
get_estimates("AAPL", horizon="fiscal quarter")  # analyst EPS + revenue estimates
```

---

## Adding New Tickers

Run once per new ticker (or batch of tickers):

```bash
# All-in-one: AV raw data + PE history + estimates
uv run scripts/add_tickers.py AAPL MSFT GOOGL

# From a CSV file
uv run scripts/add_tickers.py --csv data/new_tickers.csv

# Skip estimates calls (PE + dividends only, no AV rate limit pressure)
uv run scripts/add_tickers.py AAPL --skip-estimates
```

---

## Monthly Update Workflow

Run once per month after earnings season, in order:

```bash
# 1. Refresh all AV raw data (statements + shares + dividends) — ~95 min
uv run scripts/av_update.py

# 2. Recompute all derived metrics + refresh analyst estimates — ~20 min
uv run scripts/hf_update.py
```

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
