# Project Status — Fundamentals Alpha

## Goal

Build an ML model that identifies which fundamental characteristics predict forward stock
returns at 6-month, 1-year, 2-year, 3-year, and 5-year horizons. Use this to rank all
tickers in the database by expected return and surface buy candidates.

This replaces the earlier `valuation_model.ipynb` approach (which required GP analyst
spreadsheets as training labels — those have been deleted).

---

## Notebook

`notebooks/fundamentals_alpha.ipynb`

Mirrors the structure of `trade_systems/strategies/ibd50/ibd50_analysis.ipynb`.

### Structure

| Cell | Purpose |
|------|---------|
| 1 | Imports & config |
| 2 | Load `monthly_pe` from DB (296K rows, 1,414 tickers, 1999–2026) |
| 3 | Compute forward returns (6m, 1y, 2y, 3y, 5y) via vectorized self-join |
| 3b | Compute trailing CAGRs (rev/earn/fcf at 1y, 3y, 5y) — backward-looking |
| 4 | Feature engineering (36 features — see below) |
| 5 | Return target masking — NaN = future price not yet available |
| 6 | EDA: correlation heatmap (feature vs each return horizon) |
| 7 | EDA: monthly IC / ICIR (Spearman rank correlation per month) |
| 8 | EDA: quintile return analysis (Q1–Q5 mean return per feature) |
| 9 | XGBoost training — one model per horizon |
| 10 | SHAP importance plots (magnitude + direction beeswarm) |
| 11 | Walk-forward validation (train months 1–N, predict N+1, no lookahead) |
| 12 | Walk-forward cumulative return chart + monthly IC bar chart |
| 13 | Live scoring — ranks all tickers in pe_stats by predicted return |
| 14 | Summary printout |

---

## Features (36, as of last run)

### Valuation level (8)
`pe_ratio`, `pfcf_ratio`, `ev_ebitda`, `ps_ratio`, `pbv`, `ptbv`, `fcf_yield`, `dividend_yield`

### Mean-reversion premiums — current / 5yr rolling median (6)
`pe_premium`, `pfcf_premium`, `ev_premium`, `ps_premium`, `pbv_premium`, `ptbv_premium`

### Quality / profitability (6)
`roa`, `roe`, `roic`, `roa_premium`, `roe_premium`, `roic_premium`

### Historical fair-value anchors — 5yr rolling median, no look-ahead (7)
`pe_rolling_5yr_median`, `pfcf_rolling_5yr_median`, `ev_ebitda_rolling_5yr_median`,
`ps_rolling_5yr_median`, `roa_rolling_5yr_median`, `roe_rolling_5yr_median`,
`roic_rolling_5yr_median`

### Growth — trailing CAGRs, backward-looking (9)
`rev_cagr_1y`, `rev_cagr_3y`, `rev_cagr_5y`,
`earn_cagr_1y`, `earn_cagr_3y`, `earn_cagr_5y`,
`fcf_cagr_1y`, `fcf_cagr_3y`, `fcf_cagr_5y`

---

## Current State

Latest clean run uses **36 features** (27 valuation/quality + 9 growth CAGRs).
No look-ahead — all features are backward-looking or contemporaneous.

### Run results (36 features, 2026-05-13)

| Horizon | Training rows | In-sample R² |
|---------|--------------|--------------|
| ret_6m  | 289,273      | 0.095        |
| ret_1y  | 280,797      | 0.127        |
| ret_2y  | 263,894      | 0.161        |
| ret_3y  | 247,136      | 0.159        |
| ret_5y  | 213,896      | 0.183        |

**Walk-forward (ret_6m, 247 months, top 20% selection):**
- Top-20% return: **+16.38%**
- Benchmark return: +8.74%
- Mean excess return: **+7.64%** vs universe
- Win rate: **96%**
- Mean monthly IC: 0.1265
- **ICIR: 0.941** (close to the 1.0 "strong factor" threshold)

### Top features by SHAP importance (mean across horizons)
1. `ps_ratio` — value (negative direction = cheap wins)
2. `dividend_yield` — yield/quality
3. `roa` — profitability
4. `rev_cagr_1y` — growth (new)
5. `roa_rolling_5yr_median` — quality
6. `rev_cagr_3y` — growth (new)
7. `pfcf_ratio` — value

---

## Bugs Fixed

### 1. Forward return indexing error
`iloc[argmin()]` was being called on a differently-indexed Series, causing random
price mismatches and artificial negative mean returns (-17% to -40%).
Fixed by rewriting as a vectorized self-join merge using `day_diff.abs().dt.days`.

### 2. Look-ahead bias in goal features
`goal_discount` and `goal_upside` were computed from `goal_low` / `goal_high` columns
in `monthly_pe`. Those columns use `pe_lt_median` (all-time median, not rolling), which
incorporates future data when applied to historical rows.
Fixed by removing both features from `FEATURE_COLS`.

---

## Next Steps

### Done in this session
- [x] Re-executed notebook with 27 clean features (no goal leakage)
- [x] Added 9 growth features (1y/3y/5y CAGRs for revenue, EPS, FCF)
- [x] Confirmed value (ps_ratio, dividend_yield) dominates, growth/quality secondary
- [x] Final ICIR: 0.941 (vs 0.889 without growth features)

### Next (in priority order)

1. **Sector neutralization** — compute valuation premiums relative to sector median
   rather than (or in addition to) own 5yr history. Requires a sector/industry mapping
   per ticker. Typically improves IC by removing macro/sector return noise.
   - Needs: sector mapping table (not currently in DB)
   - Suggested source: SEC SIC codes or Yahoo Finance sector field

2. **Liquidity / market cap filter** — the current live scoring includes micro-caps and
   thinly traded stocks that top the rankings. Add a minimum market cap filter
   (e.g. >$500M) in Cell 13 before presenting buy candidates.
   - Simple addition: `live = live[live['market_cap_b'] >= 0.5]` before ranking

3. **Save trained model artifacts** — currently the model is retrained from scratch
   on every notebook run. Save `models[PRIMARY_ML_TARGET]` + `train_medians` + `FEATURE_COLS`
   to `models/` so a quick-predict cell can reuse without retraining.

4. **Composite factor score** — once the best individual factors are confirmed via ICIR,
   build a blended score (value + quality + growth) weighted by ICIR. Simpler and
   more robust than XGBoost for live scoring.

5. **DCF model** — separate notebook. Use historical FCF + growth rates to compute
   intrinsic value. Complement to the factor model (factor model ranks stocks;
   DCF provides a price target).

### Performance notes (for future tuning)
- Notebook runs ~7–8 minutes end-to-end on this machine
- Forward return computation is now vectorized (was the bottleneck)
- Trailing CAGR computation adds ~1 minute (9 self-joins)
- Walk-forward validation is the slowest cell (~3 minutes — 247 XGBoost retrains)

---

## Data

- **DB**: `data/historic_fundamentals.duckdb`
- **Table**: `monthly_pe` — 296,348 rows, 1,414 tickers, 1999-12-31 to 2026-05-31
- **Key columns**: price, pe_ratio, pfcf_ratio, ev_ebitda, ps_ratio, pbv, ptbv,
  roa, roe, roic, fcf_yield, dividend_yield, plus 5yr rolling medians for each;
  earnings_yield, earnings_yield_3y_avg, earnings_yield_5y_avg, normalized_pe_5y
- **Dependencies**: `xgboost`, `shap` (both installed in .venv)
