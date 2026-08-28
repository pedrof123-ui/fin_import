# PLAN: Historic capex and R&D intensity ratios

Status: Phase 0 (design review) complete 2026-08-27. Phase 1 COMPLETE 2026-08-27 (code,
tests — full suite 653 passed/0 failed — and full-history backfill: 2,658 tickers,
0 failed). Phase 2 COMPLETE 2026-08-27 (sector.py/db.py/pe.py code, sector_stats rebuild
verified sane by sector, pe_stats backfilled for all tickers, full test suite green
throughout). Phase 4 COMPLETE 2026-08-28 (sector-aware DCF fallback wired in, 10 new unit
tests, full suite 663 passed/0 failed, live smoke-tested). Phase 3 COMPLETE 2026-08-28
(gauntlet run, findings logged in docs/capex_rd_factors_test.md: 3/4 factors rejected,
1/4 — rd_intensity_change_3y — promising but not promoted, needs the fuller gauntlet first).
ALL PHASES COMPLETE.

## Why

Raw capex (`cash_flow_statements.capital_expenditures`, 270,403/270,403 rows populated,
1983-2026) and R&D (`income_statements.research_and_development`, 208,996/275,134 rows,
76% — the rest is legitimately non-reporting financials/REITs/utilities) are fully present
in `data/av_financials.duckdb`, but neither is ever turned into a ratio and persisted.
`monthly_pe` and `sector_stats` already carry `ttm_gross_margin`, `ttm_operating_margin`,
`ttm_fcf_margin` (with 5yr median/slope) per ticker and per sector/industry
([[project_fundamentals_alpha]] pattern) — capex and R&D intensity are the same shape of
ratio and are simply missing.

The concrete cost of the gap: `dcf/forecaster.py` already computes `capex_pct_revenue` and
`rd_pct` per ticker at DCF-run time (`forecaster.py:369-379`), then throws them away — no
history, no sector benchmark. When a ticker has no usable capex history at all, the fallback
is a hardcoded `0.05` (`forecaster.py:373`) and D&A falls back to a hardcoded `0.03`
(`forecaster.py:379`) — the same flat 5%/3% for a REIT and a software company. This plan
replaces that blind fallback with an actual sector/industry median, and makes capex/R&D
intensity available as ordinary cross-sectional factors for the gauntlet
(same infra as [[project_greenblatt_factors_result]], [[project_mda_factors_result]]).

Given that record — Greenblatt, CANSLIM, Fibonacci, and the MD&A composite were all tested
and rejected as standalone factors — Phase 3 (factor gauntlet) is exploratory, not expected
to ship a new live signal. The DCF fallback improvement (Phase 4) is the part with a known
payoff and does not depend on Phase 3's outcome.

## Update process — already exists, no new cron needed

`monthly_pe` and `sector_stats` are already refreshed monthly by cron
(`5 0 1 * * ... run_pipeline.py --av-update --enable-ml-comps`, 1st of each month), which
runs `scripts/hf_update.py` as a subprocess. That script calls
`historic_fundamentals.pe.process_ticker()` per ticker and then
`historic_fundamentals.sector.compute_sector_stats()`. Both new-ratio blocks in Phase 1/2
live inside those same two functions, so once added they ride the existing monthly cron
automatically — no new script, no new cron entry.

Correction to an earlier (wrong) claim made while scoping this plan: `process_ticker()` /
`build_monthly_pe()` are NOT incremental per-ticker — `_load_monthly_prices()` loads a
ticker's full price history and `build_monthly_pe()` rebuilds the entire monthly series from
scratch every call; `upsert_monthly_pe()` then does `INSERT OR REPLACE` over all of it. So an
ordinary `hf_update.py` run already recomputes `monthly_pe`'s full 1983-2026 history with any
newly added column — no special flag, and 1.4 below is just "run hf_update.py once." Only
`sector_stats` has genuine incremental behavior (`compute_sector_stats()`'s `month_filter`
skips months already present unless `--full-sector-rebuild` is passed) — that flag is still
needed for 2.3.

## Phase 1 — Per-ticker ratios in `monthly_pe`

