# AI Researcher Improvement Plan

Goal: add an independent Valuation sub-agent to the AI Researcher pipeline and upgrade the
framework/prompts to institutional research-desk quality. This plan is written for a coding
agent: each phase is independently implementable and testable. Mark phases Complete as done.

## Current architecture (for context)

`api/research_router.py` implements a fan-out/fan-in pipeline (OpenAI Agents SDK via OpenRouter):

1. Data gathering: ~11 parallel fetchers (DuckDB, SEC EDGAR, AV transcripts, Tavily) with timeouts.
2. Three parallel sub-agents: Competitive & Strategy (`research_competitive.md`), Earnings & MD&A
   Historian (`research_earnings.md`), Technical Analyst (`research_technical.md`), each with a
   Pydantic `output_type` and an error fallback.
3. Chief Analyst (`research_chief.md`) synthesizes into `EquityResearchReport`, rendered to
   markdown, cached 24h in `research_cache.duckdb` keyed by (ticker, model).

The repo already has a deterministic DCF engine: `dcf.run_dcf_av(ticker)` returns a `DcfResult`
(intrinsic value per share, WACC detail, FCFF forecast, terminal value, WACC x terminal-growth
sensitivity grid, warnings, analyst estimates anchoring). It reads av_financials.duckdb,
prices.duckdb (current price), fred.duckdb (risk-free rate), and stored weekly betas. The
Valuation sub-agent builds on this engine — the LLM interprets a deterministic model, it does
not invent DCF math.

---

## Part A — Valuation sub-agent design

### Mandate

An independent "Valuation Analyst" that produces its own unbiased fair-value estimate from
fundamentals: a DCF (deterministic engine, run as bear/base/bull scenarios) plus a
multiples-based cross-check. It runs in parallel with the other three sub-agents.

Independence decision (v1): the valuation agent takes NO input from the other sub-agents'
outputs — only deterministic data. The competitive agent's context includes web search; letting
news sentiment leak into the valuation would reintroduce the bias this agent exists to exclude.
It does receive the raw peer comparison table (data, not prose). The Chief is where narrative
and valuation meet. Future enhancement (not v1): feed the competitive agent's moat/VRIO
conclusion into terminal-growth critique.

### Hard data rules

Allowed:
- All financial statement data (av_financials.duckdb, historic_fundamentals.duckdb)
- prices.duckdb (used internally by the DCF for WACC capital-structure weights)
- Analyst EPS and revenue estimates (earnings_estimates table / DcfResult.analyst_estimates)
- Historical normalized multiples (normalized_pe_5y, normalized_pfcf_5y from pe_stats)
- Peer fundamental/multiple data (for relative valuation)

Prohibited — must NOT appear anywhere in the valuation agent's context:
- goal_low, goal_high, goal_2x (model price targets in pe_stats)
- analyst_target_price and analyst rating distribution (company_overview)

Anti-anchoring rule (design decision): the valuation agent's context also excludes the current
stock price, price returns, and current P/E / P/FCF (any figure from which price is trivially
derivable). The agent values the business blind; the Chief Analyst computes upside vs. price.
This is what makes the valuation genuinely unbiased rather than a rationalization of the quote.
Concretely: the DCF summary shown to the agent omits `current_price`, `upside_pct`, and market
cap (shows WACC as rates + debt/equity weights only); valuation inputs show normalized
multiples and per-share earnings/FCF, not current multiples.

### New data functions (research_router.py or a new api/valuation_data.py)

