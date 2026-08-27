# Project Status — Fundamentals Alpha + FinView

## AI DCF Guardrail Fixes (complete, 2026-08-27)

Prompted by reviewing two real AI Researcher reports (IBM, PEG): the Chief Analyst flagged a 2.0%
cost of debt as implausible against a 5.17% risk-free rate on IBM, and PEG's AI DCF authored
35-42% capex intensity that breached the guardrail's flat `[0%, 35%]` sanity bound, causing the
Chief to discount the AI DCF base case ($150.40 -> $135.00) and land on HOLD. Investigated both
before writing any code — neither was what it first looked like.

### What was found

**Cost of debt below the risk-free rate is not necessarily a bug.** `dcf/wacc.py::compute_cost_of_debt`
estimates an *embedded* rate (`avg_interest_expense / avg_total_debt`, clamped [2%, 15%]) — a
company that termed out debt at 2020-2021 zero-rate-era coupons can legitimately show an embedded
cost below today's risk-free rate. The real problem is narrower: `dcf/model.py` applies one flat
WACC to both the 5-year forecast and the terminal value, and an embedded rate that low is not a
defensible discount rate for the terminal value (existing debt will mature and refinance at
prevailing rates long before "forever" arrives). A time-varying WACC would need debt-maturity/
vintage data this pipeline doesn't have (Alpha Vantage fundamentals give only aggregate
`interest_expense` and aggregate debt balances) — out of scope; shipped a deterministic advisory
flag instead of a value change.

**The capex guardrail's flat 35% ceiling had no empirical basis and was miscalibrated by sector.**
Traced to `features/ai_dcf/SPEC.md` §6.5, introduced whole-cloth with no derivation shown. Pulled
actual capex/revenue from `av_financials.duckdb` across 2,581 tickers: the median *utility* alone
runs 37.98% (p90 62.4%) — already above the flat cap PEG was flagged against — while tech/
healthcare/consumer/financials medians run 1.2-2.7% (p90 4-23%), nowhere near it. The flat bound
was flagging normal capital-intensive-sector capex as anomalous while doing almost no work for
asset-light sectors. capex was also the only one of the four guardrail metrics with no
ticker-specific historical anchor — `ebit_margin_pct` and `cogs_pct` already compare against each
ticker's own history.

### What shipped

- **Cost-of-debt sanity warning** (`dcf/model.py::run_dcf_av`, next to the existing WACC<5% check):
  fires whenever `cost_of_debt < risk_free_rate`. Advisory only — `compute_cost_of_debt`'s
  embedded-rate estimate and its [2%, 15%] clamp are untouched. Reaches the mechanical DCF's
  context automatically via existing "DATA-QUALITY WARNINGS" plumbing; `format_ai_dcf_summary`
  (`api/ai_dcf_router.py`) extended to surface it on the AI DCF side too, since the AI DCF
  Architect can set `cost_of_debt_override` independently of the mechanical DCF.
