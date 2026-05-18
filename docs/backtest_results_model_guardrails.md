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
top_pct_20          +17.00%  +18.46%   0.9482   1.3519   -49.74%  1.0862   +4.98%   0.6557    64.6%     254
top_pct_10          +19.28%  +19.63%   1.0031   1.3984   -50.77%  1.1365   +6.71%   0.7972    64.6%     254
top_n_50            +20.14%  +20.24%   1.0138   1.4607   -51.33%  1.1521   +7.40%   0.8124    66.5%     254
top_n_25            +22.48%  +20.84%   1.0851   1.5034   -50.14%  1.1630   +9.62%   0.9301    65.7%     254
universe_ew         +16.38%  +19.04%   0.8958   1.3489   -43.45%  1.0939   +4.28%   0.5459    65.4%     254
SPY                  +8.39%  +15.20%   0.6083   0.8605   -50.80%     N/A      N/A      N/A    63.5%     318
f_low_ps            +19.51%  +21.46%   0.9429   1.4678   -44.88%  1.2335   +5.87%   0.7422    63.0%     254
f_high_fcf_yield    +18.08%  +19.70%   0.9479   1.3648   -43.62%  1.1412   +5.46%   0.6938    63.4%     254
f_high_div_yield    +16.05%  +17.18%   0.9573   1.3278   -35.44%  0.9173   +5.90%   0.4585    65.7%     254
f_low_evebitda      +17.69%  +21.32%   0.8740   1.3009   -44.80%  1.1687   +4.76%   0.5676    63.8%     246
f_low_pe            +15.46%  +19.83%   0.8289   1.1558   -47.24%  1.1455   +2.79%   0.4654    63.8%     254
f_high_earnings_yield  +15.29%  +19.75%   0.8238   1.1433   -47.87%  1.1421   +2.65%   0.4528    63.4%     254
xgb_top_pct_20      +20.80%  +21.31%   0.9987   1.6202   -45.07%  1.2259   +7.24%   0.8427    64.2%     254
xgb_top_pct_10      +23.16%  +23.14%   1.0215   1.7008   -49.98%  1.2922   +8.87%   0.8873    63.8%     254
xgb_top_n_50        +25.57%  +23.94%   1.0757   1.8954   -46.87%  1.2890  +11.31%   0.9473    63.4%     254
xgb_top_n_25        +28.43%  +27.42%   1.0513   1.8852   -55.17%  1.3540  +13.45%   0.8911    65.7%     254
gr_top_pct_20       +20.82%  +17.95%   1.1496   1.8473   -24.19%  1.0451   +5.85%   0.6910    67.3%     211
gr_top_pct_10       +23.43%  +18.79%   1.2219   1.9497   -21.85%  1.0885   +7.85%   0.8924    67.8%     211
gr_top_n_50         +23.31%  +18.74%   1.2192   1.9638   -23.93%  1.0810   +7.84%   0.8731    67.8%     211
gr_top_n_25         +24.20%  +18.90%   1.2494   1.8719   -29.32%  1.0693   +8.89%   0.8991    67.3%     211
xgb_gr_top_pct_20   +19.20%  +19.22%   1.0152   1.6134   -31.97%  1.0987   +3.48%   0.4936    64.9%     211
xgb_gr_top_pct_10   +20.40%  +19.98%   1.0344   1.7132   -32.40%  1.1220   +4.34%   0.5577    64.5%     211
xgb_gr_top_n_50     +19.77%  +19.72%   1.0182   1.6650   -32.07%  1.1063   +3.93%   0.5109    63.5%     211
xgb_gr_top_n_25     +21.09%  +20.22%   1.0527   1.7291   -33.08%  1.1117   +5.18%   0.5805    64.0%     211
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_pct_20                  13.6%              1.36         16.34
top_pct_10                  16.1%              1.61         19.26
top_n_50                    17.3%              1.73         20.80
top_n_25                    19.6%              1.96         23.52
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
gr_top_pct_20                 15.4%              1.54         18.47
gr_top_pct_10                 17.4%              1.74         20.90
gr_top_n_50                   18.1%              1.81         21.68
gr_top_n_25                   20.1%              2.01         24.13
xgb_gr_top_pct_20             24.4%              2.44         29.23
xgb_gr_top_pct_10             29.2%              2.92         34.99
xgb_gr_top_n_50               28.3%              2.83         33.91
xgb_gr_top_n_25               33.8%              3.38         40.61
```


## XGBoost Model Turnover

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
xgb_top_pct_20              23.1%              2.31         27.70
xgb_top_pct_10              27.8%              2.78         33.41
xgb_top_n_50                30.2%              3.02         36.19
xgb_top_n_25                38.1%              3.81         45.71
```
