# Project Structure

```
fin_import2/
├── api/
│   ├── main.py                          FastAPI app and route definitions
│   ├── importer.py                      Import logic: fetch SEC filings, extract, insert
│   ├── db.py                            DuckDB connection wrapper
│   ├── dcf_router.py                    DCF endpoints: GET /dcf/{ticker}, POST /dcf/{ticker}/run
│   ├── screener_router.py               Stock screener: POST /screen, GET /screen/metadata; includes Graham net current asset
│   │                                    value (NCAV = current assets - total liabilities, Security Analysis Ch. XLIII)
│   ├── sector_router.py                 Sector dashboard: GET /sector/snapshot, /sector/history, /sector/companies
│   ├── earnings_router.py               Earnings call transcripts: GET /earnings/report, POST /earnings/import-url, POST /earnings/import-audio,
│   │                                    GET /earnings/models, POST /earnings/chat
│   ├── earnings_calendar_router.py      Earnings calendar: GET /earnings-calendar. Reads earnings_calendar (av_financials.duckdb) joined with
│   │                                    company_overview, 30-day lookback, status ('reported'/'upcoming') derived at query time
│   ├── research_router.py               AI equity research: GET /research/{ticker}. Valuation Analyst sub-agent context now includes
│   │                                    a second, independent AI-authored DCF (via ai_dcf_router.get_or_run_ai_dcf) alongside the
│   │                                    mechanical bear/base/bull scenarios; neutral reconciliation rule in dcf_reconciliation
│   │                                    (features/ai_dcf/SPEC.md 6.8). Cache: research_cache.duckdb
│   ├── ai_dcf_router.py                 Agentic AI DCF Valuator: GET /research/ai-dcf{,/status}, POST /research/ai-dcf/cancel.
│   │                                    Evidence team (Fundamentals Historian / Industry & Competitors / Guidance & MD&A, parallel)
│   │                                    -> DCF Architect (senior valuation persona authors per-year bear/base/bull revenue growth,
│   │                                    cogs_pct, EBIT margin, capex%, TG) -> guardrails (capex ceiling is ticker-anchored on its own
│   │                                    historical max + 15pp, not one flat % for every sector) -> dcf.run_dcf_av x3 (LLM never computes the
│   │                                    valuation itself). get_or_run_ai_dcf is the in-process, cache-aware entry point shared with
│   │                                    research_router (joins an in-flight task instead of double-starting). Cache: ai_dcf_cache.duckdb.
│   │                                    See features/ai_dcf/SPEC.md and PLAN.md.
│   ├── ai_dcf_data.py                   Agentic AI DCF Valuator data layer: get_fundamentals_history, get_mda_history (mda_filings.duckdb,
│   │                                    currently unused elsewhere), get_industry_report (14-day read window into
│   │                                    industry_research_cache.duckdb, bypasses that router's 24h TTL), get_competitor_transcripts
│   │                                    (cached-only, zero new Alpha Vantage calls), get_engine_context, get_historical_margin_bounds
│   │                                    (incl. capex_pct_max — the ticker's own historical capex ceiling, added 2026-08-27).
│   ├── industry_research_router.py      Industry AI research: GET /industry-research/{industries,models,report,status}, POST /industry-research/cancel
│   │                                    Map-reduce multi-agent pipeline (per-company digest -> Trends/Risks specialists -> Chief) at strict AV
│   │                                    `industry` grain (never sector — see features/industry_research/SPEC.md 2.1). Cache: industry_research_cache.duckdb
│   ├── industry_data.py                 Industry AI research data layer: list_industries, resolve_members, get_industry_aggregates,
│   │                                    get_member_financials, get_industry_beat_miss, get_industry_estimates, get_industry_transcripts,
│   │                                    get_industry_web_search, scope_key. `*_raw`/`*_df` + `format_*` split (fetch once, format many) to
│   │                                    avoid duplicate Alpha Vantage calls between LLM-context text and markdown appendix tables.
│   └── av_router.py                     Alpha Vantage fundamentals: GET /av-fundamentals/{ticker} (goal prices + ml_fair_* ML comps valuation fields),
│                                        GET /av-financials/{ticker}/{stmt}, GET /quote/{ticker}, GET /av-dcf/{ticker}
│
├── dcf/
│   ├── __init__.py
│   ├── assumptions.py                   Dataclasses: YearForecast, UserOverrides, NwcAssumptions, DcfResult, HistoricalRow (includes AR/AP/inventory for WC day charts)
│   ├── forecaster.py                    ARIMA(0,1,0) + OLS forecasting for P&L ratios; DSO/DPO/DIO
│   ├── model.py                         FCFF build-up, terminal value, equity bridge, historical rows
│   ├── wacc.py                          WACC, CAPM, cost of debt, Hamada beta re-levering
│   └── data.py                          Loads financials, stock price, DGS10 from DuckDB databases
│
├── web/                                 Next.js frontend (port 3000)
│   ├── app/
│   │   ├── page.tsx                     Main UI: import form, Financials + DCF Valuation tabs
│   │   └── layout.tsx
│   ├── components/
│   │   ├── ImportForm.tsx               Ticker input, period selector (default 10 FY), import button
│   │   ├── ScreenerViewer.tsx           Stock screener: 18-metric filter panel + sortable results table
│   │   ├── SectorViewer.tsx             Sector/industry dashboard: VMQ composite rankings, 5yr history chart, company drill-down
│   │   ├── AvFinancialsViewer.tsx       Alpha Vantage income/balance/cashflow statements viewer
│   │   ├── AvDcfViewer.tsx              AV-data-powered DCF valuation viewer
│   │   ├── FundamentalsViewer.tsx       PE/FCF/EV/EBITDA history, goal prices, valuation signals
│   │   ├── EquityResearchViewer.tsx     AI-generated equity research report
│   │   ├── IndustryResearchViewer.tsx   AI-generated industry research report: industry picker (or custom ticker basket), model picker,
│   │   │                                live status bar, clickable ticker cells in every appendix/ranked-ideas table (jumps to single-name AI Research)
│   │   ├── EarningsSummaryViewer.tsx    Earnings call transcript summarization: quarter selector, model picker, URL import, LLM-generated report
│   │   ├── StatementViewer.tsx          Financials table with FY/Q display toggle
│   │   ├── DcfViewer.tsx                DCF container: state, Reset/Update buttons, layout
│   │   ├── DcfSummary.tsx               Valuation summary card + editable WACC inputs (rf, mrp, beta, cod, tax)
│   │   ├── DcfStatements.tsx            Historical & proforma P&L/BS/CF table; EBIT, EBITDA, Income Tax, Net Income rows with margins; editable forecast ratios
│   │   ├── DcfNwcCapex.tsx              Editable DSO/DPO/DIO inputs; projected ΔNWC and CapEx per year
│   │   ├── DcfFcffTable.tsx             FCFF build-up (Revenue→EBIT→NOPAT→+D&A→-CapEx→-ΔNWC→FCFF→PV)
│   │   ├── DcfTerminalValue.tsx         Terminal value decomposition: FCFF₅, TV, PV(TV), TV% of EV
│   │   ├── DcfSensitivity.tsx           2D sensitivity table: intrinsic value vs WACC × terminal growth
│   │   ├── DcfQuarterly.tsx             Q1-Q4 actual vs estimated quarterly revenue, gross profit, EBIT
│   │   ├── DcfIncomeChart.tsx           Revenue/Gross Profit absolute chart + Gross/EBIT/Net margin % chart
│   │   ├── DcfEfficiencyChart.tsx       Working Capital Days (DSO/DPO/DIO lines), Capex/Revenue %, Effective Tax Rate %
│   │   ├── EarningsEstimates.tsx        Analyst EPS + revenue consensus estimates table
│   │   ├── ValuationRangeBand.tsx       Low/mid/high range bar w/ current-value marker; ML Fair Value panel in FundamentalsViewer.tsx
│   │   └── ui/                          shadcn/ui primitives (Button, Input, Select)
│   └── lib/
│       ├── dcf-types.ts                 TypeScript interfaces for all DCF API shapes
│       ├── formatField.ts               blurFormat / focusStrip / parsePct utilities
│       ├── useArrowNav.ts               useLinearArrowNav (1D) / useGridArrowNav (2D) keyboard nav hooks
│       └── utils.ts                     Tailwind class merge helper
│
├── extractors/
│   ├── statement_extractor.py           Shared 2-pass extractor core (all 3 statement types)
│   ├── income_statement_extractor.py    Thin wrapper: income mapping, validation helpers
│   ├── balance_sheet_extractor.py       Thin wrapper: balance sheet mapping
│   └── cash_flow_extractor.py           Thin wrapper: cash flow mapping
│
├── xbrl_mappings/
│   ├── income_statement_xbrl_mapping.py Static XBRL concept → field mappings (30 fields)
│   ├── balance_sheet_xbrl_mapping.py    (37 fields)
│   └── cash_flow_xbrl_mapping.py        (31 fields; includes PaymentsToAcquireProductiveAssets for Amazon)
│
├── tests/
│   ├── conftest.py                      Mocks openai-agents submodules for fast tests
│   ├── test_api.py                      API tests (fast + integration; excluded from default pytest run)
│   ├── test_features.py                 Unit tests for feature formulas in pe.py (margins, leverage, yields, normalized multiples)
│   ├── test_point_in_time.py            Timing alignment tests: feature_available_date <= prediction_date, no future fundamentals
│   ├── test_universe.py                 Universe filter tests: market-cap, price, sector filter logic, NaN handling
│   ├── test_baselines.py                Baseline factor IC, quintile spread, composite score tests
│   ├── test_model.py                    Walk-forward validation tests: temporal splits, embargo enforcement, OOS metrics
│   ├── test_backtest.py                 Portfolio backtest tests: non-overlapping returns, TC calculation, benchmark alignment
│   ├── test_risk.py                     Risk diagnostics tests: exposure_report, value_trap_flags, apply_guardrails, drawdown_analysis
│   └── test_score_live.py              Live scoring tests: filter application, feature_available_date check, missing-data flags
│
├── data/
│   ├── financial_statements.duckdb      SEC EDGAR financial statements (income, balance, cashflow)
│   ├── av_financials.duckdb             Alpha Vantage financial statements (income, balance, cashflow)
│   ├── historic_fundamentals.duckdb     Monthly PE timeseries, PE statistics, analyst estimates snapshots, sector_stats, dcf_results,
│   │                                    ml_comps_valuation (live-scoring cache, additive to goal_pe/goal_low/goal_high),
│   │                                    ml_model_metadata (retrain history)
│   ├── earnings_transcripts.duckdb      Earnings call transcripts: symbol, quarter, transcript_text, fetched_date, api_response_json, source
│   │                                    Also earnings_surprises (EPS beat/miss history, 30d cache), shared by the single-name and industry AI researchers.
│   ├── mda_filings.duckdb               MD&A text from SEC EDGAR 10-K/10-Q filings: ticker, form, fiscal_period_end, mda_text,
│   │                                    char_count, status (ok/empty/error). See PLAN_MDA.md.
│   ├── industry_research_cache.duckdb   Industry AI research report cache: scope_key (industry name, or a stable hash of a custom ticker
│   │                                    basket), model, report_markdown, generated_at. 24h TTL, mirrors research_cache.duckdb's shape.
│   ├── ai_dcf_cache.duckdb              Agentic AI DCF Valuator cache: ticker, model, result_json (full AiDcfResult, for
│   │                                    get_or_run_ai_dcf's in-process reuse), report_markdown, generated_at. 24h TTL.
│   ├── xbrl_mappings_multi.duckdb       AI-discovered concept mapping store
│   └── ib_tracker.duckdb               Portfolio tracker: fills, tax lots, daily NAV, score snapshots, backtest benchmarks
│                                        Created automatically when IB_TRACKER_DB env var is set.
│
├── notebooks/
│   ├── fundamentals_alpha.ipynb         Quant alpha research: which fundamentals predict forward returns?
│   │                                    37 cells, 1,411 tickers, 1999–2026 monthly data
│   │                                    Features: valuation, quality, growth CAGRs, margins, momentum
│   │                                    ML: XGBoost per horizon + SHAP; walk-forward + live ranking
│   ├── portfolio_tracker.ipynb          Portfolio tracker interface: snapshot_report, trades, tax summary,
│   │                                    live vs backtest comparison, model IC time series chart
│   ├── valuation_model.ipynb            Legacy valuation model (replaced by fundamentals_alpha)
│   ├── ml_comps_valuation.ipynb         Monitoring: coverage/RMSE/win-rate over time (from ml_comps_validation_folds.csv),
│   │                                    feature importance from the active production models
│   └── lab.ipynb                        Scratch / exploratory
│
├── docs/
│   ├── Project_Structure.md             This file
│   ├── runbook.md                       Operational runbook: prerequisites, data pipeline, validation, live scoring, model assumptions, known limitations, go/no-go criteria
│   ├── feature_definitions.md           Feature reference: formula, signal direction, data source for all monthly_pe features
│   ├── integration_map.md               Phase 0 repository discovery and integration map
│   ├── pit_audit_report.md              Phase 1 point-in-time audit: filing-lag policy, timing-violation log, test coverage
│   ├── baseline_results.md              Phase 4 output: IC, ICIR, quintile spreads for all baseline factors (generated by run_baselines.py)
│   ├── walkforward_results.md           Phase 5 output: OOS R², rank IC, ICIR, hit rate, SHAP stability (generated by run_walkforward.py)
│   ├── backtest_results.md              Phase 6 output: CAGR, Sharpe, drawdown, turnover, TC drag vs SPY (generated by run_backtest.py)
│   ├── risk_report.md                   Phase 7 output: sector exposure, guardrails, drawdown, beta decomposition (generated by run_risk.py)
│   ├── live_scores_YYYYMMDD.csv         Phase 8 output: ranked investable universe with scores, risk flags, vol-weighted positions, regime alloc (generated by score_live.py)
│   ├── validation_report.md             Walk-forward OOS validation: per-fold IC/ICIR/NW-ICIR/HitRate/Q-spread + yearly breakdown (generated by validate_model.py)
│   ├── survivorship_bias_report.md      Survivorship bias analysis: cohort comparison, estimated 0.5–1.5 pp/year inflation
│   ├── PORTFOLIO_TRACKER_GUIDE.md       Portfolio tracker: setup, workflow, schema, slippage, FIFO tax lots, multi-strategy
│   ├── BULK_IMPORT_GUIDE.md             Bulk import CLI reference
│   ├── MULTI_STATEMENT_EXTRACTOR_GUIDE.md  Extractor internals
│   ├── ml_comps_validation_report.md    ML comps valuation gate result (generated by validate_ml_comps_valuation.py)
│   └── ml_comps_validation_folds.csv    Fold-level gate results (generated by validate_ml_comps_valuation.py); consumed by notebooks/ml_comps_valuation.ipynb
│
├── historic_fundamentals/               Historic fundamentals analytics package (PE, FCF, EV/EBITDA, P/S, ROA, ROE, ROIC, P/BV, P/TBV + sector/industry peer stats)
│   ├── __init__.py                      Public API: get_pe_stats, get_pe_history, get_estimates, get_sector_stats, get_sector_history, compute_sector_stats + lower-level exports
│   ├── db.py                            HistoricFundamentalsDB: schema (monthly_pe, pe_stats, earnings_estimates, sector_stats), upsert, query methods
│   ├── pe.py                            TTM computation engine: EPS, revenue, FCF, EBITDA, NOPAT, equity; builds monthly timeseries and statistics for all metrics
│   │                                    Also computes margins, margin stability (5yr median/slope/change), leverage (debt_to_ebitda, interest_coverage),
│   │                                    yield rolling avgs, normalized CAPE-style multiples, roa_stability_5y, and feature_available_date per row.
│   ├── estimates.py                     EARNINGS_ESTIMATES fetch, normalize, forward PE + NTM revenue calculation
│   ├── sector.py                        compute_sector_stats(): monthly median/p25/p75 aggregates per sector and industry from monthly_pe + company_overview
│   ├── query.py                         Notebook-friendly wrappers: get_pe_stats() (peer ranks), get_pe_history(), get_estimates(), get_sector_stats(), get_sector_history()
│   ├── earnings_transcripts.py          Shared earnings transcript helpers: open_db(), is_cached(), save_transcript(), fetch_from_av() (raises AVError
│   │                                    on a rate-limit/entitlement response — distinct from a genuine "no transcript" empty result),
│   │                                    fiscal_date_to_quarters(), probe_quarters(), refresh_latest_transcript() (shared cache-aside probe-and-cache
│   │                                    helper: checks the local cache, probes AV only for quarters newer than what's cached, stops probing on
│   │                                    AVError/network errors instead of exhausting the candidate list, write-through on success)
│   │                                    Used by earnings_router.py, research_router.py, industry_data.py, earnings_backfill.py, earnings_update.py
│   ├── mda.py                           MD&A (SEC EDGAR 10-K/10-Q) helpers: open_db(), fetch_mda(), fetch_all_mda_for_ticker(), get_cached_mda(), delete_ticker()
│   │                                    Used by manage_tickers.py, mda_backfill.py, mda_update.py. See PLAN_MDA.md.
│   ├── universe.py                      Investable universe filters: filter_universe(), report_universe_counts(), sensitivity_analysis(), UNIVERSE_DEFAULTS
│   │                                    Default thresholds: market_cap >= $1B, price >= $5, sector must be known. NaN values fail filters.
│   ├── baselines.py                     Rank-based single-factor and composite baseline models.
│   │                                    BASELINE_FACTORS, compute_factor_ic(), ic_summary(), quintile_returns(), composite_score(), run_all_baselines()
│   │                                    Six factors: low P/S, high FCF yield, high dividend yield, low EV/EBITDA, low P/E, high earnings yield.
│   ├── model.py                         Walk-forward XGBoost model validation with embargo.
│   │                                    walk_forward_validate(), compute_oos_metrics(), shap_stability()
│   │                                    Default: 5yr train window, 1yr test window, 12-month embargo. Primary target: ret_1y.
│   ├── backtest.py                      True monthly non-overlapping portfolio backtest.
│   │                                    run_monthly_backtest(), portfolio_metrics(), compute_universe_benchmark(), load_spy_returns()
│   │                                    PORTFOLIO_CONFIGS: top 20%, top 10%, top 50, top 25. Equal-weight or inverse-vol-weighted. TC-adjusted.
│   │                                    use_vol_weighting=True: inverse-volatility position sizing (12m rolling std, falls back to equal-weight).
│   │                                    regime_exposure: pd.Series of 0.5/1.0 exposure fractions (SPY 12m regime filter).
│   ├── risk.py                          Risk diagnostics and guardrails.
│   │                                    exposure_report(), value_trap_flags(), apply_guardrails(), constrained_holdings(),
│   │                                    drawdown_analysis(), beta_decomposition()
│   │                                    GUARDRAIL_DEFAULTS, VTF_DEFAULTS (all thresholds configurable)
│   └── ml_comps_model.py                ML comps valuation: cross-sectional peer-comps model, additive to goal_pe/goal_low/goal_high.
│                                        build_training_frame(), fit_quantile_model()/predict_quantiles() (XGBoost reg:quantileerror,
│                                        low/mid/high in one fit), walk_forward_validate_quantile() (embargo=0, RMSE/pinball/coverage vs.
│                                        naive sector-median baseline — not IC, since target is same-month not forward-looking),
│                                        fit_sector_zscore_stats()/apply_zscore_stats() (fit/transform split so scoring uses training-time
│                                        stats, not a live-batch recompute). MULTIPLE_TARGETS = {pe, evebitda, pfcf, ps}; PASSING_MULTIPLES = [pe, pfcf, ps]
│                                        (evebitda excluded — missed the Phase 3 gate's RMSE bar by 0.3pp; ps added 2026-07-21, passed with best RMSE improvement of the 4).
│
├── ib_trader/                           IB execution + portfolio tracking package
│   ├── __init__.py                      Public re-exports for all ib_trader submodules
│   ├── client.py                        IBClient: connect, get_nav, get_positions, get_live_price
│   ├── orders.py                        make_order, place_order, cancel_all_open_orders, get_order_status
│   ├── portfolio.py                     build_target, diff_portfolio, summarise_diff, load_scores_csv, find_latest_scores
│   ├── rebalance.py                     run_rebalance(): end-to-end rebalance; hooks into tracker on non-dry-run
│   ├── interactive.py                   REPL loop: status, buy, sell, quote, cancel, preview, rebalance, help
│   ├── tracker.py                       Portfolio tracker DB (DuckDB): fill capture, FIFO tax lots, NAV snapshots, score snapshots, IC tracking
│   │                                    Functions: init_tracker_db, register_strategy, record_fill, sync_ib_fills,
│   │                                    record_nav, record_score_snapshot, update_forward_returns,
│   │                                    record_fills_from_blotter, load_backtest_benchmarks
│   ├── performance.py                   P&L, risk metrics, and IC computations from tracker data
│   │                                    Functions: get_open_positions, get_pnl_summary, get_monthly_returns,
│   │                                    get_performance_stats, get_trade_stats (Profit Factor + Van Tharp
│   │                                    R-Multiple from closed tax_lots; added for trade_systems/DASHBOARD.md,
│   │                                    matches the strategies/hammer_bottom_reverse backtest notebook's
│   │                                    definition), get_period_returns_table, get_slippage_summary,
│   │                                    get_ic_series, compare_vs_backtest, get_trade_history
│   └── report.py                        snapshot_report() (8-section printed report) + Jupyter query wrappers:
│                                        get_trades, get_positions, get_performance, get_tax_summary
│
├── features/
│   ├── dcf/
│   │   ├── VISION.md                    Original DCF feature vision
│   │   └── PLAN.md                      DCF implementation plan and status
│   ├── historic_fundamentals/
│   │   ├── VISION.md                    Original historic fundamentals feature vision
│   │   ├── PLAN.md                      Historic fundamentals implementation plan and status (original build, Phases 1-4)
│   │   ├── fundamentals_alpha_action_plan.md  Validation/improvement action plan for the ret_1y XGBoost model
│   │   └── ml_comps_valuation_plan.md   ML comps valuation: phased build record, Phase 3 gate result, bugs found/fixed, Phase 9 graduation-bar stub
│   └── ib_trader/
│       ├── VISION.md                    IB trader + portfolio tracker feature vision
│       └── PLAN.md                      IB trader implementation plan (Phases 1-10, all implemented)
│
├── planning/
│   └── PLAN.md                          Overall project plan
│
├── av_financials_db.py                  Alpha Vantage DB class: schema, RateLimiter, fetch, upsert, query
├── financial_statements_db.py           SEC EDGAR DB class: schema, insert helpers, log_extraction()
├── xbrl_concept_mapper.py               AI fallback mapper via OpenRouter (Claude Haiku)
├── xbrl_mapping_manager_multi_statement.py  XBRL mapping persistence, missed_concepts logging
├── bulk_import_10k.py                   Core async bulk import logic (concurrent tickers)
├── run_bulk_import.py                   CLI entry point for SEC EDGAR bulk imports
├── pyproject.toml                       Dependencies and pytest config
└── CLAUDE.md                            Coding standards

scripts/ also contains:
    earnings_backfill.py                 One-time backfill: fetch latest 4 quarters of earnings call transcripts for all ~2,644 AV tickers
                                         Resume-safe; skips already-cached (symbol, quarter) pairs. --ticker, --quarters N, --dry-run flags.
    earnings_update.py                   Weekly update: check latest 1-2 quarters per ticker for new transcripts. Cron: Sunday 19:30 ET
                                         (crontab -l, cron_wrap.sh earnings_update). --ticker flag for single-ticker runs.
    earnings_calendar_update.py          Weekly update: fetch AV EARNINGS_CALENDAR (3-month horizon), upsert into earnings_calendar
                                         (av_financials.duckdb) for tracked tickers, purge entries >30 days old. Cron: Monday 5:45 ET
                                         (crontab -l, cron_wrap.sh earnings_calendar_update).
    mda_backfill.py                      One-time backfill: fetch 20yr 10-K + 20qtr 10-Q MD&A for all tickers in company_overview
                                         Resume-safe; skips already-cached (ticker, form, fiscal_period_end). --ticker, --csv, --limit, --force, --dry-run flags.
    mda_update.py                        Weekly update: check latest 10-K + latest 10-Q per ticker for new MD&A; designed for cron scheduling
                                         --ticker, --dry-run flags.
    rebuild_sector_stats.py              Full rebuild of sector_stats table in historic_fundamentals.duckdb (all months, ~43K rows)
                                         Run after schema changes to sector_stats or after adding new tickers in bulk.
    reconstruct_dcf_panel.py             Rebuilds DCFs as-of past quarter-ends into data/dcf_reconstruction*/ parquet (60 dates
                                         2010-2024, ~85 min on 6 workers, resumable). Point-in-time: statements by reporting lag,
                                         price/rf/beta by date, analyst estimates dropped. WARNING: a panel bakes in whatever
                                         dcf/model.py constants were live at build time -- rebuild the baseline before any A/B.
    test_dcf_upside_factor.py            Runs dcf_upside through the standard factor gauntlet (rank IC, incremental IC vs the
                                         existing value factors, quintiles, fold win rate). See docs/dcf_upside_factor_test.md.
    test_dcf_guard_walkforward.py        Out-of-sample validation of the MAX_INTRINSIC_TO_PRICE threshold (5 train yrs / 1 test yr).
    test_dcf_horizon.py                  The same factor at 1y/2y/3y/5y, with Newey-West lags = H-1 for overlapping returns.
    test_dcf_convergence.py              Per-name test: does price converge toward intrinsic value, vs a return-shuffle null,
                                         split by direction and bucketed by gap size.
    manage_tickers.py                    Add/delete tickers across four DBs: prices + AV financials + historic fundamentals + MD&A (recommended)
                                         add's --skip-mda skips the MD&A step (catch up later via mda_backfill.py --csv)
    av_import.py                         Import income/balance/cashflow from Alpha Vantage (75 calls/min limit enforced)
    av_import_overview.py                Backfill company overview (name, sector, industry, beta + 41 fields) for all tickers
    av_update.py                         Incremental update: refresh statements + overview for existing tickers
    hf_import.py                         Bulk backfill: compute PE + yield history for all AV tickers + fetch estimates
    hf_update.py                         Monthly update: refresh PE + yield + estimates + sector stats (--skip-sector, --full-sector-rebuild)
    hf_query.py                          CLI query: stats, timeseries, estimates, sector, sector-history views; --group, --name options; CSV export
    av_import_shares.py                  Standalone backfill: shares_outstanding for existing tickers
    av_import_dividends.py               Standalone backfill: dividends for existing tickers
    run_baselines.py                     Run rank-based baseline factor models; writes docs/baseline_results.md
    run_walkforward.py                   Run walk-forward XGBoost validation with embargo; writes docs/walkforward_results.md
    run_backtest.py                      Run true monthly portfolio backtest vs SPY; writes docs/backtest_results.md
                                         Key flags: --guardrails, --vol-weight (vw_gr_* portfolios), --regime-filter (rf_gr_* portfolios), --model
    run_risk.py                          Run risk diagnostics, guardrail checks, drawdown, beta decomposition; writes docs/risk_report.md
    validate_ml_comps_valuation.py       ML comps valuation go/no-go gate: walk-forward RMSE/coverage vs. naive sector-median baseline
                                         for P/E, EV/EBITDA, P/FCF, P/S; writes docs/ml_comps_validation_report.md + ml_comps_validation_folds.csv;
                                         exits non-zero if fewer than 2 of the 4 candidate multiples pass (each judged independently;
                                         passing moves a multiple from MULTIPLE_TARGETS into PASSING_MULTIPLES).
    train_ml_comps_valuation.py          Train final quantile models on a rolling window (--rolling-years, default 5 — matches the gate);
                                         saves versioned + "_latest" joblib bundles {model, zscore_stats, feature_cols} to data/ml_comps_valuation/;
                                         records ml_model_metadata.
    score_ml_comps_valuation.py          Batch-score current universe using the persisted training-time z-score stats (not a live-batch
                                         recompute); writes ml_comps_valuation. --tickers for a subset.
    report_ml_comps_history.py           Print ml_model_metadata retrain history (RMSE vs. baseline, coverage, active version) per target.
    score_live.py                        Live scoring: load latest PIT-safe features, apply universe filters, rank by score, write docs/live_scores_YYYYMMDD.csv
                                         Computes inverse-vol position weights (10% cap) and regime-adjusted alloc_pct from SPY 12m signal.
                                         Also records a score snapshot to IB_TRACKER_DB when set (used for IC tracking).
                                         Options: --top N, --verbose, --output PATH, --model PATH, --no-model, --guardrails / --no-guardrails
    rebalance.py                         CLI rebalancer: --scores, --dry-run / --no-dry-run, --order-type, --strategy, --status, --cancel-all
                                         Non-dry-run records estimated fills and NAV to IB_TRACKER_DB when set.
    sync_fills.py                        Pull IB execution history → tracker DB (actual exec IDs + fill prices for slippage)
                                         Also records NAV and optionally updates 30-day forward returns for IC calculation.
                                         Options: --strategy (required), --since DATE, --update-forward-returns, --dry-run
    ib_repl.py                           Interactive REPL: status, buy, sell, quote, cancel, preview, rebalance
    train_model.py                       Train XGBoost on full dataset and save data/model.joblib. Run after adding new features.
    validate_model.py                    Walk-forward validation: per-fold and yearly OOS IC, ICIR, NW-ICIR, hit rate, Q-spread; writes docs/validation_report.md
```

