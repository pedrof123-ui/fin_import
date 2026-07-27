# Industry AI Researcher — Feature Specification

Status: Draft for planning. Author: equities-quant analyst spec. Target: a coding planner turns
this into a phased implementation + testing plan.

## 1. Goal

An industry-level AI researcher that reviews several quarters of earnings-call transcripts across
multiple companies in the *same AV industry*, cross-references the project's quantitative
fundamentals, and produces a single report covering: industry developments, secular and cyclical
trends, forward outlook, risks/headwinds, and a ranked table of actionable single-name investment
ideas within the industry.

This is the industry-level counterpart to the existing single-name AI Researcher
(`api/research_router.py`). It reuses that feature's proven patterns (multi-agent fan-out/fan-in,
DuckDB report cache, live-status/cancel UX, "LLM writes prose, Python writes the numbers") but
runs as a **new parallel pipeline** so the two features stay decoupled.

## 2. Confirmed scope decisions

| Decision | Choice |
|---|---|
| Peer set | AV `industry` field (finer than sector), with an optional user-supplied custom ticker basket when the classification is too broad/narrow |
| Universe cap | Top **8** companies by market cap per industry (configurable constant), trailing **4** quarters of transcripts each (~32 transcripts) |
| Transcript strategy | **Per-company map-reduce**: summarize each company's calls into a compact digest first, then synthesize industry themes from the digests (keeps per-call token budget bounded, avoids one mega-context) |
| Deliverable | **Thematic report + ranked actionable ideas** (industry narrative AND a ranked winners/losers table with rationale) |
| Architecture | **New** `api/industry_research_router.py` + new prompts + new `IndustryResearchViewer.tsx` tab; shared helpers reused from the existing stack |

### 2.1 Grain guarantee — industry, never sector (hard requirement)

This is an **industry** researcher. A sector routinely spans industries on divergent cycles, so
every stage must operate strictly at the AV `industry` grain and must **never silently widen to
sector**.

Verified against the current DB: **12 sectors vs 145 distinct industries** (industry is ~12x
finer), **0 companies missing an industry classification**, and the Technology sector alone splits
into 13 industries (Semiconductors; Semiconductor Equipment & Materials; Software - Infrastructure;
Software - Application; Solar; ...) that experience materially different demand and capex cycles.

Explicit anti-requirements:
- **No sector fallback.** The single-name researcher's `_peer_df` widens to `UPPER(co.sector)=?`
  when `industry` is null. Do NOT copy that behavior. If a would-be member has no industry
  classification, **exclude it and note it** — never pull sector peers in its place.
- Member resolution filters on `UPPER(co.industry)=?` only.
- Aggregates read `sector_stats WHERE group_type='industry'` only (never `'sector'`).
- The web-search query is industry-keyed (the specific industry name), not the sector name.
- The report header states the exact industry analyzed; it must never present sector-wide medians
  as if they described the industry.
- The **custom basket** is also the escape hatch for the opposite problem: when even an AV industry
  is too coarse (e.g. "Software - Application" lumps 112 divergent names), the user narrows it to a
  hand-picked sub-theme. The pipeline still never broadens beyond the requested set.

## 3. Non-goals

- No backtesting or performance attribution of the ideas (the ideas table is qualitative +
  fundamentals-grounded, not a validated quant signal).
- No new persistent domain tables beyond a report cache — this feature *reads* existing DBs.
- No token-by-token streaming of the report body; batch-generate + poll for status, exactly like
  the single-name researcher.
- Not a replacement for the Sector dashboard (`SectorViewer` / `sector_router.py`); that stays a
  purely quantitative snapshot. This feature is the qualitative/LLM layer on top of the same data.

## 4. User experience

New always-rendered top-level tab **"Industry Research"** (peer of Screener / Sector / Calendar —
it is industry-scoped, not ticker-scoped, so it does not require a loaded ticker).

Controls:
- **Industry picker** — dropdown of available industries with member counts (sourced from the
  same `company_overview` classification the Sector dashboard uses).
- **Custom basket** (optional) — free-text ticker list; overrides the industry auto-selection.
- **Model dropdown** — same `_MODEL_OPTIONS` list as the single-name researcher.
- **Generate** button, **Cancel** button, and a one-line live status bar (Claude-Code style),
  identical UX to `EquityResearchViewer`.

Output: a markdown report rendered in-panel. Each ranked-idea ticker is clickable and calls the
existing `onSelectTicker` handler to jump into the single-name AI Research tab for that name.

## 5. Report structure (final deliverable)

1. **Header** — industry name, member tickers analyzed, quarters covered, prepared date, model.
2. **Executive summary** — 3-6 bullets: the industry's current state and the single most important
   development.
