# Earnings Calendar Feature Plan

## Goal

Add an Earnings Calendar tab to FinView showing upcoming earnings releases for all
tickers tracked in av_financials.duckdb. Data is sourced from the AV
`EARNINGS_CALENDAR` API endpoint (3-month horizon, CSV response).

## Decisions

- **Horizon**: 3 months fixed
- **Tab**: Standalone (always visible, like Screener/Sector)
- **Update frequency**: Weekly (alongside `earnings_update.py`)
- **Storage**: `av_financials.duckdb` — new `earnings_calendar` table

---

## Phase 1: Database Table + Download Script

**Goal**: Create the schema and a runnable script that populates it.

### 1.1 — Add `earnings_calendar` table to av_financials.duckdb

Schema (create-if-not-exists, upsert on `(symbol, report_date)`):

```sql
CREATE TABLE IF NOT EXISTS earnings_calendar (
    symbol             VARCHAR  NOT NULL,
    name               VARCHAR,
    report_date        DATE     NOT NULL,
    fiscal_date_ending DATE,
    estimate           DOUBLE,
    currency           VARCHAR,
    fetched_at         TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, report_date)
);
```

### 1.2 — Script `scripts/earnings_calendar_update.py`

- Fetch `EARNINGS_CALENDAR&horizon=3month` from AV API — response is a CSV stream
- Parse CSV in-memory (no file written to disk)
- Filter rows to symbols present in `companies` table of av_financials.duckdb
- Upsert into `earnings_calendar` (INSERT OR REPLACE)
- Purge rows where `report_date < today() - INTERVAL 30 DAYS` (keep a 30-day lookback)
- Obey 75-call/min rate limit (this is a single API call, no loop needed)
- CLI: `uv run scripts/earnings_calendar_update.py [--verbose]`

**Testable**: Run the script and verify rows appear in the table via a quick
`SELECT COUNT(*), MIN(report_date), MAX(report_date) FROM earnings_calendar`.

### Status: [x] Complete

---

## Phase 2: API Endpoint

**Goal**: Expose the calendar data via FastAPI.

### 2.1 — `api/earnings_calendar_router.py`

```
GET /earnings-calendar
```

Returns JSON list sorted by `report_date ASC`:

```json
[
  {
    "symbol": "AAPL",
    "name": "Apple Inc",
    "sector": "Technology",
    "report_date": "2026-07-31",
    "fiscal_date_ending": "2026-06-30",
    "estimate": 1.43,
    "currency": "USD",
    "status": "upcoming"   // "upcoming" | "reported"
  }
]
```

- `status` derived at query time: `"reported"` if `report_date < today()`, else `"upcoming"`
- JOIN with `company_overview` (latest row per ticker) for `name` and `sector`
- Only return rows where `report_date >= today() - INTERVAL 30 DAYS`

### 2.2 — Register router in `api/main.py`

Import and `app.include_router(earnings_calendar_router)`.

**Testable**: `curl http://localhost:8000/earnings-calendar` returns a valid JSON array.

### Status: [x] Complete

---

## Phase 3: Frontend Component + Tab Wiring

**Goal**: Display the calendar as a new standalone tab.

### 3.1 — `web/components/EarningsCalendarViewer.tsx`

- Table grouped by week (Mon–Sun) with a subtle week-header row
- Columns: Symbol, Company, Sector, Report Date, Fiscal Period End, EPS Estimate
- "Upcoming" rows normal; "Reported" rows dimmed (opacity-40 or similar)
- Show count of upcoming events in a header line
- Refresh button (re-fetches from API)
- Empty state if no data: hint to run `uv run scripts/earnings_calendar_update.py`

### 3.2 — Wire tab in `web/app/page.tsx`

- Add `"earnings_calendar"` to the `Tab` type union
- Add to `tabs` array (always visible, between `sector` and `av_financials`)
- Label: `"Calendar"`
- Import and render `<EarningsCalendarViewer />`

**Testable**: Tab appears in FinView, clicking it renders the table with real data.

### Status: [x] Complete

---

## Phase 4: Integration + Documentation

### 4.1 — Add to `scripts/README.md`

Document `earnings_calendar_update.py` with usage and scheduling note
(run weekly alongside `earnings_update.py`).

### Status: [x] Complete

---

## Test Plan (end-to-end)

1. `uv run scripts/earnings_calendar_update.py --verbose` — no errors, rows in DB
2. `uv run uvicorn api.main:app --reload` — `GET /earnings-calendar` returns data
3. `cd web && npm run dev` — Calendar tab visible, table renders correctly
4. Re-run script a second time — no duplicate rows, old rows purged
