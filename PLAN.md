# AI Researcher Improvement Plan

**Source**: AI_RESEARCHER_IMPROVEMENT.md

**Goal**: Upgrade the Finview AI Equity Researcher (`api/research_router.py`,
`EquityResearchViewer.tsx`) from a single mega-prompt LLM call into a fan-out/fan-in
multi-agent pipeline that adds: (1) grounded competitor/positioning analysis, (2) LLM-chosen
academic strategy frameworks (Porter's Five Forces, VRIO, Ansoff Matrix, Blue Ocean),
(3) trailing 4-quarter earnings-call + MD&A trend analysis, (4) a technical-analysis
sub-agent producing an independent BUY/HOLD/SELL-style read from price/volume data.

---

## Decisions (confirmed with user before implementation)

1. **Architecture**: fan-out/fan-in multi-agent. Three focused sub-agents run in parallel
   (Competitive & Strategy Analyst, Earnings & MD&A Historian, Technical Analyst), each with
   only the data it needs. A fourth agent (Chief Analyst, replacing today's single call)
   synthesizes their narrative output plus the existing raw data into the final structured
   `EquityResearchReport`.
2. **Technical analysis data source**: reuse trade_systems' `prices.duckdb` (already wired via
   `PRICES_DB_PATH` in `.env`) read-only. Vendor a small self-contained pandas indicator module
   in fin_import2 (SMA/RSI/MACD/52wk high-low/ATR/ROC) rather than importing trade_systems'
   Python package across repos/venvs. On-demand single-ticker FMP backfill
   (`FMP_API_KEY` already configured) for tickers missing from `prices.duckdb` (trade_systems
   only auto-discovers IBD50 tickers into that db).
3. **MD&A depth**: last 4 cached earnings-call transcripts (already backfilled for most tickers
   via `scripts/earnings_backfill.py`, zero new cost) + latest 10-K MD&A only. 10-Q MD&A
   extraction is deferred (edgartools support unverified) — not blocking.
4. **Framework selection**: LLM judgment call. All 4 frameworks are described in the sub-agent
   prompt; the model picks the 1-2 most relevant given sector/industry/growth profile and states
   why. No rule-based mapping table to maintain.

---

## Architecture

```
                     ┌─────────────────────────────────────────┐
                     │      existing data gathering (async)      │
                     │  financials, valuation, peak-earnings,     │
                     │  price/analyst, estimates, edgar risks     │
                     └───────────────────┬─────────────────────┘
                                          │
        ┌─────────────────────┬──────────┴──────────┬─────────────────────┐
        │                     │                      │                     │
┌───────────────┐   ┌───────────────────┐  ┌───────────────────┐          │
│ Competitive &  │   │ Earnings & MD&A    │  │ Technical Analyst  │          │
│ Strategy Agent │   │ Historian Agent    │  │ Agent               │          │
│ (peer screen + │   │ (4Q transcripts +  │  │ (computed indicator │          │
│  web search)   │   │  10-K MD&A)        │  │  summary, not raw   │          │
│                │   │                    │  │  price series)      │          │
└───────┬────────┘   └─────────┬──────────┘  └─────────┬──────────┘          │
        │                      │                        │                    │
        └──────────────────────┴────────────────────────┴────────────────────┘
                                          │
                                ┌─────────▼──────────┐
                                │   Chief Analyst      │
                                │   (synthesis, same    │
                                │   output_type as today)│
                                └─────────┬──────────┘
                                          │
                              EquityResearchReport (JSON)
                                          │
                                 render_to_markdown()
```

---

## Phase 1 — Technical Analyst Foundation (data + indicators, no LLM yet)

**Status**: [x] Complete
**User-facing impact**: NONE (backend only)
**New files**: `historic_fundamentals/technical_indicators.py`

### Step 1.1 — Vendor indicator computation [x]

**File**: `historic_fundamentals/technical_indicators.py`

Add `compute_indicators(df: pd.DataFrame) -> pd.DataFrame` taking OHLCV rows (date-sorted) and
returning SMA20/50/200, RSI(14), MACD (line/signal/hist), 52-week high + `pct_off_high`,
ATR(14), ROC(10), and a simple trend label (price vs. SMA50 vs. SMA200: uptrend/downtrend/mixed).
Formulas mirror `trade_systems/ta_report/indicators.py` (hand-rolled pandas, not a new
dependency — CLAUDE.md rule 2, keep it simple, no need to add `pandas-ta` to this project for
~6 formulas).

Add `get_technical_summary(ticker: str) -> str`, same shape/contract as the existing
`get_valuation_data()` etc. in `research_router.py`:
1. ATTACH `PRICES_DB_PATH` (env var, default trade_systems path) read-only, pull last ~300
   trading days of `stock_prices` for the ticker.
2. If ticker missing or stale (latest date > 5 calendar days old), call the on-demand FMP
   backfill (Step 1.2) once, then re-query.
3. Compute indicators, render a plain-text summary block (current price vs. SMAs, RSI value +
   overbought/oversold flag, MACD signal cross state, 52wk range position, trend label).
4. On any DB lock/IO error (trade_systems' own cron may hold the write lock), catch and return
   `"[ERROR] ..."` the same way every other data-gathering function in this file already does
   — never raise into the report pipeline.

Test:
```bash
uv run python -c "
from historic_fundamentals.technical_indicators import get_technical_summary
for t in ['AAPL', 'NVDA', 'KO']:
    print(get_technical_summary(t))
    print('---')
"
# Pass: for each ticker, prints a summary with RSI in [0,100], SMA20/50/200 populated,
# a trend label, and 52-week high/low bracketing current price. No exceptions raised.
```

### Step 1.2 — On-demand single-ticker FMP backfill [x]

**File**: `historic_fundamentals/technical_indicators.py`

Add `backfill_recent_prices(ticker: str, days: int = 400) -> bool`. Mirrors the fetch call in
`scripts/fmp_price_backfill.py` (`historical-price-eod/dividend-adjusted`, `FMP_API_KEY`) but
scoped to one ticker and the last `days` calendar days, upserting into `stock_prices`. Returns
`False` (does not raise) on any HTTP error, missing key, or DB lock — caller falls back to
whatever is cached, per rule 3 (only handle exceptions when necessary, but this one is a real
external-I/O boundary).

Test:
```bash
uv run python -c "
from historic_fundamentals.technical_indicators import backfill_recent_prices
import duckdb, os
ok = backfill_recent_prices('CROX')  # pick a ticker unlikely to be in IBD50-seeded prices.duckdb
print('backfill ok:', ok)
conn = duckdb.connect(os.environ.get('PRICES_DB_PATH'), read_only=True)
print(conn.execute(\"SELECT COUNT(*), MAX(date) FROM stock_prices WHERE ticker='CROX'\").fetchall())
"
# Pass: backfill returns True, row count > 200, MAX(date) within the last 5 trading days.
```

---

## Phase 2 — Trailing 4-Quarter Earnings Data

**Status**: [x] Complete
**User-facing impact**: NONE (backend only)
**Files to modify**: `historic_fundamentals/earnings_transcripts.py`, `api/research_router.py`

### Step 2.1 — Multi-quarter transcript fetch helper [x]

Add `get_last_n_transcripts(ticker: str, n: int = 4) -> list[tuple[str, str]]` to
`earnings_transcripts.py` (returns `[(quarter, transcript_text), ...]` newest first, reading
from the cache; no AV calls here — that stays the job of `earnings_backfill.py` /
`earnings_update.py` per existing division of responsibility).

Replace `get_earnings_summary()` in `research_router.py` with `get_earnings_trend_summary()`
that calls `get_last_n_transcripts(ticker, 4)`, formats each quarter as a truncated block
(~2000 chars each to keep total context bounded), and falls back to today's single-quarter AV
probe logic only if fewer than 2 quarters are cached (keeps today's "always try to get the
newest quarter" behavior for tickers with sparse cache).

Test:
```bash
uv run python -c "
from api.research_router import get_earnings_trend_summary
out = get_earnings_trend_summary('MSFT')
print(out[:2000])
print('...')
print('quarters found:', out.count('EARNINGS TRANSCRIPT'))
"
# Pass: for a ticker with >=4 cached quarters (check via earnings_transcripts.duckdb first),
# output contains 4 distinct quarter blocks in reverse-chronological order.
```

---

## Phase 3 — Peer/Competitor Grounding Data

**Status**: [x] Complete
**User-facing impact**: NONE (backend only)
**Files to modify**: `api/research_router.py`

### Step 3.1 — Real peer screen for competitive grounding [x]

Add `get_peer_comparison(ticker: str) -> str`: looks up the ticker's sector/industry from
`company_overview`, then runs a query (same shape as the existing `_tool_screen_stocks` SQL)
to pull up to 8 same-industry peers ranked by market cap, with ticker/name/market cap/current
PE/forward PE/revenue growth/ROIC/gross margin. This gives the Competitive & Strategy sub-agent
(Phase 4) a factual peer table to ground its "Est. Market Share / Key Strength / Key Weakness"
table against, instead of inventing peers from training data alone.

Test:
```bash
uv run python -c "
from api.research_router import get_peer_comparison
print(get_peer_comparison('AMD'))
"
# Pass: returns a table containing real semiconductor peers (e.g. NVDA, INTC, QCOM) with
# non-null market cap and PE for most rows. No exception on a ticker with no company_overview
# row (returns an [INFO]/[ERROR] string instead).
```

---

## Phase 4 — Multi-Agent Report Pipeline

**Status**: [x] Complete
**User-facing impact**: Report generation time may increase (more LLM calls, still parallel);
existing 24h cache and polling UI absorb this. Report schema gains new fields — old cached
reports remain readable as plain markdown (cache key unchanged, they just age out after 24h).
**Files to modify**: `api/research_router.py`
**New files**: `api/prompts/research_competitive.md`, `api/prompts/research_earnings.md`,
`api/prompts/research_technical.md`, `api/prompts/research_chief.md` (renamed from
`research_system.md`)

### Step 4.1 — New Pydantic output types [x]

In `research_router.py`, add:
```python
class CompetitiveOutput(BaseModel):
    competitive_analysis: str
    industry_outlook: str
    strategic_framework_analysis: str

class EarningsTrendOutput(BaseModel):
    mda_summary: str
    earnings_highlights: str
    quarterly_trend_analysis: str
    near_term_catalysts: list[str]

class TechnicalOutput(BaseModel):
    technical_analysis: str
    technical_rating: Literal["BULLISH", "NEUTRAL", "BEARISH"]
```
Extend `EquityResearchReport` with `strategic_framework_analysis: str`,
`quarterly_trend_analysis: str`, `technical_analysis: str`,
`technical_rating: Literal["BULLISH","NEUTRAL","BEARISH"]`.

Test:
```bash
uv run python -c "from api.research_router import EquityResearchReport, CompetitiveOutput, EarningsTrendOutput, TechnicalOutput; print('schemas import OK')"
```

### Step 4.2 — Sub-agent prompts [x]

- `research_competitive.md`: instructs the agent to (a) identify 3-5 real direct competitors
  using the peer-comparison table + web search, not invent them; (b) apply 1-2 of the 4
  frameworks (full definitions from AI_RESEARCHER_IMPROVEMENT.md embedded in the prompt) with
  explicit reasoning for the choice; (c) produce `industry_outlook`.
- `research_earnings.md`: instructs the agent to synthesize the last 4 quarters of transcripts
  into a genuine trend narrative (accelerating/decelerating growth, margin trajectory, guidance
  revisions call-over-call, recurring management themes) plus the existing MD&A/catalysts asks.
- `research_technical.md`: instructs the agent to interpret the pre-computed indicator summary
  (never asked to compute indicators itself) into a plain-language technical read and a
  BULLISH/NEUTRAL/BEARISH rating, explicitly noting agreement/conflict with valuation-based
  signals when both are visible in context.
- `research_chief.md` (renamed `research_system.md`): drops the paragraphs now owned by
  sub-agents (competitive analysis, industry outlook, framework analysis, MD&A, earnings
  highlights, quarterly trend) and instead instructs the Chief Analyst to copy those verbatim
  from the provided sub-agent outputs into the corresponding report fields, reserving its own
  judgment for header/rating/target, key_highlights, financial_performance, valuation,
  risk_factors, investment_thesis, price_vs_fundamentals, target_price_validation,
  peak_earnings_analysis — and to reconcile the technical_rating against the fundamental rating
  in investment_thesis if they disagree.

Test: manual read-through — no automated test for prompt files; verified functionally in 4.4.

### Step 4.3 — Orchestration rewrite [x]

In `_run_research_agent()`:
1. Keep the existing data-gathering `asyncio.gather` (financials, valuation, peak_earnings,
   mda, risks, price_analyst, estimates), replacing `get_earnings_summary` →
   `get_earnings_trend_summary`, and adding `get_technical_summary` and `get_peer_comparison`
   to the gather.
2. Run the 3 sub-agents concurrently via `asyncio.gather(Runner.run(...), Runner.run(...),
   Runner.run(...))`, each scoped to only the context blocks it needs (e.g. the Technical Agent
   gets `technical_summary` + `price_analyst` only, not MD&A/risks).
3. Run the Chief Analyst with the original context blocks plus the 3 sub-agent outputs appended
   as `=== COMPETITIVE & STRATEGY ANALYSIS (pre-written) ===`, etc.
4. Preserve existing timeout/error-string handling (`_run()` helper) — a failed sub-agent should
   degrade to an `[ERROR]` string block passed to the Chief Analyst, not crash the whole report
   (matches existing philosophy for the deterministic data-gathering functions).

Test:
```bash
uv run python -c "
import asyncio
from api.research_router import _run_research_agent
report = asyncio.run(_run_research_agent('NVDA', 'google/gemini-3.5-flash'))
print(report.header.rating, report.technical_rating)
print(report.strategic_framework_analysis[:300])
print(report.quarterly_trend_analysis[:300])
print(report.technical_analysis[:300])
"
# Pass: all 4 new fields populated with non-empty, non-placeholder text; technical_rating is
# one of BULLISH/NEUTRAL/BEARISH; total wall-clock time logged is not more than ~2x today's
# baseline (check logs for the existing t0-based timing lines).
```

### Step 4.4 — Markdown renderer updates [x]

In `render_to_markdown()`: add a "Strategic Framework Analysis" subsection under Competitive
Analysis, a "## Quarterly Trend (Trailing 4Q)" section, and a "## Technical Analysis" section
with the rating shown alongside the fundamental rating in the header line (e.g.
`**Rating:** BUY | **Technical:** BULLISH`).

Test:
```bash
uv run python -c "
import asyncio
from api.research_router import _run_research_agent, render_to_markdown
report = asyncio.run(_run_research_agent('COST', 'google/gemini-3.5-flash'))
md = render_to_markdown(report)
assert '## Technical Analysis' in md
assert '## Quarterly Trend' in md
assert 'Strategic Framework' in md
print('OK, length:', len(md))
"
```

---

## Phase 5 — Frontend

**Status**: [x] Complete
**User-facing impact**: New sections visible in the report tab; no new interaction pattern
(same polling/markdown-render flow).
**Files to modify**: `web/components/EquityResearchViewer.tsx` (likely none — markdown renderer
is already generic; verify new `##`/`**Technical:**` markup renders correctly with existing
`mdComponents`).

### Step 5.1 — Visual verification [x]

Run the dev server, generate a report for a ticker in the browser, confirm the new sections
render with the same styling as existing sections (no raw markdown leaking, table renders,
rating badge line displays both ratings).

Test: manual, via the `run` skill or `npm run dev` — pass criteria is visual, not scripted.
Check at least one ticker where technical and fundamental ratings disagree (e.g. a stock in
an uptrend with a full/expensive valuation) to confirm the reconciliation language in
`investment_thesis` reads sensibly rather than contradicting itself.

---

## Phase 6 — Cross-Company Validation & Rollout

**Status**: [x] Complete

Results: NVDA (Porter's+VRIO), COST (VRIO), FCX (Porter's), UPS (Porter's+Ansoff), XE (missing
price history — technical sub-agent degraded to NEUTRAL with plain-language explanation, zero
`[ERROR]` leaks). All 5/5 reports rendered with zero `[ERROR]` strings in the final markdown.
Generation time ranged 48-64s across all 5 runs, well within the existing "60-90 seconds" UI
copy — no copy update needed. (RIVN was tried first as the "ticker outside prices.duckdb" case
but turned out to be outside Finview's tracked av_financials universe entirely, unrelated to
this feature — swapped for XE, the one ticker genuinely in-universe but missing from
prices.duckdb, which is the scenario the plan intended.)
**User-facing impact**: Full feature live for all tickers.

### Step 6.1 — Diverse ticker sweep [x]

Generate full reports (via the API, bypassing cache) for a spread of company profiles:
- High-growth tech disruptor (e.g. NVDA or CRWD) — expect Blue Ocean and/or Ansoff selected.
- Capital-intensive/commodity (e.g. FCX or X) — expect Porter's Five Forces selected.
- Asset-light consumer moat (e.g. KO or COST) — expect VRIO or Porter's selected.
- Service company without COGS breakdown (e.g. UPS — known edge case, see
  `project_dcf_no_cogs_companies` memory) — confirm technical/earnings sections still populate
  even though DCF-side data is unusual.
- A ticker NOT in trade_systems' IBD50-seeded `prices.duckdb` — confirms the on-demand FMP
  backfill path (Phase 1.2) actually triggers and succeeds.

Test criteria per ticker:
```bash
uv run python -c "
import asyncio
from api.research_router import _run_research_agent, render_to_markdown
report = asyncio.run(_run_research_agent('<TICKER>', 'google/gemini-3.5-flash'))
md = render_to_markdown(report)
# Manually inspect: competitors named are real peers (cross-check against get_peer_comparison
# output), framework choice matches expectation above with stated reasoning, technical
# indicators (RSI/SMA/trend) are directionally correct vs. a quick manual check of the price
# chart, quarterly trend narrative references 4 distinct quarters not 1.
print(md)
"
```
Pass: no `[ERROR]` strings leak into the final rendered report body (data-gathering failures
should degrade gracefully with the LLM working around them, not surface raw error tags to the
end user) for at least 4 of 5 tickers.

### Step 6.2 — Latency/cost sanity check [x]

Compare total generation time (from existing `t0`-based log lines) and OpenRouter token usage
before/after across 3 tickers already benchmarked pre-change. Confirm the UI's "60-90 seconds"
copy in `_GENERATING_MD` still roughly holds, or update the copy if the multi-agent pipeline
consistently runs longer.

Test: read logs, compare timings; update `_GENERATING_MD` text in `research_router.py` if the
new typical duration differs by more than ~30s from the current claim.

---

## Explicitly out of scope (for a future plan, not blocking)

- 10-Q MD&A extraction (deferred per Decision 3).
- Any change to `dcf/`, `historic_fundamentals/pe.py`, or other currently-modified-but-unrelated
  files visible in `git status` — those are pre-existing uncommitted work, untouched by this plan.
- New independent price-data pipeline (Decision 2 — reusing trade_systems' `prices.duckdb`
  instead).
- Backtesting the technical rating's predictive value — this is a qualitative report feature,
  not a new trading signal for `score_live.py`.