- [x] 1.1 In `historic_fundamentals/pe.py`, added alongside the `ttm_gross_margin` /
      `ttm_operating_margin` / `ttm_fcf_margin` block:
      - `ttm_capex_intensity` = TTM `capital_expenditures` / TTM revenue, via
        `_get_ttm_sum(month_end, "capital_expenditures", cfq_pit, cfa_pit)`. No `.abs()` —
        AV already reports capex as positive (matches the existing FCF convention), so
        added none rather than introduce an inconsistent sign convention.
      - `ttm_rd_intensity` = TTM `research_and_development` / TTM revenue, from `q_pit`/`a_pit`
        (added `i.research_and_development` to `_load_av_data`'s SELECT — it wasn't being
        loaded at all before this). NULL (not 0) when R&D is unreported.
      - `ttm_capex_to_da` = TTM capex / TTM `depreciation_amortization` (added
        `depreciation_depletion_and_amortization AS depreciation_amortization` to
        `_load_cashflow_data`'s SELECT, matching the naming `dcf/av_data.py` already uses for
        the same figure). This is the growth-vs-maintenance capex signal the DCF terminal
        fade (`_fade_capex_to_da`, `forecaster.py:463`) currently has no real data for.
      - Found and fixed a real bug while wiring this up: `_get_ttm_sum` raised `KeyError`
        instead of returning `None` when `col` wasn't a column in the frame at all (as
        opposed to present-but-NaN) — violated its own documented contract ("returns None
        when data is unavailable") and broke on any hand-built test frame missing a column.
        Fixed generically (`col in df.columns` guard) since the function is public and
        reused directly by `scripts/backfill_greenblatt_factors.py` and
        `scripts/backfill_canslim_factors.py`.
- [x] 1.2 Added the rolling 5yr median + slope companions, same pattern as
      `gross_margin_5y_median` / `gross_margin_slope_5y`: `capex_intensity_5y_median`,
      `capex_intensity_slope_5y`, `rd_intensity_5y_median`, `capex_to_da_5y_median`.
- [x] 1.3 Added the 7 new columns (3 raw + 4 rolling) to `monthly_pe`'s ALTER-migration
      schema in `historic_fundamentals/db.py` and to `upsert_monthly_pe`'s column list /
      INSERT list / SELECT list. Also documented the new columns' direction as
      "not unambiguously directional" in the feature-direction reference block (unlike the
      margins, high capex/R&D intensity isn't a safe prior either way).
      Tests: added `test_capex_intensity`, `test_rd_intensity`,
      `test_rd_intensity_null_when_unreported`, `test_capex_to_da`,
      `test_capex_intensity_zero_revenue` to `tests/test_features.py`. Full suite:
      653 passed, 3 skipped, 0 failed (`uv run python -m pytest tests/`).
      Smoke-tested against real data (AAPL, O, META) via `process_ticker()` — see
      [[project_capex_rd_ratios]] for the sanity-check values and one AV data-quality note
      (ticker O has a few years of `research_and_development` reported as literal cents,
      a pre-existing AV extraction artifact — produces a numerically negligible non-null
      `rd_intensity_5y_median` instead of NULL; not worth special-casing).
- [x] 1.4 Backfill full history: confirmed `process_ticker()`/`build_monthly_pe()` are NOT
      incremental — they rebuild each ticker's entire monthly series from scratch every call
      (see the corrected "Update process" note above) — so "backfill" is just running
      `hf_update.py` once, no special flag exists or is needed at this layer.
      Ran `uv run scripts/hf_update.py --skip-estimates --skip-sector` (skips AV
      estimates calls and Phase-2-not-built-yet sector stats). Result: 2,658 ok, 0 failed,
      ~30 min. `monthly_pe` row count unchanged (651,703 vs. 651,699 pre-backfill baseline —
      the +4 is normal monthly churn, not a regression), 2,645 distinct tickers, unchanged.
      New-column coverage: `ttm_capex_intensity` 622,130/651,703 (95.5%), `ttm_rd_intensity`
      537,580 (82.5%), `ttm_capex_to_da` 609,979 (93.6%) — consistent with the ~76-83%
      R&D-reporting rate expected from `income_statements` and full capex coverage.
      AAPL's backfilled row matches the earlier live smoke-test value exactly.

## Phase 2 — Sector/industry medians in `sector_stats`

- [x] 2.1 Added `ttm_capex_intensity`, `ttm_rd_intensity`, `ttm_capex_to_da` to the `base`
      CTE's SELECT list in `historic_fundamentals/sector.py` and `capex_intensity_median`,
      `rd_intensity_median`, `capex_to_da_median` to the outer `QUANTILE_CONT(...)
      FILTER (WHERE ... IS NOT NULL)` block, same pattern as `gross_margin_median`. Runs once
      per `group_type` (`sector`/`industry`), so both levels come from the one query.
- [x] 2.2 Added the 3 columns to `sector_stats`'s schema in `db.py` (base CREATE TABLE list +
      ALTER migration, matching how `gross_margin_median` etc. are declared) and to
      `upsert_sector_stats`'s dynamic `cols` list.
- [x] 2.3 Rebuilt via `uv run python scripts/rebuild_sector_stats.py`
      (`compute_sector_stats(..., full_rebuild=True)`): 43,720 rows upserted (5,253 sector-
      months, 38,467 industry-months); table total 44,642 rows post-rebuild vs. ~44,619
      pre-rebuild baseline (normal drift, not a regression) — 11 distinct sectors, 116
      distinct industries, unchanged. Sanity-checked the latest month's sector-level medians:
      R&D intensity ranks Healthcare (26.5%) and Technology (16.8%) highest, Real Estate
      (0.1%) and Energy (1.0%) lowest; capex intensity ranks Utilities highest (43.6% — the
      textbook most capex-intensive sector) and Financial Services lowest (1.4%). Correct
      direction and magnitude across all 11 sectors, no swapped/inverted columns.
- [x] 2.4 Added `current_capex_intensity`, `capex_intensity_5y_median`, `current_rd_intensity`,
      `rd_intensity_5y_median`, `current_capex_to_da` to `pe_stats` (schema in `db.py` +
      `compute_pe_stats()`'s margins block in `pe.py`). Named `_5y_median` (not `_5yr_`) to
      match the sibling `gross_margin_5y_median`/`operating_margin_5y_median` keys already in
      that same result dict and INSERT block, not the plan's original `5yr` guess.
      `upsert_pe_stats` is fully positional (`?` placeholders bound by list position, no
      dynamic column list like `upsert_sector_stats`) — verified column count, `?` count, and
      `stats.get()` count all match at 130 before running anything live.
      Re-ran the same full backfill as 1.4 (`hf_update.py --skip-estimates --skip-sector`)
      since the earlier Phase 1 backfill predated this code and left `pe_stats` NULL for
      these columns on ~2,656 tickers: 2,658 ok, 0 failed. Coverage: `current_capex_intensity`
      2,526/2,658 (95%), `current_capex_to_da` 2,560 (96%), `current_rd_intensity` 1,062 (40%
      — lower than monthly_pe's 82.5% historical-ever coverage because "current" requires
      R&D reported in the trailing 4 quarters specifically, a stricter bar than "reported at
      any point across 40 years"). `monthly_pe` row count unchanged (651,703) confirming the
      re-run was idempotent. AAPL's values match the Phase 1 smoke-test exactly.
      Full test suite green throughout (653 passed, 0 failed, checked before and after the
      live rebuild/backfill runs).

## Phase 3 — Factor gauntlet (exploratory)

- [x] 3.1 Built `scripts/test_capex_rd_factors.py` (reuses the existing infra directly:
      `historic_fundamentals.baselines.{compute_forward_returns,compute_factor_ic,ic_summary,
      quintile_returns}`, `historic_fundamentals.universe.{filter_universe,UNIVERSE_DEFAULTS}`,
      `scripts.run_backtest.{_load_monthly_pe,_join_sector}` — same building blocks
      `test_canslim_factors.py` uses, no new infra needed since the ratios are already
      point-in-time by construction from Phase 1). Tested 4 factors — `capex_intensity`,
      `capex_intensity_change_3y`, `rd_intensity`, `rd_intensity_change_3y` (3yr changes
      computed inline via `groupby("ticker").transform(lambda s: s - s.shift(36))`, not
      persisted as new columns since this is a one-off test) — via IC test (ret_6m/ret_1y),
      quintile spread, and an IS/OOS sign-stability check split at the sample midpoint
      (2006-06-30, 243 months each half) — the same test that killed the MD&A composite
      ([[project_mda_factors_result]]). Direction not assumed a priori, per `pe.py`'s own
      "not unambiguously directional" note on these columns.
- [x] 3.2 Findings logged in `docs/capex_rd_factors_test.md`
      ([[feedback_log_findings_in_the_artifact]]). Result: 3 of 4 factors
      (`capex_intensity`, `capex_intensity_change_3y`, `rd_intensity`) fail the IS/OOS
      sign-stability bar outright — same fate as Greenblatt/CANSLIM/MD&A — **not promoted**.
      `capex_intensity`'s near-zero full-period IC (-0.0055) turned out to be masking an
      exact sign flip (+0.057 IS / -0.058 OOS), not genuine noise both ways — worth knowing
      for anyone tempted to re-test it expecting "no effect" rather than "two canceling
      effects." The 4th, `rd_intensity_change_3y`, passed everything this test ran (IC
      t=3.87 full-period, quintile spread +2.96%, stable same-sign IC both halves:
      t=+2.81 IS / t=+2.96 OOS) — genuinely more promising than anything else tested here,
      but **also not promoted**: every factor this repo has actually promoted-or-rejected
      went through a full 30+-fold walk-forward backtest and a composite-level A/B first, and
      a single midpoint IS/OOS split is a lighter bar than that. Flagged as a concrete,
      specific follow-up (run it through `walk_forward_portfolio_backtest.py` +
      composite A/B, same shape as `greenblatt_factors_test.md` sections 4-6) rather than a
      vague "worth revisiting." No changes to `historic_fundamentals/baselines.py`
      `_VALUE_COLS`/`_QUALITY_COLS` or `scripts/score_live.py`.

## Phase 4 — Wire into the DCF (the concrete payoff, independent of Phase 3's result)

- [x] 4.1 Added `dcf.av_data.get_sector_dcf_fallback_ratios(ticker, as_of=None)` — looks up
      the ticker's sector/industry from `company_overview`, then the latest `sector_stats`
      `capex_intensity_median`/`rd_intensity_median`/`capex_to_da_median` at or before `as_of`
      (point-in-time safe, matches this module's existing `_as_of_clause` discipline — a
      historical DCF reconstruction must not see future sector medians), falling back
      sector -> industry -> `(None, None, None)`. Degrades to `(None, None, None)` on any
      lookup failure rather than raising, so this new path cannot break an already-working
      DCF run. Wired into `dcf/model.py::_run_dcf_core` (the one call site for
      `forecast_assumptions`) and threaded through as 3 new optional params.
      In `dcf/forecaster.py`: the `0.05` capex fallback now uses `sector_capex_intensity`
      when the ticker's own trailing capex history is empty (`len(cx_norm) == 0`); the `0.03`
      D&A fallback derives from `sector_capex_intensity / sector_capex_to_da` (this repo
      doesn't compute a standalone D&A-intensity ratio, so it's backed out via the sector's
      typical capex/D&A relationship — exactly what `capex_to_da_median` from Phase 2 was
      built for). Own history stays primary in both cases; hardcoded constants are the true
      last resort (no sector data / unclassified ticker).
- [x] 4.2 Same pattern for R&D: added `_RD_SECTOR_SIGNAL_THRESHOLD = 0.005` — when a ticker's
      own R&D history is empty AND its sector's `rd_intensity_median` is meaningfully
      non-zero (above the threshold), that's treated as a signal the ticker's own null is a
      data gap rather than "this company doesn't do R&D", and `rd_pct`/`has_rd` use the
      sector value. Sectors that genuinely don't do R&D (Real Estate, Utilities, Financial
      Services) have their own median near zero, so the threshold naturally leaves them
      alone — verified live: `O` (Real Estate) resolves to sector R&D 0.13%, below threshold,
      fallback correctly does not fire.
- [x] 4.3 Added `tests/test_forecaster_sector_fallback.py`, 10 new unit tests covering both
      ratios' full fallback chain: own-history-present (sector args ignored), no-history-with-
      sector-data (materially higher/different than the flat constant), no-history-no-sector-
      data (falls back to the original hardcoded 0.05/0.03), plus R&D's extra case (sector
      median near zero -> stays `None`, doesn't fabricate a fake R&D line). All 10 pass.
      Full suite: 663 passed, 0 failed (653 + these 10). Live end-to-end smoke test:
      `get_sector_dcf_fallback_ratios` against AAPL/O/an invalid ticker resolved correctly
      (Technology 2.5%/16.8%, Real Estate 12.1%/0.13%, unclassified -> all `None`); full
      `run_dcf_av("AAPL")` and `run_dcf_av("O")` both completed without error with the new
      wiring live.

## Out of scope

- R&D capitalization as a balance-sheet asset (Damodaran-style ROIC adjustment) — mentioned
  as a possible follow-on in the original review, not part of this plan.
- `trade_systems/data/fmp_financials.duckdb` has the same raw fields
  (`capital_expenditure`, `research_and_development_expenses`) but that DB is not part of
  this codebase's DCF/factor pipeline (fin_import2's `av_financials.duckdb` is authoritative
  for both) — no changes there.
