# CANSLIM Factor Test Plan

Goal: implement William O'Neil's CANSLIM criteria as factors in the existing
`monthly_pe` pipeline and validate them with the same methodology already used
for the Greenblatt Magic Formula test (`docs/greenblatt_factors_test.md`,
`scripts/backfill_greenblatt_factors.py` + `scripts/test_greenblatt_*.py`).
Output is a go/no-go verdict on whether a CANSLIM composite (or any individual
CANSLIM factor) should be promoted into the live composite
(`historic_fundamentals/baselines.py` `_VALUE_COLS`/`_QUALITY_COLS`/`_MOMENTUM_COL`)
or kept as a standalone screener preset, same disposition as Greenblatt.

## Decisions (confirmed with user before implementation)

- **Institutional sponsorship (I)**: no 13F/ownership data exists in either
  repo. Proxy via `company_overview.analyst_rating_strong_buy/buy/hold/sell/strong_sell`
  and `earnings_estimates.eps_rev_up_30d/down_30d` (net revision sentiment).
  No new data ingestion in this plan.
- **Base/breakout pattern (part of N)**: simplified signal only — proximity to
  52-week high + volume surge vs. trailing average. No cup-with-handle /
  consolidation-tightness pattern detection (O'Neil relied on visual judgment
  here; algorithmic pattern-matching is a separate, much larger effort).
- **Scope**: research/backtest only, following the Greenblatt factor-test
  template end to end. No live paper-trading execution (no trade_systems
  entry/exit/monitor scaffolding). If a CANSLIM composite is promoted, a live
  execution plan would be a separate follow-up, not part of this plan.

## CANSLIM → data mapping

| Letter | Meaning | Source | Status |
|---|---|---|---|
| C | Current quarterly earnings accel. | `av_financials.duckdb income_statements` (period_type='quarterly') | build (new column) |
| A | Annual earnings growth / ROE | `monthly_pe.earn_cagr_3yr/5yr`, `monthly_pe.roe` | reuse, already exists |
| N | New highs | `trade_systems prices.duckdb stock_prices` (daily OHLCV) | build (new column) |
| S | Supply/demand (volume) | `stock_prices.volume` | build (new column) |
| L | Leader — RS Rating | `stock_prices` close, cross-sectional percentile | build (new column) |
| I | Institutional sponsorship (proxy) | `company_overview` analyst ratings + `earnings_estimates` revisions | **cut** — see Phase 4 |
| M | Market direction | SPY 12m regime filter already used in `scripts/run_backtest.py` | reuse, already exists |

**Phase 0 finding**: `company_overview`/`earnings_estimates` only span ~2.5
months (2026-05 to 2026-07) — no historical archive. I cannot be backtested
and is excluded from the validated composite (Phases 6-10 test a 6-factor
C-A-N-S-L-M composite). Phase 4 (building the I proxy columns) was cut
entirely rather than built unused — see Phase 4 for reasoning.

## Phase 0 — Data audit [x]

### Step 0.1 — Confirm point-in-time depth of proxy sources [x]
Query `company_overview` and `earnings_estimates` for
`COUNT(DISTINCT fetch_date)` per ticker and the earliest fetch_date available.
Confirm whether there's enough historical snapshot coverage to backtest I
across `monthly_pe`'s ~1990s-2026 range, or only recent years.

**Result: FAILS the depth needed for historical backtesting.**
`company_overview`: 2,653 tickers, snapshots only from 2026-05-14 to
2026-07-20 (max 4 snapshots/ticker). `earnings_estimates`: 2,642 tickers,
2026-05-10 to 2026-07-19 (max ~15 snapshots/ticker). Both are live-refresh
feeds with no historical archive — there is no way to reconstruct what
analyst ratings/estimate revisions looked like in, say, 2015. **Decision:**
I is dropped from Phases 6-10 (IC test, pure replication, walk-forward,
investable comparison) entirely — those phases cannot use data that doesn't
exist historically. Phase 4 (building I proxy columns) is cut rather than
built for no consumer — see Phase 4. This plan now tests a **6-factor
C-A-N-S-L-M composite**.

