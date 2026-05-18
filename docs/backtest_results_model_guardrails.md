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
top_pct_20          +16.70%  +18.48%   0.9331   1.3429   -48.62%  1.0893   +4.65%   0.6291    65.0%     254
top_pct_10          +19.43%  +19.40%   1.0188   1.4428   -49.97%  1.1222   +7.02%   0.8149    66.1%     254
top_n_50            +21.89%  +19.91%   1.1007   1.6038   -48.98%  1.1246   +9.45%   0.9443    66.1%     254
top_n_25            +23.95%  +20.82%   1.1435   1.6421   -50.09%  1.1488  +11.24%   1.0116    66.1%     254
universe_ew         +16.38%  +19.04%   0.8958   1.3489   -43.45%  1.0939   +4.28%   0.5459    65.4%     254
SPY                  +8.39%  +15.20%   0.6083   0.8605   -50.80%     N/A      N/A      N/A    63.5%     318
f_low_ps            +19.51%  +21.46%   0.9429   1.4678   -44.88%  1.2335   +5.87%   0.7422    63.0%     254
f_high_fcf_yield    +18.08%  +19.70%   0.9479   1.3648   -43.62%  1.1412   +5.46%   0.6938    63.4%     254
f_high_div_yield    +16.05%  +17.18%   0.9573   1.3278   -35.44%  0.9173   +5.90%   0.4585    65.7%     254
f_low_evebitda      +17.69%  +21.32%   0.8740   1.3009   -44.80%  1.1687   +4.76%   0.5676    63.8%     246
f_low_pe            +15.46%  +19.83%   0.8289   1.1558   -47.24%  1.1455   +2.79%   0.4654    63.8%     254
f_high_earnings_yield  +15.29%  +19.75%   0.8238   1.1433   -47.87%  1.1421   +2.65%   0.4528    63.4%     254
xgb_top_pct_20      +20.13%  +20.94%   0.9861   1.5658   -41.57%  1.2018   +6.83%   0.8021    64.2%     254
xgb_top_pct_10      +22.65%  +22.16%   1.0381   1.6998   -43.67%  1.2492   +8.84%   0.9051    63.4%     254
xgb_top_n_50        +24.08%  +23.10%   1.0553   1.7958   -43.44%  1.2677  +10.05%   0.9193    64.6%     254
xgb_top_n_25        +28.42%  +25.22%   1.1247   2.0250   -49.41%  1.3429  +13.57%   1.0357    63.0%     254
gr_top_pct_20       +20.10%  +17.99%   1.1138   1.8026   -25.04%  1.0466   +5.12%   0.6195    64.5%     211
gr_top_pct_10       +22.17%  +18.33%   1.1911   1.9627   -23.07%  1.0541   +7.08%   0.7795    66.4%     211
gr_top_n_50         +22.66%  +18.27%   1.2170   1.9409   -22.02%  1.0479   +7.66%   0.8198    65.4%     211
gr_top_n_25         +25.17%  +18.46%   1.3176   1.9901   -23.69%  1.0370  +10.33%   0.9785    67.8%     211
xgb_gr_top_pct_20   +19.18%  +19.43%   1.0054   1.5426   -33.63%  1.1145   +3.22%   0.4933    65.9%     211
xgb_gr_top_pct_10   +20.10%  +20.08%   1.0180   1.5980   -33.65%  1.1217   +4.04%   0.5278    64.0%     211
xgb_gr_top_n_50     +20.19%  +19.55%   1.0443   1.5923   -33.76%  1.0960   +4.50%   0.5469    63.0%     211
xgb_gr_top_n_25     +20.72%  +19.72%   1.0602   1.6638   -33.29%  1.0686   +5.42%   0.5488    65.4%     211
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_pct_20                  13.5%              1.35         16.25
top_pct_10                  16.3%              1.63         19.60
top_n_50                    17.2%              1.72         20.69
top_n_25                    19.9%              1.99         23.83
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
gr_top_pct_20                 15.1%              1.51         18.17
gr_top_pct_10                 17.0%              1.70         20.41
gr_top_n_50                   17.0%              1.70         20.36
gr_top_n_25                   19.5%              1.95         23.45
xgb_gr_top_pct_20             24.8%              2.48         29.79
xgb_gr_top_pct_10             28.6%              2.86         34.29
xgb_gr_top_n_50               28.5%              2.85         34.25
xgb_gr_top_n_25               33.6%              3.36         40.32
```


## XGBoost Model Turnover

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
xgb_top_pct_20              24.0%              2.40         28.80
xgb_top_pct_10              29.1%              2.91         34.92
xgb_top_n_50                30.3%              3.03         36.31
xgb_top_n_25                36.3%              3.63         43.56
```
