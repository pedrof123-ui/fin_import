# PLAN: Ticker Universe Expansion — IWM (Russell 2000) + MDY (S&P MidCap 400)

## Overall status — ALL PHASES COMPLETE (2026-06-02)

| Phase | Status |
|---|---|
| 0 — Constituent discovery | ✓ COMPLETE |
| 1 — MDY ETF registration | ✓ COMPLETE |
| 2 — AV pipeline backfill | ✓ COMPLETE |
| 3 — FMP pipeline + key metrics | ✓ COMPLETE |
| 4 — Test suite validation | ✓ COMPLETE |
| 5 — Alpha model integration | ✓ COMPLETE |

## Goal

Expand the investable universe by onboarding all IWM (Russell 2000) and MDY (S&P MidCap 400)
constituents, minus ADRs, into every supporting database. Actual net-new tickers: 1,330.

## State before → after

| Database | Before | After |
|---|---|---|
| `av_financials.duckdb` | 1,436 | **2,750** |
| `historic_fundamentals / pe_stats` | ~1,436 | **2,643** |
| `fmp_financials.duckdb` | 1,445 | **2,758** |
| `fmp_fundamentals / key_metrics` | 1,469 | **2,798** |
| `prices.duckdb / stock_prices` | 1,485 | **2,802** |
| `prices.duckdb / etf_prices` | 25 | **26** (MDY added) |
| Alpha model scored universe | ~1,326 | **1,841** |

## Phase 0 results (2026-06-02) — COMPLETE

| Constituent set | Valid tickers |
|---|---|
| IWM (Russell 2000) | 1,769 |
| MDY (S&P MidCap 400) | 393 |
| Union | 2,091 |
| IWM ∩ MDY overlap | 71 |
| Already in av_financials | 761 |
| **Net-new to add** | **1,330** |

Breakdown of net-new: IWM-only 1,255 · MDY-only 69 · in both 6

Files written: `data/new_tickers.csv` (1,330), `data/iwm_all_tickers.csv` (1,769), `data/mdy_all_tickers.csv` (393)

## Databases written per pipeline

**AV pipeline** (`fin_import2/scripts/manage_tickers.py add`):
- `prices.duckdb / stock_prices` — daily price history via AV TIME_SERIES_DAILY_ADJUSTED
- `av_financials.duckdb` — income/balance/cashflow statements, shares, dividends, company_overview
- `historic_fundamentals.duckdb` — monthly_pe timeseries, pe_stats, earnings_estimates

**FMP pipeline** (`trade_systems/utilities/fmp/fmp_manage_tickers.py add`):
- `prices.duckdb / stock_prices` — daily price history via FMP (extends back to 1980s for many stocks)
- `fmp_financials.duckdb` — income/balance/cashflow statements, dividends, company_profile, earnings_estimates
- `fmp_fundamentals.duckdb` — key_metrics (47 pre-computed ratios)

## Rate limits

| Pipeline | Calls/min | Calls/ticker | Tickers/min | Est. time for 700 tickers |
|---|---|---|---|---|
| AV | 75 | 8 | ~9.4 | ~75 min |
| FMP | 750 | 11 | ~68 | ~10 min |

## Decision log

- **Constituent source**: FMP `etfAndMutualFunds.holdings` (richer data, already used in trade_systems)
- **ADR filtering**: rely on existing auto-rejection in both pipelines (non-USD currency check)
- **Alpha model universe filter**: leave `min_market_cap: $1B` unchanged; ingest all net-new tickers
- **FMP backfill method**: `fmp_manage_tickers.py add --csv` per-ticker (consistent with existing workflow)
- **Testing**: count + schema validation after each phase

---

## Phase 0 — Constituent discovery and deduplication ✓ COMPLETE

**Goal**: produce a clean CSV of net-new tickers to feed into subsequent phases.

### 0.1 Fetch IWM and MDY holdings via AV MCP ETF_PROFILE ✓

Note: FMP `etfAndMutualFunds.holdings` required Ultimate plan (not available). Used AV MCP
`ETF_PROFILE` instead — returned full constituent lists with symbol/description/weight.

### 0.2 Combine and deduplicate ✓

- IWM: 1,769 valid tickers · MDY: 393 · union: 2,091 · overlap: 71
- Already in av_financials: 761 · **Net-new: 1,330**
- Breakdown: IWM-only 1,255 · MDY-only 69 · in both 6

### 0.3 Validation ✓

- 0 invalid-format tickers
- Ticker length distribution normal (mostly 4-letter)
- All 1,330 confirmed absent from existing `companies` table

**Files written**: `data/new_tickers.csv` (1,330), `data/iwm_all_tickers.csv` (1,769), `data/mdy_all_tickers.csv` (393)

---

## Phase 1 — Add MDY to ETF_TICKERS (benchmark ETF onboarding) ✓ COMPLETE

**Goal**: register MDY as an ETF benchmark so it routes to `etf_prices`, then backfill its price
history. This is for the ETF wrapper itself, not the constituents.

### 1.1 Update ETF_TICKERS in all three locations ✓

