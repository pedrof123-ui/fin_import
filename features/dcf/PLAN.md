# DCF — AV Tabs Implementation Plan

## Scope

Add two new tabs to the DCF app:

1. **AV Financials** — mirrors the existing Financials tab (income / balance / cashflow sub-tabs + FY/Q toggle) but sourced from `av_financials.duckdb`
2. **AV DCF** — fully interactive DCF (same UI as the existing DCF tab) powered by Alpha Vantage data, with terminal growth defaulting to the median of all historical annual revenue growth rates

Both tabs show a clear error when AV data is not yet imported for the ticker.  
The existing DCF tab and its defaults are unchanged.

---

## Architecture overview

```
av_financials.duckdb
       │
       ├── dcf/av_data.py          column-mapping adapter (new)
       │         │
       │         └── dcf/model.py  _run_dcf_core() extracted (refactor)
       │                 │         run_dcf_av() added (new)
       │
       ├── api/av_router.py        GET /av-financials/{ticker}/{stmt}   (new)
       │                           GET /av-dcf/{ticker}                 (new)
       │                           POST /av-dcf/{ticker}/run            (new)
       │
       └── web/
             ├── page.tsx              two new Tab literals + renders
             ├── AvFinancialsViewer.tsx  statement table (new)
             └── DcfViewer.tsx          add optional apiPath prop
```

---

## Phase 1 — Backend: AV data adapter (`dcf/av_data.py`)

**What it does**: loads from `av_financials.duckdb` and returns DataFrames with the column names the DCF engine already expects.

**New file**: `dcf/av_data.py`

### AV → DCF column mapping

| Statement | AV column | DCF engine expects |
|---|---|---|
| income | `fiscal_date_ending` | `period_end_date` |
| income | `total_revenue` | `revenue` |
| income | `selling_general_and_administrative` | `selling_general_admin` |
| income | `research_and_development` | `research_development` |
| income | `income_before_tax` | `pretax_income` |
| income | `depreciation_and_amortization` | `depreciation_amortization` |
| balance | `cash_and_cash_equivalents` | `cash_and_equivalents` |
| balance | `current_net_receivables` | `accounts_receivable` |
| balance | `current_accounts_payable` | `accounts_payable` |
| balance | `current_long_term_debt` | `current_portion_long_term_debt` |
| balance | `long_term_debt_noncurrent` | `long_term_debt` |
| cashflow | `depreciation_depletion_and_amortization` | `depreciation_amortization` |
| cashflow | `capital_expenditures` | (same — no rename needed) |

Note: AV stores `period_type` as `'annual'`/`'quarterly'` (lowercase). The adapter normalises to `'Annual'`/`'Quarterly'` so no downstream change is needed.

### Diluted shares

AV income statements do not carry `diluted_shares` or `diluted_eps`. The `shares_outstanding` table exists in the schema but is never populated by `import_ticker` (no dedicated AV API call). The adapter therefore uses:

- `common_stock_shares_outstanding` from the balance sheet row (basic shares, not diluted)

This slightly overstates intrinsic value per share because basic < diluted. The error is typically 1–5%:
- AAPL: ~0.7% | NVDA: ~1.2% | high-SBC companies: up to ~4%

`diluted_eps` = `net_income / common_stock_shares_outstanding` (computed in the adapter).

### Functions exported

```python
AV_DB = Path(os.environ.get("AV_FINANCIALS_DB_PATH", ROOT / "data" / "av_financials.duckdb"))

def load_av_annual_financials(ticker: str) -> dict[str, pd.DataFrame]:
    """Returns dict with keys 'income', 'balance', 'cashflow'.
    Columns renamed to match DCF engine expectations. Sorted newest→oldest."""

def load_av_quarterly_financials(ticker: str) -> dict[str, pd.DataFrame]:
    """Same as above for quarterly data. Raises ValueError if < 8 periods."""
```

### Minimum period check

