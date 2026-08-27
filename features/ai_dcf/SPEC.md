# Agentic AI DCF Valuator — Feature Specification

Status: Approved for planning (design decisions confirmed with the user 2026-07-30).
Target: a coding agent turns this into working code via the companion PLAN.md.

## 1. Goal

An agentic AI DCF Valuator ("AI DCF") that **authors its own DCF assumptions** — instead of the
mechanical Alpha-Vantage-default assumptions used by the existing engine defaults — grounded in:

- historic financials (multi-year revenue growth, margin decomposition, capex, working capital),
- industry trends (Industry Researcher output where available, plus a purpose-built lite digest),
- direct competitor information (peer fundamentals, cached competitor transcripts),
- MD&A history (the multi-year `mda_filings.duckdb` store, currently unused by the researcher),
- the project's existing databases (no new domain data sources).

The LLM decides the assumptions; the **deterministic DCF engine computes the valuation**
(`dcf.run_dcf_av` with `UserOverrides`/`YearOverride` — the engine already accepts per-year
revenue growth, EBIT margin, capex %, plus terminal growth and WACC-input overrides). The LLM
never performs valuation arithmetic ("LLM writes assumptions and prose, Python writes the
numbers" — same discipline as the rest of the researcher stack).

The result is a **second, independent DCF valuation source** for the single-name AI Researcher,
alongside the existing mechanical bear/base/bull scenarios.

## 2. Confirmed scope decisions

| Decision | Choice |
|---|---|
| Internal architecture | **Evidence team + DCF Architect**: 3 parallel evidence agents (Fundamentals Historian, Industry & Competitors Analyst, Guidance & MD&A Analyst) each produce a structured evidence brief; one senior DCF Architect agent (finance-expert persona, experienced in equities valuation) converts the briefs into per-year, per-scenario DCF assumptions with cited justifications |
| Industry input | **Always** run a lite Industry Context input (sector_stats at industry grain + peer fundamentals + Tavily industry search) as part of the Industry & Competitors evidence agent; **additionally** include the cached full Industry Researcher report when one exists for the ticker's industry and is **≤ 14 days old** (read directly from `industry_research_cache.duckdb`, bypassing the router's 24h TTL), **age-tagged** in citations (e.g. `[Industry report, 12d old]`). Never trigger the full industry fan-out implicitly |
| Competitor transcripts | Cached-only: include up to 4 quarters of earnings transcripts for the top 3-5 industry peers **only if already cached** in `earnings_transcripts.duckdb` — zero new AV calls for competitors |
| Integration with AI Researcher | **Second source (Option 1)**: both the mechanical bear/base/bull DCF and the AI DCF feed the Valuation Analyst, whose prompt is extended to **reconcile** them with a **neutral preference rule** — it must state which DCF anchored its `fair_value_base` and why. The report gains an "DCF (AI-authored)" row in the fair-value triangulation table and an AI-vs-mechanical assumptions comparison table (both rendered deterministically in Python) |
| Exposure | **Standalone + report (Option A)**: own endpoints (`/research/ai-dcf` + status/cancel), own cache (`ai_dcf_cache.duckdb`, keyed ticker+model, **24h TTL**). The research pipeline calls the same get-or-start function, so report generation reuses a fresh cached AI DCF and vice versa. Frontend panel deferred |
| Scenarios | The Architect authors **bear / base / bull** — three full assumption sets, each run through the engine |
| Price blindness | The evidence agents and Architect never see the current stock price, current market cap, current multiples, analyst price targets, or the mechanical engine's assumption values (see 6.6) |

## 3. Non-goals

- No changes to the deterministic DCF engine's math (`dcf/model.py`, `dcf/wacc.py`,
  `dcf/forecaster.py`). The AI DCF is a new *caller* of the engine via overrides.
- No replacement of the mechanical scenarios — they remain in the pipeline as the naive baseline
  the AI DCF is audited against.
- No frontend work in this feature (the report's markdown rendering is the v1 UI; a DCF-viewer
  panel is a possible follow-up).
- No new external data sources — Tavily, EDGAR-derived MD&A store, AV transcripts/estimates, and
  the project DuckDBs only.
- Not a validated quant signal; no performance claims.

## 4. Pipeline

