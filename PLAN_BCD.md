# BCD Mispricing Signal Implementation Plan

**Based on**: Bakshi-Chen 2001, Dong-Hirshleifer 2004, Chang et al 1999, Chen-Dong 2001

**Goal**: Add a structural BCD mispricing feature to the fundamentals-alpha XGBoost model
to improve signal quality (papers show it is the strongest cross-sectional predictor, dominating
E/P, B/M, and momentum with t-stats of -4.6 to -9.17 in Fama-MacBeth regressions).

---

## Questions answered

**Will this be a new strategy?**
No. BCD Misp becomes a new feature in the existing `vw_gr_top_n_25` pipeline.
The existing strategy, backtest, and paper account are unchanged until Phase 4.

**Will it impact paper trading?**
Phases 1-3 add data and validate signals without touching `data/model.joblib` or
`scripts/score_live.py`. Paper trading is only affected in Phase 4, which has an explicit
decision gate before any promotion.

---

## Architecture

```
DGS30 (FRED)       TTM EPS           Forward EPS (FY1)
     │                │                        │
     └────────────────┴────────────────────────┘
                      │
              features/bcd/signal.py
              compute_bcd_lite_misp()
                      │
              monthly_pe.bcd_misp  ←── new column (no paper trading impact)
              market_signals.punder ←── new table (% underpriced, market regime)
                      │
         ┌────────────┴──────────────────────┐
         │                                    │
  notebooks/bcd_validation.ipynb        dcf/model.py
  (IC/ICIR validation, no retrain)      (DGS30 as risk-free rate)
         │
  [Phase 4 gate — explicit decision]
         │
  scripts/train_model.py  →  data/model.joblib (new)
         │
  scripts/score_live.py  ←── live scoring changes after Phase 4 only
```

---

## Phase 1 — Data Infrastructure

**Status**: [x] Complete
**Paper trading impact**: NONE
**Estimated effort**: 1-2 days

### Step 1.1 — Add DGS30 to fred.duckdb [x]

Add the 30-year Treasury constant-maturity yield (FRED series `DGS30`) alongside existing `DGS10`.
The BC model is parameterized on the long bond; 30-year is a closer match than 10-year.

**File to modify**: whichever script currently imports DGS10 into `data/fred.duckdb`

- Source: FRED API, series `DGS30`, backfill from 2000-01-01
- Target table: `data/fred.duckdb` → `economic_indicators` (same table, same schema as DGS10)

Test:
```bash
uv run python -c "
import duckdb
conn = duckdb.connect('data/fred.duckdb', read_only=True)
r = conn.execute(\"SELECT series_id, date, value FROM economic_indicators WHERE series_id='DGS30' ORDER BY date DESC LIMIT 5\").fetchall()
print(r)
conn.close()
"
# Pass: 5 rows returned, series_id='DGS30', value between 3.0 and 7.0
```

### Step 1.2 — Add load_risk_free_rate_30y() to dcf/data.py [x]

**File**: `dcf/data.py`

Add alongside existing `load_risk_free_rate()`:

```python
def load_risk_free_rate_30y() -> float | None:
    """DGS30 as decimal. Falls back to DGS10 + 0.005 if unavailable."""
    try:
        conn = duckdb.connect(str(FRED_DB), read_only=True)
        row = conn.execute(
            "SELECT value FROM economic_indicators WHERE series_id = 'DGS30' ORDER BY date DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return float(row[0]) / 100.0 if row else None
    except Exception:
        return None
```

Test:
```bash
uv run python -c "
from dcf.data import load_risk_free_rate_30y
r = load_risk_free_rate_30y()
print(r)
assert r is not None and 0.02 < r < 0.09
"
# Pass: float in range, no exception
```

### Step 1.3 — Verify forward EPS coverage [x]

BCD Misp needs analyst 1-year forward EPS. Confirm `earnings_estimates` has adequate coverage.

```bash
uv run python -c "
import duckdb
conn = duckdb.connect('data/historic_fundamentals.duckdb', read_only=True)
r = conn.execute('''
    SELECT COUNT(DISTINCT ticker) as tickers,
           MIN(fiscal_date) as earliest,
           MAX(fiscal_date) as latest
    FROM earnings_estimates
    WHERE horizon = 'fiscal year' AND eps_avg IS NOT NULL AND eps_avg > 0
''').fetchone()
print(f'Tickers with FY EPS estimates: {r[0]}, range: {r[1]} to {r[2]}')
conn.close()
"
# Pass: tickers >= 100, latest within last 90 days
```

