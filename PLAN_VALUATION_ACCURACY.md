# Valuation Engine — Accuracy Improvements

Created 2026-08-19. **Status: findings recorded, no work started.**

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

Backup of the pre-recompute database: `/tmp/hf_backup_pre_recompute.duckdb` (910M), with the
baseline metrics in `/tmp/baseline_snapshot.json`.
