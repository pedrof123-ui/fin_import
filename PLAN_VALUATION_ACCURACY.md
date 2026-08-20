# Valuation Engine — Accuracy Improvements

## ML comps validation — result (run 2026-08-19 12:55-15:05, 130 min)

**The pre-committed prediction held.** `evebitda` was the multiple predicted to improve, and it is
the only one that moved.

```
Multiple   RMSE before  RMSE after   dRMSE    Improve before -> after   Result
--------------------------------------------------------------------------------
pe              0.8324      0.8336   +0.14%   +18.3% -> +18.2%   PASS -> PASS
evebitda        0.8996      0.7552  -16.05%   +14.8% -> +26.4%   FAIL -> PASS
pfcf            0.9063      0.9072   +0.10%   +19.0% -> +18.9%   PASS -> PASS
ps              1.0681      1.0664   -0.16%   +23.4% -> +23.5%   PASS -> PASS
```

The three control multiples moved 0.10-0.16% in RMSE — refit noise. `evebitda` moved 16%, about
100x more, and crossed the 15% gate it had been failing. Because the three multiples that do not
take debt as an input stayed still while the one that does moved, the change is attributable to
the debt fix rather than to refitting. Coverage stayed in range (74.1% -> 74.5%).

**This closes the "stable near-miss" tracked since 2026-08-13.** Its cause was the
`debt_to_ebitda` defect feeding enterprise value, not a modelling shortfall. No EV/EBITDA-specific
model work is needed.

Run was verified to have actually executed before the numbers were read — exit clean, report mtime
15:05, both output files' checksums changed from the committed baseline, zero error lines. (The
two earlier lost attempts wrote nothing and left byte-identical files, which reads exactly like
"the fix changed nothing".)

## Sector-join fan-out found while running the factor diff

`_join_sector` merged `company_overview` without deduping. That table holds one row per refresh —
9,336 rows for 2,661 tickers — so the merge fanned every `(ticker, month_end_date)` row out into
up to 5 copies: 651,684 rows became 2,409,325, and the walk-forward universe 267,594 became
1,019,621. Duplicates carry identical sector values, so nothing was misclassified; the damage is
silent re-weighting, with a ticker counted up to 5 times in fold sizes, model fitting and IC.

This exact bug was fixed in `run_backtest.py` at `0d16007`, comment and all, but only there. The
other three call sites still had it. Fixed all of them: `run_walkforward.py`, `run_risk.py`, and
`run_baselines.py`.

`run_baselines.py` additionally selected `symbol AS ticker`; the column is `ticker`, so the query
raised `BinderException`, the bare `except` swallowed it, and that script had **never** joined
sector at all — it only ever logged a warning. Fixed with the same dedupe.

The first factor-diff run was started before this was found and was killed; its inputs were the
duplicated ones. The re-run is the one that counts.

## Walk-forward factor diff — result (run 2026-08-19 15:08, 60s)

Run after the sector-join fix, so the universe is 267,594 rows / 1,954 tickers rather than the
inflated 1,019,621. 35 folds, 33 features, target `ret_1y`.

| Aggregate OOS | Before (Jun 29) | After |
|---|---|---|
| `mean_oos_r2` | -0.5536 | -0.5121 |
| `mean_rank_ic` | -0.0169 | -0.0163 |
| `mean_rank_icir` | -0.2289 | -0.4335 |
| `mean_rank_icir_nw` | -1.2068 | -2.4771 |
| `mean_hit_rate` | - | 0.4619 |

**The debt fix did not change this model's verdict, and the verdict is negative.** Mean rank IC is
-0.016 before and after: no out-of-sample edge on `ret_1y` in either version, with R2 negative
throughout. `debt_to_ebitda` importance moved 0.0263 -> 0.0276, mid-pack among 33 features, which
is the reason a large correction to its values barely moves the aggregate.

**Read this diff with care — two changes are confounded in it.** The before-column predates both
the debt fix *and* the sector-join fix, and the baseline itself was produced on 3.8x duplicated
rows. So the small aggregate movements cannot be attributed to the debt fix alone, and the
before-column is not a trustworthy baseline in any case. The durable finding is the level, not the
delta: this model does not predict `ret_1y` out of sample, which was already true in June.

Unlike the ML comps result above, this one had no pre-committed directional prediction, so it is
an observation rather than a passed test.

## Two test-fragility bugs, both now fixed (suite green)

Both were tests that used **live data as their own reference**, so they passed only while the
data happened to agree with them. Neither was a code regression.

**1. `test_cycle_data.py::test_leverage_is_not_read_from_the_broken_column` — FIXED**
Asserted `q.leverage > stored * 3` where `stored` is the live `pe_stats.debt_to_ebitda`. That
held only while the column was broken. The recompute fixed it (CLF 0.53 -> 12.38, verified
against the pre-recompute backup) and `assess_trough_quality` independently computes
12.384244372990354, so code and column now agree exactly and the assertion inverted. Repointed to
the historical broken constant (0.5299539170506913).

**2. `test_research_ai_dcf_integration.py` (2 tests) — FIXED**
The fixture hardcodes `cycle_position="TROUGH"` with a comment reading "TXN computes TROUGH
against the live database", and QC compares the two, so `findings == []` silently depended on TXN
remaining a trough-cycle name. It no longer is. `compute_cycle_position` is now pinned in the
shared `_patch_network_calls` helper.

**Correction to an earlier note in this file:** these two were first recorded here as recompute
fallout. That was an inference, and checking it showed it was wrong — TXN computes `MID` against
**both** the live database and the pre-recompute backup, so the recompute did not cause it. They
were already failing beforehand, from an earlier data refresh that moved TXN off TROUGH. The
stash-and-rerun only established that today's sector-join fix was not responsible; it did not
establish what was.

Suite: **587 passed, 3 skipped, 0 failed.**

**Still open, needs a paid run to settle:** the plan notes below that `research_regression.py`
gates fair value to 0.15x-5.0x of price and that MU fails it. MU's mechanical DCF is now an
explicit `status='error'` ("Intrinsic value per share is not positive (-50.64)") rather than
-$16,932, so the AI Researcher takes its degradation path. Whether the report-level fair value now
lands in the gate cannot be read from the database — it needs an actual report run, which costs
money. Not run.

## Backtest baseline regeneration — prediction stated before the run

