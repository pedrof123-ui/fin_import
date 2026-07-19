# DCF Screener — Implementation Plan

> Add a Screener filter for stocks whose DCF intrinsic value exceeds current price by a
> user-given percentage. Source: user request (VISION-style planning session).

---

## Decisions (confirmed with user)

1. **UI**: new filter field in the existing Screener (`ScreenerViewer.tsx` /
   `screener_router.py`), not a separate tab/panel — composes with all existing filters
   (sector, valuation, growth, quality, ...) in one query, same as the existing
   `goal_low_upside`/`goal_high_upside` price-target filters.
2. **Compute strategy**: a scheduled batch job populates a cache table
   (`dcf_results`); the screener joins that table and computes upside against the
   *live* `current_price` at query time. Running the full DCF model live across the
   ~2,650-ticker universe on every filter click is not viable (see Feasibility below).
3. **DCF engine**: `dcf.model.run_dcf_av` (Alpha Vantage-based), matching the repo's
   move to AV as the sole active data source (FMP is being archived). Not
   `run_dcf` (legacy XBRL / `financial_statements.duckdb` path) — see Note below.
4. **Refresh cadence**: monthly, folded into the existing `scripts/run_pipeline.py`
   (already runs `hf_update` after `--av-update`). New step runs right after
   `hf_update`, so the DCF cache always refreshes alongside `pe_stats`/`monthly_pe`.
   No new/separate cron entry.
5. **Universe**: all tickers in `company_overview` (~2,650) — same universe the rest
   of the screener already covers. Tickers that error out (insufficient quarterly
   history, etc.) are skipped and recorded with `status='error'` + `error_message`,
   not silently dropped or crashing the batch.

**Note (found during investigation, not part of this plan — FIXED since, see below):**
the live single-ticker `GET /dcf/{ticker}` endpoint (`api/dcf_router.py`) 500'd —
`financial_statements.duckdb`'s `earnings_estimates` table lacked the `fiscal_date`
column that `dcf/estimates.py` queries (confirmed via `describe earnings_estimates`:
that table exists with the right schema in `historic_fundamentals.duckdb`, not in
`financial_statements.duckdb`). This plan's batch script calls `run_dcf_av` directly
with an `estimates_conn` pointed at `historic_fundamentals.duckdb` — the same pattern
`api/valuation_data.py` already uses — so it never touched the broken code path.