## Data flow

### Web app import

1. User submits ticker + period_type (FY/Q) + periods (default: 10 FY) in browser
2. `POST /import` → `api/importer.py:import_ticker()`
3. Fetches 10-K or 10-Q filings from SEC EDGAR via `edgartools`
   - Uses `company.latest(form)` for single-filing imports (zero extra network cost)
   - Falls back to `company.get_filings(form=form)[:periods]` for multi-period
4. For each filing, calls all 3 extractors (income, balance, cash flow)
5. Each extractor runs 2 passes:
   - Pass 1: static XBRL concept matching via `xbrl_mappings/`
   - Pass 2 (optional): AI batch resolution for unfound fields
6. XBRL values extracted with `presentation=False` (raw values, consistent signs across companies)
7. Results upserted into DuckDB via `INSERT OR REPLACE INTO`
8. After FY import succeeds, the browser fires a background `POST /import` for 20 quarters (non-blocking)

### DCF valuation

1. `GET /dcf/{ticker}` → `api/dcf_router.py`
2. `dcf/data.py` loads last 10 annual + 20 quarterly rows from all 3 statement tables; fetches current price; loads DGS10 from fred.duckdb
3. `dcf/forecaster.py` forecasts revenue (EWM annual growth blended with quarterly momentum signal for Y1-Y2; OLS slope anchored at Y2 for Y3-Y5) and 5 P&L ratios (ARIMA(0,1,0) Y1-Y2, OLS Y3-Y5); computes DSO/DPO/DIO from historical balance sheets
4. `dcf/wacc.py` downloads beta via yfinance; computes ke (CAPM), kd (annual IE / avg debt), WACC with market-value weights. Diluted shares: quarterly → annual → derived from net_income/EPS. Emits `warnings` for zero market cap, D_w > 80%, WACC < 5%, or terminal growth clamped.
5. `dcf/model.py` builds FCFF series: EBIT → NOPAT → +D&A → -CapEx → -ΔNWC (days-based); discounts; Gordon Growth terminal value; equity bridge
6. Returns `DcfResult` with historical rows, proforma rows, FCFF series, WACC detail, sensitivity grid, terminal value decomposition. `HistoricalRow` fields: revenue, gross profit, EBIT, EBITDA, income tax expense, pretax income, net income, D&A, CapEx, total assets, total debt, cash, diluted EPS, granular P&L components (COGS, SG&A, R&D, interest expense), and balance sheet working-capital items (accounts_receivable, accounts_payable, inventory) for DSO/DPO/DIO charting
7. `POST /dcf/{ticker}/run` accepts per-year and global overrides, re-runs from step 5

