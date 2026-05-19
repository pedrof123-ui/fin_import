# Backtest Results

**Universe**: 1055 tickers

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
top_pct_20          +16.47%  +18.49%   0.9220   1.3295   -48.62%  1.0878   +4.43%   0.6024    64.6%     254
top_pct_10          +19.21%  +19.40%   1.0091   1.4327   -49.97%  1.1194   +6.82%   0.7904    65.4%     254
top_n_50            +21.55%  +19.95%   1.0845   1.5926   -48.98%  1.1215   +9.13%   0.9065    65.7%     254
top_n_25            +23.60%  +20.90%   1.1262   1.6321   -50.09%  1.1475  +10.90%   0.9754    65.7%     254
top_n_10            +24.32%  +22.60%   1.0834   1.6417   -55.28%  1.2284  +10.72%   0.9400    63.4%     254
universe_ew         +16.26%  +19.04%   0.8899   1.3448   -43.45%  1.0927   +4.16%   0.5325    65.0%     254
SPY                  +8.40%  +15.20%   0.6086   0.8610   -50.80%     N/A      N/A      N/A    63.5%     318
f_low_ps            +19.28%  +21.49%   0.9326   1.4619   -44.88%  1.2312   +5.65%   0.7189    63.0%     254
f_high_fcf_yield    +17.93%  +19.70%   0.9411   1.3645   -43.62%  1.1389   +5.32%   0.6765    63.4%     254
f_high_div_yield    +15.93%  +17.20%   0.9504   1.3235   -35.44%  0.9163   +5.79%   0.4460    65.7%     254
f_low_evebitda      +17.53%  +21.31%   0.8675   1.2968   -44.80%  1.1660   +4.62%   0.5534    63.8%     246
f_low_pe            +15.32%  +19.83%   0.8224   1.1529   -47.24%  1.1443   +2.65%   0.4510    64.2%     254
f_high_earnings_yield  +15.13%  +19.73%   0.8173   1.1425   -47.87%  1.1391   +2.52%   0.4367    63.4%     254
xgb_top_pct_20      +20.54%  +21.23%   0.9920   1.5366   -45.15%  1.2302   +6.92%   0.8397    64.6%     254
xgb_top_pct_10      +23.42%  +22.46%   1.0549   1.7660   -43.14%  1.2596   +9.48%   0.9340    63.8%     254
xgb_top_n_50        +24.74%  +23.39%   1.0678   1.8554   -43.66%  1.2735  +10.65%   0.9362    64.2%     254
xgb_top_n_25        +25.75%  +24.48%   1.0643   1.8196   -42.98%  1.3142  +11.20%   0.9361    62.6%     254
xgb_top_n_10        +28.37%  +27.97%   1.0370   1.8460   -42.46%  1.3500  +13.42%   0.8634    66.1%     254
gr_top_pct_20       +19.94%  +17.99%   1.1065   1.8162   -24.70%  1.0435   +4.99%   0.5985    64.0%     211
gr_top_pct_10       +21.74%  +18.36%   1.1696   1.9379   -23.07%  1.0525   +6.66%   0.7322    65.9%     211
gr_top_n_50         +22.29%  +18.28%   1.1993   1.9321   -22.02%  1.0443   +7.33%   0.7771    64.5%     211
gr_top_n_25         +24.84%  +18.55%   1.2971   1.9770   -23.69%  1.0351  +10.01%   0.9324    67.3%     211
gr_top_n_10         +25.56%  +18.90%   1.3072   2.0280   -26.84%  0.9941  +11.32%   0.8716    69.2%     211
xgb_gr_top_pct_20   +19.86%  +19.41%   1.0359   1.6430   -33.31%  1.1060   +4.02%   0.5414    65.9%     211
xgb_gr_top_pct_10   +18.70%  +20.01%   0.9612   1.5359   -34.17%  1.1207   +2.64%   0.4226    62.1%     211
xgb_gr_top_n_50     +19.31%  +19.89%   0.9924   1.5592   -34.32%  1.1213   +3.25%   0.4786    63.0%     211
xgb_gr_top_n_25     +19.98%  +19.22%   1.0489   1.8739   -26.16%  1.0613   +4.78%   0.5159    62.6%     211
xgb_gr_top_n_10     +20.20%  +18.96%   1.0706   1.9291   -23.15%  1.0041   +5.82%   0.4961    62.6%     211
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_pct_20                  13.5%              1.35         16.23
top_pct_10                  16.3%              1.63         19.60
top_n_50                    17.2%              1.72         20.66
top_n_25                    19.9%              1.99         23.84
top_n_10                    25.6%              2.56         30.70
```


## Single-Factor Baseline Turnover

```
Factor (top20%)      Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
f_low_ps                     8.9%              0.89         10.72
f_high_fcf_yield            12.6%              1.26         15.12
f_high_div_yield             9.6%              0.96         11.55
f_low_evebitda              12.7%              1.27         15.19
f_low_pe                    12.1%              1.21         14.56
f_high_earnings_yield          12.1%              1.21         14.51
```


## Guardrailed Portfolio Turnover (value traps excluded, max_missing=2)

```
Portfolio              Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
------------------------------------------------------------------------
gr_top_pct_20                 15.1%              1.51         18.15
gr_top_pct_10                 17.0%              1.70         20.37
gr_top_n_50                   16.9%              1.69         20.34
gr_top_n_25                   19.5%              1.95         23.38
gr_top_n_10                   24.1%              2.41         28.87
xgb_gr_top_pct_20             24.8%              2.48         29.73
xgb_gr_top_pct_10             29.3%              2.93         35.11
xgb_gr_top_n_50               29.1%              2.91         34.86
xgb_gr_top_n_25               33.0%              3.30         39.64
xgb_gr_top_n_10               41.6%              4.16         49.90
```


## XGBoost Model Turnover

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
xgb_top_pct_20              23.5%              2.35         28.24
xgb_top_pct_10              28.1%              2.81         33.70
xgb_top_n_50                29.3%              2.93         35.11
xgb_top_n_25                34.4%              3.44         41.23
xgb_top_n_10                43.2%              4.32         51.81
```