`"MDY"` added to `# Broad market` group in all three files (in sync):
- `trade_systems/utilities/etf_tickers.py`
- `trade_systems/utilities/fmp/fmp_manage_tickers.py`
- `fin_import2/scripts/manage_tickers.py`

**Bug fixed**: discovered and fixed a DuckDB read/write connection conflict in `manage_tickers.py`
where a pre-opened `read_only=True` prices connection in `cmd_add` blocked `_backfill_prices`
from opening the same file for writing. Fixed by moving the read-only connection inside
`_add_ticker`, opened after the backfill step completes. Affects all future bulk imports.

### 1.2 Backfill MDY price history ✓

```bash
uv run scripts/manage_tickers.py add MDY --skip-estimates
```

### 1.3 Validation ✓

- MDY: **6,685 rows** in `etf_prices` (1999-11-01 → 2026-06-01)
- MDY absent from `stock_prices` (correct routing confirmed)

---

## Phase 2 — AV pipeline backfill (fin_import2) ✓ COMPLETE

**Goal**: onboard all net-new tickers into `av_financials.duckdb`, `historic_fundamentals.duckdb`,
and `prices.duckdb / stock_prices` via the existing `manage_tickers.py add` pipeline.

### 2.1 Dry-run ✓

Confirmed 1,330 tickers and correct DB paths.

### 2.2 Run the full AV pipeline ✓

```bash
uv run scripts/manage_tickers.py add --csv data/new_tickers.csv
```

Actual runtime: **~153 minutes** (1,330 tickers × 8 calls ÷ 75/min).

### 2.3 Results

| Outcome | Count | Tickers |
|---|---|---|
| Succeeded | 1,313 | — |
| ADR rejected (non-USD) | 4 | DRUG (CAD), ELVR (AUD), STNE (BRL), ZGN (EUR) |
| Not found in AV (invalid API call) | 13 | AHH, AMBC, ASGN, ATGE, ATUS, AXL, COMM, EXPI, GMRE, KAR, KFS, MODG, OMI |

The 13 "not found" tickers are likely recently delisted or renamed; AV no longer serves them.
FMP (Phase 3) successfully imported all 13.

**DB counts after Phase 2:**

| Database | Tickers |
|---|---|
| `av_financials.duckdb` | 2,750 (was 1,436) |
| `historic_fundamentals / pe_stats` | 2,643 |
| `stock_prices` | 2,789 (was 1,485) |

**Exit criteria met**: 98.7% of net-new tickers (1,313/1,330) imported. Spot-check passed (60–100+ income rows, populated sectors).

---

## Phase 3 — FMP pipeline backfill (trade_systems) ✓ COMPLETE

**Goal**: onboard net-new tickers into `fmp_financials.duckdb`, `fmp_fundamentals.duckdb`,
and extend `stock_prices` history back to the 1980s via FMP.

### 3.1–3.2 FMP pipeline ✓

```bash
cd /home/pedro/projects/trade_systems
uv run utilities/fmp/fmp_manage_tickers.py add --csv /home/pedro/projects/fin_import2/data/new_tickers.csv
```

Actual runtime: **~80 minutes**. 1,326 succeeded, 4 failed (same ADRs as Phase 2).
The 13 AV "not found" tickers all succeeded in FMP — FMP retains data for delisted/renamed tickers.

### 3.3 Key metrics backfill ✓

```bash
uv run utilities/fmp/key_metrics_backfill.py
```

105,427 new rows added. DB summary: 2,798 symbols, 295,796 total rows, earliest 1983-09-30.

### 3.4 Results

**DB counts after Phase 3:**

| Database | Tickers |
|---|---|
| `fmp_financials.duckdb` | 2,758 (was 1,445) |
| `fmp_fundamentals / key_metrics` | 2,798 (was 1,469) |
| `stock_prices` | 2,802 (extended to 1983 for many tickers) |

Price history spot-check: MPAA and USNA back to 1999-11-01; ICHR from 2016-12-09 (newer IPO).

**Exit criteria met**: 99.7% of net-new tickers (1,326/1,330) imported into FMP.

---

## Phase 4 — Full test suite validation ✓ COMPLETE

**Goal**: confirm no regressions in existing functionality.

### 4.1 Full test suite ✓

- `trade_systems`: **25/25 passed**
- `fin_import2`: **23/24 passed**, 1 skipped (`test_fundamentals_not_null` — uses legacy XBRL DB, unrelated to this expansion)
- Log: `docs/test_ticker_expansion.log`

### 4.2 Alpha model smoke test ✓

`uv run pytest tests/test_features.py -v` — 23 passed, 1 skipped. Zero failures.

### 4.3 Spot-check (10 new tickers — 5 IWM, 5 MDY) ✓

