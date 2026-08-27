# AI DCF Guardrail Fixes — Implementation Plan

Companion to `SPEC.md` / `PLAN.md` (Agentic AI DCF Valuator, shipped 2026-07-31). This plan
addresses two real findings from the IBM (2026-08-27) and PEG (2026-08-26) research reports.
Mark each step and phase Complete here as built (CLAUDE.md rule 8). Run everything with
`uv run` (rule 5).

## Background

**IBM report:** the Chief Analyst flagged the AI/mechanical DCF's 2.0% cost of debt as
implausible against a 5.17% risk-free rate — but nothing in the pipeline checks this
deterministically; the Chief only caught it by reasoning over the WACC breakdown text. Traced
to `dcf/wacc.py:compute_cost_of_debt`, which estimates an *embedded* rate
(`avg_interest_expense / avg_total_debt`, clamped `[2%, 15%]`) and landed exactly on the floor.

Investigated whether this is a real bug: **it is not, by itself.** A company that termed out
debt at 2020-2021 zero-rate-era coupons can legitimately show an embedded cost of debt below
today's risk-free rate — that's a fact about existing fixed-rate debt, not a data error. The
actual problem is narrower: `dcf/model.py` uses one flat WACC for both the 5-year forecast
*and* the terminal value. Embedded cost is a defensible rate for near-term years (it's the
real cash interest burden); it is not defensible for the terminal value, which stands in for a
perpetuity and should reflect a sustainable/marginal financing cost, since existing debt will
mature and refinance at prevailing rates long before "forever" arrives. A real fix (splitting
WACC into forecast-horizon vs. terminal-value rates) needs debt-maturity/vintage data this
pipeline doesn't have (AV fundamentals give only aggregate `interest_expense` and aggregate
debt balances) — out of scope here. This plan ships the deterministic flag only (Tier 1);
a time-varying WACC is a separate, larger follow-up if pursued later.

**PEG report:** the AI DCF's 35-42% capex intensity was flagged as breaching the guardrail's
`[0%, 35%]` bound, and the Chief discounted the AI DCF base case ($150.40 → $135.00) partly on
that basis. Checked the bound's provenance: `features/ai_dcf/SPEC.md` §6.5 states
`CAPEX_MIN, CAPEX_MAX = 0.0, 0.35` with no derivation, introduced whole-cloth with the rest of
the feature (commit `eccff1c`) and never calibrated. Pulled actual capex/revenue from
`av_financials.duckdb` (2,581 tickers, latest annual filing, by sector):

| Sector | Median | p90 |
|---|---|---|
| Utilities | 37.98% | 62.4% |
| Energy | 14.8% | 59.7% |
| Real Estate | 9.7% | 51.2% |
| Technology / Healthcare / Consumer / Financials | 1.2%–2.7% | 4%–23% |

The median utility already sits above the flat 35% cap PEG was flagged against — capex is the
only one of the four guardrail metrics (`revenue_growth`, `ebit_margin_pct`, `capex_pct_revenue`,
`cogs_pct`) with no ticker-specific historical anchor; `ebit_margin_pct` and `cogs_pct` both
already compare against the ticker's own history via `get_historical_margin_bounds`. Fix:
extend that same pattern to capex instead of hard-coding one number for every sector.

Both fixes stay **advisory (warnings), not clips** — consistent with the existing design
(`validate_assumptions` never mutates the Architect's authored numbers except the one hard rule,
`terminal_growth_rate`). A hard clip on cost of debt would punish legitimate embedded-cost
situations; a hard clip on capex would override genuine, evidence-cited capital upcycles (e.g.
PEG's stated $24-28B 2026-2030 plan) that are exactly what the DCF Architect is designed to
capture.

---

## Phase 1 — Cost-of-debt sanity warning  [x] Complete (2026-08-27)

Deterministic flag whenever a scenario's cost of debt sits below the risk-free rate, replacing
reliance on the LLM noticing it. Advisory only — `compute_cost_of_debt`'s embedded-rate
estimate and its `[2%, 15%]` clamp are untouched.

- [x] 1.1 In `dcf/model.py::run_dcf_av`, next to the existing
      `if wacc_detail.wacc < 0.05:` check (~line 757), add a sibling check: if
      `wacc_detail.cost_of_debt < wacc_detail.risk_free_rate`, append a `DcfResult.warnings`
      entry. Word it as advisory, not "this is wrong" — name the plausible cause (pre-rate-hike
      fixed debt) and the actual consequence (this same rate discounts the terminal value, where
      it likely understates the sustainable long-run financing cost).
- [x] 1.2 Verify (no code change expected) that this warning reaches the mechanical DCF's
      Valuation Analyst context automatically via `get_dcf_summary`'s existing
      "DATA-QUALITY WARNINGS" block (`api/valuation_data.py:244-245`), which already renders
      any `DcfResult.warnings` entry.
- [x] 1.3 Extend `format_ai_dcf_summary` (`api/ai_dcf_router.py`) to also surface each
      scenario's `engine[label]["warnings"]` (already captured by `_extract_engine_result` at
      line 395 but never rendered). Needed because the AI DCF Architect can independently set
      `cost_of_debt_override`, producing a warning the shared mechanical-DCF context wouldn't
      carry.
- [x] 1.4 Tests: new `tests/test_wacc.py` covering `compute_wacc`/`run_dcf_av` — warning fires
      when `cost_of_debt_override` is set below `risk_free_rate`; no false positive when the
      computed embedded kd sits above rf; confirm the AI-DCF-side surfacing added in 1.3 renders
      the warning text. Update any `test_ai_dcf.py` / `test_ai_dcf_orchestration.py` assertions
      that pin `format_ai_dcf_summary`'s exact output format.
