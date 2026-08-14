# Fibonacci Retracement Factor Test

Evaluates the classic technical-analysis idea of buying pullbacks at Fibonacci
retracement levels, backfilled into `monthly_pe` by
`scripts/backfill_fibonacci_factors.py`:

- `fib_retracement_pct` = (52wk high − price) / (52wk high − 52wk low). 0.0 = at
  the high, 1.0 = at the low. Swing high/low use the "auto-fib" convention most
  charting tools default to (highest-high / lowest-low of a lookback window),
  not a strictly sequenced up-leg.
- `fib_618_proximity` = −|`fib_retracement_pct` − 0.618|. Higher = closer to the
  golden-ratio 61.8% pullback level, the single most cited Fibonacci entry level.
- `fib_in_golden_zone` = 1 if retracement is inside the 38.2%–61.8% band, else 0.
- `above_200dma` = 1 if price is above its trailing 200-day SMA — textbook
  Fibonacci usage restricts retracement entries to stocks already in an
  established uptrend, so this is used both as a universe filter and to check
  whether the signal only works (or only fails) in that regime.

Coverage after backfill: 97.2% of monthly_pe rows (2,638 tickers).

## 1. IC test (Spearman rank IC vs forward returns, market-wide and uptrend-only)

| factor | horizon | universe | mean IC | ICIR (NW) | hit rate | t-stat |
|---|---|---|---|---|---|---|
| `fib_618_proximity` | ret_1m | market-wide | -0.0105 | -1.68 | 45.8% | -1.61 |
| `fib_618_proximity` | ret_1m | uptrend-only | +0.0020 | 0.30 | 45.9% | 0.30 |
| `fib_618_proximity` | ret_3m | market-wide | -0.0193 | -2.35 | 43.9% | -3.16 |
| `fib_618_proximity` | ret_3m | uptrend-only | -0.0024 | -0.30 | 47.2% | -0.38 |
| `fib_618_proximity` | ret_6m | market-wide | -0.0269 | -2.80 | 43.2% | -4.59 |
| `fib_618_proximity` | ret_6m | uptrend-only | -0.0024 | -0.26 | 44.4% | -0.40 |
| `fib_618_proximity` | ret_1y | market-wide | -0.0328 | -3.06 | 38.8% | -5.59 |
| `fib_618_proximity` | ret_1y | uptrend-only | -0.0047 | -0.45 | 47.2% | -0.80 |
| `fib_in_golden_zone` | ret_1y | market-wide | -0.0143 | -1.97 | 46.5% | -3.16 |
| `fib_in_golden_zone` | ret_1y | uptrend-only | -0.0139 | -1.63 | 37.9% | -2.75 |

Every horizon, both universes: IC is at best statistically indistinguishable
from zero (uptrend-only, short horizons) and at worst reliably **negative**
(market-wide, longer horizons — t-stat -5.59 at 1yr). Being closer to a 61.8%
pullback does not predict better forward returns anywhere in this test; if
anything, on the full market it mildly predicts worse ones.

## 2. Quintile spread (Q1 best/closest to golden zone − Q5 worst)

```
                                ret_3m spread    ret_1y spread
market-wide, fib_618_proximity      -0.79%           -2.63%
uptrend-only, fib_618_proximity     -0.43%           -0.83%
```

Spread is negative in every cut tested — Q5 (furthest from the golden-ratio
level) outperforms Q1 on average. Consistent with the IC results.

## 3. Pure Fibonacci backtest (rank by fib_618_proximity, uptrend universe only,
no guardrails, no fundamentals)

```
Portfolio                       CAGR     Sharpe   MaxDD    WinRate  Months
fibonacci_top_n_25             +79.91%   3.722   -12.22%   87.9%    480
fibonacci_top_n_30             +77.20%   3.810   -11.41%   89.6%    480
fibonacci_top_pct_20           +75.97%   4.411   -14.58%   91.6%    475
universe_ew (uptrend univ.)    +39.23%   2.622   -11.37%   77.7%    480
SPY                             +9.45%   0.650   -61.22%   63.6%    522
```

**These numbers are not credible and should not be read as a positive
result.** An 80% CAGR / 3.7 Sharpe long-only large-cap strategy over 40 years
is not a real edge — it is a symptom of the survivorship bias already flagged
as unresolved in this project (`monthly_pe` only contains tickers currently
tracked by the pipeline, i.e. no delisted/bankrupt names). Restricting to
"above 200dma" compounds that bias: it doesn't carry the forward-looking risk
it would in a point-in-time universe that includes real delistings, because
every ticker in the sample is, by construction, one that survived to the
present. The equal-weight uptrend benchmark itself (Sharpe 2.6, no factor
involved at all) shows the inflation isn't specific to the Fibonacci ranking —
it's the universe. Section 3 is included for completeness but is
uninterpretable evidence either way, not a result to act on.

## 4. Augmented composite A/B (sector-neutral, guardrailed, top_n_25, identical
universe/dates, both computed in the same run)

```
                                             CAGR     Sharpe    MaxDD    WinRate  Months
baseline (current live factors)            +15.96%   0.952   -40.07%   66.0%    406
augmented (+fib_618_proximity)             +14.48%   0.873   -41.64%   64.0%    406
```

Worse on every metric.

## 5. Walk-forward fold stability (36 non-overlapping annual test folds,
train=5y/test=1y, same fold structure as `walk_forward_portfolio_backtest.py`)

**Augmented beats baseline in 9 / 35 valid folds (26%)** — a clean, consistent
loss, not a coin flip. Full breakdown in
`scripts/test_fibonacci_walkforward.py` output.

## Conclusion

Rejected outright — the weakest of the technical/quant factor experiments
tried in this project so far (CANSLIM, Greenblatt subset both landed closer to
a coin flip; this one loses cleanly on IC, quintile spread, full-period
composite metrics, and fold win rate simultaneously). **Not promoted.**
`fib_retracement_pct`, `fib_618_proximity`, `fib_in_golden_zone`, and
`above_200dma` columns are kept in `monthly_pe` for reference, same treatment
as the PEGY growth-rate columns, but nothing in
`historic_fundamentals/baselines.py` changes.

This matches the base-rate expectation from the theory itself: Fibonacci
retracement levels have no structural link to equity risk premia — any
apparent effect in unfiltered technical-analysis lore is best explained by
self-fulfilling attention (enough discretionary traders watch 61.8% that it
becomes a soft, short-lived magnet on intraday/daily charts), not something
that should show up in a monthly cross-sectional forward-return test on a
$1B+ market cap universe.