### Bulk import (CLI)

1. `run_bulk_import.py` parses CLI args, prompts for confirmation
2. Calls `bulk_import_10k.bulk_import_10k()` with form=10-K or 10-Q
3. Processes up to N tickers concurrently (default 3) via `asyncio.Semaphore`
4. `Company()` and `get_filings()` run in `asyncio.to_thread()` — true parallelism during SEC I/O
5. AI fallback is on by default; disable with `--no-ai`
6. edgartools' built-in rate limiter handles SEC's 9 req/s limit; `--delay` adds extra sleep between filings
7. Each filing writes one row to `extraction_log` in `financial_statements.duckdb`
8. Unresolved concepts logged to `missed_concepts` in `xbrl_mappings_multi.duckdb`
9. Writes summary reports to `bulk_import_results/`

## Extractor architecture

All three extractors share a single core in `extractors/statement_extractor.py`:

```
extract_statement()                    ← shared core (async)
├── open XBRLMappingManager            (single connection for entire call)
├── get_enriched_mapping()             (inject AI discoveries seen >= 2x, free)
├── await asyncio.to_thread(xbrl())    (non-blocking SEC network call)
├── detect date columns                (handles "(FY)"/"(Q1)"/"(YTD)" suffixes)
├── Pass 1: _extract_value() per field
│   ├── aggregation_fields   → sum multiple matching concepts (e.g. SG&A components)
│   ├── max_fields           → take max across matches (e.g. Revenues vs RFCWCEA)
│   └── default              → first match wins
├── Pass 2: AI batch fallback (on by default, disable with --no-ai)
│   ├── Phase A: prior discoveries from ai_discovery_queue (free DB lookup)
│   └── Phase B: Claude Haiku via OpenRouter, chunks of 20 concepts
├── log AI discoveries → ai_discovery_queue
└── log unresolved fields/concepts → missed_concepts

extract_income_statement()   ← thin wrapper, defines _AGG_FIELDS, _MAX_FIELDS, _ALT_NAMES
extract_balance_sheet()      ← thin wrapper
extract_cash_flow()          ← thin wrapper
```

