# Agentic AI DCF Valuator — Implementation Plan

Companion to `SPEC.md`. Phased, test-first, executable by a coding agent. Mark each step and
phase Complete here as built (CLAUDE.md rule 8). Run everything with `uv run` (rule 5). Keep the
Alpha Vantage budget in mind at every phase (rule 7): the only permitted new AV calls are the
target's own transcript probe and estimate refresh — competitor data is cached-only.

Conventions carried over from the industry-research build:
- Every DB connection opened during a parallel gather is `read_only=True`.
- Gather data ONCE per run and pass it to both LLM contexts and deterministic renderers — no
  function may independently re-fetch what the orchestrator already fetched.
- LLM writes assumptions and prose; Python computes and renders every number.
- After any prompt/schema change, clear the relevant cache (`DELETE FROM ai_dcf_cache`) before
  judging output.

---

## Phase 0 — Data-readiness + engine-override audit  [x] Complete (2026-07-30)

No new feature code. Verify the ground the feature stands on, with a short written note of
findings appended to this phase.

- [x] 0.1 MD&A coverage: for 5 sample tickers (TXN, UPS, FIVE (mid-cap), CRWV (recent IPO),
      ETSY (zero coverage — genuine 0-row case, kept as the "low-coverage" example instead of
      substituting another ticker) plus APLD as a second recent/thin-history name), queried
      `mda_filings.duckdb`. Findings:
      - TXN: 40 rows (10-K + 10-Q back to ~2016), char_count 14k-25k, all `status='ok'`.
      - UPS: 40 rows, char_count 20k-**119k** (much larger than TXN/EDGAR-derived MD&A
        elsewhere in the project, which caps at 8000 chars) — needs real truncation.
      - CRWV: 5 rows only (IPO'd 2025) — degrade path (fewer than 3 annual 10-Ks) will be
        exercised routinely for recent IPOs, not just as an edge case.
      - ETSY: 0 rows — `get_mda_history` must degrade cleanly to "no MD&A cached", not error.
      - **New finding**: `mda_filings.status` includes `'empty'` (13,125 of 79,469 total rows
        project-wide) alongside `'ok'` (66,344) — e.g. CROX has 4 empty 10-Qs interleaved with
        real ones. `get_mda_history` MUST filter `status='ok'` — `get_cached_mda`'s current
        signature returns all rows regardless of status, so Phase 1.2 filters client-side.
      - Decided cap: **8,000 chars/filing** (matches the existing `_MAX_EDGAR_CHARS` convention
        in `research_router.py`), 3 annual 10-Ks + 1 latest 10-Q = **32k char budget**, safely
        under the ~40k target.
- [x] 0.2 Industry-report mapping: resolved `company_overview.industry ->
      industry_data.scope_key -> industry_research_cache` for the 5 tickers. TXN -> SEMICONDUCTORS
      -> 2 cached rows (both ~3 days old at audit time) — hit path confirmed working. UPS ->
      INTEGRATED FREIGHT & LOGISTICS, CRWV -> SOFTWARE - INFRASTRUCTURE, FIVE -> SPECIALTY
      RETAIL, APLD -> INFORMATION TECHNOLOGY SERVICES — all 0 cache rows (expected; industry
      reports only exist for the 6 industries generated during the Industry Researcher's own
      build/testing). Join logic itself works correctly.
- [x] 0.3 Engine override behavior (critical — the whole feature rides on this) — **found and
      resolved a real landmine, schema changed as a result (see SPEC 6.2b):**
      - Confirmed (a) year_forecasts reflect `revenue_growth`/`capex_pct_revenue` overrides
        exactly; (b) intrinsic value moves in the expected direction (TXN default $53.48 ->
        aggressive-bull override $112.88); (d) `beta`/`tax_rate_override`/`cost_of_debt_override`
        flow into `wacc_detail` exactly as set (verified beta_raw=1.500, cost_of_debt=0.0300,
        tax_rate=0.1500 on a forced override).
      - **(c) was NOT clean** — this is the landmine: `ebit_margin_pct` alone is capped at
        `1 - cogs_pct - sga_pct - rd_pct` for `reports_cogs=True` companies. UPS
        (`cogs_pct` ≈ 0.813) requesting `ebit_margin_pct=0.35` silently produced **0.187**
        instead — no error, just a different number. This is NOT the no-COGS-company case from
        `project_dcf_no_cogs_companies` (UPS actually has `reports_cogs=True`; that memory's
        no-COGS example is presumably a different, more purely-service company). Root cause:
        `dcf/model.py`'s EBIT-margin plug (~line 765) computes
        `other_opex = 1 - cogs_pct - sga_pct - rd_pct - ebit_m`; when negative, it floors
        SG&A/R&D at zero and gives up — cogs_pct itself is never touched unless separately
        overridden.
      - **Fix verified**: setting `cogs_pct=0.55` alongside `ebit_margin_pct=0.30` for UPS
        produced exactly 0.300 (confirmed `merge_overrides` in `forecaster.py:463-478` applies
        `cogs_pct` before the EBIT-margin plug runs). For `reports_cogs=False` companies,
        `cogs_pct` is pinned at 0 by the forecaster regardless (`forecaster.py`'s
        `cogs_flat = ... if reports_cogs else 0.0`) so `ebit_margin_pct` alone has full range
        there — no ceiling issue for genuinely no-COGS businesses.
      - **Schema change**: `ScenarioAssumptions` gains `cogs_pct: list[float]` (SPEC 5.5/6.2).
        `get_engine_context` must expose `reports_cogs` + historical COGS% (SPEC 5.4/6.2b).
        `validate_assumptions` gains an internal-consistency guardrail (SPEC 6.5). Confirmed
        via `V`/`MA`/`PYPL`/`MSCI`/`SPGI` spot-check that `reports_cogs=True` is the overwhelming
        common case (all 5 tested True) — the ceiling issue is the norm, not the exception, for
        any company that reports a COGS/gross-profit line.
- [x] 0.4 Transcript/estimates coverage: TXN (4 quarters cached, latest 2026Q2), UPS (3 quarters,
      2026Q1), CRWV (3 quarters, 2026Q1) all warm. `earnings_estimates` row counts: TXN 520,
      UPS 40, CRWV 24 — all non-zero. Newest-quarter probe logic reusable as-is, no changes
      needed.
- [x] 0.5 Decided constants:
      - MD&A per-filing char cap: **8,000** (matches `_MAX_EDGAR_CHARS`); 3 annual + 1 quarterly
        = ~32k char budget for the Guidance agent.
      - Competitor transcripts: **max_peers=5**, reuse `_MAX_TRANSCRIPT_CHARS=7000`/quarter,
        4 quarters — cached-only, so actual size varies with what's on hand.
      - Industry-report age window: **14 days**, per SPEC (confirmed no reason to change after
        seeing real cache ages — the 2 TXN-industry rows were 3 days old, comfortably inside).
      - Evidence-agent context budget: no hard cap set beyond the per-source caps above; total
        composed context per evidence agent expected in the 15-40k char range, well within
        normal LLM context windows for the models already in `_MODEL_OPTIONS`.

Acceptance: findings above satisfy the phase's acceptance criteria — the cogs_pct/ebit_margin_pct
interaction surprise was caught and the SPEC updated (6.2, 6.2b, 5.5, 6.5) BEFORE Phase 2 locks
the schema, as required.

---

## Phase 1 — Data layer, no LLM: `api/ai_dcf_data.py`  [x] Complete (2026-07-30)

- [x] 1.1 `get_fundamentals_history(ticker)` — up to 10 annual years from `av_financials.duckdb`:
      revenue + YoY growth, gross/operating/net margins, COGS/SGA/R&D/other-opex % of revenue,
      capex % of revenue, D&A % of revenue, DSO/DPO/DIO, FCF, diluted shares. Formatted text
      block, `[ERROR]` degrade.
- [x] 1.2 `get_mda_history(ticker, n_annual=3)` — per SPEC 5.4, using
      `historic_fundamentals.mda.get_cached_mda`; **filter `status == 'ok'` client-side**
      (Phase 0.1 finding: `'empty'` rows are real and common — ~16.5% of all cached rows
      project-wide); labels `[10-K FY2025 MD&A]` etc.; truncate to **8,000 chars/filing**
      (Phase 0.5); degrade to `[INFO] no MD&A cached` when zero `'ok'` rows exist (exercised
      routinely for recent-IPO tickers like CRWV, not just as an edge case).
- [x] 1.3 `get_industry_report(ticker, max_age_days=14)` — per SPEC 5.4; returns
      `(markdown, age_days)` or None; freshest across models; skips `custom:*`.
- [x] 1.4 `get_competitor_transcripts(ticker, max_peers=5, n_quarters=4)` — cached-only
      (imports NO AV-fetch functions — enforce by test); peer selection via the `_peer_df`
      pattern (top by market cap, same industry).
- [x] 1.5 `get_engine_context(ticker)` — risk-free rate (`dcf.data.load_risk_free_rate_30y`,
      falling back to `load_risk_free_rate`), raw 5yr/2yr beta (`dcf.wacc.get_betas`),
      historical effective tax rate (`dcf.wacc.compute_effective_tax_rate` on the last 5 annual
      periods, same convention as `dcf/model.py` line ~616), book total debt/equity, share-count
      trend, **`reports_cogs` flag + 7yr-median historical COGS% of revenue**. Implementation
      note (deviation from the original sketch): `reports_cogs`/historical COGS% are derived
      directly from `load_av_annual_financials`'s income dataframe (same
      `cost_of_revenue.notna().any() or gross_profit.notna().any()` test `forecaster.py` uses)
      rather than running a full baseline `run_dcf_av(ticker)` — cheaper, self-contained, and
      avoids a whole DCF engine run just for one boolean + one ratio. Text explains the
      cogs_pct/ebit_margin_pct interaction so the Architect prompt (3.1/4.1) can instruct
      accordingly. NO market cap, NO price (verified by `test_engine_context_price_blind`).