| Ticker | Source | Inc rows | Bal rows | CF rows | Sector | Price start | FMP rows |
|---|---|---|---|---|---|---|---|
| CAC | IWM | 101 | 101 | 101 | FINANCIAL SERVICES | 1999-11-01 | 150 |
| ALEC | IWM | 48 | 48 | 48 | HEALTHCARE | 2019-02-07 | 47 |
| HWBK | IWM | 101 | 101 | 101 | FINANCIAL SERVICES | 1999-11-01 | 143 |
| GMGI | IWM | 0 | 0 | 0 | N/A | 2009-10-30 | 89 |
| FLYW | IWM | 32 | 32 | 32 | TECHNOLOGY | 2021-05-26 | 32 |
| CRBG | MDY | 30 | 30 | 30 | FINANCIAL SERVICES | 2022-09-15 | 30 |
| CHWY | MDY | 43 | 43 | 43 | CONSUMER CYCLICAL | 2019-06-14 | 42 |
| VVV | MDY | 60 | 60 | 60 | CONSUMER CYCLICAL | 2016-09-23 | 59 |
| BSY | MDY | 40 | 40 | 40 | TECHNOLOGY | 2020-09-23 | 38 |
| PLNT | MDY | 67 | 64 | 67 | CONSUMER CYCLICAL | 2015-08-06 | 63 |

Note: GMGI has 0 AV rows (AV returned no financial data) but 89 FMP rows — acceptable.

**Exit criteria met**: 9/10 spot-check tickers have full statement coverage in both pipelines.

---

## Phase 5 — Alpha model strategy integration ✓ COMPLETE

**Goal**: confirm the fundamentals alpha model runs end-to-end with the expanded universe
and generate updated live scores.

### 5.1 Universe check ✓

- Total tickers with `pe_stats`: 2,631
- Tickers passing `$1B` market cap filter: 1,841 (was ~1,326)
- **Net-new tickers passing filter: 515** (39% of 1,330 — expected, Russell 2000 is mostly sub-$1B)

### 5.2 Live scoring ✓

```bash
uv run scripts/score_live.py
```

Ran clean with no errors. Output: `docs/live_scores_20260602_rf_vw_gr_top_n_25.csv` (25 rows).
Top-25 portfolio generated successfully with expanded universe.

### 5.3 Documentation ✓

Plan updated with final counts. `PLAN_TICKER_EXPANSION.md` is the authoritative record.

**Exit criteria met**: `score_live.py` ran without errors, universe expanded from ~1,326 to 1,841 scored tickers.

---

## Phased timeline estimate

| Phase | Task | Estimated time |
|---|---|---|
| 0 | Constituent discovery + CSV | COMPLETE — 1,330 net-new tickers |
| 1 | Add MDY to ETF_TICKERS + price backfill | COMPLETE — 6,685 MDY price rows in etf_prices |
| 2 | AV pipeline (manage_tickers.py add, 1,330 tickers) | COMPLETE — 1,313 ok, 17 failed (13 AV not found, 4 ADR) |
| 3 | FMP pipeline (fmp_manage_tickers.py add + key_metrics) | COMPLETE — 1,326 ok, 4 failed (same ADRs) |
| 4 | Test suite + validation | COMPLETE — 25/25 + 23/24 passed, 0 regressions |
| 5 | Alpha model scoring + docs | COMPLETE — score_live.py ran clean, 515 new tickers in universe |

Total wall-clock: **~3.5 hours** (most of which is unattended pipeline runs).

Phase 2 revised: 1,330 tickers × 8 AV calls = 10,640 calls ÷ 75/min = ~142 min.
Phase 3 revised: 1,330 tickers × 11 FMP calls = 14,630 calls ÷ 750/min = ~20 min.

---

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| AV API returns empty data for small-cap tickers | Low–Medium | Empty responses log a warning and skip; ticker does not enter `companies` table |
| ADR count higher than expected (many foreign names in Russell 2000) | Medium | Auto-rejection handles this; log review shows rejected tickers |
| FMP price history diverges from AV for overlapping dates | Low | Both pipelines use upsert; FMP runs after AV so FMP values win for overlapping dates |
| `fmp_manage_tickers.py` ETF routing for MDY (before Phase 1) | None | Phase 1 is a prerequisite — MDY added to `_ETF_TICKERS` before any import |
| Historic_fundamentals PE computation fails for low-data tickers | Low | `process_ticker` returns empty DataFrame; logged as warning; does not fail the run |
| Alpha model notebook crashes on expanded universe (memory) | Low | Score via `score_live.py` first (production path); notebook is exploratory |
| Rate limit exceeded on AV (>75 calls/min) | None | Built-in `RateLimiter` enforces 75/min; do not run parallel `manage_tickers.py` instances |

---

## File deliverables

| Phase | Files created / modified |
|---|---|
| 0 | `data/new_tickers.csv`, `data/iwm_all_tickers.csv`, `data/mdy_all_tickers.csv` |
| 1 | `trade_systems/utilities/etf_tickers.py`, `trade_systems/utilities/fmp/fmp_manage_tickers.py`, `fin_import2/scripts/manage_tickers.py` |
| 2 | DB writes to `av_financials.duckdb`, `historic_fundamentals.duckdb`, `prices.duckdb` |
| 3 | DB writes to `fmp_financials.duckdb`, `fmp_fundamentals.duckdb`, `prices.duckdb` (extended history) |
| 4 | `docs/test_ticker_expansion.log` |
| 5 | Updated `STATUS.md` with expansion summary |