The `max_fields` mechanism prevents revenue understatement when a company reports both a
specific concept (e.g. `RevenueFromContractWithCustomerExcludingAssessedTax`) and a broader
aggregate (`Revenues`). The larger value is always the correct total.

D&A is sourced primarily from the cash flow statement (operating section non-cash add-back),
with income statement as fallback. Most companies report D&A in CF, not IS.

## DCF model detail

**FCFF formula**

```
EBIT   = Revenue × (1 - cogs_pct - sga_pct - rd_pct)
NOPAT  = EBIT × (1 - tax_rate)
FCFF   = NOPAT + D&A - CapEx - ΔNWC
ΔNWC   = Receivables(t) + Inventory(t) - Payables(t)
         - Receivables(t-1) - Inventory(t-1) + Payables(t-1)
         where Receivables = Revenue × DSO/365
               Inventory   = COGS × DIO/365
               Payables    = COGS × DPO/365
TV     = FCFF₅ × (1 + g) / (WACC - g)
EV     = Σ PV(FCFF₁..₅) + PV(TV)
Equity = EV - net_debt
Price  = Equity / diluted_shares
```

**Forecasting (annual data only)**

| Metric | Method |
|--------|--------|
| revenue Y1-Y2 | EWM annual growth + quarterly momentum signal (50%/25% blend) |
| revenue Y3-Y5 | OLS slope anchored at Y2 (avoids stall when momentum > trend) |
| cogs_pct, sga_pct, rd_pct, interest_pct, other_pct | ARIMA(0,1,0) Y1-Y2, OLS Y3-Y5 |
| D&A %, CapEx % | historical 5-yr average |
| DSO, DPO, DIO | historical 5-yr average from balance sheet |

