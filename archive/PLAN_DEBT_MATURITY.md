# PLAN: Debt Maturity Database (SEC EDGAR)

Status: ALL PHASES DONE (2026-09-02). See each phase's checkboxes below for what was actually
built/found; nothing here is speculative, every design choice was driven by a live
discrepancy hit while testing against real filings (see Phase 1.2, 2.2, 4.1 notes especially).
`data/debt_maturity.duckdb` is populated for real (1,272 of 2,666 tickers, 268 with the coupon
data the WACC split needs) — Phase 3's mechanical DCF integration is live, not inert, and
Phase 5 wired the same data into the AI DCF Architect and AI Researcher Valuation Analyst as
LLM-facing context. Full test suite 703 passed; the paid AI Researcher regression harness
(5 tickers + degradation case) also passed clean. This plan can be archived.

**Phases 4 and 5 were swapped from the original draft (2026-09-02), before either started:**
the original order had the AI DCF context-wiring phase first. But Phase 3 (the mechanical
DCF WACC split) is already fully built and wired into `dcf/wacc.py`/`dcf/model.py` — it's
inert only for lack of real data. Running the full-universe backfill first activates that
already-finished work immediately, with no further coding, rather than adding more code on
top of an empty database. It also de-risks the context-wiring phase's design: the 90-ticker
coverage sample and 3 deep-dive tickers (IBM/AAPL/Southern Co.) already needed two rounds of
real bug fixes as sample size grew (Phase 1.2) — writing the LLM-facing rendering logic
against the real full-universe distribution, once it exists, beats designing it against a
small sample and risking rework.

**Update 2026-09-02: no longer inert.** Phase 4 populated the real `data/debt_maturity.duckdb`
(1,272 of 2,666 tickers have a summary row, 268 have the coupon data the split needs) and
live-verified the split is active for real (IBM/AAPL/Southern Co.). The paragraph below is
kept for history — it described the state through the end of Phase 3, before Phase 4 ran.

Everything shipped in Phases 0-3 was inert until Phase 4 ran: `dcf/wacc.py` looks up
`debt_maturity.db.get_summary(ticker)`, which returned `None` until `data/debt_maturity.duckdb`
existed (nothing had written to it yet — Phase 2's tests and live checks all used scratch
DBs in `/tmp`, on purpose, to avoid seeding the real one with a handful of tickers ahead of
a proper full-universe backfill). So DCF output was byte-for-byte unchanged for every ticker
until Phase 4 populated the real database.

Builds on: `features/ai_dcf/PLAN_GUARDRAILS.md` Phase 1 (cost-of-debt-vs-risk-free-rate
advisory warning, shipped 2026-08-27), which diagnosed the real issue but explicitly deferred
fixing it: "a real fix (splitting WACC into forecast-horizon vs. terminal-value rates) needs
debt-maturity/vintage data this pipeline doesn't have (AV fundamentals give only aggregate
`interest_expense` and aggregate debt balances)." Confirmed 2026-08-31 via edgartools'
`edgar_notes` tool that this data does exist in SEC 10-K XBRL notes — live-tested on IBM and
AAPL, both returned per-tranche coupon/maturity/amount plus a standardized 5-year-and-thereafter
maturity ladder.

## Why

