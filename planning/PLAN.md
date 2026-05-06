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