```
get-or-start (cache ai_dcf_cache.duckdb, keyed ticker+model, 24h TTL)
        |
   gather data (parallel, thread pool, all sanitized — see 6.6):
     - fundamentals history (10yr annual where available: revenue, margin
       decomposition COGS/SGA/R&D/other-opex, capex %, D&A %, NWC days,
       share count, FCF) — av_financials.duckdb
     - MD&A history (last 3 annual 10-K MD&As + latest 10-Q, truncated
       per filing) — mda_filings.duckdb
     - earnings transcripts (last 4 quarters, cached + newest-quarter AV
       probe, reuse get_earnings_trend_summary logic)
     - consensus estimates (earnings_estimates, forward EPS/revenue)
     - peer fundamentals (_peer_df pattern, industry grain)
     - sector_stats industry aggregates (group_type='industry' only)
     - cached Industry Researcher report if <= 14d old (age computed)
     - cached competitor transcripts (top 3-5 peers, cached-only)
     - Tavily industry/TAM search (reuse _tavily_search)
        |
STAGE 1 — EVIDENCE (3 sub-agents, parallel):
     - Fundamentals Historian     -> FundamentalsBrief
     - Industry & Competitors     -> IndustryBrief
     - Guidance & MD&A Analyst    -> GuidanceBrief
     each: structured brief with numeric ranges + inline source tags
        |
STAGE 2 — DCF ARCHITECT (1 call; split per scenario only if the
     structured-output grammar limit forces it — see 6.7):
     input : the 3 briefs + engine-context facts (risk-free rate, raw beta,
             historical effective tax rate, share-count trend — no price)
     output: AiDcfAssumptions — per scenario (bear/base/bull): 5 years of
             {revenue_growth, ebit_margin_pct, capex_pct_revenue} +
             terminal_growth_rate + optional beta/tax/cost-of-debt override,
             each with a one-line justification citing brief evidence
        |
   Python: guardrail validation (6.5) -> map to UserOverrides ->
           run_dcf_av x3 -> AiDcfResult (assumptions + justifications +
           engine outputs + QC warnings) -> JSON + markdown, cached
```

## 5. Architecture

### 5.1 New files

| File | Purpose |
|---|---|
| `api/ai_dcf_data.py` | Data-gathering layer: evidence-context builders, industry-report cache lookup (14d window), sanitization. All synchronous, thread-safe, read-only DB access |
| `api/ai_dcf_router.py` | Orchestration (evidence fan-out, Architect, engine runs), guardrails, `AiDcfResult`, markdown renderer, cache, status/cancel, endpoints |
| `api/prompts/ai_dcf_fundamentals.md` | Fundamentals Historian evidence agent |
| `api/prompts/ai_dcf_industry.md` | Industry & Competitors evidence agent |
| `api/prompts/ai_dcf_guidance.md` | Guidance & MD&A evidence agent |
| `api/prompts/ai_dcf_architect.md` | DCF Architect |
| `tests/test_ai_dcf.py` | Data-layer, guardrail, mapping, renderer, and mocked-pipeline tests |

Register the router in `api/main.py`. Update `docs/Project_Structure.md`.

### 5.2 Modified files (research-pipeline integration)

| File | Change |
|---|---|
| `api/research_router.py` | Data-gathering adds the AI DCF get-or-start (new status phase `running_ai_dcf` between `gathering_data` and `running_specialists`); Valuation Analyst context gains the AI DCF summary; `ValuationOutput` gains `ai_dcf_intrinsic_value: Optional[float]` (echo) and `dcf_reconciliation: str`; `_model_summary_table` gains a "DCF (AI-authored)" row; new deterministic AI-vs-mechanical assumptions comparison table in the Valuation Model Detail block; `_validate_report` extended (see 6.8) |
| `api/prompts/research_valuation.md` | New data section (AI-AUTHORED DCF) + reconciliation instructions (neutral preference rule) |

### 5.3 Reused, do not reimplement

- `dcf.run_dcf_av` + `dcf.assumptions.UserOverrides`/`YearOverride` — the engine and its override
  surface. Note: `YearOverride.ebit_margin_pct` overrides margins via the other-opex residual;
  `UserOverrides.terminal_growth_rate`, `beta`, `tax_rate_override`, `cost_of_debt_override` are
  the WACC/terminal levers. The engine handles no-COGS service companies already
  (memory `project_dcf_no_cogs_companies`) — the override path must not disturb that.
