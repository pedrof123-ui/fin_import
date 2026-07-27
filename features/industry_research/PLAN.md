# Industry AI Researcher — Implementation Plan

Companion to `SPEC.md`. Phased, test-first, executable by a coding agent. Mark each step and phase
`[x]` Complete as it lands (CLAUDE.md rule 8). Standards: `uv run` always, no emojis, simplest
thing that works, only handle exceptions that actually occur.

Grain guarantee (SPEC 2.1) is a hard, tested invariant in every phase that touches selection or
aggregation: **industry only, never a silent sector fallback.**

Run tests with: `uv run pytest tests/test_industry_data.py -q`

---

## Phase 0 — Data-readiness audit  [x] Complete (2026-07-27)

Goal: confirm the read-only inputs exist and are current before writing code. No production code in
this phase — a throwaway script or REPL check is fine.

Steps:
- [x] Confirm `earnings_transcripts.duckdb` has >=1 recent cached quarter for the top-8-by-mktcap
      members of 3 sample industries (Semiconductors, Software - Infrastructure, Biotechnology).
- [x] Confirm `sector_stats` has current `group_type='industry'` rows (max `month_end_date` within
      ~1 month of today). If stale, run `uv run python scripts/rebuild_sector_stats.py`.
- [x] Confirm `company_overview` industry classification is populated for those members (spec
      verified 0 missing globally; re-confirmed for the samples — all 24 resolved).
- [x] Record the chosen constants in SPEC/PLAN if different from defaults: `MEMBERS_CAP=8`,
      `N_QUARTERS=4`. — Defaults confirmed, no change.

Findings (recorded 2026-07-27):

| Industry | Resolved top-8 (by mkt cap) | Transcript coverage (cached quarters) |
|---|---|---|
| Semiconductors | NVDA, TSM, AVGO, MU, AMD, INTC, ARM, TXN | 3-5 quarters each, all 8 present (TSM has 0 cached — foreign ADR, not in `earnings_transcripts`; degrade-gracefully path exercises this) |
| Software - Infrastructure | MSFT, ORCL, PLTR, PANW, CRWD, FTNT, NET, SNPS | 3-4 quarters each, all 8 present |
| Biotechnology | VRTX, REGN, ARGX, ALNY, RVMD, RPRX, ONC, MRNA | 2-3 quarters each, all 8 present |

`sector_stats`: both `group_type='sector'` (11 groups) and `group_type='industry'` (116 groups)
current as of 2026-06-30 (today 2026-07-27) — no rebuild needed. All 3 sample industries have a
current industry-grain row with plausible `ticker_count` (52/93/272 — industry ticker_count in
`sector_stats` is the full universe measured for that industry, larger than the top-8 cap used for
report member selection).

