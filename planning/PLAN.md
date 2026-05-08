# PLAN: Financial Statements Import Pipeline

## Status: Complete (as of 2026-04-30)

All planned improvements have been implemented. This document reflects the current state.

---

## Architecture

```
Browser (Next.js :3000)
    ↕  HTTP (JSON)
FastAPI backend (Python :8000)
    ↕
extractors/ + xbrl_mappings/ + financial_statements_db.py
dcf/ (FCFF model, forecaster, WACC)
    ↕
DuckDB (data/financial_statements.duckdb)
```

---

## Backend: FastAPI (`api/`)

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/import` | Trigger import for a ticker |
| GET | `/statements/{ticker}/{type}` | Retrieve stored statement |
| GET | `/tickers` | List tickers already in DB |
| GET | `/dcf/{ticker}` | DCF valuation with model defaults |
| POST | `/dcf/{ticker}/run` | Re-run DCF with user overrides |

### Key implementation notes

- Single `FinancialStatementsDB` instance opened at app startup (lifespan)
- `company.latest(form)` used for single-filing imports (zero extra network cost)
- `period_type=FY` → 10-K, `period_type=Q` → 10-Q

---

## Extractor pipeline

Consolidated from 3 near-duplicate files into a shared core + thin wrappers:

```
extractors/statement_extractor.py        ← shared core
extractors/income_statement_extractor.py ← wrapper
extractors/balance_sheet_extractor.py    ← wrapper
extractors/cash_flow_extractor.py        ← wrapper
```

Key behaviors:
- `stmt.to_dataframe(presentation=False)` — raw XBRL values, consistent signs
- `max_fields` mechanism — takes the largest matching value for total-line fields
  (prevents revenue understatement when e.g. `Revenues` and `RFCWCEA` both appear)
- `filing.report_date` preferred over `filing.period_of_report` (avoids SGML download)
- Date column detection handles `(FY)` / `(Q1)` / `(YTD)` suffixes from edgartools v5+
- D&A sourced from cash flow statement (primary) with income statement as fallback

---

## Bulk import (`bulk_import_10k.py`)

- Concurrent ticker processing via `asyncio.Semaphore(concurrency)` (default: 3)
- edgartools built-in rate limiter handles SEC's 9 req/s; no sleep needed
- `clear_company_facts_cache()` called after each ticker to prevent memory growth
- `INSERT OR REPLACE INTO` for atomic upserts (no delete-then-insert race)

---

## DCF engine (`dcf/`)

FCFF model using granular P&L ratios:

```
EBIT   = Revenue × (1 - cogs_pct - sga_pct - rd_pct)
NOPAT  = EBIT × (1 - tax_rate)
FCFF   = NOPAT + D&A - CapEx - ΔNWC
ΔNWC   = Days-based working capital model (DSO, DPO, DIO)
TV     = FCFF₅ × (1 + g) / (WACC - g)   [Gordon Growth]
EV     = Σ PV(FCFF₁..₅) + PV(TV)
```

Revenue forecasting:
- Y1-Y2: analyst annual revenue estimates (Alpha Vantage) are the primary source; EWM of historical annual growth rates blended with quarterly momentum signal (50%/25%) is the fallback when no estimates are available
- Y3-Y5: linear fade from the final Y2 growth rate toward the terminal growth rate, applied after all Y1/Y2 are settled (analyst estimates + user overrides + quarterly actuals cascade). Y3 = 2/3·g_y2 + 1/3·g_terminal, Y4 = 1/3·g_y2 + 2/3·g_terminal, Y5 = g_terminal
- Quarterly YTD detection: identifies YTD-cumulative filers (AAPL pattern: 3 entries/year with resets > 35%) and groups by fiscal year before computing YoY comparisons

P&L ratio forecasting: exponentially weighted mean of the last 5 annual years (EWM half-life ~1.4 yrs, same decay as revenue model), applied flat across all 5 forecast years. Recent years are weighted more than older ones; mean-reversion over the competitive horizon is preserved.

WACC: Hamada equation; risk-free rate from FRED DGS10; yfinance beta; cost of debt from 5-yr average interest/debt.

Default terminal growth rate: 3%.

All WACC inputs, per-year P&L ratios, and working capital days are overridable in the UI. Reset button restores model defaults without re-fetching.

---

## Frontend: Next.js (`web/`)

- Next.js 16 (App Router, Turbopack)
- Tailwind CSS v4 dark mode
- IBM Plex Mono / IBM Plex Sans fonts
- Tabs: Financials (income / balance / cash flow table) + DCF Valuation

### Import defaults

- Default: 10 FY (annual) periods
- On FY import: background async fetch of up to 20 quarterly filings (non-blocking)
- Financials table has FY / Q display toggle; switching re-fetches appropriate period count

### DCF UI layout (DcfViewer)

```
[ Valuation Summary + editable WACC card ]

