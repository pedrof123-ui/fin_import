# fin_import2

Downloads SEC EDGAR financial statements (10-K annual, 10-Q quarterly) into DuckDB. Includes a web app for single-ticker imports, a DCF valuation engine, and a CLI tool for bulk imports.

## Architecture

- **FastAPI backend** (`api/`) — REST API for importing, querying statements, and running DCF valuations
- **Next.js frontend** (`web/`) — UI to import a ticker, view all 3 statements, switch FY/Q, DCF valuation tab
- **DuckDB** (`data/financial_statements.duckdb`) — stores income, balance sheet, and cash flow tables
- **DCF engine** (`dcf/`) — FCFF model: EWM+momentum revenue forecasting, ARIMA+OLS ratio forecasting, WACC via Hamada, Gordon Growth terminal value; historical and proforma financials with EBIT, EBITDA, income tax, net income margin, and proforma EPS
- **Bulk import CLI** (`run_bulk_import.py`) — batch-imports many tickers from a CSV with concurrent processing

## Quick Start

### Web app

```bash
# Terminal 1 — backend (port 8000)
uv run uvicorn api.main:app --reload

# Terminal 2 — frontend (port 3000)
cd web && npm run dev
```

Open http://localhost:3000, enter a ticker, set periods (default: 10 FY), click Import.

Importing FY data automatically downloads up to 20 quarters in the background. Switch the display between annual and quarterly using the FY / Q toggle in the Financials table.

### Bulk import (CLI)

```bash
# Annual (default), last 20 filings
uv run run_bulk_import.py tickers.csv

# Quarterly, last 8 quarters
uv run run_bulk_import.py tickers.csv --quarterly --periods 8

# Annual, 10 years, AI fallback for better XBRL coverage
uv run run_bulk_import.py tickers.csv --periods 10 --ai

# 5 tickers in parallel (default: 3)
uv run run_bulk_import.py tickers.csv --concurrency 5
```

CSV format — any of these column names work: `ticker`, `symbol`, `stock`. First column used if none found.

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tickers` | List all tickers in DB |
| `POST` | `/import` | Import a ticker from SEC EDGAR |
| `GET` | `/statements/{ticker}/{type}` | Query statements (type: `income`, `balance`, `cashflow`) |
| `GET` | `/dcf/{ticker}` | Run DCF with model defaults |
| `POST` | `/dcf/{ticker}/run` | Re-run DCF with user-supplied overrides |

Import request body:
```json
{"ticker": "AAPL", "periods": 10, "period_type": "FY"}
```
`period_type` is `"FY"` (annual 10-K) or `"Q"` (quarterly 10-Q).

Statement query params: `?period_type=FY&periods=10`

DCF run override body (all fields optional):
```json
{
  "years": {
    "1": {"revenue_growth": 0.08, "cogs_pct": 0.42, "sga_pct": 0.06},
    "2": {"revenue_growth": 0.07}
  },
  "terminal_growth_rate": 0.025,
  "risk_free_rate": 0.043,
  "market_risk_premium": 0.055,
  "beta": 1.2,
  "cost_of_debt": 0.04,
  "tax_rate": 0.21,
  "dso": 45.0,
  "dpo": 60.0,
  "dio": 10.0
}
```

## DCF Model

The DCF uses FCFF (Free Cash Flow to the Firm):

```
EBIT   = Revenue × (1 - cogs_pct - sga_pct - rd_pct)
NOPAT  = EBIT × (1 - tax_rate)
FCFF   = NOPAT + D&A - CapEx - ΔNWC
ΔNWC   = derived from DSO / DPO / DIO working capital days
TV     = FCFF₅ × (1 + g) / (WACC - g)   [Gordon Growth]
EV     = Σ PV(FCFF₁..₅) + PV(TV)
```

Forecasting:
- **Revenue Y1-Y2**: exponentially weighted mean of historical annual growth rates (decay 0.5) blended with a quarterly momentum signal (EWM of last-4-quarter YoY growth + linear trend): 50% momentum / 50% annual for Y1, 25% / 75% for Y2
- **Revenue Y3-Y5**: OLS slope from combined historical + Y1-Y2 series, anchored at Y2 level (eliminates stall when momentum boosts Y1/Y2 above trend)
- **P&L ratios** (cogs_pct, sga_pct, rd_pct, interest_pct, other_pct): ARIMA(0,1,0) for years 1-2, OLS for years 3-5
- All forecasts use **annual** 10-K data; quarterly income data is used only for the momentum signal and is handled correctly for both standalone and YTD-cumulative filers

**WACC** (`dcf/wacc.py`):
- Cost of equity: CAPM — `ke = rf + β × MRP`. Beta from yfinance; rf from FRED DGS10; MRP defaults to 5.5% (Damodaran).
- Cost of debt: `kd = annual_interest_expense / avg_quarterly_debt`, clamped [2%, 15%]. Uses the **annual** income statement for interest expense so the full-year amount is divided by debt (not a quarterly fraction).
- Capital structure weights: market-value based (`total_debt` from latest quarterly balance sheet; `market_cap = price × diluted_shares`).
- Diluted shares: three-level fallback — quarterly income statement → annual income statement → derived from `net_income / diluted_eps`.
- Hamada equation unlever/re-lever beta at the current D/E ratio.
- `DcfResult.warnings` carries a list of data quality messages (e.g. zero market cap, WACC below 5%, terminal growth clamped). Shown as amber banners in the UI.

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
--delay SECS      Extra seconds between SEC requests (default: 0; edgartools has built-in rate limiter)
--concurrency N   Tickers to process in parallel (default: 3)
--output DIR      Reports directory (default: ./bulk_import_results)
--log FILE        Log file (default: bulk_import.log)
```

