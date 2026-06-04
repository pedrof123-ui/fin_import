# ML Model Validation Plan

## Objective

Determine whether the XGBoost model in `notebooks/fundamentals_alpha.ipynb` produces
enough genuine out-of-sample alpha to replace the `rf_vw_gr_top_n_25` composite score
as the production strategy.

**Decision gate:** ML must beat the composite score by ≥ 2% annualised CAGR on the
same period, same universe, same portfolio construction rules, with stable recency
performance, before a live replacement is considered.

---

## Current State

| Item | Status |
|------|--------|
| NW ICIR bug fixed | Done (commit 98b78ab) |
| Live scoring $300M filter fixed | Done (commit 98b78ab) |
| Walk-forward uses overlapping 1-year returns | **Not fixed — inflates CAGR** |
| ML vs composite comparison | **Not done — different time periods** |
| Composite backtest period | 211 months (~2005–2026) |
| ML walk-forward period | 436 months (~1984–2026) |
| Survivorship bias | Not quantified |

### Why the current +31.92% ML CAGR cannot be trusted

1. **Wrong return metric**: the walk-forward reports mean of monthly overlapping 1-year
   returns, not a compounded monthly equity curve. Consecutive months share 11/12 of the
   same return window, inflating the annualised figure.

2. **Non-overlapping periods**: ML covers 1984–2026 (436 months); the composite backtest
   only covers 2005–2026 (211 months). The 1990s and 2000–2003 tech bust were exceptionally
   favorable for value/quality factors — the ML captures those decades, the composite does not.
   The apparent outperformance is at least partly a period effect.

3. **Corrected NW ICIR ≈ 0.35**: after the bug fix, the NW-adjusted ICIR falls below the
   0.5 "practically significant" threshold, signalling the ML factor is weaker than it appeared.

---

## Phase 1 — Fix the walk-forward equity curve

**What:** Replace the mean of monthly overlapping 1-year returns with a proper compounded
monthly equity curve using 1-month forward returns.

**Why:** The current metric is not tradeable. A portfolio rebalanced monthly holds each
position for one month, so the relevant return is `ret_1m`, not `ret_1y`. Using 1-year
overlapping returns inflates the CAGR and produces an autocorrelated, non-investable series.

**Implementation (in `fundamentals_alpha.ipynb`):**

1. Add `ret_1m` as a forward return target (already supported by `compute_forward_returns`
   with `horizons={"ret_1m": 1}`).
2. Modify the walk-forward loop to:
   - Predict scores using the model trained on `ret_1y` (signal horizon stays 1 year)
   - Measure actual realised return using `ret_1m` (holding period = 1 month)
   - Compound monthly returns into a CAGR: `(1 + r1) × (1 + r2) × … ^ (12/n) - 1`
3. Report compounded CAGR, annualised vol, Sharpe, and max drawdown.

**Note:** The model is still trained to predict 1-year returns (signal horizon). The change
is only in how realised performance is measured and aggregated.

**Acceptance criteria:**
- [ ] Walk-forward reports compounded monthly CAGR (not mean of 1-year returns)
- [ ] Sharpe and max drawdown computed from monthly return series
- [ ] NW ICIR computed on 1-month IC values (lags = 0 or 1, not 11)

---

## Phase 2 — Align comparison periods

**What:** Run the composite score (`gr`) walk-forward over the same 436-month period
as the ML model, so both are evaluated on identical history.

**Why:** Comparing ML over 1984–2026 vs composite over 2005–2026 is not a valid test.
The full expanded history (back to 1983) is in `historic_fundamentals.duckdb` for both
strategies — there is no reason the composite backtest should start in 2005.

**Implementation:**

Option A (preferred): Add a composite score baseline to the ML walk-forward notebook.
- At each walk-forward step, compute the composite score on the same training cross-section
- Select the top 20% by composite score alongside the top 20% by ML score
- Report both equity curves on the same chart and table

Option B: Extend the existing `run_backtest.py` / `run_baselines.py` to cover 1984–2026
and re-run to produce updated `backtest_results.md`.

**Acceptance criteria:**
- [ ] Composite score CAGR computed over the same 436-month window as ML
- [ ] Side-by-side performance table: ML vs composite, same period, same universe

---

## Phase 3 — Recency check

