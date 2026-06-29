# Backtest Results

**Universe**: 1797 tickers

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
top_pct_20          +17.27%  +17.35%   1.0114   1.4294   -46.92%  0.8430   +9.71%   0.6887    66.3%     483
top_pct_10          +17.72%  +17.84%   1.0092   1.6193   -48.25%  0.7891  +10.10%   0.5657    62.0%     482
top_n_50            +19.86%  +18.51%   1.0786   1.5622   -51.06%  0.8439  +12.29%   0.7848    64.0%     483
top_n_25            +19.24%  +20.12%   0.9818   1.4204   -56.69%  0.8139  +11.94%   0.6304    62.7%     483
top_n_10            +20.03%  +24.57%   0.8685   1.4587   -50.53%  0.8290  +12.60%   0.5464    60.9%     483
universe_ew         +14.70%  +17.61%   0.8727   1.1878   -43.39%  0.9036   +6.59%   0.5446    64.0%     483
SPY                  +9.54%  +16.00%   0.6554   0.7564   -61.22%     N/A      N/A      N/A    63.9%     521
f_low_ps            +18.04%  +19.53%   0.9521   1.4805   -46.20%  0.9169   +9.19%   0.6129    63.1%     482
f_high_fcf_yield    +16.66%  +18.09%   0.9482   1.3020   -43.65%  0.8701   +9.09%   0.6296    65.6%     442
f_high_div_yield    +15.43%  +15.52%   1.0080   1.3649   -35.18%  0.6195  +11.27%   0.5788    65.3%     329
f_low_evebitda      +15.42%  +18.29%   0.8807   1.2276   -44.58%  0.8255   +8.02%   0.4783    63.8%     483
f_low_pe            +14.81%  +17.27%   0.8909   1.2765   -47.04%  0.7935   +7.15%   0.3925    62.9%     482
f_high_earnings_yield  +14.03%  +17.57%   0.8401   1.1251   -47.54%  0.8171   +6.70%   0.3998    62.5%     483
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_pct_20                  16.8%              1.68         20.20
top_pct_10                  20.8%              2.08         24.95
top_n_50                    19.8%              1.98         23.82
top_n_25                    23.0%              2.30         27.56
top_n_10                    29.2%              2.92         35.01
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