Same as existing: raise `ValueError` if quarterly income has fewer than 8 rows.

---

## Phase 2 — Backend: refactor `dcf/model.py` + add `run_dcf_av`

### Extract `_run_dcf_core`

Current `run_dcf(ticker, db, overrides)` loads data and runs the model in one function.  
Refactor into:

```python
def run_dcf(ticker: str, db, overrides: UserOverrides | None = None) -> DcfResult:
    quarterly = load_quarterly_financials(db, ticker)
    annual    = load_annual_financials(db, ticker)
    return _run_dcf_core(ticker, annual, quarterly, overrides)

def _run_dcf_core(
    ticker: str,
    annual: dict[str, pd.DataFrame],
    quarterly: dict[str, pd.DataFrame],
    overrides: UserOverrides | None,
) -> DcfResult:
    # everything that currently lives inside run_dcf after data loading
    ...
```

The public API of `run_dcf` is unchanged — existing router works without modification.

### Add `run_dcf_av`

```python
def run_dcf_av(ticker: str, overrides: UserOverrides | None = None) -> DcfResult:
    from dcf.av_data import load_av_annual_financials, load_av_quarterly_financials
    quarterly = load_av_quarterly_financials(ticker)
    annual    = load_av_annual_financials(ticker)

    # Default terminal growth = median of historical annual revenue YoY growth
    if overrides is None or overrides.terminal_growth_rate is None:
        median_g = _median_revenue_growth(annual["income"])
        overrides = (overrides or UserOverrides()).replace(terminal_growth_rate=median_g)

    return _run_dcf_core(ticker, annual, quarterly, overrides)
```

### Median terminal growth helper

```python
def _median_revenue_growth(income_df: pd.DataFrame) -> float:
    """Median YoY annual revenue growth from historical data. Clamped [0%, 15%]."""
    rev = income_df["revenue"].dropna()
    if len(rev) < 2:
        return 0.03
    # income_df sorted newest→oldest; pairwise growth = rev[i] / rev[i+1] - 1
    rates = (rev.values[:-1] / rev.values[1:] - 1)
    return float(np.clip(np.median(rates), 0.0, 0.15))
```

---

## Phase 3 — Backend: new API router (`api/av_router.py`)

**New file**: `api/av_router.py`

### Endpoints

```
GET  /av-financials/{ticker}/{stmt}   stmt ∈ {income, balance, cashflow}
                                      ?period_type=annual|quarterly&periods=20
GET  /av-dcf/{ticker}
POST /av-dcf/{ticker}/run             same RunRequest body as /dcf/{ticker}/run
```

The `RunRequest` and override-parsing logic are imported from `dcf_router.py` (no duplication).

### Error handling

If AV data is absent for the ticker:
- `load_av_*_financials` raises `ValueError`
- Router returns `HTTP 404` with `{"detail": "No AV data for {ticker} — import via av_financials_db first"}`

### Register in `api/main.py`

```python
from api.av_router import router as av_router
app.include_router(av_router)
```

---

## Phase 4 — Frontend: `AvFinancialsViewer.tsx`

**New file**: `web/components/AvFinancialsViewer.tsx`

Mirrors `StatementViewer.tsx`. Key differences:

| Aspect | StatementViewer | AvFinancialsViewer |
|---|---|---|
| Endpoint | `/statements/{ticker}/{stmt}` | `/av-financials/{ticker}/{stmt}` |
| Period filter param | `period_type=FY\|Q` | `period_type=annual\|quarterly` |
| Date column | `period_end_date` | `fiscal_date_ending` |
| Period label | FY/Q from `fiscal_year`+`fiscal_quarter` | year from `fiscal_date_ending` date; quarter derived from month |
| Columns skipped | `ticker`, `period_end_date`, etc. | `ticker`, `fiscal_date_ending`, `period_type` |

Period label logic for AV (no `fiscal_year`/`fiscal_quarter` fields):
- Annual: `"FY " + fiscal_date_ending.slice(0, 4)`
- Quarterly: derive quarter from month of `fiscal_date_ending` (Jan/Feb/Mar → Q1, etc.)