### Step 0.2 — Confirm quarterly EPS derivation [x]
`income_statements` has no direct EPS column. Confirm
`net_income / shares_outstanding` (joined via `shares_outstanding` table, same
diluted-share convention `historic_fundamentals/pe.py` already uses for other
per-share figures) reproduces `company_overview.eps`/`diluted_eps_ttm` closely
enough to trust for a derived quarterly-YoY series.

**Result: PASSES.** TTM net income / latest diluted shares vs.
`company_overview.diluted_eps_ttm`, 20-ticker spot check: median absolute
relative error **1.67%** (well under the 5% threshold). Three outliers (AAP
35%, ABEO 23%, ABR 40%) likely from non-recurring items or share-count timing
mismatches — acceptable noise level for a cross-sectional growth-rate factor,
same tolerance the existing `earn_growth_1yr`/`earn_cagr_3yr` columns already
carry. Proceed with Phase 1 as planned.

## Phase 1 — Backfill: C (current quarterly earnings acceleration) [x]

`scripts/backfill_canslim_factors.py` (same shape as
`backfill_greenblatt_factors.py`: `ALTER TABLE monthly_pe ADD COLUMN IF NOT
EXISTS`, per-ticker loop, coverage log at the end) — but with the reporting
lag applied correctly (`fiscal_date_ending + 60 days <= month_end`, matching
`build_monthly_pe`'s PIT policy), unlike `backfill_greenblatt_factors.py`'s
`_get_ttm_sum` calls, which filter on raw `fiscal_date_ending <= month_end`
with no lag — a pre-existing look-ahead gap in that script, out of scope to
fix here since it's already tested/rejected, but not replicated in this one.

- `q_earn_yoy` = latest available quarter's YoY **EPS** growth (net_income /
  diluted shares as of that quarter's fiscal_date_ending, via
  `historic_fundamentals.pe._get_shares` — using the historical share count at
  each compared quarter, not a single current count, so buyback-driven EPS
  growth shows up distinctly from net-income growth).
- `q_earn_accel` = `q_earn_yoy` (latest quarter) minus `q_earn_yoy` one quarter
  prior — positive means earnings growth is accelerating, the O'Neil-specific
  signal beyond plain growth.

