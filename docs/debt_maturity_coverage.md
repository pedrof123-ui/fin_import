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

**GO, decided 2026-09-01.** Full universe, null-safe fallback (option (a) below) — build for
all ~2,500 tickers, ~36% of the sample got the real WACC split, the rest keep today's
embedded-rate-only behavior unchanged. Options considered: (a) full-universe build scoped to
the ~36% with per-tranche coupon detail, everyone else falls back to today's embedded-rate WACC
(matches the plan's existing null-safe design, no scope change needed) — **chosen**; (b) also
extract maturities-ladder-only tickers (another ~31%) for `weighted_avg_years_to_maturity` alone,
useful for a future maturity-profile feature but not for the WACC split this plan targets; (c)
narrow to bond-issuing sectors only (Real Estate/Energy/Industrials/Utilities lean 50-75%) and
treat this as a sector-scoped feature rather than full-universe.

## Phase 4 — full-universe backfill results (2026-09-02)

Ran `scripts/backfill_debt_maturity.py --universe` against all 2,666 tickers in
`company_overview` (concurrency 5, ~18 minutes). Outcome:

| status | count | pct of universe |
|---|---|---|
| coverage (either concept extracted any tranche rows) | 1,272 | 47.7% |
| no coverage | 1,391 | 52.2% |
| error (unretryable) | 3 | 0.1% |

**The number that actually matters is lower than either of those: 268 tickers (10.1% of the
universe) have a non-null `weighted_avg_coupon_long_dated`** — the field `dcf/wacc.py`'s Phase 3
split actually consumes. The gap between 47.7% "coverage" and 10.1% "split applies" is
`debt_maturity/summary.py`'s source-selection (Phase 2.2): many tickers have per-tranche detail
tagged, but the maturities ladder covers more total debt for them, so `compute_summary` picks the
ladder (years-only, no coupon) over the per-tranche table. This is working as designed — the
alternative (always preferring per-tranche detail) would understate `total_debt_covered` on
exactly the tickers Phase 2.2 was fixed for (Southern Co.'s ladder-vs-instruments case) — but it
means the Phase 0 sample's 35.8% per-tranche-coverage estimate overstated how often the WACC
split actually fires, once source-selection is applied on top of raw concept presence.

3 unretryable errors (`Company not found` on EDGAR: HIFS, NBN, TOWN — ticker not resolvable,
likely delisted/renamed/reassigned, same class of issue as
[[project_survivorship_bias_result]]) are left as no-coverage; not fixable generically. 36 other
errors (mostly SEC read timeouts, a handful of `'NoneType' object has no attribute 'facts'` for
filings with no XBRL attachments at all) were transient/a real generic bug
(`scripts/fetch_debt_maturity.py`'s `extract_debt_tranches` now returns `[]` when
`filing.xbrl()` is `None`, same null-safe pattern as the existing `filing is None` check) and all
resolved cleanly on retry — final count above already reflects the retry.

Live end-to-end verification post-backfill: IBM/AAPL/Southern Co.'s real
`debt_maturity_summary` rows reproduce Phase 2's scratch-DB sanity numbers exactly (IBM
WAYTM=9.8y 100% dated 3.10%/3.88%; Southern Co. WAYTM=22.5y 100% dated 5.31%/4.20%; AAPL
WAYTM=2.5y 46% dated). `dcf.model.run_dcf_av` for all three now emits the split-WACC advisory
text (`wacc_terminal > wacc`, warning cites the disclosed long-dated coupon) — confirmed live,
not just in tests. A no-coverage ticker (ZM) confirmed unchanged: `wacc_terminal is None`,
falls back to embedded `wacc`.