- `api/valuation_data.compute_dcf_scenarios` — the mechanical bear/base/bull baseline (unchanged);
  reused for the comparison table.
- `historic_fundamentals/mda.py` — `open_db`, `get_cached_mda` for MD&A history.
- `historic_fundamentals/earnings_transcripts.py` — transcript cache + newest-quarter probe.
- `research_router.py` scaffolding to copy structurally: `_md_table`, `_tavily_search`, `_peer_df`
  pattern, DuckDB cache trio, `_background_tasks`/`_task_status`/`_set_status`, `_get_or_start`
  retry guard, `/status` + `/cancel` endpoint shapes, `_run_subagent` + `asyncio.wait_for`
  timeout pattern, `_MODEL_OPTIONS`, `_coerce_optional_float`.
- `api/industry_data.scope_key` — maps industry name -> cache key for the report lookup.

### 5.4 Data layer (`api/ai_dcf_data.py`)

| Function | Returns |
|---|---|
| `get_fundamentals_history(ticker)` | Text block: up to 10 annual years of revenue (+growth), gross/operating/net margin, COGS/SGA/R&D/other-opex as % of revenue, capex % of revenue, D&A % of revenue, NWC days (DSO/DPO/DIO), FCF, diluted share count trend. From `av_financials.duckdb` |
| `get_mda_history(ticker, n_annual=3)` | Text block: last `n_annual` 10-K MD&As + the latest 10-Q MD&A from `mda_filings.duckdb`, each truncated to a per-filing char cap, labeled with form + fiscal period. Degrades to whatever is cached (possibly nothing) |
| `get_industry_report(ticker, max_age_days=14)` | `(report_markdown, age_days) | None`: ticker -> `company_overview.industry` -> `scope_key(industry)` -> freshest row across models in `industry_research_cache.duckdb` within the window. Ignores `custom:*` rows. Returns None past the window or when no industry classification exists |
| `get_competitor_transcripts(ticker, max_peers=5, n_quarters=4)` | Text block: cached-only transcripts for the top peers by market cap from `_peer_df`-style query. **No AV fetches.** Peers with nothing cached are skipped with a note |
| `get_engine_context(ticker)` | Text block for the Architect: risk-free rate, raw 5yr/2yr beta (from `features/beta`), historical effective tax rate, debt/equity book context, diluted shares trend, **`reports_cogs` flag + 7yr-median historical COGS% of revenue** (derived directly from the income statement — same test `dcf/forecaster.py` uses — not a full engine run; see 6.2b) — the engine-input facts the Architect may reasonably override. **No market cap, no price** |
| Reused from `research_router` / `industry_data` | financial summary, peer table, transcripts, estimates, sector_stats aggregates, Tavily search |

All degrade gracefully to an `[INFO]`/`[ERROR]` placeholder string; a missing input never fails
the run — the corresponding evidence agent is told the input is unavailable.

### 5.5 Pydantic output schemas (sketch)

Evidence briefs (Stage 1) — each field is short structured text with inline source tags:

- `FundamentalsBrief`: `growth_history`, `margin_history`, `capital_intensity`,
  `working_capital`, `cyclicality_assessment`, `sustainable_ranges` (explicit numeric ranges the
  history supports: revenue growth band, EBIT margin band, capex band).
- `IndustryBrief`: `industry_growth_outlook`, `pricing_margin_direction`, `capex_cycle`,
  `competitive_position` (share gainer/holder/loser vs. named peers), `terminal_context`
  (long-run growth vs. GDP argument), `used_industry_report: bool`,
  `industry_report_age_days: Optional[int]`.
- `GuidanceBrief`: `explicit_guidance` (quoted revenue/margin/capex guidance with quarter tags),
  `strategy_shifts`, `demand_inflections`, `guidance_credibility` (guidance vs. subsequent
  actuals, from beat/miss + MD&A year-over-year comparison), `consensus_view`.

Architect (Stage 2):

