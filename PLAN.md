# Earnings Call Transcript Database — Implementation Plan

## Overview

Populate and maintain `data/earnings_transcripts.duckdb` with earnings call transcripts
for all tickers in `av_financials.duckdb`, sourced from the Alpha Vantage
`EARNINGS_CALL_TRANSCRIPT` API.

**Scope agreed:**
- Ticker universe: all ~2,655 tickers in `av_financials.duckdb`
- History depth: latest 4 quarters per ticker (backfill)
- Weekly update: check latest 1-2 quarters for all tickers
- `earnings_call_date`: add as nullable column (AV does not return this field)

---

## Phase 1: Schema Enhancement

**Files:** `api/earnings_router.py`, `api/research_router.py`

### Steps

1. Add `earnings_call_date DATE` (nullable) to `CREATE TABLE IF NOT EXISTS` in
   `earnings_router._open_db()`.
2. Add the corresponding `ADD COLUMN` migration guard (same pattern as existing
   `source` column migration).
3. Update `_save_transcript()` signature to accept `earnings_call_date: Optional[date] = None`
   and include it in the `INSERT ... ON CONFLICT DO UPDATE`.
4. Mirror the same schema change + migration guard in `research_router.py`'s inline
   `CREATE TABLE IF NOT EXISTS` block (lines ~631–644).

**Test:** Run `uv run python3 -c "from api.earnings_router import _open_db; c = _open_db(); print(c.execute('DESCRIBE earnings_transcripts').fetchall()); c.close()"` and confirm `earnings_call_date` column appears.

**Status:** [x] Complete

---

## Phase 2: Shared Transcript Helper Module

**Files:** `historic_fundamentals/earnings_transcripts.py` (new)

Extract the AV fetch + DB write logic into a shared module so both the backfill
script and weekly update script can reuse it without duplicating code.

### Steps

1. Create `historic_fundamentals/earnings_transcripts.py` with:
   - `open_db(db_path) -> duckdb.DuckDBPyConnection` — opens DB with full schema
     (same as `_open_db()` in earnings_router, including migration guards)
   - `get_latest_cached_quarter(conn, symbol) -> Optional[str]`
   - `is_cached(conn, symbol, quarter) -> bool`
   - `save_transcript(conn, symbol, quarter, transcript_text, api_json, source, earnings_call_date)` — upsert
   - `fetch_from_av(symbol, quarter, api_key) -> Optional[str]` — returns transcript
     text or `None` (no raise on 404/missing); also returns raw `api_json`
   - `fiscal_date_to_quarters(latest_fiscal_date, today, n_quarters) -> list[str]` —
     converts the ticker's latest `fiscal_date_ending` to an ordered list of calendar
     quarter strings to probe, applying the 60-day lookahead rule

2. Update `api/earnings_router.py` to import and use this module (replace duplicated
   code). `_fetch_from_av()` can wrap the helper; `_open_db()` can delegate to it.

3. Update `api/research_router.py` `get_earnings_summary()` to use the shared module
   for schema creation and save, removing ~25 lines of duplicated code.

**Test:** `uv run python3 -c "from historic_fundamentals.earnings_transcripts import fiscal_date_to_quarters; from datetime import date; print(fiscal_date_to_quarters(date(2026,3,31), date(2026,6,22), 4))"` should return `['2026Q2', '2026Q1', '2025Q4', '2025Q3']`.

**Status:** [x] Complete

---

## Phase 3: Backfill Script

**File:** `scripts/earnings_backfill.py`

One-time script: fetch the latest 4 quarters of earnings call transcripts for all
tickers in `av_financials.duckdb`. Resume-safe (skips already-cached entries).

### Steps