R&D: if a company never reports R&D, `rd_pct` stays `None` throughout (shown as blank in UI).

**WACC computation** (`dcf/wacc.py`)

| Input | Source | Notes |
|-------|--------|-------|
| Beta | yfinance `Ticker.info["beta"]` | Falls back to 1.0; Hamada unlever/re-lever at current D/E |
| Risk-free rate | FRED `DGS10` from fred.duckdb | Falls back to 4.5% |
| Market risk premium | Constant 5.5% | Damodaran estimate; user-overridable |
| Cost of equity | `ke = rf + β × MRP` | CAPM |
| Cost of debt | `annual_IE / avg_quarterly_debt` | Uses annual income statement for IE (full-year amount); clamped [2%, 15%] |
| Tax rate | 5-yr average effective rate from annual income | Clamped [15%, 40%]; falls back to 21% |
| Diluted shares | Quarterly → annual → `net_income / diluted_eps` | Three-level fallback; market cap = price × shares |
| Capital structure | Market-value weights from latest quarterly balance sheet + current price | D_w = debt / (debt + market_cap) |

`DcfResult.warnings` is a `list[str]` populated when:
- Market cap is zero after all share fallbacks
- Debt weight exceeds 80%
- WACC falls below 5%
- Cost of debt is below the risk-free rate (advisory — plausible for pre-rate-hike-cycle fixed
  debt, but the same rate discounts the terminal value; added 2026-08-27, see
  `features/ai_dcf/PLAN_GUARDRAILS.md`)