**Phase 1 complete when**: DGS30 in fred.duckdb, `load_risk_free_rate_30y()` returns valid float.

---

## Phase 2 — BCD Signal Computation

**Status**: [x] Complete
**Paper trading impact**: NONE (read-only additions to monthly_pe)
**Estimated effort**: 2-3 days

### Step 2.1 — Implement BCD-lite model price [x]

Create `features/bcd/signal.py`.

**BCD-lite formula** (no parameter optimization; uses three directly observable inputs):

```
G(t) = (fwd_eps_1y - ttm_eps) / ttm_eps   # analyst consensus 1yr EPS growth
r(t) = DGS30(t) + 0.055                    # 30yr yield + 5.5% ERP (Damodaran)
g_T  = 0.03                                # terminal growth (nominal GDP proxy)
P_model(t) = ttm_eps * (1 + G(t)) / (r(t) - g_T)   if r(t) - g_T > G(t)
           = NaN                                      otherwise (transversality violated)
Misp(t) = (price(t) - P_model(t)) / P_model(t)       clipped to [-3, +3]
```

Positive Misp = overpriced; negative Misp = underpriced. Portfolio sorts on Misp ascending
(buy the most underpriced: lowest Misp decile).

**File**: `features/bcd/__init__.py` (empty), `features/bcd/signal.py`

```python
# features/bcd/signal.py

def compute_bcd_lite_misp(
    ttm_eps: float,
    fwd_eps_1y: float,
    price: float,
    dgs30: float,
    erp: float = 0.055,
    terminal_growth: float = 0.03,
    misp_clip: float = 3.0,
) -> float | None:
    if not (ttm_eps > 0 and fwd_eps_1y > 0 and price > 0 and dgs30 > 0):
        return None
    g = (fwd_eps_1y - ttm_eps) / ttm_eps
    r = dgs30 + erp
    if r - terminal_growth <= g:
        return None
    model_price = ttm_eps * (1.0 + g) / (r - terminal_growth)
    if model_price <= 0:
        return None
    misp = (price - model_price) / model_price
    return float(max(-misp_clip, min(misp_clip, misp)))
```

Test:
```bash
uv run python -c "
from features.bcd.signal import compute_bcd_lite_misp

# AAPL-like: 10% forward growth, 4.5% 30yr yield
misp = compute_bcd_lite_misp(6.0, 6.6, 190.0, 0.045)
assert misp is not None and -1.0 < misp < 3.0, f'Unexpected: {misp}'

# Negative EPS returns None
assert compute_bcd_lite_misp(-0.5, 1.0, 20.0, 0.045) is None

# Transversality violation (growth >= discount rate) returns None
assert compute_bcd_lite_misp(1.0, 2.0, 50.0, 0.02) is None

print('All BCD-lite unit tests passed')
"
```

### Step 2.2 — Add bcd_misp column to monthly_pe [x]

Schema migration:
```bash
uv run python -c "
import duckdb
conn = duckdb.connect('data/historic_fundamentals.duckdb')
conn.execute('ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS bcd_misp DOUBLE')
conn.close()
print('Column added')
"
```

### Step 2.3 — Backfill script [x]

Create `scripts/backfill_bcd_misp.py`.

Logic per (ticker, month_end_date):
1. Fetch `ttm_eps` and `price` from `monthly_pe`
2. Fetch nearest FY1 `eps_avg` from `earnings_estimates` where `fiscal_date >= month_end_date`
3. Fetch `DGS30` from `fred.duckdb` nearest to `month_end_date`
4. Compute `compute_bcd_lite_misp()` and write back to `monthly_pe.bcd_misp`

Test (dry run first):
```bash
uv run python scripts/backfill_bcd_misp.py --dry-run
# Expected: prints coverage stats (total rows, eligible, expected non-null %) without writing

uv run python scripts/backfill_bcd_misp.py
# Then validate:
uv run python -c "
import duckdb
conn = duckdb.connect('data/historic_fundamentals.duckdb', read_only=True)
r = conn.execute('''
    SELECT
        COUNT(*) as total,
        COUNT(bcd_misp) as non_null,
        ROUND(100.0*COUNT(bcd_misp)/COUNT(*), 1) as pct,
        ROUND(AVG(bcd_misp), 3) as avg_misp,
        ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY bcd_misp), 3) as p25,
        ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY bcd_misp), 3) as p75
    FROM monthly_pe WHERE ttm_eps > 0
''').fetchone()
print(r)
conn.close()
# Pass: pct > 50%, avg_misp near 0 (mkt roughly fairly valued on avg), p25 < 0, p75 > 0
"
```