1. Create `scripts/earnings_backfill.py`:
   - Load all tickers from `av_financials.duckdb` (`SELECT DISTINCT ticker FROM income_statements`)
   - For each ticker, get `MAX(fiscal_date_ending)` where `period_type = 'quarterly'`
   - Call `fiscal_date_to_quarters(latest_fiscal_date, today, n=4)` to get the 4 quarters to attempt
   - For each quarter, skip if `is_cached(conn, symbol, quarter)`
   - Fetch via `fetch_from_av()`, save via `save_transcript()`
   - Rate-limit at 75 calls/min using `RateLimiter` from `av_financials_db.py`
   - Progress bar via `tqdm`; print summary (fetched, skipped, not_found, errors) at end
   - `--ticker TICKER` flag for single-ticker runs
   - `--dry-run` flag that prints what would be fetched without making API calls

**Rate estimate:** 2,655 tickers × up to 4 calls = up to 10,620 calls → ~142 min at 75/min.
In practice much faster: most "not found" responses return quickly and many recent
quarters will already be in the DB.

**Usage:**
```
uv run scripts/earnings_backfill.py
uv run scripts/earnings_backfill.py --ticker AAPL
uv run scripts/earnings_backfill.py --dry-run
```

**Test:** Run `uv run scripts/earnings_backfill.py --ticker AAPL` and verify AAPL has
up to 4 quarters in the DB after completion.

**Status:** [x] Complete

---

## Phase 4: Weekly Update Script

**File:** `scripts/earnings_update.py`

Weekly script: for each ticker in `av_financials.duckdb`, check if there is a newer
transcript than what is currently cached (1–2 AV calls per ticker).

### Steps

1. Create `scripts/earnings_update.py`:
   - Load all tickers + their `MAX(fiscal_date_ending)` from `av_financials.duckdb`
   - For each ticker, call `fiscal_date_to_quarters(latest_fiscal_date, today, n=2)`
     to get the 1–2 quarters most likely to be new
   - For each quarter, skip if `is_cached(conn, symbol, quarter)`
   - Fetch, save, rate-limit (same pattern as backfill)
   - Print summary: checked, new_fetched, already_cached, not_found, errors
   - `--ticker TICKER` flag for single-ticker runs

**Rate estimate:** 2,655 tickers × up to 2 calls = up to 5,310 calls → ~71 min worst
case, typically much less (most quarters already cached).

**Usage:**
```
uv run scripts/earnings_update.py
uv run scripts/earnings_update.py --ticker MSFT
```

**Test:** Run `uv run scripts/earnings_update.py --ticker MSFT` and confirm the latest
quarter is in the DB.

**Status:** [x] Complete

---

## Phase 5: On-demand Fetch Alignment

**File:** `api/earnings_router.py`

Ensure the on-demand flow (Finview Earnings Summary tab) properly uses the shared
helper from Phase 2 and passes `earnings_call_date=None` to align with the updated
schema. No functional change to user-facing behavior — this phase cleans up the
router after the Phase 2 refactor.

### Steps

1. Verify `earnings_router.py` after Phase 2 refactor: confirm `_save_transcript()`,
   `_fetch_from_av()`, `_open_db()` all delegate to `historic_fundamentals.earnings_transcripts`.
2. Remove any remaining duplicated schema creation code.

**Test:** Make a request to `/earnings/report?ticker=AAPL&quarter=latest` and confirm
the response is generated and the transcript is in the DB with `earnings_call_date = NULL`.

**Status:** [x] Complete

---

## Implementation Order

1. Phase 1 (Schema) — prerequisite for all phases
2. Phase 2 (Shared module) — prerequisite for 3, 4, 5
3. Phase 3 (Backfill) and Phase 4 (Weekly update) — can be done in parallel after Phase 2
4. Phase 5 (Router alignment) — after Phase 2

---

## Notes

- AV rate limit is 75 calls/min. Both scripts use `RateLimiter` from `av_financials_db.py`.
- The backfill is idempotent: re-running skips already-cached (symbol, quarter) pairs.
- The weekly update script is meant to run as a scheduled task (e.g., cron on Sunday night).
- `earnings_call_date` will be NULL for all AV-sourced transcripts until AV adds it to
  their API response. The column is kept for future use and potential manual updates.
- Quarter format used throughout: `YYYYQN` (e.g., `2026Q2`), matching calendar quarters
  derived from `fiscal_date_ending` via `(month - 1) // 3 + 1`.
