# ML Comps-Based Fair Valuation — Implementation Plan

## Status

**Phase 0 — COMPLETE** (2026-07-20): Schema stub + this plan doc.
**Phase 1 — COMPLETE** (2026-07-20): Feature/dataset assembly module.
**Phase 2 — COMPLETE** (2026-07-20): Quantile regression model + walk-forward harness.
**Phase 3 — COMPLETE, PASS** (2026-07-20): P/E and P/FCF cleared the gate; EV/EBITDA did not (see below).
**Phase 4 — COMPLETE** (2026-07-20): Batch training + scoring pipeline, P/E and P/FCF only. Two real bugs found and fixed before shipping — see below.
**Phase 5 — COMPLETE** (2026-07-20): Model metadata / retrain visibility report.
**Phase 6 — COMPLETE** (2026-07-20): API exposure, verified against a live server.
**Phase 7 — COMPLETE** (2026-07-20): Frontend panel, verified in a real browser (Playwright) — renders correctly, 0 console errors, existing Price Targets/Valuation Multiples sections unaffected.
**Phase 8 — COMPLETE** (2026-07-20): Monitoring notebook, executed end-to-end with real data.

---

## Purpose

Predict a fair valuation range for a stock from fundamental comps — margins, growth, ROIC, leverage, size, sector — using ML, as a **new, additive** field alongside the existing `goal_pe`/`goal_low`/`goal_high` (see below). Continuously retrained as new fundamentals data arrives.

## Non-goal

This plan does **not** modify `goal_pe`, `goal_pcf`, `goal_peg`, `goal_bv`, `goal_low`, `goal_high`, `pe_stats`, or any of their existing consumers (`api/av_router.py`'s existing fields, `api/screener_router.py`'s goal-upside filters, paper-trading code). Those fields are computed by comparing a ticker to **its own** multiple history (`historic_fundamentals/pe.py::enrich_goals()`) — genuinely different from what this plan builds, which compares a ticker to **its peers**' fundamentals cross-sectionally. Both can coexist and be compared; replacing the old fields is an explicit future decision, not part of this work (see Phase 9 below).

## Why this design

The existing forward-return XGBoost model in this module (`historic_fundamentals/model.py`, target `ret_1y`) has a flat OOS rank IC (-0.017) despite a strong-looking backtest, and is already live-paper-trading past its own never-closed go/no-go gate (`features/historic_fundamentals/fundamentals_alpha_action_plan.md` Phase 11 was never completed). This plan is designed to not repeat that pattern: Phase 3 below is a pre-registered, fold-level (not just aggregate) validation gate that must pass before the model is wired into scoring, API, or UI.

The model predicts a **fair multiple** (P/E, EV/EBITDA, P/FCF), not price or return, directly:
- **vs. predicting price**: raw price is scale-dependent on shares outstanding, not a fundamentals-comparable quantity across tickers — a multiple is.
- **vs. predicting forward return**: a multiple is a same-month cross-sectional value with no forward-looking label, so it sidesteps the market-timing noise that likely explains the existing model's flat IC.

Fair price = predicted multiple × the ticker's own EPS/EBITDA/FCF.

---

## Phase 0 — Schema stub

- `historic_fundamentals/db.py::_create_schema()` — added `ml_comps_valuation` (PK `ticker`, full-replace-per-run live-scoring cache, mirrors `dcf_results`) and `ml_model_metadata` (PK `(model_name, model_version, target)`, retrain history).

## Phase 1 — Feature/dataset assembly

`historic_fundamentals/ml_comps_model.py` — `build_training_frame()` joins `monthly_pe` + `company_overview.sector` + `sector_stats` peer medians (`pe_median`/`evebitda_median`/`pfcf_median`), applies the `feature_available_date` point-in-time filter (a discipline `train_model.py` does not currently apply — not repeated here), drops peer groups with `ticker_count < 5`.

v1 feature set (all pre-computed in `monthly_pe`): `rev_growth_1yr`, `rev_cagr_3yr/5yr`, `fcf_growth_1yr`, `fcf_cagr_3yr`, `ttm_gross_margin` (+5y median), `ttm_operating_margin` (+5y median +slope), `ttm_fcf_margin` (+5y median), `roa`/`roe`/`roic`, `roa_stability_5y`, `debt_to_ebitda`, `interest_coverage`, `earnings_quality`, `asset_growth`, `momentum_12_1`, `log_market_cap`.