- Terminal growth is clamped because WACC ≤ default terminal growth rate

Warnings are displayed as amber banners in `DcfViewer.tsx`.

**Editable assumptions (UI)**

Global: risk-free rate, market risk premium, beta, cost of debt, tax rate, terminal growth rate, DSO, DPO, DIO

Per-year: revenue_growth, cogs_pct, sga_pct, rd_pct, interest_pct, other_pct, capex_pct_revenue

Reset button restores all inputs to model-computed defaults without re-fetching.

**AV data adapter** (`dcf/av_data.py`)

Alpha Vantage column names differ from what the DCF engine expects. `av_data.py` renames them on load so nothing downstream needs AV awareness.

| Statement | AV column | DCF engine name |
|-----------|-----------|-----------------|
| income | `fiscal_date_ending` | `period_end_date` |
| income | `total_revenue` | `revenue` |
| income | `selling_general_and_administrative` | `selling_general_admin` |
| income | `research_and_development` | `research_development` |
| income | `income_before_tax` | `pretax_income` |
| income | `depreciation_and_amortization` | `depreciation_amortization` |
| balance | `fiscal_date_ending` | `period_end_date` |
| balance | `cash_and_cash_equivalents` | `cash_and_equivalents` |
| balance | `current_net_receivables` | `accounts_receivable` |
| balance | `current_accounts_payable` | `accounts_payable` |
| balance | `current_long_term_debt` | `current_portion_long_term_debt` |
| cashflow | `fiscal_date_ending` | `period_end_date` |
| cashflow | `depreciation_depletion_and_amortization` | `depreciation_amortization` |

AV `period_type` is lowercase (`'annual'`/`'quarterly'`); the adapter normalises to title-case so no other module needs awareness.

**Diluted shares approximation:** AV income statements carry no `diluted_shares`. The adapter derives shares from `common_stock_shares_outstanding` on the balance sheet (basic, not diluted). This overstates intrinsic value per share by the dilution gap — typically 1–5% (AAPL ~0.7%, NVDA ~1.2%, high-SBC companies up to ~4%).

**Terminal growth default (AV DCF only):** median of all historical annual revenue YoY growth rates, clamped to [0%, 15%]. Capped at 15% to prevent outlier growth years from producing an unrealistic perpetuity rate.

**Known constraints and non-obvious decisions:**

| Constraint | Decision |
|------------|----------|
| AV has no diluted shares in income statement | Use `common_stock_shares_outstanding` from balance sheet; ~1–5% intrinsic value overstatement |
| AV cashflow may lack D&A for some tickers | Fall back to income statement `depreciation_and_amortization` |
| AV reports fewer than 8 quarterly periods for some tickers | Raise `ValueError` → API returns HTTP 404 with actionable message |
| `UserOverrides` is a dataclass | Use `dataclasses.replace()` to apply terminal growth default without mutating caller's object |

## Fundamentals Alpha model

`notebooks/fundamentals_alpha.ipynb` — quantitative return-prediction model.

**Data:** `monthly_pe` table from `historic_fundamentals.duckdb`, 296K rows, 1,411 tickers (after $300M market cap filter), 1999–2026.

**Cell execution order:**

```
Config → Load monthly_pe (with shares) → Sector join + $300M cap filter
→ Forward returns (vectorized self-join, ±45d tolerance)
→ Trailing CAGRs (rev/earn/fcf × 1y/3y/5y)
→ 12-1 month price momentum (add_momentum, from df.price)
→ Feature engineering: premiums, sector-relative, is_profitable
   WF_FEATURE_COLS frozen here — not touched by SHAP pruning
→ Return masking
→ Cross-sectional z-score → ML_DF (EDA uses raw df)
→ EDA: correlation heatmap, IC/ICIR, quintile analysis
→ XGBoost training on ML_DF + WF_FEATURE_COLS
→ SHAP plots → SHAP_FEATURE_COLS + shap_models (for live scoring only)
→ Walk-forward: WF_FEATURE_COLS + ML_DF + Newey-West ICIR + TC tracking
→ Cumulative return charts (gross + net-TC)
→ Live scoring: SHAP_FEATURE_COLS + x-sec z-score of live data
→ Summary table: icir_nw + net_tc
```

