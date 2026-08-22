# DCF Accuracy — Measurement Plan

Created 2026-08-20. **Status: Phases 0-3 complete 2026-08-21. Verdict: the DCF-upside factor is
REJECTED at the old 10x bound; tightening the bound to 2.5x rescues it to earnings_yield-grade
and is walk-forward validated. Phase 1 continues accumulating.**

## Why this exists

The valuation engine was substantially reworked on 2026-08-19/20 — growth fade, capex fade to
D&A, a year-1 growth cap, a 5-year EBIT margin window, a non-positive guard and a 10x
plausibility bound. See `PLAN_VALUATION_ACCURACY.md`.

**Every one of those changes was justified by defensibility, not by accuracy.** A 194% one-year
revenue forecast, a 5.2% margin for a company earning 65.8%, a $1,099,172 share price for GNTX —
each is indefensible on its face, and removing it is progress. But *not one of them was shown to
make a fair value closer to right.* We can currently demonstrate that fewer outputs are absurd. We
cannot demonstrate that any output is accurate.

Every factor in this repo clears a walk-forward gauntlet before it is trusted — CANSLIM,
Fibonacci, PEGY, Greenblatt and the MD&A features were all **rejected** by that bar. The DCF has
never faced it, and it feeds the Screener's `dcf_upside` filter and the AI Researcher's mechanical
anchor regardless.

Until this measurement exists, further DCF tuning is unfalsifiable by construction.

**What "accuracy" means here, and what it does not.** There is no ground truth for intrinsic
value, so this plan cannot measure whether a fair value is close to right in dollar terms. It
measures a **proxy**: if the DCF is any good, stocks it calls cheap should outperform stocks it
calls expensive. That proxy is the bar every other factor in this repo faced, but it answers "is
this useful for ranking?" rather than "is this number right?" A DCF systematically 30% too low for
every company would score perfectly here, because a constant bias cancels in a cross-sectional
rank. Read every result below with that limit in mind.

Three distinct things get reported and they are independent of each other:

| | what it means |
|---|---|
| **completion / coverage** | `run_dcf_av` returned a number instead of raising |
| **plausibility** | the number sits inside defensible bounds (the output guards) |
| **predictive validity** | the number ranks stocks by forward return (IC, quintiles, folds) |

Coverage is not accuracy. The Phase 3 guard change deliberately trades the first for the third:
coverage 81% -> 72%, mean IC 0.016 -> 0.044.

---

## Phase 0 — The blocker: there is no history  [x]

`dcf_results` is a **single-snapshot table**. Every row shares one `computed_at`, and each rebuild
overwrites it. Verified 2026-08-20: `MIN(computed_at) = MAX(computed_at)`, one distinct date. The
snapshot was overwritten three times on 2026-08-20 alone.

**So DCF accuracy cannot be backtested today at all, and every future rebuild destroys more
evidence.** This is the first thing to fix and it is nearly free.

**Step 0.1 — Retain snapshots.** [x] **Complete 2026-08-21.** `dcf_results_history` added
(`historic_fundamentals/db.py`), keyed `(ticker, snapshot_date)`, written by
`scripts/compute_dcf_batch.py` alongside the existing `dcf_results` upsert. Regression test:
`tests/test_compute_dcf_batch.py::test_history_retains_prior_snapshots`.

A second gap surfaced while implementing this and is fixed in the same table. **`dcf_results`
never stored a price.** `dcf_upside` is computed at query time in `api/screener_router.py:254`
against `pe_stats.current_price`, so a snapshot of intrinsic values alone would still have been
unmeasurable — there would be no record of what the DCF was betting against. The history table
therefore also carries `price_at_computation`, plus three fields that make a stored row
diagnosable rather than merely present:

| Column | Why it is there |
|---|---|
| `price_at_computation` | Without it a stored intrinsic value has no reference point |
| `beta_raw` | Separates real betas from the 1.0 fallback (see Phase 0.2) |
| `tv_pct_enterprise_value` | Terminal value dominates; a row that is 95% TV failed differently from one that is 50% |
| `analyst_years_applied` | Separates the mechanical core from the analyst layer (see the Option C decision) |

**Step 0.2 — Fix beta before measuring anything.** [x] **Complete 2026-08-21.** Found while
scoping Phase 2: **877 of the 2,149 `status='ok'` DCFs (41%) have no stored beta at all**, so
`dcf/wacc.py:69` falls back to `beta_raw = 1.0`. `ticker_betas` covers 1,454 tickers against
2,827 in `stock_prices`, and its newest `computed_date` is **2026-06-05** — 11 weeks stale.
`features/beta/beta.py::refresh_betas` documents itself as "Called by the daily cron job"; no such
cron exists. That is the fifth instance of the documented-but-not-running automation pattern.

