# AI Researcher — Industry Cycle Awareness

Created 2026-08-17. **Status: Phases 0-8 complete (7 dropped), Phase 6 defect fixed. Next: Phase 9.**

## Resume here

Next action: **Phase 8 — QC and regression.** Part of it already landed in Phase 5: the
two-directional `cycle_position` check is live in `_validate_report`, and it gates the harness.
What remains:

- Extend `scripts/research_regression.py` with one known cyclical at a trough and one at a peak
  (NUE or CLF, and MU or UAL), asserting the section renders with the expected polarity. Today
  all three harness tickers are NOT_CYCLICAL, so no run has ever exercised a rendered callout.
- The **output-truncation check**, now more pressing than when this plan was written: the Chief's
  input grew by ten scored conditions, a TROUGH QUALITY block and the cycle-earnings-power block,
  and a TROUGH/OPPORTUNITY narrative is the longest output case in the feature. Generate that
  worst case and confirm the JSON completes well inside `max_tokens=32000`. Truncation here is
  silent and surfaces as a malformed report rather than an error.
- Full-universe fire-rate report confirming finding 3's 40.5% false-positive rate is gone.

Phase 7 is **dropped** by agreement — lowest value in the plan, duplicates what the cycle block
already says, in a section the Chief does not use for the rating. Go 6 -> 8 -> 9.

Also open, and bigger than this plan: **`pe_stats.debt_to_ebitda` is wrong universe-wide** and the
same root cause understates enterprise value. See the end of Phase 4. Not fixed, deliberately.

Settled, do not relitigate: F/GM false negatives **accepted 2026-08-18** (8/10 recall, zero false
positives). Rubric conditions are scored in Python, not by the model — see the Phase 3 deviation
note for why.

Two traps this plan has now hit three times, worth stating as a rule: **a condition implied by
another condition is not evidence** (cond1/cond4 at 99.7%, the mirrored "P/E undefined" clause at
45.8%, "any forward improvement" at 73.9%). Any new condition added in Phase 4 must be checked for
pairwise co-firing before it is trusted — `scripts/cycle_position_calibration.py` prints the worst
pairs for exactly this reason.

Also carried: EPS ratios and growth rates need sign guards, because cyclicals at a trough
routinely have negative numerators *and* denominators. Phase 2 fixed two such cases.

**This is not just plan work — it fixes a live production defect.** The current peak-earnings
rubric fires on **48.0% of the universe** (1,088 of 2,267 tickers with usable data). Reports
generated today carry spurious "Peak-Earnings Trap Alert" warnings on AAPL, MSFT, KO, PG and
COST. There is no cheap partial fix: removing the degenerate condition 4 only drops the rate to
29.5%, and AAPL still trips on conditions 1 and 3 alone. Measured 2026-08-17. The gate is the
fix, because the correct answer for AAPL is "not a cyclical, do not run this rubric at all".

Decisions already taken (do not relitigate): 7-year detection window, `MID` renders no
standalone section, timing budget raised to 900s. See "Decisions taken" near the end.

Verification baseline: `uv run python scripts/research_regression.py` passes every substantive
check on NVDA/UPS/KO as of 2026-08-17 (committed in `fce9f91`). Run it before and after
behavioural changes so diffs are attributable. It costs ~$1.50 and ~20 minutes per run.

Flags to carry forward:
- Any new `_validate_report` check that can fire on a healthy ticker **fails the regression
  suite**, which gates on `qc_findings == []`. Keep the Phase 8 check narrow.
- The Valuation Analyst is deliberately price-blind (`api/valuation_data.py:266-270`). Phase 6
  must hand it a price-free subset — `current_pe` and `normalized_pe_5y` both embed today's
  price.
- Phase 3 must repair condition 4 before mirroring it; it is 99.7% redundant with condition 1.
- `chief_analyst_core` has a documented silent-JSON-truncation history tied to this exact field
  (`api/research_router.py:2295-2298`). See the Open question.

## Problem

The AI Researcher models cycle position **only as downside risk**. There is a peak-earnings
trap rubric but no trough counterpart, so the classic cyclical profit opportunity — depressed
earnings making the P/E look optically expensive at the bottom of the cycle — is structurally
invisible to it.

Four findings from the review (all verified against the live code and `data/` DuckDBs):

**1. The trough side does not exist.** Repo-wide search for `trough`, `depressed`, `mid-cycle`,
`under-earning`, `MIN(ttm_eps)`, `normalized earnings power`: zero hits in
`api/research_router.py` and zero in every `api/prompts/research_*.md`. The rubric at
`research_router.py:886-896` is one-directional by construction — condition 4 fires only when
current P/E is *below* normalized P/E, condition 5 only when margin is *above* the 5yr median.
The output field is named `peak_earnings_analysis`.

**2. `ttm_eps > 0` deletes the trough.** The 5-year history query
(`research_router.py:829-841`) excludes loss periods — exactly the regime where cycle position
matters. Measured distortion of the mid-cycle EPS baseline:

| Ticker | True 5yr avg EPS | What the AI sees | Months dropped |
|---|---|---|---|
| MU | $4.74 | $7.57 | 15/60 |
| AAL | -$0.53 | $1.23 | 22/60 |
| CLF | $1.00 | $2.80 | 21/60 |
| OXY | $4.99 | $5.95 | 7/60 |

For AAL the sign of mid-cycle earnings flips. The query also computes `MAX` but no `MIN`, so
there is no trough reference point even in principle.

