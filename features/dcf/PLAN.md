# DCF Feature — Implementation Plan

## Status

**Phase 1 — COMPLETE** (2026-04-23)
**Phase 2 — not started**
**Phase 3 — not started**
**Phase 4 — not started**

---

## Recommendations to Improve the VISION

Before the questions and plan, a few improvements worth discussing:

1. **Use FCFF, not FCFE.** The VISION does not specify which free cash flow definition to use.
   FCFF (Free Cash Flow to the Firm) is the standard choice for multi-year DCF because it
   separates operating value from capital structure. Formula:
   `FCFF = EBIT × (1 - tax_rate) + D&A - CapEx - ΔNWC`
   Then subtract net debt at the end to get equity value. FCFE is harder to model reliably
   when leverage changes over the forecast period.

2. **Specify SARIMAX for the time series model.** "statsmodel time series models" is vague.
   For quarterly financial data, SARIMAX with seasonal period=4 is the appropriate choice.
   It captures both trend and quarterly seasonality (e.g., retail Q4 spikes). The model
   should be fitted per-metric independently.

3. **Add a sensitivity table.** Standard DCF practice includes a 2D sensitivity table of
   intrinsic value vs (WACC × terminal growth rate). This is more useful than a single
   point estimate and easy to implement once the core model works.

4. **Re-lever the yfinance beta.** Beta from yfinance is the levered beta of the current
   capital structure. If the company's leverage changes in the forecast, re-levering
   (Hamada equation) gives a more accurate cost of equity. Recommend: unlever the raw
   beta, then re-lever with the forecast D/E ratio.

5. **Set an explicit terminal growth rate default.** The VISION says "use the last year for
   steady-state terminal value" but does not specify a terminal growth rate. Recommend
   defaulting to 2.5% (approximate long-run nominal GDP growth) with user override.

6. **Minimum data guard.** If a company has fewer than 8 quarters of history, the SARIMAX
   model will produce poor results. Recommend requiring at least 8 quarterly periods (or
   4 annual) and surfacing a clear error if data is insufficient.

---

## Decisions

1. **FCF type**: FCFF confirmed.
2. **Quarterly data required**: The DCF requires at least 8 quarterly periods imported for
   WACC balance sheet data. However, income forecasting uses **annual** data (see note below).
3. **Proforma display**: All 5 proforma years shown as annual in the table.
4. **Override persistence**: Session-only. Overrides reset on ticker change or page reload.
5. **Override scope**: Per-year overrides for valuation assumptions only:
   revenue growth rate, gross margin, operating margin, CapEx % of revenue.
   WACC inputs (risk-free rate, MRP, beta) are global overrides, not per-year.
6. **Tab design**: Simple show/hide tab bar, no new routing.
7. **Charting**: Recharts added for FCFF bar chart and sensitivity table.

### Implementation note: forecasting uses annual data, not quarterly

US SEC 10-Q filings report income statement items as YTD cumulative figures (e.g. the Q2
filing shows 6-month year-to-date revenue, not standalone Q2 revenue). Companies also
file only 3 quarterly 10-Qs per year, with the Q4/full-year in the 10-K. This means
quarterly income series cover only 9 months per year and cannot be reliably summed to
annual. The forecaster therefore uses annual 10-K data for all income forecasting:
- Years 1-2: ARIMA(0,1,0) with trend on annual revenue levels; same for margin ratios.
- Years 3-5: OLS linear regression on (historical annual + Y1/Y2 ARIMA forecasts).
Quarterly data is still required and used for WACC capital structure (balance sheet
items are point-in-time, not cumulative, so they are safe to use directly).

---

## Architecture

### Directory structure

```
dcf/
  __init__.py
  forecaster.py          # SARIMAX + linear regression forecasting
  wacc.py                # WACC, CAPM, cost of debt, beta handling
  model.py               # FCF construction, terminal value, NPV discounting
  assumptions.py         # Default assumptions, user override merging
  data.py                # Reads from financial_statements.duckdb, prices.duckdb, fred.duckdb

api/
  dcf_router.py          # FastAPI router — GET /dcf/{ticker}, POST /dcf/{ticker}/run
  main.py                # (modified) register dcf_router

web/components/
  DcfViewer.tsx          # Main DCF container (tab content)
  DcfAssumptions.tsx     # Editable table: growth rates, margins, WACC inputs
  DcfSummary.tsx         # Valuation summary card: intrinsic value vs current price
  DcfStatements.tsx      # Historical + proforma statements table (reuses StatementViewer styling)
  DcfSensitivity.tsx     # 2D sensitivity table (WACC × terminal growth)

web/app/
  page.tsx               # (modified) add tab bar: "Financials" | "DCF Valuation"
```