- `ScenarioAssumptions`: `revenue_growth: list[float]` (len 5, decimals),
  `cogs_pct: list[float]` (len 5, decimal % of revenue — see the gross-margin-ceiling finding
  in 6.2b; only meaningful for `reports_cogs=True` targets), `ebit_margin_pct: list[float]`
  (len 5), `capex_pct_revenue: list[float]` (len 5), `terminal_growth_rate: float`,
  `rationale: str` (the scenario's story in 2-4 bullets with source tags).
- `AiDcfAssumptions`: `bear/base/bull: ScenarioAssumptions`,
  `beta_override: Optional[float]`, `tax_rate_override: Optional[float]`,
  `cost_of_debt_override: Optional[float]`, `wacc_rationale: str`,
  `key_debates: list[str]` (the 2-4 assumption calls that most drive the valuation and why they
  were made this way — the auditable core of the output).

Keep the Architect schema compact (flat float lists, no nested per-year objects) to stay under
the Anthropic compiled-grammar limit; the split fallback is one call per scenario (6.7).

Apply `_coerce_optional_float`-style `field_validator(mode="before")` coercion on all numeric
fields.

### 5.6 `AiDcfResult` (Python-assembled, cached as JSON + markdown)

Per scenario: the authored assumptions, the mapped `UserOverrides`, and the engine's
`DcfResult` extract (intrinsic value/share, WACC detail, 5yr FCFF table, terminal value %).
Plus: the three briefs, `key_debates`, guardrail QC warnings, generation metadata (model,
timestamps, which optional inputs were present — industry report + age, MD&A years found,
competitor transcripts found).

## 6. Design rules

### 6.1 Deterministic valuation math

The Architect's numbers are *inputs*; every valuation figure (intrinsic value, FCFF, WACC,
terminal value) comes out of `run_dcf_av`. The markdown renderer takes all numbers from
`AiDcfResult`'s engine extracts, never from LLM prose.

### 6.2 Mapping assumptions -> UserOverrides

Per scenario: `years={i: YearOverride(revenue_growth=g[i-1], cogs_pct=cg[i-1] (only if the
target reports_cogs — see 6.2b), ebit_margin_pct=m[i-1], capex_pct_revenue=c[i-1]) for i in
1..5}`, `terminal_growth_rate`, plus `beta`, `tax_rate_override`, `cost_of_debt_override` when
authored. `default_ebit_margin_pct` is left None (engine fills its median default for any year
the Architect somehow leaves uncovered — should not happen with the fixed-length lists).

### 6.2b Landmine — `ebit_margin_pct` alone is capped by trailing COGS% (Phase 0 finding, live-
verified 2026-07-30)

`dcf/model.py`'s EBIT-margin control block (~line 765) achieves a requested `ebit_margin_pct`
by using `other_opex_pct` as a plug: `other_opex = 1 - cogs_pct - sga_pct - rd_pct - ebit_m`.
When that slack is negative (target margin too rich for the *unoverridden* `cogs_pct` to
support even after SG&A/R&D are floored at zero), the engine silently settles for
`1 - cogs_pct - 0 - 0 - 0` instead of the requested margin — **no exception, no warning, just a
different number than what was authored.**

Verified live: for UPS (historical `cogs_pct` ≈ 0.813, `reports_cogs=True`), requesting
`ebit_margin_pct=0.35` alone silently produced 0.187 (= `1 - 0.813`) instead. Requesting
`ebit_margin_pct=0.30` together with `cogs_pct=0.55` produced exactly 0.300 — confirms
`cogs_pct` is applied first via `merge_overrides` (`dcf/forecaster.py:463-478`), before the
EBIT-margin plug runs, so setting both together reliably achieves the target.

For `reports_cogs=False` targets (no COGS breakout in AV data — `forecaster.py`'s
`cogs_flat = ... if reports_cogs else 0.0`), `cogs_pct` is pinned at 0 regardless, so
`ebit_margin_pct` alone has the engine's full range with no ceiling — this is the case the
original (pre-audit) SPEC design implicitly assumed for ALL companies. It only holds for
no-COGS companies.

