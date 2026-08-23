# Beta Feature Implementation Plan

## Goal

Compute and store rolling 2-year daily OLS betas for all tracked stocks against VTI (Vanguard Total Stock Market ETF) as the market index. Replace the live yfinance beta lookup in the DCF WACC calculation with point-in-time stored betas. Store monthly historical snapshots to support future ML pipeline integration without look-ahead bias.

## Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Market index | VTI | Total market captures small/mid caps over-represented in our universe vs. SPY |
| Regression window | 2-year daily (504 obs) | Matches common screener convention; more responsive than 5Y monthly |
| Returns | Log returns ln(P_t/P_{t-1}) | Handles compounding correctly for OLS |
| History depth | Monthly snapshots, full history | Enables point-in-time beta for ML backtest, avoids look-ahead |
| Storage | `ticker_betas` table in `prices.duckdb` | Co-located with price data; no new database |
| Cron | ~~Separate `update_betas.py`~~ **SUPERSEDED 2026-08-23** — that file was never installed as a cron and has been deleted; the single entry point is `beta.py refresh`, installed Sat 08:00. See README. | Clean separation from price ingestion |
| Min observations | 126 (~6 months) | Return None → DCF falls back to 1.0 for newly-listed tickers |

---

## Phase 0: VTI price backfill

**Prerequisite for all other phases.**

### Files to modify

**`trade_systems/utilities/etf_tickers.py`** — add `"VTI"`:
```python
ETF_TICKERS: frozenset[str] = frozenset({
    "SPY", "IWM", "IWN", "VTI",   # <-- add VTI
    ...
})
```

**`fin_import2/scripts/manage_tickers.py`** — add `"VTI"` to `_ETF_TICKERS` (line 124). Comment says keep in sync with etf_tickers.py.

### VTI backfill (one-time)

VTI inception: 2001-06-27. Run once from `trade_systems/`:

```bash
uv run -c "
import sys; sys.path.insert(0, '.')
from utilities.yfinance_utilities import download_prices
from datetime import date
download_prices(['VTI'], start_date=date(2001, 6, 27), db_path='data/prices.duckdb')
"
```

Adding VTI to `ETF_TICKERS` means `download_prices` routes it to `etf_prices` and `update_prices.py` keeps it current automatically from that point on.

### Verification
```sql
SELECT MIN(date), MAX(date), COUNT(*) FROM etf_prices WHERE ticker = 'VTI';
-- expect: ~2001-07-02, <today>, ~6000+ rows
```

---

## Phase 1: Database schema

Table created lazily inside `_init_beta_table()` in `features/beta/beta.py`. No manual DDL needed.

```sql
CREATE TABLE IF NOT EXISTS ticker_betas (
    ticker        VARCHAR  NOT NULL,
    computed_date DATE     NOT NULL,   -- last trading day of regression window
    window_days   INTEGER  NOT NULL,   -- 504 = 2-year daily
    beta          DOUBLE,
    r_squared     DOUBLE,
    n_obs         INTEGER,
    PRIMARY KEY (ticker, computed_date, window_days)
);
```

---

## Phase 2: Beta computation module

**New file**: `fin_import2/features/beta/beta.py`

### Public API

```python
PRICES_DB: Path           # /home/pedro/projects/trade_systems/data/prices.duckdb
DEFAULT_WINDOW = 504      # trading days
MIN_OBS = 126             # ~6 months minimum

def get_beta(
    ticker: str,
    as_of_date: date | None = None,
    window_days: int = DEFAULT_WINDOW,
    db_path: Path = PRICES_DB,
) -> float | None:
    """Return stored beta. as_of_date=None returns latest row."""

def backfill_betas(
    tickers: list[str] | None = None,
    window_days: int = DEFAULT_WINDOW,
    db_path: Path = PRICES_DB,
) -> int:
    """Compute monthly beta snapshots from inception to today. Returns rows written."""

def refresh_betas(
    window_days: int = DEFAULT_WINDOW,
    db_path: Path = PRICES_DB,
) -> int:
    """Compute current-month beta for all tickers. Called by daily cron."""
```

