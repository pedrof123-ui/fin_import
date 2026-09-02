# PLAN: Debt Maturity Database (SEC EDGAR)

Status: Phases 0-3 done (2026-09-01), stopped there by request. Phase 4 (full-universe
backfill + cron) and Phase 5 (AI DCF context wiring) not started — next session should pick
up at Phase 4. See each phase's checkboxes below for what was actually built/found; nothing
in Phases 0-3 is speculative, every design choice was driven by a live discrepancy hit
while testing against real filings (see Phase 1.2, 2.2 notes especially).

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

Everything shipped in Phases 0-3 is inert until Phase 4/5 run: `dcf/wacc.py` looks up
`debt_maturity.db.get_summary(ticker)`, which returns `None` until `data/debt_maturity.duckdb`
exists (nothing has written to it yet — Phase 2's tests and live checks all used scratch
DBs in `/tmp`, on purpose, to avoid seeding the real one with a handful of tickers ahead of
a proper full-universe backfill). So today's DCF output is byte-for-byte unchanged for
every ticker; the split only activates once Phase 4 populates the real database.

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

## Phase 4 — Full-universe backfill + refresh cadence — RESUME HERE next session

- [ ] 4.1 Batch run across the full ticker universe (~2,500 tickers), throttled per Phase 0/1
      findings on SEC request pacing.
- [ ] 4.2 Refresh cadence: piggyback on the existing monthly AV-refresh cron (same "no new cron
      needed" pattern as [[project_capex_rd_ratios]]) — a monthly sweep is enough since this only
      changes when a ticker files a new 10-K.
- [ ] 4.3 Live-verify a handful of tickers end-to-end (AV DCF warning text changes as expected
      once real data exists — this is Phase 3's mechanical WACC split activating for real).

## Phase 5 — AI DCF integration — context

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

- [ ] 5.1 `api/ai_dcf_data.py`: new `get_debt_maturity_context(ticker)`, same shape as
      `get_fundamentals_history`/`get_industry_report` — renders the maturity ladder and
      weighted-average coupon/maturity as a text block, null-safe when unavailable.
- [ ] 5.2 Wire into the DCF Architect / Valuation Analyst context assembly so they reason over
      real numbers instead of inferring "probably pre-hike debt" from the warning text alone.
- [ ] 5.3 Tests, including the no-coverage case renders nothing (not an empty/broken block).

## Cross-cutting acceptance criteria

- [x] (Phases 0-3 only; re-check after Phase 4/5) Full existing test suite green
      throughout, not just new tests — 685 passed before Phase 3's edits (already
      including Phases 1-2's new tests); 692 passed, 3 skipped, 3 deselected after
      (including Phase 3's `tests/test_wacc.py` additions). No failures in either run.
- [x] (Phases 0-3 only; re-check Phase 5's new context block too) Every integration point
      is null-safe: a ticker with no debt-maturity coverage behaves exactly as it does
      today (no new hard failures, no clipped/mutated numbers — this stays
      advisory/informational only, consistent with `PLAN_GUARDRAILS.md`'s "warnings, not
      clips" design principle). Concretely: `debt_maturity.db.get_summary` returns `None`
      on a missing file or missing ticker; `dcf/wacc.py` leaves `cost_of_debt_terminal`/
      `wacc_terminal` `None` in that case; `dcf/model.py` falls back to the embedded
      `wacc` for the terminal value, so every ticker's DCF output is unchanged until the
      real `data/debt_maturity.duckdb` is populated (Phase 4) *and* that specific ticker
      has per-tranche coverage (~36% of the universe per Phase 0).
- [x] Coverage numbers and the go/no-go decision logged to `docs/debt_maturity_coverage.md`
      (not only this plan), per [[feedback_log_findings_in_the_artifact]].
