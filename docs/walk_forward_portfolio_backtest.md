# Walk-Forward Portfolio Backtest — Fundamentals Alpha

Periodic retrain (one XGBoost model per fold, never scoring data it was trained on or after),
fold-safe sector z-scoring. Contrast with `docs/backtest_results_model*.md`, which score ONE
static model across up to ~40 years using per-month self-referential normalization — a
different, less rigorous methodology (see historic_fundamentals/model.py's
`generate_walk_forward_oos_scores()` docstring).

**Date range (walk-forward-evaluable)**: 1991-03-31 to 2026-06-30
 (36 folds, train=5y / test=1y / embargo=12mo)

**TC**: 10 bps one-way | **Sector cap**: 25%


## Results (wf_ = walk-forward OOS model, composite_ = same-window composite-score control)

```
Portfolio                 CAGR    AnnVol   Sharpe     MaxDD  WinRate  Months
----------------------------------------------------------------------------
wf_top_pct_20          +18.20%   +20.04%    0.940   -42.21%  +62.65%     423
wf_top_pct_10          +18.79%   +21.65%    0.908   -44.08%  +64.30%     423
wf_top_n_50            +20.14%   +29.64%    0.769   -52.54%  +60.76%     423
wf_top_n_25            +20.76%   +33.26%    0.732   -61.66%  +59.34%     423
wf_top_n_10            +16.51%   +31.12%    0.649   -68.74%  +58.87%     423
composite_top_pct_20   +18.27%   +16.32%    1.117   -47.07%  +67.38%     423
composite_top_pct_10   +19.48%   +17.41%    1.116   -46.14%  +62.88%     423
composite_top_n_50     +20.58%   +23.33%    0.922   -56.25%  +63.83%     423
composite_top_n_25     +22.84%   +26.02%    0.923   -50.09%  +61.70%     423
composite_top_n_10     +23.32%   +25.60%    0.950   -52.03%  +61.94%     423
universe_ew            +15.48%   +16.75%    0.949   -43.01%  +64.54%     423
SPY                     +8.85%   +15.92%    0.619   -61.22%  +64.54%     423
```