[ Historical & Proforma statements table ]
  (editable P&L ratios: cogs%, sga%, rd%, capex% per forecast year)

[ NWC & CapEx table ]
  (editable DSO / DPO / DIO; projected ΔNWC and CapEx per year)

[ FCFF build-up table ]
  (Revenue → EBIT → NOPAT → +D&A → -CapEx → -ΔNWC → FCFF → Discount → PV)
  (Terminal value column; EV bridge below table)

[ Terminal Value decomposition card ]

[ Sensitivity table ] (WACC × terminal growth, 5×5)

[ PV Breakdown bar chart ]
```

Keyboard navigation:
- WACC card: up/down arrow between the 5 editable inputs
- Proforma table: up/down/left/right across all editable cells; Enter blurs
- Fields auto-format on blur: percentages show "%" suffix, betas show 2 decimal places, days show 1 decimal place

---

## UI improvements (2026-04-29)

- **Period end dates**: shown in column headers in both Financials and DCF historical tables
- **Shares formatting**: shares-outstanding fields in Financials table render without `$` prefix (e.g. `15.2B` not `$15.2B`)
- **Full equity bridge**: DcfFcffTable now shows `∑PV FCFFs + PV Terminal = EV − Net Debt = Equity ÷ Diluted Shares = Intrinsic Value/Share`
- **DCF "as of" date**: header shows the most recent historical period end date

## XBRL mapping fixes (2026-04-30)

- `PaymentsToAcquireProductiveAssets` added to `capital_expenditures` in `cash_flow_xbrl_mapping.py` — Amazon uses this concept instead of the standard `PaymentsToAcquirePropertyPlantAndEquipment`
- Historical FCFF rows now joined by `period_end_date` (was positional index) — prevents silent null CapEx when income/balance/cashflow tables have different row counts
- `HistoricalRow` dataclass and TypeScript interface extended with `period_end_date` field

## DCF forecasting enhancements (2026-05-06)

- **Revenue Y3-Y5 methodology**: replaced OLS dollar-level slope (which extrapolated historical divestiture declines) with a fade model anchored on the final post-analyst Y2 growth rate. `fade_y3_y5()` in `forecaster.py` is called from `model.py` after analyst estimates, user overrides, and the Y1 quarterly actuals cascade are all settled. Y3 = 2/3·g_y2 + 1/3·g_terminal, Y4 = 1/3·g_y2 + 2/3·g_terminal, Y5 = g_terminal. This is the standard equity research approach and avoids oscillation from analyst/model base mismatches.
- **P&L ratio forecasting**: replaced simple equal-weight 5-year mean with EWM (half-life ~1.4 yrs) in `_mean_ratio`. Applies to COGS%, SG&A%, R&D%, interest%, other opex%. D&A% and CapEx% retain their normalized mean (asset-intensity ratios are not trend-driven).
- **Default terminal growth rate**: raised from 2.5% to 3% (`DEFAULT_TERMINAL_GROWTH` in `model.py`).

## MCP integration

edgartools MCP server configured in `~/.claude.json` with `EDGAR_IDENTITY` env var.
Supports `edgar_company`, `edgar_filing`, `edgar_compare`, `edgar_trends`, and others.

---

---

# Alpha Vantage Financial Statements Database — Implementation Plan

## Status: Complete (as of 2026-05-08)

---

## Overview

Build a production-grade pipeline to fetch, store, and query financial statements
(income statement, balance sheet, cash flow) from the Alpha Vantage API into a new
dedicated DuckDB database. No changes to existing fin_import2 code.

---

## Database Recommendation

**DuckDB** — already used throughout the project. Optimal for this workload:
- Columnar storage: fast aggregations across thousands of tickers and decades of data
- Native Python/pandas integration (already in use)
- Zero server overhead; single file, trivially backed up
- Scales comfortably to millions of rows (1000 tickers × 80 quarters × 3 statements ≈ 240 000 rows)

**File**: `data/av_financials.duckdb` (separate from the SEC EDGAR `financial_statements.duckdb`)

---

## File Structure

```
av_financials_db.py               # Core DB class + rate-limited AV fetcher
scripts/
    av_import.py                  # CLI: import one ticker / CSV / prices.duckdb
    av_query.py                   # CLI: query statements with optional date range
    av_update.py                  # CLI: refresh all tickers already in the DB
