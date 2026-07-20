# Composite Score — Rank IC and Top/Bottom Spread Analysis

Ad hoc analysis run 2026-07-20 to close a gap in the Phase 11 acceptance checklist
(no direct IC measurement existed for the composite score prior to this — only
portfolio-level backtest metrics). Universe: `UNIVERSE_DEFAULTS` (market_cap >= $1B,
price >= $5, ex-Financials/Real-Estate, ADV >= $5M where available), full available
history (`monthly_pe` spans 1983-2026), composite score via
`_compute_pit_composite_score(sector_neutral=False)`.

## Monthly cross-sectional rank IC

Spearman correlation between composite score and forward return, computed per month,
averaged across all months with >= 30 tickers.

| Forward horizon | N months | Mean IC | IC std | ICIR | % months IC > 0 |
|---|---:|---:|---:|---:|---:|
| 1 month | 475 | 0.0139 | 0.0668 | 0.21 | 59.6% |
| 12 months | 472 | 0.0346 | 0.1240 | 0.28 | 59.3% |

Small but real and consistently-signed — comparable in magnitude to a modest, usable
factor (for reference, the retired XGBoost model's 12-month OOS rank IC was -0.017,
i.e. flat/slightly negative — see `features/historic_fundamentals/fundamentals_alpha_action_plan.md`
and `walk_forward_portfolio_backtest.md`).

## Top-N vs. bottom-N spread (mean forward return)

Each month, sort by composite score descending, compare the top-N and bottom-N
tickers' mean forward return.

**1-month forward:**

| Top/Bottom N | Top mean | Bottom mean | Spread | N months |
|---:|---:|---:|---:|---:|
| 25 | +0.87% | +0.51% | **+0.36%** | 450 |
| 50 | +0.71% | +0.70% | +0.01% | 426 |
| 100 | +0.69% | +2.07% | **-1.37%** | 400 |
| 190 (~decile) | +0.63% | +1.43% | **-0.80%** | 367 |

**12-month forward** (same pattern, larger magnitudes):

| Top/Bottom N | Top mean | Bottom mean | Spread |
|---:|---:|---:|---:|
| 25 | +8.99% | +4.98% | **+4.02%** |
| 50 | +8.60% | +6.95% | +1.65% |
| 100 | +8.07% | +22.93% | **-14.86%** |
| 190 (~decile) | +7.41% | +16.06% | **-8.65%** |

## Important finding: the edge is concentrated at the extreme top, and inverts at broader cuts

This is not noise or a computation artifact (checked at two horizons, same pattern both
times): the composite score's positive predictive spread holds at top 25 and roughly
breaks even at top 50, but **inverts** at top 100 and broader (~decile) cuts — the
bottom of the ranking outperforms on average at those wider cuts. The traded
configuration in this pipeline (`top_n_25`, and the live `vw_gr_top_n_25` strategy) sits
squarely in the positive-spread zone, so this does not undermine the currently-deployed
strategy's evidence. It does mean the composite score should **not** be characterized as
a broadly monotonic quality/value signal across the full ranking — it is closer to "the
top ~25-50 names are identifiably better than average," not "higher score = uniformly
better across the board."

**Open question, not resolved here:** this cross-sectional spread finding is in tension
with `docs/walk_forward_portfolio_backtest.md`'s `composite_top_pct_20` result (top 20%,
~380 tickers, walk-forward-restricted window 1991-2026), which showed a *positive*
CAGR/Sharpe edge over universe-EW at that broader cut. Candidate explanations not yet
tested: (a) date-range mismatch — this analysis uses the full 1983-2026 history
(including sparser, noisier early-1980s data) vs. the portfolio backtest's
1991-2026-restricted window; (b) compounded monthly-rebalanced portfolio return vs.
simple average single-period cross-sectional spread are genuinely different statistics
and can diverge under return-distribution skew. Flagged as a follow-up item, not blocking
for the top_n_25 configuration actually in use.
