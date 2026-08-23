# DCF Follow-Up — Horizon, Single-Name Use, and Survivorship

Created 2026-08-22. Successor to `archive/PLAN_DCF_ACCURACY.md`, which is closed. Findings from
that work: `docs/dcf_upside_factor_test.md`.

## STATE (updated 2026-08-23)

**Phases 1, 2 and 3 are closed. Phase 4 is next and its prediction is committed.**

| phase | status |
|---|---|
| 1 — is 1y the wrong clock? | **done** — objection answered, verdict softens but stands |
| 2 — single-name usefulness | **done** — prediction FAILED; the DCF *does* carry per-name information, weakly |
| 3 — small-cap survivorship | **closed unbuilt** — nothing decides differently on the answer |
| 4 — calibration-in-the-large | **done** — the signal is CONCENTRATED, and it explains Phase 1 |
| 5 — act on it in the AI Researcher | **done, shipped** (17acd79) — Chief Analyst regime note |

**ALL PHASES CLOSED. Findings live in `docs/dcf_upside_factor_test.md`, not here.** This plan is a
process record; the factor-test doc is the durable artifact, sitting beside the
canslim/fibonacci/greenblatt verdicts where someone asking "what do we know about the DCF" will
look. If a result exists only in this file, it is not logged — see the note at the bottom.

**Headline after three phases.** The mechanical DCF is not a useful cross-sectional ranking factor
(Phase 1), but it *does* carry genuine, sector-independent, per-name directional information
(Phase 2) — a 2-4pp tilt over a matched null, which the ranking tests could not see. It is a tilt,
not an anchor: prices move away from its intrinsic values about twice as often as toward them at
5y. **Recommendation, narrowed by Phase 4 and now being implemented (Phase 5):** the mechanical DCF is
worth real narrative weight only when it disagrees with the market **by a lot and to the downside**
(price above ~2.5x intrinsic), where roughly half its edge survives controlling for the value
effect. In the middle of the distribution it carries essentially nothing beyond `earnings_yield`.

**Housekeeping — both CLOSED 2026-08-23, and both were mis-stated when first recorded:**

- **`ticker_betas` window 504.** Nothing reads it — only 260d (cost of equity) and 104d (reported)
  are ever queried. Dead data from an earlier experiment, now annotated as such in
  `features/beta/beta.py` so it is not mistaken for a maintained series. Left in place rather than
  deleted (358,759 rows in a shared DB); deletion is a separate call.
  Also found: a **second beta entry point**, `features/beta/update_betas.py`, documented in that
  feature's README and PLAN with its own crontab line and **never installed** — the same
  documented-but-not-running pattern that left betas stale from 2026-06-05. Deleted rather than
  wired up: it only added logging `cron_wrap.sh` already provides, and two entry points for one
  job is the problem.

- **"44 tickers pinned at beta 1.0 by broken price history" was WRONG on two counts.** Of the 44
  skipped by `refresh_betas`: **21 are legitimate new listings** that genuinely lack 26 weeks of
  history and are correctly skipped, and of the rest **none are in the AV universe and none get a
  DCF** (0 rows in `dcf_results`). They are de-tracked leftovers — BK, CMA, HES, K, WBA, X and
  others with history ending 1999 — that no live path touches. **Not a defect, and not a
  trade_systems ingestion bug either.** Closed.

- Noted while there: `prices.duckdb` has a **`universe_snapshots`** table (`snapshot_date`,
  `ticker`, `sub_index`) that is **empty, 0 rows**. It is an unpopulated scaffold for exactly the
  historical universe membership Phase 3 needed. It does not reopen Phase 3 — there is no data in
  it — but if it were ever wired up, Phase 3's blocker would begin to dissolve from that date
  forward.

---

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

## Phase 2 — Single-name usefulness  [x] **Complete 2026-08-23 — prediction FAILED, the DCF does carry per-name information**

The predecessor measured cross-sectional ranking. **That is not how the AI Researcher uses the
DCF** — it consumes a fair value for one company as a valuation anchor. A factor can be useless
for ranking and still informative for a single name, and vice versa; the two questions are
genuinely different and neither implies the other.

