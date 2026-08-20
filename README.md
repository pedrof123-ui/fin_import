# fin_import2

Downloads SEC EDGAR financial statements (10-K annual, 10-Q quarterly) into DuckDB. Includes a web app for single-ticker imports, a DCF valuation engine, a CLI tool for bulk imports, and a separate Alpha Vantage financial statements database.

## Architecture

- **FastAPI backend** (`api/`) — REST API for importing, querying statements, DCF valuations, stock screener, sector/industry dashboard, single-name equity research, industry-level research, and earnings call transcripts
- **Next.js frontend** (`web/`) — FinView UI with tabs: Screener, Sector Dashboard, Calendar, AV Data, AV DCF, Fundamentals, Estimates, AI Research, Industry Research, Earnings, News, XBRL Statements
- **DuckDB** (`data/financial_statements.duckdb`) — stores income, balance sheet, and cash flow tables from SEC EDGAR
- **DuckDB** (`data/av_financials.duckdb`) — stores income, balance sheet, and cash flow tables from Alpha Vantage API, plus company overview (sector/industry/name/beta)
- **DuckDB** (`data/historic_fundamentals.duckdb`) — monthly PE/P/FCF/EV/EBITDA timeseries, valuation stats, sector/industry aggregates (43K rows), analyst estimates
- **DuckDB** (`data/earnings_transcripts.duckdb`) — earnings call transcripts for all AV tickers, fetched from Alpha Vantage and cached; used by the Earnings tab and AI Research
- **DCF engine** (`dcf/`) — 10-year FCFF model: EWM+momentum revenue forecasting with growth capped and faded to terminal, historical mean for P&L ratios, CapEx faded to D&A, WACC via Hamada, Gordon Growth terminal value, plausibility guards on the output; historical and proforma financials with EBIT, EBITDA, income tax, net income margin, and proforma EPS; Y1 quarterly breakdown (actuals + seasonality-based estimates)
- **ML comps valuation** (`historic_fundamentals/ml_comps_model.py`) — XGBoost quantile regression predicting a fair P/E, EV/EBITDA, P/FCF, and P/S multiple per stock vs. sector peers, converted to a fair-price range; additive to `goal_pe`/`goal_low`/`goal_high`. Enabled via `--enable-ml-comps`, which is live in the production monthly cron (see [ML Comps Valuation](#ml-comps-valuation) below)
- **Bulk import CLI** (`run_bulk_import.py`) — batch-imports many tickers from a CSV with concurrent processing
- **IB Trader** (`ib_trader/`) — Interactive Brokers execution layer: connects to TWS, computes target positions from live scores, diffs current holdings, and submits MOC/MKT/LMT orders; includes a CLI rebalancer and an interactive REPL for ad-hoc orders

## Quick Start

### Web app

Runs as systemd user services (`finview-api`, `finview-web`), auto-started on boot/login:

```bash
systemctl --user status finview-api finview-web
systemctl --user restart finview-api finview-web   # apply code changes
systemctl --user stop finview-api finview-web
systemctl --user start finview-api finview-web
journalctl --user -u finview-api -f                # tail logs (also finview-web)
```

For active development with hot reload, stop the services first, then run manually:

```bash
systemctl --user stop finview-api finview-web

# Terminal 1 — backend (port 8000)
uv run uvicorn api.main:app --reload

# Terminal 2 — frontend (port 3000)
cd web && npm run dev
```

`scripts/start.sh`/`scripts/stop.sh` also still work, but only while the systemd services
are stopped — otherwise both fight over ports 8000/3000.

Open http://localhost:3000, enter a ticker, set periods (default: 10 FY), click Import.

Importing FY data automatically downloads up to 20 quarters in the background. Switch the display between annual and quarterly using the FY / Q toggle in the Financials table.

### Bulk import (CLI)

```bash
# Annual (default), last 20 filings
uv run run_bulk_import.py tickers.csv

# Quarterly, last 8 quarters
uv run run_bulk_import.py tickers.csv --quarterly --periods 8

# Annual, 10 years, AI fallback for better XBRL coverage
uv run run_bulk_import.py tickers.csv --periods 10 --ai

# 5 tickers in parallel (default: 3)
uv run run_bulk_import.py tickers.csv --concurrency 5
```

CSV format — any of these column names work: `ticker`, `symbol`, `stock`. First column used if none found.

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tickers` | List all tickers in DB |
| `POST` | `/import` | Import a ticker from SEC EDGAR |
| `GET` | `/statements/{ticker}/{type}` | Query statements (type: `income`, `balance`, `cashflow`) |
| `GET` | `/dcf/{ticker}` | Run DCF with model defaults |
| `POST` | `/dcf/{ticker}/run` | Re-run DCF with user-supplied overrides |
| `GET` | `/screen/metadata` | Sector/industry lists for screener dropdowns |
| `POST` | `/screen` | Stock screener — filter by 18 fundamental metrics |
| `GET` | `/sector/snapshot` | Current sector or industry fundamentals + VMQ composite score |
| `GET` | `/sector/history` | Monthly timeseries for one sector/industry (for charts) |
| `GET` | `/sector/companies` | Company fundamentals filtered to one sector/industry |
| `GET` | `/av/{ticker}/financials` | Alpha Vantage income/balance/cashflow statements |
| `GET` | `/av/{ticker}/overview` | Company overview (sector, industry, name, beta, market cap) |
| `GET` | `/earnings/report` | Earnings call transcript summary (params: `ticker`, `quarter`, `model`) |
| `POST` | `/earnings/import-url` | Import transcript from a PDF/HTML URL and summarize |
| `POST` | `/earnings/import-audio` | Transcribe an earnings call mp3/mp4 (Whisper) and summarize |
| `GET` | `/earnings/models` | List available LLM models for transcript summarization |
| `GET` | `/earnings-calendar` | Upcoming/recent earnings dates for tracked tickers (30-day lookback) |
| `POST` | `/research/{ticker}` | AI-generated equity research summary |
| `GET` | `/industry-research/industries` | List industries with member counts, for the picker |
| `GET` | `/industry-research/report` | AI-generated industry research report (params: `industry` or `tickers` for a custom basket, `model`, `retry`) |
| `GET` | `/industry-research/status` | Live generation status/phase for polling |
| `POST` | `/industry-research/cancel` | Cancel an in-progress industry report generation |
| `GET` | `/industry-research/models` | List available LLM models for industry research |

Import request body:
```json
{"ticker": "AAPL", "periods": 10, "period_type": "FY"}
```
`period_type` is `"FY"` (annual 10-K) or `"Q"` (quarterly 10-Q).

Statement query params: `?period_type=FY&periods=10`

DCF run override body (all fields optional):
```json
{
  "years": {
    "1": {"revenue_growth": 0.08, "cogs_pct": 0.42, "sga_pct": 0.06, "da_pct": 0.04},
    "2": {"revenue_growth": 0.07}
  },
  "terminal_growth_rate": 0.025,
  "risk_free_rate": 0.043,
  "market_risk_premium": 0.055,
  "beta": 1.2,
  "cost_of_debt": 0.04,
  "tax_rate": 0.21,
  "dso": 45.0,
  "dpo": 60.0,
  "dio": 10.0,
  "y1_quarter_revenues": {"1": 95000000000, "2": 89000000000}
}
```

## DCF Model

The DCF uses FCFF (Free Cash Flow to the Firm):

```
EBIT   = Revenue × (1 - cogs_pct - sga_pct - rd_pct - other_opex_pct)
NOPAT  = EBIT × (1 - tax_rate)
FCFF   = NOPAT + D&A - CapEx - ΔNWC
ΔNWC   = derived from DSO / DPO / DIO working capital days
TV     = FCFF₁₀ × (1 + g) / (WACC - g)  [Gordon Growth]
EV     = Σ PV(FCFF₁..₁₀) + PV(TV)
```

Forecasting:
- **Revenue Y1-Y2**: exponentially weighted mean of historical annual growth rates (decay 0.5) blended with a quarterly momentum signal (EWM of last-4-quarter YoY growth + linear trend): 50% momentum / 50% annual for Y1, 25% / 75% for Y2. **Both are then capped** — Y1 at 60% (`MAX_YEAR1_GROWTH`), Y2 at 30% (`MAX_FADE_START_GROWTH`). Neither figure is an analyst estimate; both are extrapolations, and the momentum term's linear projection is unbounded, so an accelerating company extrapolates its own acceleration. Uncapped, MU read 194% for Y1 and 103% for Y2 during the AI-memory boom, and a random sample found year-1 forecasts up to 5,520%
- **Revenue Y3-Y10**: fade linearly from Y2's capped growth rate to terminal growth by year 10. A user-pinned year re-anchors the fade rather than being overwritten by it
- **P&L ratios** (cogs_pct, sga_pct, rd_pct, interest_pct, other_opex_pct): historical mean over the 5 most recent annual periods, applied flat across all 10 forecast years. Mean-reversion is the standard DCF assumption — margins are bounded by competitive dynamics over the horizon
- **other_opex_pct**: residual between gross profit and operating income, net of SG&A and R&D already captured. Absorbs operating costs reported outside standard line items (e.g. Amazon fulfillment, technology, content). Prevents EBIT from being overstated when companies have significant operating costs not mapped to COGS/SG&A/R&D
- **D&A**: normalized 5-year mean from the CF statement, applied flat
- **CapEx**: starts from the same normalized 5-year mean, then **fades linearly to D&A** by year 10. The gap between them is growth investment, which should not persist into perpetuity — the direct analogue of fading growth to terminal growth. A company already spending below D&A is left alone rather than faded upward
- **EBIT margin**: median over **5** annual periods (`_median_ebit_margin`). Three years cannot normalise a cyclical — MU's last three were 26.4%, 5.2% and -37.0%, so the median landed on the bust-to-boom transition year and the DCF forecast MU to win the AI boom on volume while never earning from it. Five years gives 22.7%, matching the `operating_margin_5y_median` that `pe_stats` and the cycle rubric already treat as normal
- All forecasts use **annual** 10-K data; quarterly income data is used only for the momentum signal and is handled correctly for both standalone and YTD-cumulative filers
- **Historical EBIT fallback**: when `operating_income` is null in the DB (common with pharma/healthcare XBRL filers), EBIT is derived as `gross_profit − SG&A − R&D`
- **Y1 quarterly detail**: the DCF tab shows a quarterly breakdown of Y1 mixing reported actuals with seasonality-based estimates for unreported quarters. Quarterly revenue estimates can be overridden via `y1_quarter_revenues` in the run request

**Output guards** (`dcf/model.py`) — a DCF that cannot produce a meaningful number fails explicitly
rather than returning a wrong one. Both write `status='error'` with the reason into `dcf_results`:
- **Non-positive intrinsic value** rejected. A negative value per share is not a valuation; it means
  the assumptions do not describe a going concern.
- **`MAX_INTRINSIC_TO_PRICE = 10.0`** — an intrinsic value above 10x the market price is a
  computation failure, not a bargain. Before this guard the universe contained GNTX at $1,099,172
  per share against a $23.64 price. Deliberately loose: a genuinely mispriced company can be worth
  several times its price.

As of 2026-08-20 this leaves ~19% of the universe with no mechanical DCF (2,149 ok / 512 error of
2,661). That is intended — the AI Researcher takes its DCF degradation path for those tickers
instead of anchoring on a number nobody can defend. **There is no accuracy measurement for the DCF**;
these guards establish plausibility only. See `features/dcf/PLAN_DCF_ACCURACY.md`.

**WACC** (`dcf/wacc.py`):
- Cost of equity: CAPM — `ke = rf + β × MRP`. Beta from yfinance; rf from FRED DGS10; MRP defaults to 5.5% (Damodaran).
- Cost of debt: `kd = annual_interest_expense / avg_quarterly_debt`, clamped [2%, 15%]. Uses the **annual** income statement for interest expense so the full-year amount is divided by debt (not a quarterly fraction).
- Capital structure weights: market-value based (`total_debt` from latest quarterly balance sheet; `market_cap = price × diluted_shares`).
- Diluted shares: three-level fallback — quarterly income statement → annual income statement → derived from `net_income / diluted_eps`.
- Hamada equation unlever/re-lever beta at the current D/E ratio.
- `DcfResult.warnings` carries a list of data quality messages (e.g. zero market cap, WACC below 5%, terminal growth clamped). Shown as amber banners in the UI.

## Alpha Vantage Pipeline

Two databases driven by the Alpha Vantage API, both independent of the SEC EDGAR pipeline.

### .env variables

```
ALPHA_VANTAGE_API_KEY=<your premium key>
PRICES_DB_PATH=/path/to/trade_systems/data/prices.duckdb
AV_DB_PATH=data/av_financials.duckdb              # optional override
HF_DB_PATH=data/historic_fundamentals.duckdb      # optional override
```

### Adding new tickers (all-in-one)

```bash
# Fetches all AV data + prices + computes PE history + analyst estimates in one pass
uv run scripts/manage_tickers.py add AAPL MSFT GOOGL

# From a CSV file
uv run scripts/manage_tickers.py add --csv tickers.csv
```

This is the recommended way to onboard new tickers. It populates `av_financials.duckdb`, `prices.duckdb`, and `historic_fundamentals.duckdb` with a single command (~8 AV calls/ticker).

### Monthly update

```bash
# 1. Refresh all AV raw data (statements + shares + dividends + company overview) — ~115 min
uv run scripts/av_update.py

# 2. Recompute all derived metrics + refresh analyst estimates + sector stats — ~20 min
uv run scripts/hf_update.py
```

First-time setup: run `uv run scripts/av_import_overview.py` once after `av_update.py` to backfill company overview for all tickers (~19 min, 1 AV call/ticker).

### Query raw financials and company overview

```bash
uv run scripts/av_query.py AAPL
uv run scripts/av_query.py AAPL MSFT --statement income --period annual
uv run scripts/av_query.py AAPL --start 2020-01-01 --end 2024-12-31
uv run scripts/av_query.py AAPL --statement balance --out output.csv
uv run scripts/av_query.py AAPL --overview                   # latest company overview snapshot
uv run scripts/av_query.py AAPL --overview --history         # all monthly overview snapshots
```

### Query historic fundamentals (PE, P/FCF, EV/EBITDA, sector/industry peers, market cap, growth, estimates)

```bash
uv run scripts/hf_query.py AAPL                              # PE, P/FCF, EV/EBITDA, FCF yield, forward multiples, market cap, growth, sector peer ranks
uv run scripts/hf_query.py AAPL --view timeseries           # monthly PE, P/FCF, EV/EBITDA, FCF yield, TTM revenue/FCF/EBITDA
uv run scripts/hf_query.py AAPL --view estimates            # analyst estimates
uv run scripts/hf_query.py --all --out output.csv           # export all tickers
uv run scripts/hf_query.py --view sector                    # latest sector aggregate medians (PE, P/FCF, EV/EBITDA, yields, growth, quality)
uv run scripts/hf_query.py --view sector --group industry   # same for industry level
uv run scripts/hf_query.py --view sector-history --name TECHNOLOGY  # monthly sector timeseries
```

The rate limiter enforces the 75 calls/minute premium plan limit. Each ticker costs 6 AV calls for raw data (3 statements + shares + dividends + overview); bulk throughput is ~12 tickers/minute.

## Earnings Call Transcript Pipeline

Transcripts are fetched from Alpha Vantage (`EARNINGS_CALL_TRANSCRIPT`) and cached in `data/earnings_transcripts.duckdb`. The shared module `historic_fundamentals/earnings_transcripts.py` handles all DB and AV-fetch logic, including `probe_quarters()`/`refresh_latest_transcript()` — the single cache-aside "probe AV for anything newer than what's cached, write through, stop on a real AV error instead of exhausting every candidate quarter" helper shared by the Finview Earnings tab, both AI Researchers, and the two cron scripts below.

### One-time backfill (latest 4 quarters per ticker)

```bash
uv run scripts/earnings_backfill.py              # all ~2,644 tickers, ~2.5 hrs
uv run scripts/earnings_backfill.py --ticker AAPL
uv run scripts/earnings_backfill.py --dry-run    # preview without API calls
uv run scripts/earnings_backfill.py --quarters 8 # extend to 8 quarters
```

### Weekly updates (cron, via `cron_wrap.sh` — see `crontab -l`)

```bash
uv run scripts/earnings_update.py               # all tickers, ~45 min. Cron: Sunday 19:30 ET
uv run scripts/earnings_update.py --ticker MSFT
uv run scripts/earnings_calendar_update.py       # AV EARNINGS_CALENDAR, 3mo horizon. Cron: Monday 5:45 ET
```

Both transcript scripts are resume-safe — already-cached `(symbol, quarter)` pairs are skipped. Quarter format is `YYYYQN` (e.g. `2026Q2`) and follows each company's own fiscal quarter, not the calendar quarter (`fiscal_date_to_quarters()` uses the ticker's fiscal year end month). A 60-day lookahead rule automatically probes the quarter after the latest one in `av_financials.duckdb` when it may have already reported. `earnings_calendar_update.py` upserts into the `earnings_calendar` table in `av_financials.duckdb` (served by `GET /earnings-calendar`) and purges entries older than 30 days.

The Finview Earnings tab and both AI Researchers also fetch and cache transcripts on demand when a newer quarter isn't in the database yet, ahead of the weekly cron.

---

## AI Research

Two LLM-generated research features, both in the Finview UI, both cached (24h TTL) and backed by the same multi-agent fan-out/fan-in pattern (`agents` SDK via OpenRouter):

- **AI Research tab** (`api/research_router.py`) — single-name equity research report for one ticker: 4 parallel specialist sub-agents (Competitive & Strategy, Earnings & MD&A Historian, Technical Analyst, an independent price-blind Valuation Analyst) feeding a Chief Analyst synthesis. Includes a follow-up chat grounded in the generated report. The Valuation Analyst is fed two independent DCFs — the mechanical bear/base/bull scenarios plus the Agentic AI DCF Valuator below — and reconciles them under a neutral preference rule (no hard-coded favorite) in a new `dcf_reconciliation` field.
- **Agentic AI DCF Valuator** (`api/ai_dcf_router.py`, data layer in `api/ai_dcf_data.py`) — a second, independent DCF source: three evidence sub-agents (Fundamentals Historian, Industry & Competitors, Guidance & MD&A) feed a senior DCF Architect persona that authors per-year bear/base/bull revenue growth, margin, and capex assumptions grounded in company history, industry trends, competitor transcripts, and multi-year MD&A/guidance. The LLM only authors assumptions; the same deterministic `dcf.run_dcf_av` engine that powers the mechanical scenarios computes the actual valuation. Standalone endpoints (`GET /research/ai-dcf{,/status}`, `POST /research/ai-dcf/cancel`) plus an in-process, cache-aware entry point (`get_or_run_ai_dcf`) shared with the AI Research tab above. Full design rationale, architecture, and phased build record (including two real bugs found and fixed during live verification): `features/ai_dcf/SPEC.md` and `features/ai_dcf/PLAN.md`.
- **Industry Research tab** (`api/industry_research_router.py`, data layer in `api/industry_data.py`) — cross-company industry research report: pick an AV `industry` (e.g. "Semiconductors" — deliberately finer-grained than sector, since a sector like Technology can span industries on very different cycles) or supply a custom ticker basket. A map-reduce pipeline digests each company's trailing earnings calls individually, then two specialists (Trends & Developments, Risks & Outlook) and a Chief Strategist synthesize industry-wide themes and a ranked table of relative (over/neutral/underweight) ideas across the analyzed companies. Every number in the report — valuation, growth, EPS surprises, the ranked-ideas metrics — is computed in Python from the database, never authored by the LLM. Full design rationale, architecture, and phased build record: `features/industry_research/SPEC.md` and `features/industry_research/PLAN.md`.

Both default to per-agent model tiering (Claude Sonnet 5 for numeric/high-stakes roles, DeepSeek/
GPT-5.6 Luna for qualitative synthesis and extraction — see `STATUS.md`), or a single explicit
model (Claude, Gemini, Qwen, GLM, Grok via OpenRouter) can be picked per report, overriding every
agent uniformly. Each generated report shows its own real generation cost and token count,
computed from the OpenRouter API's actual per-call usage.

---

## Fundamentals Alpha — Operational Flow

Monthly rebalance workflow for the `vw_gr_top_n_25` strategy (vol-weighted composite score, top 25 holdings).
Backtest: 24.5% CAGR, 1.35 Sharpe, -21.6% MaxDD, 71.1% win rate (211 months).

### Step 1 — Refresh fundamentals data (once per month, after earnings season)

```bash
# Refresh raw AV data: statements, shares, dividends, company overview (~115 min, 6 calls/ticker)
uv run scripts/av_update.py

# Recompute derived metrics + analyst estimates + sector stats (~20 min, 1 call/ticker)
uv run scripts/hf_update.py
```

Fundamentals update quarterly, so monthly is sufficient. Skip-flags are available when needed:

```bash
uv run scripts/av_update.py --skip-overview     # omit OVERVIEW calls (~95 min)
uv run scripts/hf_update.py --skip-estimates    # PE/yield recompute only, no AV calls
```

### Step 2 — Score the universe and get the rebalance list

```bash
uv run scripts/score_live.py --top 25
```

Outputs ranked table to stdout and writes `docs/live_scores_{YYYYMMDD}_vw_gr_top_n_25.csv`.

What the script produces:
- Top 25 tickers ranked by composite score (value + quality + momentum), sector-capped at 25%
- **Inverse-vol weights** (`weight_pct`): sized by 1/trailing-12m-vol, capped at 10% per position
- **Regime signal**: if SPY 12m return > +25% or < -20%, `alloc_pct` is reduced to 50% of `weight_pct` (remainder goes to cash)
- **Guardrails** (on by default): excludes value traps and stocks with >2 missing factors
- `feature_available_date` column confirms each row is point-in-time safe

Useful flags:

```bash
uv run scripts/score_live.py --top 25 --no-guardrails    # include value traps / partial data
uv run scripts/score_live.py --top 25 --verbose          # show debug output
```

### Step 3 — Review the CSV

Open `docs/live_scores_{YYYYMMDD}_vw_gr_top_n_25.csv` and check:
- Regime label (FULL 100% vs REDUCED 50%)
- Any `value_trap=True` or `data_quality=poor` entries near the top
- `top_factor` column for the primary driver per stock

### Step 4 — Execute the rebalance via IB

```bash
# Dry run first — previews orders without submitting (default)
uv run scripts/rebalance.py

# When satisfied, submit MOC orders to IB
uv run scripts/rebalance.py --no-dry-run
```

`rebalance.py` auto-finds the latest `docs/live_scores_*.csv`. Only rows with a non-empty `alloc_pct` are treated as portfolio positions.

### Summary

| Step | Script | Frequency | Time |
|------|--------|-----------|------|
| 1a. Refresh raw data | `av_update.py` | Monthly | ~115 min |
| 1b. Recompute metrics | `hf_update.py` | Monthly | ~20 min |
| 2. Score universe | `score_live.py` | Monthly on rebalance day | seconds |
| 3. Review CSV | — | — | manual |
| 4. Execute trades | `rebalance.py --no-dry-run` | Monthly | seconds |

---

## ML Comps Valuation

Cross-sectional peer-comps model: predicts a fair P/E, EV/EBITDA, P/FCF, and P/S multiple for each stock from its fundamentals vs. sector peers (XGBoost quantile regression, low/mid/high range), converted to a fair-price band. Additive to the `goal_pe`/`goal_low`/`goal_high` fields already surfaced in the Fundamentals tab, which compare a ticker to its *own* multiple history rather than peers — both are shown side by side. Full build record and validation gate: `features/historic_fundamentals/ml_comps_valuation_plan.md`.

```bash
# One-time / after retraining: validate the model beats a naive sector-median baseline
# (~2-2.5hr for the 4 multiples; measured 130 min on 2026-08-19 — a 50-min timeout has killed it before)
uv run scripts/validate_ml_comps_valuation.py

# Train final production models (all 4 — see PASSING_MULTIPLES in historic_fundamentals/ml_comps_model.py)
uv run scripts/train_ml_comps_valuation.py

# Score the current universe -> ml_comps_valuation table -> /av-fundamentals/{ticker} API fields
uv run scripts/score_ml_comps_valuation.py

# Retrain history / drift visibility
uv run scripts/report_ml_comps_history.py
```

Pass `--enable-ml-comps` to `scripts/run_pipeline.py` to include training + scoring. **This is
already live in the production monthly cron** — it is off by default for a manual run only.

EV/EBITDA was excluded until 2026-08-19 for missing the 15% RMSE-improvement gate by 0.3pp. That
was never a modelling shortfall: the enterprise value feeding it counted only the current portion
of debt. With that fixed and the universe recomputed it clears every criterion (+26.4% RMSE
improvement, second-best of the four; 100% fold win rate; 74.5% coverage) and is now a production
multiple.

---

## IB Trader

Execution layer for Interactive Brokers TWS. Requires TWS or IB Gateway running locally with API enabled.

### .env variables

```
IB_HOST=127.0.0.1              # TWS hostname (default: 127.0.0.1)
IB_PORT=7497                   # 7497 = paper, 7496 = live
IB_CLIENT_ID=1                 # TWS client ID (must be unique per connection)
IB_ACCOUNT=                    # account number (auto-detected if blank)
IB_MARKET_DATA_TYPE=3          # 1 = live (default for live accounts), 3 = delayed (default for paper)
```

### Portfolio rebalance (CLI)

```bash
# Dry run — preview orders without submitting (default)
uv run scripts/rebalance.py

# Dry run with explicit scores CSV
uv run scripts/rebalance.py --scores docs/live_scores_20260519.csv

# Submit orders to IB
uv run scripts/rebalance.py --no-dry-run

# Show account status only
uv run scripts/rebalance.py --status

# Cancel all open orders
uv run scripts/rebalance.py --cancel-all
```

Scores are loaded from the latest `docs/live_scores_*.csv` (produced by `score_live.py`) unless `--scores` is given. Only rows with a non-empty `alloc_pct` are treated as portfolio positions. Run `score_live.py` before rebalancing.

### Interactive REPL

```bash
uv run scripts/ib_repl.py
```

Ad-hoc trading and inspection. Commands: `status`, `buy/sell TICKER QTY [TYPE [PRICE]]`, `quote TICKER`, `cancel ORDER_ID|all`, `preview [PATH]`, `rebalance [PATH] [--confirm]`, `help`, `quit`.

---

## Tests

```bash
# Fast tests (no network)
uv run pytest tests/test_api.py -m "not integration"

# Integration tests (hit SEC EDGAR, ~10-30s each)
uv run pytest tests/test_api.py -m integration
```

## Bulk import options

```
uv run run_bulk_import.py tickers.csv [options]

--periods N       Filings per ticker (default: 20)
--quarterly       Import 10-Q instead of 10-K
--db PATH         Database path (default: data/financial_statements.duckdb)
--ai              AI fallback for unmapped XBRL concepts
--no-skip         Re-import existing filings
--delay SECS      Extra seconds between SEC requests (default: 0; edgartools has built-in rate limiter)
--concurrency N   Tickers to process in parallel (default: 3)
--output DIR      Reports directory (default: ./bulk_import_results)
--log FILE        Log file (default: bulk_import.log)
```

## Project layout

```
api/
  main.py              FastAPI app, routes
  importer.py          Import logic (fetch SEC filings, extract, insert)
  db.py                DuckDB connection wrapper
  dcf_router.py        DCF endpoints (GET /dcf/{ticker}, POST /dcf/{ticker}/run)
  research_router.py            Single-name AI equity research: fan-out/fan-in multi-agent pipeline + chat
  ai_dcf_router.py               Agentic AI DCF Valuator: evidence team -> DCF Architect -> dcf.run_dcf_av
                                 (LLM authors assumptions only; features/ai_dcf/SPEC.md)
  ai_dcf_data.py                 AI DCF data layer: fundamentals history, MD&A, industry report, competitor transcripts
  industry_research_router.py   Industry AI research: map-reduce pipeline (per-company digest -> Trends/Risks -> Chief),
                                 strictly at AV `industry` grain, never sector (features/industry_research/SPEC.md)
  industry_data.py               Industry research data layer: resolvers, aggregates, member financials, beat/miss, estimates
dcf/
  assumptions.py       Dataclasses: YearForecast, UserOverrides, DcfResult, NwcAssumptions, HistoricalRow
  forecaster.py        Historical mean for P&L ratios; normalized mean for D&A and CapEx; DSO/DPO/DIO
  model.py             FCFF construction, terminal value, equity bridge
  wacc.py              WACC, CAPM, cost of debt, Hamada beta re-levering
  data.py              Reads from financial_statements.duckdb, prices.duckdb, fred.duckdb
web/                   Next.js frontend (port 3000)
  app/page.tsx         Main page: tab manager, ticker loader, all tab panels
  components/
    ImportForm.tsx           Ticker input, period selector, import button
    ScreenerViewer.tsx       Stock screener: 18-metric filter panel + results table
    SectorViewer.tsx         Sector/industry dashboard: VMQ rankings, 5yr chart, company drill-down
    AvFinancialsViewer.tsx   Alpha Vantage income/balance/cashflow statements
    AvDcfViewer.tsx          AV-data-powered DCF valuation
    FundamentalsViewer.tsx   PE/FCF/EV/EBITDA history, goal prices, valuation signals
    EquityResearchViewer.tsx AI-generated equity research report
    IndustryResearchViewer.tsx AI-generated industry research report: industry/custom-basket picker, live status, clickable ticker cells
    EarningsSummaryViewer.tsx Analyst earnings estimates + revenue consensus
    StatementViewer.tsx      SEC XBRL financials table with FY/Q toggle
    DcfViewer.tsx            DCF container: state management, Reset/Update actions
    DcfSummary.tsx           Valuation summary + editable WACC inputs
    DcfStatements.tsx        Historical & proforma table with editable forecast ratios
    DcfQuarterly.tsx         Y1 quarterly detail: actuals + seasonality estimates
    DcfNwcCapex.tsx          DSO/DPO/DIO inputs + projected NWC and CapEx per year
    DcfFcffTable.tsx         FCFF build-up table + EV bridge
    DcfTerminalValue.tsx     Terminal value decomposition card
    DcfSensitivity.tsx       2D sensitivity table (WACC × terminal growth)
    ValuationRangeBand.tsx   Low/mid/high range bar w/ current-value marker; used by the ML Fair Value panel
  lib/
    dcf-types.ts         TypeScript interfaces for all DCF data
    formatField.ts       blurFormat / focusStrip / parsePct utilities
    useArrowNav.ts       useLinearArrowNav / useGridArrowNav keyboard nav hooks
extractors/
  statement_extractor.py          Shared 2-pass extractor core (static + AI fallback)
  income_statement_extractor.py   Thin wrapper — income-specific mapping + validation
  balance_sheet_extractor.py      Thin wrapper — balance sheet
  cash_flow_extractor.py          Thin wrapper — cash flow
xbrl_mappings/         Static XBRL concept → field mappings
historic_fundamentals/         Monthly PE/P/FCF/EV/EBITDA timeseries + sector/industry peer stats + market cap + growth + analyst estimates
  __init__.py                  Public API: get_pe_stats, get_pe_history, get_estimates, get_sector_stats, get_sector_history
  db.py                        HistoricFundamentalsDB: schema (monthly_pe, pe_stats, earnings_estimates, sector_stats), upsert, query
  pe.py                        TTM EPS/FCF/EBITDA + PE/P/FCF/EV/EBITDA + dividend/revenue/earnings/FCF growth stats
  estimates.py                 EARNINGS_ESTIMATES fetch, normalize, forward PE/P/FCF/NTM revenue calculation
  sector.py                    compute_sector_stats(): monthly median/p25/p75 aggregates per sector and industry
  query.py                     Notebook-friendly wrappers: get_pe_stats() (with peer ranks), get_pe_history(), get_estimates(), get_sector_stats(), get_sector_history()
  ml_comps_model.py            ML comps valuation: feature assembly, XGBoost quantile fit/predict, walk-forward harness, fit/transform-split sector z-scoring
scripts/
  manage_tickers.py            Add/delete tickers across all three DBs (prices + AV + historic fundamentals)
  av_import.py                 Import AV financials + shares + dividends (single/CSV/prices.duckdb)
  av_import_overview.py        Backfill company overview (name, sector, industry, beta + 41 fields) for all tickers
  av_import_shares.py          Standalone backfill: shares_outstanding for existing tickers
  av_import_dividends.py       Standalone backfill: dividends for existing tickers
  av_query.py                  Query AV financial statements + company overview (--overview, --history flags)
  av_update.py                 Monthly refresh: all AV data (statements + shares + dividends + overview)
  hf_import.py                 Bulk backfill: PE history + estimates for all AV tickers
  hf_update.py                 Monthly update: recompute PE/yield + refresh estimates + sector stats (--skip-sector, --full-sector-rebuild)
  hf_query.py                  CLI query: stats, timeseries, estimates, sector, sector-history views; CSV export
  update_alpha_vantage_estimates.py  Update analyst EPS/revenue estimates from AV
  earnings_backfill.py         One-time backfill: latest 4 quarters of earnings call transcripts for all AV tickers
  earnings_update.py           Weekly update (cron): check for new earnings call transcripts across all tickers
  earnings_calendar_update.py  Weekly update (cron): refresh earnings_calendar from AV EARNINGS_CALENDAR
  score_live.py                Live scoring: ranked investable portfolio with alloc_pct; writes docs/live_scores_YYYYMMDD.csv
  rebalance.py                 IB portfolio rebalancer CLI (dry run by default); reads latest live_scores CSV
  ib_repl.py                   Interactive REPL for IB: status, buy/sell, quote, cancel, rebalance
  validate_ml_comps_valuation.py  ML comps valuation go/no-go gate: walk-forward vs. naive sector-median baseline
  train_ml_comps_valuation.py     Train final quantile models (P/E, P/FCF, P/S) on a rolling 5yr window; saves to data/ml_comps_valuation/
  score_ml_comps_valuation.py     Batch-score current universe -> ml_comps_valuation table
  report_ml_comps_history.py      Retrain history / drift visibility from ml_model_metadata
ib_trader/
  __init__.py                  Public API: IBClient, make_order, place_order, cancel_all_open_orders, get_order_status, OrderSpec, load_scores_csv, find_latest_scores, build_target, diff_portfolio, summarise_diff, run_rebalance
  client.py                    IBClient: connect, get_nav, get_positions, qualify_contracts, get_live_prices, get_live_midprices
  orders.py                    make_order, place_order, cancel_all_open_orders, get_order_status; MOC cutoff warning
  portfolio.py                 OrderSpec, load_scores_csv, find_latest_scores, build_target, diff_portfolio, summarise_diff
  rebalance.py                 run_rebalance: NAV fetch, live prices, target build, diff, dry-run/submit
  interactive.py               run_repl, _print_status, _print_quote, _handle_buy_sell, _handle_cancel, _handle_rebalance
xbrl_concept_mapper.py          AI-assisted fallback mapper (openai-agents)
av_financials_db.py             Alpha Vantage DB class: schema, rate limiter, fetch, upsert, query (includes company_overview)
financial_statements_db.py      SEC EDGAR DB class: schema, insert helpers, log_extraction()
bulk_import_10k.py              Core bulk import logic (async, concurrent)
run_bulk_import.py              CLI entry point for SEC EDGAR bulk imports
tests/                 pytest tests
data/
  financial_statements.duckdb       SEC EDGAR financial statements
  av_financials.duckdb              Alpha Vantage: statements, shares outstanding, dividends, company overview, earnings_calendar
  historic_fundamentals.duckdb      Monthly PE/P/FCF/EV/EBITDA timeseries, valuation stats, sector/industry aggregates, analyst estimates, ML comps valuation cache
  earnings_transcripts.duckdb       Earnings call transcripts: text, fetched_date, api_response_json, source (av/url/audio); also earnings_surprises
  xbrl_mappings_multi.duckdb        AI-discovered XBRL concept mapping store
```
