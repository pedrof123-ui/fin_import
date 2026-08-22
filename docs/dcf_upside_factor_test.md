# DCF-Implied Upside — Factor Test

Tested 2026-08-21/22. **Verdict: REJECTED at the bound that was live at the time.** Sits alongside
`canslim_factors_test.md`, `fibonacci_factors_test.md` and `greenblatt_factors_test.md` — the
other candidates this repo measured and turned down.

Full process record: `archive/PLAN_DCF_ACCURACY.md`.

## What was tested — and what was not

The factor is `dcf_upside = intrinsic_value_per_share / price - 1`, evaluated at each month-end
against the most recent point-in-time DCF. The test is **Spearman rank IC against forward 12-month
return, computed cross-sectionally within each month**, summarised across 167 months.

Plainly: *within one month, if you rank every investable stock by how undervalued the DCF says it
is, does that ranking match their ranking by return over the next year?*

**Not tested, and worth stating because the distinction is easy to lose:**

- **Whether any fair value is numerically right.** There is no ground truth for intrinsic value.
  A DCF systematically 30% too low for every company scores perfectly here, because a constant
  bias cancels in a cross-sectional rank. This is unmeasurable, not merely unmeasured.
- **Single-name usefulness** — how the AI Researcher actually consumes the DCF.
- **The shipped model.** This is the *mechanical* DCF. Production adds an analyst-estimate layer
  worth a median 29% of intrinsic value, and no historical reconstruction can reach it
  (`earnings_estimates` only begins 2026-05-10).
- **Horizons beyond one year.** See "Known weakness" below.

## Panel

Reconstructed point-in-time via `scripts/reconstruct_dcf_panel.py`: 60 quarterly as-of dates
2010-2024, **75,280 ticker-dates, 61,289 ok valuations (81.4%)** — matching production's 81.4%.
Intrinsic value recomputed quarterly (when statement inputs change), carried forward against each
month's price to yield a monthly factor at quarterly compute cost.

Point-in-time correctness is assertion-validated (`tests/test_dcf_as_of.py`), not eyeballed, and
verified non-vacuous by a negative control: feeding the unfiltered live loader to the same
assertion fails it.

Success rate by year is flat 77-85% with no early-year decay (2010 at 82.8%, on the panel
average) — the check that mattered, since thin early coverage would have meant the result was
driven by which companies survived the filter in early folds. The 2020-21 dip to ~77% is
composition, verified not assumed: insufficient-quarterly-history failures run 15.3% there vs
5.1% elsewhere, the IPO/SPAC cohort crossing $1B without eight quarters of filings.

## 1. Standalone rank IC vs ret_1y — indistinguishable from zero

| factor | mean IC | ICIR (NW) | hit rate | t |
|---|---|---|---|---|
| **dcf_upside** | **0.0157** | **0.56** | **52.7%** | **1.51** |
| fcf_yield | 0.0871 | 4.06 | 78.1% | 11.28 |
| roic | 0.0513 | 3.77 | 75.7% | 8.99 |
| earnings_yield | 0.0498 | 2.20 | 69.2% | 5.89 |
| ebitda_ev_yield | 0.0489 | 1.64 | 64.5% | 4.70 |

## 2. Incremental IC — the unique component is negatively predictive

Cross-sectional rank correlation with existing value factors: 0.43 (`earnings_yield`), 0.46
(`ebitda_ev_yield`), 0.32 (`fcf_yield`), 0.10 (`roic`). Residualised on the first three:

| | mean IC | ICIR (NW) | hit rate | t |
|---|---|---|---|---|
| dcf_upside | 0.0157 | 0.56 | 52.7% | 1.51 |
| **dcf_upside_resid** | **-0.0164** | **-0.75** | **44.3%** | **-1.95** |

**Whatever the DCF knows that `earnings_yield` and `ebitda_ev_yield` do not was actively wrong.**
This is the finding that matters — a factor 0.45-correlated with one already in the composite can
post a respectable standalone IC and add nothing.

## 3. Quintiles — non-monotonic, and the "cheapest" bucket is worst

Q1 (highest upside) 0.1410, Q2 0.1506, Q3 0.1585, Q4 0.1538, Q5 0.1527. Mean Q1-Q5 spread
-0.0117, positive in 45.5% of months. The mild positive IC comes from the middle of the
distribution, not the extremes.

