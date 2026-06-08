# Import Pipeline

## Overview

The pipeline fetches SEC EDGAR filings for a list of companies, parses XBRL data, maps concepts to standardized financial line items, and stores results in DuckDB.

### XBRL concept mapping architecture

XBRL concepts are resolved to standardized field names in three layers, tried in order. First, **industry-specific overrides** (`xbrl_mappings/industry_overrides.py`) prepend concepts tuned for the company's Fama-French 48 industry (derived from its SIC code via `xbrl_mappings/sic_lookup.py`); this is the primary accuracy gain for banks, insurers, and REITs. Second, the **expanded static mappings** (`xbrl_mappings/income_statement_xbrl_mapping.py`, `balance_sheet_xbrl_mapping.py`, `cash_flow_xbrl_mapping.py`) cover 1,236 concepts sourced from edgartools' `gaap_mappings.json` (2,924 raw concepts), tiered by confidence — high-confidence entries (≥ 0.7) precede lower-confidence ones (0.5–0.69). Third, an **AI fallback** (`use_ai_fallback=True`) attempts LLM-based discovery for any field still unresolved after both layers. The bridge mapping (`xbrl_mappings/bridge_mapping.json`) translates edgartools standard tags to fin_import2 field names and served as the generation key for the static expansion.

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
| `scripts/manage_tickers.py add` | Add new tickers: prices + all AV data + all derived metrics in one pass | ~8 (statements + shares + dividends + overview + prices + estimates) |
| `scripts/av_update.py` | Monthly refresh for all tickers in DB (statements + shares + dividends + overview) | 6 |
| `scripts/av_import_overview.py` | Backfill company overview for all tickers (first-time setup) | 1 |

`manage_tickers.py add` is the recommended way to onboard new tickers. It populates all three
databases (`av_financials.duckdb`, `prices.duckdb`, `historic_fundamentals.duckdb`) in a single
command, including goal prices and all forward multiples. Use `manage_tickers.py delete` to remove
a ticker cleanly from all three DBs.

`scripts/av_import.py` and `scripts/hf_import.py` remain available as standalone tools for
targeted raw-data or derived-metrics work respectively.

`av_update.py` accepts `--skip-overview` to omit the OVERVIEW calls (e.g. when only raw financials changed). `av_import_overview.py` accepts `--force` to re-fetch even if already fetched this month, and `--ticker` for a single ticker.

### Tables in av_financials.duckdb

| Table | Source endpoint | Key |
|-------|----------------|-----|
| `income_statements` | INCOME_STATEMENT | (ticker, fiscal_date_ending, period_type) |
| `balance_sheets` | BALANCE_SHEET | (ticker, fiscal_date_ending, period_type) |
| `cash_flow_statements` | CASH_FLOW | (ticker, fiscal_date_ending, period_type) |
| `shares_outstanding` | SHARES_OUTSTANDING | (ticker, date) |
| `dividends` | DIVIDENDS | (ticker, ex_dividend_date) |
| `company_overview` | OVERVIEW | (ticker, fetch_date) |
| `companies` | — | ticker registry |
| `import_log` | — | audit trail |

`company_overview` stores a snapshot per `(ticker, fetch_date)` for monthly historical tracking. All 45 AV OVERVIEW fields are stored (text, date, and numeric). The latest snapshot per ticker is joined automatically into `get_pe_stats()` to supply `name`, `sector`, `industry`, and `beta`. Query with `uv run scripts/av_query.py TICKER --overview` (latest) or `--overview --history` (all snapshots).

### Rate limit

6 AV calls per ticker × 75/min ≈ 115 min for ~1,400 tickers.

---

## Historic Fundamentals Pipeline

Computes derived metrics for all tickers and stores them in `data/historic_fundamentals.duckdb`.

### Entry points

| Script | Purpose | AV calls/ticker |
|--------|---------|----------------|
| `scripts/hf_import.py` | Initial backfill: PE history + estimates | 1 (estimates only) |
| `scripts/hf_update.py` | Monthly refresh: recompute all metrics + refresh estimates + goal prices + sector stats | 1 |

