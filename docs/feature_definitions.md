# Feature Definitions

All features listed here are computed in `historic_fundamentals/pe.py` and stored in the `monthly_pe` table in `data/historic_fundamentals.duckdb`. Each row in `monthly_pe` represents one ticker on one month-end date. Features are point-in-time safe: fundamental data is gated at `fiscal_period_end + 60 days` (quarterly) or `fiscal_period_end + 90 days` (annual) before it is used in any computation.

The authoritative signal-direction reference is the comment block in `pe.py` beginning at line 440 ("Feature direction reference").

---

## Valuation

Price-based multiples. All raw multiples are computed as market price divided by a fundamental per-share or aggregate metric. Lower values mean the stock is cheaper relative to fundamentals.

| Feature | Formula | Signal direction | Data source |
|---|---|---|---|
| `pe_ratio` | price / TTM EPS | Lower is better | income_statements, shares_outstanding |
| `pfcf_ratio` | price / (TTM FCF / shares) | Lower is better | cash_flow_statements, shares_outstanding |
| `ev_ebitda` | EV / TTM EBITDA | Lower is better | income_statements, balance_sheets, shares_outstanding, prices |
| `ps_ratio` | market_cap / TTM revenue | Lower is better | income_statements, shares_outstanding, prices |
| `pbv` | price / (total_shareholder_equity / shares) | Lower is better | balance_sheets, shares_outstanding |
| `ptbv` | price / ((equity - intangibles - goodwill) / shares) | Lower is better | balance_sheets, shares_outstanding |

Notes:
- `pe_ratio` is NULL when TTM EPS <= 0.
- `pfcf_ratio` is NULL when TTM FCF <= 0 (FCF per share must be positive to form a meaningful multiple; negative FCF is still captured via `fcf_yield`).
- `ev_ebitda` is NULL when TTM EBITDA <= 0 or balance sheet data is unavailable.
- `pbv` is NULL when total_shareholder_equity <= 0.
- `ptbv` is NULL when tangible book value <= 0.
- EV = price * shares + total_debt - cash. total_debt = long_term_debt_noncurrent + short_term_debt + current_long_term_debt.

---

## Yields

Yield metrics are the reciprocal of the corresponding multiples, expressed as a rate. They remain defined even when the underlying multiple would be infinite or negative.

| Feature | Formula | Signal direction | Data source |
|---|---|---|---|
| `earnings_yield` | TTM EPS / price | Higher is better | income_statements, shares_outstanding, prices |
| `fcf_yield` | (TTM FCF / shares) / price | Higher is better | cash_flow_statements, shares_outstanding, prices |
| `ebitda_ev_yield` | TTM EBITDA / EV | Higher is better | income_statements, balance_sheets, shares_outstanding, prices |

Notes:
- `earnings_yield` is always defined when TTM EPS is computable (including negative EPS years), avoiding the blow-up problem of P/E when EPS is near zero.
- `fcf_yield` is always defined when TTM FCF is computable, including negative FCF (negative yield signals cash burn).
- `ebitda_ev_yield` is always defined when EBITDA and EV are computable, including negative EBITDA.

Rolling averages of each yield are also stored:

| Feature | Formula | Notes |
|---|---|---|
| `earnings_yield_3y_avg` | 36-month rolling mean of `earnings_yield` | min 24 months |
| `earnings_yield_5y_avg` | 60-month rolling mean of `earnings_yield` | min 36 months |
| `fcf_yield_3y_avg` | 36-month rolling mean of `fcf_yield` | min 24 months |
| `fcf_yield_5y_avg` | 60-month rolling mean of `fcf_yield` | min 36 months |
| `ebitda_ev_yield_3y_avg` | 36-month rolling mean of `ebitda_ev_yield` | min 24 months |
| `ebitda_ev_yield_5y_avg` | 60-month rolling mean of `ebitda_ev_yield` | min 36 months |

---

## Normalized Multiples

CAPE-style multiples that substitute the current fundamental with a multi-year average. They reduce cyclical distortion relative to the raw multiple.

| Feature | Formula | Signal direction | Data source |
|---|---|---|---|
| `normalized_pe_5y` | price / avg(TTM EPS over 60 months) | Lower is better | income_statements, shares_outstanding, prices |
| `normalized_pfcf_5y` | price / avg(TTM FCF per share over 60 months) | Lower is better | cash_flow_statements, shares_outstanding, prices |
| `normalized_evebitda_5y` | EV / avg(TTM EBITDA over 60 months) | Lower is better | income_statements, balance_sheets, shares_outstanding, prices |
| `normalized_ps_5y` | market_cap / avg(TTM revenue over 60 months) | Lower is better | income_statements, shares_outstanding, prices |

Notes:
- All normalized multiples require a minimum of 36 months of data; NULL before that.
- Negative averages in the denominator produce NULL rather than a misleading negative multiple.
- These features include loss years in the average, unlike rolling-median approaches that exclude negative periods.

---

## Quality

