# DCF Feature — Implementation Plan

## Status

**Phase 1 — COMPLETE** (2026-04-23): Backend data layer and DCF engine
**Phase 2 — COMPLETE** (2026-04-23): API endpoints
**Phase 3 — COMPLETE** (2026-04-23): Frontend (initial)
**Phase 4 — COMPLETE** (2026-04-23): Polish
**Phase 5 — COMPLETE** (2026-04-28): Granular P&L, DSO/DPO/DIO NWC, TV decomposition, UI improvements
**Phase 6 — COMPLETE** (2026-04-30): Revenue forecasting overhaul, period dates, equity bridge, XBRL fixes

---

## Current model (Phase 5)

### FCFF formula

```
EBIT   = Revenue × (1 - cogs_pct - sga_pct - rd_pct)
NOPAT  = EBIT × (1 - tax_rate)
FCFF   = NOPAT + D&A - CapEx - ΔNWC
ΔNWC   = derived from DSO/DPO/DIO working capital days model
TV     = FCFF₅ × (1 + g) / (WACC - g)   [Gordon Growth]
EV     = Σ PV(FCFF₁..₅) + PV(TV)
Equity = EV - net_debt
Price  = Equity / diluted_shares
```

### Revenue forecasting (Phase 6)

- **Y1-Y2**: blend of (a) exponentially weighted mean of annual YoY growth rates (EWM decay=0.5) and (b) quarterly momentum signal
  - Quarterly signal: EWM of last-4-quarter YoY comparisons + linear trend (acceleration), weighted 60%/40%
  - Blend: Y1 = 50% momentum + 50% annual; Y2 = 25% momentum + 75% annual
  - YTD detection: identifies filers with cumulative quarterly revenue (e.g. AAPL: 3 entries/year with resets > 35%) and groups by fiscal year before computing YoY
- **Y3-Y5**: OLS slope from combined historical + Y1/Y2 series, anchored at Y2 level
  - Anchoring prevents near-zero growth stall when momentum boosted Y1/Y2 above the historical OLS fitted line

### P&L ratio forecasting

- Forecasts 5 ratios: `cogs_pct`, `sga_pct`, `rd_pct`, `interest_pct`, `other_pct`
- Method: ARIMA(0,1,0) for years 1-2, OLS linear regression for years 3-5
- Uses annual (10-K) data only — quarterly income figures are YTD cumulative
- R&D handled gracefully: if company never reports R&D, `rd_pct` stays `None`

### Working capital (NWC)

Days-based model replaces flat NWC% assumption:
- DSO (Days Sales Outstanding) = Receivables / Revenue × 365
- DPO (Days Payable Outstanding) = Payables / COGS × 365
- DIO (Days Inventory Outstanding) = Inventory / COGS × 365
- Historical 5-yr averages computed from balance sheet; overridable in UI

### D&A sourcing

D&A sourced from cash flow statement (operating section non-cash add-back), with income statement as fallback. Most companies report D&A only in CF.

### WACC

```
ke  = rf + β_levered × MRP
kd  = interest_expense / average(total_debt)  [5yr avg, clamped 2%-15%]
D   = total_debt (balance sheet)
E   = market_cap (current_price × diluted_shares)
WACC = ke × (E/V) + kd × (1 - tax_rate) × (D/V)
```

Beta re-levering (Hamada):
```
β_unlevered = β_raw / (1 + (1 - tax_rate) × D/E_historical)
β_levered   = β_unlevered × (1 + (1 - tax_rate) × D/E_forecast_year5)
```

---

## Decisions

1. **FCF type**: FCFF confirmed.
2. **Quarterly data role**: balance sheet inputs only (WACC, DSO/DPO/DIO). Income forecasting uses annual only.
3. **Proforma display**: 5 forecast years shown as annual.
4. **Override persistence**: session-only; resets on ticker change or page reload.
5. **Override scope**:
   - Per-year: `revenue_growth`, `cogs_pct`, `sga_pct`, `rd_pct`, `interest_pct`, `other_pct`, `capex_pct_revenue`
   - Global: rf, mrp, beta, cod, tax_rate, terminal_growth_rate, dso, dpo, dio
6. **Reset**: restores all fields to model defaults without re-fetching (`useRef` pattern)
7. **Keyboard navigation**: section-scoped arrow keys; blur-formatting on exit
8. **Tab design**: simple show/hide, no new routing
9. **Charting**: Recharts; PV breakdown bar chart at bottom of DCF tab

---

## Architecture

### Backend files

```
dcf/
  __init__.py
  assumptions.py     Dataclasses: YearForecast, UserOverrides, NwcAssumptions, DcfResult
  forecaster.py      ARIMA + OLS forecasting; compute_nwc_days()
  model.py           FCFF build-up, terminal value, equity bridge, historical/proforma rows
  wacc.py            WACC, CAPM, cost of debt, Hamada; accepts cod_override, tax_rate_override
  data.py            Reads financials, stock price, DGS10

api/
  dcf_router.py      GET /dcf/{ticker}, POST /dcf/{ticker}/run
```

### Frontend files

