# Point-in-Time Data Audit Report

Phase 1 — Fundamentals Alpha Action Plan  
Date: 2026-05-16

---

## 1. Prediction date definition

The model uses `month_end_date` as the prediction date (T). This is the last calendar day of the month on which stocks are scored or trained. All feature data must be available by T (i.e., `feature_available_date <= T`). Forward returns are measured from T forward — the target period starts at T and is not a source of leakage.

---

## 2. Feature availability gate: before and after fix

### Before fix

Every data source in `build_monthly_pe()` used:

```python
df[df["fiscal_date_ending"] <= month_end]
```

This is the naive gate. It assumes that data from a quarter ending on `fiscal_date_ending` is immediately available on `fiscal_date_ending`, with no filing delay. In practice, quarterly reports are filed 45–75 days after period-end. The naive gate allowed data from a quarter ending, for example, on 2024-01-31 to be used at the prediction date of 2024-02-01 — before any 10-Q would have been filed.

### After fix (Phase 1)

The availability gate now applies conservative reporting lags:

```python
q_pit = q[q["fiscal_date_ending"] + timedelta(days=60) <= month_end]
a_pit = a[a["fiscal_date_ending"] + timedelta(days=90) <= month_end]
```

These filtered DataFrames (`q_pit`, `a_pit`, `cfq_pit`, `cfa_pit`) are used for all feature computation within the monthly loop. No helper function receives unfiltered data.

A helper function makes the lag policy explicit:

```python
def _feature_available_date(fiscal_date_ending: date, period_type: str) -> date:
    if period_type == "annual":
        return fiscal_date_ending + timedelta(days=90)
    return fiscal_date_ending + timedelta(days=60)
```

---

## 3. Lag policy: quarterly +60d, annual +90d

| Period type | Lag applied | Rationale |
|---|---|---|
| Quarterly (income, balance, cashflow) | +60 days | SEC 10-Q filing deadline is 45 days (large accelerated filers) to 45 days (accelerated) or 45 days after quarter-end. 60-day lag is conservative. |
| Annual (income, balance, cashflow) | +90 days | SEC 10-K filing deadline is 60–90 days after fiscal year-end. 90-day lag covers all filer categories. |

These are conservative fallbacks. They may exclude some data that was actually available earlier. No reporting lag is applied to price data (prices are always point-in-time safe at month-end) or dividend data (ex-dividend date is the availability date).

---

## 4. What is NOT available

- No SEC filing date (`filed`) column exists in the database.
- No SEC accepted date (`acceptanceDatetime`) column exists.
- No EDGAR submission timestamp is stored.
- The `av_financials.duckdb` database contains only `fiscal_date_ending` as a timing reference.

The conservative lag policy (quarterly +60d, annual +90d) is the only safeguard available given this limitation. If SEC EDGAR filing dates are added to the database in the future, they should replace the lag-based approach.

---

## 5. Target return construction and why it is safe

The notebook's `compute_forward_returns()` function (Cell 3) computes:

```python
ret_N = price[T + N months] / price[T] - 1
```

- `T` = `month_end_date` (the prediction date)
- `price[T]` = the adjusted close price on the last trading day of month T
- The target period begins at T, not after T

This construction is safe for the following reason: the model scores stocks at T using only data that was available as of T (`feature_available_date <= T`). The return is then measured from that same T forward. The score does not use future prices to compute features; the future price only appears in the target label, which is what the model learns to predict.

The critical constraint is:

```
feature_available_date <= month_end_date (prediction date) — enforced by lag logic
target_return_start = month_end_date — not a leakage issue
```

Using `price[T]` in the target is equivalent to a "buy at month-end close" assumption, which is standard in monthly factor models.

---

## 6. Data sources audited