3. **Industry state & secular trends** — structural demand drivers, TAM direction, technology/
   regulatory shifts (grounded in transcripts + web search).
4. **Demand, pricing & margin signals** — cross-company read on demand cadence, pricing power,
   input costs, and margin trajectory, synthesized from the per-company earnings digests.
5. **Capital cycle & competitive dynamics** — capex/investment intensity, share shifts, entrants/
   consolidation.
6. **Risks & headwinds** — cyclical, structural, regulatory, and dispersion risks.
7. **Forward outlook** — next 2-4 quarters, tied to aggregated guidance direction and estimate
   revisions.
8. **Quantitative appendix (deterministic tables)** — rendered in Python, never LLM-authored:
   - Industry valuation/margin/growth medians + 3/6/12m trend (from `sector_stats`).
   - Cross-company financials table (member-by-member: mkt cap, P/E, fwd P/E, rev/earn growth,
     ROIC, gross margin) — reuse the `_peer_df` pattern.
   - Cross-company EPS beat/miss dispersion (% of members beating, streaks).
   - Estimate-revision momentum by member.
9. **Ranked actionable ideas** — table: `ticker | stance (Overweight/Neutral/Underweight) |
   key catalyst | key risk | valuation vs industry | revision momentum`. LLM authors the
   stance/catalyst/risk; **Python attaches the numeric columns** from the fundamentals so the
   figures can't drift.

## 6. Architecture

### 6.1 Pipeline (fan-out map -> reduce -> synthesize)

```
resolve members (<=8 by mkt cap, or custom basket)
        |
   gather data (parallel, thread pool):
     - transcripts (4q each)      - beat/miss (per member)
     - industry aggregates        - member financials table
     - estimate revisions         - industry web search (trends/TAM)
        |
STAGE 1 — MAP: per-company Earnings Digest sub-agent  (<=8 in parallel)
     input : one company's 4 transcripts + its beat/miss + its financials
     output: compact structured digest (demand / pricing / margins / guidance
             direction / capex / mgmt tone / notable quotes / company risks)
        |
STAGE 2 — REDUCE: industry specialist sub-agents (parallel)
     - Trends & Developments analyst   (state, secular/cyclical trends, demand, pricing)
     - Risks & Outlook analyst         (headwinds, regulation, forward outlook)
     input : the <=8 digests + quantitative aggregates + web search
        |
STAGE 3 — SYNTHESIZE: Chief Industry Strategist
     input : specialist outputs + digests + quant aggregates
     output: final report incl. LLM-proposed ranked ideas (stance/catalyst/risk)
        |
   Python post-processing: deterministic appendix tables + numeric columns
   spliced into the ranked-ideas table (LLM never emits the numbers)
```

Rationale for map-reduce: 8 companies x 4 transcripts x ~7k chars ≈ 224k chars would blow a single
context and cost. Digesting each company first (one bounded ~28k-char call) compresses each name to
a few hundred tokens before any cross-company reasoning, mirroring how the single-name researcher
keeps each sub-agent's context scoped.

### 6.2 New files

| File | Purpose |
|---|---|
| `api/industry_research_router.py` | FastAPI router, orchestration, cache, status/cancel, deterministic tables |
| `api/industry_data.py` | Data-gathering layer (resolvers + aggregate builders), all synchronous/thread-safe |
| `api/prompts/industry_company_digest.md` | Stage-1 map prompt |
| `api/prompts/industry_trends.md` | Stage-2 Trends & Developments specialist |
| `api/prompts/industry_risks.md` | Stage-2 Risks & Outlook specialist |
| `api/prompts/industry_chief.md` | Stage-3 Chief Industry Strategist (split into `_core`/`_narrative` if schema exceeds the grammar-size limit — see 6.6) |
| `web/components/IndustryResearchViewer.tsx` | Frontend tab component |
| `tests/test_industry_data.py` | Data-layer + deterministic-table unit tests |

Register the router in `api/main.py`; add the tab in `web/app/page.tsx` (always-rendered block
alongside Screener/Sector/Calendar); update `docs/Project_Structure.md`.

### 6.3 Reused, do not reimplement

- `historic_fundamentals/earnings_transcripts.py` — `open_db`, `get_last_n_transcripts`,
  `get_latest_cached_quarter`, `fetch_from_av`, `save_transcript`, beat/miss helpers
  (`get_cached_surprises` / `fetch_surprises_from_av` / `save_surprises`).
- `sector_router.py` aggregate logic / `sector_stats` table — for industry valuation, margin,
  growth medians and 3/6/12m trend columns. Factor the shared aggregation into a helper if it is
  currently inline in the router.
