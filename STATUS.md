# Project Status — Fundamentals Alpha + FinView

## Industry AI Researcher (complete, 2026-07-27)

New FinView tab: cross-company industry research, complementing the existing single-name AI
Research tab. Pick an AV `industry` (e.g. "Semiconductors" — deliberately finer-grained than
sector, since a sector like Technology spans industries on very different cycles: 12 sectors vs.
145 industries in the current DB) or supply a custom ticker basket. Full spec, architecture, and
phased build record: `features/industry_research/SPEC.md` and `features/industry_research/PLAN.md`
(all 8 phases complete, extensively live-verified, not just unit-tested).

### Architecture — map-reduce multi-agent pipeline

```
resolve members (top-8 by market cap, or custom basket)
  -> gather data in parallel (transcripts, beat/miss, financials, estimates, aggregates, web search)
  -> Stage 1 MAP: per-company Earnings Digest sub-agent, fanned out in parallel
  -> Stage 2 REDUCE: Trends & Developments + Risks & Outlook specialists, parallel
  -> Stage 3 SYNTHESIZE: Chief Industry Strategist (executive summary + ranked ideas)
  -> deterministic Python rendering (appendix tables + ranked-ideas numeric join)
```

Every number in the final report — valuation medians, EPS surprises, revision momentum, the
ranked-ideas table's valuation-vs-industry and revision-momentum columns — is computed in Python
from the database. The LLM only writes prose, stance/catalyst/risk, and the executive summary.

### Infrastructure added

- `api/industry_data.py` — data layer: `list_industries`, `resolve_members`, industry aggregates,
  member financials, beat/miss, estimates, transcripts, web search. Raw-fetch/pure-formatter split
  throughout so the LLM-context text and the markdown appendix tables share one fetch instead of
  double-hitting Alpha Vantage for the same tickers in one report generation pass.
- `api/industry_research_router.py` — the 3-stage pipeline, deterministic tables, DuckDB cache
  (`industry_research_cache.duckdb`, 24h TTL), background-task/status/cancel scaffolding
  (structurally mirrors `research_router.py`), 5 new endpoints under `/industry-research/*`.
- 4 new prompts (`api/prompts/industry_{company_digest,trends,risks,chief}.md`).
- `web/components/IndustryResearchViewer.tsx` — industry picker with member counts, custom-basket
  override, model picker, live status bar, and clickable ticker cells generalized across *every*
  appendix table (not just ranked ideas) via a ticker-shape regex on table cells.
- 105 new tests across 3 files (`test_industry_data.py`, `test_industry_research_router.py`,
  `test_industry_research_orchestration.py`), all passing, zero regressions in the existing suite.

### Grain guarantee — industry, never sector

