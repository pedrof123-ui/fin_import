# Fat-Tails / Gaussian VaR Check

Tests the Mandelbrot point directly (`scripts/analyze_fat_tails.py`): are this
project's return series fat-tailed enough that a Gaussian VaR/CVaR and a
Gaussian drawdown model materially understate real risk? Two series:

1. **SPY daily returns** (1983–2026, n=10,970) — long sample, the textbook case.
2. **composite_baseline monthly returns** (`gr_top_n_25`, same construction as
   the walk-forward scripts, n=406, 1992–2026) — the thing this project would
   actually size capital against.

## Distribution shape

| series | skew | excess kurtosis | Jarque-Bera p |
|---|---|---|---|
| SPY daily | -3.43 | +110.2 | ~0 |
| composite_baseline monthly | -0.47 | +1.55 | 7.2e-13 |

Both reject normality decisively. Daily SPY kurtosis of 110 (Gaussian = 0) is
driven by single-day extremes (Oct 1987, Mar 2020) that a normal distribution
assigns near-zero probability to.

## VaR / CVaR: Gaussian vs. historical (empirical)

```
SPY daily              VaR95   CVaR95   VaR99   CVaR99
  Gaussian              1.92%    2.42%   2.74%    3.14%
  Historical            1.70%    2.75%   3.05%    4.96%   (+58% vs Gaussian)

composite_baseline mo.  VaR95   CVaR95   VaR99   CVaR99
  Gaussian              6.80%    8.88%  10.19%   11.87%
  Historical            6.74%   10.38%  12.47%   16.17%   (+36% vs Gaussian)
```

The 95% VaR numbers are close either way — the Gaussian assumption is roughly
fine in the "ordinary" part of the distribution. The gap opens up specifically
in the tail: **99% CVaR is 36-58% larger empirically than the Gaussian formula
says**, which is exactly where a position-sizing rule calibrated off a
Gaussian VaR would be most wrong, and most expensive to be wrong about.

## Max drawdown: block bootstrap vs. Gaussian-iid simulation

Block bootstrap (resampling contiguous blocks to preserve short-run
autocorrelation/vol clustering) vs. a moment-matched Gaussian iid simulation,
5,000 paths each, same length as the real sample:

```
SPY daily max drawdown           p50    p75    p90    p95    p99
  Block bootstrap (empirical)   -49.1% -42.6% -38.5% -35.1% -30.7%
  Gaussian iid                  -49.1% -43.1% -38.6% -36.4% -32.4%
  Actual realized: -64.9%  (Global Financial Crisis, Oct 2007-Mar 2009)

composite_baseline monthly       p50    p75    p90    p95    p99
  Block bootstrap (empirical)   -35.9% -31.1% -26.7% -22.4% -18.2%
  Gaussian iid                  -31.2% -27.0% -23.8% -22.1% -19.4%
  Actual realized: -40.1%
```

**This is the more interesting, less expected result.** Block bootstrap and
Gaussian-iid land close together for SPY — and *both* badly understate the
actual -64.9% drawdown, even at their 99th percentile (-30.7% / -32.4%). A
20-trading-day block bootstrap was re-run at block sizes of 60/125/250/500
days; even at a 500-day (~2yr) block, the p99 simulated drawdown only reaches
-33.7%, still half the real one.

The reason matters: random block resampling dilutes sustained regime
persistence. The real -64.9% drawdown is one contiguous 17-month event.
Reproducing something that bad in a resampled path requires several
maximally-bad blocks landing back-to-back by chance — a low-probability
combinatorial event that swamps the diversifying effect of the other,
better-behaved blocks drawn into the same path. A plain iid Gaussian
simulation has the identical problem for the opposite reason (no memory
between periods at all). Neither a Gaussian assumption nor naive iid-block
resampling captures multi-year bear-regime clustering — which is precisely
Mandelbrot's original point: markets exhibit long-range dependence and
self-similar volatility clustering *across time scales*, not just fat tails
at a single time scale. A single-period VaR fix (empirical vs. Gaussian)
catches the short-horizon tail; it does not by itself reconstruct
regime-level drawdown risk.

## Conclusion / recommendation

- **Do use empirical/historical VaR and CVaR instead of a Gaussian formula**
  for short-horizon (single-period) risk sizing — the 99% tail is 36-58%
  fatter than Gaussian says, in both the long daily sample and the actual live
  monthly strategy returns. This is a real, decisively-confirmed effect
  (Jarque-Bera p ≈ 0 in both series), not a marginal one.
- **Don't stop at resampling for drawdown/capital-at-risk sizing.** Neither
  block bootstrap nor Gaussian simulation reproduces the worst realized
  drawdown here. For drawdown-based sizing (e.g. "how much capital would
  survive a repeat of 2008"), use explicit historical stress scenarios
  (replay the actual 2000-02, 2007-09, and 2020 episodes against the current
  process) rather than a resampled or parametric distribution — this project
  does not have that today and it would be a reasonable follow-up.
- Not a trading signal — this changes how tail risk should be *measured* for
  sizing/stop decisions, not what to buy.