Cost of equity feeds WACC feeds every intrinsic value in the universe. Measuring DCF accuracy on
top of a beta that is 1.0-by-default for 41% of names would repeat the `debt_to_ebitda` mistake:
a result produced on a known-broken input, needing a full re-run once the input is fixed.

**Done:** backfilled the full price universe for both windows (260d and 104d) — `ticker_betas`
went 1,454 -> 2,799 tickers, 543,707 rows each, current to 2026-08-21, no NaN fits, latest-snapshot
median beta 1.018 (p05 0.365, p95 2.109). **DCF tickers with no beta: 877 -> 4.** Installed the
missing cron (Sat 08:00, `--lock prices`, both windows) and **verified it by running the cron line
verbatim** rather than trusting installation — exit 0, 2,783 rows per window, nothing in
`cron_failures.log`. `features/beta/beta.py` gained a `--window` flag; `refresh` had only ever
covered the 260d series, leaving the 2yr one stale even when it did run.

44 tickers still fall back to beta=1.0 for a pre-existing reason **outside this plan's scope**:
their `stock_prices` history is broken (BK has 6 rows total; CMA and BMS have all-NULL
`adj_close` ending 1999). That is trade_systems ingestion, recorded here but not fixed.

#### Result of the re-run — the stated prediction was wrong

Predicted before running, per this plan's own rule: *WACC up and intrinsic values down for the
majority of the newly-betaed names,* on the reasoning that most US equities run beta > 1.

Measured, partitioning on the 504d window's roster (the one series the backfill did not touch,
so it preserves the pre-fix 1,454-ticker universe):

| | newly betaed (n=860) | already had beta (n=1,272) |
|---|---|---|
| median WACC change | +14.8 bps | -19.7 bps |
| % WACC up | 52.1% | 9.4% |
| median IV change | +0.02% | +4.13% |
| % IV down | 49.3% | 9.4% |

**The direction call was a coin flip.** The reasoning was wrong for this subset: universe median
beta is 1.018, and the tickers missing from the beta table skew small and new rather than
high-beta, so replacing 1.0 with ~1.02 moves nothing systematically.

**But a median-only read would have concluded "the fix changed nothing", which is backwards:**

| | moved >10% | moved >25% | p05 / p95 |
|---|---|---|---|
| newly betaed | 66.4% | 39.9% | -47.9% / +81.6% |
| already had beta | 11.6% | 1.0% | -1.6% / +13.4% |

Two-thirds of the group moved more than 10% and 40% moved more than 25%, symmetrically — which
is exactly why the median showed nothing. **beta=1.0 was compressing 860 companies onto one cost
of equity**; real betas re-dispersed them in both directions. The already-betaed group's uniform
+4.13% is the June->August beta drift, market-wide, not a defect. `status='ok'` went 2,149 ->
2,145.

The lesson to carry into Phase 3: **report dispersion alongside the median.** A symmetric
re-dispersion and a no-op are indistinguishable at the median, and the factor gauntlet's
quintile spread is the metric that would catch the difference.

---

## The measurement: two paths, agreed 2026-08-20 to do **both**

### Phase 1 — Accumulate forward  [~]

Snapshot each monthly rebuild. Nearly free, rides the existing pipeline. A usable read is 2-3
years out, so this is the reliable answer, not the fast one. **Live as of 2026-08-21** via Step
0.1 — the monthly `run_pipeline.py --av-update` run now appends a dated snapshot.

This is the path that measures the **shipped** model, analyst layer included. Phase 2 cannot.

### Phase 2 — Reconstruct backward  [ ]

Recompute DCFs as-of historical dates. Answers the question now rather than in 2029. This is where
all the cost and all the risk are.

**Correction to the original scoping (2026-08-21):** this plan assumed the reconstruction would
read `monthly_pe` and would need a new point-in-time convention. It does not. `dcf/av_data.py`
reads `av_financials.duckdb` **directly**, and `historic_fundamentals/pe.py:603-606` already
filters those exact tables point-in-time using `_LAG_QUARTERLY` (60d) / `_LAG_ANNUAL` (90d). The
work is threading `as_of` through the existing loaders, not writing a parallel implementation.
Every input has an as-of path already:

| Input | As-of availability |
|---|---|
| AV statements | `fiscal_date_ending` + lag; annual data to 1983, median 24 periods/ticker |
| Price | `stock_prices` to 1983 — but `dcf/data.py::load_current_price` calls `fetch_live_price` first (network), which must be bypassed |
| Risk-free rate | FRED `economic_indicators` has full history; a date filter |
| Beta | `features/beta/beta.py::get_beta` **already takes `as_of_date`**; `dcf/wacc.py:19` simply doesn't pass it |
| Analyst estimates | **No point-in-time data exists** — see below |

Design: add `as_of: date | None = None` to `run_dcf_av` and its loaders. The live path is unchanged
when `as_of is None`, so there is one convention rather than two.

---

#### Decision 2026-08-21: the analyst-estimate layer — **Option C**

`dcf/model.py:702` replaces the model's forecast revenue with Alpha Vantage consensus for the
years analysts cover (measured: 2 fiscal years). Because Y3-Y10 cascades off Y2's level and
terminal value is proportional to Y10 FCFF, one substituted year re-levels the entire path.

**Measured impact** (40 random tickers, same code, `estimates_conn` on vs. off):

- **Median absolute change in intrinsic value: 29%**
- 54% of tickers move >20%; 82% move >5%. Extremes BLFS -77%, EFSC -75%, JELD +307%
- **24 of 39 move *down*** when estimates are applied — the analyst layer is mostly acting as a
  brake on the model's own growth extrapolation, i.e. on the exact over-extrapolation problem the
  2026-08-19/20 work was fighting

`earnings_estimates` only begins **2026-05-10**. A 2010-2024 reconstruction has no consensus data
to read, so it can only run the mechanical model — which differs from production by ~29% median.
Three options were weighed:

- **A. Reconstruct mechanical-only and call it "the DCF's accuracy."** Rejected: a pass would not
  license trusting production, a failure would not convict it.
- **B. Strip the estimates layer out of live** so production equals what is measurable. Rejected:
  it deletes the one input sourced from humans with company access, and per the sign asymmetry
  above would make over-extrapolation worse. This is letting the test define the product.
- **C. Keep live as-is; reconstruct the mechanical layer backward, measure the shipped model
  forward.** **Chosen.**

Under C the reconstruction is scoped explicitly as *"does the mechanical DCF core carry signal,
and were the 2026-08-19/20 changes improvements?"* — which is the question this plan was written
to settle, since the growth fade, capex fade, 5-year margin window and output guards all live in
the mechanical layer and can be A/B'd against each other on one reconstructed panel.

**The Phase 2 result must not be quoted as "the DCF's accuracy."** Production carries a
29%-median layer on top of it. Phase 1 covers the shipped model, and gains a question nobody can
answer today: **does the analyst layer add accuracy or subtract it?** `analyst_years_applied` in
`dcf_results_history` is what makes the two populations separable at analysis time.

One caveat for Phase 1 reproducibility: `dcf/estimates.py::_get_cached` has a 30-day TTL and takes
`MAX(fetched_at)`, so estimates used at batch time can be up to a month stale.

---

**Sequencing — do NOT start with the full reconstruction:**

**2.1 Scope it.** [x] **Revised 2026-08-21 — quarterly compute, monthly panel.**

The original scoping said *annual* as-of dates. That is not comparable to the bar this plan
exists to apply: the gauntlet that rejected CANSLIM, Greenblatt, Fibonacci and MD&A runs Spearman
rank IC on **monthly** panels with monthly rebalances (`scripts/test_greenblatt_factors.py`). An
annual panel would have defeated the plan's own stated reason for using the established bar —
that it "makes the answer directly comparable to the factors that were rejected".

The two moving parts have different clocks, so this is fixable cheaply:

- **Intrinsic value** changes only when new financials arrive -> recompute **quarterly**
  (60 as-of dates over 2010-2024)
- **`dcf_upside` = intrinsic / price - 1** changes with price -> compute **monthly**, carrying the
  most recent available intrinsic value against each month's price

That gives ~180 monthly cross-sections at quarterly compute cost. It also mirrors production,
where `dcf_results` is rebuilt periodically and screened against live prices continuously — so the
factor is tested as it actually behaves rather than as an annual variant that ships nowhere.

Cost at ~0.37s/ticker (982s for 2,661 tickers, measured 2026-08-20): 60 x 1,900 x 0.37s = **~11.7
hours** single-threaded, ~2 hours across 6 workers. A true monthly recompute would be ~35 hours
and buys almost nothing, since the statement inputs do not change that fast.

