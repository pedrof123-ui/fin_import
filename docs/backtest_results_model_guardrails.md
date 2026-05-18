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
top_pct_20          +17.31%  +18.41%   0.9650   1.3845   -48.84%  1.0780   +5.39%   0.6777    65.0%     254
top_pct_10          +19.79%  +19.42%   1.0338   1.4201   -49.97%  1.1284   +7.31%   0.8545    65.4%     254
top_n_50            +21.15%  +20.19%   1.0578   1.4982   -50.95%  1.1439   +8.50%   0.8832    66.5%     254
top_n_25            +21.95%  +20.88%   1.0619   1.4564   -53.33%  1.1650   +9.06%   0.8901    67.3%     254
universe_ew         +20.07%  +25.18%   0.8387   1.6884   -42.60%  1.0171   +8.82%   0.4710    66.9%     254
SPY                  +8.39%  +15.20%   0.6083   0.8605   -50.80%     N/A      N/A      N/A    63.5%     318
f_low_ps            +19.93%  +21.25%   0.9668   1.5030   -44.09%  1.2192   +6.45%   0.7766    63.4%     254
f_high_fcf_yield    +17.88%  +19.63%   0.9419   1.3475   -43.88%  1.1372   +5.30%   0.6791    63.0%     254
f_high_div_yield    +16.56%  +16.94%   0.9951   1.3484   -33.96%  0.9075   +6.52%   0.5065    66.5%     254
f_low_evebitda      +18.83%  +21.19%   0.9238   1.3626   -44.69%  1.1607   +5.99%   0.6485    64.6%     246
f_low_pe            +16.03%  +19.76%   0.8561   1.1798   -47.61%  1.1390   +3.43%   0.5117    65.0%     254
f_high_earnings_yield  +15.70%  +19.68%   0.8446   1.1617   -47.66%  1.1350   +3.15%   0.4863    64.6%     254
xgb_top_pct_20      +20.61%  +21.13%   0.9982   1.6119   -42.94%  1.2179   +7.14%   0.8391    63.8%     254
xgb_top_pct_10      +23.57%  +22.77%   1.0489   1.7736   -45.55%  1.2741   +9.47%   0.9286    64.2%     254
xgb_top_n_50        +26.73%  +23.96%   1.1145   1.9502   -43.90%  1.2876  +12.49%   1.0078    65.4%     254
xgb_top_n_25        +29.93%  +27.54%   1.0906   1.9759   -50.16%  1.3517  +14.98%   0.9443    64.6%     254
gr_top_pct_20       +20.82%  +18.01%   1.1467   1.8346   -24.39%  1.0475   +5.82%   0.6879    66.4%     211
gr_top_pct_10       +23.44%  +18.83%   1.2197   1.9258   -23.13%  1.0899   +7.83%   0.8884    67.8%     211
gr_top_n_50         +23.57%  +18.74%   1.2307   1.9954   -23.69%  1.0778   +8.14%   0.8887    67.8%     211
gr_top_n_25         +25.33%  +18.84%   1.3019   1.9314   -28.30%  1.0693  +10.03%   1.0013    69.7%     211
xgb_gr_top_pct_20   +19.38%  +19.26%   1.0212   1.6202   -32.38%  1.1002   +3.63%   0.5071    64.9%     211
xgb_gr_top_pct_10   +20.12%  +19.84%   1.0283   1.7096   -33.02%  1.1135   +4.18%   0.5372    62.1%     211
xgb_gr_top_n_50     +19.59%  +19.63%   1.0141   1.6560   -32.65%  1.0949   +3.91%   0.4915    63.5%     211
xgb_gr_top_n_25     +22.57%  +20.09%   1.1195   1.8777   -32.94%  1.1007   +6.81%   0.6856    63.5%     211
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_pct_20                  16.4%              1.64         19.67
top_pct_10                  18.7%              1.87         22.50
top_n_50                    19.5%              1.95         23.43
top_n_25                    21.0%              2.10         25.26
```


## Single-Factor Baseline Turnover

```
Factor (top20%)      Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
f_low_ps                     8.6%              0.86         10.30
f_high_fcf_yield            12.3%              1.23         14.77
f_high_div_yield             9.4%              0.94         11.22
f_low_evebitda              12.2%              1.22         14.58
f_low_pe                    11.9%              1.19         14.28
f_high_earnings_yield          11.7%              1.17         14.08
```


## Guardrailed Portfolio Turnover (value traps excluded, max_missing=2)

```
Portfolio              Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
------------------------------------------------------------------------
gr_top_pct_20                 18.0%              1.80         21.58
gr_top_pct_10                 19.7%              1.97         23.62
gr_top_n_50                   20.0%              2.00         23.98
gr_top_n_25                   21.9%              2.19         26.23
xgb_gr_top_pct_20             26.6%              2.66         31.91
xgb_gr_top_pct_10             31.3%              3.13         37.57
xgb_gr_top_n_50               30.2%              3.02         36.24
xgb_gr_top_n_25               35.3%              3.53         42.31
```


## XGBoost Model Turnover

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
xgb_top_pct_20              25.1%              2.51         30.09
xgb_top_pct_10              30.1%              3.01         36.08
xgb_top_n_50                32.0%              3.20         38.37
xgb_top_n_25                39.0%              3.90         46.82
```