**What:** Break the 436-month OOS period into rolling 5-year windows and measure whether
ML alpha over the composite is stable, growing, or decaying.

**Why:** A model that learned the 1990s well but has degraded since 2015 would still show
strong full-period numbers. We need recent alpha to trust live deployment.

**Implementation (in notebook):**

For each 5-year window (1990–1995, 1995–2000, …, 2020–2026):
- Compute: ML CAGR, composite CAGR, ML − composite excess return, ML ICIR

**Acceptance criteria:**
- [ ] ML excess return over composite is positive in at least 4 of the last 5 years
- [ ] No obvious trend of decay in the most recent 3-year window

---

## Phase 4 — Portfolio-level backtest with production setup

**What:** Apply the same portfolio construction as `rf_vw_gr_top_n_25` (vol weighting,
regime filter, sector cap, top-25 fixed) to ML scores and measure CAGR / Sharpe / MaxDD.

**Why:** The walk-forward uses top-20% equal weight with no regime filter. That is a
different strategy from what would actually replace production. The comparison must use
identical portfolio construction.

**Implementation:**

Extend the walk-forward loop to produce a `top_n_25` ML portfolio alongside the existing
`top_pct_20` output:
- Select top 25 stocks by ML score (with 25% sector cap)
- Apply inverse-vol weighting (capped 10%)
- Apply SPY 12m regime filter
- Compound monthly returns

**Acceptance criteria:**
- [ ] ML `rf_vw_xgb_gr_top_n_25` CAGR ≥ composite `rf_vw_gr_top_n_25` CAGR + 2%
- [ ] ML Sharpe ≥ composite Sharpe
- [ ] ML Max DD not worse than composite Max DD by more than 3%

---

## Phase 5 — Survivorship bias quantification

**What:** Estimate the upward bias in all backtest results caused by excluding
delisted/bankrupt companies from the universe.

**Why:** Stocks that went bankrupt or were acquired at distressed prices typically had
poor fundamentals — exactly what value/quality models avoid. Excluding them makes the
strategy look better than it would have been in practice.

**Implementation:**

1. Identify tickers present in `historic_fundamentals.duckdb` that are no longer active.
2. Check what their final price outcomes were (acquired at premium vs distressed/zero).
3. Estimate the fraction of the universe in each period that was delisted.
4. Apply a conservative haircut to reported CAGR based on delisting rate ×
   average delisting return.

This is a quantification exercise, not a data reconstruction. We are not re-importing
delisted data — just estimating the bias magnitude.

**Acceptance criteria:**
- [ ] Survivorship bias estimated in percentage points of CAGR
- [ ] Adjusted ML CAGR still beats adjusted composite CAGR by ≥ 2%

---

## Phase 6 — Decision and paper trading

**What:** If Phases 1–5 pass acceptance criteria, run both strategies in parallel for
3 months on paper before any live switch.

**Why:** Live market conditions (transaction costs, market impact, execution slippage)
are not captured in backtests. A parallel paper run confirms the live scoring pipeline
produces sensible portfolios before capital is committed.

**Implementation:**

- `score_live.py --use-model` already supports XGBoost scoring
- Run both `gr` and `xgb_gr` variants side by side each month
- Track: portfolio overlap, score correlation, actual realised 1-month returns

**Acceptance criteria:**
- [ ] Phases 1–5 all pass
- [ ] 3 months of parallel paper trading with ML portfolio performing in line with backtest
- [ ] No data quality or scoring anomalies observed

---

## Tracking

| Phase | Description | Status | Blocking |
|-------|-------------|--------|---------|
| 1 | Fix walk-forward equity curve | Not started | Nothing |
| 2 | Align comparison periods | Not started | Nothing |
| 3 | Recency check | Not started | Phase 1 |
| 4 | Portfolio-level backtest | Not started | Phases 1–2 |
| 5 | Survivorship bias estimate | Not started | Nothing |
| 6 | Paper trading | Not started | Phases 1–5 |

---

## Files

| File | Role |
|------|------|
| `notebooks/fundamentals_alpha.ipynb` | Main notebook — Phases 1, 2, 3, 4 implemented here |
| `scripts/score_live.py` | Production scorer — Phase 6 uses `--use-model` flag |
| `scripts/run_backtest.py` | Composite backtest runner — Phase 2 Option B |
| `docs/backtest_results.md` | Reference composite metrics (currently 211 months only) |