**Universe: 2010-2024, deliberately not earlier.** Coverage would support 2005 (1,269 tickers with
>=8 quarterly periods, vs 1,551 at 2010 and 2,556 at 2024), but survivorship worsens going back,
so the extra folds are the most contaminated ones.

**Cap floor $1B, to match the gauntlet's UNIVERSE_DEFAULTS.** NOTE: the justification originally
given here — that sub-$1B names would "degrade panel quality" because they complete less often —
was WRONG, and the small-cap panel run afterwards disproves it. See the small-cap section in
Phase 3. The floor is defensible only as "matches the bar the rejected factors faced", not as a
quality argument.

**2.2 Pilot point-in-time correctness on one or two years before spending hours.** [x]
**Complete 2026-08-21.** This is the whole risk of the exercise. A reconstruction that lets the forecaster see data published after the
as-of date produces a look-ahead-biased result that will look excellent and mean nothing.
**Validate by asserting no input carries a publication date after the as-of date**, not by
eyeballing whether the numbers look sensible. Concretely, assert per ticker: max
`fiscal_date_ending` used + its lag <= as_of; price date <= as_of; beta `computed_date` <= as_of;
`analyst_years_applied == 0`.

**Implemented:** `as_of: date | None = None` on `run_dcf_av`, threaded to `dcf/av_data.py`
(statements, via the shared `LAG_ANNUAL`/`LAG_QUARTERLY`), `dcf/data.py` (price and FRED rates)
and `dcf/wacc.py` (beta). The live path is untouched when `as_of is None`. Setting `as_of` forces
`estimates_conn = None` **inside the model** rather than trusting callers to remember.

`load_current_price` needed the most care: it called `fetch_live_price` first, so a historical run
would have silently used today's quote — the most direct look-ahead available, and one that would
not have raised.

The 60/90-day convention existed in **three** independent copies before this (`pe.py`,
`scripts/backfill_canslim_factors.py:53`, hardcoded in the tests). Rather than add a fourth,
`LAG_QUARTERLY`/`LAG_ANNUAL` are now public in `pe.py` and the CANSLIM script imports them. The
test file keeps its literals deliberately — a test asserting a constant's value must not import
that constant.

Validation: `tests/test_dcf_as_of.py`, 46 assertions across 5 tickers x 4 as-of dates. **Verified
non-vacuous** by a negative control: feeding the unfiltered live loader to the same assertion
fails it (newest period 2025-09-30, available 2025-12-29, against a 2015 as-of). This matters
because ordering-only assertions have passed anchoring bugs green in this repo before.

Spot check, AAPL — every dated input tracks the date:

```
as_of=2015-06-30  iv=  88.79  px=  27.98  wacc=0.0785  beta=0.935  rf=0.0311  ay=0
as_of=2019-06-30  iv=  64.16  px=  47.35  wacc=0.0778  beta=1.129  rf=0.0252  ay=0
as_of=None        iv= 115.23  px= 311.30  wacc=0.1107  beta=1.105  rf=0.0519  ay=0
```

**2.3 Only then run the full reconstruction.** [x] **Complete 2026-08-21.**
`scripts/reconstruct_dcf_panel.py`, 60 quarterly as-of dates 2010-2024, 6 workers, 88 minutes.
**75,280 ticker-dates, 2,259 tickers, 61,289 ok valuations (81.4%)** — matching production's
81.4% exactly, which is the check that the as-of path is not quietly starving the model.

Two pre-flight checks before trusting it:

- **Success rate by year is flat (77-85%) with no early-year decay** — 2010 at 82.8% sits on the
  panel average. This was the real risk: had 2010-2012 come in worse it would have meant thin
  point-in-time AV coverage, and any factor result would have been driven by which companies
  survived the filter in early folds.
- **The 2020-21 dip (78.1%/77.0%) is composition, not defect.** Verified rather than assumed:
  insufficient-quarterly-history failures run 15.3% there vs 5.1% elsewhere — the IPO/SPAC cohort
  crossing $1B without eight quarters of filings. Those had no computable DCF at the time, which
  is correct behaviour.

**Universe-filter integrity.** `universe_at()` derives market cap from `monthly_pe.shares`, which
goes transiently wrong around splits. Measured: **21 ticker-dates, 0.028% of the panel**. It only
decides where compute is spent — the DCF reads `diluted_shares` from the AV statements — so a
spuriously included ticker still gets a correct valuation.