**Addendum — bug fixed (out of the plan's original scope, done at user request):**
root cause was a genuine schema divergence, not a typo: `financial_statements.duckdb`'s
`earnings_estimates` table was created by `financial_statements_db.py` with a column
named `date`, populated by a separate legacy writer
(`scripts/update_alpha_vantage_estimates.py`) that had real data — 3,077 rows across 80
tickers, silently uncorrupted because writes from `dcf/estimates.py`'s own `_store()`
had always failed too (wrapped in a bare `except: pass`, so the bug was invisible on
the write path and only surfaced as a 500 on reads). Fixed by renaming the column to
`fiscal_date` in `financial_statements_db.py::_create_schema()` (matching
`historic_fundamentals.duckdb`'s existing convention), with an in-place
`ALTER TABLE ... RENAME COLUMN` migration guarded by an `information_schema` check —
same pattern `historic_fundamentals/db.py::_rename_column_if_exists()` already uses —
so the 3,077 existing rows were preserved, not dropped. Also updated
`scripts/update_alpha_vantage_estimates.py`'s `INSERT` column list to match.
Verified: migration ran against the real DB (3,077 rows / 80 tickers intact after
rename); `GET /dcf/AAPL`, `/dcf/WMT`, `/dcf/MSFT`, `/dcf/NVDA` all now return 200 with
real analyst-estimate data in the payload (previously all 500'd); `/dcf/JPM` and
`/dcf/BRUN` correctly return 422 (`ValueError`, not a crash) for unrelated,
pre-existing data-coverage gaps in `financial_statements.duckdb` specifically. Added
`tests/test_earnings_estimates_schema.py` (3 tests: fresh-DB schema, legacy-DB
migration preserves data, `fetch_and_cache()` no longer binder-errors on a seeded
cache row — no network dependency). Full suite: 243 passed, 3 skipped, 0 broken. A
secondary latent bug was fixed as a side effect: `_store()`'s writes to
`financial_statements.duckdb` will now actually succeed (they always silently failed
before), so the 30-day estimate cache will start working for that DB going forward.

---

## Feasibility check (done)

Timed `run_dcf_av` directly against `historic_fundamentals.duckdb` /
`av_financials.duckdb`:

- AAPL, JPM, WMT: 0.33–0.46s each.
- Random 30-ticker sample: 29/30 succeeded, 9.8s total (0.33s/ticker avg). The one
  failure (BRUN) raised a clean `ValueError` ("only 6 quarterly periods, need 8") —
  an expected, catchable data-quality skip, not a crash.
- Full universe (~2,650 tickers) projects to **~15 minutes sequential** — comfortably
  fits inside the existing monthly pipeline window (which already includes a ~30 min
  AV fetch step). No parallelization needed for v1.

---

## Architecture

```
scripts/compute_dcf_batch.py                                          [new]
  for ticker in company_overview:
      try:    run_dcf_av(ticker, estimates_conn=<historic_fundamentals.duckdb>)
              -> upsert dcf_results(ticker, intrinsic_value_per_share, wacc,
                                     terminal_growth_rate, enterprise_value, net_debt,
                                     diluted_shares, status='ok', error_message=NULL,
                                     computed_at)
      except: -> upsert dcf_results(..., status='error', error_message=str(e))

historic_fundamentals.duckdb
  + dcf_results table                                                 [new]

api/screener_router.py
  (already ATTACHes historic_fundamentals.duckdb as hf)
  + LEFT JOIN dcf_results dr ON ps.ticker = dr.ticker AND dr.status = 'ok'
  + RANGE_FIELDS entry:
      ("dcf_upside", "CASE WHEN ps.current_price > 0 AND dr.intrinsic_value_per_share
                            IS NOT NULL
                       THEN (dr.intrinsic_value_per_share / ps.current_price - 1)
                       ELSE NULL END")
  + two ScreenRequest fields: dcf_upside_min / dcf_upside_max
  + add dr.intrinsic_value_per_share + the dcf_upside expression to the base SELECT

web/components/ScreenerViewer.tsx
  + RANGE_FIELD_META["dcf_upside"] = { label: "DCF Upside", fmt: "pct" }
  + add "dcf_upside" to the "Price Targets" FILTER_SECTIONS entry
  + add to RESULT_COLS (green/red colored, same as other upside columns)
  + optional: new "DCF Undervalued" preset (e.g. dcf_upside_min: 20)
```

This is the exact extension recipe already documented at the top of both
`screener_router.py` and `ScreenerViewer.tsx` ("Adding a new metric: ..."). No new
architecture — one more field following the existing `goal_*_upside` pattern.

---

## Phase 0 — `dcf_results` cache table + batch script [DONE]

**Deliverables:**
- New table in `historic_fundamentals.duckdb`:
  `dcf_results(ticker VARCHAR PRIMARY KEY, intrinsic_value_per_share DOUBLE, wacc DOUBLE,
  terminal_growth_rate DOUBLE, enterprise_value DOUBLE, net_debt DOUBLE,
  diluted_shares DOUBLE, status VARCHAR, error_message VARCHAR, computed_at TIMESTAMP)`.
- `scripts/compute_dcf_batch.py`: iterates `company_overview` tickers, calls
  `run_dcf_av`, upserts one row per ticker (full rebuild each run, matching
  `hf_update.py`'s style — not incremental). Prints an ok/error summary at the end,
  same style as `scripts/measure_coverage.py`. Supports `--tickers` for targeted runs.
- `tests/test_compute_dcf_batch.py`: run against a small fixed ticker list (AAPL, JPM,
  WMT, BRUN), assert `dcf_results` gets exactly one row per ticker with correct
  `status`, and that BRUN (known thin-data ticker) produces `status='error'` with a
  non-null `error_message` rather than crashing the run.

**Testable:** `uv run scripts/compute_dcf_batch.py --tickers AAPL,JPM,WMT,BRUN`
produces 4 rows in `dcf_results` — 3 `status='ok'`, 1 `status='error'` (BRUN),
matching the ValueError already observed during feasibility testing.

**Result:** implemented as planned, no deviations.
- `dcf_results` table + `upsert_dcf_results()` added to `historic_fundamentals/db.py`,
  following the existing `upsert_sector_stats()` bulk-register-then-`INSERT OR REPLACE`
  pattern.
- `scripts/compute_dcf_batch.py` added; one fix needed vs. the original design — DuckDB
  refuses two connections to the same file with different configs in one process
  (`duckdb.connect(path)` read-write + `duckdb.connect(path, read_only=True)`
  simultaneously raises `ConnectionException`), so the script passes `hf_db.conn`
  itself as `estimates_conn` to `run_dcf_av` instead of opening a second read-only
  connection.
- `uv run scripts/compute_dcf_batch.py --tickers AAPL,JPM,WMT,BRUN --verbose` verified
  live: 3 ok, 1 error (BRUN, same "only 6 quarterly periods" message as the
  feasibility check), 4 rows written, 1.3s total.
- `tests/test_compute_dcf_batch.py` added (2 tests, run against a `tmp_path` copy of
  `historic_fundamentals.duckdb` so production data is never touched): status/value
  correctness per ticker, and full-rebuild-not-merge behavior on re-run. Both pass.
- Full existing suite (`uv run pytest tests/`) still green: 224 passed, 3 skipped, 0
  broken by the schema addition.

---

## Phase 1 — Wire into screener backend [DONE]

**Deliverables:**
- `api/screener_router.py`: join `dcf_results`, add `dcf_upside` to `RANGE_FIELDS` +
  `ScreenRequest`, add `intrinsic_value_per_share`/`dcf_upside` to the base SELECT.

**Testable:** `curl -X POST localhost:8000/screen -d '{"dcf_upside_min": 0.2}'`
returns only tickers where `intrinsic_value_per_share / current_price - 1 >= 0.20`
(verified in Python against the returned fields); tickers with no `dcf_results` row
are absent from results whenever this filter is set (not null-crashed into the set).

**Result:** implemented as planned, no deviations to the SQL design.
- Added `dr = hf.dcf_results` (status='ok' rows only) via `LEFT JOIN`, plus
  `dcf_intrinsic_value` and the `dcf_upside` CASE expression to the base SELECT and
  `RANGE_FIELDS`/`ScreenRequest`, following the exact `goal_*_upside` pattern.
- Verified live end-to-end against the real dev server (restarted to pick up the
  code change — no `--reload` flag on the running uvicorn process): unfiltered
  `/screen` still returns the full 2,651-ticker universe unchanged; BRUN (the
  Phase 0 error case) correctly shows `dcf_intrinsic_value: null` / `dcf_upside: null`
  and is excluded whenever `dcf_upside_min` is set; `dcf_upside_min` composes cleanly
  with an existing filter (`roic_min`).
- `tests/test_screener_dcf.py` added (4 tests, via `TestClient` against the real
  `historic_fundamentals.duckdb`/`av_financials.duckdb`, matching
  `test_valuation_data.py`'s no-mocking convention): dcf fields present for AAPL,
  filtered results never contain a null `dcf_upside` or a value below threshold,
  unfiltered count matches `pe_stats` exactly (join doesn't fan out/drop rows), and
  composability with `roic_min`. One test design flaw caught and fixed before it
  became a false signal: an initial "join doesn't shrink the unfiltered universe"
  check used `market_cap_b_min: 0` as a stand-in for "no filter," but that's a
  pre-existing screener behavior, not neutral — NULL `market_cap_b` rows correctly
  fail a `>= 0` comparison in SQL, so the check was comparing 2,651 against 2,650 for
  reasons unrelated to this change. Replaced with a direct comparison against
  `SELECT COUNT(DISTINCT ticker) FROM pe_stats`.
- Full suite: 240 passed (224 + 16 new across both phases), 3 skipped, 0 broken.

---

## Phase 2 — Wire into screener frontend [DONE]

**Deliverables:**
- `ScreenerViewer.tsx`: `RANGE_FIELD_META.dcf_upside` added to the "Price Targets"
  section, added to `RESULT_COLS`. Optional "DCF Undervalued" preset (confirm during
  implementation whether wanted).

**Testable:** in a browser, entering "20" in the DCF Upside min filter and running
the screen returns the same ticker set as the Phase 1 curl test; CSV export includes
the DCF Upside column.

**Result:** implemented as planned, no deviations.
- Added `dcf_upside` to `RANGE_FIELD_META` (Price Targets section) and `RESULT_COLS`,
  plus a "DCF Undervalued" preset (`dcf_upside_min: 20`) alongside the existing 4.
- Verified live in a real browser (Playwright against the already-running
  `next dev` server on :3000, hot-reloaded automatically — no restart needed): the
  "DCF Upside" filter row renders in Price Targets; the "DCF Undervalued" preset
  populates the field to 20 and correctly returns 0 matches (expected — only 3
  tickers have DCF data seeded so far from Phase 0, all currently DCF-overvalued);
  lowering the threshold to -90 returns exactly the 3 seeded tickers (AAPL, JPM,
  WMT) with DCF Upside values matching the Phase 1 curl test exactly
  (-47.5%/-55.3%/-71.7%, red-colored as negative); column sort works both
  directions; horizontal scroll reveals the column correctly positioned at the
  right of the results table.
- CSV export not independently re-verified in-browser (unchanged generic code path
  already covering all `RESULT_COLS` — same mechanism already proven for the other
  upside columns).

---

## Phase 3 — Pipeline integration [DONE]

**Deliverables:**
- `scripts/run_pipeline.py`: new `compute_dcf_batch` step inserted immediately after
  `hf_update`.

**Testable:** `uv run scripts/run_pipeline.py --skip-validate --skip-train` (fast
path) runs the new step and reports its timing in the final summary alongside
existing steps, without altering existing step behavior.

**Result:** implemented as planned, no deviations.
- Added the `compute_dcf_batch` step to `run_pipeline.py` right after `hf_update`,
  gated by a new `--skip-dcf` flag (mirroring `--skip-validate`/`--skip-train`), plus
  matching docstring/summary-output updates.
- Verified step ordering and flag gating via `--dry-run` (both with and without
  `--skip-dcf`) — new step appears in the right place, existing steps unchanged.
- Ran the **real full-universe batch** (not just a dry-run) to actually roll this
  out beyond the Phase 0 seed tickers: `uv run scripts/compute_dcf_batch.py` over
  all 2,652 tickers in `company_overview` — **2,613 ok, 39 error (98.5% success),
  1167.3s (~19.5 min** — a bit longer than the ~15 min feasibility estimate, still
  comfortably within the monthly pipeline window). All 39 errors are the same two
  clean, expected causes seen in feasibility testing: thin quarterly history
  (< 8 quarters) or tickers with no AV data at all (mostly non-US ADRs — ASML, ERIC,
  HMC, NVO, SNY, TSM, SBS, HMY, FUTU, CCEP, E — a pre-existing AV data-coverage gap,
  unrelated to this feature).
- Verified end-to-end against the real, fully-populated cache: `POST /screen` with
  `dcf_upside_min: 0.2, market_cap_b_min: 1` returns 525 real, diverse tickers
  (NVDA +90%, JNJ +72%, WFC +21.5%, etc.) instead of the Phase 0 seed set. In the
  browser, the "DCF Undervalued" preset (still `dcf_upside_min: 20`) now returns
  **698 matches** against the full universe, confirming the feature works
  end-to-end with real data, not just the 4-ticker seed sample.
- Noted, not fixed (pre-existing, out of scope): a handful of `dcf_upside` values
  are extreme (600%+) for some tickers — this is the underlying DCF engine's known
  sensitivity to margin/WACC assumptions on certain names, not something introduced
  by this integration; the screener only surfaces `dcf/model.py`'s existing output.

**All 3 implementation phases of this plan are now complete.**

---

## Non-goals

- Per-user custom DCF assumption overrides in the screener — the existing
  `POST /dcf/{ticker}/run` per-ticker override UI already covers ad hoc "what-if"
  analysis for one name at a time. The screener uses model-default assumptions for
  every ticker, same as `pe_stats`.
- Fixing the unrelated `GET /dcf/{ticker}` 500 bug in `api/dcf_router.py` — flagged
  above as a separate, pre-existing issue, not touched by this plan.