This is testable, just not by rank IC. Candidate designs, to be chosen before running:

### DESIGN DECIDED 2026-08-22: **convergence**

**Chosen — Convergence.** Does `price / intrinsic_value` move toward 1 over the horizon, and how
often? Measured per company: compare `price_{t+H} / intrinsic_t` against `price_t / intrinsic_t`
and test whether the ratio moves toward 1.

**Why this one, over the two alternatives — the reason is survivorship.** It bites Phase 2 harder
than it bit the ranking test. A rank IC only asks about *relative* ordering within a month, so a
missing company distorts the ordering slightly. A directional or absolute test asks *did the
stocks the DCF called cheap actually go up?* — and the companies absent from this database are
disproportionately the ones that went to zero, which is exactly the population the DCF would have
called cheap.

Convergence is a **ratio** question that a delisted company simply cannot answer, so its absence
shows up as a missing observation. Directional accuracy silently counts that same absence as
evidence **in the DCF's favour**. Given Phase 3 established that the survivorship gap cannot be
quantified from local data, preferring the design that fails loudly over the one that fails
flatteringly is the whole point.

**Rejected — Directional hit rate.** Does `intrinsic > price` predict positive excess return for
that name over 3-5 years? Rejected on the survivorship asymmetry above: the missing companies
would have been counted as "called cheap" and their -100% outcomes are simply absent, biasing the
hit rate upward by an unknown amount. Would also need a benchmark decision (SPY vs sector vs
universe) that convergence avoids entirely.

**Rejected — Calibration-in-the-large.** Bucket by predicted upside and check whether bigger
predicted gaps produce bigger realised moves. Not rejected on merit — it is a good test and worth
running as a SECONDARY read if convergence produces a signal. Deferred because it shares the
directional test's survivorship exposure (it is an absolute-return question per bucket), and
because running two designs and reporting the better one is exactly the retrofitting this plan
keeps warning against. **Pick one, commit, report it.**

### Test construction — two confounds that would fake a positive result

**Confound 1: market drift.** Equities drift up. Any name with `price < intrinsic` will appear to
"converge" from drift alone, with no information in the intrinsic value at all. A raw convergence
rate is therefore meaningless on its own.

**Confound 2: mechanical mean reversion.** When `|r_t - 1|` is large, almost any change is more
likely to shrink it than grow it. Extreme ratios "converge" for arithmetic reasons.

Both are handled by testing against nulls rather than against zero:

- **Primary**: for each (ticker, as_of), `r_t = price_t / intrinsic_t` and
  `r_{t+H} = price_{t+H} / intrinsic_t` — the SAME intrinsic value, so this asks whether price
  moved toward the valuation. Convergence when `|r_{t+H} - 1| < |r_t - 1|`.
- **Null A — shuffled intrinsic.** Shuffle intrinsic values within each as-of cross-section,
  breaking only the ticker linkage while preserving both distributions. Repeat for a null band.
  **The result is the actual rate MINUS this null**, never the raw rate.
- **Null B — directional asymmetry.** Split by `r_t < 1` (undervalued) vs `r_t > 1` (overvalued).
  **Genuine information requires BOTH to converge.** Drift alone converges only the undervalued
  side. This is the discriminating test and the one to lead on: an overvalued name must fall
  toward its intrinsic value, which market drift actively works against.

Horizons 1y / 3y / 5y (Phase 1 established the signal, if any, lives at 3-5y).

**PREDICTION COMMITTED BEFORE RUNNING (2026-08-23):**

1. **Raw convergence will look positive and mean nothing** — roughly 55-65% for undervalued names,
   driven by drift and mechanical mean reversion.
2. **Overvalued names will NOT converge** at a meaningfully better-than-null rate. This is the
   prediction that matters; if it is wrong, the DCF carries real per-name information.