---

## Phase 3 — The actual test  [x] **Complete 2026-08-21 — REJECTED as-is**

Treat **DCF-implied upside** (`intrinsic_value / price - 1`) as a factor and run it through the
same gauntlet every other candidate faces: rank IC, ICIR with Newey-West, quintile spread, and
fold win rate across annual walk-forward folds.

Using the established bar matters more than the specific metric — it makes the answer directly
comparable to the factors that were rejected, and it removes the temptation to invent a bespoke
measure that happens to flatter the DCF.

**State the expected direction before running.** Every prediction in the 2026-08-19/20 work was
committed in advance, which is the only reason results like "EV/EBITDA improves while the other
three multiples do not" were readable as evidence rather than rationalised afterwards.

**Predictions committed 2026-08-21, before the panel was built:**

1. DCF-implied upside shows **weak positive rank IC (~0.01-0.03) that fails the fold win rate** —
   the same shape as the rejected CANSLIM and MD&A candidates.
2. **It is largely redundant with the existing value factors.** A DCF at fixed WACC is mostly a
   levered function of current margins and growth, which `earnings_yield` and `ebitda_ev_yield`
   already capture.

Prediction 2 is the more useful one either way, and it dictates the test design: measure
**incremental IC against the existing value factors**, not standalone IC, exactly as the Greenblatt
test compared against `earnings_yield`/`ebitda_ev_yield`/`roic`. A factor 0.8-correlated with one
already in the composite can post a respectable standalone IC and still add nothing.

**Report dispersion alongside every median.** The beta fix in Step 0.2 moved 40% of its group by
more than 25% while showing a median change of +0.02% — a symmetric re-dispersion and a no-op are
indistinguishable at the median. Quintile spread is the metric that separates them.

---

### Result (`scripts/test_dcf_upside_factor.py`)

**1. Standalone rank IC vs ret_1y — indistinguishable from zero.**

| factor | mean IC | ICIR (NW) | hit rate | t |
|---|---|---|---|---|
| **dcf_upside** | **0.0148** | **0.53** | **52.7%** | **1.43** |
| fcf_yield | 0.0871 | 4.06 | 78.1% | 11.28 |
| roic | 0.0513 | 3.77 | 75.7% | 8.99 |
| earnings_yield | 0.0498 | 2.20 | 69.2% | 5.89 |
| ebitda_ev_yield | 0.0489 | 1.64 | 64.5% | 4.70 |

**2. Incremental IC — the unique component is negatively predictive.** Rank correlation with the
existing value factors is 0.43-0.46. Residualised on them, dcf_upside's IC is **-0.0164**
(ICIR-NW -0.75, hit rate 44.3%, t = -1.95). Whatever the DCF knows that `earnings_yield` and
`ebitda_ev_yield` do not was actively wrong.

**3. Quintiles are non-monotonic and the "cheapest" bucket is the worst:** Q1 (highest upside)
0.1410, Q2 0.1506, Q3 0.1585, Q4 0.1538, Q5 0.1527. Mean Q1-Q5 spread -0.0117, positive in only
45.5% of months. The mild positive IC comes from the middle of the distribution, not the extremes.

**4. Fold win rate:** 8/15 (53%) standalone, 6/15 (40%) residualised.

**Against the predictions committed above:** prediction 1 was correct (0.0148, inside the stated
0.01-0.03, failing fold win rate). Prediction 2 was correct but understated — redundancy is
moderate (0.43-0.46, not the ~0.8 implied) yet the incremental result is worse than "adds
nothing", it is negative.

**A pooled table by valuation bucket appears to show the opposite and is NOT evidence.** Pooling
across months confounds the factor with time: periods with many high-upside stocks are post-crash
periods with high forward returns. The per-month cross-sectional result is the valid one, which is
why the gauntlet computes IC per month.

### Follow-up: the guard is the fix  [x]

The non-monotonic quintile pattern says extreme DCF outputs are where the model breaks. Trimming
them rescues the factor:

| bound | mean IC | ICIR (NW) | t | rows kept |
|---|---|---|---|---|
| 10.0 (old) | 0.0157 | 0.56 | 1.51 | 99.6% |
| 3.0 | 0.0368 | 1.47 | 4.07 | 82.8% |
| **2.5 (adopted)** | **0.0441** | **1.81** | **4.97** | **78.3%** |
| 2.0 | 0.0451 | 1.92 | 5.20 | 71.8% |

