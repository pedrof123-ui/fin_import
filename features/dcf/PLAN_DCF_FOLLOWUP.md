# DCF Follow-Up — Horizon, Single-Name Use, and Survivorship

Created 2026-08-22. Successor to `archive/PLAN_DCF_ACCURACY.md`, which is closed. Findings from
that work: `docs/dcf_upside_factor_test.md`.

## Why this exists

The predecessor answered one question well and left three standing. It measured whether
**DCF-implied upside ranks stocks cross-sectionally over a 12-month horizon** — it does not, for
>=$1B names, and its incremental information over `earnings_yield`/`ebitda_ev_yield`/`fcf_yield`
is negative.

That verdict rests on a choice nobody defended: **one year**. A DCF is a claim about decades of
cash flows, and the standard premise is that price converges to intrinsic value over three to five
years. Judging it on 1-year returns partly measures "does the market close this gap within twelve
months", which is a different and harder question than "is the valuation right". **If the DCF is a
slow-convergence signal, the predecessor tested it on the wrong clock and its verdict is too
harsh.** That is Phase 1, it is cheap, and it should run before anything else here — it can
invalidate the finding the rest of this plan builds on.

---

## Permanent limits — NOT work items

Recorded so nobody opens a phase for them.

**Dollar-terms calibration is unmeasurable.** "Is this fair value close to the company's true
intrinsic value?" has no ground truth — nobody observes intrinsic value. Every test in this
programme is a *proxy*: if the DCF is any good, stocks it calls cheap should outperform stocks it
calls expensive. A DCF systematically 30% too low for every company scores perfectly on any
cross-sectional rank test, because a constant bias cancels. **This will never be closed. Do not
open it.**

**The shipped model cannot be reconstructed.** Production applies an analyst-estimate layer worth
a **median 29% of intrinsic value** (54% of tickers move >20%), and `earnings_estimates` only
begins 2026-05-10. No historical panel can include it. The only route is the forward accumulation
in `dcf_results_history`, already live and running monthly, readable ~2028-29. **Nothing can
accelerate this.** The correct action is to leave it alone.

---

## Phase 1 — Is one year the wrong clock?  [x] **Complete 2026-08-22 — objection ANSWERED, verdict softens but stands**

Re-run the factor at **1y, 2y, 3y and 5y**. Four horizons, not two: with three points you cannot
tell slow convergence (monotonic rise) from a peak-and-fade. 1y is the existing baseline and 2y
bridges it cheaply.

The panel already exists (`data/dcf_reconstruction_flat_2p5/`, built under current constants), so
this is minutes of compute, not hours. **Run it before Phase 2 or 3** — it can change the verdict
those phases are premised on.

**1.1 — Sample and lag structure, fixed in advance.** Overlapping returns are autocorrelated, so
Newey-West lags must be H-1. Measured against `monthly_pe` (max month 2026-08):

| horizon | scoreable panel months | NW lags |
|---|---|---|
| 1y | 180 (2010-01 → 2024-12) | 11 |
| 2y | 176 (→ 2024-08) | 23 |
| 3y | 164 (→ 2023-08) | 35 |
| 5y | 140 (→ 2021-08) | 59 |

`ic_summary` defaults to `nw_lags=11`. **Using the default at 3y or 5y would produce inflated
t-stats that look like a strong result.**

**1.2 — Do NOT lead on t-stats at long horizons.** At 5y the estimator uses 59 lags from 140
months — 42% of the sample length. The overlap correction is right in principle but the estimator
is noisy. **Lead on the trend shape across the four horizons and on fold win rate**, both of which
survive overlap in a way t-stats do not. A 5y t-stat of 6 reported as a triumph is the artifact
talking.

**1.3 — Measure INCREMENTAL IC at every horizon, not just standalone.** This is the one that
decides it. Value factors generally strengthen at longer horizons, so a rise in the DCF's
standalone IC at 3y could simply mean "all value works better at 3y" — which says nothing about
the DCF. The question is whether it beats `earnings_yield`/`ebitda_ev_yield`/`fcf_yield` **at that
horizon**, exactly as in the predecessor's Phase 3.

**PREDICTION COMMITTED BEFORE RUNNING:** standalone IC **rises** with horizon, and **incremental
IC stays near zero or negative**, because the reference factors rise too. If that holds, the
existing verdict stands and the horizon objection is answered. If incremental IC turns clearly
positive at 3y or 5y, **the verdict was too harsh** and the DCF is a slow-convergence signal that
was tested on the wrong clock — in which case the 2.5x guard should be re-derived at the horizon
where the signal actually lives, since it was fitted at 1y.

### Result (`scripts/test_dcf_horizon.py`), panel `data/dcf_reconstruction_flat_2p5`

