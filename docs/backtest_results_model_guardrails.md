# Backtest Results

**Universe**: 1912 tickers

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
top_pct_20          +16.05%  +17.34%   0.9524   1.2665   -47.99%  0.8280   +8.68%   0.5811    64.5%     484
top_pct_10          +19.07%  +18.45%   1.0446   1.6138   -47.93%  0.8199  +11.16%   0.6504    63.5%     482
top_n_50            +19.39%  +18.03%   1.0809   1.5206   -47.78%  0.8692  +11.65%   0.8359    65.3%     484
top_n_25            +20.53%  +18.95%   1.0878   1.5881   -51.78%  0.8577  +12.89%   0.8171    65.5%     484
top_n_10            +20.99%  +22.45%   0.9667   1.4754   -54.42%  0.8405  +13.51%   0.6526    62.8%     484
universe_ew         +14.75%  +17.52%   0.8789   1.1909   -43.05%  0.9018   +6.72%   0.5595    63.8%     484
SPY                  +9.48%  +15.99%   0.6522   0.7536   -61.22%     N/A      N/A      N/A    63.8%     522
f_low_ps            +18.18%  +19.29%   0.9678   1.4662   -44.87%  0.9112   +9.44%   0.6349    62.7%     483
f_high_fcf_yield    +17.33%  +17.97%   0.9853   1.3416   -43.31%  0.8538   +9.96%   0.6720    65.7%     443
f_high_div_yield    +15.42%  +15.23%   1.0234   1.3881   -33.93%  0.6369  +11.19%   0.6143    66.1%     330
f_low_evebitda      +15.51%  +18.27%   0.8852   1.2420   -44.73%  0.8269   +8.14%   0.4901    63.4%     484
f_low_pe            +14.29%  +17.51%   0.8554   1.1653   -46.98%  0.8068   +7.11%   0.4180    62.4%     484
f_high_earnings_yield  +14.17%  +17.41%   0.8531   1.1511   -47.28%  0.8105   +6.95%   0.4154    63.2%     484
xgb_top_pct_20      +18.31%  +20.87%   0.9169   1.2714   -41.46%  0.9465   +9.88%   0.6497    63.0%     484
xgb_top_pct_10      +17.21%  +23.61%   0.7962   1.1294   -69.18%  0.9560   +8.58%   0.4905    61.5%     483
xgb_top_n_50        +20.79%  +20.77%   1.0206   1.5018   -37.39%  0.9506  +12.32%   0.8084    64.3%     484
xgb_top_n_25        +23.44%  +22.83%   1.0430   1.6609   -38.71%  0.9142  +15.30%   0.7968    64.3%     484
xgb_top_n_10        +24.17%  +24.54%   1.0107   1.6592   -37.35%  0.9309  +15.88%   0.7672    63.2%     484
gr_top_pct_20       +14.53%  +18.76%   0.8223   1.0443   -46.48%  0.7544   +7.69%   0.3608    64.8%     403
gr_top_pct_10       +16.07%  +19.79%   0.8578   1.1342   -46.15%  0.7450   +9.30%   0.4222    64.2%     402
gr_top_n_50         +15.83%  +18.59%   0.8889   1.2387   -46.46%  0.7814   +8.95%   0.4718    64.7%     405
gr_top_n_25         +16.67%  +18.99%   0.9124   1.2549   -46.32%  0.7620   +9.96%   0.4984    65.4%     405
gr_top_n_10         +17.75%  +19.80%   0.9294   1.3680   -45.60%  0.7144  +11.45%   0.5103    65.2%     405
xgb_gr_top_pct_20   +12.80%  +19.73%   0.7136   0.9401   -42.48%  0.7952   +5.79%   0.2753    64.9%     405
xgb_gr_top_pct_10   +13.19%  +20.12%   0.7209   0.9701   -36.68%  0.7293   +6.75%   0.2746    61.5%     403
xgb_gr_top_n_50     +14.49%  +19.07%   0.8093   1.1600   -42.11%  0.8041   +7.40%   0.3887    64.0%     405
xgb_gr_top_n_25     +15.12%  +19.39%   0.8280   1.1594   -40.61%  0.7585   +8.44%   0.3989    63.2%     405
xgb_gr_top_n_10     +15.67%  +20.71%   0.8103   1.1558   -40.75%  0.6521   +9.92%   0.3708    63.2%     405
```


## Turnover and Transaction Cost Drag

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
top_pct_20                  15.6%              1.56         18.70
top_pct_10                  19.8%              1.98         23.74
top_n_50                    16.3%              1.63         19.57
top_n_25                    19.9%              1.99         23.88
top_n_10                    25.6%              2.56         30.76
```


## Single-Factor Baseline Turnover

```
Factor (top20%)      Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
f_low_ps                    12.0%              1.20         14.39
f_high_fcf_yield            14.7%              1.47         17.63
f_high_div_yield            10.3%              1.03         12.41
f_low_evebitda              14.4%              1.44         17.23
f_low_pe                    14.4%              1.44         17.32
f_high_earnings_yield          14.2%              1.42         17.03
```


## Guardrailed Portfolio Turnover (value traps excluded, max_missing=2)

```
Portfolio              Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
------------------------------------------------------------------------
gr_top_pct_20                 17.0%              1.70         20.40
gr_top_pct_10                 21.0%              2.10         25.18
gr_top_n_50                   16.2%              1.62         19.42
gr_top_n_25                   18.9%              1.89         22.66
gr_top_n_10                   24.5%              2.45         29.44
xgb_gr_top_pct_20             27.8%              2.78         33.41
xgb_gr_top_pct_10             33.3%              3.33         40.01
xgb_gr_top_n_50               28.0%              2.80         33.55
xgb_gr_top_n_25               32.9%              3.29         39.51
xgb_gr_top_n_10               40.4%              4.04         48.49
```


## XGBoost Model Turnover

```
Portfolio            Avg Turnover   Avg TC/Mo (bps)   Ann TC Drag
----------------------------------------------------------------------
xgb_top_pct_20              25.7%              2.57         30.88
xgb_top_pct_10              32.7%              3.27         39.27
xgb_top_n_50                25.3%              2.53         30.40
xgb_top_n_25                29.8%              2.98         35.71
xgb_top_n_10                37.6%              3.76         45.17
```