That sweep is in-sample selection — the same pattern that killed the MD&A contrarian composite —
so it was validated out-of-sample (`scripts/test_dcf_guard_walkforward.py`, 5 train years /
1 test year, matching `test_canslim_rs_updown_regime.py`):

- **Adaptive** (threshold chosen on train, scored on the unseen next year): beats 10x in **8/10
  folds**, and the selection is **stable** — 2 distinct values across 10 folds, converging on 1.5.
- **Fixed 2.0x vs 10x**: wins **12/15 years**, mean IC delta +0.0285, and **stronger in the recent
  half** (7/8 vs 5/7 early) — the opposite of the single-regime artifact that killed the CANSLIM
  regime factors. The three losing years are all years when the baseline IC was already strongly
  positive, i.e. tightening trades a little upside in good years for a lot in bad ones.

**Adopted 2.5, the loosest bound the evidence supports** — the walk-forward's own choice was
tighter, so 2.5 maximises coverage without leaving the validated range. Cost: 232 of 2,145 ok
tickers reclassified as failures, universe with no mechanical DCF 19.4% -> ~28.1%.

### Small-cap band ($300M-1B) — CORRECTS an earlier claim in this plan

A second panel was reconstructed over the $300M-1B band (36 min, 21,969 ticker-dates, 1,575
tickers, 72.5% completion vs 81.4% for >=$1B) and run through the same gauntlet:

| bound | mean IC | ICIR (NW) | hit | t | Q1-Q5 spread | folds |
|---|---|---|---|---|---|---|
| 10.0 | 0.0615 | 3.13 | 73.1% | 7.69 | **+0.0465** | 12/15 |
| 2.5 | 0.0672 | 2.98 | 70.7% | 6.82 | +0.0494 | 10/15 |
| 2.0 | 0.0753 | 3.10 | 70.1% | 7.10 | +0.0533 | 10/15 |

**The factor is far stronger in small caps than large caps, and it was never rejected there** —
even at the untightened 10x bound it posts ICIR-NW 3.13 and a positive quintile spread, against
0.56 and a *negative* spread for >=$1B.

**This corrects the reasoning recorded earlier in this plan.** Small caps were excluded on the
grounds that they would "degrade panel quality", citing DCF completion rates (73.5% vs 80.5%).
That conflated two independent things: **completion is a coverage metric, not an accuracy
metric.** A ticker-date "succeeds" when `run_dcf_av` returns a number instead of raising — it says
nothing about whether the number was right. Small caps complete less often *and* rank better.

**Treat the small-cap result with more suspicion than the large-cap one, not less.** This plan
pre-committed to the rule that a pass on a survivorship-flattered panel should be blamed on the
bias first, and small caps are where that bias is worst by a wide margin: delisting rates are far
higher than the large-cap 51%-of-S&P-exits figure, every one of the 1,575 tickers in the panel
still exists today, and the companies missing are disproportionately the cheap-looking ones that
went to zero — exactly the population that would otherwise sit in the high-upside bucket and drag
its return down. The large-cap rejection is the more trustworthy of the two findings, because
failure cannot be manufactured by a bias running in the factor's favour.

**The 2.5x bound still stands:** it improves both bands (large cap 0.0157 -> 0.0441, small cap
0.0615 -> 0.0672), so the guard change is not a large-cap-only artifact.

---

### Follow-up: the bound had to split by caller  [x] **2026-08-21**

Tightening `MAX_INTRINSIC_TO_PRICE` to 2.5 globally was a regression for the AI DCF, which runs
bear/base/bull through the same `run_dcf_av`. Measured across 25 tickers: bull scenarios lost
**2/25 -> 7/25**. Availability was never at risk (the base scenario did not trip), but the AI DCF
presents a RANGE, and dropping the bull truncates it asymmetrically -- biasing the shown valuation
downward, which is worse than a wide range.

The fix is a second constant rather than a looser single bound, because there are two different
questions:

| | question | value |
|---|---|---|
| `MAX_INTRINSIC_TO_PRICE` | is this number useful for ranking? | 2.5 |
| `MAX_INTRINSIC_TO_PRICE_OVERRIDE` | is this number absurd? | 10.0 |

2.5 was fitted against runaway extrapolation **by the model**; it is the wrong test for a run whose
forecast the caller supplied. 10x still catches what the guard was built for -- GNTX was 46,418x.
Discriminator is `overrides.years` being non-empty: overriding beta or terminal growth alone leaves
the revenue and margin path forecaster-driven, so it keeps the 2.5 bound.