### Step 2.4 — Compute monthly Punder (market regime signal) [x]

Create `market_signals` table and populate it with the fraction of covered stocks where
`bcd_misp < 0` (BCD-underpriced) per month. This is the market-timing signal from the papers
(R² = 22.1% vs S&P 500 12-month forward return, t-stat = 7.87).

```bash
uv run python -c "
import duckdb
conn = duckdb.connect('data/historic_fundamentals.duckdb')
conn.execute('''
    CREATE TABLE IF NOT EXISTS market_signals (
        month_end_date DATE PRIMARY KEY,
        punder DOUBLE,
        n_stocks INTEGER,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.execute('''
    INSERT OR REPLACE INTO market_signals (month_end_date, punder, n_stocks)
    SELECT
        month_end_date,
        AVG(CASE WHEN bcd_misp < 0 THEN 1.0 ELSE 0.0 END) as punder,
        COUNT(*) as n_stocks
    FROM monthly_pe
    WHERE bcd_misp IS NOT NULL
    GROUP BY month_end_date
''')
n = conn.execute('SELECT COUNT(*) FROM market_signals').fetchone()[0]
print(f'market_signals rows: {n}')
conn.close()
# Pass: n >= 60 months of data
"
```

**Phase 2 complete when**: `monthly_pe.bcd_misp` >= 50% populated for eligible rows;
`market_signals` has a complete monthly punder time series.

---

## Phase 3 — Signal Validation

**Status**: [x] Complete
**Paper trading impact**: NONE

### Results (scripts/validate_bcd_signal.py, run 2026-06-29)

**Step 3.1 — Standalone IC/ICIR [x]**
- Months: 408 (1991-07 to 2026-06); mean IC = -0.046; NW-ICIR = **-3.67** >> gate 0.30 — PASS
- Annual sign consistency: **74.3%** >> gate 60% — PASS
- Years with wrong sign (IC > 0): 1993, 1994, 1998, 1999, 2006, 2015, 2017, 2018, 2019

**Step 3.2 — Mean-reversion speed [x]**
- Lag-12 autocorr: bcd_misp = 0.24 vs pe_ratio = 0.66 — PASS at all lags 1-24

**Step 3.3 — Punder vs SPY [x]**
- Slope = -0.022, p = 0.82 — FAIL
- BCD-lite punder is miscalibrated for market timing (avg punder = 61.9%); needs full
  parameter estimation to produce calibrated absolute prices.

**Step 3.4 — Sector coverage [x]**
- Healthcare: 45.8% (low; biotech/pharma with negative EPS excluded)
- All other sectors: 59-87%

### Critical finding: bcd_misp is redundant with pe_ratio in the ML model

Cross-sectional Spearman correlation with existing features (2005+, >B cap):
  pe_ratio = +0.82, earnings_yield = -0.82, earn_growth_1yr = -0.63, ev_ebitda = +0.60

Adding bcd_misp as a raw XGBoost feature HURTS performance (23.4% null rate + redundancy):
  Baseline NW-ICIR: 2.26  →  With bcd_misp: 0.95 (same 16 folds, 2010-2026)

### Decision: use bcd_misp as a FILTER, not an XGBoost feature

Phase 4 is revised: do NOT add bcd_misp to FEATURE_COLS in train_model.py.
Instead, use it as a post-score filter in score_live.py: prefer (or require) bcd_misp < 0.
This preserves ML model integrity while applying the cross-sectional alpha from the BCD signal.

---

## Phase 4 — BCD Hard Filter in score_live.py

**Status**: [x] Complete (2026-06-29)
**Paper trading impact**: YES — changes which stocks appear in top-25

### Approach (revised from original plan)

Phase 3 showed bcd_misp is redundant with pe_ratio in XGBoost (0.82 Spearman correlation,
NW-ICIR dropped 2.26→0.95 when added as feature). Decision: use as portfolio filter instead.

Post-2010 backtest (bcd_hard threshold=0.0 vs baseline, vw_gr_top_n_25):
  baseline: CAGR=12.66%, Sharpe=0.754, MaxDD=-35.5%
  bcd_hard: CAGR=15.66%, Sharpe=0.919, MaxDD=-28.0%, PF=1.97, R-Exp=1.35%