3. **Actual minus shuffled null will be small — under 5 percentage points** at every horizon.
4. Therefore: **no per-name signal strong enough to justify the AI Researcher anchoring on a
   mechanical fair value**, and the recommendation will be to reframe rather than remove (the
   number is still a defensible reference point, just not a prediction).

Reasoning: Phase 1 measured the DCF's incremental cross-sectional information at ~0.02 IC even at
5y. Per-name convergence is a genuinely different question — that is why this phase exists — but a
strong per-name signal alongside near-zero cross-sectional signal would be surprising.

**If prediction 2 fails** (overvalued names converge at a real rate above null), the verdict from
the whole programme is too harsh: the DCF would be informative per-name while useless for ranking,
which is exactly the case the ranking tests could not see. Run calibration-in-the-large as the
secondary read at that point, not before.

### RESULT (`scripts/test_dcf_convergence.py`), panel `data/dcf_reconstruction_flat_2p5`

**Prediction 2 failed.** Overvalued names DO converge above null, consistently, and the edge
*grows* with horizon — the opposite of what was predicted.

```
Q1: does the DCF carry per-name information?  (edge over null, BOTH sides required)
  1y: undervalued +2.65pp, overvalued +2.20pp -> YES, both sides beat null
  3y: undervalued +2.87pp, overvalued +4.12pp -> YES, both sides beat null
  5y: undervalued +1.61pp, overvalued +4.07pp -> YES, both sides beat null

overall edge over null: 1y +2.41pp (z 10.7), 3y +3.54pp (z 22.4), 5y +2.87pp (z 11.7)
sector-matched null:    1y +2.08pp,          3y +3.13pp,          5y +2.57pp
```

**It is not sector information.** Drawing the substitute return from the same sector and as-of date
leaves ~87% of the edge intact. That was the obvious objection to a positive result and it does not
hold.

**But the absolute performance is poor, and this is the other half of the answer:**

```
Q2: is it strong enough to anchor on?  (ABSOLUTE convergence rate)
  1y: converges 45.0% of the time -> diverges 55.0%
  3y: converges 38.8%             -> diverges 61.2%
  5y: converges 32.2%             -> diverges 67.8%
```

Two true statements that sound contradictory and are not: **the DCF beats a random contemporaneous
return by 2-4pp**, and **prices move away from its intrinsic values roughly twice as often as
toward them at 5y**. It tilts the odds; it does not call the outcome. At 3y the overvalued edge
moves convergence from 23.4% to 27.5% — a 17% relative improvement on an unreliable base.

### Verdict: reframe, do not remove

The predicted conclusion was right, for the wrong reason. Not "the number is meaningless" — it
carries genuine, sector-independent, per-name information, which the cross-sectional tests could
not see. But a 2-4pp tilt is **not a valuation anchor**, and presenting a precise mechanical fair
value implies far more than the evidence supports.

Recommendation for the AI Researcher: keep the mechanical DCF, present it as **one directional
input among several** rather than as a fair-value anchor. It already triangulates against ML comps;
this supports that framing and argues against restoring any single-number emphasis.

**Calibration-in-the-large is now warranted** as the secondary read — the plan deferred it pending
a signal, and there is one. It would answer whether *bigger* predicted gaps produce bigger realised
moves, which is what would distinguish "weak tilt" from "useful when the gap is large".

### METHOD ERROR worth more than the result

**The first null was wrong, and it failed on exactly the confound this plan had predicted.**

Version 1 shuffled *intrinsic values* across companies. That widened the `r_t` distribution badly
— median `|r_t - 1|` 0.461 actual vs 0.779 shuffled, p90 4.31 vs 10.68 — and wide ratios converge
**mechanically**, which is confound B, the very thing the null existed to control. The null was
easier than reality, so the real pairing looked *anti*-informative: edge -0.70pp at 1y, -3.18pp at
3y, **-6.03pp at 5y with z = -26.7**. Reported as-is that would have been a dramatic and completely
false finding: "price converges toward the DCF's fair value LESS often than toward a random
company's".