**A pooled table by valuation bucket appears to show the opposite and is not evidence.** Pooling
across months confounds the factor with time: periods with many high-upside stocks are post-crash
periods with high forward returns. The per-month cross-sectional result is the valid one, which is
why the gauntlet computes IC per month.

## 4. Fold win rate

8/15 annual folds positive (53%) standalone; 6/15 (40%) residualised.

## 5. The guard is the fix — 10x -> 2.5x

The non-monotonic quintile pattern says extreme DCF outputs are where the model breaks. Trimming
them rescues the factor:

| `MAX_INTRINSIC_TO_PRICE` | mean IC | ICIR (NW) | t | rows kept |
|---|---|---|---|---|
| 10.0 (was) | 0.0157 | 0.56 | 1.51 | 99.6% |
| 3.0 | 0.0368 | 1.47 | 4.07 | 82.8% |
| **2.5 (adopted)** | **0.0441** | **1.81** | **4.97** | **78.3%** |
| 2.0 | 0.0451 | 1.92 | 5.20 | 71.8% |

That sweep is in-sample selection, so it was validated out-of-sample
(`scripts/test_dcf_guard_walkforward.py`, 5 train years / 1 test year):

- **Adaptive** (threshold chosen on train, scored on the unseen next year): beats 10x in **8/10
  folds**, selection **stable** — 2 distinct values across 10 folds, converging on 1.5.
- **Fixed 2.0x vs 10x**: wins **12/15 years**, mean IC delta +0.0285, and **stronger in the recent
  half** (7/8 vs 5/7 early) — the opposite of the single-regime artifact that killed the CANSLIM
  regime factors. The three losing years are all years when the baseline IC was already strongly
  positive: tightening trades a little upside in good years for a lot in bad ones.

2.5 was adopted as the **loosest bound the evidence supports** (the walk-forward's own choice was
tighter), maximising coverage without leaving the validated range. Cost: 232 of 2,145 ok tickers
became explicit failures; universe with no mechanical DCF 19.4% -> 28.1%. Production rebuild
landed at **1,912 ok**, against 1,913 predicted.

**A second constant was needed.** Applying 2.5 globally was a regression for the AI DCF, which
runs bear/base/bull through the same engine: bull-scenario loss tripled (2/25 -> 7/25), truncating
the presented range asymmetrically and biasing it downward. `MAX_INTRINSIC_TO_PRICE_OVERRIDE = 10.0`
now applies when the *caller* supplied the per-year forecast. Two thresholds because there are two
questions: *is this number useful for ranking?* and *is this number absurd?*

## 6. Below $1B the factor works — and that corrects a claim made mid-test

A second panel over $300M-1B (21,969 ticker-dates, 1,575 tickers, 72.5% completion):

| bound | mean IC | ICIR (NW) | hit | Q1-Q5 spread | folds |
|---|---|---|---|---|---|
| 10.0 | 0.0615 | 3.13 | 73.1% | **+0.0465** | 12/15 |
| 2.5 | 0.0672 | 2.98 | 70.7% | +0.0494 | 10/15 |
| 2.0 | 0.0753 | 3.10 | 70.1% | +0.0533 | 10/15 |

**The factor was never rejected in small caps** — even untightened it posts ICIR-NW 3.13 and a
positive quintile spread, against 0.56 and a *negative* spread for >=$1B.

Small caps had been excluded earlier in this work on the grounds they would "degrade panel
quality", citing DCF completion rates (73.5% vs 80.5%). **That conflated two independent things:
completion is coverage, not accuracy.** A ticker-date "succeeds" when the engine returns a number
instead of raising; it says nothing about whether the number was right. Small caps complete less
often *and* rank better.

**Trust the small-cap result less, not more.** The plan pre-committed to the rule that a pass on a
survivorship-flattered panel should be blamed on the bias first, and small caps are where that
bias is worst: all 1,575 tickers still exist today, and the missing ones are disproportionately
cheap-looking companies that went to zero — exactly the population that would sit in the
high-upside bucket dragging its returns down. **The large-cap rejection is the more trustworthy
finding, because a bias running in the factor's favour cannot manufacture a failure.**

## Horizon — tested 2026-08-22, objection answered

A DCF is a claim about decades, and the standard premise is that price converges to intrinsic
value over three to five years, not one. Judging it on 1-year returns risked measuring "does the
market close this gap within twelve months" rather than "is the valuation right". Re-run at four
horizons (`scripts/test_dcf_horizon.py`, panel rebuilt under current constants):