- `research_router.py::_peer_df` pattern — member financials table (ATTACH both DBs read-only,
  `QUALIFY ROW_NUMBER()` latest-snapshot join).
- `research_router.py` scaffolding to copy structurally: `_md_table`, the DuckDB cache
  (`_init_cache`/`_cache_get`/`_cache_put`), `_background_tasks`/`_task_status`/`_set_status`,
  `_get_or_start` with the `retry` guard, and the `/status` + `/cancel` endpoints.
- `_MODEL_OPTIONS`, `_STYLE_GUIDE`, and the `_run_subagent` + `asyncio.wait_for(_LLM_TIMEOUT)`
  fan-out helper.

### 6.4 Data layer (`api/industry_data.py`)

| Function | Returns |
|---|---|
| `list_industries()` | industries with member counts (for the picker) — from latest `company_overview` snapshot |
| `resolve_members(industry, custom_tickers, cap=8)` | ordered ticker list — custom basket verbatim if given, else top-`cap` by market cap filtered on `UPPER(co.industry)=?` **only** (no sector fallback; a member with null industry is excluded, not sector-substituted) |
| `get_industry_transcripts(tickers, n=4)` | `{ticker: [(quarter, text), ...]}`; probes AV for a newer-than-cache quarter per ticker, then reads cache (reuse the `get_earnings_trend_summary` probe logic) |
| `get_industry_aggregates(industry)` | valuation/margin/growth medians + 3/6/12m deltas — from `sector_stats WHERE group_type='industry'` **only**; must not read `group_type='sector'` rows |
| `get_member_financials(tickers)` | per-member financials dataframe — `_peer_df`-style query **but with the sector-fallback branch removed** (see 2.1) |
| `get_industry_beat_miss(tickers)` | per-member EPS surprise rows + dispersion summary |
| `get_industry_estimates(tickers)` | per-member forward growth + revision momentum |
| `get_industry_web_search(industry)` | Tavily query for industry secular trends / TAM / demand (reuse `_tavily_search`) |

All degrade gracefully: a member with no cached transcript is still included in the financial
tables and simply contributes no digest (report notes reduced coverage). Never hard-fail the whole
report because one name is missing data.

### 6.5 Pydantic output schemas (sketch)

- `CompanyDigest` (Stage 1): `ticker`, `demand`, `pricing_margins`, `guidance_direction`
  (Literal `RAISED`/`MAINTAINED`/`LOWERED`/`UNCLEAR`), `capex_investment`, `management_tone`
  (Literal `BULLISH`/`NEUTRAL`/`CAUTIOUS`), `notable_quotes: list[str]`, `company_risks: list[str]`.
- `TrendsOutput`, `RisksOutput` (Stage 2): bulleted narrative fields per report section.
- `IndustryIdea`: `ticker`, `stance` (Literal `OVERWEIGHT`/`NEUTRAL`/`UNDERWEIGHT`), `catalyst`,
  `key_risk`. Numeric columns are NOT in the schema — Python appends them.
- `IndustryReport` (Stage 3 chief): header + section prose + `ranked_ideas: list[IndustryIdea]`.

Apply the same `field_validator(mode="before")` placeholder-string coercion helper the single-name
researcher uses (`_coerce_optional_float`) for any numeric fields, to survive `"n/a"`-for-null.

### 6.6 Known landmines (carried over from the single-name researcher — see memory
`project_ai_researcher_valuation_agent`)

- **Anthropic compiled-grammar size limit**: a single large structured-output schema fails on
  Claude models with "compiled grammar is too large". Keep `IndustryReport` modest; if it grows,
  split the Chief into two sequential calls (`_core` = ideas + structured fields, `_narrative` =
  prose) and merge in Python, exactly as `research_chief_core.md`/`research_chief_narrative.md` do.
- **DuckDB read-only concurrency**: every connection opened inside the parallel fan-out must be
  `read_only=True`; mixing read-write and read-only handles to the same file errors.
- **Cache staleness**: any prompt/logic change that alters report content needs the cache cleared
  to be visible (`DELETE FROM industry_research_cache`).
- **Numbers belong in Python**: the ranked-ideas numeric columns and every appendix table are
  rendered deterministically from the DBs; the LLM only writes stance/catalyst/risk/prose.

### 6.7 Caching, status, endpoints

Cache table `industry_research_cache(scope_key, model, report_markdown, generated_at)`, 24h TTL.
`scope_key` = uppercased industry name, or `custom:` + a stable hash of the sorted custom-ticker
list. Status phases: `gathering_data -> digesting_companies -> running_specialists ->
synthesizing -> done|error|cancelled`.