`dcf/wacc.py::compute_cost_of_debt` estimates a single embedded rate
(`avg_interest_expense / avg_total_debt`, clamped `[2%, 15%]`) and `dcf/model.py` applies the
resulting flat `wacc` to both the 5-year forecast *and* the terminal value (`model.py:937-938`:
`terminal_value = last_fcff * (1 + g) / (wacc - g)`, then `pv_tv = terminal_value / (1 + wacc) **
len(fcff_series)` — same `wacc` both places). For a company with long-dated, low-coupon debt
issued before the current rate cycle, the embedded rate is a defensible discount rate for the
next 5 years (it's the real cash interest burden) but not for a perpetuity-standing-in terminal
value, since that debt will eventually mature and refinance at prevailing rates. Right now the
pipeline can only flag this (`run_dcf_av`'s advisory warning) — it has no data to fix it with.

SEC 10-K debt notes carry exactly the missing ingredient: `us-gaap_ScheduleOfDebtInstrumentsTextBlock`
(per-tranche coupon + maturity + amount) and `us-gaap_ScheduleOfMaturitiesOfLongTermDebtTableTextBlock`
(aggregate principal due in each of the next 5 years, plus "Thereafter"). Both are standardized
XBRL concept IDs, though the rendered table layout varies by filer (see IBM's multi-currency
breakout vs. AAPL's flat table, both pulled live 2026-08-31).

## Design

**Storage:** new `data/debt_maturity.duckdb`, following the existing pattern of small
per-concern DBs (`historic_fundamentals.duckdb`, `industry_research_cache.duckdb`) rather than
extending `av_financials.duckdb` — that one is AV-sourced; this is SEC-sourced, same split the
MD&A pipeline already uses.

- `debt_tranches`: ticker, cik, fiscal_year, filed_date, currency, coupon_rate, maturity_year,
  amount — one row per disclosed tranche/bucket.
- `debt_maturity_summary`: ticker, fiscal_year, weighted_avg_years_to_maturity,
  weighted_avg_coupon_near_term (tranches maturing within the DCF forecast horizon),
  weighted_avg_coupon_long_dated (beyond it), total_debt_covered, total_debt_reported (from
  the balance sheet, for a coverage sanity check) — the numbers actually consumed downstream.

**Extraction:** same `from edgar import Company` entry point `bulk_import_10k.py` already uses
in this repo (the vendored `edgartools` package, not just its MCP wrapper). Per ticker: latest
10-K → `xbrl().notes.search(...)` for a debt-related note → pull tables matching the two
concept IDs above → parse into rows. SEC's own rate limiting is separate from the Alpha Vantage
75calls/min constraint (CLAUDE.md rule 7); edgartools self-throttles per-request already
(`bulk_import_10k.py:403` comment), so this needs its own conservative concurrency setting, not
a copy of the AV limiter.

**Known coverage gap:** companies financed mainly through bank revolvers/private debt won't tag
a maturities schedule at all. Every downstream consumer must treat this as optional
(null-safe fallback to today's embedded-rate-only behavior), matching how
`get_historical_margin_bounds` and the sector DCF fallback already degrade gracefully when
ticker-specific data is missing.

## Phase 0 — Coverage check (decision gate, no schema yet)

- [x] 0.1 Sample ~75-100 tickers spanning market-cap deciles and sectors (reuse the ticker
      universe already used for sector_stats/monthly_pe backfills). Done via
      `scripts/debt_maturity_coverage_check.py`, stratified sample of 90 by `company_overview`
      market-cap decile, seed 42.
- [x] 0.2 For each, fetch the latest 10-K's XBRL, and check concept-level presence of the two
      target concept IDs directly (`xbrl.facts.to_dataframe()`, concept membership) rather than
      keyword note-search — faster and more reliable (IBM's debt note title didn't match a
      `.search('debt')` keyword lookup at all despite having both concepts tagged, confirmed
      live). Recorded per-tranche vs aggregate-ladder presence separately, not just Y/N.
- [x] 0.3 Computed hit rate overall, by decile, by sector, and — the finding that matters —
      broken out **by concept**, since the two concepts answer different questions. Logged to
      `docs/debt_maturity_coverage.md`.
- [x] 0.4 Explicit go/no-go: **GO, decided 2026-09-01** (recorded in
      `docs/debt_maturity_coverage.md`). Headline "either concept" hit rate is 66.7%, but
      the concept this plan's Phase 3 WACC split actually needs (per-tranche coupon,
      `ScheduleOfDebtInstrumentsTextBlock`) is present in only 35.8% of the sample,
      concentrated in bond-issuing sectors (Real Estate/Energy/Industrials 57-75%) vs thin
      in Technology/Healthcare/Financials (14-18%). Spread across market-cap deciles is
      fine (no mega-cap-only concentration) — a sector gap, not a size gap. Chose
      "full universe, null-safe fallback": build for all ~2,500 tickers per the plan's
      original scope; ~36% get the real WACC split, the rest keep today's behavior
      unchanged (the plan's design already requires this fallback for missing data).

## Phase 1 — Extraction + parsing

- [x] 1.1 `scripts/fetch_debt_maturity.py`: given a ticker, fetch the latest 10-K, extract
      both target concepts via `xbrl.facts` (not note-title search, per the Phase 0.2
      finding), parse into `debt_tranches`-shaped rows. Parsing works off a generic row
      shape (a standalone year/"Thereafter" token as pivot, first parseable number after
      it) rather than any filer's specific column layout (CLAUDE.md rule 6) — validated
      live against IBM, AAPL, Southern Co., and 12 more sampled tickers (Real
      Estate/Energy/Industrials/Healthcare/Financials/Consumer) with no crashes and no
      out-of-range years/negative amounts.
- [x] 1.2 Layout variants handled, each found live (not hypothesized): multi-currency
      sections with a running-state per-section currency (IBM: USD/EUR + named GBP/JPY
      overrides, reset to USD rather than leaking the prior section's currency into an
      unresolved "Other currencies" umbrella — a real bug caught and fixed); year ranges
      like "2028-2035" and "2026–2075" averaged to a midpoint (Apple, Southern Co.);
      coupon position relative to the year column varies by filer (IBM: coupon before
      year; Southern Co: coupon *after* year — another real bug caught and fixed: this
      silently zeroed Southern Co.'s entire per-tranche extraction until fixed); a
      multi-subsidiary maturities table (Southern Co.) where the ticker's own consolidated
      column must be picked, not a subsidiary's; a flat single-cell "3.45% Notes due 2028"
      layout with no separate year column (synthetic-tested; the plan's own headline
      example, not yet seen live in the sample). Known unresolved gap, documented not
      fixed: large diversified issuers (Apple) sometimes report decades of tranches in one
      coarse bucket (e.g. $86.8B spanning 2025-2062) — the midpoint-year approximation
      misclassifies near-term-vs-long-dated for that bucket; not fixable without
      finer-grained tags than these two concepts provide.
- [x] 1.3 Unit tests against cached fixtures (`tests/fixtures/debt_maturity/`: real
      TextBlock HTML from IBM/AAPL/Southern Co., covering the variants above) plus
      synthetic HTML for edge cases (empty/malformed input, an explicit "Total" row, an
      em-dash-as-zero amount, a row with no coupon). `edgartools/tests/cassettes` turned
      out not to fit — its cassettes are VCR-style full HTTP recordings for testing
      edgartools itself, not a fixture format for downstream parsers; raw saved HTML is
      simpler and sufficient here.
- [x] 1.4 `uv run pytest tests/test_fetch_debt_maturity.py` green (18 tests). Full existing
      suite run in progress as part of the cross-cutting acceptance check.

## Phase 2 — Storage schema + derived summary

- [x] 2.1 `debt_maturity/db.py` creates `data/debt_maturity.duckdb` with `debt_tranches`
      (no primary key — a filer can legitimately reuse a raw_label, e.g. Southern Co.'s
      subsidiaries each having their own "Senior notes" tranche at the same maturity year;
      refreshed by delete-then-reinsert per ticker, same pattern as
      `historic_fundamentals/mda.py`) and `debt_maturity_summary` (PK ticker+fiscal_year,
      upserted).
- [x] 2.2 `debt_maturity/summary.py::compute_summary` — a design refinement beyond the
      plan's original wording, found live: `weighted_avg_years_to_maturity` cannot simply
      prefer the maturities ladder unconditionally as originally assumed. Southern Co.'s
      ladder is a 5-year-only schedule with no "Thereafter" residual, covering barely 18%
      of its real total debt once the per-tranche table's multi-subsidiary breakdown is
      summed ($21.2B vs $118.2B) — using the ladder there would badly understate both
      `total_debt_covered` and years-to-maturity. Fixed by picking whichever concept
      covers more total dollars (ties go to the ladder, since it's normally finer-grained
      when coverage is equal — confirmed on Apple, where both reconcile to the identical
      $91.281B). Also added a field beyond the plan's original 5 —
      `pct_maturity_dated` — because a large undated "Thereafter" bucket is *silently*
      excluded from the weighted-years average (there's no year to weight it by); on
      Apple that bucket is 54% of total debt, meaning its reported
      `weighted_avg_years_to_maturity` (2.5y) rests on under half the balance. Without
      this field a consumer (esp. Phase 5's LLM-facing text) can't tell a fully-dated
      number (IBM, Southern Co.: 100%) from a mostly-guessed one (Apple: 46%) — this was
      judged necessary for the number to be trustworthy, not scope creep.
- [x] 2.3 `tests/test_debt_maturity_summary.py` (10 tests): weighting math, missing-coupon
      handling (ladder-only → coupon fields None, not an error), single-tranche edge case,
      the undated-bucket-dwarfs-the-total case, and the source-selection tie-break
      (equal coverage → ladder; unequal → fuller source), each derived from a real
      discrepancy hit live (IBM/AAPL/Southern Co.), not hypothesized in advance.

Live end-to-end sanity check (`scripts/backfill_debt_maturity.py`, scratch DB, not the
production one — full backfill is Phase 4): IBM WAYTM=9.8y (100% dated, coupon split
3.10%/3.88% near/long), Southern Co. WAYTM=22.5y (100% dated, 5.31%/4.20%), Apple
WAYTM=2.5y (only 46% dated — flagged, not hidden) with near_term=None (both of Apple's
coarse buckets' midpoint years land beyond the 5y horizon, so the split correctly can't
find any near-term coupon tranche in Apple's own reporting granularity — the coarse-bucket
gap from Phase 1.2 showing up exactly where expected, not a new bug).

## Phase 3 — AV (mechanical) DCF integration — split WACC

- [x] 3.1 `dcf/wacc.py::compute_wacc`: added `cost_of_debt_terminal` (sourced from
      `debt_maturity.db.get_summary(ticker).weighted_avg_coupon_long_dated`, via a lazy
      import so `dcf/wacc.py` doesn't hard-depend on the new module at import time) and
      `wacc_terminal` on `WaccDetail`, plus a `cost_of_debt_terminal_override` parameter
      mirroring the existing `cost_of_debt_override` (wired through `UserOverrides` too).
      Not clamped like the embedded `kd` estimate — this is a reported coupon, not a noisy
      derived rate. Both fields are `None` (no fallback value, no silent default) when a
      ticker has no `debt_maturity_summary` coverage — today's ~2/3 of the universe until
      Phase 4's backfill runs, and the ~64% even after it per the Phase 0 coverage numbers.
- [x] 3.2 `dcf/model.py`: `terminal_value` and `pv_tv` (both formerly keyed on the single
      `wacc`) now use `wacc_tv = wacc_detail.wacc_terminal or wacc_detail.wacc` — falling
      back to the embedded rate when there's no split, so behavior is byte-for-byte
      unchanged for every ticker without coverage. Years 1-5 (`_build_fcff_series`, called
      before this point) still receive `wacc_detail.wacc` directly, untouched. The
      terminal-growth-exceeds-WACC clamp check was also switched from `wacc` to `wacc_tv`,
      since that clamp only protects the terminal-value formula's denominator.
- [x] 3.3 The advisory warning (`cost_of_debt < risk_free_rate`) now branches: when
      `cost_of_debt_terminal` is available it states the terminal value uses a separate,
      higher, disclosed-coupon rate and "does not inherit this understatement"; the
      original "likely understates..." wording is kept verbatim for tickers where the
      split couldn't be applied (still the large majority today).
- [x] 3.4 `tests/test_wacc.py` +6 tests: no-coverage → both fields `None`; auto-lookup via
      a mocked `debt_maturity.db.get_summary`; explicit override wins over lookup (and the
      lookup is asserted *not called* in that case); and an AAPL `run_dcf_av` integration
      test proving years 1-5's `wacc` is unchanged between a flat-WACC baseline and a
      split run, `wacc_terminal > wacc` when the split applies, `pv_terminal_value` is
      correspondingly lower, and the warning text switches. Full DCF suite (144 tests
      across `test_dcf_coverage/test_dcf_as_of/test_compute_dcf_batch/test_screener_dcf/
      test_ai_dcf` + this file) green; full non-integration suite (685 tests, run before
      Phase 3's edits, confirming Phases 1-2 introduced no regression) also green, second
      full run covering Phase 3 in progress.

## Phase 4 — Full-universe backfill + refresh cadence — DONE 2026-09-02

- [x] 4.1 Batch run across the full ticker universe (2,666 tickers from `company_overview`),
      concurrency 5 (Phase 0's validated setting) via a new `--universe` mode on
      `scripts/backfill_debt_maturity.py`, resumable via a progress log. Result: 1,272 tickers
      (47.7%) got any tranche data, but only 268 (10.1%) have the `weighted_avg_coupon_long_dated`
      the WACC split actually needs — source-selection (Phase 2.2) often prefers the
      coupon-less ladder over per-tranche detail when the ladder covers more debt, so the
      Phase 0 sample's 35.8% estimate overstated the real activation rate. 39 initial errors
      (36 transient SEC timeouts + a real bug: `extract_debt_tranches` crashed when a filing
      has no XBRL attachments at all — fixed generically, same null-safe pattern as the
      existing `filing is None` check, `tests/test_fetch_debt_maturity.py` +1 test) all
      resolved on retry, down to 3 genuinely unresolvable "ticker not on EDGAR" cases
      (delisted/renamed). Full numbers in `docs/debt_maturity_coverage.md`'s new Phase 4
      section, per [[feedback_log_findings_in_the_artifact]].
- [x] 4.2 Refresh cadence: wired into `scripts/run_pipeline.py` as a new step (gated on
      `--av-update`, non-fatal, ~20 min), positioned right after `av_update` — piggybacks on
      the existing monthly AV-refresh cron (same "no new cron needed" pattern as
      [[project_capex_rd_ratios]]), a fresh full-universe pass each month (not `--resume`,
      progress log dated per run) since this only changes when a ticker files a new 10-K.
- [x] 4.3 Live-verified end-to-end against the real database (not a scratch DB): IBM/AAPL/
      Southern Co.'s real `debt_maturity_summary` rows reproduce Phase 2's scratch-DB numbers
      exactly; `dcf.model.run_dcf_av` for all three now emits the split-WACC advisory text with
      `wacc_terminal > wacc`; a no-coverage ticker (ZM) confirmed `wacc_terminal is None`,
      unchanged fallback behavior.

## Phase 5 — AI DCF integration — context — DONE 2026-09-02

Suggested starting point: `api/ai_dcf_data.py` already has `get_fundamentals_history` and
`get_industry_report` to pattern-match against for shape/null-safety conventions. The data
this phase needs is `debt_maturity.db.get_summary(ticker)` (Phase 2, returns `None` or a
dict with `weighted_avg_years_to_maturity`, `pct_maturity_dated`,
`weighted_avg_coupon_near_term/long_dated`, `total_debt_covered`) plus, for the maturity
ladder itself (not currently exposed by `get_summary`), a direct query against
`debt_tranches` in `data/debt_maturity.duckdb` (schema in `debt_maturity/db.py`) — that
table doesn't have a read helper yet, only `save_tranches`/`delete_ticker`; add one.
Remember `pct_maturity_dated` when rendering `weighted_avg_years_to_maturity` as text — a
low value (Apple: 46%) means the number rests on less than half the disclosed debt and the
rendered text should say so, not state it as a bare fact. With Phase 4 done first, this
phase should be designed against the real full-universe coverage/quality distribution
rather than the Phase 0 sample alone.

- [x] 5.1 `api/ai_dcf_data.py::get_debt_maturity_context(ticker)` — same [ERROR]/[INFO]-degrade
      shape as `get_fundamentals_history`/`get_industry_report`. Renders weighted-avg
      years-to-maturity (with a CAUTION line when `pct_maturity_dated < 0.9`, per the Apple
      case), near-term/long-dated coupon, total debt covered, and the individual tranches —
      capped at `MAX_DEBT_TRANCHES_SHOWN = 15` by amount (some filers disclose 50-130+
      subsidiary rows, e.g. Entergy: 133), with an "N smaller tranches omitted" note. Added
      `debt_maturity/db.py::get_tranches(ticker)` read helper (the plan's suggested starting
      point — only `save_tranches`/`delete_ticker` existed before).
- [x] 5.2 Wired into both consumers: (a) the DCF Architect — `build_architect_context` gained a
      `debt_maturity_context` param and a new `--- DEBT MATURITY ---` block, gathered
      alongside `engine_context` in `run_ai_dcf`'s asyncio.gather; `ai_dcf_architect.md` gained
      a note that `cost_of_debt_override` shouldn't be used to "fix" a low embedded rate when
      the terminal-value split already handles it automatically. (b) the AI Researcher's
      Valuation Analyst — `api/valuation_data.py::get_dcf_summary` gained the same block
      (imported from `api.ai_dcf_data`) plus `cost_of_debt_terminal`/`wacc_terminal` lines in
      the existing WACC BREAKDOWN, shown only when the split applies.
- [x] 5.3 10 new tests: 4 for `get_debt_maturity_context` (no-coverage renders `[INFO]` not
      empty, full render with/without the caution line, tranche-count cap), a
      price-blindness check (parametrized, matching the module's existing convention), and 4
      round-trip tests for `get_tranches` in new `tests/test_debt_maturity_db.py` (missing
      file/ticker, round-trip, cross-ticker isolation) — `debt_maturity/db.py` had no direct
      unit tests before this (Phase 2 validated it only via live sanity checks). Full suite:
      703 passed (was 693), 3 skipped, 3 deselected. Also ran the paid AI Researcher
      regression harness (`scripts/research_regression.py`, required by this file's own
      review-gate hook since `api/ai_dcf_router.py` changed) — NVDA/UPS/KO/MU/FANG +
      degradation case, **ALL CHECKS PASSED**, no `[FAIL]` anywhere.

## Cross-cutting acceptance criteria

- [x] Full existing test suite green throughout, not just new tests — 685 passed before
      Phase 3's edits (already including Phases 1-2's new tests); 692 passed, 3 skipped, 3
      deselected after Phase 3 (including `tests/test_wacc.py`'s additions); 693 after
      Phase 4's `extract_debt_tranches` no-XBRL-attachments fix (+1 test); 703 after Phase
      5's new tests. No failures in any run. Phase 5 additionally ran the paid AI Researcher
      regression harness (`scripts/research_regression.py`) since it touches
      `api/ai_dcf_router.py` — ALL CHECKS PASSED, no `[FAIL]`.
- [x] Every integration point is null-safe: a ticker with no debt-maturity coverage behaves
      exactly as it does today (no new hard failures, no clipped/mutated numbers — this stays
      advisory/informational only, consistent with `PLAN_GUARDRAILS.md`'s "warnings, not
      clips" design principle). Concretely: `debt_maturity.db.get_summary`/`get_tranches`
      return `None`/`[]` on a missing file or missing ticker; `dcf/wacc.py` leaves
      `cost_of_debt_terminal`/`wacc_terminal` `None` in that case; `dcf/model.py` falls back
      to the embedded `wacc` for the terminal value; `get_debt_maturity_context` renders an
      `[INFO]` placeholder, not an empty/broken block, when there's no coverage — true for
      ~90% of the universe per the real Phase 4 backfill (268/2,666 tickers get the split).
- [x] Coverage numbers and the go/no-go decision logged to `docs/debt_maturity_coverage.md`
      (not only this plan), per [[feedback_log_findings_in_the_artifact]].