Regression tests: `tests/test_dcf_as_of.py::test_plausibility_bound_splits_by_who_drove_the_forecast`
and `::test_non_forecast_overrides_still_get_the_default_bound`.

---

### What this does and does not license

- **No live trading change.** `dcf_upside` is not in `_VALUE_COLS`/`_QUALITY_COLS`/`_MOMENTUM_COL`
  and `score_live.py` never reads it. No position or backtest baseline depends on it.
- **It is used in exactly two places**: the Screener's filter (`api/screener_router.py`) and its UI
  column (`web/components/ScreenerViewer.tsx`).
- **This does not test the AI Researcher's per-company anchor.** Cross-sectional ranking ability
  and per-company calibration are different questions; that one needs its own test.

---

## Known ceiling: survivorship bias  [ ]

**Any reconstruction will overstate DCF accuracy and this must be stated in the result, not
discovered afterwards.** 51% of real S&P 500 exits since 2016 are missing entirely from
`monthly_pe`/`stock_prices`, and BBBY's ticker was silently reassigned to Overstock after
bankruptcy — contaminating data rather than merely omitting it. A DCF panel reconstructed from
that universe systematically excludes the companies whose intrinsic value collapsed, which is
precisely the population a valuation model should be judged on.

This does not invalidate the exercise, but it caps what the result can claim. Decide up front
whether the answer is worth having under that ceiling.

**Decided 2026-08-21: state the ceiling, do not attempt to fix it.** Reconstructing a delisted
universe is its own project. The panel is 100% survivors by construction and the result must say
so. Note the asymmetry that makes the exercise still worth running: **if the factor fails on a
survivorship-flattered panel, that is a strong result** — failure cannot be explained away by a
bias that runs in the factor's favour. If it passes, the bias is the first thing to suspect.

---

## Open question inherited from `archive/DCF_VISION.md`  [x] **RESOLVED 2026-08-21**

**The spec is unimplementable, and the code was right to reject it.** Measured across 1,831
tickers holding both a WACC and >=5 annual growth observations:

| terminal growth = median historical revenue growth | share of universe |
|---|---|
| **g >= WACC — Gordon Growth breaks entirely** | **45.8%** |
| g within 1pp below WACC — terminal value explodes | 6.7% |
| **broken or absurd in total** | **52.5%** |

The median company's median historical revenue growth is 9.1% against a median WACC of 9.66%, and
80.8% of companies exceed nominal GDP. As perpetual growth that is impossible on its face; as a
Gordon Growth input it is arithmetically undefined for half the universe.

So `_default_terminal_growth` ignoring its argument is not an unfinished implementation, as this
plan originally speculated ("the logic was removed or never landed"). It is the correct rejection
of a bad spec. **Flat 3% stands.**

### Live follow-up: a BOUNDED per-company rule  [x] **REJECTED 2026-08-21**

`min(median historical revenue growth, 3%)`, floored at 0 — only ever lowers, never raises. A
business that grew 1.4%/yr for a decade should not be assumed to grow at 3% in perpetuity.

Scope is small but not trivial: **88.6% of companies land exactly at 3% (unchanged), 11.4% change
to a median 1.36%.** For that 11.4%, terminal growth 3% -> 1.36% at a 9.66% WACC takes the TV
multiple from 15.5x to 12.2x — a 21% cut in terminal value and ~12% off enterprise value.

Implemented behind `DCF_TERMINAL_GROWTH_RULE` (env var, so it survives into the reconstruction's
worker processes; defaults to `flat`, so production is untouched until this is decided).

**PREDICTION COMMITTED BEFORE THE PANEL RUN:** the ranking test will be **INCONCLUSIVE**. Only
11.4% of names move, so the cross-sectional IC change should sit inside noise — I expect
|delta IC| < 0.005 and no clean fold-win-rate signal. Direction, if any, mildly positive: the
affected names are mature slow-growers whose fair values were overstated, so lowering them should
help slightly.

**This is the case flagged at the top of this plan**: terminal growth is largely a LEVEL
assumption, and a ranking test cannot see a level shift. If the result is inconclusive as
predicted, the rule should be decided on economic grounds — not held hostage to a statistical
answer this method cannot produce. Recording that in advance so an inconclusive result is not
retrofitted into either a pass or a rejection.

#### Methodology error caught during the first comparison (2026-08-21)

