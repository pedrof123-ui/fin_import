# PLAN: Financial Statements Web App

## Overview

A full-stack web app with a Next.js frontend and a FastAPI backend. The backend wraps the existing Python pipeline to import SEC filings into DuckDB and serve the stored data. The frontend lets the user trigger imports and view financial statements.

---

## Architecture

```
Browser (Next.js)
    ↕  HTTP (JSON)
FastAPI backend (Python)
    ↕
Existing pipeline (bulk_import_10k.py, extractors/, financial_statements_db.py)
    ↕
DuckDB (data/financial_statements.duckdb)
```

The frontend and backend run as two separate processes in development. In production they can be co-located or deployed separately.

---

## Backend: FastAPI (`api/`)

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/import` | Trigger import for a ticker |
| GET | `/statements/{ticker}/{type}` | Retrieve stored statement |
| GET | `/tickers` | List tickers already in DB |

### POST `/import`

Request body:
```json
{
  "ticker": "AAPL",
  "periods": 5,
  "period_type": "FY"
}
```

- `period_type` `"FY"` → fetches 10-K filings; `"Q"` → fetches 10-Q filings
- Calls `process_ticker()` from `bulk_import_10k.py` (or the 10-Q equivalent)
- Runs async; returns `{ "status": "ok", "filings_processed": N }` when complete
- Returns HTTP 200 on success, 400 on bad ticker, 500 on extraction error

### GET `/statements/{ticker}/{type}`

- `type`: `income` | `balance` | `cashflow`
- Query params: `period_type=FY|Q`, `periods=N` (number of most recent periods to return)
- Calls `db.get_company_statements()` filtered by period_type and limited to N rows
- Returns JSON array of records (one per period), columns = top-level DB fields only
- 404 if ticker not found in DB

### GET `/tickers`

- Returns `["AAPL", "MSFT", ...]` from the `companies` table

### File structure

```
api/
  main.py          # FastAPI app, route definitions
  schemas.py       # Pydantic request/response models
  db.py            # Thin wrapper: opens FinancialStatementsDB, exposes query helpers
  importer.py      # Wraps process_ticker(); handles FY vs Q, error handling
requirements-api.txt  # fastapi, uvicorn, plus existing project deps
```

### Key implementation notes

- Open a single `FinancialStatementsDB` instance at startup (app lifespan)
- `process_ticker()` is async — run directly in the endpoint; no job queue needed for MVP
- For 10-Q support: the existing `extract_and_insert_filing()` already handles quarterly filings; `process_ticker()` needs a `form_type` parameter passed through to filter Edgar filings by `'10-Q'` instead of `'10-K'`
- CORS: allow `localhost:3000` in development

---

## Frontend: Next.js (`web/`)

### Tech choices

- Next.js (App Router)
- Tailwind CSS (dark mode via `darkMode: 'class'`, class set on `<html>`)
- shadcn/ui components (Input, Select, Button, Table)
- `fetch` for API calls (no extra client library needed)

### Pages / Components

```
web/
  app/
    layout.tsx          # Dark html root, global styles
    page.tsx            # Single-page app
  components/
    ImportForm.tsx      # Ticker input, periods input, FY/Q dropdown, Submit button
    StatementViewer.tsx # Statement type dropdown + data table
    LoadingSpinner.tsx  # Simple spinner for import in progress
```

### UI flow

1. User fills `ImportForm`:
   - Ticker: text input (uppercased automatically)
   - Periods: number input (default 5, min 1 max 20)
   - Period type: select FY | Q

2. On submit: POST `/import` → show spinner while waiting

3. On success: fetch GET `/statements/{ticker}/income` (default) → render table

4. `StatementViewer` has a statement-type dropdown (Income Statement | Balance Sheet | Cash Flow). Changing it fetches the corresponding endpoint and re-renders the table.

5. Table columns: Period End Date + all non-null top-level financial fields. Format numbers as `$X.XXB / $X.XXM` (billions/millions) depending on magnitude.

### Top-level concepts displayed

The DB already stores only top-level standardized fields — no raw XBRL sub-items. Display every DB column that is a financial value (i.e., exclude metadata columns: ticker, filing_date, extraction_date, fields_extracted, total_fields, coverage_pct, filing_type). This naturally satisfies "display revenue not revenue details".

Suggested display order (Income Statement example):
`period_end_date | revenue | gross_profit | operating_income | pretax_income | net_income | diluted_eps`

Full column lists come from the DB schema — all columns in `income_statements`, `balance_sheets`, `cash_flow_statements` minus the 8 metadata columns.

---

## Implementation Order

### Phase 1 — Backend foundation
1. Create `api/` directory and `api/main.py` with FastAPI app skeleton
2. Implement `api/db.py`: open DuckDB, expose `get_statements()` and `list_tickers()`
3. Implement GET `/tickers` and GET `/statements/{ticker}/{type}`
4. Test with existing DuckDB data using curl / httpie

### Phase 2 — Import endpoint
5. Implement `api/importer.py`: wrap `process_ticker()`, handle FY vs Q (pass `form='10-K'` or `'10-Q'` to Edgar)
6. Implement POST `/import`
7. Test end-to-end import of a single ticker

### Phase 3 — Frontend scaffold
8. `npx create-next-app web --typescript --tailwind --app`
9. Install shadcn/ui: `npx shadcn@latest init`
10. Set dark mode class on `<html>` in `layout.tsx`
11. Build `ImportForm` component (static, no API calls yet)
12. Build `StatementViewer` component (static mock data)

### Phase 4 — Wire frontend to backend
13. Connect `ImportForm` submit → POST `/import`
14. On success, trigger GET `/statements/{ticker}/{type}` → pass data to `StatementViewer`
15. Wire statement-type dropdown to re-fetch correct endpoint
16. Add number formatting (billions/millions)
17. Add loading and error states

### Phase 5 — Polish
18. Responsive layout, spacing, typography
19. Empty state when no data yet (prompt user to import)
20. Show ticker list from GET `/tickers` as autocomplete or recent imports list

---

## Development setup

```bash
# Backend
cd api
uv run uvicorn main:app --reload --port 8000

# Frontend
cd web
npm run dev   # runs on :3000
```

Backend URL configured in `web/.env.local`:
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Out of scope (MVP)

- Authentication
- Background job queue / WebSocket progress streaming
- Pagination of large tables
- Chart/visualization of time series
- Export to CSV