**Known limitation, accepted for v1**: sector/industry classification comes from the *latest* `company_overview` snapshot applied retroactively to all history — no point-in-time historical classification exists anywhere in this codebase. Same limitation `sector_stats` already has; not new, not solved here.

## Phase 2 — Model

3 separate `XGBRegressor` per multiple (PE, EV/EBITDA, P/FCF), each fit with `objective="reg:quantileerror"`, `quantile_alpha=[0.1, 0.5, 0.9]`, `multi_strategy="one_output_per_tree"` (native XGBoost multi-quantile regression, `xgboost>=3.2.0`) to get a low/mid/high range from a single fit. `walk_forward_validate_quantile()` mirrors the fold-loop skeleton of `model.py::walk_forward_validate()` (reuses `_apply_sector_zscore`) but with `embargo_months=0` (no forward-looking label to leak) and RMSE/pinball-loss/coverage metrics instead of IC.

## Phase 3 — Go/no-go gate

**Baseline**: predict `multiple = sector_stats` peer median for that ticker's `(sector, month)`.

**Pass criteria** (for ≥2 of 3 multiples, via walk-forward over full history):
1. Aggregate OOS `rmse_log` ≥15% better than the naive baseline.
2. Model beats baseline in ≥60% of individual folds (catches a flat-IC-hidden-by-aggregate problem the old model's evaluation missed).
3. `coverage_p10_p90` between 70-90%, miss rate roughly symmetric.

**Result (2026-07-20, full history 1990-2026, 36 folds/multiple): PASS.**

| Multiple | RMSE improvement vs. baseline | Fold win rate | Coverage p10-p90 | Result |
|---|---:|---:|---:|---|
| P/E | +18.3% | 100% (36/36) | 74.9% | PASS |
| EV/EBITDA | +14.7% | 100% (36/36) | 74.1% | FAIL (missed 15% RMSE bar by 0.3pp) |
| P/FCF | +18.7% | 100% (36/36) | 73.1% | PASS |

2 of 3 multiples (P/E, P/FCF) passed all three criteria — gate clears the ≥2 requirement. Notably, the model beat the naive sector-median baseline in **100% of individual folds for all three multiples**, not just in aggregate — this is the specific check this gate was designed around, and it held cleanly across 36 years including the dot-com bust, 2008-09, and 2020. EV/EBITDA missed only the RMSE-improvement threshold (14.7% vs. 15%) while still winning every fold; not wired into scoring below, but close enough to revisit if the RMSE threshold or EV/EBITDA feature set is later adjusted. Full per-fold detail: `docs/ml_comps_validation_report.md`.

**Decision: proceed to Phase 4 for P/E and P/FCF only.** EV/EBITDA excluded from batch scoring/API/UI in this pass.

Phases 4+ below proceed on P/E and P/FCF.

## Phase 4 — Batch scoring

`scripts/train_ml_comps_valuation.py` + `scripts/score_ml_comps_valuation.py`, mirroring `train_model.py` / `compute_dcf_batch.py`. Wired into `scripts/run_pipeline.py` behind an **opt-in** `--enable-ml-comps` flag (default off, now enabled by the Phase 3 pass above).

**Two real bugs found and fixed while validating end-to-end scoring (not caught by the Phase 3 gate, which only validates the model in isolation):**

1. **Train/serve z-score skew.** The scoring script initially recomputed sector z-score statistics from the live scoring snapshot alone (mirroring `scripts/score_live.py`'s existing convention for the old model) instead of using the statistics the model was actually trained on. This fed the model features normalized against a completely different reference distribution than training, and produced wildly miscalibrated predictions (P/E "high" bands in the thousands for effectively every ticker). Fixed by adding `fit_sector_zscore_stats()`/`apply_zscore_stats()` to `ml_comps_model.py`, which split fit and transform so training-time stats are persisted in the model bundle (`{model, zscore_stats, feature_cols}`) and applied unchanged at scoring time. **This same skew likely affects the existing `score_live.py` for the old ret_1y model too** — out of scope to fix here, but worth flagging if that model's live scores are ever scrutinized.
2. **Full-history vs. rolling-window final fit.** Even after fix #1, predictions were still poorly calibrated at the tails. Root cause: the final production model was trained on the *entire* 1985-2026 history in one shot, while the Phase 3 gate only ever validated 5-year rolling training windows — a genuine mismatch between what was validated and what shipped. Fixed by adding `--rolling-years` (default 5) to `train_ml_comps_valuation.py`, matching `train_model.py`'s own existing convention for the old model, which this new script had initially deviated from.
3. **Residual tail extrapolation.** Even correctly windowed, tree-based quantile regression occasionally extrapolates to implausible multiples for unusual feature combinations (a handful of tickers, observed up to 1000x+ pre-clip). Added a `MAX_MULTIPLE = 500` sanity cap in `score_ml_comps_valuation.py` on the predicted multiple before converting to a price, since an unbounded "fair value" figure reaching the UI would be a real trust problem — this is a targeted fix for a demonstrated failure mode, not speculative defensive programming.

After all three fixes, spot-checking AAPL/MSFT/JPM/XOM: `ml_fair_price_mid` landed within 10-35% of current price for all four (well inside the plan's 0.3x-3x plausibility bar). Full-universe run: 2,122/2,653 tickers scored `ok`, 515 `no_price_basis` (no positive EPS or FCF/share to convert a multiple into a price), 15 `error`, 1 `insufficient_peers`.

## Phase 5 — Model metadata

`scripts/report_ml_comps_history.py` — queries `ml_model_metadata` for retrain history (RMSE vs baseline, coverage, active version). Lightweight by design, no MLflow.

## Phase 6 — API

`api/av_router.py`'s `/av-fundamentals/{ticker}` gets 13 new `ml_fair_*` fields + 2 metadata fields, sourced from `ml_comps_valuation`, `null` when unscored. No changes to existing fields/behavior.

## Phase 7 — Frontend

New `ValuationRangeBand.tsx` component + a gated "ML Fair Value (Experimental — Comps Model)" section in `FundamentalsViewer.tsx`, rendered only when `ml_fair_price_mid != null`. Does not touch the existing goal-price rendering.

Verified live: `npm run dev` + `uv run uvicorn api.main:app --port 8000`, loaded AAPL in a real browser via Playwright. The panel renders "Fair Price $210.30 – $459.50 (mid $304.14)" alongside P/E and P/FCF implied-multiple bars, each with a current-value marker; 0 console errors; existing Price Targets/Valuation Multiples sections render identically to before. One incidental finding during verification: a stale uvicorn process from a prior session (dated 2026-07-19) was still holding port 8000, silently serving pre-change code — killed and restarted to get an accurate check. Worth remembering when verifying any API change in this repo: confirm you're hitting a freshly started server, not a long-lived leftover one.

## Phase 8 — Monitoring

`notebooks/ml_comps_valuation.ipynb` — coverage-over-time, model-vs-baseline RMSE over time, fold win rate by year, and feature importance from the active production models. `scripts/validate_ml_comps_valuation.py` now also writes `docs/ml_comps_validation_folds.csv` (fold-level results across all 3 multiples) so the notebook can plot time-series diagnostics without re-running the ~85 min walk-forward gate on every execution. Simplification documented in the notebook itself: point-level predicted-vs-actual calibration (not just fold-level aggregates) and full SHAP stability across folds are deferred — the fold-level series already carry the signal that matters (is the model still winning per-period, is it still calibrated) without persisting a heavier per-row prediction log.

Re-ran the full gate as part of producing this artifact (same 36 folds/multiple, 1990-2026): result unchanged, P/E and P/FCF pass, EV/EBITDA misses by the same margin — confirms the Phase 3 result is stable, not a one-off.

Executed via `jupyter nbconvert --to notebook --execute` — all 4 plot cells produced non-empty images, zero errors.

---

## Phase 9 — Go/No-Go for touching `goal_pe`/`goal_low`/`goal_high` (NOT STARTED, OUT OF SCOPE)

Explicitly not part of this plan. Would require, at minimum, before even opening this conversation:

- N consecutive months of live-scored `ml_comps_valuation` predictions with maintained calibration (coverage staying in the 70-90% band, not drifting).
- A forward comparison of `ml_fair_price_mid` vs. `goal_low`/`goal_high` accuracy against realized future prices, over a real holdout period — not backtested with hindsight.
- Explicit sign-off, given the existing model in this module already shows what happens when a good-looking backtest substitutes for a real gate.
