# Backtest Results

**Universe**: 1920 tickers

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
top_pct_20          +17.31%  +17.32%   1.0148   1.4574   -46.76%  0.8376   +9.83%   0.6903    66.0%     483
top_pct_10          +17.41%  +18.32%   0.9739   1.4254   -47.18%  0.8178  +10.11%   0.6082    62.7%     483
top_n_50            +19.55%  +19.43%   1.0235   1.4737   -56.74%  0.8405  +12.04%   0.7057    63.6%     483
top_n_25            +19.66%  +21.70%   0.9413   1.4235   -53.30%  0.8457  +12.11%   0.6160    63.4%     483
top_n_10            +21.11%  +25.40%   0.8835   1.4634   -52.25%  0.8517  +13.51%   0.5820    61.3%     483
universe_ew         +14.74%  +17.56%   0.8768   1.1914   -42.98%  0.9008   +6.71%   0.5528    64.2%     483
SPY                  +9.49%  +16.01%   0.6528   0.7550   -61.22%     N/A      N/A      N/A    63.7%     521
f_low_ps            +17.91%  +19.66%   0.9415   1.4415   -44.98%  0.9175   +9.10%   0.6014    62.9%     482
f_high_fcf_yield    +16.67%  +18.02%   0.9515   1.2991   -43.79%  0.8664   +9.18%   0.6346    64.9%     442
f_high_div_yield    +15.47%  +15.41%   1.0163   1.3777   -34.65%  0.6158  +11.37%   0.5871    66.0%     329
f_low_evebitda      +15.77%  +17.97%   0.9099   1.3102   -44.51%  0.8195   +7.89%   0.4573    63.5%     482
f_low_pe            +14.81%  +17.21%   0.8937   1.2815   -47.03%  0.7903   +7.22%   0.3960    63.1%     482
f_high_earnings_yield  +13.94%  +17.54%   0.8367   1.1222   -47.37%  0.8137   +6.68%   0.3952    62.9%     483
xgb_top_pct_20      +19.04%  +20.91%   0.9452   1.3528   -42.30%  0.9782  +10.31%   0.7213    63.4%     483
xgb_top_pct_10      +19.10%  +22.46%   0.8970   1.3102   -40.60%  1.0299   +9.91%   0.6796    62.7%     483
xgb_top_n_50        +20.07%  +24.57%   0.8718   1.4108   -39.55%  1.0527  +10.68%   0.6488    63.1%     483
xgb_top_n_25        +19.19%  +28.25%   0.7644   1.2855   -42.99%  1.0595   +9.74%   0.5187    58.8%     483
xgb_top_n_10        +24.23%  +32.39%   0.8320   1.4930   -49.86%  1.1032  +14.38%   0.6283    58.8%     483
gr_top_pct_20       +13.98%  +18.37%   0.8085   1.1210   -46.10%  0.7534   +7.33%   0.3472    64.6%     404
gr_top_pct_10       +15.15%  +19.27%   0.8335   1.1252   -44.97%  0.7074   +8.81%   0.3746    64.8%     403
gr_top_n_50         +17.16%  +19.13%   0.9293   1.3215   -46.71%  0.7203  +10.80%   0.4983    65.3%     404
gr_top_n_25         +17.99%  +20.46%   0.9150   1.3533   -42.27%  0.6358  +12.37%   0.4746    66.8%     404
gr_top_n_10         +16.86%  +21.57%   0.8341   1.2931   -36.66%  0.6281  +11.31%   0.4069    62.4%     404
xgb_gr_top_pct_20   +13.95%  +20.24%   0.7507   1.0540   -44.49%  0.8554   +6.39%   0.3544    62.6%     404
xgb_gr_top_pct_10   +15.19%  +20.80%   0.7877   1.1464   -42.10%  0.8554   +7.63%   0.4132    64.4%     404
xgb_gr_top_n_50     +15.36%  +20.63%   0.7997   1.1682   -39.85%  0.8149   +8.16%   0.4091    64.4%     404
xgb_gr_top_n_25     +14.31%  +22.09%   0.7205   1.0088   -41.67%  0.8574   +6.73%   0.3475    62.6%     404
xgb_gr_top_n_10     +15.87%  +24.91%   0.7221   0.9647   -47.39%  0.8331   +8.51%   0.3836    61.9%     404
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_pct_20                  16.8%              1.68         20.10
top_pct_10                  20.6%              2.06         24.66
top_n_50                    21.5%              2.15         25.80
top_n_25                    25.5%              2.55         30.66
top_n_10                    30.5%              3.05         36.64
```


## Single-Factor Baseline Turnover

```
Factor (top20%)      Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
f_low_ps                    12.6%              1.26         15.14
f_high_fcf_yield            15.0%              1.50         18.04
f_high_div_yield            10.3%              1.03         12.34
f_low_evebitda              15.1%              1.51         18.16
f_low_pe                    14.8%              1.48         17.70
f_high_earnings_yield          14.2%              1.42         17.04
```


## Guardrailed Portfolio Turnover (value traps excluded, max_missing=2)

```
Portfolio              Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
------------------------------------------------------------------------
gr_top_pct_20                 15.8%              1.58         18.93
gr_top_pct_10                 19.9%              1.99         23.92
gr_top_n_50                   20.6%              2.06         24.70
gr_top_n_25                   23.2%              2.32         27.89
gr_top_n_10                   27.2%              2.72         32.63
xgb_gr_top_pct_20             26.8%              2.68         32.13
xgb_gr_top_pct_10             33.8%              3.38         40.58
xgb_gr_top_n_50               37.7%              3.77         45.20
xgb_gr_top_n_25               41.7%              4.17         50.03
xgb_gr_top_n_10               48.6%              4.86         58.31
```


## XGBoost Model Turnover

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
xgb_top_pct_20              26.4%              2.64         31.74
xgb_top_pct_10              30.8%              3.08         36.95
xgb_top_n_50                30.6%              3.06         36.72
xgb_top_n_25                36.1%              3.61         43.37
xgb_top_n_10                42.5%              4.25         51.01
```