`hf_import.py` skips tickers already in the DB unless `--force` is passed.
Both scripts support `--skip-estimates` to skip the AV estimates call (PE/dividend recompute only, no API calls).

`hf_update.py` additional flags:
- `--skip-sector` — skip sector/industry aggregate stats computation
- `--full-sector-rebuild` — recompute sector stats for all historical months (default: incremental, new months only)

Sector stats are computed after the per-ticker loop and require `company_overview` data in `av_financials.duckdb`. Run `av_import_overview.py` first if sector stats show no data.

### Data sources

| Data | Source | Notes |
|------|--------|-------|
| Net income (TTM) | `av_financials.duckdb / income_statements` | Sum of last 4 quarterly; annual fallback |
| EBITDA (TTM) | `av_financials.duckdb / income_statements.ebitda` | Sum of last 4 quarterly; annual fallback |
| EBIT (TTM) | `av_financials.duckdb / income_statements.ebit` | Sum of last 4 quarterly; annual fallback (used for ROIC) |
| Revenue (TTM) | `av_financials.duckdb / income_statements.total_revenue` | Sum of last 4 quarterly; annual fallback |
| Income tax / pre-tax income | `av_financials.duckdb / income_statements` | income_tax_expense / income_before_tax; used to compute effective tax rate for ROIC |
| FCF (TTM) | `av_financials.duckdb / cash_flow_statements` | operating_cashflow − capital_expenditures; sum of last 4 quarterly; annual fallback |
| Total assets | `av_financials.duckdb / balance_sheets.total_assets` | Most recent quarter ≤ month_end (used for ROA) |
| Shareholder equity | `av_financials.duckdb / balance_sheets.total_shareholder_equity` | Most recent quarter ≤ month_end (used for ROE, ROIC, P/BV, P/TBV) |
| Intangibles / goodwill | `av_financials.duckdb / balance_sheets` | intangible_assets_excl_goodwill + goodwill; most recent quarter ≤ month_end (used for P/TBV) |
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
| `monthly_pe` | (ticker, month_end_date) | price, ttm_eps, pe_ratio, pe_rolling_5yr_median, normalized_pe_5y, earnings_yield, earnings_yield_3y_avg, earnings_yield_5y_avg, shares, ttm_dividend, dividend_yield, ttm_revenue, ttm_fcf, pfcf_ratio, pfcf_rolling_5yr_median, normalized_pfcf_5y, fcf_yield, fcf_yield_3y_avg, fcf_yield_5y_avg, ttm_ebitda, ev_ebitda, ev_ebitda_rolling_5yr_median, normalized_evebitda_5y, ebitda_ev_yield, ebitda_ev_yield_3y_avg, ebitda_ev_yield_5y_avg, ps_ratio, ps_rolling_5yr_median, normalized_ps_5y, roa, roa_rolling_5yr_median, roe, roe_rolling_5yr_median, roic, roic_rolling_5yr_median, pbv, pbv_rolling_5yr_median, ptbv, ptbv_rolling_5yr_median, goal_pe, goal_pcf, goal_peg, goal_bv, goal_2x, goal_low, goal_high |
| `pe_stats` | ticker | market_cap_b, current_price, current_pe, pe_lt_median, pe_p10/p25/p75/p90, pe_rolling_5yr_median, normalized_pe_5y, current_earnings_yield, earnings_yield_3y_avg, earnings_yield_5y_avg, forward_pe, forward_12m_eps, forward_earnings_yield, current_ttm_eps, months_available, ttm_dividend, dividend_yield, rev_growth_1yr, rev_cagr_3yr/5yr, rev_ntm_growth_est, earn_growth_1yr, earn_cagr_3yr/5yr, earn_ntm_growth_est, current_pfcf, pfcf_lt_median, pfcf_p25/p75, pfcf_rolling_5yr_median, normalized_pfcf_5y, current_fcf_yield, fcf_yield_3y_avg, fcf_yield_5y_avg, forward_pfcf, fcf_margin_5yr_median, fcf_growth_1yr, fcf_cagr_3yr/5yr, current_evebitda, evebitda_lt_median, evebitda_p25/p75, evebitda_rolling_5yr_median, normalized_evebitda_5y, current_ebitda_ev_yield, ebitda_ev_yield_3y_avg, ebitda_ev_yield_5y_avg, ebitda_margin_5yr_median, forward_evebitda, current_ps, ps_lt_median, ps_p25/p75, ps_rolling_5yr_median, normalized_ps_5y, forward_ps, current_roa, roa_lt_median, roa_p25/p75, roa_rolling_5yr_median, current_roe, roe_lt_median, roe_p25/p75, roe_rolling_5yr_median, current_roic, roic_lt_median, roic_p25/p75, roic_rolling_5yr_median, current_pbv, pbv_lt_median, pbv_p25/p75, pbv_rolling_5yr_median, current_ptbv, ptbv_lt_median, ptbv_p25/p75, ptbv_rolling_5yr_median, goal_pe, goal_pcf, goal_peg, goal_bv, goal_2x, goal_low, goal_high |
| `earnings_estimates` | (ticker, fiscal_date, horizon, fetched_at) | eps_avg/high/low, rev_avg/high/low, revision counts |
| `sector_stats` | (group_type, group_name, month_end_date) | ticker_count, pe/pfcf/evebitda/ps median/p25/p75, pbv_median, earnings_yield/fcf_yield/ebitda_ev_yield/dividend_yield medians, roa/roe/roic median/p25/p75, rev_growth_1yr_median, earn_growth_1yr_median |