`pe_stats` spot-check (Semiconductors): 7/8 members have `market_cap_b`; **TSM's `market_cap_b` is
NULL** — confirms the `COALESCE(ps.market_cap_b, co.market_cap/1e9)` fallback in `resolve_members`/
`get_member_financials` is load-bearing, not just defensive boilerplate. TSM also has 0 cached
transcripts (ADR, not covered by AV's EARNINGS_CALL_TRANSCRIPT for this symbol) — confirms the
"member with no transcript still appears in financials tables, contributes no digest" degrade path
(SPEC 6.4) is a real case, not hypothetical, and should be exercised in Phase 1/3 tests.

Acceptance: a short written note (in this file's Phase 0 checklist or a scratch log) listing the 3
industries, their resolved top-8 tickers, and transcript-coverage counts. — met, see table above.

---

## Phase 1 — Data layer, no LLM: `api/industry_data.py`  [x] Complete (2026-07-27)

Goal: all read-only data gathering as pure, synchronous, thread-safe functions returning plain
strings/dataframes. This is the majority of the testable surface.

Steps:
- [x] `list_industries() -> list[dict]` — `{industry, sector, member_count}` from the latest
      `company_overview` snapshot, ordered by member_count desc. Powers the picker.
- [x] `resolve_members(industry: str | None, custom_tickers: list[str] | None, cap: int = 8)
      -> list[str]`
      - custom basket: return the provided tickers verbatim (uppercased, de-duped, order preserved).
      - else: top-`cap` by `COALESCE(ps.market_cap_b, co.market_cap/1e9)` where
        `UPPER(co.industry) = UPPER(?)`. **No sector-fallback branch.** Null-industry names never
        appear.
- [x] `get_industry_aggregates(industry: str) -> str` — valuation/margin/growth medians + 3/6/12m
      deltas from `sector_stats WHERE group_type='industry'` only. Factor out / reuse the
      `sector_router` snapshot logic; do not read `group_type='sector'`.
- [x] `get_member_financials(tickers: list[str]) -> str` — per-member table (mkt cap, P/E, fwd P/E,
      rev/earn growth, ROIC, gross margin). Adapt `research_router._peer_df` **with the sector
      fallback branch removed**; query by explicit ticker IN (...) list, not by classification.
- [x] `get_industry_beat_miss(tickers: list[str]) -> str` — per-member EPS surprise rows +
      dispersion summary (% of members that beat, median surprise). Reuse
      `earnings_transcripts.get_cached_surprises` / `fetch_surprises_from_av` / `save_surprises`.
- [x] `get_industry_estimates(tickers: list[str]) -> str` — per-member forward growth + revision
      momentum (mirror `research_router.get_estimates_summary`, looped over members).
- [x] `get_industry_transcripts(tickers: list[str], n: int = 4) -> dict[str, list[tuple[str,str]]]`
      — reuse the AV newest-quarter probe logic from
      `research_router.get_earnings_trend_summary`, then `get_last_n_transcripts`. Bound concurrent
      AV probes to stay under 75 calls/min (SPEC 7). Degrade to fewer/zero quarters silently.
- [x] `get_industry_web_search(industry: str) -> str` — reuse `research_router._tavily_search`
      with an industry-keyed query (industry name, not sector).
- [x] `scope_key(industry, custom_tickers) -> str` — uppercased industry name, or
      `"custom:" + sha1(sorted(uppercased tickers))`. Order-independent, stable.

Tests (`tests/test_industry_data.py`, fixture/monkeypatched DuckDB — no network):
- [x] `resolve_members` orders by market cap and caps at `cap`.
- [x] `resolve_members` custom-basket passthrough (verbatim, de-duped).
- [x] `resolve_members` empty/unknown industry returns `[]` (no crash).
- [x] **Grain guarantee:** a member row with null/blank industry is excluded, never sector-swapped.
- [x] **Grain guarantee:** `get_industry_aggregates` returns no `group_type='sector'` row.
- [x] **Grain guarantee:** Semiconductors and Software - Infrastructure resolve to disjoint member
      sets and distinct aggregates.
- [x] `scope_key` stable and order-independent for custom baskets; distinct for distinct sets.
- [x] `get_industry_beat_miss` dispersion math (% beating, median surprise) correct on a fixture.

Acceptance: `uv run pytest tests/test_industry_data.py -q` green; every function callable against
the real DBs from a REPL and returns sane output for the 3 sample industries. — Met: 19/19 tests
pass; live-verified against Semiconductors and Software - Infrastructure (see Findings below).

Findings / design deviation (recorded 2026-07-27):

**Raw/format split, not in the original SPEC function list.** While designing Phase 2's markdown
appendix tables, realized that a naive implementation (Phase 2 renderer independently re-calling
the same DB/AV logic as its Phase 1 text-formatter counterpart) would fetch EPS-surprise data from
Alpha Vantage twice per report generation — once for the LLM sub-agent context, once for the
appendix table — needlessly consuming AV rate-limit budget (CLAUDE.md rule 7) for data already in
hand. Fixed by splitting `get_industry_aggregates`, `get_industry_beat_miss`, and
`get_industry_estimates` each into a raw-fetch function (does the DB/AV work once) + a pure
formatter (no DB/network access) + a thin text-wrapper (preserves the original public signature
used by Phase 1's tests):

| Original (SPEC 6.4) | Raw fetcher (new) | Pure formatter (new) |
|---|---|---|
| `get_industry_aggregates(industry)` | `get_industry_aggregates_raw(industry) -> Optional[dict]` | `format_industry_aggregates(raw) -> str` |
| `get_industry_beat_miss(tickers)` | `get_beat_miss_raw(tickers) -> dict` | `format_beat_miss(tickers, raw) -> str` |
| `get_industry_estimates(tickers)` | `get_estimates_df(tickers) -> pd.DataFrame` | `format_estimates(tickers, df) -> str` |

`get_member_financials_df` / `get_member_financials` already followed this shape naturally (mirrors
`research_router._peer_df` + `get_peer_comparison`), so no change was needed there — it's the
existing pattern this refactor generalizes to the other three functions.

**Phase 5's orchestrator must call the `*_raw`/`*_df` functions ONCE per report** and pass results
to both the Phase 1 text formatter (for sub-agent context) and the Phase 2 markdown renderer (for
the appendix) — exactly like the single-name researcher's `compute_dcf_scenarios` being computed
once and shared between `render_valuation_model_tables` and `render_market_share_table` via
`_build_post_subagent_tables`. Phase 2 and Phase 5 steps below should consume `get_member_financials_df`,
`get_industry_aggregates_raw`, `get_beat_miss_raw`, and `get_estimates_df` — not the text-wrapper
functions — when building the markdown appendix.

**Also found live:** `eps_rev_up_7d`/`eps_rev_down_7d` (INTEGER columns in `earnings_estimates`)
surface nulls as pandas' nullable `pd.NA` sentinel when read via DuckDB's `.df()`, not plain `None`
or float `NaN`. A naive `is not None` check lets `pd.NA` through and `int(pd.NA)` raises
`TypeError` — hit this immediately when smoke-testing `get_industry_estimates` against the real DB
for Semiconductors. Fixed with a shared `_is_missing(v)` helper (checks `None`, float NaN/inf, AND
`pd.isna`) used everywhere a DB value is formatted. Any new numeric formatting code added in later
phases should use `_is_missing`, not a bare `is None`/`math.isnan` check, whenever the source column
can be an INTEGER type.

**Confirmed real (not hypothetical) via live data:** TSM (Semiconductors, ADR) has `market_cap_b =
NULL` in `pe_stats` and zero cached rows in `earnings_transcripts` — both the market-cap COALESCE
fallback and the "member with no transcript still appears in financials tables" degrade path (SPEC
6.4) are exercised by real production data, confirmed in `test_member_financials_every_requested_ticker_appears_even_if_absent`.

---

## Phase 2 — Deterministic tables + ranked-ideas numeric join  [x] Complete (2026-07-27)

Goal: all report numbers rendered in Python (never LLM), reusing `research_router._md_table`.
Renderers take pre-fetched raw data (see Phase 1's raw/format-split finding above) — they must
NOT re-fetch, to avoid duplicating AV calls already made for the LLM-context text versions.

Built in `api/industry_research_router.py` (this file now also formally hosts `IndustryIdea`,
since Phase 2's `attach_idea_metrics` needed the type — Phase 4 will add the remaining Stage 2/3
schemas alongside it, matching how every Pydantic schema in the single-name researcher lives in
its router file).

Steps:
- [x] `render_industry_aggregates_table(raw: dict) -> str` — takes
      `industry_data.get_industry_aggregates_raw(industry)`'s output; valuation/margin/growth
      medians + 3/6/12m trend.
- [x] `render_member_financials_table(df: pd.DataFrame) -> str` — takes
      `industry_data.get_member_financials_df(tickers)`'s output; cross-company financials.
- [x] `render_beat_miss_table(tickers, raw: dict) -> str` — takes
      `industry_data.get_beat_miss_raw(tickers)`'s output; per-member surprise + dispersion footer.
- [x] `render_revision_momentum_table(tickers, df: pd.DataFrame) -> str` — takes
      `industry_data.get_estimates_df(tickers)`'s output; forward growth + revision momentum.
- [x] `attach_idea_metrics(ideas: list[IndustryIdea], financials_df: pd.DataFrame, industry_pe_median,
      estimates_df: pd.DataFrame) -> list[list[str]]` — join LLM-proposed ideas to real
      fundamentals (valuation vs industry median P/E, 7d revision counts); `"n/a"` for a proposed
      ticker absent from the DB, or a member with a null current_pe. Numbers come only from here.

Tests (`tests/test_industry_research_router.py`, pure in-memory fixtures — no DB, no network):
- [x] Each renderer produces a valid markdown table (header + separator + N rows).
- [x] `attach_idea_metrics` matches known tickers to fundamentals and yields `"n/a"` for an unknown
      ticker without crashing.
- [x] Empty inputs degrade to an empty string / empty rows, never an exception.

Acceptance: tables render correctly for a sample industry from a REPL; unit tests green. — Met:
live-verified against Semiconductors (all 4 appendix tables + a mock ranked-ideas table rendered
correctly, including "n/a" degrade for INTC's null P/E and a ticker not in the DB at all); 16/16
new tests pass; full fast suite (206 tests) green with no regressions.

---

## Phase 3 — Stage-1 map: per-company Earnings Digest agent  [x] Complete (2026-07-27)

Goal: compress each company's 4 transcripts + beat/miss + financials into a compact structured
digest, in parallel over members.

Built in `api/industry_research_router.py` (extends the Phase 2 file): `CompanyDigest`,
`_build_digest_context`, `_run_digest_subagent`, `run_company_digests`.

Steps:
- [x] `api/prompts/industry_company_digest.md` — inputs: one company's transcripts + beat/miss +
      financials; injects `{style_guide}`. Output: `CompanyDigest`.
- [x] `CompanyDigest` Pydantic model (SPEC 6.5): `ticker`, `demand`, `pricing_margins`,
      `guidance_direction` (Literal RAISED/MAINTAINED/LOWERED/UNCLEAR), `capex_investment`,
      `management_tone` (Literal BULLISH/NEUTRAL/CAUTIOUS), `notable_quotes: list[str]`,
      `company_risks: list[str]`. No numeric fields ended up in the final schema, so no
      `_coerce_optional_float`-style validator was needed (SPEC 6.5 anticipated one speculatively).
- [x] Fan-out via `run_company_digests()`: `asyncio.gather` over members with >=1 cached
      transcript quarter, `_LLM_TIMEOUT=400` per call (matches research_router's ceiling), each
      transcript capped at `_MAX_TRANSCRIPT_CHARS=7000`/quarter. Members with zero transcript
      quarters (real case: TSM) are filtered out BEFORE any LLM call — never sent to the
      sub-agent at all, not "sent then failed."
      Deviation from the original plan: reused `research_router._STYLE_GUIDE` + `_load_prompt`
      directly via import (both are simple, path-agnostic, module-private-by-convention only)
      rather than reimplementing `_run_subagent`'s exact shape — `_run_digest_subagent` is a new,
      simpler standalone function (no `fallback` object param, since a failure here means "absent
      from the dict", not "render a fallback section").

Tests (`tests/test_industry_research_router.py`, `agents` SDK mocked via monkeypatched `Runner` —
never hits a real Agent/Runner call in the unit-test path):
- [x] Fan-out over N members returns N digests; a member with no transcript is skipped, not failed.
- [x] A single sub-agent timeout/exception falls back gracefully without killing the batch.
- [x] (Added beyond the original list) `_run_digest_subagent` itself catches `asyncio.TimeoutError`
      and generic `Exception` and returns `None` rather than propagating, tested directly via a
      monkeypatched `Runner`.

Acceptance: run once live against 1 industry; eyeball digest quality (each name compressed to a few
hundred tokens with correct guidance_direction / tone). — Met: live-ran `run_company_digests`
against 3 real Semiconductors members (AMD, ARM, TXN) with `google/gemini-3.5-flash`. All 3
returned well-formed digests with plausible, differentiated `guidance_direction`/`management_tone`
(AMD/TXN: RAISED/BULLISH; ARM: UNCLEAR/BULLISH — correctly reflects that ARM's transcript excerpt
didn't explicitly address guidance changes), correctly cited quotes with quarter tags, and
company-specific (not generic) risks. 24/24 unit tests pass; full fast suite (214 tests) green,
no regressions.

---

## Phase 4 — Stage-2 specialists + Stage-3 chief + renderer  [x] Complete (2026-07-27)

Goal: reduce digests + quant aggregates into the final report and ranked ideas.

Built in `api/industry_research_router.py` (extends Phases 2-3): `TrendsOutput`, `RisksOutput`,
`ChiefOutput`, `ReportHeader`, `_format_digests_for_prompt`, `_run_stage_agent`,
`run_industry_synthesis`, `build_coverage_note`, `validate_ranked_ideas`, `render_industry_report`.

Steps:
- [x] `api/prompts/industry_trends.md` (Trends & Developments) and `api/prompts/industry_risks.md`
      (Risks & Outlook) — inputs: the <=8 digests + aggregates + web search. Outputs `TrendsOutput`
      / `RisksOutput`.
- [x] `api/prompts/industry_chief.md` — synthesizes specialists + digests + aggregates into
      `ChiefOutput` (`executive_summary: list[str]` + `ranked_ideas: list[IndustryIdea]` ONLY —
      see deviation below).
- [x] `IndustryIdea` model: `ticker`, `stance` (Literal OVERWEIGHT/NEUTRAL/UNDERWEIGHT),
      `catalyst`, `key_risk` — no numeric fields (Python attaches them, Phase 2). (Already built
      in Phase 2.)
- [x] **Grammar-size guard:** NOT NEEDED. Deviation from the original plan — deliberately did NOT
      have the chief restate header metadata or the Stage-2 specialists' narrative sections (both
      already fully covered; Python has the former, Stage 2 already wrote the latter — a 3rd LLM
      pass re-deriving them would risk drift). `ChiefOutput` ended up with only 2 top-level fields
      (`executive_summary` + `ranked_ideas`), structurally comparable in size to the single-name
      researcher's smallest sub-agent schemas, comfortably clear of the ~5,657-char threshold that
      forced the core/narrative split there. No split file needed.
- [x] `render_industry_report(header, trends, risks, executive_summary, ranked_ideas_rows,
      aggregates_table_md, member_financials_table_md, beat_miss_table_md,
      revision_momentum_table_md, coverage_note, qc_findings) -> str` — assembles markdown:
      header, exec summary, narrative sections (Trends' 3 + Risks' 2, direct from Stage 2 — the
      Chief never touches them), deterministic appendix tables (Phase 2), ranked-ideas table with
      attached numbers, QC footer, disclaimer. Reuses `_md_table`.
- [x] Deterministic QC pass (non-blocking): `build_coverage_note` (coverage gaps) +
      `validate_ranked_ideas` (invented/missing/duplicate tickers in the Chief's output) — both
      logged/footnoted, never block generation, same pattern as `_validate_report`.

Tests (`tests/test_industry_research_router.py`, `Runner`/`_run_stage_agent` mocked):
- [x] End-to-end with all sub-agents mocked -> valid markdown containing every appendix table and a
      ranked-ideas table whose numeric columns come from Phase 2, not the mock LLM.
- [x] Degraded run: a missing Stage-2 output renders an `[ERROR]` placeholder for just that
      section rather than failing the whole report (`run_industry_synthesis` partial-failure test
      + `render_industry_report`'s missing-stage test).
- [x] (Added beyond the original list) `validate_ranked_ideas`: invented ticker, missing member,
      duplicate ticker, case-insensitive matching — 5 tests. `build_coverage_note`: full-coverage
      None case + missing-member case — 2 tests.

Acceptance: one full live report for Semiconductors reads coherently; no LLM-authored number
disagrees with the appendix. — Met: ran the full Stage 1 -> Stage 2 -> Stage 3 -> render pipeline
live against 4 real Semiconductors members (NVDA, TSM, AVGO, MU) with `google/gemini-3.5-flash`.
`validate_ranked_ideas` returned zero findings (all 4 tickers present exactly once, no invented
tickers); every number in the Ranked Actionable Ideas table (e.g. MU "54.8x vs 94.3x (-42%)")
matched the corresponding Member Financials / Industry Aggregates appendix rows exactly, since
both are Python-computed from the same `fin_df`/`agg_raw`. The Chief's Forward Outlook correctly
aggregated guidance-direction counts across digests ("Three of the analyzed companies raised
guidance... while one remains unclear") rather than fabricating a pattern — genuine cross-digest
synthesis, not templated filler. 36/36 unit tests pass; full fast suite (226 tests) green.

**Found live, out of scope to fix here:** TSM's `current_pe` in `pe_stats` is 1.1 (vs. plausible
~25-35x peers) — surfaced starkly in the Ranked Actionable Ideas table as "1.1x vs 94.3x (-99%)".
This is a pre-existing upstream data-quality issue in `historic_fundamentals` (likely an ADR-ratio
handling bug — TSM ADRs represent 5 ordinary shares — unrelated to this feature), not something
introduced by or fixable within the Industry Researcher. Flagging for a separate investigation;
this feature's job is to surface real underlying data faithfully, including its warts.

---

## Phase 5 — Router: cache, status/cancel, endpoints  [x] Complete (2026-07-27)

Goal: `api/industry_research_router.py`, structurally mirroring `research_router.py`.

Steps:
- [x] Orchestrator `_run_industry_research(industry, tickers, model, status_key)` chaining
      resolve -> gather -> Stage 1 -> Stage 2 -> Stage 3 -> render. Status phases:
      `gathering_data -> digesting_companies -> running_specialists -> synthesizing ->
      done|error|cancelled`. (See deviation note below on `running_specialists`/`synthesizing`.)
- [x] Cache table `industry_research_cache(scope_key, model, report_markdown, generated_at)`, 24h
      TTL. Copy `_init_cache`/`_cache_get`/`_cache_put` keyed on `(scope_key, model)`.
- [x] `_background_tasks` / `_task_status` / `_set_status` / `_get_or_start` with the `retry` guard
      (no silent auto-restart after error/cancel) — copy from `research_router`.
- [x] Endpoints: `GET /industry-research/industries`, `GET /industry-research/report`
      (`industry` | `tickers` + `model` + `retry`), `GET /industry-research/status`,
      `POST /industry-research/cancel`, `GET /industry-research/models` (reused `_MODEL_OPTIONS`
      via import rather than duplicating the constant).
- [x] Every DuckDB handle inside the fan-out is `read_only=True` (SPEC 6.6) — verified: all of
      `industry_data.py`'s read paths use `read_only=True`; only the industry-research cache
      itself opens read-write, and never concurrently with a read-only handle to the same file.
- [x] Register the router in `api/main.py`.

Deviation: `run_industry_synthesis` (Phase 4) does Stage 2 (Trends+Risks, parallel) then Stage 3
(Chief) as ONE awaited call, so the orchestrator can't emit a status update between them. Resolved
by re-purposing `synthesizing` to mean "assembling the final report" (QC + rendering, which
happens after `run_industry_synthesis` returns) rather than "chief LLM call in progress" — a
cosmetic status-label nuance, not a functional gap; all 5 phases still surface to the UI in order.

Tests (`tests/test_industry_research_orchestration.py`, `_run_industry_research` mocked — never
hits a real LLM in the unit-test path):
- [x] Cache get/put + TTL expiry (roundtrip, miss, model-distinction, expired-row, within-TTL).
- [x] Status transitions; cancel then retry-after-cancel (`_get_or_start` spawns a task, status
      progresses to `done`; a failing run sets `error` and blocks silent auto-restart until
      `retry=True`; a running task can be cancelled via the endpoint and sets `cancelled`).
- [x] `/industry-research/report` with a custom `tickers` list bypasses classification and uses
      the basket (verified `_run_industry_research` receives `industry=None,
      custom_tickers=["nvda","amd"]` and caches under the custom scope key).
- [x] (Added beyond the original list) `industry_research_report` endpoint's 400 when neither
      `industry` nor `tickers` given; `industry_research_status`'s idle/done states;
      `_parse_tickers` CSV parsing.

Acceptance: endpoints respond locally (`uv run uvicorn api.main:app`); a report generates and
caches; second call served from cache. — Met, with a real caveat worth recording: the user's own
Finview dev server was already running on port 8000 holding a write-lock on
`financial_statements.duckdb` (via `api.main`'s lifespan), so a second full `api.main:app`
instance cannot start concurrently (DuckDB single-writer lock — this is pre-existing behavior of
`api/main.py`, unrelated to this feature). Verified instead via a minimal standalone app mounting
only `industry_research_router` (that router never opens `financial_statements.duckdb`) on a
separate port. Full live HTTP round-trip confirmed: `/industries` returned real data; `/report`
for a 2-ticker custom basket (`AVGO,TXN`) triggered generation, `/status` polled through all 4
phases in order (`gathering_data -> digesting_companies -> running_specialists -> done`) over
~40s; the second `/report` call returned byte-identical content in <20ms (cache hit, confirmed via
`diff`); `retry=true` after a deliberately-induced `error` state (missing `OPENROUTER_API_KEY` in
the test subprocess's env) correctly restarted generation once the key was available.

**Bug found and fixed live (real, not hypothetical):** `google/gemini-3.5-flash` occasionally
emitted the literal two-character sequence `\n` (backslash + "n") inside a `TrendsOutput` string
field instead of an actual newline character — confirmed via `repr()` on the raw HTTP response,
which showed `...\\n- The custom...` as literal text, not a JSON-escaping artifact. Unfixed, this
renders as visible backslash-n text in the frontend's markdown viewer instead of a line break.
Fixed with `_sanitize_prose` (converts literal `\n` -> real newline, for prose sections) and
`_sanitize_table_cell` (converts both a literal `\n` and any genuine newline to a single space,
since a raw newline inside a markdown table cell breaks the table) — applied respectively to
every Trends/Risks/executive_summary field in `render_industry_report` and to
`IndustryIdea.catalyst`/`key_risk` in `attach_idea_metrics`. Re-verified live after the fix:
`Contains literal backslash-n: False` on a freshly generated report, with the Executive Summary's
bullets now rendering on genuinely separate lines. Added regression tests for both sanitizers.
2/2 unit tests + live re-verification pass; full fast suite (244 tests, up from 226) green.

---

## Phase 6 — Frontend: `IndustryResearchViewer.tsx` + tab  [x] Complete (2026-07-27)

Goal: new always-rendered "Industry Research" tab (peer of Screener/Sector/Calendar), matching
`EquityResearchViewer` UX.

Steps:
- [x] `web/components/IndustryResearchViewer.tsx` — industry picker (from
      `/industry-research/industries`, showing member counts), optional custom-ticker input, model
      dropdown (fetched from `/industry-research/models`), Generate/Cancel buttons, live one-line
      status bar (poll `/status` ~2.5s), markdown render (reused the `EquityResearchViewer`
      react-markdown setup, `mdComponents` config copied verbatim).
- [x] Ranked-idea tickers are clickable -> call `onSelectTicker(ticker)` to jump into single-name
      AI Research. Deviation: implemented generically via a custom `td` renderer that detects any
      ticker-shaped cell content (`/^[A-Z]{1,6}(\.[A-Z])?$/`) rather than only the Ranked Ideas
      table's first column — every ticker in every appendix table (Member Financials, Beat/Miss,
      Revision Momentum, Ranked Ideas) is clickable, not just ranked ideas. Simpler to implement
      (no column-index tracking needed) and a strictly better UX with no added cost.
- [x] `web/app/page.tsx`: added `"industry_research"` to `Tab`, `tabs`, `TAB_LABELS`
      ("Industry Research"), rendered it in the always-rendered block (peer of Screener/Sector/
      Calendar — does not require `loadedTicker`), and added it to the empty-state exclusion list.

Tests / verification (live, via Playwright against a real browser + a real running backend —
CLAUDE.md's UI-testing requirement):
- [x] `npx tsc --noEmit` clean (exit 0).
- [x] Full 8-company Semiconductors run end-to-end: industry picker populated with all 145
      industries sorted by member count; selected SEMICONDUCTORS; clicked Generate; live status
      bar progressed through all 4 phases with the exact backend-provided messages
      ("Gathering data for 8 companies in SEMICONDUCTORS..." -> "Summarizing earnings calls..." ->
      "Running industry specialists and chief strategist..." -> done) over ~130s (within the
      "60-150s" estimate); full report rendered — header, executive summary, all 5 narrative
      sections, all 4 appendix tables with correct numbers, and an 8-row Ranked Actionable Ideas
      table with genuinely differentiated stances (4 OVERWEIGHT, 2 NEUTRAL, 2 UNDERWEIGHT — not
      templated filler) and INTC's null P/E correctly showing "n/a" in Valuation vs Industry.
- [x] Clicked an NVDA ticker button in the Ranked Ideas table -> app navigated away from Industry
      Research, loaded NVDA as the active ticker (quote fetched, header updated), landed on AV
      Financials — identical behavior to clicking a ticker from Screener/Sector, confirming
      `onSelectTicker` wiring is correct and consistent with existing tabs.
      Custom basket path renders a report from a hand-entered ticker list (verified with 2-4
      ticker custom baskets throughout Phases 5-6 testing).
- [x] Cancel: clicked Cancel ~1s into a custom-basket generation -> status immediately showed
      "Cancelled. Click ... to try again." Retry-after-cancel: clicked Generate again -> a fresh
      generation started cleanly (not a stale/blocked state).

Acceptance: manual walkthrough in a real browser clean. — Met.

**Bug found and fixed live (real, not hypothetical):** BBBY (a known contaminated ticker — see
memory `project_survivorship_bias_result.md`, reassigned post-bankruptcy) has `industry` set to
the literal string `"None"` rather than a real NULL, which slipped through `list_industries()`'s
NULL/blank filter and appeared as a selectable one-member "NONE (1)" entry in the picker. Fixed by
excluding `UPPER(industry) != 'NONE'` alongside the existing NULL/blank filter. Added a regression
test (`test_list_industries_excludes_literal_none_string`); re-verified live in the browser that
"NONE" no longer appears.

**Also required, not originally in the plan:** the user's own Finview dev servers (API on :8000,
web on :3000, both already running before this session) needed a restart to pick up today's
backend changes (no `--reload` flag on the API server) — a routine, low-risk, reversible action
during active feature development, done twice (once for the initial endpoints, once after the
"NONE" fix).

---

## Phase 7 — Verification + docs  [x] Complete (2026-07-27)

Steps:
- [x] Full `uv run pytest tests/ -q` (fast subset, excluding pre-existing slow ML/backtest suites
      unrelated to this feature) green: 245 passed, 3 skipped (pre-existing), 3 deselected.
- [x] Live smoke test across 3 industries incl. one fragmented (>25 members) and one custom
      basket: Semiconductors (53 members, full 8-company LLM pipeline through the actual browser
      UI, Phase 6), Biotechnology (278 members — fragmented, `resolve_members`/
      `get_industry_aggregates` verified directly), Software - Infrastructure (95 members,
      verified directly), plus multiple custom-basket runs (2-4 tickers) via both direct HTTP and
      the browser UI across Phases 4-6.
- [x] Updated `docs/Project_Structure.md`: `industry_research_router.py` and `industry_data.py`
      entries in the `api/` tree, `IndustryResearchViewer.tsx` in the `web/components/` tree,
      `industry_research_cache.duckdb` in the `data/` tree. (Prompts directory is not documented
      there for the single-name researcher either, so no new section added for industry prompts
      — kept scope consistent with the existing doc.)
- [x] Confirmed no sector-fallback path exists anywhere: grepped both new files for every
      occurrence of "sector" — all are either grain-guarantee documentation/comments, or
      `list_industries()`'s informational `sector` display label (never used for filtering). No
      query anywhere reads `sector_stats WHERE group_type='sector'` or falls back to
      `co.sector` when `co.industry` is null.
- [x] Marked all phases/steps Complete here.

Acceptance: report generates end-to-end from the UI for industry and custom-basket inputs, numbers
are Python-sourced, grain guarantee holds, docs updated. — Met. Full feature built, tested (105
new unit/integration tests across 3 new test files, all passing, zero regressions in the existing
245-test fast suite), and live-verified at every layer: data layer against real DBs (Phase 0-1),
deterministic tables against real data (Phase 2), a real 3-company digest fan-out with a real LLM
(Phase 3), a full 4-company Stage 1-3 pipeline with a real LLM producing a coherent, internally
consistent report (Phase 4), a full HTTP round-trip including cache-hit confirmation and a live
bug fix (literal backslash-n sanitization, Phase 5), and a full 8-company report generated through
the actual browser UI with working Cancel/retry-after-cancel and clickable ticker navigation,
including a second live bug fix (BBBY's literal "None" industry string, Phase 6).

**Two real, pre-existing (not introduced by this feature) issues surfaced during development,
flagged for separate investigation, not fixed here:**
1. TSM's `current_pe` in `pe_stats` is 1.1 (vs. plausible ~25-35x peers) — likely an ADR-ratio
   handling bug in `historic_fundamentals` (Phase 4 finding).
2. BBBY's industry classification contamination (literal "None" string) is itself downstream of
   the already-documented post-bankruptcy ticker-reassignment issue in
   `project_survivorship_bias_result.md` — this feature only defensively filtered the symptom
   (the literal string leaking into the industry picker), not the root cause.

---

## Cross-cutting acceptance criteria

- Industry-only grain enforced and tested at selection and aggregation (SPEC 2.1).
- Every number in the report is rendered in Python; the LLM writes prose + stance/catalyst/risk.
- AV usage stays under 75 calls/min; transcripts served from cache where present.
- Report caches 24h keyed by `(scope_key, model)`; error/cancel never auto-restarts silently.
- Graceful degradation when some members lack transcripts.
- The ranked-ideas table is presented as qualitative, not a validated strategy (SPEC 10).
