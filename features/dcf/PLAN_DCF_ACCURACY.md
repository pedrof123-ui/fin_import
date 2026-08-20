# DCF Accuracy — Measurement Plan

Created 2026-08-20. **Status: not started. Written to be decided on, not executed yet.**

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

---

## Phase 0 — The blocker: there is no history  [ ]

`dcf_results` is a **single-snapshot table**. Every row shares one `computed_at`, and each rebuild
overwrites it. Verified 2026-08-20: `MIN(computed_at) = MAX(computed_at)`, one distinct date. The
snapshot was overwritten three times on 2026-08-20 alone.

**So DCF accuracy cannot be backtested today at all, and every future rebuild destroys more
evidence.** This is the first thing to fix and it is nearly free.

**Step 0.1 — Retain snapshots.** Add `dcf_results_history` (or make `dcf_results` append-only with
a snapshot date) and write to it on every batch run. Do this **regardless of which measurement
path is chosen below** — the cost is trivial and skipping it guarantees this same conversation in
a year with no more data than today.

---

## The measurement: two paths, agreed 2026-08-20 to do **both**

### Phase 1 — Accumulate forward  [ ]

Snapshot each monthly rebuild. Nearly free, rides the existing pipeline. A usable read is 2-3
years out, so this is the reliable answer, not the fast one.

### Phase 2 — Reconstruct backward  [ ]

Recompute DCFs as-of historical dates from `monthly_pe`, which holds point-in-time financials.
Answers the question now rather than in 2029. This is where all the cost and all the risk are.

**Recommended sequencing — do NOT start with the full reconstruction:**

**2.1 Scope it.** A full monthly panel is infeasible: the DCF runs ~0.4s/ticker (1,022s for 2,661
tickers), so 2,661 tickers x ~420 months ≈ **124 days of compute**. Annual as-of dates over the
investable universe (~1,900 tickers after filters) for 2010-2024 is 15 x 1,900 x 0.4s ≈ **3.2
hours** — an overnight job. Start there.

**2.2 Pilot point-in-time correctness on one or two years before spending hours.** This is the
whole risk of the exercise. The DCF reads `pe_stats` and the AV financials, which are **current**
snapshots, not as-of views. A reconstruction that lets the forecaster see data published after the
as-of date produces a look-ahead-biased result that will look excellent and mean nothing.
`run_backtest.py` already has `feature_available_date` machinery for exactly this problem — reuse
it rather than inventing a second convention. **Validate by asserting no input carries a
publication date after the as-of date**, not by eyeballing whether the numbers look sensible.

**2.3 Only then run the full reconstruction.**

---

## Phase 3 — The actual test  [ ]

Treat **DCF-implied upside** (`intrinsic_value / price - 1`) as a factor and run it through the
same gauntlet every other candidate faces: rank IC, ICIR with Newey-West, quintile spread, and
fold win rate across annual walk-forward folds.

Using the established bar matters more than the specific metric — it makes the answer directly
comparable to the factors that were rejected, and it removes the temptation to invent a bespoke
measure that happens to flatter the DCF.

**State the expected direction before running.** Every prediction in the 2026-08-19/20 work was
committed in advance, which is the only reason results like "EV/EBITDA improves while the other
three multiples do not" were readable as evidence rather than rationalised afterwards.

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

---

## Open question inherited from `archive/DCF_VISION.md`  [ ]

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