```
mean IC            ret_1y   ret_2y   ret_3y   ret_5y
dcf_upside         0.0368   0.0551   0.0707   0.0776
dcf_upside RESID   0.0037   0.0053   0.0077   0.0201
earnings_yield     0.0445   0.0700   0.0838   0.0874
ebitda_ev_yield    0.0443   0.0652   0.0759   0.0669
fcf_yield          0.0782   0.1121   0.1444   0.1569

fold win rate      ret_1y   ret_2y   ret_3y   ret_5y
dcf_upside           9/15    11/15    10/15    10/15
dcf_upside RESID     9/15     8/15     9/15     9/15

months used           178      175      163      139   (predicted 180/176/164/140)
```

**The prediction was half right.** Standalone IC rises monotonically as predicted. Incremental IC
did NOT stay near zero — it rises to **+0.0201 at 5y** (ICIR-NW 1.29, t 3.75), which the plan's own
threshold (>0.01) counts as clearly positive.

**But the metric this plan pre-committed to leading on says otherwise.** Constraint 1.2 fixed in
advance that fold win rate, not t-stats, is the read that survives overlapping returns. The
residual fold win rate is **flat: 9/15, 8/15, 9/15, 9/15** — no improvement at any horizon.

**And the artifact that constraint was written for showed up plainly:** `fcf_yield` at 5y posts a
**hit rate of 1.0000** and t = 27.7. A 100% hit rate across 141 overlapping months means roughly
THREE independent observations. Long-horizon t-stats here are decorative, and would have looked
like a triumph if reported without this constraint.

### Verdict

**The horizon objection is answered. The finding softens rather than flips.**

The DCF does carry more information at longer horizons — but so does every value factor
(`earnings_yield` 0.0445 -> 0.0874, `fcf_yield` 0.0782 -> 0.1569). A DCF rising with horizon is not
evidence of anything specific to DCFs, which is exactly why constraint 1.3 required measuring
INCREMENTAL IC rather than standalone.

Incremental contribution against `fcf_yield` standalone: **~1/19th at 3y** (0.0077 vs 0.1444,
t 1.81 — not significant) and **~1/8th at 5y** (0.0201 vs 0.1569). Fold consistency flat at 9/15
throughout.

**3y is the weaker result and it is the horizon that matters most** — the convergence argument
rests on 3-5 years, and a real DCF edge should be clearest at 3y. The 5y figure is the DCF's best
horizon and the least reliable one (~3 independent observations); quoting it alone overstates the
case. So *"not a useful ranking factor on its own merits"* **stands**, and 3y strengthens it.
What no longer stands is *"actively wrong beyond the existing value factors"*.

### Reconciliation worth keeping

The predecessor reported incremental IC of **-0.0164** at 1y; this run gives **+0.0037** at the
same horizon. The difference is the panel — the predecessor used the 10x-bound one, this uses
2.5x. **The guard change fixed the negative incremental IC**, confirmed independently by a test
that was not designed to check it.

### The contingency is DECLINED, deliberately

This plan said that if incremental IC turned clearly positive at 3y/5y, the 2.5x guard should be
re-derived at that horizon. It did, at 5y. **Do not re-derive it there.**

A threshold fitted on 5-year overlapping returns is fitted on ~3 independent observations; the 1y
fit had ~15 independent years behind it and survived an out-of-sample walk-forward. Re-deriving at
5y would be textbook overfitting, and would be done to chase a result this plan predicted would
not appear. The contingency was written before the sample-size consequence was understood; it is
declined on that basis, not ignored.

---

## Phase 2 — Single-name usefulness  [ ]

The predecessor measured cross-sectional ranking. **That is not how the AI Researcher uses the
DCF** — it consumes a fair value for one company as a valuation anchor. A factor can be useless
for ranking and still informative for a single name, and vice versa; the two questions are
genuinely different and neither implies the other.

This is testable, just not by rank IC. Candidate designs, to be chosen before running:

- **Directional hit rate**: does `intrinsic > price` predict positive excess return for that name
  over 3-5 years, per company rather than per cross-section?
- **Convergence**: does `price / intrinsic` move toward 1 over the horizon, and how often?
- **Calibration-in-the-large**: bucket by predicted upside and check realised return against it.
  Not calibration of the *level* (unmeasurable, above), but whether bigger predicted gaps
  correspond to bigger realised moves.

**Depends on Phase 1**, now complete: the signal is strongest at 3-5 years, so use that horizon.
Note that Phase 1 also caps expectations — the DCF's incremental information over existing value
factors is real but small (~0.02 IC at 5y), so a single-name test should be powered for a modest
effect, not a large one.

**Note the asymmetry before starting:** the AI Researcher already degrades cleanly when the
mechanical DCF is unavailable (~28% of the universe at the 2.5x bound), and that path is now
warned and logged. So a negative result here has a clear action — widen the degradation path —
while a positive result mostly confirms current behaviour.

---

## Phase 3 — Scope small-cap survivorship  [x] **SCOPED 2026-08-22 — CLOSED UNBUILT**

