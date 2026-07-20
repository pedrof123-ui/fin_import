# Composite Score — Robustness / Sensitivity Check (Phase 9)

Portfolio fixed at top_n_25 (25 stocks, equal-weight, monthly rebalance, 25% sector cap).
Portfolio-SIZE sensitivity already covered by docs/walk_forward_portfolio_backtest.md
(top_pct_20/10, top_n_50/25/10 all computed there) — not repeated here.

```
Variant                           CAGR   Sharpe     MaxDD    AnnVol  Tickers
----------------------------------------------------------------------------
universe_min_cap_300M          +22.46%    0.965   -53.68%   +24.14%     2036
universe_min_cap_1B (baseline)   +19.58%    0.938   -52.39%   +21.70%     1908
universe_min_cap_5B            +17.83%    0.980   -50.90%   +18.60%     1257
tc_0bps                        +19.98%    0.954   -52.20%   +21.70%     1908
tc_10bps (baseline)            +19.58%    0.938   -52.39%   +21.70%     1908
tc_25bps                       +18.98%    0.915   -52.68%   +21.70%     1908
tc_50bps                       +18.00%    0.876   -53.16%   +21.71%     1908
tc_100bps                      +16.04%    0.797   -54.10%   +21.73%     1908
scoring_raw (baseline)         +19.58%    0.938   -52.39%   +21.70%     1908
scoring_sector_neutral         +17.40%    0.851   -53.38%   +21.77%     1908
```
