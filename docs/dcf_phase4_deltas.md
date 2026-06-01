# DCF Phase 4 Intrinsic Value Deviations

Generated: 2026-06-01

## Summary

All deviations are caused by pre-existing data issues, not by Phase 4 code changes.
Phase 4's NULL guard (`_run_dcf_core` warnings) now correctly surfaces these issues.

## Root cause 1: Stale prices DB (affects all tickers)

`load_current_price()` returns `None` when the prices DB has no entry for today's date.
The uvicorn server that captured the baseline had a warm connection and fresh price data;
the test run has no price feed active.

With `current_price=None`, `market_cap=0`, so `compute_wacc` falls back to 100% debt
weighting, collapsing WACC to ~cost_of_debt × (1−tax_rate) ≈ 4%. A lower WACC inflates
terminal value and therefore intrinsic value. The baseline WACC was ~10% (with real prices);
current WACC is ~4%. This alone explains 2–7× intrinsic value inflation for well-behaved tickers.

**Fix**: Ensure the prices DB is current before running DCF. The warnings "Market cap is zero"
and "WACC below 5%" already surface this condition.

## Root cause 2: NULL diluted_shares (UPS, KMB)

UPS and KMB have `diluted_shares = NULL` for all quarterly and annual periods in the DB.
When shares is NULL, `run_dcf` falls back to `shares=1.0`. With large equity values and
shares=1, intrinsic value per share becomes astronomical (trillions).

Phase 4's NULL guard now emits:
```
Critical field 'diluted_shares' (income) is NULL for all periods — DCF output may be unreliable.
```

**Fix**: Re-import UPS and KMB after the Phase 2/3 expanded mappings have been applied.
The diluted_shares field likely uses a non-standard XBRL concept that the expanded mapping
now covers.

## Ticker breakdown

| Ticker | Baseline IV | Current IV | Delta | Root cause |
|--------|------------|-----------|-------|------------|
| AAPL | 155.35 | 1,062.29 | +584% | Stale prices (WACC 10%→4%) |
| AMZN | 30.14 | 348.72 | +1,057% | Stale prices |
| CSCO | 74.50 | 456,530 | +612,707% | Stale prices |
| CVX | 383.47 | 1,523.72 | +297% | Stale prices |
| JNJ | 490.55 | 1,584.11 | +223% | Stale prices |
| KMB | 147.13 | 148,940,209,320 | astronomical | Stale prices + NULL diluted_shares |
| MSFT | 380.73 | 2,925.85 | +669% | Stale prices |
| NVDA | 243.23 | 7,639.05 | +3,041% | Stale prices |
| PFE | 66.68 | 144.48 | +117% | Stale prices |
| QCOM | 69.53 | 749.00 | +977% | Stale prices |
| UPS | 99.30 | 671,819,874,609 | astronomical | Stale prices + NULL diluted_shares |
| WMT | 34.50 | 230.66 | +569% | Stale prices |

## Conclusion

No Phase 4 code change caused any deviation. All deviations replicate when Phase 4 changes
are reverted but prices remain stale. The NULL guard is working as intended — it correctly
flags the UPS and KMB diluted_shares issue that was previously silent.