- [x] 1.5 `uv run pytest tests/test_wacc.py tests/test_ai_dcf.py tests/test_ai_dcf_orchestration.py tests/test_dcf_coverage.py tests/test_dcf_as_of.py tests/test_compute_dcf_batch.py tests/test_screener_dcf.py tests/test_research_ai_dcf_integration.py` green.

## Phase 2 — Ticker-anchored capex sanity bound  [x] Code/tests/docs complete (2026-08-27); 2.7 pending

Replace the flat global `CAPEX_MAX = 0.35` ceiling with each ticker's own historical
capex-intensity range plus a buffer, mirroring the existing `ebit_margin_pct` pattern
(`ebit_margin_max + EBIT_MARGIN_HIST_MAX_BUFFER`).

- [x] 2.1 Extend `get_historical_margin_bounds` (`api/ai_dcf_data.py`) to also return
      `capex_pct_max`: the max of the ticker's own historical `capex_pct_revenue` over the same
      7-year window already used for `ebit_margin_max`, reusing the `annual["cashflow"]` /
      `capital_expenditures` join already implemented in `get_fundamentals_history`
      (~lines 145-156). Null when cash-flow history is unavailable or covers fewer than 2 usable
      years (e.g. recent IPOs).
- [x] 2.2 In `api/ai_dcf_router.py::_check_scenario_ranges`: keep `CAPEX_MIN = 0.0` as a hard
      floor (capex can't be negative). Replace the flat `CAPEX_MAX` ceiling with:
      `bounds.get("capex_pct_max") + CAPEX_HIST_MAX_BUFFER` when `capex_pct_max` is available,
      falling back to the existing flat `CAPEX_MAX = 0.35` when it is `None` (keeps a bound
      rather than going unbounded for thin-history tickers). New constant
      `CAPEX_HIST_MAX_BUFFER = 0.15` (proposed — wider than the EBIT-margin buffer's 10pp, since
      capex intensity swings more across an investment cycle than operating margin does; open to
      adjusting after review).
- [x] 2.3 Update the warning message to state which anchor was used (ticker-historical vs. flat
      fallback), for auditability in the rendered QC warnings.
- [x] 2.4 Update `features/ai_dcf/SPEC.md` §6.5's capex bullet to describe the ticker-anchored
      rule, matching how the EBIT-margin bullet already documents its own historical-anchor
      language.
- [x] 2.5 Tests (`tests/test_ai_dcf.py`): add `capex_pct_max` to the `_NEUTRAL_BOUNDS` fixture;
      update `test_validate_assumptions_flags_capex_out_of_range` for the new bound; add:
      - a utility-like bounds fixture (`capex_pct_max=0.38`) where authored 42% capex does
        *not* fire (within historical range + buffer) — regression proof for the PEG
        false-positive;
      - a case where authored capex exceeds even the ticker's own historical max + buffer,
        confirming the warning still fires;
      - a fallback case (`capex_pct_max=None`) confirming the flat 35% ceiling still applies.
- [x] 2.6 `uv run pytest tests/test_ai_dcf.py tests/test_ai_dcf_orchestration.py` green.
- [x] 2.7 Live check: cleared IBM + PEG's cached rows from `data/ai_dcf_cache.duckdb` and
      `data/research_cache.duckdb`, regenerated both full reports end-to-end (2026-08-27, real
      LLM run, ~$0.79 combined). Interim verification (before the live run) also done via direct
      `get_historical_margin_bounds` calls: PEG `capex_pct_max=0.328` → ceiling 47.8%; IBM 0.050
      → 20.0%; AAPL 0.040 → 19.0% — tighter than the old flat 35% for asset-light names.
      **Live-run result:** PEG's AI DCF authored capex 35.8%/39.2% (base/bull) — essentially the
      same magnitude as the original flagged report — and NO capex quality-control-bound breach
      appears anywhere in the regenerated report; the Chief discusses the ramp on its economic
      merits instead. Cost-of-debt warning fired correctly and generically: IBM ("2.0% cost of
      debt is below the 5.17% risk-free rate...") AND PEG independently ("2.09% cost-of-debt
      assumption versus a 5.17% risk-free rate" — PEG wasn't one of the two original tickers
      flagged for this issue, so this is the fix generalizing as intended, not something
      specifically tuned for IBM). Consequential but not isolated by a controlled A/B test (LLM
      run-to-run variance, different day's price): PEG's rating moved HOLD → BUY, base fair
      value $135 → $114, target range $57-$278 → $68-$170 (narrower, no longer inflated by one
      scenario tripping the stale bound). IBM stayed HOLD, target $175-$320 → $172-$285.
      Reports saved to scratchpad (`IBM_regen.md`, `PEG_regen.md`) and sent to the user.

## Cross-cutting acceptance criteria

- [x] Full existing DCF/AI-DCF test suite green, not just the new/updated tests (also ran the
      full project suite: 648 passed, 3 pre-existing unrelated skips).
- [x] Both fixes remain warnings, not clips — no change to `TG`'s existing hard-enforcement
      pattern, no new hard-rejection paths introduced.
- [x] `data/ai_dcf_cache.duckdb` and `data/research_cache.duckdb` cleared for IBM/PEG before the
      live-verification run.
- [x] IBM and PEG re-run manually post-fix, reports read as expected (see 2.7 above for detail).