**Scope before building. Leaving the caveat standing is a legitimate outcome.**

`docs/dcf_upside_factor_test.md` reports that the factor works below $1B (ICIR-NW 3.13 even
untightened, positive quintile spread, 12/15 folds) and immediately discounts it for survivorship
— on **reasoning, not measurement**. That is the only conclusion in the whole programme resting on
an argument rather than a number.

The argument: all 1,575 tickers in the small-cap panel still exist today, and the missing ones are
disproportionately cheap-looking companies that went to zero — exactly the population that would
sit in the high-upside bucket dragging its returns down. `project_survivorship_bias_result`
quantified the large-cap gap at 51% of real S&P 500 exits since 2016; small-cap delisting rates
are structurally higher and have never been measured here.

**3.1 — Scope it first, and be willing to stop.** The data needed is a historical small-cap
universe including delisted names, which is **not in any database in this repo**. That likely
means an external source (CRSP, Sharadar, or similar), which is a purchase and an ingestion
pipeline. This is plausibly a bigger job than the entire predecessor plan. Estimate the cost
before committing.

**3.2 — Ask what the answer changes.** Before spending, state what decision moves on the result.
Today the small-cap finding is documented with its caveat and drives nothing: `dcf_upside` is not
in the live composite, and the screener preset carries the warning. **If nothing changes either
way, the honest move is to leave the caveat standing and close this phase unbuilt** — that is a
valid outcome, not a failure.

**3.3 — A cheaper partial answer may exist.** Before the full reconstruction, check whether
`stock_prices` retains any tickers that stopped trading, and whether the AV universe has ever been
snapshotted historically. A measured lower bound on the gap beats an unmeasured assertion, even if
it is not the full number.

### Scoping result — closed unbuilt, which this plan named as a valid outcome

**3.3 — no cheap partial answer exists.** `stock_prices` retains essentially no delisted names:

| last price date | tickers |
|---|---|
| still trading | 2,779 |
| stopped 2025-26 | 30 |
| **stopped 2020-24** | **0** |
| stopped 2010-19 | 1 |
| stopped pre-2010 | 17 |

**Zero tickers stopped trading between 2020 and 2024**, which is impossible in reality — hundreds
of US listings delisted in that window. The table is a snapshot of currently-listed names, not a
historical universe. `company_overview` snapshots begin **2026-05-14**, three months, with two full
sweeps (2026-07-01, 2026-08-01). Neither supports reconstructing a 2010-2024 universe, and no
lower bound worth reporting can be extracted from three months.

So the only route is external data (CRSP, Sharadar or similar): a purchase plus an ingestion
pipeline, plausibly larger than the entire predecessor plan.

**3.2 — nothing decides differently on the answer, and the reason is structural.** The live
trading universe carries a **$1B market-cap floor** (`scripts/score_live.py` applies
`UNIVERSE_DEFAULTS`, `min_market_cap = 1_000_000_000`). **The $300M-1B band is not tradeable at
all**, and `dcf_upside` appears nowhere in the live scoring path — not in `score_live.py`, not in
`_VALUE_COLS`/`_QUALITY_COLS`/`_MOMENTUM_COL`.

For the small-cap survivorship number to change any decision, TWO prior decisions would have to
land first: lower the universe floor to admit small caps, and promote `dcf_upside` into the
composite. Both are far larger questions than this one, and neither is on the table. The only
remaining consumer is the Screener — a research tool, whose "DCF Undervalued" preset already
carries the size split and the survivorship caveat.

**Decision: closed unbuilt.** Buying data to produce a number that changes nothing is not
diligence. The small-cap finding in `docs/dcf_upside_factor_test.md` stays as it is — an edge
flagged as survivorship-inflated and unquantified, which is an honest state rather than a gap.

**Reopen this if** the universe floor is ever lowered below $1B, or if `dcf_upside` is proposed
for the live composite. Either makes the number decision-relevant; until then it is not.

---

## Method constraints inherited from the predecessor

These cost real time to learn. Do not rediscover them.

1. **A reconstructed panel bakes in every `dcf/model.py` constant live at build time**, not just
   the variable under test. Any A/B needs its baseline rebuilt under current constants. **The tell
   that you have a confound: identical intrinsic values on both sides of an ok/error flip.**
2. **Post-hoc filtering flatters** relative to a real rebuild (0.0441 vs 0.0413) — filtering
   removes rows without letting the model respond.
3. **Report dispersion alongside every median.** A symmetric re-dispersion and a no-op are
   indistinguishable at the median.
4. **Completion rate is coverage, not accuracy.** Conflating them already produced one wrong
   recommendation (excluding small caps).
5. **State the expected direction before running.** Every result in the predecessor that was
   readable as evidence rather than rationalised afterwards had a prediction committed first —
   including the ones that turned out wrong.