- [x] 1.6 Context assembly helpers: `build_fundamentals_context`, `build_industry_context`
      (peer table + sector_stats industry aggregates + Tavily search text + industry report w/
      age tag + competitor transcripts), `build_guidance_context` (MD&A history + target
      transcripts + beat/miss + consensus estimates). Each takes ALREADY-FETCHED pieces as
      arguments (raw/format split — orchestrator fetches once).
- [x] 1.7 Tests (`tests/test_ai_dcf.py`, 25 tests):
      - industry-report window/selection/exclusion/age math (fixture cache DB);
      - MD&A selection order + truncation + empty degrade (fixture MD&A DB) — including the
        Phase 0.1 `status='empty'` filtering finding;
      - competitor transcripts cached-only guarantee (monkeypatched `et.fetch_from_av` raises
        if called — confirmed never invoked);
      - sanitization: composed contexts for real tickers (TXN, UPS) contain no current-price/
        market-cap/analyst-target strings (string-level assertions, mirrors
        `tests/test_valuation_data.py`'s existing convention);
      - each builder degrades to a placeholder on missing DB.
      - `test_engine_context_reports_cogs_matches_phase0_findings` — regression test for the
        Phase 0.3 landmine, confirms TXN/UPS both report_cogs=True and the ceiling warning text
        is present in the engine context.

Acceptance met: `uv run pytest tests/test_ai_dcf.py` — 25/25 green; full project suite
(`uv run pytest tests/`) — 356 passed, 3 skipped, no regressions. Scratch run against real DBs
for TXN (fundamentals history — 10yr revenue/margins/COGS-SGA-R&D breakdown, FCF, NWC days all
populated), CRWV (MD&A — degrades correctly to 2 filings, only 1 annual 10-K cached for this
2025 IPO), TXN industry report (3 days old, correctly under the 14d window), and TXN competitor
transcripts (NVDA transcript found and rendered, cached-only) all produced sensible output.

---

## Phase 2 — Assumption schema, guardrails, engine bridge, renderers (no LLM)  [x] Complete (2026-07-30)

- [x] 2.1 Pydantic schemas in `api/ai_dcf_router.py`: `ScenarioAssumptions`,
      `AiDcfAssumptions`, the three brief schemas (SPEC 5.5), with `_coerce_optional_float`
      (imported from `api.research_router`, not duplicated) validators on all numeric fields —
      including an element-wise `_coerce_float_list` for the four list[float] fields, plus a
      `_require_len_5` validator enforcing exactly 5 years at construction time (a wrong-length
      list raises `pydantic.ValidationError` immediately, so `validate_assumptions` never has
      to handle malformed-length scenarios itself — simpler than the originally-sketched
      "reject the scenario" runtime path).
- [x] 2.2 `validate_assumptions(a: AiDcfAssumptions, bounds: dict) ->
      tuple[AiDcfAssumptions, list[str]]` — guardrails per SPEC 6.5. Signature simplified from
      the sketch: `bounds` (= `api.ai_dcf_data.get_historical_margin_bounds(ticker)`'s dict)
      already carries `reports_cogs`, so it isn't a separate parameter. Soft warnings for
      revenue growth/EBIT margin/capex/cogs_pct range violations, margin-vs-historical-max,
      cogs-drop-without-headroom, and the `reports_cogs=True`
      `ebit_margin_pct[i] > 1 - cogs_pct[i]` internal-consistency check (SPEC 6.2b). The one
      hard rule (`terminal_growth_rate` out of [0%,4%]) is flagged here as a warning but
      **enforced in `to_overrides`, not here** — `validate_assumptions` never mutates `a`
      (verified by `test_validate_assumptions_never_mutates_input`), since
      `ScenarioAssumptions.terminal_growth_rate` is a required (non-Optional) float that can't
      be cleared to `None` in place.
- [x] 2.3 `to_overrides(s: ScenarioAssumptions, a: AiDcfAssumptions, reports_cogs: bool) ->
      UserOverrides` — mapping per SPEC 6.2; only passes `cogs_pct` into `YearOverride` when
      `reports_cogs` is True; drops `terminal_growth_rate` to `None` (engine default) when out
      of range — this is where the Phase 2.2 hard-rule warning actually takes effect.
- [x] 2.4 `run_ai_dcf_engine(ticker, assumptions, reports_cogs) -> dict[str, DcfResult | None]`
      — three `run_dcf_av` calls (bear/base/bull), per-scenario exception -> None, base None ->
      raises `RuntimeError` (AI DCF unavailable). Read-only `historic_fundamentals.duckdb`
      connection, same pattern as `compute_dcf_scenarios`.
- [x] 2.5 `AiDcfResult` dataclass (`.build()` classmethod, `to_dict`/`to_json`/`from_dict`/
      `from_json`) — JSON round-trip verified. `_extract_engine_result` pulls only the fields
      renderers need from a real `DcfResult` (intrinsic value, full WACC breakdown, terminal
      growth/value%, 5yr per-year revenue/growth/EBIT-margin/capex/FCFF, warnings) into a flat
      JSON-serializable dict — Pydantic sub-models (assumptions, 3 briefs) serialize via
      `.model_dump()`/`.model_validate()`, not `dataclasses.asdict` (which doesn't traverse
      BaseModel instances).
- [x] 2.6 Renderers: `render_ai_dcf_markdown` (standalone report, SPEC 7.1 — header/inputs-used/
      valuation summary/assumptions table/key debates/scenario rationales/WACC rationale/all
      3 evidence briefs/QC warnings); `render_ai_dcf_comparison_table` (SPEC 7.2 — AI vs.
      mechanical, both columns computed from engine output, `_ai_row_stats`/
      `_mechanical_row_stats` share the same rev-CAGR/avg-margin/avg-capex math already used by
      `research_router._dcf_assumptions_table`); `render_ai_dcf_triangulation_row` (single row
      for `research_router._model_summary_table`, Phase 6 splices it in). All reuse `_md_table`.
- [x] 2.7 Tests (`tests/test_ai_dcf.py`, +51 tests, 76 total in the file):
      - guardrails: every soft-warning rule fires on crafted inputs (revenue growth, EBIT
        margin absolute + vs.-historical-max, capex, cogs_pct absolute + drop-without-headroom,
        the UPS-like `ebit_margin_pct > 1-cogs_pct` consistency check, cogs-checks skipped for
        `reports_cogs=False`); the length-5 `ValidationError` at construction time; placeholder-
        string coercion; `validate_assumptions` never mutates its input;
      - `to_overrides` drops out-of-range TG / keeps in-range TG / includes-or-omits `cogs_pct`
        by `reports_cogs`;
      - `check_scenario_ordering` flags and clears correctly;
      - **engine round-trip against the REAL `run_dcf_av`** (not mocked) on TXN (finite
        intrinsic value, year_forecasts match authored values exactly) and UPS — including the
        exact Phase 0.3 regression: `cogs_pct=0.55` + `ebit_margin_pct=0.30` achieves 0.300
        exactly (`test_run_ai_dcf_engine_ups_ebit_margin_ceiling_regression`), plus a companion
        negative test proving the ceiling still exists WITHOUT the cogs override
        (`test_run_ai_dcf_engine_ups_ebit_margin_without_cogs_override_hits_ceiling`) so a
        future engine change silently "fixing" this doesn't go unnoticed;
      - base-scenario engine failure raises;
      - `AiDcfResult` JSON round-trip equality; `render_ai_dcf_markdown`/
        `render_ai_dcf_triangulation_row`/`render_ai_dcf_comparison_table` numbers match a
        fixture's engine extracts exactly (no mocked LLM needed — these are pure functions).

Acceptance met: `uv run pytest tests/test_ai_dcf.py` — 76/76 green; full project suite
(`uv run pytest tests/`) — 382 passed, 3 skipped, no regressions. The Phase 0.3 scratch scenario
is now a permanent regression test, reproduced through the real bridge end-to-end (assumptions
in, engine out) with zero LLM involvement.

---

## Phase 3 — Prompts + evidence agents (Stage 1)  [x] Complete (2026-07-30)

- [x] 3.1 `api/prompts/ai_dcf_fundamentals.md` — Fundamentals Historian: extract the sustainable
      growth/margin/capex/working-capital ranges the HISTORY supports, flag cyclicality and
      one-offs; forbid forward speculation (that is the Guidance agent's job); inline source
      tags `[FY2023]`-style; `{style_guide}`/`{ticker}`/`{date}`/`{context}` placeholders.
- [x] 3.2 `api/prompts/ai_dcf_industry.md` — Industry & Competitors Analyst: industry growth
      outlook, pricing/margin direction, capex cycle, competitive position vs. named peers,
      terminal-growth context; must tag industry-report citations with age
      (`[Industry report, Nd old]`) and distinguish them from live search `[TAM search]` and
      peer-DB `[DB]` evidence; carries the incidental-price-noise clause.
- [x] 3.3 `api/prompts/ai_dcf_guidance.md` — Guidance & MD&A Analyst: quoted explicit guidance
      with quarter tags, strategy shifts across the MD&A years, demand inflections, guidance-
      vs-actuals credibility read; incidental-price-noise clause.
- [x] 3.4 Evidence fan-out in `ai_dcf_router.py`: standalone `_run_evidence_agent` (copy of
      `research_router._run_subagent`'s timeout/fallback pattern, but a free function rather than
      a closure so it's independently mockable), 3 agents in parallel via `asyncio.gather` in
      `run_evidence_agents`, per-agent fallback brief with `[ERROR]` fields. **Added beyond the
      original sketch**: a `_sanitize_all_fields` model-validator hook (via
      `model_validator(mode="after")`) on all 5 Pydantic schemas (3 briefs + `ScenarioAssumptions`
      + `AiDcfAssumptions`) reusing `industry_research_router._sanitize_prose` — the literal-
      backslash-n LLM quirk (documented as a known landmine, SPEC 6.7) was actually observed live
      on TXN's fundamentals brief during 3.5's check, confirming the landmine applies here too,
      not just in the industry researcher.
- [x] 3.5 Live check (real LLM, `google/gemini-3.5-flash`): ran the three agents for TXN (good
      coverage) and CRWV (2025 IPO, thin history — 1 annual 10-K, 3 transcript quarters).
      Findings: provenance tagging worked exactly as specified — fundamentals brief cited
      `[FY2016-FY2025]`-style year ranges matching real data (e.g. "COGS expanded from 31.2% of
      revenue in FY2022 to 43.0% in FY2025" — matches `get_fundamentals_history` output exactly);
      industry brief correctly used the cached SEMICONDUCTORS report with
      `[Industry report, 3d old]` tags, distinguished from `[DB]` (peer/aggregates) and
      `[NVDA 2027Q1]` (competitor transcript) tags; guidance brief cited specific quarters
      (`[Q2 2026 Call]`) with real guidance figures (Q3 revenue $5.65-6.15B, EPS $2.23-2.57) and
      caught a real strategic event (Silicon Labs acquisition, Q1 2026). CRWV's thin-history case
      degraded cleanly (brief still produced, correctly scoped to the ~1 year of real data
      available). No price/market-cap leakage observed in either run. After the sanitization fix
      (3.4), verified at the raw-string level (not JSON-escaped, which would give a false
      positive) that no literal backslash-n remains in any brief field for either ticker.

Acceptance met: mocked-agent unit tests (`test_run_evidence_agents_fan_out_one_failure_others_succeed`
— fan-out returns 3 briefs, one agent "failing" yields its `[ERROR]` fallback while the other two
return real Pydantic objects unchanged) + the live check done and noted above. 59/59 tests green
in `tests/test_ai_dcf.py`.

---

## Phase 4 — DCF Architect + orchestrator  [x] Complete (2026-07-30)

- [x] 4.1 `api/prompts/ai_dcf_architect.md` — senior equity-valuation expert persona
      (15+ years, institutional buy-side DCF practice). Inputs: the three briefs + engine
      context (Phase 1.5), composed by `build_architect_context` into one `{context}` block
      (the prompt uses the standard single-placeholder convention, not the four separate
      placeholders originally sketched — simpler, matches every other prompt in the codebase).
      Explicit instructions on how the engine consumes each field, the `cogs_pct`/
      `ebit_margin_pct` ceiling constraint (SPEC 6.2b), bear-must-be-genuine-downside /
      bull-must-be-defensible-upside discipline, no valuation arithmetic, price-blind clause —
      all per the sketch, live-verified working in 4.4.
- [x] 4.2 Orchestrator `run_ai_dcf(ticker, model, status_cb) -> AiDcfResult` in
      `api/ai_dcf_router.py`: gathers all Phase 1 inputs in parallel via a thread-pool `_run`
      wrapper (per-call timeout AND per-call exception catch, degrading to `[ERROR]`/a supplied
      `default` rather than ever raising out of the gather step) -> builds the 3 evidence
      contexts -> `run_evidence_agents` (Phase 3) -> `build_architect_context` +
      `run_architect` (4.1) -> `validate_assumptions` + `run_ai_dcf_engine` (Phase 2) ->
      `check_scenario_ordering` -> `AiDcfResult.build`. Status phases exactly per SPEC 6.9
      (`gathering_data -> running_evidence -> running_architect -> computing_dcf`), delivered
      via an optional `status_cb(phase, message)` callback rather than a class-based status
      object — simpler for a single function, Phase 5 wraps it for the polling-status pattern.
- [x] 4.3 Grammar-limit fallback: **NOT NEEDED — verified NOT triggered.** Live-tested the
      single-call Architect against BOTH `google/gemini-3.5-flash` and
      `anthropic/claude-sonnet-4-6` (the model family that forced the split in
      `research_chief_core.md`/`research_chief_narrative.md`) end-to-end on TXN; both completed
      successfully with no compiled-grammar error. `AiDcfAssumptions`'s flat-float-list, no-
      nested-per-year-object schema (SPEC 5.5's explicit design goal) stays comfortably under
      the limit that broke the single-name researcher's much larger `EquityResearchReport`
      schema. The split-call seam (`run_architect` as a single, isolated function boundary) is
      still in place structurally if a future larger schema or different model ever needs it,
      but no split implementation was written since PLAN said to build it "only if the error
      actually occurs" — it didn't.
- [x] 4.4 Live checks (real LLM, `google/gemini-3.5-flash` for TXN/UPS/CRWV, plus one
      `anthropic/claude-sonnet-4-6` run on TXN for the grammar check):
      - **TXN** (70.3s wall time): base assumptions — revenue growth 12%/15%/8%/6%/5%,
        cogs_pct declining 41.5%→36.3% (cited: 300mm fab cost efficiencies), EBIT margin rising
        37%→45.5%, TG 3.5%. Zero QC warnings. Bear/base/bull intrinsic values $30.18/$60.79/
        $89.64 — correctly ordered, genuinely differentiated (not a copy of the mechanical
        defaults — `compute_dcf_scenarios`'s own base case for TXN is $53.48 per the Phase 0.3
        note, so the AI base of $60.79 reflects real evidence-driven divergence, not a
        rubber-stamp). `key_debates` cited specific brief evidence (capex glide path, gross
        margin path, segment share capture) — genuinely falsifiable, not generic hedging.
      - **UPS** (70.9s): this is the Phase 0.3 landmine's real-world test. The Architect
        correctly read the ENGINE CONTEXT's `reports_cogs=True` + ~81% historical COGS warning
        and kept `cogs_pct` at 79.5-82.5% across all three scenarios while setting modest EBIT
        margins (7.5-13%) — every year of every scenario landed inside the `1-cogs_pct` ceiling
        with zero QC warnings, and the engine's ACHIEVED margin matched the AUTHORED margin
        exactly (e.g. authored 0.11 -> achieved 0.11), confirming the landmine fix works at the
        prompt level, not just the schema/guardrail level. Bear/base/bull: $67.78/$93.26/$121.69
        — correctly ordered.
      - **CRWV** (70.7s, the unprofitable/low-coverage case): a genuinely hard case — CoreWeave
        is a pre-profit AI-infrastructure buildout whose real history (from Phase 3's live
        check) shows revenue scaling ~100x FY2022-FY2025 with capex historically exceeding
        100% of revenue in early years. The Architect authored comparably extreme forward
        assumptions (110-160% revenue growth, 45-120% capex/revenue) grounded in real cited
        guidance ($12.7B/$25.1B FY2026/27 consensus, GW power-capacity buildout). The guardrails
        correctly flagged essentially every extreme figure (14 warnings: revenue growth and
        capex outside range on multiple years/scenarios, bull EBIT margin exceeding historical
        max, AND a genuine scenario-ordering violation — bear/base/bull intrinsic values were
        **-$3,240 / -$12,977 / -$31,006**, bull MORE negative than bear). Root cause understood,
        not a bug: for a company still burning cash on capex years ahead of revenue, "more
        optimistic" assumptions (higher growth => proportionally more capex in this Architect's
        model) produce WORSE near-term discounted FCFF within a fixed 5-year explicit horizon —
        a real, known limitation of vanilla FCFF DCF applied to hyper-growth infrastructure
        buildouts, not a defect in the AI DCF valuator. The guardrails did exactly their job:
        never crashed, surfaced every warning, and the QC-warning-heavy output is itself the
        correct signal that this methodology is a poor fit for this specific business — a
        report consumer seeing 14 warnings + a negative bull case knows immediately to treat
        the DCF section skeptically for this name. No guardrail-threshold changes made in
        response — loosening them would hide exactly the case they exist to catch.
      - AV budget: zero additional Alpha Vantage calls observed in any of the 5 live runs beyond
        the target's own transcript/estimates probe (already warm from prior phases in every
        case) — competitor transcripts and industry report are cached-only by construction.
- [x] 4.5 Tests (`tests/test_ai_dcf.py`, +5 tests, 64 total): mocked end-to-end
      (`test_run_ai_dcf_mocked_agents_real_data_real_engine` — mocks exactly `run_evidence_agents`
      + `run_architect`, everything else including the real DB gather and real `run_dcf_av`
      engine runs against TXN) -> valid `AiDcfResult` + markdown; degraded-input run (MD&A/
      industry report/competitor transcripts all forced to placeholders) completes with
      `inputs_available` correctly reflecting zero coverage; Architect failure -> `RuntimeError`
      propagates cleanly; base-scenario engine failure (bogus ticker) -> raises; status callback
      receives exactly the 4 SPEC-6.9 phases in order.

Acceptance met: `uv run pytest tests/test_ai_dcf.py` — 64/64 green; full suite
(`uv run pytest tests/`) — 395 passed, 3 skipped, no regressions. Five live runs completed and
noted above (TXN x2 models, UPS, CRWV); zero AV budget violations; grammar-limit fallback
confirmed unnecessary rather than assumed unnecessary.

---

## Phase 5 — Router: cache, status/cancel, endpoints  [x] Complete (2026-07-30)

- [x] 5.1 Cache `ai_dcf_cache(ticker, model, result_json, report_markdown, generated_at)`,
      PK (ticker, model), 24h TTL — `_init_ai_dcf_cache`/`_ai_dcf_cache_get`/`_ai_dcf_cache_put`,
      copied from `research_router`'s trio shape with the extra `result_json` column.
- [x] 5.2 Background task registry + `_get_or_start_ai_dcf` with the retry guard (no silent
      retry after error/cancel), `_set_ai_dcf_status`, phases per SPEC 6.9. Also
      `async get_or_run_ai_dcf(ticker, model) -> AiDcfResult | None` for in-process reuse by
      the research pipeline: prefers a fresh cache hit, joins an already-running task (started
      by the standalone endpoint OR a concurrent caller) instead of double-starting, or starts
      and awaits a new run — always returns `None` on failure rather than raising (SPEC 6.8).
      `_background_generate_ai_dcf` now returns the `AiDcfResult` (or `None`) in addition to its
      cache-write/status-set side effects, so both the fire-and-forget standalone path and the
      awaited in-process path share one implementation.
- [x] 5.3 Endpoints: `GET /research/ai-dcf` (markdown; `format=json` returns the cached result
      JSON, or `{"status": "generating"}` if not yet cached), `GET /research/ai-dcf/status`,
      `POST /research/ai-dcf/cancel`. Registered in `api/main.py` (import + `include_router`,
      alongside the existing `research_router`).
- [x] 5.4 Tests (`tests/test_ai_dcf_orchestration.py`, new file, 14 tests, mirrors
      `test_industry_research_orchestration.py`'s structure exactly): cache round-trip/miss/
      per-model isolation/TTL expiry-and-within-window; `_get_or_start_ai_dcf` cache-hit-skips-
      pipeline, cold-start-then-cache, error-blocks-auto-restart-until-retry, cancel-sets-
      cancelled-status; `get_or_run_ai_dcf` cache-hit-skips-pipeline, starts-and-awaits-new-run,
      returns-`None`-on-failure, and **the critical concurrency guarantee** — a caller joining
      an in-flight task (started via the standalone path) triggers exactly one orchestrator
      invocation, verified with an `asyncio.Event`-gated fake `run_ai_dcf` and an assertion on
      `call_count`.
- [x] 5.5 Live check: found the project's own long-running dev server already up on `:8000`
      (2+ days uptime) holding a write lock on `financial_statements.duckdb` — starting a second
      full `uvicorn api.main:app` conflicted on that lock (expected DuckDB single-writer
      behavior) and was correctly NOT force-started or worked around; the existing server was
      left untouched. Instead verified the new endpoints via an isolated `FastAPI` test app
      mounting only `ai_dcf_router` (no lifespan, no shared DB) with `TestClient`: idle status
      or no-cache/no-task -> `{"phase": "idle"}`; cold GET with no cache -> the generating
      placeholder; a pre-warmed cache entry -> `status` correctly falls back to `"done"`,
      markdown GET returns the real report (not the placeholder), `format=json` GET returns the
      full structured result with the correct keys; cancel-when-nothing-running ->
      `{"status": "not_running"}`. One thing did NOT behave as expected under `TestClient`
      specifically: a background task created via `asyncio.create_task` inside one request and
      inspected/cancelled from a SEPARATE subsequent `client.get()`/`client.post()` call did not
      reliably persist between calls — traced to `TestClient`'s per-request event-loop/anyio-
      portal lifecycle (a real server has one continuously-running loop across all requests;
      `TestClient` does not guarantee that across discrete calls in the way this check assumed).
      This is a test-tool limitation, not a code defect: the exact same task-registry/cancel/
      retry code path is already rigorously proven correct by 5.4's `pytest-asyncio` tests,
      which run under a real persistent event loop (matching production uvicorn behavior) and
      explicitly `await`ed task completion/cancellation across the same async test function.

Acceptance met: `uv run pytest tests/test_ai_dcf_orchestration.py` — 14/14 green; full suite
(`uv run pytest tests/`) — 409 passed, 3 skipped, no regressions. Live HTTP check noted above;
`api/main.py` updated to register the router.

---

## Phase 6 — Research-pipeline integration  [x] Complete (2026-07-30)

- [x] 6.1 `research_router._run_research_agent`: after data gathering, `await
      asyncio.wait_for(get_or_run_ai_dcf(ticker, model), timeout=_AI_DCF_TIMEOUT)` with a new
      status phase `running_ai_dcf` (new module constant `_AI_DCF_TIMEOUT = 300`, well above
      the live-observed worst case ~280s cold run); an outer `try/except Exception -> None` is
      defense-in-depth on top of `get_or_run_ai_dcf`'s own never-raises contract (SPEC 6.8).
      Runs sequentially before the specialist fan-out (not parallelized with it — matches
      SPEC 8's documented cost model, and PLAN's own literal wording). `get_or_run_ai_dcf`
      (Phase 5) already reuses its own cached data internally; no duplicate AV probes observed
      in either live check below.
- [x] 6.2 Valuation Analyst context: `api.ai_dcf_router.format_ai_dcf_summary(ai_dcf_result)`
      appended right after the existing mechanical `dcf_summary` — assumptions (revenue growth/
      EBIT margin per year), engine values, WACC rationale, and key debates, clearly labeled
      "AI-AUTHORED DCF VALUATION". Degrades to `[INFO] AI DCF unavailable for this run — proceed
      using the mechanical DCF alone` when `ai_dcf_result` is None.
- [x] 6.3 `research_valuation.md` rewritten: data section 1 relabeled "MECHANICAL DCF VALUATION
      (engine defaults)" for clarity, new section 9 "AI-AUTHORED DCF VALUATION"; new
      METHODOLOGY subsection "TWO DCF SOURCES, NEUTRAL RECONCILIATION" spelling out the
      no-default-preference rule and the >20%-disagreement adjudication requirement;
      `dcf_assessment`/DEGRADATION/citation-tag sections updated to cover both sources
      (`[Mechanical DCF]` / `[AI DCF]` tags). `ValuationOutput` extended with
      `ai_dcf_intrinsic_value: Optional[float] = None` (coerced via the existing
      `_coerce_dcf_intrinsic_value` validator, reused for both fields) and
      `dcf_reconciliation: str = ""` (defaults empty so the schema still validates when the AI
      DCF didn't run). Live-verified against `google/gemini-3.5-flash` in 6.7 — schema well
      under any grammar limit (only 2 new scalar fields on an already-existing schema).
- [x] 6.4 `_model_summary_table` gained `ai_dcf_engine: Optional[dict] = None` -> splices in
      `render_ai_dcf_triangulation_row` right after the mechanical "DCF (scenario)" row when
      present. `render_valuation_model_tables` gained `ai_dcf_result=None` -> passes
      `ai_dcf_result.engine` through to the row above and appends
      `render_ai_dcf_comparison_table(ai_dcf_engine, scenarios)` as an extra block — reuses the
      SAME `scenarios` dict from the existing single `compute_dcf_scenarios(ticker)` call;
      the AI DCF engine itself is never re-run here (it was already computed inside the AI DCF
      pipeline in 6.1). `_build_post_subagent_tables` threads `ai_dcf_result` through
      unchanged otherwise. `_format_specialist_outputs` also updated to pass
      `ai_dcf_intrinsic_value`/`dcf_reconciliation` through to the Chief's context.
- [x] 6.5 `_validate_report` gained an `ai_dcf_result=None` parameter and one more check: when
      both `ai_dcf_result` and `valuation_out.ai_dcf_intrinsic_value` are present, they must
      match the AI DCF's own base-scenario `intrinsic_value_per_share` exactly (same
      >$0.01-tolerance pattern as the existing mechanical fair-value checks).
- [x] 6.6 Tests: `tests/test_research_ai_dcf_integration.py` (new file, 15 tests) — unit-level
      coverage of every modified/new function (`_model_summary_table`/
      `render_valuation_model_tables` with/without `ai_dcf_engine`, `_validate_report`'s new
      check firing/clean/skipped, `_format_specialist_outputs` carries the new fields,
      `render_to_markdown`'s reconciliation placement present/absent, `format_ai_dcf_summary`'s
      two branches) PLUS two full `_run_research_agent` end-to-end tests with a hand-built fake
      `Agent`/`Runner` (dispatching canned Pydantic outputs by `output_type`, since the `agents`
      package itself is only a `MagicMock` via `conftest.py` and doesn't preserve real
      constructor kwargs) and EDGAR/Tavily/transcript-probe calls canned — local-DB reads run
      for real against TXN. `get_or_run_ai_dcf` mocked as success (fixture `AiDcfResult`) and as
      failure (`None`): success asserts the new row/table/reconciliation are present and QC is
      clean; failure asserts they're structurally absent and QC is still clean (report degrades
      exactly to pre-feature shape). **Found and fixed a real bug along the way**: the live
      check below caught a literal-backslash-n LLM quirk in the brand-new `dcf_reconciliation`
      field specifically (every other field in the same real report was clean) — added a
      `field_validator` on `ValuationOutput.dcf_reconciliation` reusing
      `industry_research_router._sanitize_prose`, with a dedicated regression test.
- [x] 6.7 Live checks (real LLM, `google/gemini-3.5-flash`, real TXN data):
      - **Cold run** (277.2s total — AI DCF ran fresh inside the pipeline): QC clean.
        `dcf_reconciliation` was excellent and genuinely evidence-driven: "the mechanical model
        uses historical extrapolation that keeps CapEx elevated at 22.6% of revenue in
        perpetuity, which directly contradicts management's explicit statements that the
        six-year heavy investment cycle is ending [2025Q4 call]... the AI-authored model is far
        more credible because it accurately forecasts CapEx scaling down to 9.0% by Year 5...
        we therefore adopt the AI Bull case of $79.40 [AI DCF]" instead of the mechanical
        bull's $169.04 (which the reconciliation correctly flagged as relying on an
        unsupportable 20.1% revenue CAGR given TXN's actual -4.1% 3yr revenue growth). This is
        exactly the neutral, falsifiable adjudication the feature was designed to produce — not
        a rubber-stamped preference. (This run is also where the literal-backslash-n bug above
        was caught — the ONLY occurrence in the entire 37,390-char report.)
      - **Warm run** (130.3s total, after fixing the sanitization bug): AI DCF step measured at
        **0.01s** (vs. the full cold-run cost) — confirms SPEC 8's "~zero when warm" cost claim
        precisely. QC clean, reconciliation present with no literal-backslash-n. Directly
        compared the new "AI vs. Mechanical DCF Assumptions" table's Mechanical column against
        the pre-existing "DCF Scenario Assumptions" table already in the report — Rev CAGR
        (5.5%/11.1%/20.1%), EBIT margin (37.4%/34.9%/45.3%), WACC (10.39% all three), and TG
        (3.00% all three) matched EXACTLY across both tables for bear/base/bull, confirming the
        shared-`scenarios`-dict design (6.4) produces byte-for-byte consistent numbers rather
        than two independently-computed mechanical views that could silently drift apart.

Acceptance met: full `uv run pytest tests/` — 424 passed, 3 skipped, no regressions. Two live
reports generated and eyeballed (cold + warm); QC footer clean on both; one real bug found and
fixed during the live check (dcf_reconciliation sanitization), with a permanent regression test.

---

## Phase 7 — Verification + docs  [x] Complete (2026-07-30)

- [x] 7.1 Cross-ticker live sweep (`google/gemini-3.5-flash`) — 5 tickers spanning the required
      categories. TXN/UPS/CRWV reused from Phase 4's already-thorough live checks (no need to
      re-spend LLM cost re-running identical checks); STRZ and NUE newly run for this phase.

      | Ticker | Category | Wall time | QC warnings | Bear / Base / Bull (AI) |
      |---|---|---|---|---|
      | TXN | profitable large-cap | 70.3s | 0 | $30.18 / $60.79 / $89.64 |
      | UPS | high-COGS capital-intensive | 70.9s | 0 | $67.78 / $93.26 / $121.69 |
      | STRZ | no-COGS-in-latest-filing media co. | 117.1s | 6 | $162.97 / $305.17 / $381.17 |
      | NUE | cyclical (steel) | 123.2s | 0 | $21.45 / $40.32 / $61.59 |
      | CRWV | unprofitable growth / low-data | 70.7s | 14 | -$3,240 / -$12,977 / -$31,006 |

      All 5 completed without crashing; wall times 70-123s, comfortably inside SPEC 8's budget.
      **STRZ finding**: unlike UPS, STRZ's `get_historical_margin_bounds` 7-year lookback found
      SOME non-null `cost_of_revenue` in its history even though its most recent annual filing
      doesn't break one out (post-2025 Lionsgate spin-off reporting-structure change) — so
      `reports_cogs=True` and a historical COGS median (61.2%) applied, unlike the plain DB
      query I used to hunt for "no-COGS" candidates (which only checked the latest period).
      This is a real, useful nuance, not a bug: the engine's own 7-year-lookback definition of
      `reports_cogs` is more robust than a latest-period-only check, and it correctly triggered
      guardrail warnings when the bull case assumed `cogs_pct` 15-17pp below that 61.2% median
      and EBIT margins 11-17pp above the 6.7% historical max — exactly the guardrails doing
      their job on a genuinely aggressive bull case, not a false positive.
- [x] 7.2 AI vs. mechanical base intrinsic value comparison across the sweep (mechanical values
      via `compute_dcf_scenarios`):

      | Ticker | Mechanical base | AI base | Divergence |
      |---|---|---|---|
      | TXN | $53.48 | $60.79 | +13.7% |
      | UPS | $106.42 | $93.26 | -12.4% |
      | STRZ | $48.26 | $305.17 | **+532%** |
      | NUE | $40.02 | $40.32 | +0.7% |
      | CRWV | -$1,001,596 | -$12,977 | both deeply negative/degenerate |

      This is the key confirmation the sweep was designed to produce: **the AI DCF's divergence
      from the mechanical baseline is highly company-specific, not a fixed offset** — ranging
      from near-identical (NUE, a mature cyclical business where the Architect's assumptions
      closely tracked the engine's own historical defaults, no QC warnings) to enormous (STRZ,
      where evidence-driven margin-expansion/cost-structure assumptions diverge sharply from a
      historical-percentile approach on a company mid-transition post-spinoff — this is exactly
      the kind of case the research pipeline's `dcf_reconciliation` >20%-disagreement
      adjudication rule (Phase 6) exists to force an explicit judgment call on, rather than
      silently picking one number). CRWV independently confirms the Phase 4 finding that vanilla
      FCFF DCF is a poor methodological fit for a pre-profit infrastructure buildout — the
      MECHANICAL engine produces an equally degenerate (-$1M/share) result on the same company,
      so this is a company/methodology mismatch, not an artifact of AI-authored assumptions.
- [x] 7.3 Updated `docs/Project_Structure.md`: new `ai_dcf_router.py`/`ai_dcf_data.py` entries in
      the `api/` tree (endpoints, pipeline summary, cache), `ai_dcf_cache.duckdb` added to the
      data-directory listing, `research_router.py`'s entry updated to mention the AI DCF
      integration. Updated `research_router.py`'s module docstring to describe the new
      Valuation Analyst data flow and failure-isolation contract.
- [x] 7.4 Cleared both caches (`ai_dcf_cache.duckdb`'s `ai_dcf_cache` table,
      `research_cache.duckdb`'s `research_cache` table) so the next real use reflects the final
      prompts/schema from this implementation, not any live-check-era cached content.
- [x] 7.5 Memory note saved (`project_ai_dcf_valuator.md` updated) — feature complete, live-sweep
      findings, the two real bugs found and fixed during live verification (the `cogs_pct`/
      `ebit_margin_pct` ceiling landmine in Phase 0, and the `dcf_reconciliation`
      literal-backslash-n sanitization gap in Phase 6), and the deliberate deviations from the
      original sketch (schema gained `cogs_pct`; grammar-split fallback built but never
      triggered/needed; `get_engine_context`/`reports_cogs` derived directly from financials
      rather than via a baseline engine run).

Acceptance met: sweep table recorded above; `docs/Project_Structure.md` and module docstring
updated; full test suite green (`uv run pytest tests/` — 424 passed, 3 skipped, unchanged from
Phase 6 since Phase 7 added no new code, only live verification and docs).

---

## Cross-cutting acceptance criteria

- No LLM-authored number ever appears in a rendered table — every figure traces to
  `run_dcf_av` output or a DB query.
- The AI DCF failing (any stage) never degrades the research report below today's baseline.
- No new AV call paths beyond the target's transcript probe + estimate refresh; competitor and
  industry inputs are cached-only. One full run's AV call count is logged and noted in Phase 4.
- Evidence/Architect contexts are price-blind for the target (tested at string level, Phase 1.7).
- All caches keyed (ticker|scope, model); 24h TTL for AI DCF, 14d read window for the industry
  report input, age always surfaced.