1. `get_dcf_summary(ticker) -> str` — runs the DCF engine three times deterministically
   (bear / base / bull operating scenarios) in an executor (new `_DCF_TIMEOUT = 90` total),
   formats the results as text:
   - Base = `run_dcf_av(ticker)` as-is (forecaster defaults anchored to consensus-avg
     revenue estimates).
   - Bear / bull = `run_dcf_av` with `UserOverrides.years` built from the consensus LOW / HIGH
     revenue estimates (`revenue_estimate_low/high` in earnings_estimates) for the horizons
     they cover, and `ebit_margin_pct` at the company's 5y p25 / p75 historical EBIT margin.
     If low/high estimates are unavailable, fall back to base revenue growth -/+ one half of
     the spread between quarterly-momentum and annual-EWM growth, and margins at p25/p75.
     Scenario construction is code, not LLM — disclosed in the output as a scenario table.
   - Per scenario: intrinsic value per share + revenue CAGR and average EBIT margin assumed
   - WACC breakdown (base): beta (raw/relevered), risk-free rate, MRP, cost of equity/debt,
     tax rate, debt/equity weights, WACC (no market cap, no price)
   - Terminal growth rate, terminal value as % of EV (base)
   - 5-year FCFF forecast table (base): revenue, growth %, EBIT margin, NOPAT, capex %,
     delta-NWC, FCFF
   - Sensitivity grid (base): intrinsic value per share across WACC +/-2% x terminal
     growth +/-1% (secondary band on top of the operating scenarios)
   - `DcfResult.warnings` verbatim (data-quality flags)
   - Analyst estimate anchoring used by the forecaster (allowed data)
   On exception return `[ERROR] DCF engine failed for {ticker}: {e}` (the agent prompt handles
   degradation — e.g. financials where FCFF DCF is structurally unsuitable).

2. `get_valuation_inputs(ticker) -> str` — sanitized fundamental inputs:
   - Per-share history: diluted EPS and FCF/share for last 5 fiscal years, TTM EPS
   - Normalized multiples: normalized_pe_5y, normalized_pfcf_5y (historical anchors, no
     current multiples)
   - Growth: rev_cagr_3yr, earn_cagr_3yr, rev/earn_growth_1yr, earn_ntm_growth_est
   - Quality: ROIC, gross/operating/FCF margins vs. 5y medians, debt/EBITDA
   - Forward consensus EPS and revenue per horizon (earnings_estimates — allowed)
   - Share count trend (buybacks/dilution) from diluted_shares history
   Explicitly never SELECTs goal_*, analyst_target_price, current_price, current_pe,
   current_pfcf, or monthly price history.