- **Ticker-anchored capex guardrail** (`api/ai_dcf_data.py::get_historical_margin_bounds` gains
  `capex_pct_max`; `api/ai_dcf_router.py::_check_scenario_ranges`): the capex ceiling is now each
  ticker's own historical max + 15pp, falling back to the flat 35% only when a ticker has fewer
  than 2 years of usable capex history (e.g. a recent IPO). Stays advisory, never a clip — a hard
  clip would override genuine, evidence-cited capital upcycles the DCF Architect is designed to
  capture (e.g. PEG's stated $24-28B 2026-2030 plan).
- Both fixes are generic across every ticker (CLAUDE.md rule 6), not IBM/PEG-specific — confirmed
  live when PEG's regenerated report independently triggered the *same* cost-of-debt warning IBM
  did, unprompted.
- 10 new/updated tests (`tests/test_wacc.py` new; `tests/test_ai_dcf.py`,
  `tests/test_research_ai_dcf_integration.py` updated). Full project suite green: 648 passed, 3
  pre-existing unrelated skips.

### Live verification

Regenerated both IBM and PEG reports end-to-end post-fix (cache cleared, real LLM run, ~$0.79
combined). Cost-of-debt warning fired correctly and generically on both. PEG's capex false
positive is gone — the AI DCF authored essentially the same capex intensity (35.8%/39.2%
base/bull) as the original flagged run, with no quality-control-bound breach anywhere in the new
report; the Chief now discusses the capex ramp on its economic merits instead. Consequential
result, not isolated by a controlled A/B test (LLM run-to-run variance, different day's price):
PEG's rating moved HOLD -> BUY, base fair value $135 -> $114, target range $57-$278 -> $68-$170
(narrower, no longer inflated by one scenario tripping the stale bound). The rating flip traces to
the mechanical BUY-trigger rule (`price >15% below fair_value_base` + positive momentum) losing
its override reason — that threshold was already satisfied in the original HOLD report too; the
capex QC breach was the Chief's stated reason to override it, and that reason is what the fix
removed, not the valuation becoming more bullish. IBM stayed HOLD, target $175-$320 -> $172-$285.

### Where it lives

`features/ai_dcf/PLAN_GUARDRAILS.md` is the full investigation record, before/after data, and
test coverage (all phases complete). Companion to the original `features/ai_dcf/SPEC.md` /
`PLAN.md` (Agentic AI DCF Valuator, shipped 2026-07-31) — SPEC.md §6.5 updated in place to
describe the ticker-anchored capex rule.

---

## DCF Accuracy Measurement (complete, 2026-08-21/23)

The DCF had never been measured. Every assumption in it was justified by *defensibility* — no
absurd outputs — and none by accuracy. This closes that, and the answer is two-part.

### What was found

**As a cross-sectional ranking factor: rejected.** `dcf_upside` reconstructed point-in-time over
2010-2024 (60 quarterly as-of dates, 75,280 ticker-dates, 61,289 valuations) and run through the
same gauntlet that rejected CANSLIM, Greenblatt, Fibonacci and MD&A: mean rank IC 0.0157 at the
bound then live, against `fcf_yield` at 0.0871. Incremental IC over the existing value factors was
*negative*. Re-tested at 2y/3y/5y in case one year was the wrong clock for a DCF — the verdict
softened but held.

**As a per-name signal: it works, in one regime.** Price converges toward the DCF's intrinsic
value more often than a matched null, concentrated where the DCF says a company is worth less than
~40% of its price: +8pp (2.5-12x) to +19pp (>12x) at 3-5y, about half surviving an
`earnings_yield`-matched null. **That explains the ranking result** — a signal living in ~20% of
names dilutes to nothing in a full-universe rank IC. Absolute convergence stays under 50%, so it
is a caution signal, not a price target.

### What shipped

- **`MAX_INTRINSIC_TO_PRICE` 10.0 -> 2.5**, walk-forward validated (8/10 out-of-sample folds,
  stronger in the recent half). Plus `MAX_INTRINSIC_TO_PRICE_OVERRIDE = 10.0` for caller-supplied
  forecasts — applying 2.5 globally regressed the AI DCF, whose bull scenarios legitimately exceed
  it. Production: 2,145 -> 1,912 `status='ok'` (1,913 predicted).
- **`dcf_results_history`** — an append-only dated snapshot per rebuild. `dcf_results` overwrote
  itself, and stored no price, so nothing about a past DCF was recoverable. This is the only path
  to measuring the *shipped* model (analyst layer included), readable ~2028-29.
- **`as_of` reconstruction** through `run_dcf_av` — statements, price, risk-free rate and beta all
  point-in-time, assertion-validated with a negative control.
- **Chief Analyst regime note** (`_mechanical_dcf_regime_note`) telling it where the DCF has
  earned weight and where it has not.
- **Beta fix found en route**: 877 of 2,149 DCF tickers had *no stored beta* and silently used
  1.0. Backfilled to 2,799 tickers, and the refresh cron that `refresh_betas` documented but
  nobody had installed is now installed and verified running.

### Where it lives

`docs/dcf_upside_factor_test.md` is the findings artifact. Process records:
`archive/PLAN_DCF_ACCURACY.md`, `features/dcf/PLAN_DCF_FOLLOWUP.md`. No live trading changed —
`dcf_upside` was never in the composite.

---

## ML Comps Valuation — Calibration Monitoring + Pipeline Fix (complete, 2026-08-13)

Closes a real gap discovered while reviewing the roadmap: `validate_ml_comps_valuation.py`
(the Phase 3 go/no-go gate's script) only wrote `docs/ml_comps_validation_report.md` and
`docs/ml_comps_validation_folds.csv`, both overwritten on every run — so no month-over-month
calibration history accumulated anywhere queryable, which is the actual prerequisite for a real
Phase 9 decision (replacing `goal_pe`/`goal_low`/`goal_high` with this model — see
`features/historic_fundamentals/ml_comps_valuation_plan.md`).

### What shipped

- `historic_fundamentals/db.py::update_active_ml_model_oos_metrics()` — targeted column update
  on the currently-active `model_version` row in `ml_model_metadata` (not the full-row `INSERT
  OR REPLACE` the training-time upsert uses, which would null out `trained_at`/`feature_cols`).
  No-ops cleanly for a target with no active row (`evebitda`, which never cleared Phase 3 and so
  is never trained).
- `validate_ml_comps_valuation.py` calls it for every evaluated multiple after each walk-forward
  run.
- `scripts/report_ml_comps_calibration.py` — new monthly Telegram report (mirrors the existing
  `mda_sweep_report.py` pattern): reads the metrics above, re-checks the current month against
  the Phase 3 thresholds, computes a consecutive-months-holding streak per production multiple
  by walking `model_version` history newest-first, and flags "ready for a real Phase 9 review"
  once all three (P/E, P/FCF, P/S) hold for `READY_FOR_REVIEW_MONTHS` (6, adjustable) months
  straight.
- `scripts/run_pipeline.py` wired both into `--enable-ml-comps` as new steps after train/score.

### A real bug caught before it shipped

`_run()` (the pipeline's step runner) calls `sys.exit()` on any non-zero return code —  but
`validate_ml_comps_valuation.py` deliberately returns 1 when the month's re-validation gate
fails, which is an expected outcome for an additive, non-trading-critical experimental
sub-model, not a pipeline error. Wired in as originally written, a single bad `ml_comps` month
would have silently aborted the *entire* monthly pipeline before `train_model`/`run_backtest`/
`score_live` ever ran — the actual live-trading refresh, which has nothing to do with
`ml_comps`. Added `_run(..., fatal=False)` and used it for both the validation and report steps
(a Telegram outage shouldn't kill the trading pipeline either); `fatal=True` stays the default
for every other step. 5 new tests cover the regression directly.

### Also found: this feature was already live and undocumented as such

While investigating, found `--enable-ml-comps` was already in the production crontab (monthly,
1st, was `02:00` ET) and had been running successfully since at least 2026-07-20 — contradicting
the "opt-in, not yet enabled" line in this doc's original ML Comps Valuation entry below, which
was stale for at least two monthly cycles. Corrected in place. Also moved the cron start to
`00:05` ET for headroom against the newly-added ~90min validation step, though confirmed this
isn't actually time-critical — the only same-day consumer (`fundamentals_rebalance`) doesn't run
until 15:30 ET.

### Verification

Live-ran the full walk-forward gate manually rather than waiting for the next scheduled cron
(`logs/validate_ml_comps_manual_20260813.log`) — completed in ~135 min (longer than the ~85 min
the plan doc estimated; worth treating that figure as a soft floor going forward). Results
nearly identical to the original 2026-07-20/07-21 gate: P/E +18.3%, P/FCF +19.0%, P/S +23.4%
RMSE improvement (all PASS), EV/EBITDA +14.8% (still FAIL, just under the 15% bar — and won
100% of its 36 folds individually, confirming it's a genuine small structural miss, not noise).
Confirmed metrics persisted correctly to `ml_model_metadata` for the 3 production multiples and
skipped cleanly for `evebitda`. Ran `report_ml_comps_calibration.py` for real (not `--dry-run`)
— live Telegram message sent, all three multiples correctly reporting their first
consecutive-month streak (1).

---

## Analyst Estimate Dispersion (complete, 2026-08-13)

Follow-up to Barron's, "The Hidden Red Flag in Wall Street's Price Targets" (2026-08-13) on
analyst price-target dispersion predicting weaker forward returns (Diether-Malloy-Scherbina
2002 / Zhang et al. 2024). Alpha Vantage serves no per-analyst price targets or historical
estimate snapshots, so this uses the EPS high/low/avg band already in `earnings_estimates` as a
proxy — full writeup and phase-by-phase spec in `archive/PLAN_DISPERSION.md` (all 7 phases complete).

### What shipped

- `historic_fundamentals/dispersion.py` — pure metric functions (`compute_metrics`,
  `select_horizons`, `percentile`); a hard EPS floor (`< $0.10` → null, not a degenerate ratio)
  and no hardcoded severity threshold (ranked cross-sectionally instead).
- `estimates_dispersion` monthly snapshot table + `scripts/build_dispersion_snapshots.py`,
  feeding a dormant `scripts/test_dispersion_factor.py` that refuses to run below 36 months of
  history (currently 4) rather than produce a misleading result from a short archive.
- `eps_dispersion`/`eps_dispersion_pctile`/`coverage`/`net_revisions_30d`/`eps_drift_30d` added
  to `/av-fundamentals` and `/estimates`, all nullable, independent of the snapshot table having
  run.
- Finview: header chips, a coverage/spread sub-line on the Price Targets table's Analyst
  Consensus row, and a Spread column on the Estimates tab — colored by cross-sectional
  percentile, not an absolute threshold.
- The AI Researcher chief's `target_price_validation` now cites FY1 dispersion/coverage/net
  revisions and explicitly discounts the consensus anchor when dispersion is top-quintile or
  revisions are negative — naming which condition applies rather than a blanket discount.
- Installed the `estimates_update.py` weekly cron, which the script had documented but was never
  actually scheduled.

### Real bugs caught during implementation, not by inspection

- `select_horizons` compared a pandas `Timestamp` against `datetime.date` — a `.df()` vs
  `.fetchall()` type mismatch caught by the snapshot-builder tests on first run.
- An off-by-one column index in `research_router.py` swapped `eps_rev_up_30d`/
  `eps_rev_down_30d` — caught by the test asserting the exact expected net-revisions value.
- The consequential one: the snapshot builder assumed one shared `fetched_at` timestamp per
  monthly run, but `estimates_update.py` stamps `fetched_at = now()` separately per ticker as a
  ~37-minute rate-limited sweep processes them — so the original query only ever matched the
  single last ticker processed each month. Found by running the builder against the real,
  freshly-populated DB (not caught by unit tests using a same-timestamp fixture); fixed to take
  each ticker's own latest fetch within the month, with a regression test modeling the real
  per-ticker-timestamp behavior.

### Verification

54 tests passing. Live-verified end to end: full 2,656-ticker `estimates_update.py` run (2,637
ok, 19 legitimate no-data, zero rate-limit errors, 37m9s); snapshot builder against the real DB
(4 qualifying months, 1,214-2,603 tickers each, confirmed idempotent); `curl` against a running
API across NVDA/MSFT/AVGO/BRSL/CHRN/ABCL (normal, thin-coverage, EPS-floor, and no-data cases);
Playwright screenshots of all four UI scenarios; and two live AI Researcher report generations
(NVDA, AEE) confirming the chief's discount logic fires correctly — NVDA (74th percentile,
positive revisions) explicitly reasoned it was below the 80th-percentile discount threshold and
gave consensus normal weight, AEE (8th percentile) called its spread "unremarkable." Reports
saved to `docs/dispersion_test_report_{nvda,aee}_2026-08-13.md`.

---

## AI Researcher LLM Tiering + Cost Tracking (complete, 2026-08-07)

Replaces the single global OpenRouter model previously threaded through the whole AI Researcher
(equity report, Agentic AI DCF sub-pipeline, Industry Research) with per-agent model tiering, and
adds real (not estimated) per-report cost visibility.

### Per-agent tiering

`_ROLE_MODELS` + `resolve_agent_model(role, model)` in `api/research_router.py`: the dropdown's
new default `"tiered"` resolves a different model per agent role; any other explicit dropdown
pick still overrides every agent uniformly (old behavior, preserved for testing/comparison).

- **Tier A** (`anthropic/claude-sonnet-5`, $2/$10 per M) — numeric-originating roles nothing
  downstream checks for correctness: `dcf_architect`, `valuation_analyst`, `chief_analyst_core`,
  `chief_industry_strategist`, `chat`.
- **Tier B** (`deepseek/deepseek-v4-pro`, $0.435/$0.87) — qualitative synthesis/narrative, either
  downstream-checked or no numeric stakes: `competitive_strategy_analyst`,
  `trends_developments_analyst`, `risks_outlook_analyst`.
- **Tier C** (`deepseek/deepseek-v4-flash-0731`, $0.09/$0.18) — extraction/summarization,
  including the highest-volume fan-out roles: `technical_analyst`, the 3 AI DCF evidence briefs
  (`fundamentals_historian`, `industry_competitors_analyst`, `guidance_mda_analyst`),
  `company_digest` (Industry Research, one call per member ticker).
- **Luna** (`openai/gpt-5.6-luna`, $0.10/$0.60) — `chief_analyst_narrative` and
  `earnings_mda_historian` only, swapped off DeepSeek after a live latency finding below.

### DeepSeek latency finding -> Luna swap

A live AAPL run (uncached) showed every DeepSeek-served call ran notably slow while every
Sonnet-5 call was fast: `chief_analyst_narrative` hit 399.8s of its 400s per-agent timeout cap,
and `earnings_mda_historian` hit 371.1s. A second, independent data point (JNJ, same day, before
any of these changes) actually **hit** the timeout on `chief_analyst_narrative`. This mattered
more than "slow" — Chief Core/Narrative are the only two agents in the pipeline with no fallback
(every specialist and AI DCF evidence agent degrades to a typed `[ERROR]` placeholder on
timeout instead), so a Chief-stage timeout discards the entire ~10-16 min report with nothing
cached, forcing a full re-run from scratch.

Swapped just those two roles to `openai/gpt-5.6-luna` (cheaper than DeepSeek V4 Pro on both
axes, comparable to V4 Flash) and live-tested before committing: `chief_analyst_narrative`
399.8s -> 50.9s, `earnings_mda_historian` 371.1s -> 14.6s, full pipeline 986.2s -> 306.8s. Read
the resulting AAPL report end to end — no quality regression found. Every other role (including
the 3 genuinely qualitative DeepSeek Pro roles and all Tier A roles) left untouched.

### Real usage/cost tracking

`log_llm_usage(ticker, role, model, result)` reads the OpenAI Agents SDK's aggregated
`result.context_wrapper.usage` after every `Runner.run()` call (all three routers — equity
report fan-out + Chief Core/Narrative, the 3 AI DCF evidence agents + `dcf_architect`, and
Industry Research's digest/trends/risks/chief) and logs real input/output tokens and $ cost.
Never raises — same "logging must never break generation" contract as the existing
`log_dcf_reconciliation` — so an SDK shape change or test double degrades to a skipped log line,
not a failed sub-agent.

A `UsageTracker`, held in a `contextvars.ContextVar` and shared by reference across a report's
parallel `asyncio.gather` fan-out (works because asyncio context-copies a *mutable* value by
reference into child tasks, so sibling tasks all mutate the same instance while two different
reports each get their own), accumulates cost/tokens across the whole call tree.
`render_to_markdown` prints the total on the report header itself:
`**Generation Cost:** $0.315 (119,200 tokens)`.

**Measured real cost per report** (previously only estimated from context sizes, at ~$0.12 —
3-4x too low, mainly from underestimating output tokens): **~$0.31-0.46 uncached**, ~94% of it
the 3 Sonnet-5 calls (`valuation_analyst` alone runs $0.16-0.18; `chief_analyst_core` $0.12-0.14;
`dcf_architect` ~$0.08). All 6 DeepSeek/Luna calls combined cost 2-3 cents. Cached views (24h
TTL) are free. Not wired up: `/research/chat` — it bypasses the Agents SDK with a raw streaming
`client.chat.completions.create()` call and would need separate plumbing.

### Also fixed along the way

- `/research/chat` bypassed `resolve_agent_model` entirely, sending the `"tiered"` sentinel
  straight to OpenRouter as a literal model ID whenever the frontend's dev server hot-reloaded
  ahead of a `uvicorn` restart — root cause of a live incident (every sub-agent 400'd). Fixed by
  adding a `"chat"` role to `_ROLE_MODELS` (Tier A) and resolving it in `_chat_stream`.
- `api/main.py` never called `logging.basicConfig()`, so every `log.info(...)` phase-timing
  milestone was silently dropped at the default WARNING level — including all the new usage
  logs above. Fixed; journal now shows real per-call timings and costs.
- Chief Core and Chief Narrative previously shared one status label (`"synthesizing"`), so a
  stall looked like one undifferentiated black box up to ~800s. Added a `"writing_narrative"`
  phase between them.

### Verification

Two full live AAPL report generations (one with a cold Agentic AI DCF sub-pipeline, one with it
cache-hit) plus the pre-swap DeepSeek baseline run — all read end to end for quality, not just
timed. Full 190-test suite across the 5 touched files (`api/research_router.py`,
`api/ai_dcf_router.py`, `api/industry_research_router.py`, plus 2 test files updated for the new
`_run_stage_agent`/`_run_research_agent` signatures) passes. Committed `a75be83`.

---

## Agentic AI DCF Valuator (complete, 2026-07-30)

New second, independent DCF source feeding the single-name AI Research tab's Valuation Analyst,
alongside the existing mechanical bear/base/bull scenarios. Full spec, architecture, and phased
build record: `features/ai_dcf/SPEC.md` and `features/ai_dcf/PLAN.md` (all 8 phases complete,
extensively live-verified, not just unit-tested).

### Architecture — evidence team + DCF Architect

```
gather data in parallel (fundamentals history, MD&A, cached Industry Researcher report
  if <=14d old, cached competitor transcripts, target transcripts/estimates, peer table)
  -> Stage 1: 3 evidence sub-agents in parallel (Fundamentals Historian, Industry &
     Competitors, Guidance & MD&A) each produce a structured brief
  -> Stage 2: DCF Architect (senior valuation persona) authors per-year bear/base/bull
     revenue growth, COGS%, EBIT margin, capex% + terminal growth, citing brief evidence
  -> guardrails (range checks, cogs/margin internal consistency) -> dcf.run_dcf_av x3
  -> AiDcfResult (assumptions + engine output + QC warnings), cached, rendered to markdown
```

The LLM only authors assumptions; the SAME deterministic `dcf.run_dcf_av` engine that powers the
mechanical scenarios computes the actual valuation — never the LLM. The Valuation Analyst sees
both DCFs and reconciles them under a neutral preference rule (no hard-coded favorite) in a new
`dcf_reconciliation` field.

### Infrastructure added

- `api/ai_dcf_data.py` — data layer: fundamentals history, MD&A history (`mda_filings.duckdb`,
  previously unused by the researcher), cached Industry Researcher report lookup (own 14-day
  freshness window, bypasses that router's 24h TTL), cached-only competitor transcripts (zero
  extra Alpha Vantage calls), engine context (risk-free rate, beta, tax rate, `reports_cogs` flag).
- `api/ai_dcf_router.py` — assumption schemas + guardrails, the engine bridge, evidence-agent
  fan-out, DCF Architect call, orchestrator, DuckDB cache (`ai_dcf_cache.duckdb`, 24h TTL),
  background-task/status/cancel scaffolding, 3 new endpoints under `/research/ai-dcf*`, plus
  `get_or_run_ai_dcf` — an in-process, cache-aware entry point shared with the research pipeline
  that joins an in-flight run instead of double-starting one.
- 4 new prompts (`api/prompts/ai_dcf_{fundamentals,industry,guidance,architect}.md`).
- `api/research_router.py` changes: new `running_ai_dcf` status phase; Valuation Analyst context
  gains the AI DCF summary; `ValuationOutput` gains `ai_dcf_intrinsic_value` (echo, QC-checked)
  and `dcf_reconciliation`; new "DCF (AI-authored)" triangulation row and "AI vs. Mechanical DCF
  Assumptions" comparison table (both reuse the existing single mechanical DCF computation — the
  AI DCF's own engine never runs twice).
- 122 new tests across 3 files (`test_ai_dcf.py`, `test_ai_dcf_orchestration.py`,
  `test_research_ai_dcf_integration.py`), all passing, zero regressions in the existing suite
  (424 total passing project-wide).

### Key findings / bugs fixed (live, not hypothetical)

- **`ebit_margin_pct` alone is silently capped at `1 - cogs_pct - sga_pct - rd_pct`** for
  companies that report COGS explicitly — found live on UPS (historical COGS ~81%): requesting
  a 35% EBIT margin silently produced 18.7% instead, no error. Root cause: the engine's EBIT-
  margin control plugs the gap via `other_opex_pct`, which can't go negative, and gives up
  rather than touching `cogs_pct`. Fix: the assumption schema gained a `cogs_pct` lever
  alongside `ebit_margin_pct`; the Architect prompt explains the constraint explicitly; a
  guardrail warns when the pair is internally inconsistent. Verified live on UPS afterward: the
  Architect correctly held `cogs_pct` near the historical level and stayed under the ceiling in
  all three scenarios, zero guardrail warnings, achieved margins matching authored targets
  exactly.
- The same literal-backslash-n `google/gemini-3.5-flash` quirk documented in the Industry AI
  Researcher section below hit this feature's evidence briefs too, AND separately hit a brand-
  new field added to the existing single-name researcher (`ValuationOutput.dcf_reconciliation`)
  — every other field in a real generated report was clean, isolating the issue to that one new
  field. Both fixed by reusing the existing `_sanitize_prose` helper.
- Live 5-ticker sweep (TXN, UPS, STRZ, NUE, CRWV) confirmed the AI DCF's divergence from the
  mechanical baseline is genuinely company-specific, not a fixed offset: from +0.7% (NUE, a
  mature cyclical business where the Architect's assumptions closely tracked the engine's own
  historical defaults) to +532% (STRZ, evidence-driven margin thesis vs. a historical-percentile
  approach on a company mid-transition post-spinoff). CRWV (pre-profit AI-infrastructure
  buildout) produced a degenerate, deeply negative value under BOTH the mechanical and AI DCF —
  confirms vanilla FCFF DCF is a poor methodological fit for that business model, not an
  artifact of AI-authored assumptions; guardrails correctly surfaced 14 warnings (including a
  genuine bear>bull scenario-ordering violation) rather than hiding the mismatch.

### Verification

Live-verified at every layer: individual evidence-agent and Architect calls against real TXN/UPS/
CRWV data (including one full run against `anthropic/claude-sonnet-4-6` to confirm no compiled-
grammar issue, unlike the single-name researcher's Chief schema which needed splitting); a full
mocked-agent end-to-end pipeline test; standalone-endpoint HTTP checks (cold/warm/cancel) via an
isolated test app (the project's own long-running dev server was left untouched rather than
risking a port/lock conflict); two full real research-report generations for TXN (one cold, one
with a warm AI DCF cache — AI DCF step measured at 0.01s warm vs. the full cold-run cost,
confirming the "near-zero added latency when cached" design goal); and the 5-ticker live sweep
above.

---

## Industry AI Researcher (complete, 2026-07-27)

New FinView tab: cross-company industry research, complementing the existing single-name AI
Research tab. Pick an AV `industry` (e.g. "Semiconductors" — deliberately finer-grained than
sector, since a sector like Technology spans industries on very different cycles: 12 sectors vs.
145 industries in the current DB) or supply a custom ticker basket. Full spec, architecture, and
phased build record: `features/industry_research/SPEC.md` and `features/industry_research/PLAN.md`
(all 8 phases complete, extensively live-verified, not just unit-tested).

### Architecture — map-reduce multi-agent pipeline

```
resolve members (top-8 by market cap, or custom basket)
  -> gather data in parallel (transcripts, beat/miss, financials, estimates, aggregates, web search)
  -> Stage 1 MAP: per-company Earnings Digest sub-agent, fanned out in parallel
  -> Stage 2 REDUCE: Trends & Developments + Risks & Outlook specialists, parallel
  -> Stage 3 SYNTHESIZE: Chief Industry Strategist (executive summary + ranked ideas)
  -> deterministic Python rendering (appendix tables + ranked-ideas numeric join)
```

Every number in the final report — valuation medians, EPS surprises, revision momentum, the
ranked-ideas table's valuation-vs-industry and revision-momentum columns — is computed in Python
from the database. The LLM only writes prose, stance/catalyst/risk, and the executive summary.

### Infrastructure added

- `api/industry_data.py` — data layer: `list_industries`, `resolve_members`, industry aggregates,
  member financials, beat/miss, estimates, transcripts, web search. Raw-fetch/pure-formatter split
  throughout so the LLM-context text and the markdown appendix tables share one fetch instead of
  double-hitting Alpha Vantage for the same tickers in one report generation pass.
- `api/industry_research_router.py` — the 3-stage pipeline, deterministic tables, DuckDB cache
  (`industry_research_cache.duckdb`, 24h TTL), background-task/status/cancel scaffolding
  (structurally mirrors `research_router.py`), 5 new endpoints under `/industry-research/*`.
- 4 new prompts (`api/prompts/industry_{company_digest,trends,risks,chief}.md`).
- `web/components/IndustryResearchViewer.tsx` — industry picker with member counts, custom-basket
  override, model picker, live status bar, and clickable ticker cells generalized across *every*
  appendix table (not just ranked ideas) via a ticker-shape regex on table cells.
- 105 new tests across 3 files (`test_industry_data.py`, `test_industry_research_router.py`,
  `test_industry_research_orchestration.py`), all passing, zero regressions in the existing suite.

### Grain guarantee — industry, never sector

Hard requirement, tested and grep-audited: member resolution filters `UPPER(co.industry)=?` only
(no OR-fallback to sector like the single-name researcher's `_peer_df` has), aggregates read
`sector_stats WHERE group_type='industry'` only. A company with a null/blank industry
classification is excluded, never sector-substituted. Verified live: Semiconductors and
Software - Infrastructure (both under the Technology sector) resolve to disjoint member sets and
distinct aggregate figures.

### Key findings / bugs fixed (live, not hypothetical)

- `pandas.NA` (not `None`/float `NaN`) is how DuckDB INTEGER columns with nulls surface in pandas
  after `.df()` — crashed `int(pd.NA)` in estimate-revision formatting until caught by a shared
  `is_missing()` helper used everywhere a DB value is formatted.
- `google/gemini-3.5-flash` occasionally emits the literal two-character sequence `\n` inside a
  structured-output string field instead of a real newline — sanitized before rendering
  (`_sanitize_prose` for narrative sections, `_sanitize_table_cell` for table cells, which can't
  contain a raw newline without breaking the table).
- BBBY (the already-documented contaminated ticker from the survivorship-bias analysis below —
  reassigned post-bankruptcy) has industry set to the literal string `"None"`, which slipped past
  the NULL/blank filter and appeared as a selectable "NONE (1)" entry in the industry picker until
  excluded defensively.
- TSM's `current_pe` in `pe_stats` is 1.1 (vs. plausible ~25-35x peers), likely an ADR-ratio
  handling issue in `historic_fundamentals` — surfaced live in a real report's ranked-ideas table,
  flagged for separate investigation, not fixed here (pre-existing, out of scope for this feature).

### Verification

Live-verified at every layer, not just unit-tested: a real 3-4 company digest fan-out and full
Stage 1-3 pipeline with a real LLM producing internally-consistent output (e.g. correctly
aggregating "6 of 8 companies raised guidance" across digests rather than fabricating a pattern);
a full HTTP round-trip with cache-hit confirmation; and a full 8-company Semiconductors report
generated through the actual browser UI (~130s, within the estimated 60-150s), with working
Cancel, retry-after-cancel, and click-to-navigate from any ticker cell to that ticker's single-name
AI Research tab.

---

## Phase 11 Go/No-Go Gate — CLOSED, Composite Accepted, XGBoost Retired (2026-07-20)

Closed the go/no-go gate that had been open since May (`features/historic_fundamentals/fundamentals_alpha_action_plan.md` Phase 11 — `reports/model_acceptance_checklist.md`/`model_usage_decision.md` never existed until now). Triggered by a chain of findings this session: a train/serve z-score bug fix in `score_live.py` → discovering the same code pattern would be *wrong* to fix in `run_backtest.py` (single static model applied across ~40 years, era-mismatched normalization) → building a genuine walk-forward portfolio backtest to answer the question honestly → running Phase 9 robustness checks on the winner.

**Decision**: composite factor score (value+quality+momentum, no ML) = **Category 3, Paper Trading** — already what's live (`vw_gr_top_n_25`), now formally ratified with evidence. XGBoost `ret_1y` model = **Category 1, Research Only** — fails OOS rank IC (-0.017) and underperforms composite on every risk-adjusted metric under honest walk-forward testing (top_n_25: XGBoost Sharpe 0.73/-61.7% MaxDD vs. composite Sharpe 0.92/-50.1% MaxDD). No live behavior change: `score_live.py` already defaulted to composite; the pipeline never passed `--use-model`.

**Composite passed robustness testing** (`docs/composite_robustness_report.md`): stable-to-improving Sharpe across market-cap cuts (300M-5B), edge survives up to 100bps TC, no small-cap/illiquidity dependency.

**Two caveats disclosed, not resolved, in the acceptance checklist:**
- Sector-neutral scoring underperforms raw scoring (Sharpe 0.85 vs 0.94) — real share of the edge is sector positioning, not pure stock selection.
- `docs/composite_ic_analysis.md`: monthly rank IC is small-but-positive (+0.014 to +0.035, ICIR ~0.2-0.3) and top-25/50 beats bottom-25/50, but this **inverts** at top-100+/decile cuts (bottom outperforms top). The traded configuration (top_n_25) sits in the positive zone, but the score is not a broadly monotonic signal — open question, flagged for follow-up, not blocking.

Full detail: `reports/model_acceptance_checklist.md`, `reports/model_usage_decision.md`.

---

## ML Comps Valuation Model (complete, 2026-07-20; P/S extension complete, 2026-07-21)

Cross-sectional peer-comps ML model predicting a fair P/E, P/FCF, and P/S multiple for each stock from its fundamentals vs. sector peers — additive to the existing self-referential `goal_pe`/`goal_low`/`goal_high` (which compare a ticker to its *own* multiple history, not peers). Full phased build record: `features/historic_fundamentals/ml_comps_valuation_plan.md`.

### Approach

- 4 candidate multiples (P/E, EV/EBITDA, P/FCF, P/S — P/S added 2026-07-21), one XGBoost quantile-regression model each (`reg:quantileerror`, `quantile_alpha=[0.1,0.5,0.9]`) predicting a fair low/mid/high range in a single fit.
- Features: `monthly_pe`'s existing growth/margin/quality/leverage columns, sector-relative z-scored (fold-safe fit/transform split, not the live-batch self-referential z-scoring `score_live.py` uses).
- Fair price = predicted multiple × the ticker's own EPS/FCF-per-share/revenue-per-share.

### Validation gate (walk-forward, 36 folds/multiple, 1990-2026)

| Multiple | RMSE improvement vs. naive sector-median baseline | Fold win rate | Coverage p10–p90 | Result |
|---|---:|---:|---:|---|
| P/E | +18.3% | 100% (36/36) | 74.9% | PASS |
| EV/EBITDA | +14.7% | 100% (36/36) | 74.1% | FAIL then — **PASS on 2026-08-19 re-validation at +26.4%**, see note below |
| P/FCF | +18.7% | 100% (36/36) | 73.1% | PASS |
| P/S | +23.6% | 100% (36/36) | 74.7% | PASS (best of the 4, added 2026-07-21) |

P/E, P/FCF and P/S were trained/scored in production from this run; **EV/EBITDA was added 2026-08-19** once the debt defect feeding its enterprise value was fixed (+26.4% RMSE improvement on re-validation, second-best of the four). All four are now production multiples. Result reproduced identically on a second full rerun (deterministic, fixed seeds). Model beat the naive baseline in 100% of individual folds across 36 years — the fold-level check this gate was specifically designed to enforce, not just an aggregate number.

Adding P/S also closed a real coverage gap: full-universe scoring went from 2,122/2,653 tickers `ok` (515 `no_price_basis`) to 2,518/2,653 `ok` (119 `no_price_basis`) — P/S rescues tickers with negative/zero earnings or FCF (common for early-stage or cyclical-trough names) since revenue is defined almost everywhere. P/BV and PEG were also considered but not pursued: P/BV needs a per-sector model (book value is near-meaningless outside financials/industrials, would likely repeat EV/EBITDA's near-miss as a single universe-wide fit) and PEG doesn't fit this model's "multiple × ticker's own fundamental = fair price" mechanism at all.

### Infrastructure added

- `historic_fundamentals/ml_comps_model.py` — feature assembly, quantile model fit/predict, walk-forward harness, fit/transform-split sector z-scoring
- `ml_comps_valuation` + `ml_model_metadata` tables in `historic_fundamentals.duckdb`
- `scripts/{validate,train,score}_ml_comps_valuation.py`, `scripts/report_ml_comps_history.py`
- `api/av_router.py` — 16 new `ml_fair_*` fields in `/av-fundamentals/{ticker}`, additive, `null` when unscored
- `web/components/ValuationRangeBand.tsx` + new "ML Fair Value (Experimental)" panel in `FundamentalsViewer.tsx`, verified live in a browser
- `notebooks/ml_comps_valuation.ipynb` — coverage/RMSE/win-rate-over-time monitoring, executes end-to-end
- Wired into `scripts/run_pipeline.py` behind `--enable-ml-comps`. **Correction (2026-08-13): this was enabled in the production cron at some point after this entry was written** — the "opt-in, not yet enabled" line below was stale for at least two monthly cycles (confirmed live runs 2026-07-20, 2026-08-01) before being caught. See "ML Comps Valuation — Calibration Monitoring" below for the fix that followed from that discovery.

### Key findings

- Two real bugs caught before shipping, not caught by the validation gate itself (which only validates the model in isolation): (1) recomputing sector z-score stats from the live scoring batch instead of persisting training-time stats caused wildly miscalibrated predictions (P/E "high" bands in the thousands for effectively every ticker); (2) training the final production model on the full 40-year history instead of the gate-validated 5-year rolling window caused the same failure mode even after fixing (1). Both fixed — see plan doc for full detail.
- The existing `score_live.py` for the ret_1y model likely has the same z-score train/serve skew bug (#1 above) — not fixed here (out of scope), flagged for future attention if that model's live scores are ever scrutinized.
- Not wired to replace `goal_pe`/`goal_low`/`goal_high` — that's an explicit, deliberately un-started future decision (see plan doc's Phase 9).
- P/S predictions can hit extreme values for very-low-revenue-base names (e.g. ACHR mid ~293x, current ~1909x) — the existing `MAX_MULTIPLE=500` sanity cap (added for the original 3 multiples) handles this correctly without any P/S-specific change.

---

## BCD Mispricing Filter (complete, 2026-06-29)

Hard portfolio filter applied in `scripts/score_live.py` based on Bakshi-Chen 2001 structural valuation model.

### Formula (BCD-lite)

```
P_model = ttm_eps × (1 + earn_growth_1yr) / (DGS30 + 5.5% ERP - 3% terminal_growth)
Misp    = (price - P_model) / P_model   [clipped to ±3]
```

Require `bcd_misp ≤ 0` (structurally underpriced only). NULL = excluded.

### Backtest impact (post-2010, vw_gr_top_n_25)

| Variant | CAGR | Sharpe | MaxDD | PF | R-Exp |
|---------|------|--------|-------|-----|-------|
| baseline | 12.66% | 0.754 | -35.5% | 1.63 | 0.91% |
| bcd_hard | **15.66%** | **0.919** | **-28.0%** | **1.97** | **1.35%** |

### Infrastructure added

- `features/bcd/signal.py` — `compute_bcd_lite_misp()` function
- `monthly_pe.bcd_misp` — 433,133 rows populated (84.8% of ttm_eps>0 rows)
- `market_signals` table — monthly punder (420 months; avg=61.9%)
- DGS30 in `trade_systems/data/fred.duckdb`; `dcf/data.py load_risk_free_rate_30y()`
- DCF model now uses DGS30 as risk-free rate (was DGS10)
- `scripts/score_live.py _apply_bcd_filter()` — runs when `--guardrails` is on (default)
- `scripts/backfill_bcd_misp.py` — backfill + punder computation
- `scripts/backtest_bcd_filter.py` — comparison script (baseline vs bcd_hard vs bcd_soft)
- `scripts/validate_bcd_signal.py` — Phase 3 IC/ICIR/autocorr/punder validation

### Key finding: use as filter, not ML feature

Standalone NW-ICIR=-3.67 (strong signal) but 0.82 Spearman correlation with pe_ratio makes it redundant in XGBoost (NW-ICIR drops 2.26→0.95). Used as a pre-scoring hard filter instead.

---


## FinView — Sector & Industry Dashboard (complete, 2026-06)

Web analytics platform at `web/` (Next.js, port 3000) with 8 tabs:

| Tab | Description |
|-----|-------------|
| Screener | 18-metric stock filter with sortable results |
| Sector | Sector/industry rankings, VMQ composite score, 5yr history chart, company drill-down |
| AV Data | Alpha Vantage income/balance/cashflow viewer |
| AV DCF | DCF valuation from AV data |
| Fundamentals | PE/FCF/EV history, goal prices, valuation signals |
| AI Research | AI-generated equity research report |
| Earnings | Analyst EPS + revenue consensus estimates |
| XBRL | SEC XBRL financial statements (appears after download) |

### Sector dashboard — VMQ composite score methodology

Cross-sectional z-scores (capped ±2.5) of three factors, weighted:

- 35% Value: EV/EBITDA vs own 5yr historical median (avoids cross-sector PE comparison distortions)
- 35% Momentum: trailing 1yr revenue growth median
- 30% Quality: ROIC median

Score > 0.2 = undervalued/improving (emerald), < -0.2 = expensive/deteriorating (rose).

### sector_stats table (historic_fundamentals.duckdb)

43,611 rows (5,231 sector rows + 38,380 industry rows). Columns added in this session:
`gross_margin_median`, `operating_margin_median`, `fcf_margin_median`, `debt_to_ebitda_median`, `interest_coverage_median`

Rebuild: `uv run scripts/rebuild_sector_stats.py`

---


## Goal

Build an ML model that identifies which fundamental characteristics predict forward stock
returns at 6-month, 1-year, 2-year, 3-year, and 5-year horizons. Use this to rank all
tickers in the database by expected return and surface buy candidates.

This replaces the earlier `valuation_model.ipynb` approach (which required GP analyst
spreadsheets as training labels — those have been deleted).

---

## Notebook

`notebooks/fundamentals_alpha.ipynb`

Mirrors the structure of `trade_systems/strategies/ibd50/ibd50_analysis.ipynb`.

### Structure

| Cell | Purpose |
|------|---------|
| 1 | Imports & config |
| 2 | Load `monthly_pe` from DB (296K rows, 1,414 tickers, 1999–2026) |
| 3 | Compute forward returns (6m, 1y, 2y, 3y, 5y) via vectorized self-join |
| 3b | Compute trailing CAGRs (rev/earn/fcf at 1y, 3y, 5y) — backward-looking |
| 4 | Feature engineering (36 features — see below) |
| 5 | Return target masking — NaN = future price not yet available |
| 6 | EDA: correlation heatmap (feature vs each return horizon) |
| 7 | EDA: monthly IC / ICIR (Spearman rank correlation per month) |
| 8 | EDA: quintile return analysis (Q1–Q5 mean return per feature) |
| 9 | XGBoost training — one model per horizon |
| 10 | SHAP importance plots (magnitude + direction beeswarm) |
| 11 | Walk-forward validation (train months 1–N, predict N+1, no lookahead) |
| 12 | Walk-forward cumulative return chart + monthly IC bar chart |
| 13 | Live scoring — ranks all tickers in pe_stats by predicted return |
| 14 | Summary printout |

---

## Features (36, as of last run)

### Valuation level (8)
`pe_ratio`, `pfcf_ratio`, `ev_ebitda`, `ps_ratio`, `pbv`, `ptbv`, `fcf_yield`, `dividend_yield`

### Mean-reversion premiums — current / 5yr rolling median (6)
`pe_premium`, `pfcf_premium`, `ev_premium`, `ps_premium`, `pbv_premium`, `ptbv_premium`

### Quality / profitability (6)
`roa`, `roe`, `roic`, `roa_premium`, `roe_premium`, `roic_premium`

### Historical fair-value anchors — 5yr rolling median, no look-ahead (7)
`pe_rolling_5yr_median`, `pfcf_rolling_5yr_median`, `ev_ebitda_rolling_5yr_median`,
`ps_rolling_5yr_median`, `roa_rolling_5yr_median`, `roe_rolling_5yr_median`,
`roic_rolling_5yr_median`

### Growth — trailing CAGRs, backward-looking (9)
`rev_cagr_1y`, `rev_cagr_3y`, `rev_cagr_5y`,
`earn_cagr_1y`, `earn_cagr_3y`, `earn_cagr_5y`,
`fcf_cagr_1y`, `fcf_cagr_3y`, `fcf_cagr_5y`

---

## Current State

Latest clean run uses **36 features** (27 valuation/quality + 9 growth CAGRs).
No look-ahead — all features are backward-looking or contemporaneous.

### Run results (36 features, 2026-05-13)

| Horizon | Training rows | In-sample R² |
|---------|--------------|--------------|
| ret_6m  | 289,273      | 0.095        |
| ret_1y  | 280,797      | 0.127        |
| ret_2y  | 263,894      | 0.161        |
| ret_3y  | 247,136      | 0.159        |
| ret_5y  | 213,896      | 0.183        |

**Walk-forward (ret_6m, 247 months, top 20% selection):**
- Top-20% return: **+16.38%**
- Benchmark return: +8.74%
- Mean excess return: **+7.64%** vs universe
- Win rate: **96%**
- Mean monthly IC: 0.1265
- **ICIR: 0.941** (close to the 1.0 "strong factor" threshold)

### Top features by SHAP importance (mean across horizons)
1. `ps_ratio` — value (negative direction = cheap wins)
2. `dividend_yield` — yield/quality
3. `roa` — profitability
4. `rev_cagr_1y` — growth (new)
5. `roa_rolling_5yr_median` — quality
6. `rev_cagr_3y` — growth (new)
7. `pfcf_ratio` — value

---

## Bugs Fixed

### 1. Forward return indexing error
`iloc[argmin()]` was being called on a differently-indexed Series, causing random
price mismatches and artificial negative mean returns (-17% to -40%).
Fixed by rewriting as a vectorized self-join merge using `day_diff.abs().dt.days`.

### 2. Look-ahead bias in goal features
`goal_discount` and `goal_upside` were computed from `goal_low` / `goal_high` columns
in `monthly_pe`. Those columns use `pe_lt_median` (all-time median, not rolling), which
incorporates future data when applied to historical rows.
Fixed by removing both features from `FEATURE_COLS`.

---

## Next Steps

### Done in this session
- [x] Re-executed notebook with 27 clean features (no goal leakage)
- [x] Added 9 growth features (1y/3y/5y CAGRs for revenue, EPS, FCF)
- [x] Confirmed value (ps_ratio, dividend_yield) dominates, growth/quality secondary
- [x] Final ICIR: 0.941 (vs 0.889 without growth features)

### Next (in priority order)

1. **Sector neutralization** — compute valuation premiums relative to sector median
   rather than (or in addition to) own 5yr history. Requires a sector/industry mapping
   per ticker. Typically improves IC by removing macro/sector return noise.
   - Needs: sector mapping table (not currently in DB)
   - Suggested source: SEC SIC codes or Yahoo Finance sector field

2. **Liquidity / market cap filter** — the current live scoring includes micro-caps and
   thinly traded stocks that top the rankings. Add a minimum market cap filter
   (e.g. >$500M) in Cell 13 before presenting buy candidates.
   - Simple addition: `live = live[live['market_cap_b'] >= 0.5]` before ranking

3. **Save trained model artifacts** — currently the model is retrained from scratch
   on every notebook run. Save `models[PRIMARY_ML_TARGET]` + `train_medians` + `FEATURE_COLS`
   to `models/` so a quick-predict cell can reuse without retraining.

4. **Composite factor score** — once the best individual factors are confirmed via ICIR,
   build a blended score (value + quality + growth) weighted by ICIR. Simpler and
   more robust than XGBoost for live scoring.

5. **DCF model** — separate notebook. Use historical FCF + growth rates to compute
   intrinsic value. Complement to the factor model (factor model ranks stocks;
   DCF provides a price target).

### Performance notes (for future tuning)
- Notebook runs ~7–8 minutes end-to-end on this machine
- Forward return computation is now vectorized (was the bottleneck)
- Trailing CAGR computation adds ~1 minute (9 self-joins)
- Walk-forward validation is the slowest cell (~3 minutes — 247 XGBoost retrains)

---

## Data

- **DB**: `data/historic_fundamentals.duckdb`
- **Table**: `monthly_pe` — 296,348 rows, 1,414 tickers, 1999-12-31 to 2026-05-31
- **Key columns**: price, pe_ratio, pfcf_ratio, ev_ebitda, ps_ratio, pbv, ptbv,
  roa, roe, roic, fcf_yield, dividend_yield, plus 5yr rolling medians for each;
  earnings_yield, earnings_yield_3y_avg, earnings_yield_5y_avg, normalized_pe_5y
- **Dependencies**: `xgboost`, `shap` (both installed in .venv)