### Data flow

```
GET /dcf/{ticker}
  └─ data.py: load last 5 annual / 20 quarterly from financial_statements.duckdb
  └─ data.py: load latest price from prices.duckdb
  └─ data.py: load DGS10 from fred.duckdb (latest value)
  └─ yfinance: download beta for ticker
  └─ forecaster.py: SARIMAX forecast Q1-Q8 per metric; linear regression Q9-Q20 (Y3-Y5)
  └─ model.py: compute historical FCFF, project FCFF for years 1-5, terminal value, NPV
  └─ wacc.py: compute WACC from beta, rf, MRP, kd, D/E
  └─ return: assumptions{}, historical[], proforma[], valuation{}, wacc_detail{}

POST /dcf/{ticker}/run  (with override body)
  └─ same as above, but override assumptions with user-supplied values before discounting
```

### API response schema (sketch)

```python
class DcfResponse(BaseModel):
    ticker: str
    intrinsic_value_per_share: float
    current_price: float
    upside_pct: float

    wacc_detail: WaccDetail       # beta, rf, MRP, ke, kd, tax_rate, D_weight, E_weight, wacc
    assumptions: DcfAssumptions   # growth rates, margins, terminal_growth per year + terminal

    historical: list[StatementRow]   # last 5 years: IS + BS + CF relevant lines
    proforma: list[StatementRow]     # 5 forecast years: same line items
    fcff_series: list[FcffRow]       # year, revenue, ebit, fcff, discount_factor, pv_fcff
    sensitivity: list[SensitivityRow]  # wacc × terminal_growth grid
```

### DCF model detail

**Forecast stage (forecaster.py)**

Input: quarterly `income_statements`, `balance_sheets`, `cash_flow_statements` for the ticker.

Metrics forecast via SARIMAX (order and seasonal order auto-selected by AIC):
- `revenue`, `operating_income`, `net_income`, `depreciation_amortization`,
  `capital_expenditures`, `net_change_in_working_capital` (derived from BS deltas)

Forecast horizon: 8 quarters (years 1-2) via SARIMAX, then aggregate to annual.

Years 3-5: linear regression on the annual SARIMAX output to extrapolate trend.

**FCFF construction (model.py)**

```
EBIT         = operating_income
NOPAT        = EBIT × (1 - effective_tax_rate)
FCFF         = NOPAT + D&A - CapEx - ΔNWC
```

Effective tax rate = `income_tax_expense / pretax_income` (5-year average, clamped to [15%, 40%]).

**WACC (wacc.py)**

```
ke  = rf + β_levered × MRP
kd  = interest_expense / average(short_term_debt + long_term_debt)  [5yr avg, clamped 2%-15%]
D   = total_debt (balance sheet)
E   = market_cap (current_price × diluted_shares)
V   = D + E
WACC = ke × (E/V) + kd × (1 - tax_rate) × (D/V)
```

Beta levering/unlevering (Hamada):
```
β_unlevered = β_raw / (1 + (1 - tax_rate) × D/E_historical)
β_levered   = β_unlevered × (1 + (1 - tax_rate) × D/E_forecast_year5)
```

**Terminal value**

Gordon Growth Model:
```
TV = FCFF₅ × (1 + g_terminal) / (WACC - g_terminal)
PV_TV = TV / (1 + WACC)^5
```

**Equity value**

```
Enterprise_Value = sum(PV_FCFF₁..₅) + PV_TV
Equity_Value     = Enterprise_Value - net_debt
                   where net_debt = total_debt - cash_and_equivalents
Price_per_share  = Equity_Value / diluted_shares_outstanding
```

**Defaults (assumptions.py)**

| Parameter | Default | Source |
|-----------|---------|--------|
| Market Risk Premium | 5.5% | hardcoded (Damodaran estimate) |
| Terminal growth rate | 2.5% | hardcoded |
| Min tax rate | 15% | hardcoded |
| Max tax rate | 40% | hardcoded |
| Risk-free rate | DGS10 latest | fred.duckdb |
| Beta | raw levered | yfinance |

All defaults overridable by user in the UI.

### Frontend components

**Tab bar** (added to `page.tsx`)

A simple two-button tab bar matching the existing header style — no new routing needed:
```
[  Financials  ]  [  DCF Valuation  ]
```
`activeTab` state drives which component renders in `<main>`.

**DcfViewer.tsx**