```
mean IC            ret_1y   ret_2y   ret_3y   ret_5y
dcf_upside         0.0368   0.0551   0.0707   0.0776
dcf_upside RESID   0.0037   0.0053   0.0077   0.0201
earnings_yield     0.0445   0.0700   0.0838   0.0874
fcf_yield          0.0782   0.1121   0.1444   0.1569

residual folds       9/15     8/15     9/15     9/15
```

**The verdict softens but stands.** The DCF does carry more information at longer horizons — but
so does every value factor, so a DCF rising with horizon is not evidence about DCFs. What matters
is the incremental contribution over the factors already in use, and at 5y that is **0.0201
against `fcf_yield`'s 0.1569 standalone**, roughly an eighth, with **no improvement in fold
consistency at any horizon** (flat 9/15).

**Long-horizon t-stats here are not usable and were pre-declared so.** `fcf_yield` at 5y posts a
hit rate of **1.0000** with t = 27.7 — a 100% hit rate across 141 overlapping months means about
three independent observations. Fold win rate was fixed in advance as the metric to lead on for
exactly this reason.

**One result changed: the negative incremental IC was a 10x-bound artifact.** At 1y it was -0.0164
on the 10x panel and is **+0.0037** on the 2.5x panel. The guard change fixed it — confirmed by a
test not designed to check it. So "adds nothing beyond existing value factors" stands; "is
actively wrong beyond them" does not.

**A guard re-derived at 5y was considered and declined**: a threshold fitted on 5-year overlapping
returns rests on ~3 independent observations, against ~15 independent years for the 1y fit that
survived walk-forward. See `features/dcf/PLAN_DCF_FOLLOWUP.md` Phase 1.

## Terminal growth — resolved en route

`archive/DCF_VISION.md` specified terminal growth as the median of historical annual revenue
growth. **That spec is unimplementable.** Across 1,831 tickers holding both a WACC and >=5 annual
growth observations: median historical revenue growth is 9.1% against a median WACC of 9.66%, so
**45.8% would have g >= WACC** — Gordon Growth breaks entirely — and another 6.7% land within 1pp
below where the terminal value explodes. **52.5% of the universe would produce a broken or absurd
terminal value**, and 80.8% of companies exceed nominal GDP, impossible as perpetual growth.

So `_default_terminal_growth` ignoring its argument is the correct rejection of a bad spec, not
unfinished work. A bounded variant — `min(median historical revenue growth, 3%)` floored at 0 —
was built and A/B'd with both panels rebuilt under identical constants: 89.8% of intrinsic values
unchanged, 10.0% lowered, no coverage cost, and **mean IC 0.0413 both ways, delta +0.00003**
against a 0.005 threshold committed before the run. Rejected: it buys nothing measurable, adds a
per-company parameter, and capping fixes the *arithmetic* of the spec's premise without fixing the
premise — a decade of revenue history is not evidence about growth in perpetuity.

## Method lessons (these outlast the result)

1. **A reconstructed panel bakes in every `dcf/model.py` constant live at build time**, not just
   the rule under test. Comparing a panel built at `MAX_INTRINSIC_TO_PRICE=10` against one built
   at 2.5 produced an 18.8pp "coverage collapse" that was nearly reported as a finding about
   terminal growth. **The tell: identical intrinsic values on both sides of an ok/error flip.**
   Rebuild the baseline under current constants.
2. **Post-hoc filtering flatters.** The rebuilt flat panel at 2.5x gives mean IC 0.0413; filtering
   the 10x panel down to 2.5x gave 0.0441. Filtering removes rows without letting the growth fade
   respond, since terminal growth feeds `extend_growth_years` as well as the terminal value.
3. **Report dispersion alongside every median.** The beta fix that preceded this work moved 40% of
   its group by >25% while showing a median change of +0.02% — a symmetric re-dispersion and a
   no-op are indistinguishable at the median.
4. **Completion rate is not accuracy.** Stated twice here because it produced a wrong
   recommendation once already.

## Reproduce

```bash
uv run scripts/reconstruct_dcf_panel.py --workers 6          # ~85 min, resumable
uv run scripts/test_dcf_upside_factor.py
uv run scripts/test_dcf_guard_walkforward.py
```
