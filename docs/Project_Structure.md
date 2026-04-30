# Project Structure

```
fin_import2/
├── api/
│   ├── main.py                          FastAPI app and route definitions
│   ├── importer.py                      Import logic: fetch SEC filings, extract, insert
│   ├── db.py                            DuckDB connection wrapper
│   └── dcf_router.py                    DCF endpoints: GET /dcf/{ticker}, POST /dcf/{ticker}/run
│
├── dcf/
│   ├── __init__.py
│   ├── assumptions.py                   Dataclasses: YearForecast, UserOverrides, NwcAssumptions, DcfResult
│   ├── forecaster.py                    ARIMA(0,1,0) + OLS forecasting for P&L ratios; DSO/DPO/DIO
│   ├── model.py                         FCFF build-up, terminal value, equity bridge, historical rows
│   ├── wacc.py                          WACC, CAPM, cost of debt, Hamada beta re-levering
│   └── data.py                          Loads financials, stock price, DGS10 from DuckDB databases
│
├── web/                                 Next.js frontend (port 3000)
│   ├── app/
│   │   ├── page.tsx                     Main UI: import form, Financials + DCF Valuation tabs
│   │   └── layout.tsx
│   ├── components/
│   │   ├── ImportForm.tsx               Ticker input, period selector (default 10 FY), import button
│   │   ├── StatementViewer.tsx          Financials table with FY/Q display toggle
│   │   ├── DcfViewer.tsx                DCF container: state, Reset/Update buttons, layout
│   │   ├── DcfSummary.tsx               Valuation summary card + editable WACC inputs (rf, mrp, beta, cod, tax)
│   │   ├── DcfStatements.tsx            Historical & proforma P&L/BS/CF table; editable forecast ratios
│   │   ├── DcfNwcCapex.tsx              Editable DSO/DPO/DIO inputs; projected ΔNWC and CapEx per year
│   │   ├── DcfFcffTable.tsx             FCFF build-up (Revenue→EBIT→NOPAT→+D&A→-CapEx→-ΔNWC→FCFF→PV)
│   │   ├── DcfTerminalValue.tsx         Terminal value decomposition: FCFF₅, TV, PV(TV), TV% of EV
│   │   ├── DcfSensitivity.tsx           2D sensitivity table: intrinsic value vs WACC × terminal growth
│   │   └── ui/                          shadcn/ui primitives (Button, Input, Select)
│   └── lib/
│       ├── dcf-types.ts                 TypeScript interfaces for all DCF API shapes
│       ├── formatField.ts               blurFormat / focusStrip / parsePct utilities
│       ├── useArrowNav.ts               useLinearArrowNav (1D) / useGridArrowNav (2D) keyboard nav hooks
│       └── utils.ts                     Tailwind class merge helper
│
├── extractors/
│   ├── statement_extractor.py           Shared 2-pass extractor core (all 3 statement types)
│   ├── income_statement_extractor.py    Thin wrapper: income mapping, validation helpers
│   ├── balance_sheet_extractor.py       Thin wrapper: balance sheet mapping
│   └── cash_flow_extractor.py           Thin wrapper: cash flow mapping
│
├── xbrl_mappings/
│   ├── income_statement_xbrl_mapping.py Static XBRL concept → field mappings (30 fields)
│   ├── balance_sheet_xbrl_mapping.py    (37 fields)
│   └── cash_flow_xbrl_mapping.py        (31 fields; includes PaymentsToAcquireProductiveAssets for Amazon)
│
├── tests/
│   ├── conftest.py                      Mocks openai-agents submodules for fast tests
│   └── test_api.py                      API tests (fast + integration)
│
├── data/
│   ├── financial_statements.duckdb      Main DuckDB database
│   └── xbrl_mappings_multi.duckdb       AI-discovered concept mapping store
│
├── docs/
│   ├── Project_Structure.md             This file
│   ├── BULK_IMPORT_GUIDE.md             Bulk import CLI reference
│   └── MULTI_STATEMENT_EXTRACTOR_GUIDE.md  Extractor internals
│
├── features/
│   └── dcf/
│       ├── VISION.md                    Original DCF feature vision
│       └── PLAN.md                      DCF implementation plan and status
│
├── planning/
│   └── PLAN.md                          Overall project plan
│
├── financial_statements_db.py           DuckDB schema definition and insert helpers
├── xbrl_concept_mapper.py               AI fallback mapper (openai-agents)
├── xbrl_mapping_manager_multi_statement.py  XBRL mapping persistence
├── bulk_import_10k.py                   Core async bulk import logic (concurrent tickers)
├── run_bulk_import.py                   CLI entry point for bulk imports
├── pyproject.toml                       Dependencies and pytest config
└── CLAUDE.md                            Coding standards
```

## Data flow

### Web app import

1. User submits ticker + period_type (FY/Q) + periods (default: 10 FY) in browser
2. `POST /import` → `api/importer.py:import_ticker()`
3. Fetches 10-K or 10-Q filings from SEC EDGAR via `edgartools`
   - Uses `company.latest(form)` for single-filing imports (zero extra network cost)
   - Falls back to `company.get_filings(form=form)[:periods]` for multi-period
4. For each filing, calls all 3 extractors (income, balance, cash flow)
5. Each extractor runs 2 passes:
   - Pass 1: static XBRL concept matching via `xbrl_mappings/`
   - Pass 2 (optional): AI batch resolution for unfound fields
