# Backtest Results

**Universe**: 1373 tickers

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
top_pct_20          +16.72%  +18.46%   0.9354   1.3374   -48.12%  1.0886   +4.68%   0.6337    64.6%     254
top_pct_10          +18.31%  +19.57%   0.9633   1.3579   -50.93%  1.1467   +5.63%   0.7394    63.8%     254
top_n_50            +19.90%  +20.48%   0.9944   1.4393   -52.66%  1.1671   +6.99%   0.7883    65.4%     254
top_n_25            +21.47%  +21.44%   1.0211   1.4429   -55.08%  1.2019   +8.17%   0.8448    66.9%     254
universe_ew         +18.48%  +22.74%   0.8544   1.5241   -45.15%  1.0404   +6.97%   0.4676    65.7%     254
SPY                  +8.39%  +15.20%   0.6083   0.8605   -50.80%     N/A      N/A      N/A    63.5%     318
f_low_ps            +19.44%  +21.27%   0.9471   1.4270   -44.81%  1.2229   +5.91%   0.7440    63.8%     254
f_high_fcf_yield    +16.27%  +20.14%   0.8539   1.2174   -49.68%  1.1525   +3.52%   0.5172    62.6%     254
f_high_div_yield    +15.54%  +18.22%   0.8893   1.1880   -40.89%  0.9861   +4.64%   0.4233    65.4%     254
f_low_evebitda      +18.23%  +21.36%   0.8941   1.3152   -46.65%  1.1709   +5.27%   0.6042    64.2%     246
f_low_pe            +16.00%  +20.25%   0.8395   1.1516   -48.52%  1.1572   +3.20%   0.4937    62.2%     254
f_high_earnings_yield  +15.37%  +20.13%   0.8159   1.1212   -48.97%  1.1505   +2.65%   0.4440    61.4%     254
xgb_top_pct_20      +19.64%  +21.38%   0.9509   1.4884   -45.91%  1.2383   +5.95%   0.7667    65.0%     254
xgb_top_pct_10      +22.45%  +22.68%   1.0124   1.6288   -45.35%  1.2884   +8.20%   0.8859    66.1%     254
xgb_top_n_50        +24.33%  +24.36%   1.0204   1.7889   -46.43%  1.3175   +9.76%   0.8722    65.7%     254
xgb_top_n_25        +25.02%  +27.05%   0.9617   1.6629   -49.75%  1.3193  +10.43%   0.7499    64.2%     254
gr_top_pct_20       +20.12%  +18.09%   1.1104   1.7470   -26.05%  1.0574   +4.98%   0.6303    65.9%     211
gr_top_pct_10       +22.05%  +19.17%   1.1421   1.8362   -25.06%  1.1121   +6.13%   0.7627    65.4%     211
gr_top_n_50         +22.62%  +19.24%   1.1635   1.7690   -26.41%  1.1169   +6.63%   0.8116    65.9%     211
gr_top_n_25         +23.22%  +19.25%   1.1886   1.7010   -27.21%  1.1095   +7.33%   0.8461    68.7%     211
xgb_gr_top_pct_20   +20.03%  +19.88%   1.0233   1.6036   -34.43%  1.1312   +3.84%   0.5470    63.0%     211
xgb_gr_top_pct_10   +20.50%  +20.47%   1.0191   1.6173   -34.75%  1.1448   +4.11%   0.5537    64.5%     211
xgb_gr_top_n_50     +21.67%  +20.27%   1.0751   1.7478   -34.69%  1.1257   +5.56%   0.6346    62.6%     211
xgb_gr_top_n_25     +22.39%  +19.98%   1.1166   2.0013   -29.73%  1.0811   +6.91%   0.6590    64.5%     211
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_pct_20                  16.1%              1.61         19.36
top_pct_10                  18.6%              1.86         22.36
top_n_50                    20.4%              2.04         24.44
top_n_25                    22.4%              2.24         26.87
```


## Single-Factor Baseline Turnover

```
Factor (top20%)      Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
f_low_ps                     8.3%              0.83         10.01
f_high_fcf_yield            11.5%              1.15         13.84
f_high_div_yield             9.5%              0.95         11.38
f_low_evebitda              12.9%              1.29         15.48
f_low_pe                    12.0%              1.20         14.35
f_high_earnings_yield          11.6%              1.16         13.88
```


## Guardrailed Portfolio Turnover (value traps excluded, max_missing=2)

```
Portfolio              Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
------------------------------------------------------------------------
gr_top_pct_20                 17.5%              1.75         21.06
gr_top_pct_10                 19.6%              1.96         23.51
gr_top_n_50                   20.5%              2.05         24.60
gr_top_n_25                   21.6%              2.16         25.97
xgb_gr_top_pct_20             27.2%              2.72         32.70
xgb_gr_top_pct_10             32.4%              3.24         38.93
xgb_gr_top_n_50               33.0%              3.30         39.60
xgb_gr_top_n_25               37.5%              3.75         44.94
```


## XGBoost Model Turnover

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
xgb_top_pct_20              25.8%              2.58         31.00
xgb_top_pct_10              31.4%              3.14         37.66
xgb_top_n_50                35.3%              3.53         42.41
xgb_top_n_25                42.3%              4.23         50.75
```
