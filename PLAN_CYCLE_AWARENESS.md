# AI Researcher — Industry Cycle Awareness

Created 2026-08-17. **Status: Phases 0-3 complete. Next: Phase 4.**

## Resume here

Next action: **Phase 4 — trough vs. value trap.** This is the phase that makes the feature a
profit-opportunity rather than a second warning label, and Phase 3 deliberately left the gap it
fills: the rubric can say TROUGH, but the prompt is currently instructed **not** to call a trough
an opportunity, because a depressed cyclical and a structurally impaired business are
indistinguishable on the five trough conditions. Phase 4 supplies the discriminator (revenue
trajectory, peer breadth via `get_industry_aggregates`, debt/EBITDA survivability) and the prompt
instruction should be relaxed in step with it.

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

## Phase 4 — Trough vs. value trap  [ ]

The discriminator that makes this a profit-opportunity feature rather than a second warning
label. For a `TROUGH` verdict, classify mean-reverting vs. structurally impaired using:

- **Revenue trajectory** — `rev_growth_1yr` against `rev_cagr_5yr`. Is revenue also structurally
  declining, or is this a margin event on intact demand?
- **Peer breadth** — is the whole industry depressed, or only this company? Industry-grain
  medians with 3/6/12-month deltas already exist in `api/industry_data.py:176-209, 261-270`
  (`get_industry_aggregates`) but are currently unused by the equity researcher. Industry-wide
  margin compression points to cycle; company-only points to share loss or secular decline.
  This is the phase that genuinely wires the industry dimension into the researcher.
- **Survivability** — `debt_to_ebitda` at trough earnings. A cyclical that cannot fund itself to
  the recovery is not an opportunity.

Only a trough that clears all three is framed as an opportunity; otherwise it is reported as a
possible value trap.

## Phase 5 — Schema, prompt, rendering  [ ]

Per the verified change checklist:

1. `EquityResearchReport` (`research_router.py:290`) — add `cycle_position:
   Optional[Literal["PEAK","TROUGH","MID","NOT_CYCLICAL"]] = None` and `cycle_position_analysis:
   Optional[str] = None`. Retire `peak_earnings_analysis` from the *generated* schema but leave
   the attribute present and optional so existing test fixtures
   (`tests/test_research_ai_dcf_integration.py:157, 319, 338`) keep constructing.
2. `ChiefCoreOutput` (`:322`) — add both fields to the Core half only. The merge at `:2360` is a
   `**` splat, so a field present in both chief models raises.
3. `api/prompts/research_chief_core.md` — replace the `peak_earnings_analysis` instruction with
   the symmetric rubric; state that the field stays null when `cycle_position` is `NOT_CYCLICAL`.
4. `render_to_markdown` (`:452`) — replace the block at `:539-547`. Heading and callout branch on
   `cycle_position`: "Peak-Earnings Trap Alert" (Warning) vs "Trough-Earnings Opportunity"
   (Opportunity), preserving its current position between Intrinsic Valuation and Company
   Overview.

   **`MID` renders no standalone section.** A confirmed mid-cycle reading is true but not
   actionable, and giving it a section puts a "nothing is happening here" block in most cyclical
   reports. Suppressing it outright would make absence ambiguous, though — the reader could not
   tell "we checked, it is mid-cycle" from "we never checked". So emit the verdict as a single
   line inside an existing section (Intrinsic Valuation) whenever the gate returns `CYCLICAL`,
   and reserve the standalone callout for `PEAK` and `TROUGH`.

## Phase 6 — Make it affect the valuation  [ ]

The structural fix. Add a **price-free** mid-cycle earnings block to `valuation_analyst_context`
(`research_router.py:2222-2233`): TTM EPS, forward EPS, 5yr min/mid-cycle/max EPS, current vs.
5yr-median operating margin, and the cyclicality classification. No `current_pe`, no
`normalized_pe_5y` — nothing carrying today's price, preserving the blindness that
`api/valuation_data.py:266-270` exists to protect.

Extend the PEAK-EARNINGS AWARENESS instruction (`api/prompts/research_valuation.md:114-116`) to
be symmetric: on a cyclical trough, a multiples cross-check anchored on forward consensus EPS
understates fair value the same way TTM overstates it at a peak; anchor on mid-cycle earnings
power instead and say so in `valuation_methodology`.

## Phase 7 — Industry cycle framing  [ ]

Lowest value of the set; do last or drop if the earlier phases land well. Add a cycle-position
cluster to `industry_outlook` in `api/prompts/research_competitive.md:44-53`, so the industry
section carries a cycle read alongside its secular TAM framing.

## Phase 8 — QC and regression  [ ]

- One narrow `_validate_report` check before `return findings` (`research_router.py:2085`):
  flag a `cycle_position` of `PEAK` or `TROUGH` on a ticker the Phase 1 gate classified
  `NOT_CYCLICAL`. Keep it narrow — the regression harness gates on `qc_findings == []`
  (`research_regression.py:86`), so any check that can fire on a healthy ticker fails the suite.
- Extend `scripts/research_regression.py`'s ticker set with one known cyclical at trough (NUE or
  GM) and one at peak, asserting the section renders with the expected polarity.
- Full-universe fire-rate report for peak, trough and not-cyclical, to confirm finding 3's 40.5%
  false-positive rate is gone.
- **Output-truncation check** (see Open question): generate a worst-case report — a
  `TROUGH`-verdict cyclical carrying a long `financial_performance` table — and confirm the
  Chief's JSON completes well inside `max_tokens=32000`. Truncation here is silent and surfaces
  as a malformed report rather than an error, so assert on it explicitly rather than eyeballing.

---

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
