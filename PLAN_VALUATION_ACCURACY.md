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

## Open: 2 tests still failing after the recompute (was 3; 585 passed, 2 failed, 3 skipped)

Confirmed to pre-date today's sector-join fix (stash-and-rerun: the same 3 failed without it). All
three are fallout from the universe recompute, not from today's changes.

1. `test_cycle_data.py::test_leverage_is_not_read_from_the_broken_column` — **FIXED**
   Asserted `q.leverage > stored * 3`, where `stored` is `pe_stats.debt_to_ebitda`. It was written
   when that column was the *broken* current-portion-only figure, so a correct computation had to
   be several times larger. The recompute fixed the column: CLF went 0.53 -> 12.38 (verified
   against the pre-recompute backup), and `assess_trough_quality` independently computes exactly
   12.384244372990354. The two agreeing is the *correct* outcome — the test failed precisely
   because the defect it was pinned against is gone. Rewritten to pin against the historical
   broken constant (0.5299539170506913) rather than the live column, since a test must not use a
   live column as its own reference. `tests/test_cycle_data.py`: 66 passed.

2-3. `test_research_ai_dcf_integration.py::test_run_research_agent_with_ai_dcf_{success,failure_degrades_cleanly}`
   Both fail on an unexpected finding: `cycle_position is TROUGH but the cycle block computed MID
   - the Chief overrode a deterministic verdict`. The fixtures pin TROUGH while the cycle block,
   reading recomputed data, now returns MID. Not yet diagnosed — needs a decision on whether the
   fixture or the cycle block is wrong.

Item 1 is fixed. Items 2-3 are still red and still need the fixture-vs-cycle-block decision.

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

## 1. The mechanical DCF is driven by a non-fading revenue forecast  [~] Guard shipped, fade is an open decision

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

### OPEN DECISION: introduce a growth fade

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

## 2. Are report fair values systematically below market?  [ ]  NOT ESTABLISHED

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
re-raised from the same five observations. If it is worth pursuing, the honest test is at report
level rather than DCF level — the reported fair value is a blend of mechanical DCF, AI DCF and
multiples, and only the first is measured above. That needs a run across a few dozen tickers,
which costs real money, and should wait until item 1 is fixed, since 21.7% of the inputs are
currently negative and would poison any such measurement.

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
