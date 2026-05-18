# Backtest Results

**Universe**: 1373 tickers

**Filters**: min_market_cap=1000000000 | min_price=5.00

**TC**: 10 bps one-way per trade

**Signal**: composite baseline (value+quality+momentum where available)

**Rebalancing**: quarterly equal-weight, non-overlapping 3-month returns


## Portfolio weighting

All portfolios in this backtest are equal-weight (each selected stock receives an equal allocation at each monthly rebalance).

Capped-weight portfolios (e.g., max 5% per position) are deferred to Phase 7 risk diagnostics, where position concentration limits are configured as guardrails.


## Performance Summary

```
Portfolio              CAGR   AnnVol   Sharpe  Sortino     MaxDD    Beta    Alpha       IR  WinRate  Months
--------------------------------------------------------------------------------------------------------------
top_n_25            +20.52%  +21.54%   0.9804   1.3870   -58.02%  1.2102   +7.13%   0.7792    64.2%     254
top_n_10            +20.93%  +22.66%   0.9588   1.3653   -60.56%  1.1817   +7.86%   0.6955    62.6%     254
top_pct_20          +15.93%  +18.60%   0.8928   1.2733   -49.85%  1.0925   +3.85%   0.5468    61.8%     254
universe_ew         +18.48%  +22.74%   0.8544   1.5241   -45.15%  1.0404   +6.97%   0.4676    65.7%     254
SPY                  +8.39%  +15.20%   0.6083   0.8605   -50.80%     N/A      N/A      N/A    63.5%     318
f_low_ps            +18.99%  +21.05%   0.9364   1.4352   -45.74%  1.2098   +5.60%   0.7156    63.4%     254
f_high_fcf_yield    +15.72%  +20.07%   0.8323   1.1860   -52.03%  1.1521   +2.98%   0.4767    63.0%     254
f_high_div_yield    +15.31%  +17.93%   0.8883   1.2329   -40.66%  0.9716   +4.56%   0.4049    65.0%     254
f_low_evebitda      +17.12%  +20.83%   0.8657   1.2937   -46.03%  1.1610   +4.21%   0.5484    63.3%     245
f_low_pe            +15.65%  +19.92%   0.8344   1.1840   -46.78%  1.1383   +3.06%   0.4684    61.8%     254
f_high_earnings_yield  +15.07%  +19.86%   0.8108   1.1465   -47.32%  1.1336   +2.54%   0.4200    61.0%     254
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_n_25                    14.4%              1.44         17.24
top_n_10                    17.2%              1.72         20.65
top_pct_20                   9.9%              0.99         11.84
```


## Single-Factor Baseline Turnover

```
Factor (top20%)      Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
f_low_ps                     5.4%              0.54          6.44
f_high_fcf_yield             8.1%              0.81          9.76
f_high_div_yield             6.0%              0.60          7.26
f_low_evebitda               8.9%              0.89         10.69
f_low_pe                     8.1%              0.81          9.71
f_high_earnings_yield           7.9%              0.79          9.44
```
