# Backtest Results

**Universe**: 1400 tickers

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
top_pct_20          +16.10%  +18.06%   0.9217   1.3306   -45.74%  1.0668   +4.30%   0.5818    64.2%     254
top_pct_10          +18.22%  +18.53%   1.0016   1.5140   -46.58%  1.0819   +6.25%   0.7536    64.2%     254
top_n_50            +18.18%  +17.99%   1.0243   1.4815   -48.08%  1.0826   +6.20%   0.8468    66.5%     254
top_n_25            +18.25%  +18.24%   1.0160   1.4607   -46.26%  1.0574   +6.55%   0.7488    68.5%     254
universe_ew         +17.47%  +21.56%   0.8501   1.4647   -45.02%  1.0370   +6.00%   0.4443    65.7%     254
SPY                  +8.39%  +15.20%   0.6083   0.8605   -50.80%     N/A      N/A      N/A    63.5%     318
f_low_ps            +17.49%  +20.34%   0.8991   1.3369   -44.70%  1.2052   +4.16%   0.6653    61.8%     254
f_high_fcf_yield    +16.77%  +20.08%   0.8776   1.2508   -49.53%  1.1497   +4.05%   0.5598    63.4%     254
f_high_div_yield    +15.78%  +18.17%   0.9024   1.2157   -40.19%  0.9865   +4.87%   0.4453    66.1%     254
f_low_evebitda      +15.35%  +19.47%   0.8357   1.1532   -46.34%  1.1658   +2.46%   0.5088    63.4%     254
f_low_pe            +16.17%  +19.96%   0.8559   1.1856   -46.84%  1.1401   +3.56%   0.5103    61.4%     254
f_high_earnings_yield  +15.46%  +19.93%   0.8258   1.1482   -47.76%  1.1402   +2.85%   0.4540    61.4%     254
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_pct_20                  10.8%              1.08         12.91
top_pct_10                  12.9%              1.29         15.44
top_n_50                    14.5%              1.45         17.38
top_n_25                    17.4%              1.74         20.94
```


## Single-Factor Baseline Turnover

```
Factor (top20%)      Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
f_low_ps                     8.8%              0.88         10.61
f_high_fcf_yield            11.1%              1.11         13.31
f_high_div_yield             9.6%              0.96         11.46
f_low_evebitda              12.6%              1.26         15.11
f_low_pe                    11.6%              1.16         13.93
f_high_earnings_yield          11.1%              1.11         13.30
```