The fix: shuffle the **return**, not the intrinsic value. `r_t` is then preserved exactly (killing
confound B) while the substitute return still carries the same period's market drift (killing
confound A). The question becomes precisely the intended one — does THIS company's own price
movement carry it toward ITS OWN intrinsic value more often than a random contemporaneous return
would.

**Naming a confound in advance does not prevent building a null contaminated by it.** The tell was
a large negative result: an effect that strong in the *anti*-informative direction is nearly always
a broken control, not a discovery.

### Data — none needed, everything exists

Verified 2026-08-22. Phase 2 is hours, not days.

| need | source | status |
|---|---|---|
| Point-in-time intrinsic value | `data/dcf_reconstruction_flat_2p5/` | built |
| Price at valuation date | `price_at_computation`, same panel | built |
| Forward prices to 5y | `monthly_pe` (through 2026-08) | exists |
| Benchmark (only if design changes) | `SPY` from 1983, `VTI` from 2001 in `prices.duckdb::etf_prices` | exists |
| Sector | `company_overview` via `_join_sector` | exists |

The panel storing intrinsic value **and** the price it was struck against is what makes this
cheap; `dcf_results` never stored a price, so without the Phase 0.1 change this would have needed
an 85-minute rebuild first.

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

## Phase 4 — Calibration-in-the-large  [x] **Complete 2026-08-23 — the signal is CONCENTRATED, and it explains Phase 1**

Phase 2 deferred this pending a signal. There is one, so it is now warranted.

**Question:** does the DCF's per-name edge concentrate where its claim is strong? A DCF saying a
stock is 5% mispriced is inside its own noise; one saying 80% mispriced is a strong assertion. If
the 2-4pp tilt is real information rather than a diffuse artifact, it should be larger where the
predicted gap is larger.

**Design — reuse the validated null, do not invent a new one.** Bucket observations by the size of
the predicted gap `|r_t - 1|`, and within each bucket measure the same convergence edge over the
same return-shuffle null Phase 2 used. Split by direction as well, since the overvalued side
carried the stronger edge there.

Deliberately NOT "bucket by predicted upside and compare realised returns" — that is an
absolute-return question and carries the survivorship exposure Phase 2's design was chosen to
avoid. Staying in the ratio framing keeps delisted companies as missing observations rather than
as silent evidence for the DCF.

**PREDICTION COMMITTED BEFORE RUNNING:**

1. **The edge grows with gap size** across the low and middle buckets — if the tilt is real, it
   should concentrate where the model makes a strong claim.
2. **It flattens or falls in the largest bucket.** Extremes are where the model is least reliable;
   that is why `MAX_INTRINSIC_TO_PRICE` exists at all. Expect an inverted-U, not a monotonic rise.
3. Even in the best bucket the **absolute** convergence rate stays under 50% at 3-5y, so the
   "tilt, not anchor" conclusion survives and the recommendation does not change to "anchor on it
   when the gap is large".

**What each outcome changes.** A monotonic rise (prediction 2 wrong) would mean the DCF is most
trustworthy exactly where it is currently most distrusted, and would argue for *loosening*
`MAX_INTRINSIC_TO_PRICE` — the opposite of what Phase 3 of the predecessor plan concluded. A flat
profile (prediction 1 wrong) would mean the tilt is diffuse and not specifically about mispricing,
which would weaken the Phase 2 result considerably.

### RESULT

**The DCF's per-name information is concentrated, not diffuse.** Bucketed within direction, the
overvalued side shows ~zero edge until the DCF says a company is worth **less than 40% of its
price**, then jumps:

```
overvalued, edge over null (pp)    <25%   25-60%  60-150%    >150%
1y                                 1.26     0.95    -0.61     5.23
3y                                 0.02    -0.59     0.89    11.07
5y                                -0.21    -1.61     0.09    12.52

undervalued, edge over null (pp)   <10%   10-25%   25-40%   40-60%
1y                                 0.90     2.44     3.14     2.81
3y                                 0.74     0.72     5.10     3.68
5y                                -0.29    -0.49     0.89     3.64
```