**Features (~48 total in WF_FEATURE_COLS):**

| Group | Features |
|---|---|
| Valuation | pe, pfcf, ev_ebitda, ps, pbv, ptbv, fcf_yield, dividend_yield |
| Yields | earnings_yield (3y/5y avg), fcf_yield (3y/5y), ebitda_ev_yield (3y/5y) |
| Normalized | normalized_pe/pfcf/evebitda/ps_5y (CAPE-style) |
| Mean-reversion | pe/pfcf/ev/ps/pbv/ptbv_premium (current ÷ 5yr rolling median) |
| Quality | roa, roe, roic + 5yr premiums |
| Growth | rev/earn/fcf CAGR × 1y/3y/5y; is_profitable flag |
| Margins | gross/operating/fcf margin — level, 5yr median, slope, change |
| Leverage | debt_to_ebitda, interest_coverage, roa_stability_5y |
| Momentum | momentum_12_1 (12-1 month price return) |
| Sector-rel | pe/pfcf/ev/ps/roic/roa ÷ sector median for same month |

**Methodology controls (config cell):**

| Variable | Value | Purpose |
|---|---|---|
| WINSOR_CLIP | 1.5 | Clip returns at ±150% |
| MARKET_CAP_MIN | 300e6 | Exclude micro-caps |
| TC_BPS_ONEWAY | 10 | Transaction cost estimate |
| XSEC_ZSCORE | True | Z-score within each month before ML |

**Walk-forward outputs per horizon:** gross top-20% return, TC-adjusted return, universe EW, SPY, excess vs universe/SPY, win rate, mean IC, raw ICIR, Newey-West ICIR (lag = horizon months − 1), avg monthly turnover.

**SHAP leakage guard:** `WF_FEATURE_COLS` is frozen after feature engineering. Cell 10b (SHAP pruning) creates separate `SHAP_FEATURE_COLS` and `shap_models` used only for live scoring — walk-forward always uses the full `WF_FEATURE_COLS` set with no look-ahead from SHAP selection.

## Database tables

### `data/av_financials.duckdb`

| Table | Key columns |
|-------|-------------|
| `income_statements` | ticker, fiscal_date_ending, period_type ('annual'/'quarterly'), total_revenue, gross_profit, operating_income, ebit, ebitda, net_income, ... |
| `balance_sheets` | ticker, fiscal_date_ending, period_type, total_assets, total_liabilities, total_shareholder_equity, long_term_debt, common_stock_shares_outstanding, ... |
| `cash_flow_statements` | ticker, fiscal_date_ending, period_type, operating_cashflow, capital_expenditures, stock_based_compensation, dividend_payout, ... |
| `shares_outstanding` | ticker, date, shares_outstanding_diluted, shares_outstanding_basic, fetched_at |
| `dividends` | ticker, ex_dividend_date, declaration_date, record_date, payment_date, amount, fetched_at |
| `company_overview` | ticker, fetch_date, name, sector, industry, beta, market_cap, pe_ratio, ... (all 45 AV OVERVIEW fields) |
| `earnings_calendar` | symbol, name, report_date, fiscal_date_ending, estimate, currency, time_of_day, fetched_at (PK: symbol, report_date) |
| `companies` | ticker, last_updated_at, total_annual, total_quarterly |
| `import_log` | ticker, run_at, success, statements, periods_inserted, error_msg |

Primary key on all three statement tables: `(ticker, fiscal_date_ending, period_type)`. All numeric fields stored as DOUBLE; AV `"None"` strings converted to NULL on ingest.

`company_overview` PK is `(ticker, fetch_date DATE)` for monthly historical snapshots. The latest snapshot per ticker is joined automatically into `get_pe_stats()` to supply `name`, `sector`, `industry`, and `beta`.

`earnings_calendar` is populated by `earnings_calendar_update.py` (weekly cron) from AV EARNINGS_CALENDAR, filtered to tickers already in `companies`; entries older than 30 days are purged each run. Served by `earnings_calendar_router.py`.

### `data/financial_statements.duckdb`

| Table | Key columns |
|-------|-------------|
| `income_statements` | ticker, period_end_date, fiscal_year, period_type, revenue, gross_profit, net_income, ... |
| `balance_sheets` | ticker, period_end_date, fiscal_year, period_type, total_assets, total_debt, ... |
| `cash_flow_statements` | ticker, period_end_date, fiscal_year, period_type, operating_cash_flow, capital_expenditures, depreciation_amortization, ... |
| `extraction_log` | ticker, filing_type, fiscal_year, statements_extracted, overall_coverage_pct, success, execution_time_seconds |
| `companies` | ticker, first_filing_date, last_filing_date, total_filings |

All three statement tables use `INSERT OR REPLACE INTO` keyed on `(ticker, filing_date, period_end_date)` for atomic upserts.

### `data/historic_fundamentals.duckdb`

| Table | Key columns |
|-------|-------------|
| `monthly_pe` | ticker, month_end_date (last calendar day), price (adj_close), ttm_eps, pe_ratio (NULL when ttm_eps ≤ 0), pe_rolling_5yr_median (trailing 60-month window), ttm_source ('quarterly'/'annual'), shares, ttm_dividend, dividend_yield, ttm_revenue, ttm_fcf, pfcf_ratio, pfcf_rolling_5yr_median, fcf_yield, ttm_ebitda, ev_ebitda, ev_ebitda_rolling_5yr_median, ps_ratio, ps_rolling_5yr_median, roa, roa_rolling_5yr_median, roe (NULL when equity ≤ 0), roe_rolling_5yr_median, roic (NULL when IC ≤ 0), roic_rolling_5yr_median, pbv (NULL when equity ≤ 0), pbv_rolling_5yr_median, ptbv (NULL when TBV ≤ 0), ptbv_rolling_5yr_median, earnings_quality ((OCF−NI)/avg_assets), asset_growth (YoY total_assets growth, quarterly), momentum_12_1 (12-1 month price return), updated_at |
| `pe_stats` | ticker (PK), market_cap_b, current/lt_median/p25/p75/p10/p90/rolling_5yr_median for PE + forward_pe/12m_eps; current/lt_median/p25/p75/rolling_5yr_median for P/FCF, EV/EBITDA, P/S, ROA, ROE, ROIC, P/BV, P/TBV; forward_pfcf, forward_evebitda, forward_ps; fcf/ebitda margins; rev/earn/fcf growth CAGRs and NTM estimates; ttm_dividend, dividend_yield, months_available, updated_at |
| `earnings_estimates` | ticker, fiscal_date, horizon ('fiscal quarter'/'fiscal year'), fetched_at (PK together), eps_avg/high/low/count, eps_avg_7d/30d/60d/90d, eps_rev_up/down_7d/30d, rev_avg/high/low/count |
| `sector_stats` | group_type ('sector'/'industry'), group_name, month_end_date (PK together), ticker_count, pe/pfcf/evebitda/ps median/p25/p75, pbv_median, earnings_yield/fcf_yield/ebitda_ev_yield/dividend_yield medians, roa/roe/roic median/p25/p75, rev_growth_1yr_median, earn_growth_1yr_median, gross_margin_median, operating_margin_median, fcf_margin_median, debt_to_ebitda_median, interest_coverage_median |

