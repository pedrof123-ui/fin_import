# AI Researcher — Industry Cycle Awareness

Created 2026-08-17. **Status: Phase 0 complete, paused before Phase 1.**

## Resume here

Next action: **Phase 1 — the cyclicality gate.** It is the load-bearing piece; Phases 2-8 all
depend on its `CYCLICAL` / `NON_CYCLICAL` / `INSUFFICIENT_HISTORY` verdict.

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

## Phase 1 — Cyclicality gate  [ ]

Without this the rubric is noise (finding 3). Only companies that actually exhibit cyclical
behaviour should get a cycle-position verdict at all.

New helper computing a cyclicality classification from `monthly_pe` over a **7-year** window:

- coefficient of variation of `ttm_eps`
- fraction of months with `ttm_eps <= 0`
- peak-to-trough EPS amplitude
- revenue amplitude alongside earnings amplitude, to separate demand cyclicality from pure
  margin swings

Output: `CYCLICAL` / `NON_CYCLICAL` / `INSUFFICIENT_HISTORY`. Data-driven, not a sector
whitelist — per CLAUDE.md rule 6 the fix must be generic across all stocks.

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

## Phase 2 — Symmetric, honest cycle data  [ ]

Rework `get_peak_earnings_data` (`research_router.py:816`) into `get_cycle_position_data`:

- **Drop `AND ttm_eps > 0`** so loss periods count. This is the change that makes mid-cycle EPS
  honest and the trough visible. Note it changes existing peak-side numbers for cyclicals —
  intended, and the reason Phase 0 comes first.
- Add `MIN(ttm_eps)` over the window.
- Label `AVG(ttm_eps)` explicitly as mid-cycle EPS, and add "current EPS as % of mid-cycle" —
  the one ratio that reads correctly in both directions.
- Guard the existing `pct_of_peak` division when `eps_5yr_max <= 0` (all-loss company).
- Emit the Phase 1 cyclicality classification into the block.

Verification: re-run the four tickers in the finding-2 table and confirm the mid-cycle figures
now match the true values.

## Phase 3 — Symmetric rubric  [ ]

Replace the one-sided INTERPRETATION GUIDE (`research_router.py:886-896`) and the matching
prompt rubric (`api/prompts/research_chief_core.md:119-131`) with peak and trough blocks, gated
on `CYCLICAL` from Phase 1.

Repair the degenerate condition first: **condition 4 must go or be re-specified**, since it is
99.7% redundant with condition 1 (finding 3). A defensible replacement compares current P/E to
the *price-independent* `pe_rolling_5yr_median` rather than to `normalized_pe_5y`.

Trough conditions mirror the repaired peak set — EPS well below mid-cycle, forward EPS well
above TTM (analysts forecast recovery), earnings falling materially faster than revenue (margin
compression rather than demand collapse), multiple optically high or undefined on depressed
earnings, operating margin well below the 5yr median.

Two cases the dry run exposed and that must be handled explicitly:

- **Negative mid-cycle EPS** (AAL: 5yr avg -$0.53). The "% of mid-cycle" test is meaningless.
  Fall back to a margin- and revenue-based position read.
- **Both sides firing** (V scored 2 peak / 2 trough). Define the tie-break rather than leaving
  it to the model.

Thresholds are to be calibrated in-phase against the same labelled sample as Phase 1, not
guessed. Report the fire rate across the universe — if either side fires on more than roughly a
quarter of *cyclical* names, the thresholds are too loose.

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
