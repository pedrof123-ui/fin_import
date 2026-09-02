# Debt Maturity Coverage Check (PLAN_DEBT_MATURITY.md Phase 0)

Sample: 90 tickers (81 fetched successfully, 9 errors).

- Overall hit rate (either concept tagged): 66.7%
- Both concepts tagged: 19.8% (16/81)
- Maturities ladder only (`ScheduleOfMaturitiesOfLongTermDebtTableTextBlock`, no per-tranche
  coupon): 30.9% (25/81)
- Per-tranche detail only (`ScheduleOfDebtInstrumentsTextBlock`, no aggregate ladder): 16.0% (13/81)
- Neither concept: 33.3% (27/81)

**The two concepts answer different questions and should not be conflated.** The maturities
ladder (present in 50.6% of the sample, alone or combined) gives principal-by-year, which is
enough for `weighted_avg_years_to_maturity` but carries no coupon rate. The per-tranche detail
(present in 35.8% of the sample, alone or combined) is the one that actually carries coupon
rates and is required for `weighted_avg_coupon_near_term` / `weighted_avg_coupon_long_dated` —
the numbers the WACC split (Phase 3) actually needs. So the coverage number that matters for
this plan's core deliverable is **35.8%, not the 66.7% headline** — roughly one in three tickers,
not two in three.

By concept, coverage is reasonably spread across market-cap deciles (12.5%-57%, no strong
monotonic size trend) but concentrated by sector: Real Estate (75%), Energy (71%), Industrials
(57%) tag per-tranche detail far more often than Technology (18%), Healthcare (18%), Financial
Services (14%), Basic Materials (17%) — sectors that finance mostly through revolvers, retained
earnings, or (for financials) deposits/repo rather than public bond tranches.

## By market-cap decile (0=smallest, 9=largest)

| decile | hit rate | n |
|---|---|---|
| 0 | 44.4% | 9 |
| 1 | 55.6% | 9 |
| 2 | 87.5% | 8 |
| 3 | 71.4% | 7 |
| 4 | 37.5% | 8 |
| 5 | 50.0% | 8 |
| 6 | 62.5% | 8 |
| 7 | 87.5% | 8 |
| 8 | 100.0% | 7 |
| 9 | 77.8% | 9 |

## By sector

| sector | hit rate | n |
|---|---|---|
| UTILITIES | 100.0% | 2 |
| REAL ESTATE | 100.0% | 4 |
| INDUSTRIALS | 92.9% | 14 |
| ENERGY | 85.7% | 7 |
| CONSUMER CYCLICAL | 83.3% | 6 |
| CONSUMER DEFENSIVE | 80.0% | 5 |
| FINANCIAL SERVICES | 71.4% | 7 |
| COMMUNICATION SERVICES | 50.0% | 2 |
| TECHNOLOGY | 45.5% | 11 |
| HEALTHCARE | 41.2% | 17 |
| BASIC MATERIALS | 33.3% | 6 |

## Errors

- PFBC: no 10-K on file
- PEGA: The read operation timed out
- BRUN: no 10-K on file
- SFL: no 10-K on file
- CGAU: no 10-K on file
- BTDR: no 10-K on file
- AG: no 10-K on file
- GFI: no 10-K on file
- SQM: no 10-K on file

## Go/no-go

Pending user decision — see conversation. Options considered: (a) full-universe build scoped to
the ~36% with per-tranche coupon detail, everyone else falls back to today's embedded-rate WACC
(matches the plan's existing null-safe design, no scope change needed); (b) also extract
maturities-ladder-only tickers (another ~31%) for `weighted_avg_years_to_maturity` alone, useful
for a future maturity-profile feature but not for the WACC split this plan targets; (c) narrow to
bond-issuing sectors only (Real Estate/Energy/Industrials/Utilities lean 50-75%) and treat this
as a sector-scoped feature rather than full-universe.