**3. The existing peak rubric misfires on ~40% of the universe.** Conditions 1 and 4 are
near-duplicates: for any company whose EPS grows, current EPS sits near its own 5yr max *and*
`current_pe < normalized_pe_5y` (because `normalized_pe_5y = price / avg_5yr_EPS`, so a rising
EPS makes today's P/E mechanically lower than the CAPE-style one). Measured across the universe
(n=1596 with usable data):

- cond 1 (near 5yr-max EPS): 649 (40.7%)
- cond 4 (P/E below normalized): 1045 (65.5%)
- **both, which alone trips the "TWO or more" threshold: 647 (40.5%)**

647 of the 649 cond-1 tickers also fire cond 4 — it is not an independent signal. A dry run of
the current rubric flags AAPL, MSFT, KO, PG and COST as peak-earnings traps. This is a
pre-existing bug, independent of the trough work, and it must be fixed or the symmetric version
inherits it.

**4. The analysis is advisory only.** The block goes to exactly one consumer,
`chief_analyst_core` (`research_router.py:2281`). It is *not* in `valuation_analyst_context`
(`research_router.py:2222-2233`) — the agent that actually sets `fair_value_low/base/high`. The
Chief's rating is derived mechanically from `price_vs_fair_value_high_pct`. So a detected trap
changes prose and nothing else: no rating gate, no fair-value adjustment, no QC check.

Also: `industry_outlook` (`api/prompts/research_competitive.md:44-53`) is framed entirely around
TAM, drivers, regulation, penetration and share — a *secular growth* frame with zero cycle
language. Sector aggregates (`sector_stats`) never enter the report path; `get_sector_stats` /
`get_sector_history` are never imported by `research_router.py`.

## Approach

Fix the **input**, not the output. Rather than bolting a cycle override onto the rating, make
mid-cycle earnings power visible to the agent that sets fair value, so the existing mechanical
rating arithmetic does the right thing on its own.

Two guardrails shape the design:

- **The Valuation Analyst is deliberately price-blind** (`api/valuation_data.py:266-270`: it
  uses `pe_rolling_5yr_median` rather than `normalized_pe_5y` precisely because the latter
  embeds today's price). The cycle block cannot be handed to it as-is — `current_pe` and
  `normalized_pe_5y` both leak price. It gets a price-free subset only.
- **A trough signal is not automatically an opportunity.** Distinguishing a cyclical trough
  (mean-reverting) from secular decline (value trap) is the core of the feature. Getting this
  wrong tells the user to buy a melting ice cube.

## Non-goals

- No change to the mechanical rating rules in `research_chief_core.md:41-52`. Cycle position
  must not override the rating directly.
- No new DuckDB columns. Every ingredient already exists in `pe_stats` and `monthly_pe`
  (verified: `current_ttm_eps`, `forward_12m_eps`, `earn_growth_1yr`, `earn_cagr_3yr/5yr`,
  `rev_growth_1yr`, `rev_cagr_5yr`, `current_operating_margin`, `operating_margin_5y_median`,
  `debt_to_ebitda`).
- No cache migration. `research_cache` stores rendered markdown with a 24h TTL (32 rows), never
  reconstructs the Pydantic model on read, so new fields cannot break it. Nothing to clear.
- No frontend change. `EquityResearchViewer.tsx` renders the markdown blob and references no
  field by name.

---

## Phase 0 — Repair the regression harness  [x] Complete

`scripts/research_regression.py:41` unpacked 5 values from `_run_research_agent`, which returns
a 7-tuple (`research_router.py:2388-2391`), so the harness died with `ValueError: too many
values to unpack` on every ticker. Pre-existing breakage, not caused by this work, but nothing
downstream could be validated until it ran.

**Done 2026-08-17:**

- Fixed the unpack. Only `:41` was affected — `:107` already used `report, *_`. The fix
  star-unpacks the tail (`..., market_share_md, *_`) so future growth of the return tuple cannot
  break it silently a third time; this matches the idiom already used at `:107`.
- **How long it was dead:** broke in `7ff1be5` (2026-07-31) when `dcf_reconciliation` took the
  return 5 -> 6, then `a75be83` (2026-08-07) took it 6 -> 7. The harness was last touched
  2026-07-20. So it was dead 17 days, and the AI DCF audit trail, LLM tiering, and ML comps
  triangulation all shipped without this end-to-end gate running.
- **Baseline run:** all three tickers generate, and every substantive check passes —
  `target_low <= target_high`, `intrinsic_valuation`, `balance_sheet_analysis`, all four
  valuation tables, fair values populated and ordered, and `qc_findings == []` on all three.
  Degradation check (`ZZZZNOTATICKER`) passes. Full log kept for diff attribution.
- **Timing budget raised 180s -> 900s.** The 180s ceiling was written 2026-07-20 with the note
  "verified comfortably under 180s (26-97s)" — ten days before the inline Agentic AI DCF landed.
  That pipeline alone carries a 600s outer timeout because its per-agent budgets legitimately
  reach ~800s, so a report can exceed 180s with nothing wrong. Measured this run: NVDA 401.5s,
  UPS 438.6s, KO 394.3s. 900s clears the legitimate worst case and still catches a true hang.
  Not investigated further as a performance regression — decided in-session.

Residual: the ~400s figure was not attributed across stages (the per-stage timings go to a
logger the script does not configure). If report latency later becomes a concern, the sharper
fix is to measure AI DCF time separately from the rest rather than widen the single ceiling.

## Phase 1 — Cyclicality gate  [x] Complete (2 known false negatives, see below)

Without this the rubric is noise (finding 3). Only companies that actually exhibit cyclical
behaviour should get a cycle-position verdict at all.

Shipped as `api/cycle_data.py` (`classify_cyclicality`), calibrated by
`scripts/cyclicality_calibration.py`, covered by `tests/test_cycle_data.py` (18 tests).
Output: `CYCLICAL` / `NON_CYCLICAL` / `INSUFFICIENT_HISTORY`, data-driven with no sector
whitelist, per CLAUDE.md rule 6.

**What it measures, and why not the metrics this plan originally listed.** The four proposed
inputs (CoV of `ttm_eps`, loss-month fraction, peak-to-trough EPS amplitude, revenue amplitude)
were all built and measured. Every one of them conflates cyclicality with two other things,
and the measurements are worth keeping:

- *Splits corrupt every per-share metric.* `monthly_pe.shares` is transiently wrong around
  stock splits — AAPL reads 56,899M shares in 2020-09 against a true ~17,100M, WMT reads
  24,323M in 2024-01 against ~8,084M — which craters `ttm_eps` for a few months. AAPL's raw
  EPS drawdown over the window reads 0.92, which alone would have flagged it CYCLICAL and
  failed the gate. `ttm_eps * shares` recovers aggregate earnings exactly (the bad share count
  cancels: $58.4B on both sides of AAPL's artifact), and `ttm_revenue` carries no share count
  at all. **Anything downstream that reads `ttm_eps` monthly history is exposed to this** —
  including `eps_5yr_avg`/`eps_5yr_max` in the current peak rubric. Phase 2 must not
  reintroduce it.
- *COVID sits inside the window.* Nearly every company's revenue fell in 2020, so single-
  drawdown measures call **69% of the universe cyclical** — no better than the 48% defect
  being fixed. One V-shaped hole is not a cycle.
- *One-off charges mimic earnings cycles.* MRK's earnings drawdown is 0.98 and JNJ's 0.63,
  above true cyclicals like GM (0.82) and NUE (0.86). Normalizing by peak earnings also
  explodes whenever earnings cross zero, so peer-median drawdown is ~1.5-3.0 in most
  industries and discriminates nothing.

What survives all three is **co-movement with an industry cycle**, which is also the textbook
definition. The gate builds a peer factor from the company's own industry (falling back to
sector below 8 peers with usable history) and measures

    systematic amplitude = |beta to peer factor| x stdev(peer factor)

on year-over-year log revenue growth, with subject and peers demeaned first so the factor
carries the common *cycle* rather than common *growth* — otherwise an industry holding
hyper-growth entrants (autos with TSLA/RIVN) reads as a trend. Idiosyncratic volatility no
longer counts: a biotech with lumpy revenue has high own volatility but near-zero beta.
Threshold `_AMPLITUDE_MIN = 0.10`, calibrated 2026-08-17.

**Calibration result.** The hard requirement — zero false positives on mega-cap compounders —
is met, on the plan's nine and on a wider set of twenty added during calibration:

| Set | Result |
|---|---|
| Gate non-cyclicals (AAPL, MSFT, KO, PG, COST, V, WMT, JNJ, UNH) | 9/9 correct |
| Wider non-cyclicals (PEP, MCD, MA, MRK, TMO, SO, DUK, VZ, ...) | 20/20 correct |
| Gate cyclicals | 8/10 — **F and GM miss** |
| Wider cyclicals (CAT, DE, AA, LUV, CCL, RCL, HAL, SLB, EOG, CF, MOS, DOW, LYB, ...) | 13/15 — FCX and WHR miss |

Full universe (n=2,644): 30.7% `CYCLICAL`, 58.5% `NON_CYCLICAL`, 10.7% `INSUFFICIENT_HISTORY`
(better than the 19% the coverage table predicted). Large caps 23.3% cyclical. Sector profile
is the shape it should be — Energy 82%, Basic Materials 52%, Consumer Cyclical 34%,
Industrials 19%, Technology 19%, Healthcare 14%, Utilities 7%, Consumer Defensive 3%.

**Open: the F/GM false negatives.** This plan pre-committed to correct `CYCLICAL` on all ten,
and autos miss (F 0.057, GM 0.071 against a 0.10 threshold). The cause is real, not a bug: US
auto *revenue* was genuinely stable across 2019-2026 — the COVID dip recovered and price
increases offset volume. Autos are cyclical in *earnings*, via operating leverage. Three
rescues were built and measured, and all three cost more than they buy:

- systematic *margin* amplitude — non-cyclical margin swings (JNJ 0.043, MRK 0.044) sit above
  the autos (F 0.029, GM 0.022); any threshold catching autos drags in half the market
- peer-shared earnings drawdown — fires on 70-76% of the universe, for the zero-crossing
  reason above
- lowering the revenue threshold to 0.06 — catches F but makes V a false positive, breaking
  the requirement that actually matters

Recall failures are the safer failure here: a missed cyclical renders no cycle section, while
a false positive is the AAPL-trap-alert defect this plan exists to remove. **Decision pending:
accept 8/10, or hold Phase 2 until autos are covered.** If autos must be covered, the honest
route is a longer window for the earnings leg (their revenue cycle is visible over 10yr but
not 7), which reopens the survivorship argument settled below.

**Why 7 years.** Five years can sit entirely inside one leg of a cycle — a semiconductor or
housing name reads as a secular grower and the feature switches itself off for exactly the
companies it exists for. Ten years detects cycles better but costs coverage, measured against
`monthly_pe` (2,644 tickers):

| Window | Tickers with near-full history | Coverage |
|---|---|---|
| 5yr | 2,448 | 93% |
| 7yr | 2,134 | 81% |
| 10yr | 1,920 | 73% |

Ten years would push 528 names into `INSUFFICIENT_HISTORY` with no verdict at all. The deciding
factor is the survivorship gap already recorded in the project memory (51% of real S&P 500 exits
since 2016 are missing from these tables): deep cyclicals are the companies that die at the
bottom, so a long window samples disproportionately from cyclicals that *survived*. Calibrating
trough thresholds on survivors teaches "troughs always recover" — the precise wrong lesson for a
feature that recommends buying them. Seven years is the compromise; if coverage proves binding,
add a 5-year fallback tier rather than lengthening the window.

Calibration gate for this phase: on a labelled sample, **zero** false positives on the mega-cap
compounder set (AAPL, MSFT, KO, PG, COST, V, WMT, JNJ, UNH) and correct `CYCLICAL` on
MU, CLF, NUE, F, GM, DAL, UAL, OXY, DVN, AAL. Report the confusion matrix over the full
universe before proceeding.

## Phase 2 — Symmetric, honest cycle data  [x] Complete

`get_peak_earnings_data` is now `get_cycle_position_data` (`api/research_router.py:817`), wired
into the fan-out under the label `cycle_position`. All five specified changes shipped:

- **`AND ttm_eps > 0` dropped**, so loss periods count.
- **`MIN(ttm_eps)` added** and labelled as the trough.
- **`AVG(ttm_eps)` labelled mid-cycle**, with "current EPS as % of mid-cycle" alongside it, plus
  a count of loss months so the LLM can see how much of the window was underwater.
- **`pct_of_peak` guarded** — and the guard had to go further than specified, see below.
- **Phase 1 cyclicality verdict emitted** into the block, with its amplitude, beta, peer group
  and peer count, and an explicit sentence for non-cyclicals: *"Cycle position is NOT a
  meaningful reading for this company."*

**Verification against the finding-2 table.** Dropping the filter reproduces the measured truth
exactly — MU $4.74, AAL -$0.53, CLF $1.00, OXY $4.99, against $7.57 / $1.23 / $2.80 / $5.95 with
the filter on. Regression-tested in `tests/test_cycle_data.py`.

**EPS history is restated on the current share count** (`ttm_eps * shares / median shares over
the last 12 months`). This was not in the phase spec and is load-bearing: the split defect
recorded in Phase 1 puts the artifact month straight into `MIN`, so AAPL's raw 5-year trough EPS
reads **$1.03 against a true ~$5.60** — an 82% phantom earnings collapse on the clearest
non-cyclical in the universe, produced by the very statistic this phase adds. Multiplying by
`shares` cancels the bad count exactly. The restatement also makes the history comparable across
buybacks and issuance, which matters for AAL (share count roughly doubled in the window).

**Two bugs found by measurement, both fixed here.** Neither was in the phase spec; both would
have silently corrupted Phase 3's trough conditions:

1. *Percentage change inverts on a negative base.* CLF's forward EPS improving from -$2.13 to
   -$0.36 computed as **-83.1%** — indistinguishable from a collapse, while the loss is actually
   narrowing by $1.77/share. Pre-existing, and directly under Phase 3's planned trough condition
   "forward EPS well above TTM". The block now states the dollar move and names the direction
   when TTM EPS is negative.
2. *A "% of" reading needs both sides positive, not just the denominator.* The specified guard
   covered `eps_5yr_max <= 0` only, so CLF (current -$2.13 against $1.08 mid-cycle) rendered as
   **"-196% of mid-cycle"** — a number with no interpretation. Now both ratios fall back to
   prose, distinguishing "mid-cycle earnings are negative" (AAL) from "currently loss-making"
   (CLF).

Deliberately **not** changed in this phase, because Phase 3 owns them: the block's
`INTERPRETATION GUIDE` is still the one-sided peak-only rubric, and the `chief_context` section
header still reads `=== PEAK-EARNINGS TRAP SIGNALS ===`. The schema field
`peak_earnings_analysis`, its renderer at `:540`, and `research_chief_core.md:119` are untouched
and belong to Phase 5.

Tests: 25 in `tests/test_cycle_data.py` (7 new for this phase). Full suite 546 passed, 3 skipped
— no regressions. The LLM pipeline itself has not been re-run; `scripts/research_regression.py`
is the gate for that and is worth one run once Phase 3 changes the prompt, since Phase 2 alters
what the Chief reads.

## Phase 3 — Symmetric rubric  [x] Complete

Rubric lives in `api/cycle_data.py` (`evaluate_cycle_position`, thresholds as module constants),
rendered by `get_cycle_position_data`, calibrated by `scripts/cycle_position_calibration.py`.
The `chief_context` header is now `=== CYCLE POSITION (PEAK / TROUGH / MID) ===` and
`api/prompts/research_chief_core.md` carries the symmetric instruction.

**Calibrated fire rates among CYCLICAL names** (plan gate: each side under ~25%):

| Side | Rate | Threshold |
|---|---|---|
| PEAK | 17.3% | 2 of 5 conditions |
| TROUGH | 22.5% | 3 of 5 conditions |
| MID | 60.1% | — |

**Condition 4 repaired.** Current P/E is now compared to `pe_rolling_5yr_median` instead of
`normalized_pe_5y`. Co-firing with condition 1 falls from **99.7% to 26.6%**, and the condition's
own fire rate from 65.5% to 4.8% — it now carries information instead of restating condition 1.

**The threshold asymmetry (2 peak / 3 trough) is measured, not arbitrary.** Trough conditions are
individually far more prevalent because cycles are correlated and cyclicals are depressed
together: 43.8% of cyclicals are loss-making or below half mid-cycle, 38.9% carry a recovery
forecast, 26.3% have margins 5pp under their own median. At 2-of-5 the trough side fires on
**43-46% however tightly the individual thresholds are set**, so the count is the only effective
lever. It reads correctly economically too: at a peak, near-peak EPS plus one corroborator is
enough, while at a trough being depressed is necessary but not sufficient.

**The mirrored rubric reproduced the very bug this phase repairs, and that had to be fixed too.**
Mirroring condition 4 as "multiple optically high **or undefined** on depressed earnings" makes it
automatically true for every loss-maker — and a loss-maker already satisfies the depressed-earnings
condition, so "two or more" was met by the single fact of being loss-making. Measured co-firing
45.8% of cyclicals. Removing the "undefined" clause (loss-making is already condition 1's job)
drops it to 8.7%. Same lesson as finding 3: a condition that is implied by another condition is
not evidence.

A second degenerate mirror caught the same way: "forward EPS above TTM (analysts forecast
recovery)" fires on **73.9%** of cyclicals, because analysts forecast improvement for almost
everything. It now demands a *material* recovery — a loss-maker must be forecast to return to
profit, not merely to lose less — which brings it to 38.9%.

**The two cases the plan flagged:**

- *Negative mid-cycle EPS* (AAL): the EPS-versus-mid-cycle tests are skipped and the block emits
  an explicit NOTE that position rests on the margin and revenue conditions instead.
- *Both sides firing*: resolves to `MID` with a note that the evidence is contradictory, rather
  than picking a winner. Chosen because `MID` renders no standalone callout (Phase 5), so an
  ambiguous case cannot produce a confident wrong claim. **Measured 0 clashes across 813
  cyclicals** at these thresholds — V, which the plan flagged at 2 peak / 2 trough, is now
  `NOT_CYCLICAL` and never reaches the rubric.

**Deviation from the plan, deliberate: the conditions are scored in Python, not by the model.**
The plan had the prompt list the rubric and the Chief count conditions. But a calibrated fire rate
is a claim about arithmetic — if an LLM re-applies five numeric thresholds per report, the measured
17.3%/22.5% describes nothing that actually runs. So the block now emits `CYCLE POSITION: <verdict>`
plus every condition marked `MET` or `no`, and the prompt forbids re-deriving or overriding it.
The Chief narrates the evidence rather than computing it. This makes Phase 8's QC check
(PEAK/TROUGH on a NOT_CYCLICAL ticker) nearly unfireable, which is the right direction.

**Sanity read on named tickers:** MU PEAK (3/5 — EPS at 5yr max, 992% 1yr growth against a
-0.7% 3yr CAGR, margins 43pp over median), CLF/NUE/DVN/LYB TROUGH, UAL/CCL PEAK, DAL/OXY/AAL/CAT/
DE/SLB MID, and all nine mega-cap compounders NOT_CYCLICAL — the 48% misfire is gone at the
rubric level.

Tests: 34 in `tests/test_cycle_data.py` (9 new). Full suite 555 passed, 3 skipped.

## Phase 4 — Trough vs. value trap  [x] Complete

`assess_trough_quality` in `api/cycle_data.py`, rendered as a TROUGH QUALITY block whenever the
position is TROUGH, with the prompt relaxed in step: the Chief may now frame a trough as an
opportunity, but only on an `OPPORTUNITY` verdict.

All three tests must clear, and **UNKNOWN never counts as a pass** — an unestablished
survivability test is not a pass, because the cost of that error is telling someone to buy a
company that cannot fund itself to the recovery. Measured over the 183 TROUGH names:

| Test | Passes | Unknown |
|---|---|---|
| Demand intact — TTM revenue vs. its own 5yr peak, >=90% | 39.9% | 0% |
| Industry-wide — industry margin under its own median, or industry earnings shrinking | 57.4% | 4.4% |
| Survivable — total debt / TTM EBITDA <= 4x at trough earnings | 42.1% | 19.1% |
| **All three -> OPPORTUNITY** | **9.3% (17 of 183)** | |

Pairwise co-passing is 16-24%, so no test is implied by another — the check this plan now runs
by reflex. Sample opportunities: FANG, CHRD, MTDR, NOV, TEX, TPR. CLF is the instructive
negative: 12.4x leverage, revenue 80% of peak, and a steel industry that is *not* depressed
alongside it — three failures, reported as a possible value trap rather than a cheap cyclical.

**`rev_cagr_5yr` was rejected as the demand test.** The plan specified it, but its 5-year window
starts in the depressed 2021 base, so it reads positive for **93.4%** of troughs and discriminates
nothing. TTM revenue against its own 5-year peak asks the same question without the window
artifact: a cyclical margin trough keeps revenue near its highs, a melting ice cube does not.

### `pe_stats.debt_to_ebitda` is wrong across the whole database

The survivability test computes leverage from `short_long_term_debt_total` rather than reading
`pe_stats.debt_to_ebitda`, because that column is broken. `_get_ev_debt_cash`
(`historic_fundamentals/pe.py:464`) builds total debt as
`long_term_debt_noncurrent + short_term_debt + current_long_term_debt`, and treats a NULL
component as zero as long as one component is present. **`long_term_debt_noncurrent` is NULL in
100% of the 193,441 quarterly balance-sheet rows that carry a debt total**, so the column measures
only the *current portion* of debt.

Understatement is a median of **6.1x**. Verified against raw financials:

| Ticker | Stored | True |
|---|---|---|
| T | 0.25x | 3.24x |
| CCL | 0.43x | 3.91x |
| VZ | 1.26x | 4.18x |
| NUE | 0.10x | 1.26x |

Among TROUGH names the true leverage distribution is p50 3.9x / p75 8.8x / p90 21.3x, against the
stored column's p50 of 0.4x — the difference between "no cyclical is over-levered" and "half of
them are".

**This is not confined to this feature and has not been fixed.** The same helper supplies
`total_debt` to the enterprise-value calculation at `pe.py:689`, so `ev`, `ev_ebitda` and
`ebitda_ev_yield` are all understated on the debt side, and those feed `ml_comps_model.py`,
`scripts/run_walkforward.py` factor sets, and the `sector_stats` medians. The code fix is a
one-liner (prefer `short_long_term_debt_total`, fall back to the component sum), but it
invalidates the computed columns until `monthly_pe` is recomputed across the universe, which
reaches the ML comps models and any backtest baseline. **That decision is deliberately left
open** — it is a re-import and possibly a retrain, not a phase step.

Tests: 40 in `tests/test_cycle_data.py` (6 new), including a guard that leverage does not track
the broken column. Full suite 561 passed, 3 skipped.

**One latent bug fixed here, caught by the existing integration tests.** `classify_cyclicality`
and `assess_trough_quality` both `ATTACH` the av database; DuckDB shares a catalog across
connections to the same file, so the second attach raised
`Binder Error: database with name "av" already exists` whenever the research fan-out held
connections open concurrently. Both now use `ATTACH IF NOT EXISTS`. Phases 1-3 shipped with the
single-attach version and passed the regression harness, so this only became reachable in Phase 4.

## Phase 5 — Schema, prompt, rendering  [x] Complete

The fix is user-visible from here: a cyclical trough no longer renders under a "Warning" header.

1. `EquityResearchReport` — added `cycle_position: Optional[Literal["PEAK","TROUGH","MID",
   "NOT_CYCLICAL"]]` and `cycle_position_analysis: Optional[str]`. `peak_earnings_analysis` stays
   on the model, optional, so existing fixtures keep constructing, and the renderer still falls
   back to it so a report generated before the rename renders its callout.
2. `ChiefCoreOutput` — the new pair replaces `peak_earnings_analysis` on the Core half only. A
   test now asserts the two chief schemas share no field, since the merge is a `**` splat and any
   overlap raises at runtime rather than at import.
3. `research_chief_core.md` — `cycle_position` is copied verbatim from the block and must never be
   null when the section states one; `cycle_position_analysis` is populated only for PEAK/TROUGH.
4. `render_to_markdown` — heading and callout branch three ways, not two:

   | Position | Heading | Callout |
   |---|---|---|
   | PEAK | Peak-Earnings Trap Alert | `> **Warning:**` |
   | TROUGH + OPPORTUNITY | Trough-Earnings Opportunity | `> **Opportunity:**` |
   | TROUGH otherwise | Trough Earnings — Possible Value Trap | `> **Caution:**` |
   | MID | *(one line inside Intrinsic Valuation)* | — |
   | NOT_CYCLICAL | *(nothing)* | — |

**The third branch is an addition to this plan's spec,** which predates Phase 4 and branched only
on PEAK vs TROUGH. Rendering a failed-survivability trough as "Trough-Earnings Opportunity" would
invert the meaning of the Phase 4 verdict at the last step — CLF, at 12.4x leverage, would be
presented to a reader as an opportunity. `trough_quality` is passed into the renderer as a
computed argument rather than an LLM-set field, for the same reason the conditions are scored in
Python: the callout label is the difference between "buy this" and "this may be a value trap".

**The silent-failure risk is closed, not just flagged** (done 2026-08-18, pulling part of Phase 8
forward). The callout is gated on `report.cycle_position`, which the *model* fills in, so a Chief
that omitted it would have erased the whole feature from the report with no error and no QC
finding. Both halves are now in place:

- *Defence.* `compute_cycle_position(ticker)` recomputes the verdict deterministically, and
  `render_to_markdown` backfills it when the field is null. A missing field degrades the prose
  rather than deleting the section.
- *Detection.* `_validate_report` reports both a null `cycle_position` and a mismatch against the
  computed verdict.

A mismatch is reported but deliberately **not** overridden. The prose the Chief wrote matches the
position it claimed, so swapping the heading underneath it would pair a trough heading with peak
text — worse than either error alone. Only the null case is backfilled, where there is no
contradicting prose.

**Consequence to expect:** this check gates the regression harness, which asserts
`qc_findings == []`. If the live Chief omits `cycle_position`, the next regression run fails.
That is the intended signal — it fires only on a real defect — but it is the failure to look for
first if the Phase 6 run comes back red. Two existing fixtures in
`tests/test_research_ai_dcf_integration.py` had to start setting the field for the same reason.

Tests: 49 in `tests/test_cycle_data.py` (9 new). Full suite 570 passed, 3 skipped. Not yet
exercised against a live model — the schema change means the Chief must actually populate
`cycle_position`, which only a real generation proves. That is the next regression run.

## Phase 6 — Make it affect the valuation  [x] Complete

The structural fix. Until this landed, a detected cycle position changed prose and nothing else —
it never reached the agent that sets `fair_value_low/base/high`.

`get_cycle_earnings_power(ticker)` produces a **price-free** block, added to the fan-out and to
`valuation_analyst_context`: cyclicality verdict, cycle position, TTM and forward EPS, 5yr
trough / mid-cycle / peak EPS restated on the current share count, and current-vs-5yr-median
operating margin. No `current_pe`, no `normalized_pe_5y`, no price, market cap or multiple
anywhere — the cycle-position block itself can never be handed to this agent, since
`normalized_pe_5y` is literally today's price over average EPS. Five tickers are asserted
clean against a banned-term list in `tests/test_cycle_data.py`.

`api/prompts/research_valuation.md` replaces PEAK-EARNINGS AWARENESS with a symmetric CYCLE
AWARENESS instruction that names the anchor for each position:

| Position | Anchor |
|---|---|
| NOT_CYCLICAL / MID | forward consensus EPS, as before |
| PEAK | mid-cycle EPS — TTM overstates normal earning power |
| TROUGH + OPPORTUNITY | mid-cycle EPS — TTM *and* forward both understate it |
| TROUGH + POSSIBLE_VALUE_TRAP | forward consensus, and say which test failed |

**The trough case carries a trap the plan did not mention.** The plan asks for a symmetric
instruction: anchor on mid-cycle at a trough as at a peak. But normalising a trough that failed
Phase 4's demand, peer-breadth or survivability tests inflates fair value on an impaired
business — the exact mirror of the peak error, applied to a company that may never regain
mid-cycle earnings. The block therefore carries the trough-quality verdict and the prompt gates
normalisation on it. CLF is the worked example: TROUGH, but POSSIBLE_VALUE_TRAP, so the analyst
stays on forward consensus and must say why.

**A latent concurrency bug surfaced here and is fixed.** DuckDB shares one catalog across all
connections to a file, so `ATTACH IF NOT EXISTS` is a check-then-act that races. Phase 6 added a
second concurrent attacher to the fan-out and both tasks began passing the check in the same
instant, with the loser raising `Binder Error: database with name "av" already exists`. Losing
the race is harmless — the winner's attach is what makes `av` resolvable for every connection —
so `_attach_av` swallows exactly that error. The three pre-existing attach pairs in
`research_router.py` were made idempotent at the same time; `api/sector_router.py` has the same
latent pattern and was left alone, being off this code path.

Tests: 59 in `tests/test_cycle_data.py` (8 new). Full suite 580 passed, 3 skipped.

## Phase 7 — Industry cycle framing  [~] Dropped by agreement 2026-08-18

Lowest value of the set; do last or drop if the earlier phases land well. Add a cycle-position
cluster to `industry_outlook` in `api/prompts/research_competitive.md:44-53`, so the industry
section carries a cycle read alongside its secular TAM framing.

## Phase 8 — QC and regression  [x] Code complete, final harness run pending

- **`_validate_report` check** — landed early, in Phase 5. Two-directional: a null
  `cycle_position` when the block computed one, and a mismatch against the computed verdict.
  Deliberately narrow, so it fires only on a real defect.
- **Harness extended** — `scripts/research_regression.py` now runs five tickers. NVDA, UPS and KO
  are all NON_CYCLICAL, so before this **no run had ever exercised a rendered cycle callout**.
  Added MU (PEAK) and FANG (TROUGH that clears the trough-quality tests). Each asserts
  `cycle_position`, that the expected callout heading renders, and that
  `cycle_position_analysis` is populated. Cost rises from ~$1.50/~20min to roughly ~$2.50/~35min.
  The expectation table is checked against the live gate first and reported as *informational* if
  the gate has moved — a changed verdict means the data moved, not that the model erred, and
  should not fail the suite silently as a model bug.
- **Truncation guard** — folded into the same two tickers. `UsageTracker` is aggregate across all
  agents so it cannot isolate the Chief Core call, but the failure mode is fields being cut from
  the end of the Core JSON, so the check asserts `key_highlights`, `financial_performance` and
  `fair_value_base` all survive alongside the longest cycle narrative in the feature.
- **Before/after on the original defect** — `scripts/cycle_defect_before_after.py` replays the
  original rubric against current data and scores the shipped pipeline on the same universe:

  | | Fires | Share |
  |---|---|---|
  | BEFORE — original rubric | 1,523 | 57.6% |
  | AFTER — pipeline reports PEAK | 141 | 5.3% |

  AAPL, MSFT, KO, PG and COST all move from TRAP to NOT_CYCLICAL. After-state across the
  universe: PEAK 5.3%, TROUGH 6.9%, MID 18.5%, NOT_CYCLICAL 69.3%.

  *Honest note on the number:* finding 3 quoted 40.5%, which was specifically the
  conditions-1-and-4 pair that alone trips the "TWO or more" threshold. The replay scores all
  five original conditions and so reads higher at 57.6%. Both measure the same defect from
  different angles; the after-state is what the comparison turns on, and the script says this in
  its own output rather than quietly presenting 57.6% as a reproduction of 40.5%.

**Outstanding:** one run of the extended harness as the final gate. Watch for a `cycle_position`
QC finding — the check gates on `qc_findings == []`, so a Chief that omits the field fails the
suite by design.

## DEFECT — Phase 6's mid-cycle anchor produced absurd fair values  [x] Fixed 2026-08-19

Found by the first extended regression run, which **passed every check while carrying the bug**,
because it asserted only `fair_value_low <= base <= high` and never that the numbers were
plausible:

| Ticker | Price | Base fair value | Base vs price |
|---|---|---|---|
| MU (PEAK) | $823.03 | $23.58 | -97% |
| FANG (TROUGH, OPPORTUNITY) | $202.95 | $37.19 | -82% |

MU's mechanism was unambiguous: mid-cycle EPS $4.72 x **exactly 5.00** = $23.58. The Valuation
Analyst did what Phase 6's prompt told it — "anchor on mid-cycle EPS, not TTM" — and produced a
valuation disconnected from reality. Before Phase 6 it would have anchored on forward consensus
($73.44) and landed in a sane range, so this was a regression, not a pre-existing issue.

**Root cause.** A raw 5-year average EPS is not normal earning power for a business whose earnings
level has structurally shifted. MU's window spans the 2023 memory trough (-$6.04/sh) and the
current AI-driven peak ($44.31/sh); the $4.72 mean describes neither. This is the same
trend-versus-amplitude problem Phase 1 solved *for the gate* by demeaning the peer factor, and it
was never applied to the mid-cycle figure itself.

**Fix: normalise the margin, not the EPS level.**

    normalised EPS = current TTM revenue x the company's own 5yr median NET margin / current shares

Net margin rather than operating margin, because it already carries interest and tax — no
tax-rate assumption, no interest handling — and because it is computed from aggregate earnings
(`ttm_eps * shares`), which cancels the share-count defect around splits. Using *current* revenue
is what makes it immune to secular growth.

| Ticker | Price | Old anchor (5yr avg) | New anchor (normalised) | Price / new |
|---|---|---|---|---|
| MU | $823.03 | $4.72 | $14.59 | 56x |
| FANG | $202.95 | $10.25 | $18.25 | 11x |
| NUE | $257.29 | $19.60 | $18.92 | 14x |
| UAL | $121.33 | $3.65 | $9.10 | 13x |
| DVN | $45.13 | $5.63 | $5.92 | 8x |
| CLF | $11.52 | $1.08 | $0.64 | 18x |

The 5yr trough/average/peak figures are still shown, but explicitly relabelled as historical range
"for context only — NOT anchors", and the prompt names the normalised figure and forbids
substituting the average.

**Second, independent lesson — the harness could not catch this class of error.** It asserted
ordering only, so a fair value 97% below market passed green. Added a plausibility check
comparing base fair value to current price, deliberately wide (0.3x-3.0x) and *informational*
rather than gating: the goal is catching an anchoring error, not disagreeing with a real call on a
genuinely mispriced stock. A matching SANITY CHECK instruction now asks the Valuation Analyst to
re-check its own anchor before returning a base that far from the market.

Tests: 66 in `tests/test_cycle_data.py`, including a parametrised guard that price divided by the
normalised anchor stays inside a range a multiple could plausibly close. Full suite 587 passed.

**End-to-end verification is still OUTSTANDING.** The deterministic half is confirmed — the
anchor values above are computed in Python and checked offline. What has *not* been confirmed is
that the Valuation Analyst uses the new anchor to produce sane fair values, which is the whole
point of the fix. The verification run on 2026-08-19 is void: the OpenRouter account ran out of
credits and returned HTTP 402 from NVDA's very first sub-agent call onward, so no ticker
completed. Top up credits and re-run `scripts/research_regression.py`; the numbers to check are
MU and FANG, which read -97% and -82% against market price before the fix.

**Known limitation, deliberately not fixed here.** The Phase 3 rubric's trough condition still
compares current EPS to the raw 5-year *average* ("EPS <= 50% of mid-cycle"). On a secular grower
at a genuine trough that test under-fires, because the average is dragged down by a smaller past
business. It is a recall gap rather than a wrong answer, and changing it would invalidate the
Phase 3 calibration and require a full re-sweep, so it is left as a follow-up.

## Phase 9 — Fix `debt_to_ebitda` and enterprise value  [ ]  (follow-up, after Phase 8)

Agreed 2026-08-18 to run this immediately after the cycle plan closes. Scoped as its own piece
because the one-line code change is not the work — the recompute and the diff review are.

**The defect.** `_get_ev_debt_cash` (`historic_fundamentals/pe.py:464`) builds total debt as
`long_term_debt_noncurrent + short_term_debt + current_long_term_debt` and treats NULL components
as zero when at least one is present. `long_term_debt_noncurrent` is NULL in 100% of the 193,441
quarterly `balance_sheets` rows carrying a debt total, so every derived figure sees only the
current portion of debt — a median 6.1x understatement (T 0.25x stored vs 3.24x true; CCL 0.43x
vs 3.91x; VZ 1.26x vs 4.18x; NUE 0.10x vs 1.26x). Full detail at the end of Phase 4.

**Blast radius.** `pe_stats.debt_to_ebitda` and `monthly_pe.debt_to_ebitda` directly; and via the
enterprise-value calculation at `pe.py:689`, also `ev`, `ev_ebitda` and `ebitda_ev_yield`. Those
feed `historic_fundamentals/ml_comps_model.py`, the factor set in `scripts/run_walkforward.py`,
and the `sector_stats` medians.

**Steps.**

1. Prefer `short_long_term_debt_total` in `_get_ev_debt_cash`, falling back to the component sum
   when it is absent. Keep the fallback — the total field is not universally populated either.
2. Recompute `monthly_pe` across the universe (~2,600 tickers) and rebuild `pe_stats` and
   `sector_stats`.
3. Re-run the ML comps validation and the factor walk-forward, and **diff against the current
   baselines**. This is the deliverable, not the code change.
4. Simplify `api/cycle_data.py` `assess_trough_quality` to read the repaired column instead of
   computing leverage locally, and drop the regression guard that pins it away from
   `pe_stats.debt_to_ebitda`. Do this only once step 3 confirms the repair.

**Stated hypothesis, so the recompute is an experiment and not a chore.** EV/EBITDA is the one
ML comps model tracked as a persistent "stable near-miss" on calibration, and it is the model
whose input is corrupted on the debt side. Prediction: its calibration improves. If it does not,
the near-miss has a different cause — also worth knowing. Note the understatement varies by
company rather than being a uniform level shift, so it injects cross-sectional noise too; no
direction is predicted for any individual factor result.

**Risk to weigh before step 2:** every previously validated factor result and backtest baseline
used the broken EV. Some "validated" conclusions may move. Budget the diff review, not the fix.

## Decisions taken

- **Detection window: 7 years**, with a 5-year fallback tier if coverage proves binding. See
  Phase 1 for the coverage table and the survivorship argument that settled it.
- **`MID` renders no standalone section** — one line inside Intrinsic Valuation instead. See
  Phase 5.
- **Input-token cost is a non-issue.** Measured: the current block is 1,042 chars (~260 tokens)
  for AAPL, 1,050 for NUE. Doubling it is negligible, and no phase adds an LLM call, so the
  measured ~$0.31-0.46/report should be unchanged.

## Open question

**Output-token headroom on `chief_analyst_core`.** This is the one real risk and it is a
carry-over, not a new one. `api/research_router.py:2295-2298` records that `max_tokens=16000`
*silently truncated* the Chief's JSON on tickers with a longer `peak_earnings_analysis` section
(COHR named), which is why the budget is 32000 today. A symmetric rubric populates that field on
more tickers, and Phase 4's trap-vs-opportunity reasoning is a longer argument than a peak
warning. There should be headroom at 32000, but it must be measured on a worst case — a
`TROUGH`-verdict cyclical with a long `financial_performance` table — rather than assumed.
Fold that check into Phase 8; a silent truncation reads as a malformed report, not as an error.