`sector_stats` holds both `group_type='sector'` and `group_type='industry'` rows in the same table, keyed by `(group_type, group_name, month_end_date)`. Only groups with at least 5 valid peers per metric are included. Sector assignments are sourced from the latest `company_overview` snapshot (today's assignments applied back through history, consistent with standard factor-investing convention).

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
  │   │   │   ├── pe_rolling_5yr_median: rolling(60, min_periods=36).median()
  │   │   │   │     [min_periods=36 so up to 2 years of losses in the window still yields a value]
  │   │   │   ├── normalized_pe_5y = price / rolling_60m_mean(ttm_eps, min_periods=36)
  │   │   │   │     (includes negative EPS years in the average; NULL when avg ≤ 0)
  │   │   │   ├── earnings_yield = ttm_eps / price (defined even when negative; no blow-up)
  │   │   │   ├── earnings_yield_3y_avg: rolling(36, min_periods=24).mean()
  │   │   │   ├── earnings_yield_5y_avg: rolling(60, min_periods=36).mean()
  │   │   │   ├── ttm_dividend: sum dividends with ex_date in trailing 365 days
  │   │   │   ├── dividend_yield: ttm_dividend / price
  │   │   │   ├── ttm_revenue: sum last 4 quarterly total_revenue (or annual fallback)
  │   │   │   ├── ttm_fcf: sum last 4 quarterly (operating_cashflow − capital_expenditures)
  │   │   │   │     (AV reports capex as positive; annual fallback)
  │   │   │   ├── pfcf_ratio = price / (ttm_fcf / shares) (NULL when TTM FCF ≤ 0)
  │   │   │   ├── fcf_yield = (ttm_fcf / shares) / price (always defined; negative when FCF < 0)
  │   │   │   ├── pfcf_rolling_5yr_median: rolling(60, min_periods=36).median()
  │   │   │   ├── fcf_yield_3y_avg: rolling(36, min_periods=24).mean()
  │   │   │   ├── fcf_yield_5y_avg: rolling(60, min_periods=36).mean()
  │   │   │   ├── normalized_pfcf_5y = price / rolling_60m_mean(fcf_per_share, min_periods=36)
  │   │   │   │     (NULL when avg ≤ 0)
  │   │   │   ├── ttm_ebitda: sum last 4 quarterly ebitda (or annual fallback)
  │   │   │   ├── ev = price × shares + total_debt − cash (computed when balance sheet available; NULL when ev ≤ 0)
  │   │   │   ├── ev_ebitda = ev / ttm_ebitda (NULL when EBITDA ≤ 0 or EV ≤ 0)
  │   │   │   ├── ev_ebitda_rolling_5yr_median: rolling(60, min_periods=36).median()
  │   │   │   ├── ebitda_ev_yield = ttm_ebitda / ev (always defined when EV > 0; negative when EBITDA < 0)
  │   │   │   ├── ebitda_ev_yield_3y_avg: rolling(36, min_periods=24).mean()
  │   │   │   ├── ebitda_ev_yield_5y_avg: rolling(60, min_periods=36).mean()
  │   │   │   ├── normalized_evebitda_5y = ev / rolling_60m_mean(ttm_ebitda, min_periods=36)
  │   │   │   │     (NULL when avg ≤ 0 or ev unavailable)
  │   │   │   ├── ps_ratio = price × shares / ttm_revenue (market cap / revenue; NULL when revenue = 0)
  │   │   │   ├── ps_rolling_5yr_median: rolling(60, min_periods=36).median()
  │   │   │   ├── normalized_ps_5y = market_cap / rolling_60m_mean(ttm_revenue, min_periods=36)
  │   │   │   │     (NULL when avg ≤ 0)
  │   │   │   ├── roa = ttm_net_income / total_assets (most recent BS ≤ month_end; negative allowed)
  │   │   │   ├── roa_rolling_5yr_median: rolling(60, min_periods=36).median()
  │   │   │   ├── roe = ttm_net_income / equity (NULL when equity ≤ 0; negative allowed)
  │   │   │   ├── roe_rolling_5yr_median: rolling(60, min_periods=36).median()
  │   │   │   ├── NOPAT = TTM EBIT × (1 − eff_tax_rate); rate clamped [0, 0.5], default 21%
  │   │   │   ├── roic = NOPAT / invested_capital; IC = equity + net_debt (NULL when IC ≤ 0)
  │   │   │   ├── roic_rolling_5yr_median: rolling(60, min_periods=36).median()
  │   │   │   ├── pbv = price / (equity / shares) (NULL when equity ≤ 0)
  │   │   │   ├── pbv_rolling_5yr_median: rolling(60, min_periods=36).median()
  │   │   │   ├── ptbv = price / (TBV / shares); TBV = equity − intangibles_excl_gw − goodwill
  │   │   │   │     (NULL when TBV ≤ 0)
  │   │   │   └── ptbv_rolling_5yr_median: rolling(60, min_periods=36).median()
  │   │   ├── compute_pe_stats(ticker, monthly_pe)
  │   │   │     → current_price + PE percentiles + current snapshot +
  │   │   │       normalized_pe_5y, current/3y/5y earnings_yield, forward_earnings_yield +
  │   │   │       normalized_pfcf_5y, current_fcf_yield, fcf_yield_3y/5y_avg +
  │   │   │       normalized_evebitda_5y, current_ebitda_ev_yield, ebitda_ev_yield_3y/5y_avg +
  │   │   │       normalized_ps_5y +
  │   │   │       FCF/EV/EBITDA/P/S/ROA/ROE/ROIC/P/BV/P/TBV lt_median/p25/p75
  │   │   ├── compute_revenue_stats(annual)   → rev_growth_1yr, rev_cagr_3yr, rev_cagr_5yr
  │   │   ├── compute_earnings_stats(annual)  → earn_growth_1yr, earn_cagr_3yr, earn_cagr_5yr
  │   │   └── compute_fcf_stats(cashflow_a, annual)
  │   │         → fcf_growth_1yr, fcf_cagr_3yr, fcf_cagr_5yr, fcf_margin_5yr_median,
  │   │           ebitda_margin_5yr_median
  │   │           (only positive FCF/EBITDA years used; margins = metric / revenue, last 5 annual)
  │   ├── estimates phase (1 AV call per ticker, skipped with --skip-estimates)
  │   │   ├── fetch_estimates(ticker, api_key, limiter)  → AV EARNINGS_ESTIMATES response
  │   │   ├── normalize_estimates(ticker, raw)            → DB-ready dicts
  │   │   └── hf_db.upsert_estimates(ticker, rows)
  │   │     [estimates stored before goals so PEG goal uses fresh data]
  │   ├── goal enrichment phase (no AV calls)
  │   │   ├── enrich_goals(monthly_pe, stats, hf_db.conn, ticker)
  │   │   │   ├── goal_pe   = ttm_eps × pe_lt_median
  │   │   │   ├── goal_pcf  = (ttm_fcf / shares) × pfcf_lt_median
  │   │   │   ├── goal_peg  = forward_12m_eps (as-of month) × pe_lt_median
  │   │   │   │     (looks up earnings_estimates; NULL for months without stored estimates)
  │   │   │   ├── goal_bv   = (price / pbv) × pbv_lt_median
  │   │   │   ├── goal_2x   = 2 × price
  │   │   │   ├── goal_low  = min(avg of valid goals, goal_peg)
  │   │   │   └── goal_high = max of valid goals  [valid = non-null and > 0]
  │   │   ├── extract_goal_stats(monthly_pe)  → current goal values for pe_stats
  │   │   └── hf_db.upsert_monthly_pe() + hf_db.upsert_pe_stats()
  │   └── snapshot update phase (no AV calls — reads local DBs)
  │       ├── _update_forward_pe()         → forward_pe, forward_12m_eps from stored estimates
  │       ├── _update_rev_ntm_growth_est() → NTM rev estimate / TTM actual revenue − 1
  │       ├── _update_earn_ntm_growth_est() → forward_12m_eps / current_ttm_eps − 1
  │       ├── _update_forward_pfcf()       → price / (NTM_revenue × fcf_margin_5yr_median / shares)
  │       │     (NULL when no NTM revenue estimate or fcf_margin_5yr_median is unavailable)
  │       ├── _update_forward_evebitda()   → current_EV / (NTM_revenue × ebitda_margin_5yr_median)
  │       │     current_EV = price × shares + total_debt − cash (latest quarterly balance sheet)
  │       │     (NULL when EV ≤ 0, no NTM revenue estimate, or ebitda_margin_5yr_median unavailable)
  │       ├── _update_forward_ps()         → current_market_cap / NTM_revenue
  │       │     current_market_cap = latest price × diluted shares
  │       │     (NULL when no NTM revenue estimate available)
  │       └── _update_market_cap()         → latest price × diluted shares / 1e9 (billions)
  ├── sector stats phase (after ticker loop, full-update only, skipped with --skip-sector or --ticker)
  │   ├── compute_sector_stats(hf_db.conn, av_db_path, full_rebuild=args.full_sector_rebuild)
  │   │   ├── open av_conn (read-only), query company_overview QUALIFY latest fetch_date per ticker
  │   │   ├── register _sector_map temp view in hf_conn
  │   │   └── for group_type in (sector, industry):
  │   │       └── run aggregation SQL on monthly_pe joined to _sector_map
  │   │           ├── prior_year CTE: range-join 10–14 months back, MAX per ticker+month → prior_date
  │   │           ├── base CTE: join sector map + prior month for YoY growth
  │   │           └── aggregate: QUANTILE_CONT(metric, 0.50/0.25/0.75) FILTER (WHERE metric > 0)
  │   │               for pe, pfcf, ev_ebitda, ps, pbv, roa, roe, roic; medians for yields + growth
  │   │               HAVING COUNT(DISTINCT ticker) >= 5
  │   │           incremental mode: skips months already in sector_stats via NOT IN subquery
  │   └── hf_db.upsert_sector_stats(sector_df)  → INSERT OR REPLACE via temp view
  └── hf_db.close()
```

Note: `upsert_pe_stats` uses `COALESCE` for estimate-derived and externally-set fields
(`forward_pe`, `forward_12m_eps`, `forward_earnings_yield`, `forward_pfcf`, `forward_evebitda`,
`forward_ps`, `rev_ntm_growth_est`, `earn_ntm_growth_est`, `market_cap_b`) so `--skip-estimates`
runs preserve existing analyst data. The snapshot update phase always runs regardless of
`--skip-estimates`.

### Rate limit

PE + revenue phase is local (no AV calls): a few minutes for all tickers.
Estimates phase: 1 call/ticker at 75/min ≈ 20 min.

### Notebook usage

```python
import sys
sys.path.insert(0, "..")   # path to project root from notebooks/
from historic_fundamentals import get_pe_stats, get_pe_history, get_estimates, get_sector_stats, get_sector_history

import pandas as pd
pd.set_option('display.max_columns', None)

# Ticker snapshots
get_pe_stats("AAPL")                          # current_price, PE, P/FCF, EV/EBITDA, P/S,
                                              #   ROA, ROE, ROIC, P/BV, P/TBV, market cap,
                                              #   dividends, growth, goal prices,
                                              #   + sector/industry peer percentile ranks
                                              #   (sector_pe_pct, sector_val_score, etc.)
get_pe_stats(["AAPL", "MSFT", "GOOGL"])
get_pe_stats()                                # all tickers; sector/industry ranks auto-computed

# Monthly timeseries
get_pe_history("AAPL", start="2020-01-01")   # PE, P/FCF, EV/EBITDA, P/S, ROA, ROE, ROIC,
                                              #   P/BV, P/TBV, FCF yield, dividend yield,
                                              #   TTM revenue/FCF/EBITDA, goal prices

# Analyst estimates
get_estimates("AAPL", horizon="fiscal quarter")

# Sector/industry aggregate fundamentals
get_sector_stats()                            # latest sector medians (PE, P/FCF, EV/EBITDA,
                                              #   P/S, P/BV, yields, ROA, ROE, ROIC, growth)
get_sector_stats("industry")                  # same at industry level
get_sector_stats("sector", ["Technology", "Healthcare"])  # filter specific sectors

get_sector_history("TECHNOLOGY")              # monthly sector timeseries since inception
get_sector_history("Software—Application", group="industry", start="2020-01-01")
```

`get_pe_stats()` adds the following peer rank columns when sector/industry data is available (requires `av_import_overview.py` to have run):

| Column | Meaning |
|--------|---------|
| `sector_pe_pct` | PE percentile within sector (0=cheapest, 100=most expensive) |
| `sector_pfcf_pct` | P/FCF percentile within sector |
| `sector_evebitda_pct` | EV/EBITDA percentile within sector |
| `sector_ps_pct` | P/S percentile within sector |
| `sector_roic_pct` | ROIC quality percentile within sector (100=highest quality) |
| `sector_val_score` | Composite value score: mean of (100 − pe/pfcf/evebitda/ps pcts); high = cheap |
| `industry_*` | Same columns at industry level |

Ranks are NULL for stocks with fewer than 5 valid peers in their group.

---

## Adding New Tickers

Run once per new ticker (or batch of tickers):

```bash
# All-in-one: prices + AV raw data + PE history + estimates
uv run scripts/manage_tickers.py add AAPL MSFT GOOGL

# From a CSV file
uv run scripts/manage_tickers.py add --csv data/new_tickers.csv

# Skip estimates calls (saves 1 AV call/ticker)
uv run scripts/manage_tickers.py add AAPL --skip-estimates

# Preview without writing anything
uv run scripts/manage_tickers.py add AAPL --dry-run
```

---

## Monthly Update Workflow

Run once per month after earnings season, in order:

```bash
# 1. Refresh all AV raw data (statements + shares + dividends + company overview) — ~115 min
uv run scripts/av_update.py

# 2. Recompute all derived metrics + refresh analyst estimates + sector stats — ~20 min
uv run scripts/hf_update.py
```

To skip the overview refresh (e.g. mid-month statement update only):
```bash
uv run scripts/av_update.py --skip-overview     # ~95 min; omits OVERVIEW calls
uv run scripts/hf_update.py --skip-sector       # skips sector stats aggregation
```

First-time setup (run once after the initial `av_update.py`):
```bash
uv run scripts/av_import_overview.py            # backfills company overview for all tickers (~19 min)
uv run scripts/hf_update.py --full-sector-rebuild  # computes sector stats for all historical months
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
