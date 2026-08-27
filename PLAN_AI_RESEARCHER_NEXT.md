# AI Researcher — Next Improvements

Candidate next steps identified 2026-08-27 while investigating and fixing the two AI DCF
guardrail bugs (`features/ai_dcf/PLAN_GUARDRAILS.md`, both complete, merged to main). None of
the phases below have started. Mark each step and phase Complete here as built (CLAUDE.md rule
8); move this file to `archive/` once closed out.

## Background

`PLAN_GUARDRAILS.md` fixed two real bugs found by reading live IBM/PEG reports critically: a
cost-of-debt sanity check that didn't exist, and a flat global capex bound that turned out to be
miscalibrated by sector (empirically verified against 2,581 tickers). The same pattern —
generate real reports, read them skeptically, check any suspicious guardrail against real data —
is the highest-value way to find the next bug, so most of what follows continues that pattern
rather than a spec-level audit.

## Phase 1 — Audit the remaining flat guardrail bounds  [ ] Not started

`api/ai_dcf_router.py` still has two guardrail bounds that are flat constants with no
ticker-specific anchor, the same shape the capex bound was before Phase 2 of
`PLAN_GUARDRAILS.md`. Neither is confirmed broken — this phase is the empirical check, not an
assumed fix.

- [ ] 1.1 `REV_GROWTH_MIN, REV_GROWTH_MAX = -0.50, 1.00` (no historical anchor at all, unlike
      capex which now has one). Pull actual YoY revenue growth from `av_financials.duckdb`
      (same query pattern as the capex sector pull in `PLAN_GUARDRAILS.md` Phase 2's
      background) and check the tails specifically for recent IPOs and trough-recovery
      companies — a Year-1 forecast growth rate legitimately above 100% is plausible for both
      and is exactly the false-positive shape the capex bug had.
- [ ] 1.2 `EBIT_MARGIN_MIN, EBIT_MARGIN_MAX = -0.30, 0.60` — lower priority. This one already has
      a ticker-specific soft ceiling layered on top (`ebit_margin_max + EBIT_MARGIN_HIST_MAX_BUFFER`),
      so the flat range is only an outer safety rail, not the primary check, and margins don't
      vary by sector as dramatically as capex intensity does. Do a quick empirical pull to
      confirm before assuming it's fine — don't skip it on assumption alone.
- [ ] 1.3 If either turns out miscalibrated, apply the same fix pattern as capex: ticker-anchored
      bound (historical range + buffer), advisory warning only (never a hard clip), flat
      fallback for tickers with insufficient history. Add tests mirroring
      `tests/test_ai_dcf.py`'s capex regression tests.

## Phase 2 — Live report review across untested sectors  [ ] Not started

Both bugs this session were found by reading real reports (IBM, PEG), not by auditing the spec.
Extend that coverage deliberately rather than waiting for the next report to surface something
by chance.

- [ ] 2.1 Generate and read full reports for at least one REIT, one bank/financial (different
      capital-structure assumptions than the guardrails were designed around — WACC/debt
      treatment for financials is often structurally different), and one hypergrowth small-cap
      or recent IPO (thin history, tests the guardrail fallback paths directly).
- [ ] 2.2 For each, specifically check: does anything in the DCF Scenario Assumptions table, the
      AI vs. Mechanical comparison table, or the Chief's `dcf_reconciliation`/`dcf_assessment`
      prose look economically implausible the way the IBM cost-of-debt and PEG capex findings
      did? Note anything suspicious even if not immediately explainable.

## Phase 3 — Cost-of-debt Tier 2 (terminal-value-specific WACC)  [ ] Blocked — not actionable yet

Deferred in `PLAN_GUARDRAILS.md`'s background section. The theoretically correct fix — splitting
WACC into a forecast-horizon rate (embedded cost of debt, defensible for years 1-5) and a
separate terminal-value rate (a marginal/steady-state cost of debt proxy, since existing
fixed-rate debt will mature and refinance before "forever" arrives) — needs debt-maturity/vintage
data this pipeline does not have. Alpha Vantage fundamentals give only aggregate
`interest_expense` and aggregate debt balances, nothing per-tranche.

- [ ] 3.1 Not startable until a data source decision is made: either a new data feed with
      bond-level maturity/coupon detail, or an accepted simpler proxy (e.g. floor the
      terminal-value WACC's cost-of-debt component at the risk-free rate, leaving forecast-year
      WACC on the embedded rate). Revisit only if this becomes a priority — the Phase 1 warning
      already flags the condition to a human reader in the meantime.

## Backlog — lower priority, not blocking

- [ ] AI DCF frontend viewer panel — deferred as a non-goal in the original build
      (`features/ai_dcf/SPEC.md`). Still markdown-only in reports; no standalone interactive UI
      panel exists for the AI DCF the way `DcfViewer.tsx` exists for the mechanical DCF.
- [ ] `archive/PLAN_CYCLE_AWARENESS.md` Phase 8 notes "one run of the extended harness as the
      final gate" as outstanding. Predates this plan and is unrelated to AI DCF specifically;
      may already be stale since that plan is archived (implying it was closed out) — verify
      before treating as a real open item.
- [ ] MD&A 10-Q extension paused pending a go-ahead (per prior session record) — a data-pipeline
      item feeding the Guidance & MD&A evidence agent, not an AI Researcher code change.
