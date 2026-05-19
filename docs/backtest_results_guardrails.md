# Backtest Results

**Universe**: 1056 tickers

**Filters**: min_market_cap=1000000000 | min_price=5.00

**TC**: 10 bps one-way per trade

**Signal**: composite baseline (value+quality+momentum where available)

**Rebalancing**: monthly equal-weight, non-overlapping 1-month returns


## Portfolio weighting

All portfolios in this backtest are equal-weight (each selected stock receives an equal allocation at each monthly rebalance).

Capped-weight portfolios (e.g., max 5% per position) are deferred to Phase 7 risk diagnostics, where position concentration limits are configured as guardrails.


## Performance Summary

```
Portfolio              CAGR   AnnVol   Sharpe  Sortino     MaxDD    Beta    Alpha       IR  WinRate  Months
--------------------------------------------------------------------------------------------------------------
top_pct_20          +16.56%  +18.63%   0.9206   1.3099   -48.79%  1.0956   +4.44%   0.6083    64.6%     254
top_pct_10          +19.80%  +19.30%   1.0394   1.4548   -50.17%  1.1135   +7.49%   0.8445    65.7%     254
top_n_50            +21.96%  +19.97%   1.1008   1.6404   -48.31%  1.1248   +9.52%   0.9418    65.7%     254
top_n_25            +24.68%  +20.96%   1.1657   1.7025   -49.71%  1.1452  +12.02%   1.0373    66.9%     254
top_n_10            +25.71%  +22.85%   1.1243   1.6333   -52.04%  1.2071  +12.36%   0.9754    65.0%     254
universe_ew         +16.38%  +19.04%   0.8958   1.3489   -43.45%  1.0939   +4.28%   0.5459    65.4%     254
SPY                  +8.39%  +15.20%   0.6083   0.8605   -50.80%     N/A      N/A      N/A    63.5%     318
f_low_ps            +19.51%  +21.46%   0.9429   1.4678   -44.88%  1.2335   +5.87%   0.7422    63.0%     254
f_high_fcf_yield    +18.08%  +19.70%   0.9479   1.3648   -43.62%  1.1412   +5.46%   0.6938    63.4%     254
f_high_div_yield    +16.05%  +17.18%   0.9573   1.3278   -35.44%  0.9173   +5.90%   0.4585    65.7%     254
f_low_evebitda      +17.69%  +21.32%   0.8740   1.3009   -44.80%  1.1687   +4.76%   0.5676    63.8%     246
f_low_pe            +15.46%  +19.83%   0.8289   1.1558   -47.24%  1.1455   +2.79%   0.4654    63.8%     254
f_high_earnings_yield  +15.29%  +19.75%   0.8238   1.1433   -47.87%  1.1421   +2.65%   0.4528    63.4%     254
gr_top_pct_20       +20.08%  +18.15%   1.1048   1.8260   -24.86%  1.0529   +5.01%   0.6098    65.4%     211
gr_top_pct_10       +22.05%  +18.47%   1.1776   1.9357   -23.09%  1.0573   +6.91%   0.7544    66.4%     211
gr_top_n_50         +22.14%  +18.21%   1.1961   1.9721   -23.49%  1.0426   +7.21%   0.7702    64.0%     211
gr_top_n_25         +25.05%  +18.50%   1.3102   1.9775   -24.03%  1.0332  +10.26%   0.9551    67.3%     211
gr_top_n_10         +26.45%  +19.59%   1.3050   2.1115   -27.15%  1.0499  +11.42%   0.9411    66.4%     211
vw_gr_top_pct_20    +19.63%  +17.22%   1.1327   1.8719   -23.32%  0.9944   +5.39%   0.5727    64.9%     211
vw_gr_top_pct_10    +21.71%  +17.59%   1.2117   1.9745   -21.97%  1.0011   +7.38%   0.7354    66.8%     211
vw_gr_top_n_50      +21.70%  +17.39%   1.2238   1.9662   -22.26%  0.9904   +7.53%   0.7417    66.4%     211
vw_gr_top_n_25      +24.72%  +17.51%   1.3588   2.0690   -22.50%  0.9822  +10.66%   0.9733    68.7%     211
vw_gr_top_n_10      +25.62%  +18.81%   1.3158   2.0510   -27.68%  1.0189  +11.03%   0.9274    66.8%     211
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_pct_20                  13.6%              1.36         16.33
top_pct_10                  16.2%              1.62         19.45
top_n_50                    16.9%              1.69         20.33
top_n_25                    19.8%              1.98         23.73
top_n_10                    22.5%              2.25         27.02
```


## Single-Factor Baseline Turnover

```
Factor (top20%)      Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
f_low_ps                     8.9%              0.89         10.73
f_high_fcf_yield            12.6%              1.26         15.13
f_high_div_yield             9.6%              0.96         11.55
f_low_evebitda              12.7%              1.27         15.18
f_low_pe                    12.1%              1.21         14.54
f_high_earnings_yield          12.1%              1.21         14.47
```


## Guardrailed Portfolio Turnover (value traps excluded, max_missing=2)

```
Portfolio              Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
------------------------------------------------------------------------
gr_top_pct_20                 14.7%              1.47         17.62
gr_top_pct_10                 16.5%              1.65         19.78
gr_top_n_50                   16.6%              1.66         19.97
gr_top_n_25                   18.9%              1.89         22.65
gr_top_n_10                   21.5%              2.15         25.82
```