| Source | Data loaded from | Period type | Lag applied | Gate (after fix) |
|---|---|---|---|---|
| Income statements | `av_financials.duckdb` — `income_statements` | quarterly | +60d | `fiscal_date_ending + 60d <= month_end` |
| Balance sheets | `av_financials.duckdb` — `balance_sheets` | quarterly | +60d | `fiscal_date_ending + 60d <= month_end` |
| Cash flow statements | `av_financials.duckdb` — `cash_flow_statements` | quarterly | +60d | `fiscal_date_ending + 60d <= month_end` |
| Income statements (annual) | `av_financials.duckdb` — `income_statements` | annual | +90d | `fiscal_date_ending + 90d <= month_end` |
| Balance sheets (annual) | `av_financials.duckdb` — `balance_sheets` | annual | +90d | `fiscal_date_ending + 90d <= month_end` |
| Cash flow statements (annual) | `av_financials.duckdb` — `cash_flow_statements` | annual | +90d | `fiscal_date_ending + 90d <= month_end` |
| Shares outstanding | `av_financials.duckdb` — `shares_outstanding` | daily timeseries | none needed | `date <= month_end` (no filing lag for share counts) |
| Dividends | `av_financials.duckdb` — `dividends` | event-based | none needed | `ex_dividend_date <= month_end` (ex-date is the availability date) |
| Prices | `prices.duckdb` — `stock_prices` | daily | none needed | last trading day of month |

---

## 7. feature_available_date column

A new `feature_available_date DATE` column was added to the `monthly_pe` table schema and to the `upsert_monthly_pe()` function in `db.py`.

For each row, `feature_available_date` is set to the maximum `_feature_available_date()` across all fundamental data sources used in that row. This is the earliest date at which all the data used for that row's features was conservatively assumed to be available.

By construction, `feature_available_date <= month_end_date` for every row (the lag filter guarantees this).

---

## 8. Timing violations

Timing violations are logged at WARNING level in `build_monthly_pe()`. A violation is defined as a fiscal period that would have been included by the naive gate but is excluded by the lag gate. After the fix is applied, no violations should appear in practice — the warning fires only if a caller bypasses the lag logic (e.g., passes pre-filtered data with a shorter lag).

Warning format:

```
PIT violation prevented: quarterly fiscal_date_ending=YYYY-MM-DD
would be used at month_end=YYYY-MM-DD without lag (feature_available_date=YYYY-MM-DD)
```

---

## 9. Known limitations

1. **Sector assignments are point-in-time in name only.** The `company_overview` table stores one sector/industry per ticker (the most recent). When sector is joined into the model, the current sector classification is applied to all historical months. A company that changed sectors will appear in its current sector for all historical periods. This is standard factor-model convention but technically applies future sector information to past data.

2. **No SEC filing dates.** The +60d/+90d lags are conservative but approximate. Some companies file earlier (reducing lag risk) and some may reclassify data retroactively. The lags prevent the worst-case leakage but may slightly reduce the number of usable training observations for months immediately following quarter-end.

3. **Shares outstanding timeseries.** The `shares_outstanding` table uses `date` (the report date) directly, without a filing lag. This is appropriate because share counts are updated continuously (via prospectuses, 8-K filings, etc.) and the date column reflects when the count was known. This is consistent with how prices are handled.

4. **No delisting flag.** Stocks that were delisted or acquired are not explicitly flagged in the database. Survivorship bias is limited by the fact that the database includes all tickers for which Alpha Vantage data was fetched, but tickers that were never imported will be missing.

5. **Restatements.** Alpha Vantage data reflects the most recently available figures. If a company restated historical financials, the original reported figures (which were available at the time) are not preserved. This is a data limitation of all provider-sourced fundamental databases.

---

## 10. Timing violations: none expected after fix

After Phase 1, the lag filter in `build_monthly_pe()` ensures that no fundamental data with `feature_available_date > month_end_date` is used. The warning log (Task 3) serves as a safety net for future regressions. No violations should appear in normal operation.

---

## 11. Files modified

| File | Change |
|---|---|
| `historic_fundamentals/pe.py` | Added `_feature_available_date()`, `_LAG_QUARTERLY`, `_LAG_ANNUAL`; added `q_pit`/`a_pit`/`cfq_pit`/`cfa_pit` lag filters in `build_monthly_pe()`; added violation warning log; added `feature_available_date` to output DataFrame |
| `historic_fundamentals/db.py` | Added `feature_available_date DATE` column to `monthly_pe` schema and `upsert_monthly_pe()` |
| `tests/test_point_in_time.py` | New: 10 tests for `_feature_available_date()` and lag filter behavior |
| `tests/test_features.py` | Updated `_prices()` default date from `2024-01-31` to `2024-03-31` so that quarterly data ending `2023-12-31` satisfies the lag constraint |
| `docs/pit_audit_report.md` | This document |