Endpoints (mirror the single-name shapes):
- `GET /industry-research/industries` -> picker list.
- `GET /industry-research/report?industry=...&tickers=...&model=...&retry=bool`
- `GET /industry-research/status?...`
- `POST /industry-research/cancel?...`
- `GET /industry-research/models` (or reuse the existing `/research/models`).

## 7. Rate limits & cost

- **Alpha Vantage 75 calls/min** (CLAUDE.md rule 7): transcripts are largely pre-cached by
  `scripts/earnings_backfill.py`; only a newest-quarter probe per member hits AV (<=~3 calls x 8
  members). Beat/miss is cached 30d. Bound concurrent AV probes so a run stays well under 75/min.
- **LLM cost/latency**: ~8 map calls + ~2 reduce calls + 1 (or 2) chief calls. Map calls dominate
  token volume; the digest compression is what keeps total cost bounded. Reuse `_LLM_TIMEOUT` and
  per-agent `asyncio.wait_for`.

## 8. Data readiness (pre-req, verify in Phase 0)

- `earnings_transcripts.duckdb` coverage for the target industries' top names (backfill already
  fetched the latest 4 quarters per AV ticker).
- `sector_stats` has current `group_type='industry'` rows (rebuilt via
  `scripts/rebuild_sector_stats.py` if stale).
- `company_overview` industry classification is populated for members.

## 9. Testing plan

Unit (`tests/test_industry_data.py`, fast, DB-mock or fixture-backed):
- `resolve_members`: industry auto-select ordering by market cap + cap; custom-basket passthrough;
  empty/unknown industry handling.
- **Grain guarantee (2.1)**: a member with a null/blank industry is excluded, NOT replaced by
  sector peers; `get_industry_aggregates` never returns a `group_type='sector'` row; two industries
  in the same sector (e.g. Semiconductors vs Software - Infrastructure) resolve to disjoint member
  sets and distinct aggregates.
- `scope_key` hashing: stable and order-independent for custom baskets.
- `get_industry_aggregates` / `get_industry_beat_miss`: correct medians and dispersion math.
- Deterministic ranked-ideas numeric join: LLM-proposed tickers correctly matched to fundamentals,
  graceful "n/a" for tickers absent from the DB.
- Cache TTL get/put; prompt `_fill` substitution.

Integration (mirrors `tests/conftest.py`, which already mocks `openai-agents` submodules):
- Full pipeline with mocked sub-agents -> renders valid markdown, includes appendix tables and
  ranked-ideas table.
- Degraded run: an industry where 2 of 8 members lack transcripts still produces a report noting
  reduced coverage.
- Status transitions and cancel/retry-after-cancel (copy the single-name researcher's test).

Manual/Playwright: generate a real report for one industry (e.g. Semiconductors), verify live
status transitions, working cancel, clickable idea tickers, and no LLM-authored numbers drifting
from the appendix.

## 10. Metrics discipline (per project standard `feedback_strategy_metrics`)

The ranked-ideas table is qualitative and explicitly NOT presented as a validated strategy. If a
future phase promotes it toward a tradable signal, that phase must report Profit Factor and
R-Expectancy alongside Sharpe/MaxDD/turnover before any go/no-go — do not imply performance here.

## 11. Suggested phasing (for the planner)

- **Phase 0** — Data-readiness audit (section 8); confirm transcript/sector_stats/classification
  coverage; decide the members cap constant.
- **Phase 1** — `industry_data.py` resolvers + aggregate builders + unit tests (no LLM).
- **Phase 2** — Deterministic appendix tables + ranked-ideas numeric join (still no LLM).
- **Phase 3** — Prompts + Stage-1 map (per-company digest) sub-agent; verify digest quality on one
  industry.
- **Phase 4** — Stage-2 specialists + Stage-3 chief synthesis; markdown renderer; grammar-size
  split if needed.
- **Phase 5** — Router: cache, status/cancel, endpoints; register in `api/main.py`.
- **Phase 6** — `IndustryResearchViewer.tsx` + tab wiring + clickable idea tickers.
- **Phase 7** — Integration/Playwright verification; update `docs/Project_Structure.md`.

Mark every phase/step Complete in the resulting PLAN.md as built (CLAUDE.md rule 8).

## 12. Open questions for the planner (deferred, not blocking)

- Should the report cache be invalidated automatically when a member reports a new quarter, or is
  24h TTL sufficient? (Recommend 24h TTL for v1.)
- Should there be an optional industry-level chat (like `/research/chat`) grounded in the generated
  report? (Recommend deferring to a follow-up.)
- For very fragmented industries (>25 members), is top-8-by-mktcap representative, or should the
  picker warn and suggest a custom basket? (Recommend a soft coverage note in the report header.)