6. XBRL values extracted with `presentation=False` (raw values, consistent signs across companies)
7. Results upserted into DuckDB via `INSERT OR REPLACE INTO`
8. After FY import succeeds, the browser fires a background `POST /import` for 20 quarters (non-blocking)

### DCF valuation

1. `GET /dcf/{ticker}` → `api/dcf_router.py`
2. `dcf/data.py` loads last 10 annual + 20 quarterly rows from all 3 statement tables; fetches current price; loads DGS10 from fred.duckdb
3. `dcf/forecaster.py` forecasts revenue (EWM annual growth blended with quarterly momentum signal for Y1-Y2; OLS slope anchored at Y2 for Y3-Y5) and 5 P&L ratios (ARIMA(0,1,0) Y1-Y2, OLS Y3-Y5); computes DSO/DPO/DIO from historical balance sheets
4. `dcf/wacc.py` downloads beta via yfinance; Hamada unlever/re-lever; computes ke, kd, WACC
5. `dcf/model.py` builds FCFF series: EBIT → NOPAT → +D&A → -CapEx → -ΔNWC (days-based); discounts; Gordon Growth terminal value; equity bridge
6. Returns `DcfResult` with historical rows, proforma rows, FCFF series, WACC detail, sensitivity grid, terminal value decomposition
7. `POST /dcf/{ticker}/run` accepts per-year and global overrides, re-runs from step 5

### Bulk import (CLI)

1. `run_bulk_import.py` parses CLI args, prompts for confirmation
2. Calls `bulk_import_10k.bulk_import_10k()` with form=10-K or 10-Q
3. Processes up to N tickers concurrently (default 3) via `asyncio.Semaphore`
4. edgartools' built-in rate limiter handles SEC's 9 req/s limit per-request
5. Writes summary reports to `bulk_import_results/`

## Extractor architecture

All three extractors share a single core in `extractors/statement_extractor.py`:

```
extract_statement()          ← shared core
├── get XBRL from filing     (presentation=False for raw values)
├── detect date columns      (handles "(FY)"/"(Q1)"/"(YTD)" suffixes)
├── Pass 1: _extract_value() for each field in mapping
│   ├── aggregation_fields   → sum multiple matching concepts (e.g. SG&A components)
│   ├── max_fields           → take max across matches (e.g. Revenues vs RFCWCEA)
│   └── default              → first match wins
└── Pass 2: AI batch fallback (optional)

extract_income_statement()   ← thin wrapper, defines _AGG_FIELDS, _MAX_FIELDS, _ALT_NAMES
extract_balance_sheet()      ← thin wrapper
extract_cash_flow()          ← thin wrapper
```

The `max_fields` mechanism prevents revenue understatement when a company reports both a
specific concept (e.g. `RevenueFromContractWithCustomerExcludingAssessedTax`) and a broader
aggregate (`Revenues`). The larger value is always the correct total.

D&A is sourced primarily from the cash flow statement (operating section non-cash add-back),
with income statement as fallback. Most companies report D&A in CF, not IS.

## DCF model detail

**FCFF formula**

```
EBIT   = Revenue × (1 - cogs_pct - sga_pct - rd_pct)
NOPAT  = EBIT × (1 - tax_rate)
FCFF   = NOPAT + D&A - CapEx - ΔNWC
ΔNWC   = Receivables(t) + Inventory(t) - Payables(t)
         - Receivables(t-1) - Inventory(t-1) + Payables(t-1)
         where Receivables = Revenue × DSO/365
               Inventory   = COGS × DIO/365
               Payables    = COGS × DPO/365
TV     = FCFF₅ × (1 + g) / (WACC - g)
EV     = Σ PV(FCFF₁..₅) + PV(TV)
Equity = EV - net_debt
Price  = Equity / diluted_shares
```

**Forecasting (annual data only)**

| Metric | Method |
|--------|--------|
| revenue Y1-Y2 | EWM annual growth + quarterly momentum signal (50%/25% blend) |
| revenue Y3-Y5 | OLS slope anchored at Y2 (avoids stall when momentum > trend) |
| cogs_pct, sga_pct, rd_pct, interest_pct, other_pct | ARIMA(0,1,0) Y1-Y2, OLS Y3-Y5 |
| D&A %, CapEx % | historical 5-yr average |
| DSO, DPO, DIO | historical 5-yr average from balance sheet |

R&D: if a company never reports R&D, `rd_pct` stays `None` throughout (shown as blank in UI).

**Editable assumptions (UI)**

Global: risk-free rate, market risk premium, beta, cost of debt, tax rate, terminal growth rate, DSO, DPO, DIO

Per-year: revenue_growth, cogs_pct, sga_pct, rd_pct, interest_pct, other_pct, capex_pct_revenue

Reset button restores all inputs to model-computed defaults without re-fetching.

## Database tables

| Table | Key columns |
|-------|-------------|
| `income_statements` | ticker, period_end_date, fiscal_year, period_type, revenue, gross_profit, net_income, ... |
| `balance_sheets` | ticker, period_end_date, fiscal_year, period_type, total_assets, total_debt, ... |
| `cash_flow_statements` | ticker, period_end_date, fiscal_year, period_type, operating_cash_flow, capital_expenditures, depreciation_amortization, ... |

All tables use `INSERT OR REPLACE INTO` keyed on `(ticker, filing_date, period_end_date)` for atomic upserts.