**Resolution**: `ScenarioAssumptions` gained `cogs_pct` (6.2). `get_engine_context` (5.4) must
expose `reports_cogs` (derived directly from the income statement's cost-of-revenue/gross-profit
presence — the same test `dcf/forecaster.py` uses — not a full `run_dcf_av` call) and the
historical COGS% so the Architect prompt
can explain: "if `reports_cogs` is true and you want EBIT margin to move purely via SG&A/R&D
leverage, hold `cogs_pct` at the historical level; if your evidence supports gross-margin
change (mix shift, pricing power, input costs), set `cogs_pct` to reflect it — otherwise your
`ebit_margin_pct` target may be silently capped." `validate_assumptions` (6.5) adds a guardrail:
for `reports_cogs=True` scenarios, if `ebit_margin_pct[i] > 1 - cogs_pct[i] - 1e-6` for any year
(i.e. the pair is internally inconsistent — margin claims more than the authored COGS leaves
room for), warn and note the engine will floor SG&A/R&D rather than crash.

### 6.3 Industry-report freshness

The 24h TTL in `industry_research_router` is a UI-freshness choice; industry secular context is
valid longer. The AI DCF reads the cache table directly with its own 14-day window and must
surface the age in the brief/citation (`[Industry report, Nd old]`) so staleness is visible in
the audit trail rather than silently blended.

### 6.4 Rate limits (CLAUDE.md rule 7)

New AV calls per un-cached run: the target's newest-transcript probe (≤ ~3 calls) + estimates
fetch if stale. Competitor transcripts are cached-only by design. When invoked from the research
pipeline, the transcript probe result is shared, not repeated (gather once, pass everywhere —
same finding as industry_research PLAN Phase 1). Well under 75/min; no bursts.

### 6.5 Guardrails (Python, post-Architect, pre-engine)

- Hard reject (fall back per-field with a QC warning, never crash):
  - `terminal_growth_rate` outside [0%, 4%] -> engine's own default TG (drop the override).
  - Any list not exactly length 5 -> reject the scenario; if base is rejected the whole AI DCF
    fails over to the error path (research pipeline proceeds without it).
- Soft warn (keep the value, record a QC warning surfaced in the report):
  - any year revenue growth outside [-50%, +100%];
  - any year EBIT margin outside [-30%, +60%], or > historical max + 10pp;
  - any year capex outside [0%, ticker's own historical max capex % of revenue + 15pp] — anchored
    per-ticker (`get_historical_margin_bounds`'s `capex_pct_max`, same 7yr window as the EBIT-margin
    historical max), not a flat percentage: a 2,581-ticker check (PLAN_GUARDRAILS.md Phase 2) found
    a flat 35% ceiling sits below the median utility's own capex intensity (~38%), so it flagged
    normal capital-intensive-sector capex as anomalous while being nearly inert for asset-light
    sectors. Falls back to a flat 35% only when the ticker has fewer than 2 usable years of capex
    history to anchor on (e.g. a recent IPO);
  - any year `cogs_pct` outside [0%, 100%], or, for `reports_cogs=True` targets, more than 15pp
    below the historical trailing COGS% without corroborating evidence cited in the scenario
    rationale (a large unexplained gross-margin jump is the most likely hallucination vector);
  - for `reports_cogs=True` targets, `ebit_margin_pct[i] > 1 - cogs_pct[i]` for any year (see
    6.2b — internally inconsistent pair, engine will floor SG&A/R&D rather than hit the target);
  - bear/base/bull ordering violations (bear intrinsic value > bull after engine run).
- Post-engine sanity: if a scenario's engine run raises, that scenario is `None` (same degrade
  as `compute_dcf_scenarios`); base failing = AI DCF unavailable.

### 6.6 Price blindness