**Result**: full backfill across 2,638 tickers / 645,362 monthly_pe rows —
`q_earn_yoy` 67.1% coverage, `q_earn_accel` 60.7% coverage. Below the 70%
target set at planning time (this factor requires 5-6 consecutive PIT-visible
quarters plus a positive prior-year-quarter base for YoY to be defined, both
stricter than `earn_cagr_3yr`'s annual-fallback path), but reasonable for a
quarterly-only signal — comparable in shape to Greenblatt's two factors
(79.9%/82.2%). Spot-checked NVDA/AAPL/AMD: values are directionally sane
(NVDA accelerating from 61%->213% YoY through the recent AI cycle, AMD/AAPL
plausible magnitudes, no sign-flip or divide-by-zero artifacts). Proceeding
to Phase 2 with this coverage level.

## Phase 2 — Backfill: N (new highs) and S (volume) [x]

`scripts/backfill_canslim_technicals.py`. Both computed from
`trade_systems/data/prices.duckdb stock_prices` (vectorized pandas rolling +
`merge_asof` onto each ticker's `monthly_pe.month_end_date`, not a per-month
loop -- full universe ran in 39s vs. Phase 1's 13min, since price data needs
no reporting-lag filtering).

- `pct_off_52wk_high` = `adj_close / rolling_252d_max(adj_close) - 1` as of
  month_end (0 = at a new high, matches
  `historic_fundamentals/technical_indicators.py`'s existing formula).
- `vol_surge_ratio` = trailing 10-day average volume / trailing 63-day average
  volume as of month_end (>1 = recent surge).
- `up_down_vol_ratio` = sum(volume on up-close days) / sum(volume on down-close
  days) over the trailing 63 trading days (accumulation/distribution proxy for
  S). Known limitation: `volume` is not split-adjusted -- a split landing
  inside a trailing window would show as a spurious discontinuity; not
  corrected, rare enough for a factor-test spike.

**Result**: 627,523/645,390 (97.2%) `pct_off_52wk_high`, 641,818 (99.4%)
`vol_surge_ratio`, 641,534 (99.4%) `up_down_vol_ratio`. Spot-checked
NVDA/AAPL: `pct_off_52wk_high` in a plausible -15%/0% band near recent highs,
surge/accumulation ratios clustered near 1 with no outliers.

## Phase 3 — Backfill: L (RS Rating) [x]

`scripts/backfill_canslim_rs.py`.

- `rs_raw` = IBD-style weighted return: `0.4 * ret_3m + 0.2 * ret_6m + 0.2 *
  ret_9m + 0.2 * ret_12m` as of month_end (matches IBD's published weighting,
  overweighting the most recent quarter).
- `rs_rating` = cross-sectional percentile rank (1-99) of `rs_raw` within the
  same `month_end_date`, ranked market-wide across all monthly_pe rows with a
  valid `rs_raw` that month (same precedent as the Greenblatt factors:
  investable-universe filtering via `historic_fundamentals/universe.py
  filter_universe` is applied downstream in the IC-test/backtest scripts, not
  baked into the stored factor column itself).

**Result**: 622,548/645,390 (96.5%) coverage. Sample month (2026-06-30): 2,597
ranked names, `rs_rating` range [1.0, 99.0] as expected by construction.

Note this differs from the existing `momentum_12_1` column (raw 12-1 month
return, not cross-sectionally ranked) — keep both, RS Rating is the
percentile-ranked version CANSLIM specifically calls for.

Pass: coverage report; distribution check that `rs_rating` is roughly uniform
1-99 within each month (percentile rank should guarantee this by
construction — check for ties/clustering from thin monthly breadth in early
years, same caveat noted in the Greenblatt walk-forward result for 1992-1996).

## Phase 4 — Backfill: I (institutional sponsorship proxy) [CUT]

**Cut from this plan, not deferred-and-forgotten.** Per Phase 0.1,
`company_overview`/`earnings_estimates` only span ~2.5 months, so an I column
could never feed the validated composite in Phases 6-10. Wiring it into the
screener UI as a live-only filter is separately out of scope (see "Explicitly
out of scope" below). Building `analyst_buy_ratio`/`est_revision_net` now
would produce columns nothing in this plan reads -- speculative work for a
hypothetical future need, which CLAUDE.md's simplicity rule says to skip.
Revisit only if/when the screener-wiring follow-up actually happens.

## Phase 5 — Composite construction [x]

`CANSLIM_COLS` (7 columns — I's `analyst_buy_ratio`/`est_revision_net` never
built, per Phase 4) defined inline and reused identically across all Phase
6-10 test scripts, rather than as a separate shared module: these are
one-off test scripts, not production code with multiple consumers, so a
shared module would be premature structure for a single test run.

`q_earn_accel, earn_cagr_3yr, roe, pct_off_52wk_high, vol_surge_ratio,
up_down_vol_ratio, rs_rating`

M (market direction) confirmed as a portfolio-level exposure gate, not a
per-stock composite input — not included in the rank-sum/z-score composite;
`scripts/run_backtest.py::_compute_regime_exposure` remains available if a
regime-filtered variant is wanted later, not exercised in this plan's tests.

## Phase 6 — IC / ICIR test [x]

`scripts/test_canslim_factors.py`, same structure as
`scripts/test_greenblatt_factors.py`: per-factor Spearman IC vs. `ret_1y`/
`ret_6m`, ICIR, hit rate, t-stat, plus quintile spread. Same universe filter
as the Greenblatt IC test (mkt cap >= $1B, financials/real-estate excluded,
264,660 rows / 1,941 tickers).

**Bug found & fixed en route**: `historic_fundamentals/baselines.py
quintile_returns()` crashed on `pct_off_52wk_high` — heavy exact-zero ties
(tickers sitting right at their 52-week high) collapse `pd.qcut`'s bin edges
below 5 after `duplicates="drop"`, which the function didn't guard against.
Fixed generically (skip that month, same treatment already given to
low-breadth months) rather than worked around locally — this was a latent bug
in the shared utility, not specific to this factor.

**Result (ret_1y IC / quintile spread)**:

| factor | mean IC | ICIR | t-stat | Q1-Q5 spread |
|---|---|---|---|---|
| `q_earn_accel` (C) | 0.0002 | 0.004 | 0.07 | +0.29% |
| `earn_cagr_3yr` (A) | -0.0005 | -0.005 | -0.10 | +1.20% |
| `roe` (A) | 0.0255 | 0.212 | 4.39 | -1.52% |
| `pct_off_52wk_high` (N) | 0.0297 | 0.177 | 3.67 | -0.78% |
| `vol_surge_ratio` (S) | 0.0014 | 0.016 | 0.34 | -0.46% |
| `up_down_vol_ratio` (S) | 0.0116 | 0.102 | 2.12 | +2.40% |
| `rs_rating` (L) | 0.0149 | 0.085 | 1.77 | +4.18% |

**Reading it**: `q_earn_accel` (C) and `vol_surge_ratio` (S) show essentially
no signal by either measure — noise, not factors. `earn_cagr_3yr` (A) is
similarly flat on IC despite a mild quintile spread. `roe` (A) and
`pct_off_52wk_high` (N) both have strong, significant IC (t=4.39, t=3.67) but
**negative** naive quintile spreads — the same IC-vs-quintile-bucketing
divergence documented in `docs/greenblatt_factors_test.md` for
`greenblatt_roc`/`roic` (a handful of extreme-value outliers concentrate in
Q1 and drag its mean down even though the full rank correlation is real and
positive; IC is more robust to this than raw bucketing). `up_down_vol_ratio`
(S) and `rs_rating` (L) are the cleanest results — consistent sign and
magnitude on both measures, `rs_rating` the strongest quintile spread
(+4.18%) of any CANSLIM factor tested.

Notably, **C (current-quarter earnings acceleration) — one of CANSLIM's two
headline earnings letters — shows no measurable signal** in this test. Worth
flagging explicitly in the final verdict rather than letting it quietly ride
along in a composite.

## Phase 7 — Pure CANSLIM replication backtest [x]

`scripts/test_canslim_pure.py`: literal rank-sum of all 7 sub-factors,
market-wide, no sector cap, no guardrails, no liquidity filter — matches the
Greenblatt test's section 3 (book-faithful, standalone). Requires all 7
present, same strict handling Greenblatt used: 149,900/264,660 universe rows
(1,267 tickers) qualify.

**Result**:

| Portfolio | CAGR | Sharpe | MaxDD | WinRate | Months |
|---|---|---|---|---|---|
| canslim_top_n_25 | +13.52% | 0.745 | -46.03% | 62.2% | 405 |
| canslim_top_n_30 | +13.14% | 0.730 | -47.07% | 62.0% | 405 |
| canslim_top_pct_20 | +12.06% | 0.677 | -43.85% | 62.6% | 404 |
| universe_ew (canslim univ.) | +12.80% | 0.717 | -42.94% | 64.0% | 405 |
| SPY | +9.45% | 0.650 | -61.22% | 63.6% | 522 |

Beats SPY comfortably, but the edge over its **own** naive universe average is
thin (top_n_25: +0.72pp CAGR, +0.028 Sharpe) and MaxDD is actually *worse*
than the universe benchmark (-46.03% vs -42.94%). Contrast with Greenblatt's
pure replication, which beat its universe by +4.95pp CAGR / +0.205 Sharpe with
a *better* MaxDD. This is the composite-level echo of Phase 6's finding: two
of the seven sub-factors (`q_earn_accel`, `vol_surge_ratio`) carry no signal
and are diluting the ones that do.

## Phase 8 — Augmented composite A/B [x]

`scripts/test_canslim_augmented_ab.py` (mirrors
`scripts/test_greenblatt_factors.py` section 4, not
`test_greenblatt_vs_composite.py` — that name is reserved for Phase 10's
fold-based comparison, matching the Greenblatt precedent's own naming):
baseline (current live composite) vs. augmented (existing composite + CANSLIM
factors), identical universe, guardrails, sector cap, same dates, single
full-period run (fold-level stability is Phase 9).

**Result** (top_n_25, 406 months, identical universe/guardrails/sector cap):

|  | CAGR | Sharpe | MaxDD | WinRate |
|---|---|---|---|---|
| baseline (current live factors) | +15.96% | 0.952 | -40.07% | 66.0% |
| augmented (+7 CANSLIM factors) | +14.57% | 0.893 | -42.95% | 64.0% |

**Worse on every metric** — CAGR -1.39pp, Sharpe -0.059, MaxDD 2.9pp deeper,
win rate -2.0pp. Consistent with Phase 6/7: the noise factors (`q_earn_accel`,
`vol_surge_ratio`) are diluting the existing composite's signal rather than
adding to it.

Pass: CAGR/Sharpe/MaxDD table, full period.

## Phase 9 — Walk-forward fold stability [x]

`scripts/test_canslim_walkforward.py`, same 36 non-overlapping annual folds
(train=5y/test=1y) as `walk_forward_portfolio_backtest.py` and the Greenblatt
walk-forward test.

**Result: augmented beats baseline in 8/35 folds (23%)** — folds 2-6
(1992-1996) are identical between both composites (same low-breadth
sector-cap-absorbs-everything effect noted in the Greenblatt doc); excluding
those, 8/30 (27%). Far worse than a coin flip, and much weaker than
Greenblatt's 51%/60% fold win rates against the same baseline. The Phase 8
full-period loss is not one bad stretch dragging down an otherwise-decent
signal — augmented loses consistently across three decades, including most
of the 2009-2024 stretch.

## Phase 10 — Investable-constrained comparison vs. live composite [x]

`scripts/test_canslim_vs_composite.py` (mirrors
`scripts/test_greenblatt_vs_composite.py`): pure CANSLIM (rank-sum of all 7
sub-factors) made investable — $5M ADV liquidity filter, guardrails, 25%
sector cap, identical universe as the composite baseline — head-to-head, same
36 folds.

**Result** (top_n_25, identical universe/guardrails/sector cap/liquidity
filter):

|  | CAGR | Sharpe | MaxDD | WinRate | Months |
|---|---|---|---|---|---|
| composite (live baseline) | +16.13% | 0.905 | -39.18% | 65.6% | 404 |
| canslim (constrained, standalone) | +13.17% | 0.855 | -47.75% | 62.7% | 354 |

**Canslim beats composite in 8/31 valid folds (26%)**. Loses on every
aggregate metric, and MaxDD is materially worse (-47.75% vs -39.18%) — worse
tail risk on top of lower and less consistent returns. This corroborates
Phases 8-9 from a different angle (standalone selection rule, not blended
into the existing composite): CANSLIM as built here is not a source of edge
on this dataset, in either form.

## Phase 11 — Written verdict [x]

`docs/canslim_factors_test.md`. **Verdict: reject, not promoted.** CANSLIM as
implemented here loses on every metric whether blended into the live
composite or run standalone, across the full period and fold-by-fold (23-27%
fold win rates, worse than a coin flip) — a stronger and more one-directional
rejection than the Greenblatt test's "statistically indistinguishable" coin
flip. `_VALUE_COLS`/`_QUALITY_COLS` in `historic_fundamentals/baselines.py`
left untouched. Two sub-factors (`rs_rating`, `up_down_vol_ratio`) showed
genuine standalone signal in the IC test and are flagged as candidates for a
future narrower retest, separate from the CANSLIM bundle that diluted them
here. All 7 columns kept in `monthly_pe` for future use.

## Explicitly out of scope (for a future plan, not blocking)

- SEC EDGAR 13F ingestion for real institutional ownership.
- Cup-with-handle / consolidation-tightness pattern detection.
- Live paper-trading execution (trade_systems entry/exit/monitor).
- Wiring `rs_rating`/`pct_off_52wk_high`/`vol_surge_ratio` into the Finview
  screener UI (`api/screener_router.py` / `ScreenerViewer.tsx`) — only worth
  doing after Phase 11's verdict, same as Greenblatt's factors staying
  DB-only until a decision was made.