Primary data sources:
- `av_financials.duckdb / income_statements` — net_income, total_revenue, ebitda, ebit, income_tax_expense, income_before_tax
- `av_financials.duckdb / balance_sheets` — total_assets, total_shareholder_equity, intangible_assets_excl_goodwill, goodwill, long_term_debt_noncurrent, short_term_debt, current_long_term_debt, cash_and_short_term_investments, common_stock_shares_outstanding
- `av_financials.duckdb / cash_flow_statements` — operating_cashflow, capital_expenditures
- `av_financials.duckdb / shares_outstanding` — shares_outstanding_diluted (primary); balance_sheets fallback
- `av_financials.duckdb / dividends` — ex-dividend history for TTM dividend computation
- `av_financials.duckdb / company_overview` — sector, industry, name, beta (latest snapshot per ticker; joined into get_pe_stats() and used for sector_stats aggregation)
- `prices.duckdb / stock_prices` — adj_close for month-end price and current market cap
- Alpha Vantage EARNINGS_ESTIMATES endpoint — analyst EPS + revenue estimates

### `data/ib_tracker.duckdb`

Created automatically when `IB_TRACKER_DB` env var is set. Schema is initialized by `init_tracker_db()` in `ib_trader/tracker.py`.

| Table | Key columns |
|-------|-------------|
| `strategies` | name (PK), description, inception_date, benchmark |
| `fills` | id (seq PK), strategy, ticker, action (BUY/SELL), qty, fill_price, fill_time, exec_id (UNIQUE, NULL for blotter estimates), commission, reference_price |
| `tax_lots` | id (seq PK), strategy, ticker, open_date, open_price, qty, qty_remaining, close_date, close_price, realized_pnl, is_long_term, tax_rate |
| `daily_nav` | (strategy, date) PK, nav, cash, equity_value |
| `score_snapshots` | (strategy, snapshot_date, ticker) PK, rank, score, alloc_pct, price_at_score, forward_return (NULL until 30d later) |
| `backtest_benchmarks` | (strategy, portfolio) PK, cagr, ann_vol, sharpe, sortino, max_dd, beta, alpha, win_rate |

`fills.reference_price` stores the CSV closing price at time of scoring. Slippage = `(fill_price - reference_price) / reference_price * 10000` bps (sign-flipped for SELL).

`tax_lots.qty_remaining` decreases as SELL fills close lots FIFO. Open positions: `WHERE qty_remaining > 0`. Closed lots: `WHERE close_date IS NOT NULL`.

### `data/earnings_transcripts.duckdb`

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | VARCHAR | Ticker symbol (PK with `quarter`) |
| `quarter` | VARCHAR | Fiscal quarter string, e.g. `2026Q2` (PK with `symbol`) |
| `transcript_text` | TEXT | Full formatted transcript (speaker/title/content blocks) |
| `fetched_date` | DATE | Date the transcript was downloaded into the DB |
| `api_response_json` | TEXT | Raw Alpha Vantage JSON response (nullable) |
| `source` | VARCHAR | `'av'` (Alpha Vantage), `'url'` (manual URL import), or `'audio'` (Whisper transcription) |

Quarter strings follow the company's own fiscal quarter, not the calendar quarter — `fiscal_date_to_quarters()` uses each ticker's fiscal year end month (from av_financials `income_statements`) so labels match what AV itself returns (verified against NVDA, whose FY ends in January: AV's "2025Q4" is NVDA's own Q4, not calendar Q4). Populated by `earnings_backfill.py`, `earnings_update.py` (both weekly-cron'd — see scripts/ list above), and on-demand by `refresh_latest_transcript()` from the Finview Earnings tab and both AI Researchers.

Also holds `earnings_surprises` (EPS beat/miss history from AV EARNINGS, 30-day cache): symbol, fiscal_date_ending, reported_date, reported_eps, estimated_eps, surprise_pct, fetched_at (PK: symbol, fiscal_date_ending).

### `data/mda_filings.duckdb`

| Column | Type | Notes |
|--------|------|-------|
| `ticker` | VARCHAR | Ticker symbol (PK with `form`, `fiscal_period_end`) |
| `cik` | VARCHAR | SEC CIK number |
| `form` | VARCHAR | `'10-K'` or `'10-Q'` (PK with `ticker`, `fiscal_period_end`) |
| `fiscal_period_end` | DATE | Filing's `period_of_report` (PK with `ticker`, `form`) |
| `filing_date` | DATE | SEC filing date |
| `accession_no` | VARCHAR | SEC accession number |
| `section_key` | VARCHAR | edgartools extraction key used: `'mda'` (10-K) or `'part_i_item_2'` (10-Q) |
| `mda_text` | VARCHAR | Extracted MD&A section text |
| `char_count` | INTEGER | `len(mda_text)` |
| `status` | VARCHAR | `'ok'` (>=500 chars), `'empty'` (<500 chars, edgartools couldn't find/extract the section — accepted gap, no retry), or `'error'` (fetch/parse exception) |
| `downloaded_at` | TIMESTAMP | When the row was fetched |

Populated by `mda_backfill.py` (one-time, 20yr 10-K + 20qtr 10-Q per ticker), `mda_update.py`
(weekly cron, Sunday 20:30 ET, latest 1 10-K + 1 10-Q per ticker), and `manage_tickers.py add`
(new tickers, unless `--skip-mda`). Full-universe backfill completed 2026-07-29: 2,477 tickers,
79,469 rows, 0 errors, 83.5% `ok`. See `PLAN_MDA.md` for design/rationale, including the
DuckDB single-writer-lock interaction with concurrent `add`/backfill runs.

### `data/xbrl_mappings_multi.duckdb`

| Table | Purpose |
|-------|---------|
| `ai_discovery_queue` | Per-filing log of AI-discovered concept→field mappings |
| `missed_concepts` | Every unresolved field/concept with reason code (`ai_disabled`, `no_match`, `api_failure`) |
| `ai_discovered_mappings` | Aggregated discovery stats (times_used, confidence) |
| `core_concept_mappings` | Snapshot of static `.py` mapping files |
| `company_specific_mappings` | Ticker-level overrides |
| `statement_coverage_stats` | Per-filing field coverage percentages |