```
web/components/
  DcfViewer.tsx       Container: state, Reset/Update, full layout
  DcfSummary.tsx      Valuation summary + editable WACC inputs (rf, mrp, beta, cod, taxRate)
  DcfStatements.tsx   Historical & proforma table; editable per-year ratios (grid arrow nav)
  DcfNwcCapex.tsx     Editable DSO/DPO/DIO; projected ΔNWC and CapEx table
  DcfFcffTable.tsx    FCFF build-up columns + terminal column + EV bridge
  DcfTerminalValue.tsx  Terminal FCFF, TV, PV(TV), TV% of EV
  DcfSensitivity.tsx  5×5 WACC × terminal growth sensitivity grid

web/lib/
  dcf-types.ts        TypeScript interfaces for all API shapes
  formatField.ts      blurFormat / focusStrip / parsePct
  useArrowNav.ts      useLinearArrowNav (WACC card) / useGridArrowNav (proforma table)
```

---

## Phase 5 changes (2026-04-28)

### Backend

- `assumptions.py`: `YearForecast` now has `cogs_pct`, `sga_pct`, `rd_pct`, `interest_pct`, `other_pct` replacing `gross_margin`/`operating_margin`; `UserOverrides` adds `dso`, `dpo`, `dio`, `cost_of_debt_override`, `tax_rate_override`; `NwcAssumptions` dataclass added; `DcfResult` adds `terminal_fcff`, `terminal_value`, `tv_pct_enterprise_value`, `nwc_assumptions`
- `forecaster.py`: forecasts 5 ratios instead of 2 margins; `compute_nwc_days()` added
- `model.py`: `_da_pct()` merges CF and income DFs, prefers CF; `_nwc_from_days()` replaces flat NWC%; `_build_fcff_series()` uses granular EBIT; TV decomposition added to result
- `wacc.py`: accepts `cost_of_debt_override` and `tax_rate_override`
- `dcf_router.py`: `YearOverrideBody` updated; `RunRequest` adds dso, dpo, dio, cost_of_debt, tax_rate

### Frontend

- New components: `DcfFcffTable.tsx`, `DcfNwcCapex.tsx`, `DcfTerminalValue.tsx`
- New lib: `formatField.ts`, `useArrowNav.ts`
- `DcfSummary.tsx`: CoD and Tax Rate now editable; linear arrow nav for WACC card
- `DcfStatements.tsx`: editable ratios now per-column in proforma; grid arrow nav; blur formatting
- `DcfViewer.tsx`: `modelDefaultsRef` for Reset without re-fetch; Reset + Update buttons; updated layout order
- `page.tsx`: auto-background 20Q import after FY; `quartersStatus` pulsing indicator; FY/Q display toggle wired to `handlePeriodTypeChange`
- `StatementViewer.tsx`: FY/Q toggle buttons added
- `ImportForm.tsx`: default periods changed from 5 to 10

---

---

## Phase 6 changes (2026-04-30)

### Backend

- `forecaster.py`: revenue forecasting completely overhauled
  - `_quarterly_momentum_signal()`: detects YTD-cumulative vs standalone quarterly pattern; computes EWM of last-4-quarter YoY comparisons blended with linear trend
  - `_rev_forecast_y1y2()`: combines annual EWM growth rate with quarterly momentum (50/25% blend)
  - Y3-Y5: `rev_slope` from OLS on historical + Y1/Y2 series, applied as `y2 + slope × step` — eliminates stall
- `model.py`: `_build_historical_rows()` re-indexed on `period_end_date` instead of positional alignment — prevents silent null CapEx when statement tables have different row counts
- `assumptions.py`: `HistoricalRow` dataclass gains `period_end_date: str | None` field
- `xbrl_mappings/cash_flow_xbrl_mapping.py`: `PaymentsToAcquireProductiveAssets` added to `capital_expenditures` list (Amazon uses this concept)

### Frontend

- `DcfStatements.tsx`: period end date shown as sub-label under historical column headers
- `DcfViewer.tsx`: "as of {date}" added to header using most-recent historical period
- `DcfFcffTable.tsx`: equity bridge extended to `∑PV FCFFs + PV Terminal = EV − Net Debt = Equity ÷ Diluted Shares = Intrinsic Value/Share`; receives `netDebt`, `equityValue`, `dilutedShares`, `intrinsicValue` props
- `StatementViewer.tsx`: period end date in column headers; shares-outstanding fields formatted without `$` prefix
- `web/lib/dcf-types.ts`: `HistoricalRow` interface gains `period_end_date: string | null`

---

## Phase 1-4 implementation sequence (historical)

1. [x] `dcf/data.py` — load financials, price, DGS10
2. [x] `dcf/assumptions.py` — dataclasses
3. [x] `dcf/wacc.py` — WACC, Hamada
4. [x] `dcf/forecaster.py` — ARIMA + OLS
5. [x] `dcf/model.py` — FCFF, TV, equity bridge, sensitivity
6. [x] `statsmodels`, `yfinance` added to pyproject.toml
7. [x] `api/dcf_router.py` — GET + POST endpoints
8. [x] `api/main.py` — router registered
9. [x] `recharts` added to web/package.json
10. [x] `web/app/page.tsx` — tab bar
11. [x] `web/components/DcfStatements.tsx`
12. [x] `web/components/DcfSummary.tsx`
13. [x] `web/components/DcfSensitivity.tsx`
14. [x] `web/components/DcfViewer.tsx`
15. [x] End-to-end verified on AAPL, NVDA, WMT