## Project layout

```
api/
  main.py              FastAPI app, routes
  importer.py          Import logic (fetch SEC filings, extract, insert)
  db.py                DuckDB connection wrapper
  dcf_router.py        DCF endpoints (GET /dcf/{ticker}, POST /dcf/{ticker}/run)
dcf/
  assumptions.py       Dataclasses: YearForecast, UserOverrides, DcfResult, NwcAssumptions, HistoricalRow
  forecaster.py        ARIMA + OLS forecasting for P&L ratios; DSO/DPO/DIO computation
  model.py             FCFF construction, terminal value, equity bridge
  wacc.py              WACC, CAPM, cost of debt, Hamada beta re-levering
  data.py              Reads from financial_statements.duckdb, prices.duckdb, fred.duckdb
web/                   Next.js frontend (port 3000)
  app/page.tsx         Main page: import form, Financials + DCF tabs
  components/
    ImportForm.tsx       Ticker input, period selector, import button
    StatementViewer.tsx  Financials table with FY/Q toggle
    DcfViewer.tsx        DCF container: state management, Reset/Update actions
    DcfSummary.tsx       Valuation summary + editable WACC inputs
    DcfStatements.tsx    Historical & proforma table: EBIT, EBITDA, income tax (effective rate), net income (margin), EPS; editable forecast ratios
    DcfNwcCapex.tsx      DSO/DPO/DIO inputs + projected NWC and CapEx per year
    DcfFcffTable.tsx     FCFF build-up table (Revenue→EBIT→NOPAT→FCFF→PV) + EV bridge
    DcfTerminalValue.tsx Terminal value decomposition card
    DcfSensitivity.tsx   2D sensitivity table (WACC × terminal growth)
  lib/
    dcf-types.ts         TypeScript interfaces for all DCF data
    formatField.ts       blurFormat / focusStrip / parsePct utilities
    useArrowNav.ts       useLinearArrowNav / useGridArrowNav keyboard nav hooks
extractors/
  statement_extractor.py   Shared 2-pass extractor core (static + AI fallback)
  income_statement_extractor.py   Thin wrapper — income-specific mapping + validation
  balance_sheet_extractor.py      Thin wrapper — balance sheet
  cash_flow_extractor.py          Thin wrapper — cash flow
xbrl_mappings/         Static XBRL concept → field mappings
xbrl_concept_mapper.py AI-assisted fallback mapper (openai-agents)
financial_statements_db.py  DuckDB schema + insert helpers
bulk_import_10k.py     Core bulk import logic (async, concurrent)
run_bulk_import.py     CLI entry point for bulk imports
tests/                 pytest tests
data/                  DuckDB database files
```