```

---

## Rate Limiting

Alpha Vantage limit: **75 calls/minute**.
Each ticker requires **3 API calls** (INCOME_STATEMENT + BALANCE_SHEET + CASH_FLOW).
Sustained bulk throughput: 25 tickers/minute.

Implementation: a `RateLimiter` class using a sliding deque of timestamps.
Before each API call, the limiter checks how many calls have been made in the
last 60 seconds and sleeps the minimum required to stay under the limit.

```python
class RateLimiter:
    def __init__(self, max_calls: int = 75, period: float = 60.0): ...
    def wait(self) -> None: ...   # blocks until a call slot is available
```

---

## .env Additions

```
ALPHA_VANTAGE_API_KEY=<already present>
PRICES_DB_PATH=/home/pedro/projects/trade_systems/data/prices.duckdb
AV_DB_PATH=data/av_financials.duckdb    # optional override
```

---

## Core Module: `av_financials_db.py`

### Class `AVFinancialsDB`

**Responsibilities**:
- Open/create `data/av_financials.duckdb` and create schema on first use
- Rate-limited API fetching via `RateLimiter`
- Insert/upsert all three statement types
- Query with optional date and period filters
- Import log tracking

### DB Schema

#### `companies`
```sql
ticker          VARCHAR PRIMARY KEY,
last_updated_at TIMESTAMP,
total_annual    INTEGER DEFAULT 0,
total_quarterly INTEGER DEFAULT 0
```

#### `income_statements`
```sql
ticker                              VARCHAR NOT NULL,
fiscal_date_ending                  DATE NOT NULL,
period_type                         VARCHAR NOT NULL,   -- 'annual' | 'quarterly'
reported_currency                   VARCHAR,
fetched_at                          TIMESTAMP,
gross_profit                        DOUBLE,
total_revenue                       DOUBLE,
cost_of_revenue                     DOUBLE,
cost_of_goods_and_services_sold     DOUBLE,
operating_income                    DOUBLE,
selling_general_and_administrative  DOUBLE,
research_and_development            DOUBLE,
operating_expenses                  DOUBLE,
investment_income_net               DOUBLE,
net_interest_income                 DOUBLE,
interest_income                     DOUBLE,
interest_expense                    DOUBLE,
non_interest_income                 DOUBLE,
other_non_operating_income          DOUBLE,
depreciation                        DOUBLE,
depreciation_and_amortization       DOUBLE,
income_before_tax                   DOUBLE,
income_tax_expense                  DOUBLE,
interest_and_debt_expense           DOUBLE,
net_income_from_continuing_ops      DOUBLE,
comprehensive_income_net_of_tax     DOUBLE,
ebit                                DOUBLE,
ebitda                              DOUBLE,
net_income                          DOUBLE,
PRIMARY KEY (ticker, fiscal_date_ending, period_type)
```

#### `balance_sheets`
```sql
ticker                                  VARCHAR NOT NULL,
fiscal_date_ending                      DATE NOT NULL,
period_type                             VARCHAR NOT NULL,
reported_currency                       VARCHAR,
fetched_at                              TIMESTAMP,
total_assets                            DOUBLE,
total_current_assets                    DOUBLE,
cash_and_cash_equivalents               DOUBLE,
cash_and_short_term_investments         DOUBLE,
inventory                               DOUBLE,
current_net_receivables                 DOUBLE,
total_non_current_assets                DOUBLE,
property_plant_equipment_net            DOUBLE,
accumulated_depreciation_amortization   DOUBLE,
intangible_assets                       DOUBLE,
intangible_assets_excl_goodwill         DOUBLE,
goodwill                                DOUBLE,
investments                             DOUBLE,
long_term_investments                   DOUBLE,
short_term_investments                  DOUBLE,
other_current_assets                    DOUBLE,
other_non_current_assets                DOUBLE,
total_liabilities                       DOUBLE,
total_current_liabilities               DOUBLE,
current_accounts_payable                DOUBLE,
deferred_revenue                        DOUBLE,
current_debt                            DOUBLE,
short_term_debt                         DOUBLE,
total_non_current_liabilities           DOUBLE,
capital_lease_obligations               DOUBLE,
long_term_debt                          DOUBLE,
current_long_term_debt                  DOUBLE,
long_term_debt_noncurrent               DOUBLE,
short_long_term_debt_total              DOUBLE,
other_current_liabilities               DOUBLE,
other_non_current_liabilities           DOUBLE,
total_shareholder_equity                DOUBLE,
treasury_stock                          DOUBLE,
retained_earnings                       DOUBLE,
common_stock                            DOUBLE,
common_stock_shares_outstanding         DOUBLE,
PRIMARY KEY (ticker, fiscal_date_ending, period_type)
```

#### `cash_flow_statements`
```sql
ticker                                          VARCHAR NOT NULL,
fiscal_date_ending                              DATE NOT NULL,
period_type                                     VARCHAR NOT NULL,
reported_currency                               VARCHAR,
fetched_at                                      TIMESTAMP,
operating_cashflow                              DOUBLE,
payments_for_operating_activities               DOUBLE,
proceeds_from_operating_activities              DOUBLE,
change_in_operating_liabilities                 DOUBLE,
change_in_operating_assets                      DOUBLE,
depreciation_depletion_and_amortization         DOUBLE,
capital_expenditures                            DOUBLE,
change_in_receivables                           DOUBLE,
change_in_inventory                             DOUBLE,
profit_loss                                     DOUBLE,
cashflow_from_investment                        DOUBLE,
cashflow_from_financing                         DOUBLE,
proceeds_from_repayments_short_term_debt        DOUBLE,
payments_for_repurchase_common_stock            DOUBLE,
payments_for_repurchase_equity                  DOUBLE,
payments_for_repurchase_preferred_stock         DOUBLE,
dividend_payout                                 DOUBLE,
dividend_payout_common_stock                    DOUBLE,
dividend_payout_preferred_stock                 DOUBLE,
proceeds_from_issuance_common_stock             DOUBLE,
proceeds_from_issuance_long_term_debt           DOUBLE,
proceeds_from_issuance_preferred_stock          DOUBLE,
proceeds_from_repurchase_equity                 DOUBLE,
proceeds_from_sale_treasury_stock               DOUBLE,
change_in_cash_and_cash_equivalents             DOUBLE,
change_in_exchange_rate                         DOUBLE,
net_income                                      DOUBLE,
PRIMARY KEY (ticker, fiscal_date_ending, period_type)
```

#### `import_log`
```sql
id               INTEGER PRIMARY KEY,   -- auto-increment
ticker           VARCHAR NOT NULL,
run_at           TIMESTAMP NOT NULL,
success          BOOLEAN NOT NULL,
statements       VARCHAR,               -- 'income,balance,cashflow' (which succeeded)
periods_inserted INTEGER,
error_msg        VARCHAR
```

### Key Methods

```python
class AVFinancialsDB:
    def __init__(self, db_path: str = "data/av_financials.duckdb"): ...
    def close(self) -> None: ...

    # Fetch + store one ticker (3 API calls); returns rows inserted
    def import_ticker(self, ticker: str, api_key: str, limiter: RateLimiter) -> int: ...

    # Query: returns dict of DataFrames keyed by 'income' | 'balance' | 'cashflow'
    def query(
        self,
        tickers: list[str],
        statement: str = "all",       # 'income' | 'balance' | 'cashflow' | 'all'
        period_type: str = "all",     # 'annual' | 'quarterly' | 'all'
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, pd.DataFrame]: ...

    def list_tickers(self) -> list[str]: ...
    def has_ticker(self, ticker: str) -> bool: ...