### Computation logic

1. Load all daily prices for the ticker from `stock_prices` and VTI from `etf_prices`.
2. Inner join on date → aligned daily return series.
3. Compute daily log returns: `r = ln(adj_close_t / adj_close_{t-1})`.
4. For each target `as_of_date`, slice the trailing `window_days` rows.
5. OLS beta: `beta = cov(r_stock, r_vti) / var(r_vti)`.
6. Return `(beta, r_squared, n_obs)` or `None` if `n_obs < MIN_OBS`.

### Monthly snapshot generation (backfill)

- "Month-end dates" = last trading day of each calendar month present in `stock_prices`.
- For each ticker: iterate month-ends from `min(date) + window_days` to today.
- Batch upsert all results in a single transaction.
- Vectorized implementation using pandas: load full price history once, compute returns once, then apply rolling OLS across month-end slices.

### CLI

```bash
# Run from fin_import2/
uv run features/beta/beta.py backfill                  # full historical backfill, all tickers
uv run features/beta/beta.py backfill --ticker AAPL    # single ticker
uv run features/beta/beta.py refresh                   # current month only (cron mode)
uv run features/beta/beta.py show AAPL                 # print latest stored beta
```

---

## Phase 3: Daily cron script

**New file**: `fin_import2/features/beta/update_betas.py`

```
# Add to crontab after update_prices.py (run 30 min after to ensure prices are settled):
30 23 * * 1-5  cd /home/pedro/projects/fin_import2 && uv run features/beta/update_betas.py
```

Logic:
1. Call `refresh_betas()`.
2. Log rows written; log tickers returning None (insufficient history).

---

## Phase 4: DCF integration

**File**: `fin_import2/dcf/wacc.py` — replace `get_beta()` (lines 16–22).

Current:
```python
def get_beta(ticker: str) -> float | None:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return info.get("beta")
    except Exception:
        return None
```

Replacement:
```python
def get_beta(ticker: str) -> float | None:
    from features.beta.beta import get_beta as _get_beta
    return _get_beta(ticker)
```

No other changes. The existing fallback `(get_beta(ticker) or 1.0)` at line 71 is preserved. The `beta_override` path is untouched.

---

## Files changed

| File | Type | Change |
|---|---|---|
| `trade_systems/utilities/etf_tickers.py` | Modify | Add `"VTI"` |
| `fin_import2/scripts/manage_tickers.py` | Modify | Add `"VTI"` to `_ETF_TICKERS` |
| `fin_import2/features/beta/beta.py` | New | Full module |
| `fin_import2/features/beta/update_betas.py` | New | Cron wrapper |
| `fin_import2/dcf/wacc.py` | Modify | Replace `get_beta()` |

---

## Implementation order

```
Phase 0  →  Phase 1 (implicit in Phase 2)  →  Phase 2  →  Phase 3  →  Phase 4
```

Phases 0–3 can be fully tested before touching DCF (Phase 4).

---

## Testing plan

| Test | How |
|---|---|
| VTI in etf_prices | `SELECT COUNT(*) FROM etf_prices WHERE ticker = 'VTI'` |
| Beta backfill for AAPL | `uv run features/beta/beta.py show AAPL` — compare to yfinance value (~1.2) |
| Monthly snapshots exist | `SELECT computed_date, beta FROM ticker_betas WHERE ticker='AAPL' ORDER BY computed_date DESC LIMIT 6` |
| get_beta returns float | `python -c "from features.beta.beta import get_beta; print(get_beta('AAPL'))"` |
| DCF still produces result | Run DCF for any ticker; verify WACC output unchanged in magnitude |
| DCF fallback on new ticker | Mock a ticker with no beta rows; verify wacc uses 1.0 |

---

## Out of scope (future)

- Industry-median beta fallback for tickers with < MIN_OBS (new IPOs)
- Replacing AV beta in `company_overview` table for ML model features
- Additional windows (5Y monthly) — table schema supports `window_days` column for future addition
