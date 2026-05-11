# Historic Fundamentals — Implementation Plan

## Status

**Phase 1 — COMPLETE** (2026-05-10): Database + PE timeseries + CLI scripts
**Phase 1.5 — COMPLETE** (2026-05-11): Shares outstanding + dividends + dividend yield
**Phase 2 — COMPLETE** (2026-05-10): Query interface and Python API
**Phase 2.5 — COMPLETE** (2026-05-11): Revenue growth metrics + market cap + PE column renames
**Phase 3 — PENDING**: FastAPI router (future, when UI integration needed)

---

## Architecture

### New database: `data/historic_fundamentals.duckdb`

Separate from `av_financials.duckdb` (raw statements) and `financial_statements.duckdb` (SEC EDGAR). Stores all derived metrics and analyst estimates snapshots.

**Rationale**: Raw data belongs in its source DB; derived analytics belong in their own DB. This keeps concerns clean and makes the feature independently deployable.

### Code structure

```
historic_fundamentals/           # new package at project root
    __init__.py
    db.py                        # HistoricFundamentalsDB class (schema + query methods)
    pe.py                        # TTM EPS calculation, monthly PE, statistics
    estimates.py                 # EARNINGS_ESTIMATES fetch + store

scripts/
    hf_import.py                 # bulk backfill: compute PE history for all tickers
    hf_update.py                 # monthly update: add new month + refresh estimates
    hf_query.py                  # CLI query interface
```

---

## Database schema (`historic_fundamentals.duckdb`)

### `monthly_pe`
Primary timeseries. One row per (ticker, month-end).

```sql
CREATE TABLE monthly_pe (
    ticker                VARCHAR  NOT NULL,
    month_end_date        DATE     NOT NULL,   -- last calendar day of the month
    price                 DOUBLE,              -- adj_close on last trading day of month
    ttm_eps               DOUBLE,              -- sum of 4 most recent quarterly net_income / shares
    pe_ratio              DOUBLE,              -- price / ttm_eps; NULL when ttm_eps <= 0
    pe_rolling_5yr_median DOUBLE,              -- median pe_ratio over trailing 60 months; NULL if <60 months available
    ttm_source            VARCHAR,             -- 'quarterly' or 'annual' (see Historical Depth below)
    shares                DOUBLE,              -- shares_outstanding used for EPS (diluted preferred)
    ttm_dividend          DOUBLE,              -- sum of dividends with ex_date in trailing 365 days
    dividend_yield        DOUBLE,              -- ttm_dividend / price; NULL when no dividend data
    ttm_revenue           DOUBLE,              -- sum of 4 most recent quarterly total_revenue (or annual fallback)
    updated_at            TIMESTAMP,
    PRIMARY KEY (ticker, month_end_date)
)
```

### `pe_stats`
Pre-computed statistics snapshot, refreshed on each monthly update.

```sql
CREATE TABLE pe_stats (
    ticker                VARCHAR  PRIMARY KEY,
    updated_at            TIMESTAMP,
    -- Market cap
    market_cap_b          DOUBLE,              -- latest price × diluted shares / 1e9 (billions)
    -- Current PE
    current_pe            DOUBLE,              -- most recent month's pe_ratio
    current_ttm_eps       DOUBLE,
    -- Long-term PE stats (all available months)
    pe_lt_median          DOUBLE,
    pe_p10                DOUBLE,
    pe_p25                DOUBLE,
    pe_p75                DOUBLE,
    pe_p90                DOUBLE,
    months_available      INTEGER,
    -- Rolling 5-year PE (last 60 months)
    pe_rolling_5yr_median DOUBLE,
    -- Forward PE (from latest analyst estimates)
    forward_pe            DOUBLE,              -- current price / forward_12m_eps
    forward_12m_eps       DOUBLE,
    -- Dividend
    ttm_dividend          DOUBLE,              -- most recent month's TTM dividend per share
    dividend_yield        DOUBLE,              -- most recent month's dividend_yield
    -- Revenue growth
    rev_growth_1yr        DOUBLE,              -- (latest annual rev / prior year) - 1
    rev_cagr_3yr          DOUBLE,              -- 3-year revenue CAGR from annual data
    rev_cagr_5yr          DOUBLE,              -- 5-year revenue CAGR from annual data
    rev_ntm_growth_est    DOUBLE               -- (NTM estimated rev / TTM actual rev) - 1
)
```