Key metrics to highlight (same rows as StatementViewer, adapted to AV column names): `total_revenue`, `gross_profit`, `operating_income`, `ebitda`, `net_income`, `operating_cashflow`, `capital_expenditures`, `total_assets`, `total_shareholder_equity`.

Toggle: "FY" / "Q" buttons, same styling as existing Financials tab.

---

## Phase 5 — Frontend: parameterise `DcfViewer.tsx`

Add one optional prop to `DcfViewer.tsx`:

```typescript
interface DcfViewerProps {
  ticker: string;
  apiPath?: string;   // default "/dcf"
}
```

Replace the two hardcoded `/dcf/${ticker}` fetch strings with `` `${apiPath}/${ticker}` ``.

That's the only change to `DcfViewer.tsx`. All child components, state, and override logic are unchanged because the API response shape (`DcfData`) is identical.

---

## Phase 6 — Frontend: `AvDcfViewer.tsx` + `page.tsx`

### `AvDcfViewer.tsx` (trivial wrapper)

```typescript
import DcfViewer from "./DcfViewer";
export default function AvDcfViewer({ ticker }: { ticker: string }) {
  return <DcfViewer ticker={ticker} apiPath="/av-dcf" />;
}
```

### `page.tsx` changes

```typescript
type Tab = "financials" | "dcf" | "av_financials" | "av_dcf";
```

Tab bar labels:

| Tab value | Button label |
|---|---|
| `financials` | Financials |
| `dcf` | DCF |
| `av_financials` | AV Data |
| `av_dcf` | AV DCF |

New content blocks:

```tsx
{activeTab === "av_financials" && loadedTicker && (
  <AvFinancialsViewer ticker={loadedTicker} />
)}
{activeTab === "av_dcf" && loadedTicker && (
  <AvDcfViewer ticker={loadedTicker} />
)}
```

---

## Implementation sequence

| Step | File | New / Modified |
|---|---|---|
| 1 | `dcf/av_data.py` | New |
| 2 | `dcf/model.py` | Modified (extract `_run_dcf_core`, add `run_dcf_av`, `_median_revenue_growth`) |
| 3 | `api/av_router.py` | New |
| 4 | `api/main.py` | Modified (register `av_router`) |
| 5 | `web/components/AvFinancialsViewer.tsx` | New |
| 6 | `web/components/DcfViewer.tsx` | Modified (add `apiPath` prop) |
| 7 | `web/components/AvDcfViewer.tsx` | New |
| 8 | `web/app/page.tsx` | Modified (two new tabs) |

---

## Key constraints and risks

| Risk | Mitigation |
|---|---|
| AV has no `diluted_shares` in income statement | Derive from `shares_outstanding` table; fallback to `common_stock_shares_outstanding` from balance sheet |
| AV cashflow may lack D&A for some tickers | Fall back to income statement `depreciation_and_amortization`; same logic as existing `_da_pct()` |
| AV reports fewer than 8 quarterly periods for some tickers | Raise `ValueError` → 404 with clear message |
| `_run_dcf_core` extraction must not change the output of `run_dcf` | Run end-to-end test on AAPL before and after refactor to confirm identical `DcfResult` |
| `UserOverrides` is a dataclass — needs a `replace` helper | Use `dataclasses.replace(overrides, terminal_growth_rate=median_g)` |
| AV `period_type` is lowercase | Normalise to title-case in `av_data.py` so no other module needs awareness |

---

## Out of scope

- Auto-importing AV data from within the web app (user runs `av_financials_db.py` externally)
- Changing the existing DCF tab's terminal growth default
- Analyst-estimate overlay on the AV DCF (AV estimates are already in `financial_statements.duckdb` via `estimates.py`; the AV DCF will skip the analyst-estimate layer or include it only if the same estimates table is accessible)