Written 2026-08-19 before the numbers exist, same discipline as the ML comps prediction that held.

**Why the documented baseline is stale on two counts.** `_BACKTEST_METRICS` in
`scripts/score_live.py` (`gr_top_n_25` 17.0% CAGR / 0.960 Sharpe) predates (a) the `_join_sector`
dedupe fix in `run_backtest.py` (`0d16007`, 2026-07-23) and (b) today's debt recompute. These
numbers are displayed in live scoring output.

**Use the right before-value.** A corrected post-`0d16007`, pre-debt-fix run recorded 15.96% CAGR
/ 0.952 Sharpe for `gr_top_n_25`. **That is the apples-to-apples baseline, not the documented
17.0% / 0.960**, because comparing against the documented figure would measure the join bug and
the debt fix at once. This is the same reading rule as the walk-forward diff.

**Mechanism.** `ev_ebitda` is 1 of 4 factors in `_VALUE_COLS` and is lower-is-better. The broken
EV omitted most debt, so levered companies looked cheaper than they were and scored too well. The
corrected EV moves them down the value ranking.

**Prediction:**

| Metric | Expectation |
|---|---|
| `gr_top_n_25` MaxDD | improves (less negative) — fewer over-levered names selected |
| `gr_top_n_25` Sharpe | improves modestly from 0.952 |
| `gr_top_n_25` CAGR | **no direction predicted** — leverage boosts returns in bull runs, so this can fall even if the portfolio is better |
| `f_low_evebitda` single-factor | moves most of any single-factor portfolio; it is the direct read on the fix |

Stating no direction for CAGR is deliberate: predicting everything improves is unfalsifiable.
The claim under test is that the portfolio's *risk* profile improves because a leverage blind spot
was removed, not that the strategy earns more.

Run: `run_backtest.py --model --guardrails --vol-weight --regime-filter --tc-bps 10`
(pipeline uses only `--model --guardrails`; the `vw_`/`rf_` entries need the other two).

## Backtest regeneration — result (2026-08-19). Prediction half held.

`_BACKTEST_METRICS` updated in `scripts/score_live.py`. Run on a model retrained after a *fifth*
fan-out site was found in `train_model.py` (see below), so these are the first figures in this
file computed from fully deduplicated inputs.

### Scoring the prediction

| Predicted | Outcome | Verdict |
|---|---|---|
| Sharpe improves from 0.952 | 0.952 -> **0.980** | **held** |
| MaxDD improves | -39.7% -> **-44.7%** | **failed** |
| CAGR — no direction stated | 15.96% -> 18.33% | n/a (correctly not predicted) |

**The MaxDD claim failed and the mechanism behind it was wrong.** The reasoning was that
correcting enterprise value would push over-levered names down the `ev_ebitda` ranking and so
shallow the drawdown. Drawdown got ~5pp deeper instead. Two caveats that do *not* rescue it: the
only MaxDD available to compare against is the doubly-stale documented figure (no MaxDD was
recorded for the intermediate post-join-fix run), and the sample is 406 months against 404. Both
make the comparison imprecise — neither makes a predicted improvement into an observed one.

Beta did improve (0.781 -> 0.741), which is consistent with the leverage story; MaxDD is not.
The honest summary is that the risk profile changed in mixed directions, and the specific claim
made in advance was not supported.

### The model got worse, and that is the correct number

| Portfolio | Before (stale model) | After (retrained, clean) |
|---|---|---|
| `xgb_gr_top_n_25` | 15.53% / 0.841 | **13.08% / 0.737** |
| `vw_xgb_gr_top_n_25` | 15.18% / 0.861 | **13.36% / 0.782** |
| `rf_xgb_gr_top_n_25` | 14.67% / 0.897 | **12.72% / 0.805** |

Every model portfolio dropped 2-3pp of CAGR once trained on deduplicated rows. Read this the way
[[feedback_baselines_fitted_on_wrong_inputs]] prescribes: the *new* number came from correct
inputs, so the previous figures were inflated, not the new ones depressed. Plausible mechanism,
stated as hypothesis: duplication weighted frequently-refreshed tickers up to 5x, and AV refreshes
current index members most, so the training set was tilted toward names that survived — a
survivorship tilt smuggled in through a join. Not proven here.

**Consequence worth noting:** the composite now beats the model decisively on every configuration
(live `vw_gr_top_n_25` 17.81% / 1.012 vs `vw_xgb_gr_top_n_25` 13.36% / 0.782). The live strategy
is the composite, so this argues the current live choice is right — and it argues more strongly
than the old numbers did, where the gap was ~1.5pp rather than ~4.5pp.

**Also fixed while here:** `rf_vw_*` entries are copies of `rf_*`. `run_backtest.py` never produces
a regime-filtered *and* vol-weighted portfolio, yet `_portfolio_label` can generate that label, so
those rows would display `rf_*` numbers as though measured. Now stated in a comment rather than
left silent. Fixing it properly means a change to `run_backtest.py`; not done.

## Calibration-streak purge: not needed, and it surfaced a real gap

Asked to purge the pre-2026-08-19 calibration months so the streak toward the Phase 9 review
restarts on uncorrupted debt. **Inspected before deleting: there is nothing to purge.**