Hard requirement, tested and grep-audited: member resolution filters `UPPER(co.industry)=?` only
(no OR-fallback to sector like the single-name researcher's `_peer_df` has), aggregates read
`sector_stats WHERE group_type='industry'` only. A company with a null/blank industry
classification is excluded, never sector-substituted. Verified live: Semiconductors and
Software - Infrastructure (both under the Technology sector) resolve to disjoint member sets and
distinct aggregate figures.

### Key findings / bugs fixed (live, not hypothetical)

- `pandas.NA` (not `None`/float `NaN`) is how DuckDB INTEGER columns with nulls surface in pandas
  after `.df()` — crashed `int(pd.NA)` in estimate-revision formatting until caught by a shared
  `is_missing()` helper used everywhere a DB value is formatted.
- `google/gemini-3.5-flash` occasionally emits the literal two-character sequence `\n` inside a
  structured-output string field instead of a real newline — sanitized before rendering
  (`_sanitize_prose` for narrative sections, `_sanitize_table_cell` for table cells, which can't
  contain a raw newline without breaking the table).
- BBBY (the already-documented contaminated ticker from the survivorship-bias analysis below —
  reassigned post-bankruptcy) has industry set to the literal string `"None"`, which slipped past
  the NULL/blank filter and appeared as a selectable "NONE (1)" entry in the industry picker until
  excluded defensively.
- TSM's `current_pe` in `pe_stats` is 1.1 (vs. plausible ~25-35x peers), likely an ADR-ratio
  handling issue in `historic_fundamentals` — surfaced live in a real report's ranked-ideas table,
  flagged for separate investigation, not fixed here (pre-existing, out of scope for this feature).

### Verification

Live-verified at every layer, not just unit-tested: a real 3-4 company digest fan-out and full
Stage 1-3 pipeline with a real LLM producing internally-consistent output (e.g. correctly
aggregating "6 of 8 companies raised guidance" across digests rather than fabricating a pattern);
a full HTTP round-trip with cache-hit confirmation; and a full 8-company Semiconductors report
generated through the actual browser UI (~130s, within the estimated 60-150s), with working
Cancel, retry-after-cancel, and click-to-navigate from any ticker cell to that ticker's single-name
AI Research tab.

---

## Phase 11 Go/No-Go Gate — CLOSED, Composite Accepted, XGBoost Retired (2026-07-20)

Closed the go/no-go gate that had been open since May (`features/historic_fundamentals/fundamentals_alpha_action_plan.md` Phase 11 — `reports/model_acceptance_checklist.md`/`model_usage_decision.md` never existed until now). Triggered by a chain of findings this session: a train/serve z-score bug fix in `score_live.py` → discovering the same code pattern would be *wrong* to fix in `run_backtest.py` (single static model applied across ~40 years, era-mismatched normalization) → building a genuine walk-forward portfolio backtest to answer the question honestly → running Phase 9 robustness checks on the winner.

**Decision**: composite factor score (value+quality+momentum, no ML) = **Category 3, Paper Trading** — already what's live (`vw_gr_top_n_25`), now formally ratified with evidence. XGBoost `ret_1y` model = **Category 1, Research Only** — fails OOS rank IC (-0.017) and underperforms composite on every risk-adjusted metric under honest walk-forward testing (top_n_25: XGBoost Sharpe 0.73/-61.7% MaxDD vs. composite Sharpe 0.92/-50.1% MaxDD). No live behavior change: `score_live.py` already defaulted to composite; the pipeline never passed `--use-model`.

**Composite passed robustness testing** (`docs/composite_robustness_report.md`): stable-to-improving Sharpe across market-cap cuts (300M-5B), edge survives up to 100bps TC, no small-cap/illiquidity dependency.

**Two caveats disclosed, not resolved, in the acceptance checklist:**
- Sector-neutral scoring underperforms raw scoring (Sharpe 0.85 vs 0.94) — real share of the edge is sector positioning, not pure stock selection.
- `docs/composite_ic_analysis.md`: monthly rank IC is small-but-positive (+0.014 to +0.035, ICIR ~0.2-0.3) and top-25/50 beats bottom-25/50, but this **inverts** at top-100+/decile cuts (bottom outperforms top). The traded configuration (top_n_25) sits in the positive zone, but the score is not a broadly monotonic signal — open question, flagged for follow-up, not blocking.

Full detail: `reports/model_acceptance_checklist.md`, `reports/model_usage_decision.md`.

---

## ML Comps Valuation Model (complete, 2026-07-20; P/S extension complete, 2026-07-21)

Cross-sectional peer-comps ML model predicting a fair P/E, P/FCF, and P/S multiple for each stock from its fundamentals vs. sector peers — additive to the existing self-referential `goal_pe`/`goal_low`/`goal_high` (which compare a ticker to its *own* multiple history, not peers). Full phased build record: `features/historic_fundamentals/ml_comps_valuation_plan.md`.

### Approach

- 4 candidate multiples (P/E, EV/EBITDA, P/FCF, P/S — P/S added 2026-07-21), one XGBoost quantile-regression model each (`reg:quantileerror`, `quantile_alpha=[0.1,0.5,0.9]`) predicting a fair low/mid/high range in a single fit.
- Features: `monthly_pe`'s existing growth/margin/quality/leverage columns, sector-relative z-scored (fold-safe fit/transform split, not the live-batch self-referential z-scoring `score_live.py` uses).
- Fair price = predicted multiple × the ticker's own EPS/FCF-per-share/revenue-per-share.

### Validation gate (walk-forward, 36 folds/multiple, 1990-2026)

| Multiple | RMSE improvement vs. naive sector-median baseline | Fold win rate | Coverage p10–p90 | Result |
|---|---:|---:|---:|---|
| P/E | +18.3% | 100% (36/36) | 74.9% | PASS |
| EV/EBITDA | +14.7% | 100% (36/36) | 74.1% | FAIL (missed 15% bar by 0.3pp) |
| P/FCF | +18.7% | 100% (36/36) | 73.1% | PASS |
| P/S | +23.6% | 100% (36/36) | 74.7% | PASS (best of the 4, added 2026-07-21) |

P/E, P/FCF, and P/S are trained/scored in production; EV/EBITDA remains excluded. Result reproduced identically on a second full rerun (deterministic, fixed seeds). Model beat the naive baseline in 100% of individual folds across 36 years — the fold-level check this gate was specifically designed to enforce, not just an aggregate number.

Adding P/S also closed a real coverage gap: full-universe scoring went from 2,122/2,653 tickers `ok` (515 `no_price_basis`) to 2,518/2,653 `ok` (119 `no_price_basis`) — P/S rescues tickers with negative/zero earnings or FCF (common for early-stage or cyclical-trough names) since revenue is defined almost everywhere. P/BV and PEG were also considered but not pursued: P/BV needs a per-sector model (book value is near-meaningless outside financials/industrials, would likely repeat EV/EBITDA's near-miss as a single universe-wide fit) and PEG doesn't fit this model's "multiple × ticker's own fundamental = fair price" mechanism at all.

### Infrastructure added

- `historic_fundamentals/ml_comps_model.py` — feature assembly, quantile model fit/predict, walk-forward harness, fit/transform-split sector z-scoring
- `ml_comps_valuation` + `ml_model_metadata` tables in `historic_fundamentals.duckdb`
- `scripts/{validate,train,score}_ml_comps_valuation.py`, `scripts/report_ml_comps_history.py`
- `api/av_router.py` — 16 new `ml_fair_*` fields in `/av-fundamentals/{ticker}`, additive, `null` when unscored
- `web/components/ValuationRangeBand.tsx` + new "ML Fair Value (Experimental)" panel in `FundamentalsViewer.tsx`, verified live in a browser
- `notebooks/ml_comps_valuation.ipynb` — coverage/RMSE/win-rate-over-time monitoring, executes end-to-end
- Wired into `scripts/run_pipeline.py` behind `--enable-ml-comps` (**opt-in, not yet enabled in the production cron** — that's a separate deploy decision)

### Key findings

- Two real bugs caught before shipping, not caught by the validation gate itself (which only validates the model in isolation): (1) recomputing sector z-score stats from the live scoring batch instead of persisting training-time stats caused wildly miscalibrated predictions (P/E "high" bands in the thousands for effectively every ticker); (2) training the final production model on the full 40-year history instead of the gate-validated 5-year rolling window caused the same failure mode even after fixing (1). Both fixed — see plan doc for full detail.
- The existing `score_live.py` for the ret_1y model likely has the same z-score train/serve skew bug (#1 above) — not fixed here (out of scope), flagged for future attention if that model's live scores are ever scrutinized.
- Not wired to replace `goal_pe`/`goal_low`/`goal_high` — that's an explicit, deliberately un-started future decision (see plan doc's Phase 9).
- P/S predictions can hit extreme values for very-low-revenue-base names (e.g. ACHR mid ~293x, current ~1909x) — the existing `MAX_MULTIPLE=500` sanity cap (added for the original 3 multiples) handles this correctly without any P/S-specific change.

---

## BCD Mispricing Filter (complete, 2026-06-29)

Hard portfolio filter applied in `scripts/score_live.py` based on Bakshi-Chen 2001 structural valuation model.

### Formula (BCD-lite)

```
P_model = ttm_eps × (1 + earn_growth_1yr) / (DGS30 + 5.5% ERP - 3% terminal_growth)
Misp    = (price - P_model) / P_model   [clipped to ±3]
```

Require `bcd_misp ≤ 0` (structurally underpriced only). NULL = excluded.

### Backtest impact (post-2010, vw_gr_top_n_25)

| Variant | CAGR | Sharpe | MaxDD | PF | R-Exp |
|---------|------|--------|-------|-----|-------|
| baseline | 12.66% | 0.754 | -35.5% | 1.63 | 0.91% |
| bcd_hard | **15.66%** | **0.919** | **-28.0%** | **1.97** | **1.35%** |

### Infrastructure added

- `features/bcd/signal.py` — `compute_bcd_lite_misp()` function
- `monthly_pe.bcd_misp` — 433,133 rows populated (84.8% of ttm_eps>0 rows)
- `market_signals` table — monthly punder (420 months; avg=61.9%)
- DGS30 in `trade_systems/data/fred.duckdb`; `dcf/data.py load_risk_free_rate_30y()`
- DCF model now uses DGS30 as risk-free rate (was DGS10)
- `scripts/score_live.py _apply_bcd_filter()` — runs when `--guardrails` is on (default)
- `scripts/backfill_bcd_misp.py` — backfill + punder computation
- `scripts/backtest_bcd_filter.py` — comparison script (baseline vs bcd_hard vs bcd_soft)
- `scripts/validate_bcd_signal.py` — Phase 3 IC/ICIR/autocorr/punder validation

### Key finding: use as filter, not ML feature

Standalone NW-ICIR=-3.67 (strong signal) but 0.82 Spearman correlation with pe_ratio makes it redundant in XGBoost (NW-ICIR drops 2.26→0.95). Used as a pre-scoring hard filter instead.

---


## FinView — Sector & Industry Dashboard (complete, 2026-06)

Web analytics platform at `web/` (Next.js, port 3000) with 8 tabs:

| Tab | Description |
|-----|-------------|
| Screener | 18-metric stock filter with sortable results |
| Sector | Sector/industry rankings, VMQ composite score, 5yr history chart, company drill-down |
| AV Data | Alpha Vantage income/balance/cashflow viewer |
| AV DCF | DCF valuation from AV data |
| Fundamentals | PE/FCF/EV history, goal prices, valuation signals |
| AI Research | AI-generated equity research report |
| Earnings | Analyst EPS + revenue consensus estimates |
| XBRL | SEC XBRL financial statements (appears after download) |

### Sector dashboard — VMQ composite score methodology

Cross-sectional z-scores (capped ±2.5) of three factors, weighted:

- 35% Value: EV/EBITDA vs own 5yr historical median (avoids cross-sector PE comparison distortions)
- 35% Momentum: trailing 1yr revenue growth median
- 30% Quality: ROIC median

Score > 0.2 = undervalued/improving (emerald), < -0.2 = expensive/deteriorating (rose).

### sector_stats table (historic_fundamentals.duckdb)

43,611 rows (5,231 sector rows + 38,380 industry rows). Columns added in this session:
`gross_margin_median`, `operating_margin_median`, `fcf_margin_median`, `debt_to_ebitda_median`, `interest_coverage_median`

Rebuild: `uv run scripts/rebuild_sector_stats.py`

---


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