### `earnings_estimates`
Time-series snapshots of analyst estimates (different from DCF's current-period cache — this preserves history).

```sql
CREATE TABLE earnings_estimates (
    ticker              VARCHAR   NOT NULL,
    fiscal_date         DATE      NOT NULL,   -- period-end the estimate is for
    horizon             VARCHAR   NOT NULL,   -- 'fiscal year' or 'fiscal quarter'
    fetched_at          TIMESTAMP NOT NULL,
    eps_avg             DOUBLE,
    eps_high            DOUBLE,
    eps_low             DOUBLE,
    eps_count           INTEGER,
    eps_avg_7d          DOUBLE,
    eps_avg_30d         DOUBLE,
    eps_avg_60d         DOUBLE,
    eps_avg_90d         DOUBLE,
    eps_rev_up_7d       INTEGER,
    eps_rev_down_7d     INTEGER,
    eps_rev_up_30d      INTEGER,
    eps_rev_down_30d    INTEGER,
    rev_avg             DOUBLE,
    rev_high            DOUBLE,
    rev_low             DOUBLE,
    rev_count           INTEGER,
    PRIMARY KEY (ticker, fiscal_date, horizon, fetched_at)
)
```

---

## EPS and PE Calculation

### EPS source: `av_financials.duckdb` (no extra API calls)

TTM EPS = `SUM(net_income for last 4 quarterly periods) / latest shares_outstanding_diluted`

- `net_income` from `income_statements` (period_type = 'quarterly')
- `shares` from `shares_outstanding.shares_outstanding_diluted` (most recent entry ≤ month_end) — primary source
- Fallback: `balance_sheets.common_stock_shares_outstanding` (quarterly, then annual)
- No additional Alpha Vantage API calls required for the PE computation phase

Diluted shares are preferred over balance sheet basic shares because they include dilutive instruments (options, convertibles) and are the standard denominator for EPS in equity analysis.

**Why not AV EARNINGS endpoint**: Would cost 1 extra call per ticker (1,465 calls = 20 min additional). The data we need is already available.

### Dividend yield source: `av_financials.duckdb / dividends`

TTM dividend per share = sum of `amount` where `ex_dividend_date` is within the trailing 365 days of each month-end.

Dividend yield = `ttm_dividend / price` (NULL when no dividend data available).

### Historical depth

AV quarterly data: last 20 quarters (~5 years)
AV annual data: last 20 annual periods (~20 years)

Strategy:
- **Months with 4+ quarters available** (recent ~4.5 years): TTM from quarterly sum, `ttm_source = 'quarterly'`
- **Months before quarterly coverage** (earlier years): annual `net_income / shares` as TTM proxy, `ttm_source = 'annual'`

This gives ~20 years of monthly PE data. Long-term median and percentiles will be based on all available months regardless of source.

### Month-end price

Use `adj_close` from `prices.duckdb/stock_prices` on the last trading day of each month. `adj_close` is preferred over `close` because it accounts for stock splits and dividends, making historical comparisons valid.

### Negative TTM EPS

When TTM EPS <= 0, `pe_ratio` is stored as NULL. These months are excluded from median/percentile calculations. The `months_available` in `pe_stats` counts only non-NULL PE months.

### Forward PE

Forward 12M EPS = sum of the next 4 quarterly `eps_avg` from `earnings_estimates` (fiscal quarter horizon, future dates). If fewer than 4 quarterly estimates are available, fall back to the next annual estimate directly.

Forward PE = most recent month-end price / forward_12m_eps.

---

## Script responsibilities

### `scripts/hf_import.py` — bulk backfill

Initial backfill: computes full PE history from existing `av_financials.duckdb` data, then fetches `EARNINGS_ESTIMATES` from Alpha Vantage for all tickers.

```
uv run scripts/hf_import.py                     # all tickers from av_financials.duckdb
uv run scripts/hf_import.py AAPL MSFT           # specific tickers
uv run scripts/hf_import.py --csv tickers.csv
uv run scripts/hf_import.py --force             # recalculate even if already present
uv run scripts/hf_import.py --skip-estimates    # PE only, skip AV estimates calls
```

Per ticker:
1. Load quarterly + annual `net_income` and `shares` from `av_financials.duckdb`
2. Build monthly PE timeseries including `rolling_5yr_median` per row
3. Compute PE stats (median, percentiles, current rolling 5yr)
4. Upsert into `monthly_pe` and `pe_stats`
5. Fetch `EARNINGS_ESTIMATES` from AV, compute `forward_pe`, upsert into `earnings_estimates` and update `pe_stats`

Throughput: PE computation is local (no AV calls). Estimates fetch: 1 call/ticker at 75/min = ~20 min for all 1,465 tickers.

### `scripts/hf_update.py` — monthly cron

Intended to run at month-end (e.g., first business day of each new month). Same structure as `hf_import.py` but only adds the latest month rather than full history.

```
uv run scripts/hf_update.py                     # all tickers
uv run scripts/hf_update.py --ticker AAPL       # single ticker
uv run scripts/hf_update.py --skip-estimates    # PE only, no AV calls
```

Steps:
1. For each ticker: compute PE for the most recently completed month, upsert into `monthly_pe`
2. Recalculate `pe_stats` (long-term stats shift as new months are added)
3. Fetch `EARNINGS_ESTIMATES` from AV (1 call/ticker), store snapshot in `earnings_estimates`
4. Update `forward_pe` and `forward_12m_eps` in `pe_stats`

Rate limit: 1,465 tickers / 75 calls-per-min = ~20 min. Same `RateLimiter` as `av_financials_db.py`.

### `scripts/hf_query.py` — CLI query

```
uv run scripts/hf_query.py AAPL                           # current snapshot
uv run scripts/hf_query.py AAPL MSFT --fields pe_stats
uv run scripts/hf_query.py AAPL --timeseries --start 2020-01-01
uv run scripts/hf_query.py --all --fields pe_stats --out out.csv
uv run scripts/hf_query.py AAPL --estimates
```

Returns: DataFrame to stdout or CSV.

---

## Answered design questions from VISION

**Q8 — Same database or separate for derived stats?**

Separate database (`historic_fundamentals.duckdb`). Within it, store both the raw monthly PE timeseries (`monthly_pe`) and the pre-computed statistics (`pe_stats`). Do not pollute `av_financials.duckdb` with derived analytics.

Pre-compute stats rationale: with 1,465 tickers × ~240 monthly PE rows each = ~350k rows, on-the-fly aggregation is fast in DuckDB. However, pre-computing and caching in `pe_stats` makes bulk queries (e.g., "show all tickers trading below their long-term median PE") instant without re-aggregating every time.

**Q10 — Framework organization?**

- `historic_fundamentals/` package: pure library, no CLI, importable by other Python apps and AI agents
- `scripts/hf_*.py`: CLI entry points, thin wrappers over the library
- `data/historic_fundamentals.duckdb`: all stored data for this feature
- Coexists with `av_financials.duckdb` (source) and `financial_statements.duckdb` (DCF track)
- The `earnings_estimates` table in `financial_statements.duckdb` remains as-is for DCF; the new one in `historic_fundamentals.duckdb` adds time-series history

---

## Decisions

1. **Earnings estimates coexistence**: Keep both. DCF's table in `financial_statements.duckdb` stays as-is (current-period cache, delete-replace). New `earnings_estimates` table in `historic_fundamentals.duckdb` adds time-series history with preserved snapshots.

2. **Estimates backfill**: `hf_import.py` performs both PE backfill (local, no API) and EARNINGS_ESTIMATES backfill (1 AV call/ticker). Use `--skip-estimates` to run PE-only if needed.

3. **REST API**: No REST API in Phase 1 or 2. The Python library (`historic_fundamentals/`) directly satisfies the "other apps and AI agents" requirement. FastAPI router added in Phase 3 when UI integration is needed — the library design makes this a thin layer.

4. **Rolling 5-year median timeseries**: Stored per row in `monthly_pe.rolling_5yr_median` (trailing 60-month window). Computed during import/update as a window function. Enables charting historical PE vs its own rolling median.

---

## Implementation phases

### Phase 1 — Core infrastructure (COMPLETE 2026-05-10)
- [x] `historic_fundamentals/db.py`: `HistoricFundamentalsDB` class — schema, upsert, query methods
- [x] `historic_fundamentals/pe.py`: TTM EPS computation, monthly PE builder, `rolling_5yr_median` per row, `pe_stats` aggregation
- [x] `historic_fundamentals/estimates.py`: EARNINGS_ESTIMATES fetch, upsert, forward PE calculation
- [x] `historic_fundamentals/__init__.py`: public API exports
- [x] `scripts/hf_import.py`: bulk backfill (PE history + estimates, with `--skip-estimates`)
- [x] `scripts/hf_update.py`: monthly update (latest month PE + estimates refresh)

### Phase 1.5 — Shares outstanding + dividends (COMPLETE 2026-05-11)
- [x] `av_financials_db.py`: `shares_outstanding` and `dividends` tables + `import_shares_outstanding()` and `import_dividends()` methods
- [x] `historic_fundamentals/pe.py`: `_load_shares_ts()` — primary diluted shares from `shares_outstanding`; `_load_dividends()` — dividend event history; `build_monthly_pe()` extended with `ttm_dividend` and `dividend_yield` computation
- [x] `historic_fundamentals/db.py`: `ttm_dividend` and `dividend_yield` added to `monthly_pe` and `pe_stats` schemas; upsert uses COALESCE to preserve `forward_pe`/`forward_12m_eps` on non-estimates runs
- [x] `historic_fundamentals/query.py`: `ttm_dividend` and `dividend_yield` exposed in `get_pe_stats()` and `get_pe_history()`
- [x] `scripts/av_import.py`: shares + dividends added (5 calls/ticker total)
- [x] `scripts/av_update.py`: shares + dividends added (5 calls/ticker total); `--skip-shares` and `--skip-dividends` flags
- [x] `scripts/av_import_shares.py`: standalone backfill for `shares_outstanding`
- [x] `scripts/av_import_dividends.py`: standalone backfill for `dividends`
- [x] `scripts/add_tickers.py`: all-in-one new-ticker onboarding (raw AV + PE + estimates in one pass)

### Phase 2 — Query interface (COMPLETE 2026-05-10)
- [x] `scripts/hf_query.py`: CLI (`--view stats|timeseries|estimates`, `--all`, `--start`, `--end`, `--out`)
- [x] `historic_fundamentals/query.py`: notebook-friendly functions `get_pe_stats()`, `get_pe_history()`, `get_estimates()` — no SQL, self-contained DB connections
- [x] `historic_fundamentals/__init__.py`: clean public API for programmatic access by other apps and agents

### Phase 2.5 — Revenue growth metrics + market cap (COMPLETE 2026-05-11)
- [x] `historic_fundamentals/pe.py`: `_load_av_data()` fetches `total_revenue`; `build_monthly_pe()` adds `ttm_revenue`; `compute_revenue_stats()` computes rev_growth_1yr, rev_cagr_3yr, rev_cagr_5yr from annual data using actual elapsed years
- [x] `historic_fundamentals/estimates.py`: `compute_ntm_revenue()` — sum next 4 quarterly rev_avg, fallback to annual
- [x] `historic_fundamentals/db.py`: `ttm_revenue` in `monthly_pe`; `rev_growth_1yr`, `rev_cagr_3yr`, `rev_cagr_5yr`, `rev_ntm_growth_est`, `market_cap_b` in `pe_stats`; all with ALTER TABLE IF NOT EXISTS migrations; COALESCE on estimate-derived fields
- [x] `historic_fundamentals/db.py`: PE column renames — `lt_median→pe_lt_median`, `p10/p25/p75/p90→pe_p10/p25/p75/p90`, `rolling_5yr_median→pe_rolling_5yr_median` in both tables; idempotent RENAME COLUMN via information_schema check
- [x] `scripts/hf_update.py` + `scripts/add_tickers.py`: `_update_rev_ntm_growth_est()` and `_update_market_cap()` helpers; all snapshot updates run unconditionally (not gated by --skip-estimates)
- [x] `historic_fundamentals/query.py`: `get_pe_stats()` returns all new columns; `get_pe_history()` returns `ttm_revenue`

### Phase 3 — FastAPI router (future, when UI integration needed)
- [ ] `api/hf_router.py`: REST endpoints over the library

---

## Rate limit budget

| Operation                          | AV calls/ticker | Tickers | Total calls | Time at 75/min |
|------------------------------------|-----------------|---------|-------------|----------------|
| av_update.py (statements + shares + dividends) | 5   | 1,400   | 7,000       | ~95 min        |
| hf_import.py / hf_update.py PE phase | 0            | 1,400   | 0           | <5 min (local) |
| hf_update.py estimates             | 1               | 1,400   | 1,400       | ~20 min        |
| add_tickers.py per new ticker      | 6               | varies  | 6×N         | ~12 tickers/min |

Monthly update total: ~95 min (av_update.py) + ~20 min (hf_update.py) = ~115 min for ~1,400 tickers.