```

---

## Script: `scripts/av_import.py`

### Usage

```
uv run scripts/av_import.py AAPL
uv run scripts/av_import.py --csv data/test_tickers.csv
uv run scripts/av_import.py --from-prices-db
uv run scripts/av_import.py --csv tickers.csv --force    # re-import existing tickers
uv run scripts/av_import.py AAPL --db data/custom.duckdb
```

### Behavior
- Reads `ALPHA_VANTAGE_API_KEY` and optional `AV_DB_PATH` from `.env`
- `--from-prices-db`: reads `PRICES_DB_PATH` from `.env`, queries the `stocks` table for tickers
- `--csv`: first column of CSV, header row auto-detected and skipped if non-ticker
- Without `--force`, skips tickers that already have data in the DB
- Logs per-ticker result to stdout and writes to `import_log` table
- On error for one ticker, logs and continues with the next

---

## Script: `scripts/av_query.py`

### Usage

```
uv run scripts/av_query.py AAPL
uv run scripts/av_query.py AAPL MSFT GOOGL --statement income --period annual
uv run scripts/av_query.py AAPL --start 2020-01-01 --end 2024-12-31
uv run scripts/av_query.py AAPL --statement balance --out aapl_balance.csv
```

### Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `tickers` (positional) | required | One or more ticker symbols |
| `--statement` | `all` | `income`, `balance`, `cashflow`, or `all` |
| `--period` | `all` | `annual`, `quarterly`, or `all` |
| `--start` | none | ISO date filter inclusive |
| `--end` | none | ISO date filter inclusive |
| `--out` | none | CSV path; prints to stdout if omitted |
| `--db` | from `.env` | Override DB path |

---

## Script: `scripts/av_update.py`

Refreshes all tickers in the DB with the latest data from Alpha Vantage.
Intended to be run on a cron schedule (e.g., weekly after earnings season).

### Usage

```
uv run scripts/av_update.py
uv run scripts/av_update.py --ticker AAPL      # update one specific ticker
uv run scripts/av_update.py --db data/custom.duckdb
```

### Behavior
- Queries `companies` for all known tickers (or uses `--ticker` override)
- Re-fetches all three statements per ticker (AV returns full history per call)
- Upserts via `INSERT OR REPLACE` so existing rows are overwritten with latest data
- Logs each ticker: success / new periods added / error
- Prints a summary at the end: tickers updated, total new periods, errors

---

## Logging

All three scripts use Python `logging`:
- `INFO` to stdout by default
- `DEBUG` available via `--verbose` flag
- Key events logged: ticker started, API call made, rows inserted, ticker skipped,
  ticker failed, run complete with summary stats

The `import_log` table provides a persistent audit trail per import run.

---

## Implementation Sequence

1. `av_financials_db.py` — `RateLimiter`, schema creation, `_upsert_*` helpers,
   `import_ticker`, `query`, `list_tickers`
2. `scripts/av_import.py` — single ticker, then `--csv`, then `--from-prices-db`
3. `scripts/av_query.py`
4. `scripts/av_update.py`
5. Smoke-test with 3–5 tickers before any bulk run

---

## Notes & Constraints

- AV returns `"None"` (string) for missing values; convert to Python `None` on ingest
- AV returns all numeric values as strings (e.g., `"12345"`); cast to `DOUBLE`
- Each AV financial statement call returns all available periods (no date range param)
- The update script always re-fetches full history and upserts — simpler than delta logic
- `COMPANY_OVERVIEW` is not fetched in this phase; `companies` table is populated from
  import metadata only
- No changes to `financial_statements_db.py`, `api/`, or any existing code
