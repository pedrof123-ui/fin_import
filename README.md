# fin_import2

Downloads SEC EDGAR financial statements (10-K annual, 10-Q quarterly) into DuckDB. Includes a web app for single-ticker imports, a DCF valuation engine, a CLI tool for bulk imports, and a separate Alpha Vantage financial statements database.

## Architecture

- **FastAPI backend** (`api/`) — REST API for importing, querying statements, and running DCF valuations
- **Next.js frontend** (`web/`) — UI to import a ticker, view all 3 statements, switch FY/Q, DCF valuation tab
- **DuckDB** (`data/financial_statements.duckdb`) — stores income, balance sheet, and cash flow tables from SEC EDGAR
- **DuckDB** (`data/av_financials.duckdb`) — stores income, balance sheet, and cash flow tables from Alpha Vantage API
- **DCF engine** (`dcf/`) — FCFF model: EWM+momentum revenue forecasting, historical mean for P&L ratios, normalized 5-year mean for D&A and CapEx, WACC via Hamada, Gordon Growth terminal value; historical and proforma financials with EBIT, EBITDA, income tax, net income margin, and proforma EPS; Y1 quarterly breakdown (actuals + seasonality-based estimates)
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
    "1": {"revenue_growth": 0.08, "cogs_pct": 0.42, "sga_pct": 0.06, "da_pct": 0.04},
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
  "dio": 10.0,
  "y1_quarter_revenues": {"1": 95000000000, "2": 89000000000}
}
```

## DCF Model

The DCF uses FCFF (Free Cash Flow to the Firm):

```
EBIT   = Revenue × (1 - cogs_pct - sga_pct - rd_pct - other_opex_pct)
NOPAT  = EBIT × (1 - tax_rate)
FCFF   = NOPAT + D&A - CapEx - ΔNWC
ΔNWC   = derived from DSO / DPO / DIO working capital days
TV     = FCFF₅ × (1 + g) / (WACC - g)   [Gordon Growth]
EV     = Σ PV(FCFF₁..₅) + PV(TV)
```

Forecasting:
- **Revenue Y1-Y2**: exponentially weighted mean of historical annual growth rates (decay 0.5) blended with a quarterly momentum signal (EWM of last-4-quarter YoY growth + linear trend): 50% momentum / 50% annual for Y1, 25% / 75% for Y2
- **Revenue Y3-Y5**: OLS slope from combined historical + Y1-Y2 series, anchored at Y2 level (eliminates stall when momentum boosts Y1/Y2 above trend)
- **P&L ratios** (cogs_pct, sga_pct, rd_pct, interest_pct, other_opex_pct): historical mean over the 5 most recent annual periods, applied flat across all 5 forecast years. Mean-reversion is the standard DCF assumption — margins are bounded by competitive dynamics over a 5-year horizon
- **other_opex_pct**: residual between gross profit and operating income, net of SG&A and R&D already captured. Absorbs operating costs reported outside standard line items (e.g. Amazon fulfillment, technology, content). Prevents EBIT from being overstated when companies have significant operating costs not mapped to COGS/SG&A/R&D
- **D&A and CapEx**: normalized 5-year mean from the CF statement, applied flat across all growth years
- All forecasts use **annual** 10-K data; quarterly income data is used only for the momentum signal and is handled correctly for both standalone and YTD-cumulative filers
- **Historical EBIT fallback**: when `operating_income` is null in the DB (common with pharma/healthcare XBRL filers), EBIT is derived as `gross_profit − SG&A − R&D`
- **Y1 quarterly detail**: the DCF tab shows a quarterly breakdown of Y1 mixing reported actuals with seasonality-based estimates for unreported quarters. Quarterly revenue estimates can be overridden via `y1_quarter_revenues` in the run request

**WACC** (`dcf/wacc.py`):
- Cost of equity: CAPM — `ke = rf + β × MRP`. Beta from yfinance; rf from FRED DGS10; MRP defaults to 5.5% (Damodaran).
- Cost of debt: `kd = annual_interest_expense / avg_quarterly_debt`, clamped [2%, 15%]. Uses the **annual** income statement for interest expense so the full-year amount is divided by debt (not a quarterly fraction).
- Capital structure weights: market-value based (`total_debt` from latest quarterly balance sheet; `market_cap = price × diluted_shares`).
- Diluted shares: three-level fallback — quarterly income statement → annual income statement → derived from `net_income / diluted_eps`.
- Hamada equation unlever/re-lever beta at the current D/E ratio.
- `DcfResult.warnings` carries a list of data quality messages (e.g. zero market cap, WACC below 5%, terminal growth clamped). Shown as amber banners in the UI.

## Alpha Vantage Pipeline

Two databases driven by the Alpha Vantage API, both independent of the SEC EDGAR pipeline.

### .env variables

```
ALPHA_VANTAGE_API_KEY=<your premium key>
PRICES_DB_PATH=/path/to/trade_systems/data/prices.duckdb
AV_DB_PATH=data/av_financials.duckdb              # optional override
HF_DB_PATH=data/historic_fundamentals.duckdb      # optional override
```

### Adding new tickers (all-in-one)

```bash
# Fetches all AV data + computes PE history + analyst estimates in one pass
uv run scripts/add_tickers.py AAPL MSFT GOOGL

