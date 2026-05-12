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
| 4 | Feature engineering (27 features — see below) |
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

## Features (27, as of last edit)

### Valuation level
`pe_ratio`, `pfcf_ratio`, `ev_ebitda`, `ps_ratio`, `pbv`, `ptbv`, `fcf_yield`, `dividend_yield`

### Mean-reversion premiums (current / 5yr rolling median)
`pe_premium`, `pfcf_premium`, `ev_premium`, `ps_premium`, `pbv_premium`, `ptbv_premium`

### Quality / profitability
`roa`, `roe`, `roic`, `roa_premium`, `roe_premium`, `roic_premium`

### Historical fair-value anchors (5yr rolling median — no look-ahead)
`pe_rolling_5yr_median`, `pfcf_rolling_5yr_median`, `ev_ebitda_rolling_5yr_median`,
`ps_rolling_5yr_median`, `roa_rolling_5yr_median`, `roe_rolling_5yr_median`,
`roic_rolling_5yr_median`

---

## Current State

The notebook was last edited to remove a look-ahead bias bug but **has not been re-executed**
since that fix. The last clean execution used the leaky goal features (see Bugs below).

### Last clean run results (with leaky goal features — numbers will change after re-run)

| Horizon | Training rows | In-sample R² |
|---------|--------------|--------------|
| ret_6m  | 289,273      | 0.104        |
| ret_1y  | 280,797      | 0.142        |
| ret_2y  | 263,894      | 0.182        |
| ret_3y  | 247,136      | 0.195        |
| ret_5y  | 213,896      | 0.261        |

Walk-forward (ret_6m, 247 months, top 20% selection):
- Mean excess return: +8.6% vs universe
- Win rate: 96%
- ICIR: 1.21 (partly inflated by leaky features — expect lower after re-run)

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

### Immediate (resume here)

1. **Re-execute the notebook** with the 27 clean features:
   ```
   cd /home/pedro/projects/fin_import2
   uv run jupyter nbconvert --to notebook --execute \
     --ExecutePreprocessor.timeout=900 \
     --output /tmp/fundamentals_alpha_clean.ipynb \
     notebooks/fundamentals_alpha.ipynb
   ```
   Check that forward return means are positive (6m ~10%, 1y ~16–19%) and review
   the updated ICIR. Anything above 0.5 is practically significant; above 1.0 is strong.

2. **Add growth features** — revenue, earnings, and FCF growth rates are missing.
   They exist in `pe_stats` (current snapshot) but need to be computed historically
   from `monthly_pe` (ttm_revenue, ttm_fcf, ttm_eps per ticker per month).
   Suggested additions:
   - `rev_cagr_3yr` — 3-year trailing revenue CAGR from ttm_revenue
   - `earn_cagr_3yr` — 3-year trailing EPS CAGR from ttm_eps
   - `fcf_cagr_3yr` — 3-year trailing FCF CAGR from ttm_fcf
   These can be computed with a window function in the feature engineering cell.

### Medium term

3. **Sector neutralization** — compute valuation premiums relative to sector median
   rather than (or in addition to) own 5yr history. Requires a sector/industry mapping
   per ticker. Typically improves IC by removing macro/sector return noise.

4. **Composite factor score** — once the best individual factors are confirmed via ICIR,
   build a blended score (value + quality + momentum) weighted by ICIR. Simpler and
   more robust than XGBoost for live scoring.

5. **Liquidity / market cap filter** — the current live scoring includes micro-caps and
   thinly traded stocks that top the rankings. Add a minimum market cap filter
   (e.g. >$500M) in Cell 13 before presenting buy candidates.

6. **DCF model** — separate notebook. Use historical FCF + growth rates to compute
   intrinsic value. Complement to the factor model (factor model ranks stocks;
   DCF provides a price target).

---

## Data

- **DB**: `data/historic_fundamentals.duckdb`
- **Table**: `monthly_pe` — 296,348 rows, 1,414 tickers, 1999-12-31 to 2026-05-31
- **Key columns**: price, pe_ratio, pfcf_ratio, ev_ebitda, ps_ratio, pbv, ptbv,
  roa, roe, roic, fcf_yield, dividend_yield, plus 5yr rolling medians for each
- **Dependencies**: `xgboost`, `shap` (both installed in .venv)