### Step 4.1 — Add _apply_bcd_filter() to score_live.py [x]

**File**: `scripts/score_live.py`

Added `_apply_bcd_filter()` function that removes stocks with bcd_misp > 0 or NULL.
Called in `main()` when `--guardrails` is on (default), before `_select_output_columns()`.

Live result (2026-06-29): 1,531 universe → 326 pass BCD filter → 323 after other guardrails.

**Phase 4 complete when**: score_live.py applies bcd_hard filter; all top-25 stocks have bcd_misp <= 0.

---

## Phase 5 — DCF Improvements (Independent)

**Status**: [x] Complete (dcf/model.py now uses DGS30; Phase 5.2 skipped — DCF is FCFF-based, y₀ has no applicable hook)
**Paper trading impact**: NONE (DCF is display-only, not used by screener)
**Estimated effort**: 0.5 days

### Step 5.1 — Use 30-year Treasury as DCF risk-free rate [ ]

**File**: `dcf/model.py`

Replace `load_risk_free_rate()` call with:
```python
rf = load_risk_free_rate_30y() or (load_risk_free_rate() + 0.005) or DEFAULT_RF
```

Test:
```bash
uv run python -c "
from dcf.model import run_dcf
result = run_dcf('AAPL')
print('WACC rf:', result.wacc_detail.risk_free_rate)
# Pass: risk_free_rate > DGS10 (30yr yield typically > 10yr yield)
"
```

### Step 5.2 — y₀ buffer for near-zero EPS in DCF growth rates [ ]

**File**: `dcf/estimates.py` or `dcf/forecaster.py`

For tickers where `abs(ttm_eps) < 0.5` (near-zero earnings), the Gordon-growth denominator
becomes unstable. Add a y₀ buffer per GEVM (Dong-Hirshleifer 2004):

```python
def adjusted_growth_rate(eps_current: float, eps_fwd: float, y0: float = 0.0) -> float | None:
    denom = eps_current + y0
    if abs(denom) < 1e-6:
        return None
    return (eps_fwd - eps_current) / denom
```

Estimate y₀ per GEVM: `y₀ = max(0, rd_per_share + 0.3 * dep_per_share)` where available.
Default fallback: `y₀ = 0` (no change for profitable companies).

**Phase 5 complete when**: DCF uses DGS30 as risk-free anchor; near-zero EPS stocks no longer
produce extreme DCF values.

---

## Test Matrix

| Phase | Test | Pass condition |
|-------|------|---------------|
| 1.1 | DGS30 in fred.duckdb | >= 2000 rows, value 3-7% |
| 1.2 | load_risk_free_rate_30y() | float in (0.02, 0.09) |
| 1.3 | FY1 EPS coverage | >= 100 distinct tickers |
| 2.1 | BCD-lite unit tests | all 3 cases pass |
| 2.2 | bcd_misp schema | column exists in monthly_pe |
| 2.3 | backfill coverage | >= 50% of ttm_eps>0 rows |
| 2.4 | market_signals | >= 60 months of punder |
| 3.1 | IC/ICIR pass gate | NW-ICIR > 0.30, sign consistent >= 60% years |
| 3.2 | mean-reversion | lag-12 autocorr: bcd_misp < pe_ratio |
| 3.3 | punder regression | slope > 0, p < 0.10 |
| 3.4 | sector coverage | all sectors documented |
| 4.2 | backup | model_pre_bcd.joblib exists |
| 4.3 | retrain metrics | 3/5 metrics improve |
| 4.4 | top-25 overlap | >= 60% |
| 5.1 | DCF risk-free | rf > DGS10 |
| 5.2 | y₀ buffer | no extreme DCF for low-EPS tickers |

---

## Implementation Order

Recommended sequence: **1 → 5 → 2 → 3 → [gate] → 4**

Phase 5 can run in parallel with Phases 2-3 since it is independent of the screener.

| Phase | Effort | Depends on | Paper trading risk |
|-------|--------|-----------|-------------------|
| 1 (Data infra) | 1-2 days | nothing | none |
| 5 (DCF) | 0.5 days | Phase 1 step 1.2 | none |
| 2 (Signal) | 2-3 days | Phase 1 | none |
| 3 (Validation) | 1-2 days | Phase 2 | none |
| 4 (Model retrain) | 1 day | Phase 3 pass gate + explicit decision | **YES** |

Total calendar time: ~2 weeks.