3. Extend `get_peer_comparison()` with a `include_price_multiples: bool = True` parameter; the
   valuation agent receives the peer table (peer multiples are needed for relative valuation
   and reveal nothing about the subject's own price). Add P/FCF to the peer columns if present
   in pe_stats.

### Sub-agent spec

- Prompt: `api/prompts/research_valuation.md`
- Output type:

```python
class ValuationOutput(BaseModel):
    fair_value_low: float
    fair_value_base: float
    fair_value_high: float
    dcf_intrinsic_value: Optional[float]      # engine base case, echoed for traceability
    valuation_methodology: str                # how DCF + multiples were weighted and why
    dcf_assessment: str                       # critique of engine assumptions (WACC, tg, margins)
    relative_valuation: str                   # peer multiples cross-check
    valuation_risks: list[str]                # what breaks the fair-value case
```

- Context: `get_dcf_summary` + `get_valuation_inputs` + `get_financial_summary` + peer table.
- Prompt requirements:
  - Derive fair_value_base primarily from the base-scenario DCF; adjust only with stated
    reasons (e.g. WACC looks too low given warnings, terminal growth above long-run GDP,
    margin assumptions above 5y median without support).
  - fair_value_low/high anchor on the bear/bull scenario DCFs, cross-checked against the
    sensitivity grid and the multiples valuation (normalized multiple x forward consensus
    EPS/FCF per share) — not arbitrary +/-%.
  - If DCF is [ERROR] or warnings flag unreliable output, fall back to multiples-only valuation
    and say so in valuation_methodology.
  - Never reference a current stock price, analyst price target, or "upside" — the agent does
    not know the price. State fair value in absolute $ per share.
  - Peak-earnings awareness: if TTM EPS is far above forward consensus, anchor multiples
    valuation on forward/normalized earnings, not TTM.
- Fallback on agent failure: `ValuationOutput` with `[ERROR]` strings and fair values = 0.0
  (Chief instructed to treat 0.0 as unavailable and fall back to current goal-price logic).

### Chief Analyst integration

- Add the valuation agent's output to the specialist block in `chief_context`.
- Rewrite TARGET PRICE guidance: target_low/target_high now anchor on the Valuation Analyst's
  fair_value_low/high (the independent estimate), with goal_low/goal_high retained as a
  secondary sanity check. Rating thresholds re-based on fair_value_base:
  BUY: price >15% below fair_value_base AND positive momentum; SELL: price above
  fair_value_high or deteriorating fundamentals; HOLD otherwise.
- `target_price_validation` becomes a three-way triangulation: independent DCF/multiples fair
  value vs. normalized-multiple goal prices vs. Wall Street consensus — reconcile the gaps.
- New report field + section: `intrinsic_valuation: str` (rendered as "Intrinsic Valuation
  (DCF & Multiples)" after the Valuation table) — Chief copies the valuation agent's
  methodology/assessment/relative-valuation prose verbatim with light polish, same rule as
  other specialists.
- Extend `ValuationSummary` with `fair_value_low/base/high: Optional[float]` and render them
  in the section-2 table.

---

## Part B — Framework and prompt review: recommendations

Ranked; R1-R3 are covered by Part A phases, R4+ are Phase 4/5.

R1 (critical) — Independent valuation anchor. Today the target price is normalized historical
multiple x earnings (goal_low/high) — pure extrapolation; every rating inherits its bias.
Part A fixes this.

R2 (high) — Anti-anchoring separation. Industry practice: the valuation call is made before
looking at the tape. Enforced structurally by excluding price from the valuation agent context.

R3 (high) — Rating rules re-based on intrinsic value (Part A Chief changes).

R4 (high) — Balance sheet & capital allocation coverage. The report has no balance-sheet
section: no leverage/liquidity trend, no buyback/dividend/dilution history — table stakes for
an institutional report. Add `get_balance_sheet_summary()` (cash, total debt, net debt,
debt/EBITDA trend, share count trend, dividends/buybacks from cash flow statements) feeding a
new "Balance Sheet & Capital Allocation" report section owned by the Chief.

R5 (medium) — Earnings transcript depth. Transcripts are truncated at 2,000 chars/quarter
(~1 page) — guidance numbers usually sit mid-call. Raise to 6,000-8,000 chars per quarter
(within Flash-class context limits), and instruct the Historian to extract explicit guidance
numbers (next-Q and FY guidance ranges) into `earnings_highlights`.

R6 (medium) — Beat/miss history. AV earnings data includes historical EPS surprise; a
"last 8 quarters: beat/miss vs. consensus" line in the earnings context grounds the
guide-and-beat pattern analysis the prompt already asks for.

R7 (medium) — Source attribution. Require each specialist to tag claims inline with their
source: `[10-K]`, `[Q1-2026 call]`, `[DB]`, `[web]`, `[est.]`. Cheap change (one prompt line
per agent) with large credibility payoff; makes hallucinated claims visible on read.

R8 (medium) — Deterministic post-validation. Code-side checks after Chief output, before
caching: header.target_low <= target_high; upside_pct consistent with current_price and
target_high (+/-2pp); technical_rating matches the Technical Analyst output; fair values echoed
correctly. On failure log a warning and stamp a "QC: N inconsistencies" footer on the report
(don't block generation).

R9 (low) — Peer table multiples. Add P/FCF (and EV/EBITDA if available in pe_stats) to
`get_peer_comparison` so relative valuation isn't PE-only.

R10 — Bear/base/bull operating scenarios: now covered by Part A (`get_dcf_summary` runs the
DCF engine three times with consensus-low/avg/high revenue anchors and p25/median/p75 margin
bands). A probability-weighted expected value remains deferred.

Model choice: keep the single user-selected model for all agents (default Gemini 3.5 Flash is
adequate for the valuation agent because the DCF math is deterministic; the agent interprets).
Revisit only if the Phase 5 regression harness shows numeric sloppiness — and if any agent
gets a fixed upgrade, it should be the Chief.

Explicitly not recommended now: per-sub-agent model routing, ESG section, options-implied
signals — complexity without commensurate value for this product (CLAUDE.md rule 2).

---

## Phased implementation plan

Test tickers throughout: NVDA (large-cap growth), UPS (service co, no COGS breakdown — known
DCF special case), KO (stable dividend payer), plus one ticker absent from pe_stats to verify
degradation. All commands via `uv run`.

### Phase 1 — Valuation data layer  [x] Complete

Build `get_dcf_summary`, `get_valuation_inputs`, peer-table extension (Part A). Pure data
functions, no LLM.

Tests:
1. `uv run python -c "from api.research_router import get_dcf_summary; print(get_dcf_summary('NVDA'))"`
   prints three scenario intrinsic values with bear <= base <= bull (allow ties when estimate
   spreads are degenerate), WACC breakdown, 5-year FCFF table, sensitivity grid; no exception.
   Repeat for UPS and KO.
2. Prohibited-string check on the concatenation of `get_dcf_summary(t) + get_valuation_inputs(t)`
   for all test tickers: output contains none of `goal_low`, `goal_high`, `goal_2x`,
   `analyst_target`, `Current Price`, `upside`, `market cap` (case-insensitive). Write this as
   a small pytest (`tests/test_valuation_data.py`) so it runs in CI, not just manually.
3. Unknown ticker returns an `[ERROR]`/`[INFO]` string, no exception.
4. `get_dcf_summary` completes in < 60s per ticker (local DBs; estimates may hit AV once,
   30-day cache — well under the 75 calls/min limit).

### Phase 2 — Valuation sub-agent  [x] Complete

`research_valuation.md` prompt, `ValuationOutput` model, wire into the `asyncio.gather`
fan-out as a fourth parallel sub-agent with fallback.

Tests:
1. End-to-end `_run_research_agent("NVDA", default_model)` (direct await in a test script)
   returns a report; log line shows `valuation_analyst done`.
2. For NVDA/UPS/KO: `0 < fair_value_low <= fair_value_base <= fair_value_high`, and
   fair_value_base within the span of the three scenario intrinsic values widened by the
   sensitivity grid's min/max (sanity, not exactness).
3. Grep the valuation agent's three prose fields: no occurrence of `target price`, `current
   price`, `upside`, `analyst target` (case-insensitive).
4. Simulate DCF failure (temporarily point `run_dcf_av` at a bad ticker or monkeypatch to
   raise): report still generates; valuation_methodology states multiples-only fallback.

### Phase 3 — Chief integration, schema, rendering  [x] Complete

Chief prompt rewrite (target anchoring, rating rules, three-way target_price_validation),
`intrinsic_valuation` field, `ValuationSummary` fair-value fields, `render_to_markdown`
section, chief_context wiring. Frontend renders markdown so `EquityResearchViewer.tsx` needs
no change unless the fair-value table rows require label tweaks.

Tests:
1. Full report for NVDA contains an "Intrinsic Valuation" section and fair value low/base/high
   in the valuation table.
2. header.target_low/target_high fall within [0.8 x fair_value_low, 1.2 x fair_value_high]
   when the valuation agent succeeded (Chief may adjust, not ignore).
3. target_price_validation mentions all three anchors (DCF fair value, model goal prices,
   analyst consensus) — manual read of one report.
4. Old cached reports still render (schema change only adds optional fields); a fresh report
   replaces cache after TTL or model switch.

### Phase 4 — Report depth upgrades (R4-R7, R9)  [x] Complete

Balance sheet/capital allocation section, transcript char budget raise, beat/miss history,
source-attribution prompt lines, peer P/FCF column.

Tests:
1. Report contains "Balance Sheet & Capital Allocation" section with net debt and share-count
   trend figures matching a direct DuckDB query for the same ticker.
2. Earnings context for NVDA includes >= 4,000 chars for the latest quarter and a beat/miss
   line for 8 quarters.
3. Specialist outputs contain source tags (grep for `[10-K]` or `[Q` or `[DB]` in at least
   two sections).
4. Generation wall time stays < 3 minutes end-to-end on the default model.

### Phase 5 — QC validation and regression harness (R8)  [x] Complete

`_validate_report(report) -> list[str]` deterministic checks (Part B R8) called in
`_background_generate` before caching; a `scripts/research_regression.py` that generates
reports for the 4 test tickers and asserts the structural criteria from Phases 2-4, printing
a pass/fail table.

Tests:
1. Inject an inconsistent report (unit test with a hand-built `EquityResearchReport` where
   upside_pct contradicts price/target): `_validate_report` returns the specific finding.
2. `uv run python scripts/research_regression.py` passes for all 4 tickers on the default model.
3. Clean report produces zero findings and no QC footer.

---

## Files touched

- `api/research_router.py` — data functions, ValuationOutput, fan-out wiring, chief context,
  schema fields, renderer, QC validation
- `api/prompts/research_valuation.md` — new
- `api/prompts/research_chief.md` — target/rating/validation rewrite, new field specs
- `api/prompts/research_earnings.md`, `research_competitive.md`, `research_technical.md` —
  source-tag line; earnings guidance extraction
- `historic_fundamentals/earnings_transcripts.py` — only if char budget lives there (else the
  truncation constant in research_router.py)
- `tests/test_valuation_data.py`, `scripts/research_regression.py` — new
- `web/components/EquityResearchViewer.tsx` — no change needed (pure markdown rendering via
  react-markdown, confirmed during implementation)
- `historic_fundamentals/earnings_transcripts.py` — added `earnings_surprises` cache table +
  fetch/save helpers for the beat/miss history feature (R6)

---

## Implementation notes (discovered during build)

- The Chief Analyst's schema grew large enough (4 specialists incl. valuation, balance sheet,
  intrinsic valuation) that the default OpenAI Agents SDK `max_tokens` (unset/provider default)
  silently truncated JSON output mid-string on some tickers. Fixed by setting
  `ModelSettings(max_tokens=32000)` explicitly on the chief_agent. 8000 and 16000 both still
  truncated on at least one test ticker (UPS) — 32000 was the value that held across all
  regression runs. Worth revisiting if report depth grows further.
- `get_dcf_summary`'s estimates_conn to historic_fundamentals.duckdb must be opened
  `read_only=True` — the research pipeline holds several concurrent read-only connections to
  that file during the same asyncio.gather fan-out, and DuckDB disallows mixing read-write and
  read-only handles on one file at the same time. `fetch_and_cache`'s cache-write already
  degrades gracefully (silently skipped) under a read-only connection, so this has no
  functional cost beyond not persisting a freshly-fetched AV estimate to the shared cache.
- The Chief's RATING GUIDELINES needed to be phrased as an explicit mechanical rule
  (price_vs_fair_value_high_pct, "rating MUST be SELL unless...") rather than descriptive
  prose — an earlier looser wording produced a HOLD rating on a stock the model's own thesis
  described as overvalued above fair_value_high. The QC validator does not catch this class of
  drift (it's a semantic judgment, not an arithmetic identity), so the prompt is the primary
  defense; watch for recurrence in the regression harness.
- `research_cache.duckdb` has a 24h TTL keyed by (ticker, model) — any code/prompt change that
  alters report content needs the cache cleared (or affected tickers deleted) for it to be
  visible immediately; otherwise stale pre-change reports keep serving for up to 24h. Hit this
  live: a user-visible NVDA report showed the pre-Phase-3 target ($38-65, = goal_low/goal_high)
  and a BUY rating despite price > target_high, purely because it was cached before that
  session's fixes landed. `DELETE FROM research_cache [WHERE ticker = ...]` is the fix.

### Post-launch enhancement: Valuation Model Detail tables

Added after initial ship, per user request: the Chief's `intrinsic_valuation` prose (LLM-
authored) is now followed by four tables rendered **deterministically in Python**
(`render_valuation_model_tables` in `api/research_router.py`, called after the Valuation
Analyst returns and spliced into the markdown outside the Chief's control) — DCF Scenario
Assumptions & Output, Key Fundamentals, Comparable Companies, and a Model Summary triangulating
DCF vs. a P/E-multiples cross-check vs. the analyst's final fair value. Rationale: numbers in a
table are exactly the kind of content an LLM can silently mistranscribe (wrong digit, dropped
decimal) — since all the source data was already computed for the text context, rendering the
tables in code costs one extra DCF-scenario computation (~1s) and removes that risk entirely.

This also surfaced a real bug in `get_valuation_inputs`: it used `normalized_pe_5y`/
`normalized_pfcf_5y` (= current_price / avg_5yr_EPS — bakes in today's price in the numerator)
as if they were price-independent historical anchors. Fixed to use `pe_rolling_5yr_median`/
`pfcf_rolling_5yr_median` (genuine rolling medians of the historical P/E ratio series, same
construction as `goal_pe`) — the same class of anti-anchoring leak Phase 1's prohibited-string
test couldn't catch because it's numeric, not a banned substring. `pe_p25_5yr`/`pe_p75_5yr` feed
the Model Summary's low/high multiples cross-check for the same reason.

### Post-launch enhancement: live status, cancel, error surfacing

Added on user request: the static "Generating Research Report..." placeholder is replaced with
a live, frequently-updating one-line status (Claude-Code-style), a Cancel button, and proper
error surfacing instead of silent infinite retry.

Backend (`api/research_router.py`):
- `_task_status: dict[(ticker, model), dict]` — in-memory phase tracker (`gathering_data` →
  `running_specialists` → `synthesizing` → `done`/`error`/`cancelled`), updated inside
  `_run_research_agent` (now takes an optional `status_key` param) at each real phase
  transition — 3 coarse phases, not per-sub-agent granularity (chosen deliberately: simpler,
  matches the pipeline's natural stages, no risk of getting out of sync with actual completion
  order).
- `GET /research/status?ticker=&model=` — new, returns `{phase, message, error}`. Cheap (dict
  lookup, no DB/LLM call) so the frontend can poll every ~2.5s for a responsive live status,
  vs. the old 15s poll of the full report endpoint.
- `POST /research/cancel?ticker=&model=` — cancels the tracked `asyncio.Task` via `.cancel()`
  and immediately marks status `cancelled` (before the task's own cleanup runs, so the UI
  reflects it instantly rather than racing the cancellation).
- Fixed a real bug found while building this: on failure, `_background_generate` removed the
  task from the registry but recorded nothing — the next poll saw no cache and no running task
  and **silently started a brand-new generation forever**, with the error never surfacing.
  Fixed via `_get_or_start`'s new `retry` param: an `error`/`cancelled` status now blocks
  auto-restart until the user explicitly retries (frontend passes `retry=true` only on an
  explicit button click, never on a background poll).

Frontend (`EquityResearchViewer.tsx`): replaced the heavy markdown placeholder + naive
`text.startsWith("## Generating")` string-sniffing with status-driven state (`phase`,
`statusMessage`, `elapsedSec`) and a compact one-line status bar (pulsing dot + message +
elapsed timer + Cancel button). Verified end-to-end in a real browser via Playwright: status
transitions render live, Cancel immediately stops the run and shows "Cancelled...", and
clicking "Create Equity Report" again correctly retries from scratch.

### Post-launch enhancement: TAM, market share, and true direct competitors

Added on user request: the deterministic peer table (`_peer_df`) is a mechanical sector/
industry classification match — it can miss real competitors classified elsewhere (e.g. a
cloud division vs. a company's own industry code) and include same-industry names that don't
actually compete for the same customers. Added a distinct, LLM-identified competitor
mechanism plus TAM/market-share, following the same "LLM identifies, code computes" split used
throughout this plan.

- `CompetitiveOutput` gained `direct_competitors: list[DirectCompetitor]` (name, ticker if
  public/known else null, one-sentence why_direct — explicit product/customer overlap, not
  industry classification) and TAM fields (`tam_current_low/high`, `tam_projected_low/high`,
  `tam_projected_year`, all $B, all nullable — no fabricated precision when ungrounded).
- New `get_market_size_search(ticker)` — a second, targeted Tavily query
  ("{ticker} industry total addressable market size TAM forecast 2030") feeding the Competitive
  & Strategy Analyst, separate from the existing generic stock-news search. Chosen over relying
  on trained-knowledge recall alone, since TAM figures live in market-research content a generic
  news query won't surface.
- `render_direct_competitors_table` — deterministic DB lookup (pe_stats + company_overview) for
  whichever LLM-identified competitor tickers exist in our data; competitors without a match
  still show (name-only row) rather than being silently dropped.
- `render_market_share_table` — market share = code-computed ratio of (a) actual current annual
  revenue against `tam_current_low/high`, and (b) the DCF base-case Year-5 forecasted revenue
  (from the same `compute_dcf_scenarios` call already used for the Valuation Model Detail
  tables — refactored to share one DCF run instead of two) against `tam_projected_low/high`.
  Both tables spliced into their own report sections (Direct Competitors under Competitive
  Analysis; Market Size & Share under Industry Outlook), not the Chief's output.
- Found via live testing: NVDA's market share came out at 86-216% (current) on the first run —
  the LLM's TAM ("AI data center systems," $100-250B) was narrower than NVDA's *total* reported
  revenue (which also includes gaming, networking, professional viz). Fixed two ways: (1) a
  SCOPE CHECK instruction in the prompt telling the analyst to match TAM scope to the company's
  total revenue base or explicitly caveat a narrower segment TAM; (2) a deterministic caveat
  note auto-appended to the table whenever the computed high-end share is >=90%, regardless of
  how well the LLM manages the scope match on any given run — the same "prompt does its best,
  code catches what's left" pattern used for the rating-rule mechanical check.

### Bug fix: "n/a" string crashing report validation

A real production failure: the Chief occasionally emitted the string `"n/a"` (not JSON `null`)
for numeric `ValuationSummary` fields when the underlying metric is genuinely undefined (e.g.
P/E for an unprofitable company like RXRX) — Pydantic's strict float validation rejected the
whole `EquityResearchReport`, discarding a full ~90s generation. Fixed at both layers:
- Prompt (`research_chief.md`): explicit instruction that numeric fields must be JSON `null`,
  never a placeholder string, when unavailable.
- Code (the reliable fix): `field_validator(mode="before")` on `ValuationSummary`,
  `CompetitiveOutput`'s TAM fields, and `ValuationOutput`'s float fields, coercing known
  placeholder strings ("n/a", "-", "none", etc.) to `None` (or `0.0` for the 3 required,
  non-nullable `ValuationOutput` fair-value fields) before Pydantic's type check runs — prompt
  instructions alone can't guarantee 100% compliance across model runs, so the schema now
  tolerates the exact failure mode regardless. Verified by replaying the user's exact failing
  JSON payload through `TypeAdapter(EquityResearchReport).validate_json(...)` — the same code
  path the Agents SDK uses internally.

### Post-launch enhancement: bullet-point report style

User request: make the report bullet-point/short-paragraph style throughout for faster reading,
without losing analytical depth. Pure prompt-engineering change — no schema or rendering code
touched, since every narrative field is already a markdown string rendered through the existing
`ReactMarkdown` component (bullets/bold already styled).

- One shared `_STYLE_GUIDE` constant in `research_router.py`, injected via a `{style_guide}`
  placeholder in all 5 prompt files (substituted in `_fill()`) — a single source of truth so a
  future style tweak is a one-line change, not a 5-file edit. Core rule: bold micro-header + 2-4
  one-sentence bullets for any content that's a set of distinct points; full prose reserved for
  genuinely connected reasoning, capped at 2-3 sentences even then.
- Every "Para N — TOPIC" field spec across all 5 prompts rewritten to "bold-header bullet
  cluster" — same required topics/depth, different output form (company_overview,
  competitive_analysis, industry_outlook, strategic_framework_analysis, mda_summary,
  quarterly_trend_analysis, technical_analysis, valuation_methodology/dcf_assessment/
  relative_valuation, investment_thesis, price_vs_fundamentals, target_price_validation,
  balance_sheet_analysis). Fields already list-based (key_highlights, risk_factors,
  near_term_catalysts, valuation_risks) or single-sentence (thesis_summary) were left alone —
  already the target format. Deterministic tables unaffected.
- Verified live: full regression across NVDA/UPS/KO + degraded ticker — all generate correctly
  with bulleted output, structural checks pass. (One incidental, pre-existing QC finding on
  that NVDA run — a minor upside_pct arithmetic drift the Phase-5 QC validator is designed to
  catch — unrelated to the style change; didn't block generation, just added a QC footer.)

### Post-launch enhancement: forward-looking context for the Valuation Analyst

User request: the Valuation Analyst's assumptions were purely backward-looking (deterministic
DCF blending trailing financial ratios + quarterly momentum) with zero access to the qualitative
*why* behind recent trends — management guidance, strategic shifts, industry trajectory. Two
architectures were discussed and compared explicitly (latency/cost/independence tradeoffs) before
choosing:
- **Chosen: raw shared sources, stays parallel.** The Valuation Analyst now also reads the same
  raw earnings transcripts (`earnings`), EPS beat/miss history (`beat_miss`), 10-K MD&A (`mda`),
  and TAM/market-size search (`market_size`) that other specialists already read — not their
  finished prose. All four were already fetched during the initial parallel data-gathering
  phase, so this added zero pipeline latency and no new data-fetching.
- **Rejected: sequenced, reads finished Competitive/Earnings output.** Would add a full extra
  sequential LLM stage (+15-30s per report), couple the Valuation Analyst's success to two other
  agents succeeding first (new failure mode requiring new fallback handling), and reintroduce
  the exact "one agent's interpretation shapes another's" risk the independence design has
  avoided everywhere else (price data, `normalized_pe_5y`, etc.).
- `research_valuation.md` rewritten: new DATA PROVIDED entries for the 4 new sources, an explicit
  "USING THIS CONTEXT" instruction (hunt transcripts/MD&A for forward guidance and signs of
  acceleration/deceleration not yet in trailing averages), and the `fair_value_base` adjustment
  rule expanded to allow a stated, cited adjustment when recent guidance/execution diverges from
  the DCF's trailing-ratio assumptions (previously only WACC/terminal-growth/margin-vs-peer
  reasons were allowed).
- **Found and mitigated a real leak during verification**: live Tavily search results (both the
  general web search and the TAM-specific search) can incidentally surface news content
  mentioning the stock's own price or an analyst price target (e.g. a "BofA hikes price target"
  headline appearing in TAM search results) — an inherent risk of any live web search, not
  something fixable by filtering without stripping useful content. Mitigated two ways: (1)
  dropped the generic `web_search` block entirely (least essential of the additions — redundant
  with the peer table's quantitative view and TAM search's industry view); (2) shifted the
  actual guarantee from the input side to the output side — the prompt now explicitly instructs
  the analyst to ignore any incidental price/target mentions in the source text, and the
  meaningful test is whether the analyst's *output* ever repeats them (verified clean on a live
  run), not whether the raw input is 100% sanitized (structurally impossible for live search
  content without gutting it).
- Verified live: the Valuation Analyst's `dcf_assessment` now genuinely engages the new context
  — e.g. checking the DCF's terminal growth rate against the sourced TAM trajectory, and citing
  a specific earnings call ([2027Q1 call]) to validate the base case's revenue CAGR assumption.
  Full regression (NVDA/UPS/KO/degraded ticker) passed with zero QC findings and no latency
  regression (all runs completed in 44-50s, if anything faster than pre-change baseline).