Return-on-capital metrics. Higher values indicate a more profitable and efficiently run business.

| Feature | Formula | Signal direction | Data source |
|---|---|---|---|
| `roa` | TTM net_income / total_assets | Higher is better | income_statements, balance_sheets |
| `roe` | TTM net_income / total_shareholder_equity | Higher is better | income_statements, balance_sheets |
| `roic` | TTM NOPAT / invested_capital | Higher is better | income_statements, balance_sheets |

Notes:
- `roe` is NULL when total_shareholder_equity <= 0.
- `roic` uses NOPAT = TTM EBIT * (1 - effective_tax_rate), where effective_tax_rate is clamped to [0, 0.5] and defaults to 0.21 when income_before_tax is not positive.
- invested_capital = total_shareholder_equity + total_debt - cash.
- `roic` is NULL when invested_capital <= 0.

Rolling 5-year medians are stored alongside each quality metric: `roa_rolling_5yr_median`, `roe_rolling_5yr_median`, `roic_rolling_5yr_median`.

---

## Margins

TTM profitability margins. All margins are computed from TTM fundamental sums at each month-end.

| Feature | Formula | Signal direction | Data source |
|---|---|---|---|
| `ttm_gross_margin` | TTM gross_profit / TTM revenue | Higher is better | income_statements |
| `ttm_operating_margin` | TTM operating_income / TTM revenue | Higher is better | income_statements |
| `ttm_fcf_margin` | TTM FCF / TTM revenue | Higher is better | cash_flow_statements, income_statements |

Notes:
- All margin features are NULL when TTM revenue is zero or not available.
- FCF margin can be negative when FCF is negative; it is still defined.

---

## Margin Stability

Rolling statistics that capture margin trend and consistency over time. Computed from the monthly timeseries of the corresponding TTM margin.

| Feature | Formula | Signal direction | Data source |
|---|---|---|---|
| `gross_margin_5y_median` | 60-month rolling median of `ttm_gross_margin` | Higher is better | derived from `ttm_gross_margin` |
| `gross_margin_slope_5y` | OLS slope of `ttm_gross_margin` over 60 months (min 36) | Higher is better (improving trend) | derived from `ttm_gross_margin` |
| `operating_margin_5y_median` | 60-month rolling median of `ttm_operating_margin` | Higher is better | derived from `ttm_operating_margin` |
| `operating_margin_slope_5y` | OLS slope of `ttm_operating_margin` over 60 months (min 36) | Higher is better (improving trend) | derived from `ttm_operating_margin` |
| `operating_margin_change_3y` | `ttm_operating_margin` minus value 36 months ago | Higher is better (improved margin) | derived from `ttm_operating_margin` |
| `fcf_margin_5y_median` | 60-month rolling median of `ttm_fcf_margin` | Higher is better | derived from `ttm_fcf_margin` |
| `fcf_margin_change_3y` | `ttm_fcf_margin` minus value 36 months ago | Higher is better (improved margin) | derived from `ttm_fcf_margin` |
| `roa_stability_5y` | 60-month rolling std of `roa` (min 36) | **Lower is better** | derived from `roa` |

**Important note on `roa_stability_5y`:** This feature is `std(ROA)` over 5 years. A higher value means ROA is more volatile — which is worse. Despite the word "stability" in the name, the encoding is inverted relative to intuition: `higher = less stable = worse`. When interpreting SHAP values or building composite scores, this feature must be sign-flipped (i.e., treated as a "lower is better" factor).

Slope units are change-per-month (not per year). NaN values within the rolling window are excluded from the OLS regression so sparse fundamental data does not zero out the estimate.

---

## Leverage

Debt burden and debt-service capacity. Lower debt and higher coverage are better.

| Feature | Formula | Signal direction | Data source |
|---|---|---|---|
| `debt_to_ebitda` | total_debt / TTM EBITDA | Lower is better | balance_sheets, income_statements |
| `interest_coverage` | TTM EBIT / abs(TTM interest_expense) | Higher is better | income_statements |

Notes:
- `debt_to_ebitda` is NULL when TTM EBITDA <= 0.
- `interest_coverage` is NULL when interest_expense is zero or NULL (no debt-service requirement).
- Alpha Vantage reports `interest_expense` as a negative number (outflow convention). The absolute value is used in the denominator.
- total_debt = long_term_debt_noncurrent + short_term_debt + current_long_term_debt.

---

## Feature Availability

Every row in `monthly_pe` carries a `feature_available_date` column. This is the maximum `feature_available_date` across all fundamental data used to compute that row. It is guaranteed to be <= `month_end_date` by construction (the lag filter ensures only data whose availability date is <= month_end_date enters any computation).

The live scoring script filters to rows where `feature_available_date <= today`, preventing stale data from appearing in current rankings.

---

## Rolling Median Periods

Features with "5yr" or "rolling" in their names use a 60-month window with a minimum of 36 periods. They are NULL for the first 35 months of a ticker's history.

Features with "3y" in their names use a 36-month window with a minimum of 24 periods.