**About half the big-gap edge is the value effect.** The obvious objection — those are high-multiple
names and the value premium already punishes them — was tested by drawing the substitute return
from the same `earnings_yield` quintile:

| horizon | vs plain null | vs value-matched null | survives |
|---|---|---|---|
| 1y | 5.17pp | 2.59pp | 50% |
| 3y | 10.96pp | 5.79pp | 53% |
| 5y | 12.61pp | 7.04pp | 56% |

So roughly half is the DCF re-deriving the value premium and **half is DCF-specific** — 2.6-7.0pp,
growing with horizon.

### This EXPLAINS Phase 1 rather than contradicting it

Phase 1 measured near-zero incremental IC over `earnings_yield` across the whole cross-section.
Phase 4 shows the signal lives in ~20% of observations. **A signal concentrated in a fifth of names
is diluted to near-nothing in a full-universe rank IC.** The two results are consistent, and this
is the mechanism behind the Phase 1 null.

### Predictions: one right, two wrong

1. **Edge grows with gap size — CORRECT**, though on the overvalued side it is a step function at
   >150%, not a gradient.
2. **Flattens or falls in the largest bucket — WRONG.** It is largest there, on both sides at 5y.
3. **Absolute convergence stays under 50% — WRONG** for undervalued names with 40-60% gaps, which
   converge 67-74% of the time. But their edge over null is only 2.8-3.7pp, so nearly all of that
   is drift and mechanical mean reversion.

**High absolute convergence is not information.** The bucket that converges most often (undervalued
40-60%, up to 74%) beats its null least; the bucket that converges least (overvalued >150%, 37-44%)
beats its null most. Reporting either number alone would mislead in opposite directions.

### A pre-stated contingency that was WRONG and is withdrawn

This plan said a monotonic rise "would mean the DCF is most trustworthy exactly where it is
currently most distrusted, and would argue for LOOSENING `MAX_INTRINSIC_TO_PRICE`."

**That does not follow.** The guard caps intrinsic/price at 2.5 — it constrains the **undervalued**
extreme (model says the stock is worth far more than it trades for). The informative bucket is
where intrinsic/price is very **low** (model says it is worth far less). **Opposite tails.** The
guard never touches the names carrying the signal, so nothing here argues for changing it. The
contingency was written without checking which tail the guard bounds; committing a prediction in
advance does not make its reasoning correct.

Second methodological catch, same shape as Phase 2's null error: the first Phase 4 run bucketed by
gap size **pooled across direction**, which is confounded. Because the guard caps intrinsic/price
at 2.5, `px/iv >= 0.4` and the undervalued gap cannot exceed 60% — so every pooled bucket above 60%
is **100% overvalued**, the side with the stronger edge. The apparent "inverted-U then spike" was a
direction-mix artifact. Bucketing within direction removed it.

### Recommendation — narrowed, and now actionable

The Phase 2 recommendation ("present as one directional input rather than a fair-value anchor")
stands and is **narrowed by this result**: the mechanical DCF is most worth surfacing when it
disagrees with the market **by a lot and to the downside** — price above ~2.5x intrinsic. In the
middle of the distribution it carries essentially nothing beyond the value factors.

Concretely for the AI Researcher: the DCF deserves narrative weight when `price / intrinsic > 2.5`,
and deserves very little when the gap is moderate. That is a sharper instruction than "one input
among several", and it is supported rather than assumed.

**Not yet implemented** — this is a product change and should be decided explicitly.

## Phase 5 — Act on it in the AI Researcher  [ ] **NEXT**

Phases 1-4 measured. This is the only phase that changes the product.

**The finding to implement:** the mechanical DCF carries measurable per-name information *only*
in the extreme-overvalued regime — price above ~2.5x intrinsic — where the edge is +11 to +12.5pp
over a matched null and roughly half survives controlling for `earnings_yield`. Below that it is
~0 and the DCF is re-deriving the value effect at best.