# From a CSV file
uv run scripts/add_tickers.py --csv tickers.csv
```

This is the recommended way to onboard new tickers. It populates both `av_financials.duckdb` and `historic_fundamentals.duckdb` with a single command (6 AV calls/ticker).

### Monthly update

```bash
# 1. Refresh all AV raw data (statements + shares + dividends + company overview) — ~115 min
uv run scripts/av_update.py

# 2. Recompute all derived metrics + refresh analyst estimates + sector stats — ~20 min
uv run scripts/hf_update.py
```

First-time setup: run `uv run scripts/av_import_overview.py` once after `av_update.py` to backfill company overview for all tickers (~19 min, 1 AV call/ticker).

### Query raw financials and company overview

```bash
uv run scripts/av_query.py AAPL
uv run scripts/av_query.py AAPL MSFT --statement income --period annual
uv run scripts/av_query.py AAPL --start 2020-01-01 --end 2024-12-31
uv run scripts/av_query.py AAPL --statement balance --out output.csv
uv run scripts/av_query.py AAPL --overview                   # latest company overview snapshot
uv run scripts/av_query.py AAPL --overview --history         # all monthly overview snapshots
```

### Query historic fundamentals (PE, P/FCF, EV/EBITDA, sector/industry peers, market cap, growth, estimates)

```bash
uv run scripts/hf_query.py AAPL                              # PE, P/FCF, EV/EBITDA, FCF yield, forward multiples, market cap, growth, sector peer ranks
uv run scripts/hf_query.py AAPL --view timeseries           # monthly PE, P/FCF, EV/EBITDA, FCF yield, TTM revenue/FCF/EBITDA
uv run scripts/hf_query.py AAPL --view estimates            # analyst estimates
uv run scripts/hf_query.py --all --out output.csv           # export all tickers
uv run scripts/hf_query.py --view sector                    # latest sector aggregate medians (PE, P/FCF, EV/EBITDA, yields, growth, quality)
uv run scripts/hf_query.py --view sector --group industry   # same for industry level
uv run scripts/hf_query.py --view sector-history --name TECHNOLOGY  # monthly sector timeseries
```

The rate limiter enforces the 75 calls/minute premium plan limit. Each ticker costs 6 AV calls for raw data (3 statements + shares + dividends + overview); bulk throughput is ~12 tickers/minute.

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
  forecaster.py        Historical mean for P&L ratios; normalized mean for D&A and CapEx; DSO/DPO/DIO
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
    DcfStatements.tsx    Historical & proforma table with editable forecast ratios
    DcfQuarterly.tsx     Y1 quarterly detail: actuals + seasonality estimates
    DcfNwcCapex.tsx      DSO/DPO/DIO inputs + projected NWC and CapEx per year
    DcfFcffTable.tsx     FCFF build-up table + EV bridge
    DcfTerminalValue.tsx Terminal value decomposition card
    DcfSensitivity.tsx   2D sensitivity table (WACC × terminal growth)
  lib/
    dcf-types.ts         TypeScript interfaces for all DCF data
    formatField.ts       blurFormat / focusStrip / parsePct utilities
    useArrowNav.ts       useLinearArrowNav / useGridArrowNav keyboard nav hooks
extractors/
  statement_extractor.py          Shared 2-pass extractor core (static + AI fallback)
  income_statement_extractor.py   Thin wrapper — income-specific mapping + validation
  balance_sheet_extractor.py      Thin wrapper — balance sheet
  cash_flow_extractor.py          Thin wrapper — cash flow
xbrl_mappings/         Static XBRL concept → field mappings
historic_fundamentals/         Monthly PE/P/FCF/EV/EBITDA timeseries + sector/industry peer stats + market cap + growth + analyst estimates
  __init__.py                  Public API: get_pe_stats, get_pe_history, get_estimates, get_sector_stats, get_sector_history
  db.py                        HistoricFundamentalsDB: schema (monthly_pe, pe_stats, earnings_estimates, sector_stats), upsert, query
  pe.py                        TTM EPS/FCF/EBITDA + PE/P/FCF/EV/EBITDA + dividend/revenue/earnings/FCF growth stats
  estimates.py                 EARNINGS_ESTIMATES fetch, normalize, forward PE/P/FCF/NTM revenue calculation
  sector.py                    compute_sector_stats(): monthly median/p25/p75 aggregates per sector and industry
  query.py                     Notebook-friendly wrappers: get_pe_stats() (with peer ranks), get_pe_history(), get_estimates(), get_sector_stats(), get_sector_history()
scripts/
  add_tickers.py               All-in-one: AV raw data + PE history + estimates for new tickers
  av_import.py                 Import AV financials + shares + dividends (single/CSV/prices.duckdb)
  av_import_overview.py        Backfill company overview (name, sector, industry, beta + 41 fields) for all tickers
  av_import_shares.py          Standalone backfill: shares_outstanding for existing tickers
  av_import_dividends.py       Standalone backfill: dividends for existing tickers
  av_query.py                  Query AV financial statements + company overview (--overview, --history flags)
  av_update.py                 Monthly refresh: all AV data (statements + shares + dividends + overview)
  hf_import.py                 Bulk backfill: PE history + estimates for all AV tickers
  hf_update.py                 Monthly update: recompute PE/yield + refresh estimates + sector stats (--skip-sector, --full-sector-rebuild)
  hf_query.py                  CLI query: stats, timeseries, estimates, sector, sector-history views; CSV export
  update_alpha_vantage_estimates.py  Update analyst EPS/revenue estimates from AV
xbrl_concept_mapper.py          AI-assisted fallback mapper (openai-agents)
av_financials_db.py             Alpha Vantage DB class: schema, rate limiter, fetch, upsert, query (includes company_overview)
financial_statements_db.py      SEC EDGAR DB class: schema, insert helpers, log_extraction()
bulk_import_10k.py              Core bulk import logic (async, concurrent)
run_bulk_import.py              CLI entry point for SEC EDGAR bulk imports
tests/                 pytest tests
data/
  financial_statements.duckdb       SEC EDGAR financial statements
  av_financials.duckdb              Alpha Vantage: statements, shares outstanding, dividends, company overview
  historic_fundamentals.duckdb      Monthly PE/P/FCF/EV/EBITDA timeseries, valuation stats, sector/industry aggregates, analyst estimates
  xbrl_mappings_multi.duckdb        AI-discovered XBRL concept mapping store
```