`ml_model_metadata` holds 8 rows, one per (model_name, model_version, target) — model training
records, not a monthly metrics log. Only the three currently-active `2026-08-01` rows (pe, pfcf,
ps) carry OOS metrics at all; the `2026-07-20` and `2026-07-21` rows have NULL metrics.
`update_active_ml_model_oos_metrics` is a targeted UPDATE on the *active* row, so today's
validation already overwrote those three with post-fix numbers (pe 0.8336/+18.24%/0.7478 —
matching today's report exactly). The report confirms it:

    pe   (2026-08-01): OK, 1 consecutive month(s) holding
    pfcf (2026-08-01): OK, 1 consecutive month(s) holding
    ps   (2026-08-01): OK, 1 consecutive month(s) holding

No pre-fix calibration metrics survive anywhere, so a purge would delete nothing. Deleting the
07-20/07-21 rows would only destroy training provenance for no benefit.

### The real gap: evebitda is not tracked at all

`PASSING_MULTIPLES = ["pe", "pfcf", "ps"]` gates **four** things at once — training, production
scoring, the streak report, and the tests. evebitda was excluded on 2026-07-20 for missing the
RMSE bar "by 0.3pp ... until revisited", so it has no trained model, no active row, and
`update_active_ml_model_oos_metrics` no-ops for it. It is validated every month and the result is
discarded, which means **it can never accumulate the streak that its own promotion would depend
on.**

This is the revisit. evebitda now clears all three gate criteria decisively (+26.4% RMSE
improvement, second-best of the four; 100% fold win; 74.5% coverage).

**Decision needed, because there is no track-without-scoring path** short of splitting the
constant: adding evebitda to `PASSING_MULTIPLES` also puts it into production AI Researcher
scoring. Precedent argues for adding it — pe and pfcf were included on a single passing run
(2026-07-20) and ps on a single run (2026-07-21), so requiring more of evebitda would be
inconsistent. The 6-month streak exists to gate the *Phase 9 anchor promotion* (replacing
`goal_pe`/`goal_low`/`goal_high`), not inclusion in the multiple set.

## Upper guard result (rebuild 2026-08-19, 1,042s)

`MAX_INTRINSIC_TO_PRICE = 10.0` in `dcf/model.py`, symmetric with the non-positive guard and
skipped when no usable price exists. Rebuild reclassified **74 tickers** (predicted ~75).

| | Before guard | After guard |
|---|---|---|
| `status='ok'` | 2,220 | 2,144 |
| `status='error'` | 441 | 517 |
| negative intrinsic values | 0 | 0 |

Distribution of intrinsic value as a multiple of price, across `ok` rows:

| | p50 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|
| before | 0.75x | 2.86x | 6.01x | 35.47x | **46,418x** |
| after | 0.72x | 2.21x | 3.50x | 6.64x | **9.6x** |

The tail is gone and the centre is untouched — the median moved 0.75x -> 0.72x. 250 tickers
(11.7%) still sit above 2x, which is intended: a genuinely mispriced company can be worth several
times its price, and the guard only rejects the indefensible.

**76 tickers moved ok -> error, of which the guard explains 74.** The other two come from price
movement between the measurement and the rebuild, which also shifted individual ratios (GNTX read
46,418x when measured and 46,496x on the rebuild; D moved 13,188x -> 18,037x).

**Now ~19.4% of the universe has no mechanical DCF** (517 of 2,661), up from ~16.6%. The AI
Researcher takes its degradation path that much more often. This is the cost that was accepted
when choosing 10x over a tighter bound; revisit with `5x -> 64 more tickers (3.0%)` and
`3x -> 138 (6.4%)` once the production degradation rate has been observed.

## EV/EBITDA promoted to production (`1b0c40e`)

Added to `PASSING_MULTIPLES`, which gates training, production scoring, the streak report and the
tests together. Model trained (`evebitda_2026-08-19.joblib`); scoring verified end-to-end,
`ml_fair_evebitda_*` populated and feeding `ml_fair_price`.

Included on the same basis as the other three — one passing gate run each — now that it clears all
criteria decisively (+26.4% RMSE improvement, second-best of four; 100% fold win; 74.5% coverage).

`report_ml_comps_calibration.py` currently prints `evebitda: WARNING no OOS metrics for latest run`
and a shortest-streak of 0. That is expected and self-resolving: the row was created after today's
validation ran, and the monthly pipeline runs validation before the report, so 2026-09-01 fills it.
Metrics were deliberately **not** hand-written into the row — the report's precision exceeds what
the summary table carries, and transcribing rounded numbers into a database that feeds a
promotion decision is not worth the convenience.

## AI Researcher regression, run 2026-08-19 (~$2-3 of API spend)

`scripts/research_regression.py`, 5 tickers plus the degradation case, 36 min.
**NVDA, UPS, KO and FANG pass every gating check. The `ZZZZNOTATICKER` degradation case passes.
MU is the only failure**, on two checks.

Prediction stated before the run was that removing MU's bad mechanical DCF might not bring it into
the 0.15x-5.0x gate. **It did not.** MU now fails at `base $33.15 vs price $937.11 = 0.04x`,
below the floor rather than via the old -$16,932 route.

### The second failure is a defect this plan's own guard introduced

    [FAIL] has valuation model tables

MU's report has **no Valuation Model Detail block at all** — no Key Fundamentals, no Comparable
Companies, no Model Summary. `_assemble_deterministic_tables` (`api/research_router.py:2253`)
builds the whole block as all-or-nothing:

    valuation_tables_md = render_valuation_model_tables(...) if needs_valuation and scenarios is not None else ""

`compute_dcf_scenarios` now raises for MU, so `scenarios is None` and the entire block is dropped.
But of the four tables inside it, **two need nothing from the DCF** — `_fundamentals_table(ticker)`
and `_comps_table(ticker)` take only the ticker. `_model_summary_table` takes scenarios but also
takes the multiples and the Valuation Analyst's fair values, so it could render without the DCF row.

**Scope: this got much worse today.** Before the guard, MU had a negative-but-`ok` DCF, scenarios
computed, and all four tables rendered. Now 517 tickers (19.4%) have no mechanical DCF, and every
one of them loses its comparables and triangulation tables too — not just its DCF table. The
degradation path is more degraded than it was designed to be.

There is a particular irony in the Model Summary vanishing: the Fair Value Triangulation table is
exactly what would show a reader that $33.15 against a $937.11 price is not supported by the
multiples sitting next to it.

**FIXED 2026-08-20.** `_dcf_assumptions_table` returns `""` when `scenarios is None` (it is the
one block that is wholly DCF-derived); `_model_summary_table` accepts None and marks the DCF row
`n/a`, exactly as it already did for individual failed scenarios; the AI-vs-mechanical comparison
table is skipped since there is nothing to compare against; and the assembly no longer gates the
whole block on `scenarios is not None`. Verified: MU now renders 2,151 characters of tables
(Key Fundamentals, Comparable Companies, Model Summary) where it previously rendered `""`, and
FANG is byte-for-byte unaffected with all four tables.

### MU: corrected AGAIN 2026-08-20 — the cross-checks are not independent

**This entry has now been wrong twice, in opposite directions.** First recorded as "probably a real
disagreement rather than a bug", then revised to "looks like a real bug" on the grounds that the
Valuation Analyst sat 14-65x below every other row in the triangulation table. That second reading
was wrong, and the error was treating those rows as independent evidence.

MU is in a historic memory/AI-datacentre boom. Its own numbers say so unambiguously:

| MU | Value | Against its own history |
|---|---|---|
| TTM EPS | $44.08 | its all-time max; median since 2016 is **$3.61** -> **12.2x** |
| Forward 12m EPS | $73.39 | analysts project the peak extending further |
| Operating margin | 65.8% | 5yr median 22.6% -> **2.9x** |
| 1yr earnings growth | +992% | against a 3yr CAGR of -0.7% |

**Every row in that table is anchored on peak-cycle inputs.** The multiples rows multiply the
ticker's *normal-times* historical multiple by its *peak* forward metric — `pe_med_5y 21.34 x
fwd_eps 73.39 = $1,566`. That is the peak-earnings trap expressed as a number, and it is precisely
what the peak rubric exists to warn against. The ML comps row is no better: it is peer-relative,
and the entire memory/semiconductor peer group is at peak simultaneously, so the peer median
carries the same inflation with no un-peaked reference anywhere in the cross-section.

So "disagrees with every cross-check" carried far less weight than claimed — the cross-checks
share one failure mode.

**What the Analyst's number actually looks like:**

| Anchor | Fair value |
|---|---|
| `pe_med_5y x fwd_eps` (peak) | $1,566 |
| `pe_med_5y x half-way to mid-cycle` | $509 |
| `pe_med_5y x mid-cycle EPS $3.61` | $77 |
| `pe_p25 x mid-cycle EPS` | **$38** |
| Valuation Analyst base | **$33.15** |

$33.15 sits essentially on a 25th-percentile multiple applied to mid-cycle earnings. That is a
coherent deep-bear normalisation, not a broken calculation, and normalising *downward* is the
correct treatment for a company the system correctly flagged `PEAK`.

**The genuine anomaly is narrower: the band, not the level.** `$18.61 / $33.15 / $34.11` puts the
high only 2.9% above the base. For a cyclical at a 12x-median earnings peak, a plausible bull case
is not 3% above the bear-normalised base. The compressed upper bound is what to investigate; the
low level is defensible.

**And the regression gate may itself be mis-specified.** `research_regression.py` requires fair
value within 0.15x-5.0x of price. That assumes fair value tracks price — the exact assumption a
peak-earnings trap denies. If MU is genuinely at 12x normalised earnings, a correct through-cycle
valuation *should* fall below 0.15x of price, and the gate would flag correct behaviour as a
failure. Before treating MU's gate failure as a defect, decide whether the gate should exempt
tickers the cycle block flags `PEAK`.

**Superseded reading follows, retained so the reasoning error stays visible:**

This was first recorded here as "probably a real disagreement rather than a bug", on the reasoning
that a peak-cycle semiconductor invites a low through-cycle valuation. **Restoring the
triangulation table refutes that.** MU's Model Summary now reads:

| Method | Low | Base | High |
|---|---|---|---|
| DCF (scenario) | n/a | n/a | n/a |
| ML Comps (peer-relative) | $282.12 | $1450.10 | $5894.26 |
| Multiples (P/S x Fwd Rev/Share) | $333.43 | $453.90 | $716.51 |
| Multiples (P/E x Fwd EPS) | $768.06 | $1566.20 | $2373.36 |
| Multiples (P/FCF x Fwd FCF/Share) | $814.35 | $2141.75 | $3396.42 |
| **Valuation Analyst Fair Value** | **$18.61** | **$33.15** | **$34.11** |

Every independent cross-check — peer-relative ML comps and all three of the ticker's-own-history
multiples — lands between $454 and $2,142 at the midpoint. The Valuation Analyst returns $33.15,
roughly 14-65x below every other row and 0.04x of the $937.11 price. A defensible bear case on a
cyclical peak does not sit an order of magnitude under the most conservative cross-check
available. **The likely fault is in the Valuation Analyst's behaviour when the mechanical DCF is
unavailable** — the degradation path — not in the cycle assessment, which correctly flagged PEAK.

Not yet diagnosed. It is now at least *visible*, which it was not before this fix: the table that
exposes it is precisely the one that had been dropped along with the DCF.

## MU DCF diagnosis 2026-08-20 — capex shape is the smallest of four problems

Asked whether an exponential capex taper would serve better than the current linear one.
**Measured answer: no.** Capex is the smallest of the drags and the fade already works — capex
converges exactly to D&A by year 10 ($126.2bn = $126.2bn).

FCFF decomposition, MU, $bn:

| yr | NOPAT | D&A | capex | capex-D&A | dNWC | FCFF |
|---|---|---|---|---|---|---|
| 1 | 4.8 | 32.7 | 44.2 | 11.4 | **27.7** | **-34.3** |
| 2 | 6.2 | 42.6 | 57.4 | 14.8 | 12.1 | -20.7 |
| 3 | 7.9 | 53.9 | 70.3 | 16.4 | 13.9 | -22.5 |

**The decisive test:** set capex to D&A *instantly* in year 1 — more aggressive than any
exponential taper can be — and FCFF is still **-$22.9bn**. Fix the margin to the 22.6% 5-year
median *as well* and it is still **-$8.0bn**. Capex shape cannot reach this.

### Ranked by magnitude, the real causes

**1. Year-1 revenue growth is 194.4% and is not capped.** `MAX_FADE_START_GROWTH` caps year 2
(103.3% -> 30.0%, working correctly) but year 1 is deliberately exempt, on the stated reasoning
that it "is largely analyst consensus one year out, which is a real estimate rather than an
extrapolation". For MU it is not: revenue jumps ~$37.4bn -> $110.0bn in one year, and every later
year compounds from that inflated base to $424bn by year 10. This plan already predicted it —
*"a cap on the year-1/year-2 growth rate is probably needed as well: 194% and 103% are not
forecasts at any horizon"* — and only the year-2 half shipped.

**2. Working capital, $27.7bn in year 1** — the single largest term, larger than NOPAT, D&A and
the capex gap combined. NWC is days-based, so it scales with that inflated revenue path. It is a
symptom of (1) rather than an independent defect.

**3. EBIT margin of 5.2%, from `_median_ebit_margin`** — the median of MU's last three annual
margins, `26.4%, 5.2%, -37.0%`. The median lands on the transition year between the memory bust
and the boom. **The model pairs peak-derived growth with cycle-spanning margins**, so MU is
forecast to win the AI boom on volume ($424bn revenue) while never earning from it (5.2%). Those
two assumptions come from different phases of the cycle and should not be combined. This is
[[project_cycle_awareness]]'s "normalise the MARGIN not the EPS level" lesson surfacing in the DCF.

**4. Capex above D&A, $11.4bn** — real, already faded, and the smallest of the four.

**Recommended order if this is picked up: cap year-1 growth first.** It is the root of (1) and (2)
and the same one-line shape as the year-2 cap already shipped. Leave the capex fade alone.

## The compressed fair-value band — diagnosed, prompt conflict

MU's `$18.61 / $33.15 / $34.11` has its high 2.9% above base. `api/prompts/research_valuation.md`
contains a conflict for exactly this case:

- **DEGRADATION rule (line 145)**: with both DCF sources unavailable, "fall back to a
  multiples-only valuation (normalized P/E x **forward EPS** ...)". For MU that is
  `21.34 x $73.39 = $1,566`.
- **Cycle guidance (line 142)**: MU is stated `PEAK`; peak earnings are not to be trusted.

The Analyst followed the cycle guidance over the literal degradation instruction and normalised
EPS down to roughly mid-cycle — landing at $33.15, near `pe_p25 x mid-cycle EPS = $38`. That is
the better judgement, but it means **the band is built by varying the multiple around a single
normalised EPS**, which mechanically compresses it. Nothing instructs the high case to represent
the cycle *sustaining*, which for a company in a real AI-driven boom is the obvious bull case.

**Fix (not made — it is a prompt change affecting every report and needs a paid run to validate):**
have the degradation rule defer explicitly to the cycle position, and require the high case to
reflect the elevated cycle persisting while the low reflects full mean reversion.

## Guard threshold decision, 2026-08-20

`MAX_INTRINSIC_TO_PRICE` **stays at 10.0**. Reviewed and deliberately not tightened: the
production degradation rate has not been observed yet, the first monthly pipeline under the new
guard runs 2026-09-01, and 5x/3x are costed (64 and 138 further tickers) whenever that evidence
arrives. Revisit after the September run, not before.

## Regression gate now exempts PEAK tickers

`research_regression.py`'s 0.15x-5.0x price-proximity band assumed fair value tracks price — the
exact assumption a peak-earnings trap denies. MU at 12.2x its median EPS *should* value below the
floor, so the gate was flagging correct output, and a gate that fires on correct output is one
people learn to ignore. For `PEAK` tickers the ratio is now informational; their real gate is the
cycle-position and callout assertion, which MU already passes.

## Year-1 growth cap — predictions stated before the universe rebuild (2026-08-20)

`MAX_YEAR1_GROWTH = 0.60` in `dcf/forecaster.py`. Chosen from a random 347-ticker sample: median
year-1 growth -2.0%, p90 31.0%, p95 61.6%, p99 2,257%, max 5,520% (BWAY; also FBRX 5,067%, NEO
4,929%). 60% sits at ~p95, binds on ~5.5% of tickers, and is above MU's actual +48.9% trailing
growth so it does not bind below observed reality.

**The exemption it removes rested on a false premise.** `extend_growth_years` justified leaving
year 1 alone because it "is largely analyst consensus one year out, which is a real estimate
rather than an extrapolation". `_rev_forecast_y1y2` builds year 1 as `0.5 x quarterly momentum +
0.5 x annual EWM growth`, and `_quarterly_momentum_signal` adds an unbounded linear trend projected
one step ahead — so for an accelerating company it extrapolates the acceleration. No analyst
estimate enters it at any point.

Verified on MU before the batch: year 1 `194.4% -> 60.0%` ($110.0bn -> $59.8bn), year 2 correctly
rebased ($223.7bn -> $77.7bn), FCFF year 1 `-$34.3bn -> -$12.9bn`.

**Predictions:**

| | Expectation |
|---|---|
| MU's DCF | **still fails.** The 5.2% margin is untouched and is now the binding constraint — with margin at the 22.6% median and capex at D&A, FCFF is now +$1.4bn where it was -$8.0bn, so scale is fixed and margin is not |
| `status='error'` count | **falls** from 517 — fewer runaway-revenue negative-FCFF failures |
| 10x guard hits | **falls** from 74 — inflated revenue drives absurd-high valuations too, not only negative ones |
| intrinsic/price distribution | tightens; median moves little, having been a healthy 0.72x |

Stating that MU still fails is the point: this cap targets scale, not profitability, and claiming
it fixes MU would be claiming more than the mechanism supports.

## Year-1 cap — result (rebuild 2026-08-20, 1,022s). All four predictions held.

| | Before | After | Predicted |
|---|---|---|---|
| `status='ok'` | 2,144 | 2,155 | — |
| `status='error'` | 517 | **506** | falls — **held** |
| 10x guard hits | 74 | **71** | falls — **held** |
| MU | error (-50.56) | **error (-8.13)** | still fails — **held** |
| median intrinsic/price | 0.72x | 0.72x | moves little — **held** |

MU improved 6x toward zero (-$50.56 -> -$8.13) without crossing it, which is exactly what a
scale fix and not a profitability fix should do. Its 5.2% EBIT margin is now unambiguously the
sole remaining cause.

**Honest note on the fourth prediction.** "Distribution tightens" is at best weakly supported:
above 2x went 250 -> 246, but above 3x went 138 -> 140 and above 5x 64 -> 65. The distribution is
essentially unchanged, not tightened. Only the "median moves little" half was clearly right.

**And the aggregate effect is small: 11 fewer errors, 3 fewer guard hits.** Only ~5.5% of tickers
have year-1 growth above 60%, and many of those were failing for other reasons as well, so the
correction rarely changes an outcome on its own. This was worth doing because the exemption rested
on a false premise and a 5,520% one-year forecast is indefensible per-ticker — not because it
moves universe-level numbers, which it barely does. Recorded so nobody later mistakes it for a
headline improvement.

## EBIT margin window 3yr -> 5yr — predictions before the rebuild (2026-08-20)

`_EBIT_MARGIN_YEARS = 5` in `dcf/model.py`. The 3-year window could not produce a normalised
margin for a cyclical: MU's last three annual EBIT margins are `26.4%, 5.2%, -37.0%`, so the
median landed on the bust-to-boom transition year at 5.2% and the DCF forecast MU to win the AI
boom on volume while never earning from it. Five years gives 22.7%, matching the 22.6%
`operating_margin_5y_median` that `pe_stats` and the cycle rubric already treat as MU's normal
margin — **the DCF and the cycle assessment now agree on what "normal" means.**

Sample of 372 tickers: median change **+0.00pp** — no effect on the steady majority. 26.3% move
>2pp, 11.0% >5pp. Large movers are cyclicals in both directions (NUE +8.3pp, NBR +15.4pp, CNX
+15.9pp up; BVN -29.5pp, HP -10.2pp down). Correcting downward as readily as upward is what makes
this normalisation rather than a bull bias.

**Verified before the batch, so these are observations not predictions:** MU's FCFF turns positive
from year 2 (-4.1, +0.2, +2.3, +5.3, +9.5 $bn) and it now computes **$135.28** where it previously
failed outright. Against a ~$937 price that is 0.14x — a coherent peak-earnings-trap reading:
at normalised margins MU is worth $135 and the market is paying $937 for the peak.

**Predictions:**

| | Expectation |
|---|---|
| `status='error'` | **falls** from 506 — trough margins were a major source of negative FCFF |
| 10x guard hits | **rises** from 71 — higher normalised margins push cyclical valuations up, and the guard catches the top tail |
| median intrinsic/price | **rises** from 0.72x |

**Flagged before measuring, because it could be the real story:** FANG moved $158.79 -> $616.00,
from 0.76x to **2.95x** of price — a 4x jump. That is the largest single-ticker move seen in any
change this session. The 5-year margin is the better-founded input, so by the standing reading
rule the new number is the one from correct inputs. But a 4x move deserves scrutiny rather than
acceptance, and if the guard-hit count rises sharply this is why.

## Margin window — result (rebuild 2026-08-20, 982s). **Two of three predictions failed.**

| | Before | After | Predicted | |
|---|---|---|---|---|
| `status='error'` | 506 | **512** | falls | **FAILED** — rose by 6 |
| 10x guard hits | 71 | **70** | rises | **FAILED** — fell by 1 |
| median intrinsic/price | 0.72x | **0.73x** | rises | held, but by 0.01x — trivial |

Distribution: above 2x `246 -> 276`, above 3x `140 -> 150`, above 5x `65 -> 59`.

**Where the reasoning was right and where it was wrong.** The mechanism held — normalised margins
did push cyclical valuations up, visible in the 2-3x band thickening. But I predicted that would
show up as *more guard hits*, and it did not: the increases landed below the 10x threshold while
the extreme tail actually thinned. Predicting a mechanism correctly is not the same as predicting
the metric, and I picked the wrong metric.

**Errors rose because the fix cuts both ways, which is the point.** Companies flattered by a
favourable 3-year window now get a lower normalised margin and fail honestly — BVN's margin went
32.1% -> 2.6%. This is normalisation, not improvement, and a net +6 errors is consistent with that.
Anyone reading "errors went up" as a regression would have it backwards.

### Correction: the FANG alarm was my own measurement error

The previous section flagged FANG moving `$158.79 -> $616.00` (0.76x -> 2.95x) as the largest
single-ticker move of the session and the thing to scrutinise. **That number was wrong, and the
fault was in my test harness, not the engine.** The scratch script called `run_dcf_av(ticker)`
without the `estimates_conn` argument that `compute_dcf_batch` passes, so it forecast from a
different input set. In production FANG computes **$203.86** — 0.98x of its $208.55 price, an
improvement on 0.76x rather than a 4x explosion.

The guard-hit figures quoted elsewhere were checked against the database and are real: GNTX
46,496x, D 12,428x, KSPI 1,763x, MUR 899x, ZTO 80x all genuinely carry `status='error'`.

**Standing lesson:** verify a single-ticker figure through the same path production uses before
raising it as a concern. A convenience wrapper that drops an argument produces numbers that look
authoritative and are not.

### Where the four regression tickers now land

| Ticker | DCF | vs price |
|---|---|---|
| MU | **$135.28** (was: failed outright) | 0.14x |
| FANG | $203.86 | 0.98x |
| NVDA | $98.09 | 0.45x |
| KO | $50.78 | 0.56x |
| UPS | $117.20 | 1.14x |
| NUE | $198.61 | — |

MU finally producing a defensible number is the substantive win here, and it is a *cycle-correct*
one: at normalised margins MU is worth $135 while the market pays ~$937 for the peak.

## Regression re-run 2026-08-20 — predictions before the run

Validating the four DCF forecast changes end to end. Two are newer than the last regression.

| | Expectation |
|---|---|
| Overall | **ALL CHECKS PASSED** |
| MU `has valuation model tables` | **passes** — MU now has a real DCF ($135.28), so `compute_dcf_scenarios` succeeds, `scenarios` is not None and all four tables render. The degraded path is not exercised for MU at all any more |
| MU price-proximity | **cannot fail** — now informational for `PEAK` tickers |
| MU `cycle_position == PEAK` | holds |
| FANG `TROUGH` + opportunity callout | holds |
| NVDA / UPS / KO | keep passing; their DCFs are $98.09 / $117.20 / $50.78 |

**The interesting number is MU's `fair_value_base`.** With a working DCF anchored at $135.28
(0.14x of ~$937) the Valuation Analyst has a mechanical anchor it did not have last time. Two
possibilities worth distinguishing:

- it lands near $135 -> the compressed `$18.61/$33.15/$34.11` band was an artefact of the degraded
  path, and the prompt conflict recorded above no longer fires on MU
- it lands near $33 again -> the compression is independent of the DCF, and the prompt conflict is
  real and still needs fixing

**No prediction is offered between those two.** That is the question the run exists to answer, and
guessing would only make the answer harder to read.

## What landed 2026-08-19

| Change | Commit | Verified effect |
|---|---|---|
| Revenue growth fades to terminal, year 2 capped at 30% | `733b038` | NVDA 13x -> 0.55x of price |
| Capex fades to D&A | `a7b4aba` | FANG 0.02x -> 2.48x |
| Non-positive intrinsic values rejected | `a7b4aba` | 567 negative DCFs -> **0** |
| Total debt from the reported field | `f0b3267` | AT&T 0.25x -> 3.03x debt/EBITDA |
| Universe recompute + DCF rebuild | (data) | `debt_to_ebitda` median 0.255 -> 2.697 |

All four pre-stated directional predictions held. Per-ticker leverage now matches values computed
independently from raw financials before the work began (NUE exactly at 1.26x; T, CCL, VZ just
under, consistent with a different quarter's EBITDA). `dcf_results`: `status='ok'` 2,616 -> 2,220
and `status='error'` 39 -> 441, which is the intended trade — 402 tickers moved from a silently
wrong number to an explicit, explained failure, and total problem tickers fell from 606 to 441.
Tests 587 passed throughout.

**Consequence to watch in production:** ~17% of the universe now has no mechanical DCF, so the AI
Researcher will take its DCF degradation path more often than before.

Created 2026-08-19. **Status: fixes shipped, recomputed, and validated — the ML comps prediction
held. Remaining open: the growth-fade decision in item 1, and the 2 AI-DCF fixture tests above.**

Both items were found while verifying PLAN_CYCLE_AWARENESS.md, not by looking for them. Neither
is caused by the cycle-awareness work, and neither belongs to that plan — they are recorded here
so they are not lost with the session that surfaced them.

Related open work: **PLAN_CYCLE_AWARENESS.md Phase 9** fixes `debt_to_ebitda` and enterprise
value (only current-portion debt is counted, a median 6.1x understatement). That is a data-input
defect in the same valuation stack, and if all three are tackled together the recompute should be
done once, not three times.

---

## 1. The mechanical DCF is driven by a non-fading revenue forecast  [x] COMPLETE — fade (733b038) + 10x guard (1b0c40e)

**Priority: high.** It is live, it is wrong, and it is silent.

`dcf_results` (2,655 tickers, computed 2026-08-01): **567 tickers, 21.7%, carry a negative
`intrinsic_value_per_share`**, and 2,616 of the 2,655 rows are marked `status='ok'`. Nothing flags
these as failures.

Magnitudes are not marginal — they are nonsense:

| Ticker | Intrinsic value per share | WACC | Terminal growth |
|---|---|---|---|
| OCTV | -$5.7 x 10^15 | 10.7% | 3.0% |
| SHAZ | -$600,745,174,816 | 7.4% | 3.0% |
| IMNM | -$523,521,229,276 | 10.7% | 3.0% |
| MU | -$16,932 | 15.1% | 3.0% |

**It is not the classic terminal-value denominator flip:** `wacc <= terminal_growth_rate` on
**zero** tickers. So the cause is upstream of the terminal value — most likely forecast free cash
flows that are negative and compounding, with no guard on the result.

MU is the worked example that surfaced this. Its report base fair value came back at $80 against a
$940.76 price (0.09x), and the mechanical DCF underneath reads **-$16,673/share** on the base
scenario. NVDA in the same run returned a healthy $401.62, so the engine is not globally broken —
it fails on a large minority of tickers and says nothing.

### Root cause found 2026-08-19: the revenue forecast never fades

Not the terminal value — that is the symptom. `extend_growth_years`
(`dcf/forecaster.py:421`) carries **year 2's growth rate flat through year 10**, and its own
docstring says so: *"Y3-Y10 carry forward Y2's revenue growth rate (no fade to terminal growth)."*
This is a deliberate, documented design choice, not broken code.

For MU that means 103.34% revenue growth compounded for eight straight years:

| Year | Forecast revenue |
|---|---|
| 1 | $110bn |
| 5 | $1.9tn |
| 10 | **$65tn** — larger than world GDP |

Costs sum to 94.8% of revenue and capex is 40.1%, so FCFF is negative and scales with the
exploding revenue: -$55bn in year 2 to **-$16tn** by year 10. The terminal value then capitalises
that final figure into perpetuity.

**It breaks in both directions.** MU is capex-heavy, so runaway growth drives value negative.
NVDA has the same runaway growth with high margins and light capex, so it drives value *up*: a
direct run on 2026-08-19 returns **$2,883/share against a $219.74 price (13x)**, where the
2026-08-01 batch had it at $401.62. A sign check catches only the negative tail. Universe-wide,
19.0% of positive DCF values already exceed 2x price and 10% exceed 4.11x.

### Done 2026-08-19: the negative tail now fails honestly

`dcf/model.py` raises when terminal-year FCFF is <= 0, with a message naming
`extend_growth_years` as the likely cause. `scripts/compute_dcf_batch.py` already catches any
exception and writes `status='error'` with the message, so those 567 tickers change from a silent
wrong number to an explicit failure. This is the plan's step 3, and it is a strict improvement —
but it makes the DCF *honest*, not *useful*.

### RESOLVED — the fade shipped at `733b038`

This section is kept for the reasoning, but the decision it describes was taken and implemented on
2026-08-19. `extend_growth_years` now fades Y3-Y10 linearly from Y2's growth to `terminal_growth`,
with Y2 itself capped at `MAX_FADE_START_GROWTH = 0.30`, and `_fade_capex_to_da` does the analogous
thing for capex. Overrides re-anchor the fade rather than being overwritten.

### RESOLVED — the 10x upper guard shipped at `1b0c40e`

The fade fixed the negative tail — **0 negative intrinsic values**, down from 567. It did **not**
fix the upper tail, and nothing guards it. Measured 2026-08-19 across the 2,220 tickers currently
marked `status='ok'`, intrinsic value as a multiple of price:

| p10 | p25 | p50 | p75 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|
| 0.12x | 0.37x | 0.75x | 1.39x | 2.86x | 6.01x | 35.47x | **46,418x** |

| Above | Count | Share of `ok` |
|---|---|---|
| 2x | 328 | 14.8% |
| 3x | 215 | 9.7% |
| 5x | 141 | 6.4% |
| 10x | 75 | 3.4% |

Worst offenders, all `status='ok'` and all flowing into the AI Researcher as valid:

| Ticker | Intrinsic value/share | Price | Ratio |
|---|---|---|---|
| GNTX | $1,099,172 | $23.68 | 46,418x |
| D | $904,809 | $68.61 | 13,188x |
| KSPI | $178,834 | $98.09 | 1,823x |
| MUR | $33,434 | $35.18 | 950x |

**The median is healthy at 0.75x — this is a tail problem, not a centring problem.** A guard at
some multiple of price would convert these to explicit failures, exactly as the non-positive guard
did. The threshold is a real decision: 10x reclassifies 75 tickers (3.4%), 5x reclassifies 141
(6.4%), 3x reclassifies 215 (9.7%). Since ~17% of the universe already has no DCF, a tight
threshold pushes the AI Researcher onto its degradation path considerably more often.

**Original reasoning, retained:**

Making the DCF useful means fading the growth rate from year 2 toward terminal growth by year 10,
which is standard practice and is what the docstring flags as absent. **This changes every DCF
the system produces, not only the broken ones** — including tickers whose values look fine today.
It therefore needs a decision, not just a commit:

- every DCF-derived baseline moves, including the AI Researcher's mechanical anchor and the
  reconciliation against the AI DCF
- the fade shape (linear vs exponential) and the horizon are modelling choices worth stating
  explicitly rather than defaulting
- a cap on the year-1/year-2 growth rate is probably needed as well: 194% and 103% are not
  forecasts at any horizon

**Steps.**

1. Find where the sign is lost. Start at `dcf/model.py` `run_dcf_av` and the forecast path in
   `dcf/forecaster.py`; check whether negative forecast FCF is permitted to propagate into the
   terminal value, and whether `net_debt` is being subtracted from an already-negative
   enterprise value.
2. Characterise the 567. Are they concentrated in loss-making companies, negative-FCF companies,
   or a particular sector? A negative DCF for a pre-revenue biotech is arguably honest; -$5.7
   quadrillion never is.
3. Decide the contract: does a company whose DCF is not meaningful get a *failed* status rather
   than a negative number? `status` already exists and is not being used for this.
4. Whatever the fix, **a magnitude guard belongs at the output**: an intrinsic value per share
   outside a sane multiple of price is a computation failure, not a valuation.
5. Re-check the AI Researcher's degradation path once the status contract changes — the valuation
   prompt has a DEGRADATION rule for when DCF sources are unavailable, and more tickers should
   start taking it.

**Note for whoever picks this up:** `scripts/research_regression.py` now gates on fair value
landing within 0.15x-5.0x of price, so **MU currently fails the regression suite** for this
reason. That is intended — it is the check doing its job — but it means the suite is red until
this is addressed, and the failure should not be mistaken for a cycle-awareness regression.

---

## 2. Are report fair values systematically below market?  [x] CLOSED — NOT SUPPORTED

**Priority: low until measured.** Recorded because it was raised, and because the measurement
that would settle it does not exist yet.

The observation: 4 of the 5 regression tickers came back with a base fair value well under the
market price — MU 0.09x, FANG 0.20x, NVDA 0.43x, KO 0.53x, UPS 0.97x.

**The wider data does not support the hypothesis.** Across 2,615 tickers with both a DCF and a
price, the *positive* mechanical DCF values distribute as:

| p10 | p25 | p50 | p75 | p90 |
|---|---|---|---|---|
| 0.14x | 0.42x | **0.81x** | 1.56x | 4.11x |

The median sits at 0.81x with wide dispersion in both directions (31.6% below 0.5x, 19.0% above
2.0x). NVDA at 0.43x and KO at 0.53x land around the 25th percentile — unremarkable. A five-ticker
sample is far too small to establish a systematic bias, and the underlying engine is not centred
low.

This entry exists mainly to record that the claim was checked and **not** supported, so it is not
re-raised from the same five observations.

### Closed 2026-08-20 with report-level data

The entry above asked for a *report-level* test rather than a DCF-level one, deferred until item 1
was fixed. Item 1 is now fixed (0 negative DCFs) and the 2026-08-19 regression run supplied the
measurement as a by-product — no additional spend:

| Ticker | Before | After | |
|---|---|---|---|
| UPS | 0.97x | **1.00x** | |
| FANG | 0.20x | **1.15x** | capex fade (`a7b4aba`) |
| KO | 0.53x | **0.62x** | |
| NVDA | 0.43x | **0.46x** | |
| MU | 0.09x | **0.04x** | genuine cyclical peak, see above |

Four of five now sit between 0.46x and 1.15x — median moved ~0.43x -> 0.62x, and the cluster is
centred near 1.0x rather than below it. FANG's 0.20x -> 1.15x is the capex fade working on exactly
the case that motivated it.

**The hypothesis is not supported at report level either.** The one remaining low outlier is MU,
and that is a company at 12.2x its median earnings where a low through-cycle valuation is the
correct answer, not a bias. n=5 is still small, but it points the same way as the 2,615-ticker
DCF-level distribution, and there is no longer a reason to spend on a wider run for this question.

**Note the sample is not neutral:** these five tickers were chosen for cycle-position coverage,
which deliberately over-weights cyclicals. If this is ever revisited, draw a random sample.

---

## Reading the post-recompute diffs

Recorded 2026-08-19, before the numbers existed, so the outcome is falsifiable rather than
rationalised afterwards.

`debt_to_ebitda` and `ebitda_ev_yield` feed `historic_fundamentals/ml_comps_model.py` and the
factor set in `scripts/run_walkforward.py`. **Those models were fitted and validated on the
corrupted values**, so every dependent result will move. A moved result is ambiguous by
construction: it can mean the fix broke something, or that the previous number was never real.
Neither reading is the default.

Expected direction, stated in advance:

| Metric | Before | Expected after |
|---|---|---|
| `debt_to_ebitda` median | 0.255x | rises ~6x, toward ~1.5x |
| `ev_ebitda` median | 11.03 | rises — EV gains the missing debt |
| `ebitda_ev_yield` median | 7.63% | falls, being the reciprocal |
| Negative DCFs | 567 (21.4%) | drops sharply; the remainder fail explicitly |

The stated prediction for the ML comps diff is that **EV/EBITDA calibration improves**, since it
is the model whose input was corrupted and the one already tracked as a persistent "stable
near-miss". If it does not improve, the near-miss has another cause — also worth knowing.

When a result moves unexpectedly, the first question is "which of these two numbers was computed
from correct inputs?", not "did this get better or worse?". A baseline fitted on corrupted inputs
needs refitting before it can be compared at all; comparing a fresh measurement against a stale
baseline measures the defect, not the change.

Backup of the pre-recompute database: `~/fin_import2_artifacts/hf_backup_pre_recompute_20260819.duckdb`
(910M), with the baseline metrics in `~/fin_import2_artifacts/baseline_snapshot.json`. Moved out of
`/tmp` before the 2026-08-19 reboot so it would survive; it is not recreatable.