**ARCHITECTURAL CONSTRAINT discovered while scoping (2026-08-23).** The obvious home for this rule
is the Valuation Analyst, and that is **wrong**: `api/prompts/research_valuation.md` line 7 forbids
that agent from using the words "price", "target price" or "upside" at all — it is deliberately
price-blind so its fair value is not anchored backwards from the market. A `price / intrinsic > 2.5`
rule cannot live there.

The rule belongs with the **Chief Analyst** (`research_chief_core.md`), which is price-aware and
makes the rating call comparing `current price` to `fair_value_base`.

**SECOND PRECISION POINT.** The measurement is about the **mechanical** DCF's intrinsic value
(`run_dcf_av` under engine defaults), NOT `fair_value_base` — which is the Valuation Analyst's
judgment and may have anchored on the AI DCF instead. Applying the threshold to `fair_value_base`
would apply a finding about one number to a different one. The flag must be computed from the
mechanical intrinsic value specifically.

**The signal is GRADED, not binary** (checked 2026-08-23 before writing the note, because the
first live example came out at 125x intrinsic — far beyond anything the calibration covered, and
plausibly a near-zero-intrinsic computation artifact rather than a valuation). It is not an
artifact of the extreme tail:

| | n (3y) | edge 3y | edge 5y |
|---|---|---|---|
| 2.5-12x (median of the bucket is 5.2x) | 4,689 | +8.31pp | +10.47pp |
| >12x | 1,535 | +19.39pp | +19.29pp |

The edge holds where most such names sit AND strengthens further out, so the note grades its
language by ratio rather than quoting one number.

**Implementation:** a deterministic helper reads the cached mechanical DCF (`dcf_results`, refreshed
monthly by `compute_dcf_batch.py`) plus current price, computes the ratio, and appends a calibrated
note to `chief_context`. Deterministic rather than asking the LLM to do the arithmetic and apply a
threshold — an LLM applying a numeric rule is the less reliable half of this. No extra DCF run: it
reads the existing cache, not `compute_dcf_scenarios` a second time.

---

## Panel inventory — CHECK THIS BEFORE ANY A/B

Four reconstructed panels are on disk and **they were not all built under the same
`dcf/model.py` constants.** Mixing them produces confounded results; this already happened once
and produced a fake 18.8pp "coverage collapse". Verified 2026-08-22 by `max(intrinsic/price)`:

| panel | rows (ok) | built under | use |
|---|---|---|---|
| `data/dcf_reconstruction_flat_2p5/` | 46,652 | **2.5x** | **CURRENT baseline — use this** |
| `data/dcf_reconstruction_tgcapped/` | 47,146 | 2.5x | terminal-growth experiment, rejected |
| `data/dcf_reconstruction/` | 61,289 | 10x | **STALE** — predates the guard change |
| `data/dcf_reconstruction_smallcap/` | 15,918 | 10x | $300M-1B band |

**Note on the small-cap panel:** it was built under 10x, so the 2.5x and 2.0x rows in its results
table were produced by **post-hoc filtering, not a rebuild**. Post-hoc filtering flatters (see
constraint 2 below), so treat those two rows as optimistic. The headline small-cap claim uses the
10x row, which is the honest one for that panel.

Rebuild command (~85 min, resumable, 6 workers):
```bash
uv run scripts/reconstruct_dcf_panel.py --workers 6 --out-dir data/<name>
```

---

## Logging: the plan is not the artifact

**Caught 2026-08-23, after the fact.** Phases 2, 4 and 5 were written up in this plan and
summarised in memory, and neither reached `docs/dcf_upside_factor_test.md` — the file anyone
actually reads to learn what this repo knows about the DCF. It still said **REJECTED** with no
mention of the per-name result, and its "what was not tested" list still named single-name
usefulness as untested, two days after it had been tested and found positive.

So it was not merely incomplete, it was **wrong in a way that would have propagated**: a reader
would have concluded the DCF carries no per-name information and that nobody had checked.

**Plans get archived; findings docs are read.** "Recorded in the plan" is not "logged". When a
phase produces a result, it goes in the findings doc in the same commit — the plan tracks *how the
work went*, the doc states *what is true*. Fixed in 5906c0c.

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