Layout:
```
[ Valuation Summary card ]  [ WACC Assumptions card ]

[ Historical + Proforma statements table ]  (same visual style as StatementViewer)

[ FCFF chart — bar chart of PV(FCFF) by year + PV(TV) ]  (Recharts)

[ Sensitivity table ]  (2D grid)

[ Editable Assumptions panel ]  (collapsible)
```

**DcfAssumptions.tsx**

Editable table rows: one row per forecast year + terminal row.
Columns: Year | Revenue Growth | EBIT Margin | D&A % Rev | CapEx % Rev | NWC % Rev

Each cell is a text input; on blur, re-POSTs to `/dcf/{ticker}/run` with overrides.

---

## Implementation sequence

### Phase 1 — Backend data layer and DCF engine (Python, no UI) — COMPLETE

1. [x] Create `dcf/data.py`: helpers to load historical financials, price, DGS10 from all three databases.
2. [x] Create `dcf/assumptions.py`: dataclasses for `UserOverrides`, `YearForecast`, `WaccDetail`, `FcffYear`, `DcfResult`.
3. [x] Create `dcf/wacc.py`: WACC calculation; yfinance beta download; Hamada re-levering.
4. [x] Create `dcf/forecaster.py`: ARIMA on annual data (Y1-Y2) + linear regression (Y3-Y5); override merging.
5. [x] Create `dcf/model.py`: FCFF construction, terminal value, equity value per share, sensitivity grid.
6. [x] Add `statsmodels>=0.14.0` and `yfinance>=0.2.0` to `pyproject.toml` and install.
7. [x] Validate end-to-end on AAPL and NVDA; confirmed WACC, FCF series, sensitivity table all produce
       finite, plausible values. Override flow tested and working.

### Phase 2 — API endpoints

8. Create `api/dcf_router.py`:
   - `GET /dcf/{ticker}` — compute DCF with model defaults; returns full `DcfResult` as JSON.
   - `POST /dcf/{ticker}/run` — body contains `UserOverrides`; re-runs DCF and returns updated result.
9. Register router in `api/main.py` (one line: `app.include_router(dcf_router)`).
10. Test both endpoints manually (curl or httpie).

### Phase 3 — Frontend

11. Add `recharts` to `web/package.json` via `npm install recharts`.
12. Add tab bar to `web/app/page.tsx` — two-button toggle: "Financials" | "DCF Valuation".
13. Create `web/components/DcfStatements.tsx` — historical (5yr) + proforma (5yr) table,
    same visual style as `StatementViewer`.
14. Create `web/components/DcfSummary.tsx` — intrinsic vs price card + WACC detail breakdown.
15. Create `web/components/DcfAssumptions.tsx` — editable per-year grid:
    Year | Rev Growth | Gross Margin | Op Margin | CapEx% + global WACC overrides (RF, MRP, beta).
16. Create `web/components/DcfSensitivity.tsx` — 5×5 WACC × terminal growth grid.
17. Create `web/components/DcfViewer.tsx` — assembles all sub-components; manages override state;
    calls `GET /dcf/{ticker}` on load and `POST /dcf/{ticker}/run` on any assumption change.
18. Wire `DcfViewer` into `page.tsx` under the DCF tab.

### Phase 4 — Polish

19. Add Recharts stacked bar chart inside `DcfViewer` for PV(FCFF) by year + PV(TV).
20. Loading states (skeleton/opacity) and error display for insufficient quarterly data.
21. Test full flow end-to-end in browser across AAPL and NVDA.

---

## Dependencies

Python (added to `pyproject.toml` and installed):
- `statsmodels>=0.14.0` — ARIMA forecasting
- `yfinance>=0.2.0` — beta download

Node (not yet installed):
- `recharts` — FCFF bar chart (install via `npm install recharts` in `web/`)

---

## Files — status

| File | Status |
|------|--------|
| `dcf/__init__.py` | done |
| `dcf/data.py` | done |
| `dcf/assumptions.py` | done |
| `dcf/wacc.py` | done |
| `dcf/forecaster.py` | done |
| `dcf/model.py` | done |
| `pyproject.toml` | done — statsmodels + yfinance added |
| `api/dcf_router.py` | **TODO** |
| `api/main.py` | **TODO** — register router |
| `web/app/page.tsx` | **TODO** — add tab bar |
| `web/components/DcfViewer.tsx` | **TODO** |
| `web/components/DcfStatements.tsx` | **TODO** |
| `web/components/DcfSummary.tsx` | **TODO** |
| `web/components/DcfAssumptions.tsx` | **TODO** |
| `web/components/DcfSensitivity.tsx` | **TODO** |
| `web/package.json` | **TODO** — add recharts |