Same discipline as the existing Valuation Analyst (`api/valuation_data.py` docstring): no
current price, market cap, current multiples of the target, goal prices, or analyst price
targets anywhere in evidence contexts or Architect input. Peer multiples are allowed (they are
not the target's price). Historical rolling-median multiples are allowed. Transcripts/MD&A/web
text may incidentally mention price — prompts carry the same "incidental noise, ignore" clause
as `research_valuation.md`. The Architect also never sees the mechanical engine's assumption
values, so the two DCFs stay genuinely independent (the reconciliation happens downstream in
the Valuation Analyst, which sees both).

### 6.7 Known landmines (inherited)

- **Compiled-grammar size limit** (Claude structured output): keep schemas compact; fallback =
  one Architect call per scenario (bear/base/bull sequential) merged in Python.
- **DuckDB read-only concurrency**: every connection in the parallel gather is
  `read_only=True`; the AI DCF cache DB is the only write target.
- **Literal `\n` sanitization**: reuse `_sanitize_prose`/`_sanitize_table_cell` behavior from
  the industry router for LLM prose fields.
- **Placeholder-string floats**: `"n/a"` coercion validators on every numeric field.
- **Cache staleness during development**: prompt changes need `DELETE FROM ai_dcf_cache`.

### 6.8 Research-report integration semantics

- The Valuation Analyst receives BOTH DCF summaries, clearly labeled (mechanical = trailing-
  ratio/consensus-anchored engine defaults; AI = agent-authored assumptions with justifications).
  Its prompt requires: (a) state which DCF anchored `fair_value_base` and why (neutral rule — no
  hard-coded preference); (b) where the two disagree > 20% on base intrinsic value, explicitly
  adjudicate the driving assumption difference in `dcf_reconciliation`.
- `_validate_report` additions: if the AI DCF succeeded, the report's rendered AI DCF figures
  must match `AiDcfResult` exactly (same pattern as the existing fair-value QC check).
- Failure isolation: AI DCF error/timeout -> Valuation Analyst context says so, pipeline output
  is byte-equivalent to today's behavior minus the new sections.

### 6.9 Caching, status, endpoints

Cache table `ai_dcf_cache(ticker, model, result_json, report_markdown, generated_at)`, PK
(ticker, model), 24h TTL. Status phases: `gathering_data -> running_evidence ->
running_architect -> computing_dcf -> done|error|cancelled`.

Endpoints (mirror existing shapes):
- `GET /research/ai-dcf?ticker=...&model=...&retry=bool` — get-or-start, returns markdown (and
  the JSON via `format=json` for tests/tooling).
- `GET /research/ai-dcf/status?ticker=...&model=...`
- `POST /research/ai-dcf/cancel?ticker=...&model=...`

## 7. Report rendering

### 7.1 Standalone AI DCF markdown (also the cached artifact)

1. Header — ticker, model, prepared date, inputs available (industry report age, MD&A years,
   competitor transcript coverage).
2. Valuation summary — bear/base/bull intrinsic value/share + WACC + TG (engine numbers).
3. Assumptions table — per scenario x year: revenue growth, EBIT margin, capex % (deterministic).
4. Key debates — the Architect's `key_debates` bullets.
5. Scenario rationales + WACC rationale.
6. Evidence briefs (the three, as labeled sections).
7. QC warnings.

### 7.2 Additions to the research report

- "DCF (AI-authored)" row in the Model Summary triangulation table (bear/base/bull values).
- "AI vs. Mechanical DCF Assumptions" table: per scenario, 5yr revenue CAGR, avg EBIT margin,
  capex %, TG, WACC — AI and mechanical side by side (both from engine outputs, deterministic).
- Valuation Analyst's `dcf_reconciliation` rendered in the Intrinsic Valuation section.

## 8. Cost & latency budget

Per un-cached run: 4 LLM calls (3 evidence parallel + 1 Architect; up to 6 with the grammar
split) + 3 deterministic engine runs (seconds) + 1-2 Tavily searches. Expected wall time
dominated by 2 sequential LLM rounds (~1-3 min on default models). Research-report integration
adds one sequential round before the specialist fan-out when the cache is cold, ~zero when warm.

## 9. Testing plan

Unit (fast, fixture/mocked-DB):
- `get_industry_report`: within/past 14d window, freshest-across-models selection, `custom:*`
  exclusion, missing-industry None, age computation.
- `get_mda_history`: 3x10-K + 1x10-Q selection order, truncation, empty-cache degrade.
- `get_competitor_transcripts`: cached-only guarantee (assert no AV fetch function is called),
  peer ordering, skip-note for uncached peers.
- Sanitization: assert the composed evidence/Architect contexts never contain current price,
  market cap, or analyst-target strings for the target (reuse the valuation_data discipline).
- Guardrails: each hard/soft rule; TG fallback; scenario rejection; warning propagation.
- Mapping: `AiDcfAssumptions` -> `UserOverrides` round-trip; hand-written assumptions through
  the real `run_dcf_av` produce a finite intrinsic value; no-COGS service company unaffected.
- Renderers: assumptions/comparison tables from a fixture `AiDcfResult`; numbers match engine
  extracts exactly.
- Cache TTL get/put; status transitions; retry guard.

Integration (mocked LLM, `tests/conftest.py` pattern):
- Full AI DCF pipeline with mocked agents -> valid `AiDcfResult` + markdown.
- Degraded inputs: no industry report, no MD&A, no competitor transcripts -> still completes,
  header notes reduced inputs.
- Research pipeline with AI DCF mocked as (a) success (Valuation Analyst context contains both
  DCFs; triangulation row + comparison table present) and (b) failure (report equals today's
  structure; no orphaned sections).

Live (manual, per phase gates in PLAN.md):
- One profitable large-cap (e.g. TXN), one no-COGS service company (e.g. UPS), one
  unprofitable/low-coverage name — eyeball assumption quality, provenance tags, guardrails.

## 10. Open questions (deferred, not blocking)

- Should `key_debates` also feed the Chief's `investment_thesis` context? (Recommend not in v1;
  the Valuation Analyst's reconciliation already carries the signal downstream.)
- A DCF-viewer frontend panel (AI vs. default assumptions, one-click standalone run) — follow-up
  feature once real outputs have been observed for a while.
- ~~Persisting AI DCF history (assumption drift over time per ticker) for later audit~~ —
  **resolved by section 11 below** (2026-07-31): a lighter-weight reconciliation-decision log
  was built instead of full assumption-history tracking, per user request after discussing
  hedge-fund model-governance norms. `AiDcfResult` itself still keeps only the latest per
  (ticker, model) in `ai_dcf_cache.duckdb` — full assumption-drift-over-time tracking remains a
  distinct, still-deferred follow-up if this lighter log proves valuable enough to extend.

## 11. Addendum: DCF reconciliation audit trail (added 2026-07-31)

**Motivation**: section 6.8's neutral-preference reconciliation rule is enforced entirely by
prompt instruction — nothing previously verified the Valuation Analyst actually engaged with a
large (>20%) disagreement between the two DCFs, and nothing persisted *which* DCF ended up
anchoring `fair_value_base` or whether that choice was later borne out. This mirrors a real
model-governance gap: hedge funds and institutional research desks don't grade the prose
quality of a reconciliation write-up (an LLM judging another LLM's reasoning was explicitly
rejected as low-value and circular) — they log the decision and its inputs, so the choice can
be evaluated retrospectively against what actually happened.

**What was added**:
- `api/ai_dcf_router.py` gains `compute_divergence_pct(mechanical_base, ai_base) ->
  Optional[float]` and `compute_dcf_anchor(fair_value_base, mechanical_base, ai_base) -> str`
  (`"mechanical"` / `"ai"` / `"tied"` / `"mechanical_only"` / `"ai_only"` / `"neither_available"`
  — a deterministic proxy for which DCF the Valuation Analyst's own output ended up numerically
  closer to, not a semantic judgment of the reconciliation text), plus
  `log_dcf_reconciliation(ticker, model, mechanical_base, ai_base, fair_value_base,
  reconciliation_text)` writing one row to a new `dcf_reconciliation_log.duckdb` (ticker, model,
  generated_at, mechanical_base, ai_base, divergence_pct, anchor, reconciliation_text). Never
  raises — a logging failure must not break report generation.
- `api/research_router.py`: `_build_post_subagent_tables` now also returns the **ground-truth**
  mechanical base intrinsic value (from the same shared `compute_dcf_scenarios` call already
  used for the tables — no second DCF run) so both the log and the new QC check use real engine
  output, not the Valuation Analyst's own echoed `dcf_intrinsic_value` field. `_run_research_agent`
  calls `log_dcf_reconciliation` once per real generation (never on a cache hit), wrapped so a
  logging failure degrades silently. `_validate_report` gains one more deterministic check: if
  the two base values diverge by more than 20% and `dcf_reconciliation` is empty or near-empty
  (<20 chars), a QC warning fires — catching silent non-compliance with the reconciliation rule
  without attempting to grade reconciliations that ARE present.
- Deliberately NOT built: an LLM-based grader scoring whether the reconciliation text
  substantively engages with the disagreement. Rejected per the same reasoning as above.