The first capped-vs-flat comparison showed coverage collapsing 81.4% -> 62.6% and was nearly
reported as "the capped rule destroys a fifth of the universe". **It was confounded.** The flat
panel had been built earlier the same day while `MAX_INTRINSIC_TO_PRICE` was still 10.0; the
capped panel ran after the guard was tightened to 2.5. The two panels differed in TWO variables,
and the entire 18.8pp gap was the guard, not terminal growth.

Caught by reading the failing rows rather than the aggregate: ABT/ADM/AEE at 2010-03-31 carried
**identical** intrinsic values (70.36 / 49.44 / 99.05) in both panels while one said `ok` and the
other `error`. An identical value on both sides of a status flip means the rule under test changed
nothing and something else moved.

**A reconstructed panel bakes in every `dcf/model.py` constant live at build time, not just the
rule under test.** Any A/B needs its baseline rebuilt under the current constants. Warning added
to `scripts/reconstruct_dcf_panel.py`.

The one uncontaminated read from that comparison — restricted to the 47,065 ticker-dates `ok` in
both panels — is that **88.5% of intrinsic values were unchanged and the median change was 0.0%**,
which matches the 88.6% predicted from the rule's scope.

#### Result — the prediction held, and the decision was made on economic grounds

Both panels rebuilt under the SAME constants (2.5x bound), differing only in the terminal growth
rule:

| rule | coverage | mean IC | ICIR (NW) | hit | Q1-Q5 spread | folds |
|---|---|---|---|---|---|---|
| flat 3% | 121,850 | 0.0413 | 1.731 | 65.3% | 0.0055 | 9/15 |
| capped | 122,935 | 0.0413 | 1.774 | 64.7% | 0.0054 | 9/15 |

**delta mean IC = +0.00003** — three orders of magnitude below the 0.005 threshold committed
before the run. Identical to four decimals, same fold win rate, same quintile spread. The rule
behaved exactly as scoped mechanically (89.8% of intrinsic values unchanged, 10.0% lowered, no
coverage cost); it is simply invisible to a ranking test, as predicted, because it is a level
effect on a minority of names.

**REJECTED**, on economic grounds as the pre-commitment required:

1. No measurable benefit — the delta is noise.
2. It adds a per-company parameter and a code path for something that cannot be shown to improve
   anything (CLAUDE.md: keep it simple, never over-engineer).
3. **It inherits the premise the spec was rejected for.** Capping fixes the ARITHMETIC that broke
   Gordon Growth for 52.5% of the universe, but keeps the premise that a decade of revenue history
   tells you a company's growth rate in perpetuity. Terminal growth is a claim about decades out;
   a mature phase today is not evidence about the terminal state. Capping makes a bad premise
   safe, not correct.

The honest counterargument, recorded because it is not weak: assuming IBM grows at 3% forever when
it has managed 1.75% IS generous, and the capped rule only ever lowers. That is more defensible in
the plain sense. But this plan exists precisely because **defensibility is not accuracy** — and the
measurement says this particular defensibility improvement buys nothing.

The switch and `_median_historical_revenue_growth` were removed rather than left as off-by-default
dead code. The reasoning lives in `dcf/model.py` above `_default_terminal_growth` so the next
person to notice the unused `income_df` argument finds the answer there.

#### Side finding: post-hoc filtering flatters a result

The rebuilt flat panel at the 2.5x bound gives mean IC **0.0413**. The Phase 3 threshold sweep,
which reached 2.5 by filtering rows out of the 10x panel, gave **0.0441**. The rebuild is the
honest number: filtering removes rows without letting the growth fade change, since terminal
growth feeds `extend_growth_years` as well as the terminal value. Worth remembering before
reading any future in-sample sweep as if it were a rebuild.

### Original text



The original DCF spec called for terminal growth to default to **the median of historical annual
revenue growth**. The code does not do this: `dcf/model.py::_default_terminal_growth(income_df)`
ignores its argument and returns a flat `DEFAULT_TERMINAL_GROWTH = 0.03` for every company in the
universe. The unused parameter suggests the logic was removed or never landed.

Terminal value dominates a 10-year DCF, so a universal 3% is a first-order accuracy assumption
applied without evidence — and it is a per-company assumption being made globally. Worth resolving
inside this plan rather than separately.

---

## What this plan deliberately does not do

It does not tune the DCF. No assumption should change until the measurement exists, or the change
cannot be evaluated. If hand-testing the AI Researcher surfaces something egregious in the
meantime, record it in `PLAN_VALUATION_ACCURACY.md` rather than fixing it here.
