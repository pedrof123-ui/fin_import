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
top_pct_20          +17.29%  +18.40%   0.9645   1.3780   -48.90%  1.0774   +5.38%   0.6760    65.4%     254
top_pct_10          +19.84%  +19.53%   1.0314   1.4261   -50.38%  1.1333   +7.30%   0.8524    66.1%     254
top_n_50            +21.21%  +20.32%   1.0550   1.5112   -51.75%  1.1489   +8.51%   0.8797    66.1%     254
top_n_25            +22.18%  +20.98%   1.0673   1.4930   -53.69%  1.1593   +9.36%   0.8877    66.5%     254
universe_ew         +20.07%  +25.18%   0.8387   1.6884   -42.60%  1.0171   +8.82%   0.4710    66.9%     254
SPY                  +8.39%  +15.20%   0.6083   0.8605   -50.80%     N/A      N/A      N/A    63.5%     318
f_low_ps            +19.93%  +21.25%   0.9668   1.5030   -44.09%  1.2192   +6.45%   0.7766    63.4%     254
f_high_fcf_yield    +17.88%  +19.63%   0.9419   1.3475   -43.88%  1.1372   +5.30%   0.6791    63.0%     254
f_high_div_yield    +16.56%  +16.94%   0.9951   1.3484   -33.96%  0.9075   +6.52%   0.5065    66.5%     254
f_low_evebitda      +18.83%  +21.19%   0.9238   1.3626   -44.69%  1.1607   +5.99%   0.6485    64.6%     246
f_low_pe            +16.03%  +19.76%   0.8561   1.1798   -47.61%  1.1390   +3.43%   0.5117    65.0%     254
f_high_earnings_yield  +15.70%  +19.68%   0.8446   1.1617   -47.66%  1.1350   +3.15%   0.4863    64.6%     254
xgb_top_pct_20      +20.75%  +21.21%   1.0004   1.6309   -42.61%  1.2188   +7.27%   0.8403    63.8%     254
xgb_top_pct_10      +24.13%  +22.86%   1.0658   1.7912   -45.97%  1.2854   +9.91%   0.9674    64.2%     254
xgb_top_n_50        +26.98%  +24.21%   1.1137   1.9560   -44.92%  1.3081  +12.51%   1.0185    65.0%     254
xgb_top_n_25        +29.81%  +27.69%   1.0830   1.9497   -50.80%  1.3762  +14.59%   0.9453    64.6%     254
gr_top_pct_20       +20.84%  +18.15%   1.1402   1.8555   -24.35%  1.0538   +5.76%   0.6830    66.8%     211
gr_top_pct_10       +23.09%  +19.11%   1.1893   1.9731   -23.11%  1.0923   +7.45%   0.8204    65.9%     211
gr_top_n_50         +23.53%  +18.74%   1.2286   2.0162   -25.05%  1.0728   +8.17%   0.8739    65.9%     211
gr_top_n_25         +24.65%  +19.18%   1.2530   1.8852   -30.39%  1.0804   +9.19%   0.9151    68.7%     211
xgb_gr_top_pct_20   +18.96%  +19.44%   0.9952   1.5809   -32.47%  1.1134   +3.02%   0.4726    64.0%     211
xgb_gr_top_pct_10   +20.30%  +20.23%   1.0201   1.6863   -33.74%  1.1353   +4.05%   0.5457    61.6%     211
xgb_gr_top_n_50     +19.87%  +19.93%   1.0140   1.6406   -34.03%  1.1111   +3.96%   0.5095    62.6%     211
xgb_gr_top_n_25     +23.52%  +20.45%   1.1420   1.9455   -31.74%  1.1145   +7.57%   0.7374    65.9%     211
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_pct_20                  16.2%              1.62         19.43
top_pct_10                  18.4%              1.84         22.08
top_n_50                    18.9%              1.89         22.71
top_n_25                    21.2%              2.12         25.49
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
gr_top_pct_20                 17.5%              1.75         20.96
gr_top_pct_10                 19.1%              1.91         22.93
gr_top_n_50                   19.7%              1.97         23.59
gr_top_n_25                   21.2%              2.12         25.40
xgb_gr_top_pct_20             26.4%              2.64         31.62
xgb_gr_top_pct_10             30.1%              3.01         36.09
xgb_gr_top_n_50               29.3%              2.93         35.19
xgb_gr_top_n_25               34.3%              3.43         41.17
```


## XGBoost Model Turnover

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
xgb_top_pct_20              25.1%              2.51         30.17
xgb_top_pct_10              29.9%              2.99         35.85
xgb_top_n_50                31.7%              3.17         38.03
xgb_top_n_25                38.5%              3.85         46.14
```
