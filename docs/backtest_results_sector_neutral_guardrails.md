# Backtest Results

**Universe**: 1798 tickers

**Filters**: min_market_cap=1000000000 | min_price=5.00

**TC**: 10 bps one-way per trade

**Signal**: sector-neutral composite baseline (value+quality+momentum where available)

**Rebalancing**: monthly equal-weight, non-overlapping 1-month returns


## Portfolio weighting

All portfolios in this backtest are equal-weight (each selected stock receives an equal allocation at each monthly rebalance).

Capped-weight portfolios (e.g., max 5% per position) are deferred to Phase 7 risk diagnostics, where position concentration limits are configured as guardrails.


## Performance Summary

```
Portfolio              CAGR   AnnVol   Sharpe  Sortino     MaxDD    Beta    Alpha       IR  WinRate  Months
--------------------------------------------------------------------------------------------------------------
top_pct_20          +16.54%  +17.24%   0.9801   1.4008   -45.68%  0.8455   +8.96%   0.6439    65.2%     483
top_pct_10          +16.05%  +17.65%   0.9370   1.3992   -44.60%  0.7936   +8.94%   0.5227    65.6%     483
top_n_50            +18.16%  +18.17%   1.0164   1.4474   -42.96%  0.8569  +10.48%   0.7117    66.5%     483
top_n_25            +18.16%  +19.78%   0.9493   1.3473   -50.23%  0.8201  +10.81%   0.5887    63.6%     483
top_n_10            +18.95%  +23.58%   0.8580   1.2873   -51.49%  0.7151  +12.54%   0.4863    63.1%     483
universe_ew         +14.70%  +17.61%   0.8727   1.1878   -43.39%  0.9036   +6.60%   0.5455    64.0%     483
SPY                  +9.53%  +16.00%   0.6549   0.7559   -61.22%     N/A      N/A      N/A    63.9%     521
f_low_ps            +18.04%  +19.53%   0.9521   1.4805   -46.20%  0.9169   +9.20%   0.6135    63.1%     482
f_high_fcf_yield    +16.66%  +18.09%   0.9482   1.3020   -43.65%  0.8701   +9.10%   0.6304    65.6%     442
f_high_div_yield    +15.43%  +15.52%   1.0080   1.3649   -35.18%  0.6196  +11.27%   0.5798    65.3%     329
f_low_evebitda      +15.42%  +18.29%   0.8807   1.2276   -44.58%  0.8255   +8.03%   0.4789    63.8%     483
f_low_pe            +14.81%  +17.27%   0.8909   1.2765   -47.04%  0.7936   +7.16%   0.3932    62.9%     482
f_high_earnings_yield  +14.03%  +17.57%   0.8401   1.1251   -47.54%  0.8171   +6.71%   0.4005    62.5%     483
gr_top_pct_20       +13.09%  +18.63%   0.7585   0.9767   -43.25%  0.7521   +6.41%   0.2869    64.6%     404
gr_top_pct_10       +14.19%  +18.96%   0.7999   1.0554   -41.28%  0.7090   +7.72%   0.3174    64.7%     402
gr_top_n_50         +16.72%  +18.19%   0.9471   1.3305   -40.88%  0.7821   +9.78%   0.5379    65.6%     404
gr_top_n_25         +16.24%  +19.41%   0.8775   1.2403   -44.60%  0.7416   +9.65%   0.4489    64.9%     404
gr_top_n_10         +16.58%  +23.06%   0.7821   1.1993   -39.79%  0.5616  +11.60%   0.3637    64.4%     404
vw_gr_top_pct_20    +13.28%  +17.40%   0.8086   1.0238   -40.02%  0.6928   +7.13%   0.2924    65.8%     404
vw_gr_top_pct_10    +14.48%  +17.78%   0.8549   1.1008   -37.00%  0.6661   +8.40%   0.3340    64.9%     402
vw_gr_top_n_50      +16.56%  +16.90%   0.9974   1.3698   -36.36%  0.7348  +10.03%   0.5420    67.6%     404
vw_gr_top_n_25      +15.67%  +17.97%   0.9050   1.2443   -40.43%  0.7134   +9.33%   0.4361    66.1%     404
vw_gr_top_n_10      +15.96%  +21.37%   0.8028   1.1917   -38.88%  0.6006  +10.62%   0.3606    63.9%     404
rf_gr_top_pct_20    +12.56%  +15.97%   0.8257   0.9968   -36.66%  0.5894   +7.33%   0.2271    65.8%     404
rf_gr_top_pct_10    +13.67%  +16.31%   0.8729   1.0751   -36.66%  0.5605   +8.56%   0.2678    64.9%     402
rf_gr_top_n_50      +15.51%  +15.50%   1.0134   1.3385   -25.71%  0.6315   +9.90%   0.4420    67.6%     404
rf_gr_top_n_25      +14.97%  +16.25%   0.9450   1.2777   -29.72%  0.6058   +9.59%   0.3769    66.1%     404
rf_gr_top_n_10      +15.64%  +19.09%   0.8604   1.2324   -28.21%  0.5036  +11.17%   0.3426    63.9%     404
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_pct_20                  16.9%              1.69         20.33
top_pct_10                  21.2%              2.12         25.48
top_n_50                    18.9%              1.89         22.68
top_n_25                    22.6%              2.26         27.09
top_n_10                    29.4%              2.94         35.31
```


## Single-Factor Baseline Turnover

```
Factor (top20%)      Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
f_low_ps                    12.2%              1.22         14.67
f_high_fcf_yield            15.1%              1.51         18.14
f_high_div_yield            10.2%              1.02         12.23
f_low_evebitda              14.8%              1.48         17.72
f_low_pe                    14.6%              1.46         17.58
f_high_earnings_yield          14.0%              1.40         16.77
```


## Guardrailed Portfolio Turnover (value traps excluded, max_missing=2)

```
Portfolio              Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
------------------------------------------------------------------------
gr_top_pct_20                 16.0%              1.60         19.21
gr_top_pct_10                 19.5%              1.95         23.34
gr_top_n_50                   18.3%              1.83         22.00
gr_top_n_25                   21.3%              2.13         25.58
gr_top_n_10                   28.0%              2.80         33.57
```
