# Greenblatt "Magic Formula" Factor Test

Evaluates two factors taken directly from Joel Greenblatt's *The Little Book That
Still Beats the Market* (Appendix formulas), backfilled into `monthly_pe` by
`scripts/backfill_greenblatt_factors.py`:

- `ebit_ev_yield`  = TTM EBIT / Enterprise Value (EV = `ev_ebitda * ttm_ebitda`)
- `greenblatt_roc` = TTM EBIT / (Net Working Capital + Net Fixed Assets), excluding
  goodwill/intangibles from capital employed (unlike the existing `roic` column,
  which is NOPAT / (equity + debt − cash) and does include goodwill via equity)

Coverage after backfill: `ebit_ev_yield` 79.9%, `greenblatt_roc` 82.2% of monthly_pe
rows (2,638 tickers, comparable to existing factor coverage).

## Bug found & fixed en route

`_join_sector()` in `scripts/run_backtest.py` merged `company_overview` (which has
up to 4 historical snapshot rows per ticker — sector is identical across snapshots,
just refreshed on different `fetch_date`s) without deduplicating first. The left
join fanned out 645K monthly_pe rows to 1.75M, silently overweighting tickers with
more refresh history in every backtest that calls this shared function —
`walk_forward_portfolio_backtest.py`, `run_walkforward.py`, and
`composite_robustness_check.py` all import it. Fixed by deduping to the latest
snapshot per ticker (same pattern `score_live.py`'s `_join_overview` already used
correctly). The documented `gr_top_n_25` baseline (17.0% CAGR / 0.960 Sharpe, cited
in `score_live.py`'s `_BACKTEST_METRICS`) was generated before this fix and should
be regenerated.

## 1. IC test (ret_1y, 431 months, universe: mkt cap ≥ $1B, financials/REITs excluded)

| factor | mean IC | ICIR | hit rate | t-stat |
|---|---|---|---|---|
| `ebit_ev_yield` | 0.0499 | 0.341 | 65.4% | 7.08 |
| `greenblatt_roc` | 0.0181 | 0.153 | 60.5% | 3.17 |
| `earnings_yield` (existing) | 0.0508 | 0.382 | 66.7% | 7.93 |
| `ebitda_ev_yield` (existing) | 0.0609 | 0.392 | 66.1% | 8.15 |
| `roic` (existing) | 0.0274 | 0.260 | 62.4% | 5.40 |

Both new factors are statistically real but weaker than the existing factor already
doing that job in the composite. `ebitda_ev_yield` beats `ebit_ev_yield` on every
metric; `roic` beats `greenblatt_roc` on every metric.

## 2. Quintile spread (ret_1y, Q1 best − Q5 worst)

`greenblatt_roc` spread is **negative** (-1.68%), i.e. inverted under a naive
market-wide sort — likely driven by mega-caps with structurally negative working
capital (Apple/Amazon-type balance sheets) posting extreme ROC values without
matching forward returns. `roic` shows the same pattern (-1.00%), so this is a
known characteristic of goodwill-blind quality metrics on this universe, not unique
to the new factor. IC (rank-based) is more robust to this than raw quintile
bucketing.

## 3. Pure Greenblatt replication (literal 2-factor rank-sum, market-wide, not
sector-neutral, no guardrails, financials/REITs excluded — matches the book exactly)

```
Portfolio                       CAGR    Sharpe    MaxDD   WinRate  Months
greenblatt_top_n_25            +19.79%   1.127   -37.12%   65.0%    483
greenblatt_top_n_30            +19.19%   1.096   -34.94%   64.6%    483
greenblatt_top_pct_20          +17.06%   1.041   -42.05%   66.0%    483
universe_ew (greenblatt univ.) +14.84%   0.922   -43.49%   65.8%    483
SPY                             +9.48%   0.652   -61.22%   63.8%    522
```

Strong standalone result — beats its own universe and SPY by a wide margin. Not
guardrailed or sector-capped, so not directly comparable to the live process.

## 4. Augmented composite A/B (sector-neutral, guardrailed, top_n_25, identical
universe/dates, both computed in the same run)

```
                                              CAGR    Sharpe    MaxDD   WinRate  Months
baseline (current live factors)             +15.96%   0.952   -40.07%   66.0%    406
augmented (+ebit_ev_yield +greenblatt_roc)  +17.02%   0.996   -44.67%   65.3%    406
```

## 5. Walk-forward fold stability (36 non-overlapping annual test folds, train=5y/
test=1y, same fold structure as `walk_forward_portfolio_backtest.py`)

**Augmented beats baseline in 18 / 35 valid folds (51%)** — full period breakdown in
`scripts/test_greenblatt_walkforward.py` output. Folds 2-6 (1992-1996) show
identical returns for both composites, likely because the pre-1997 universe is
narrow enough per sector that the 25%-sector-cap selection absorbs most eligible
names regardless of exact score ranking, making the extra two factors moot in that
period. Excluding those ties, the win rate is 18/30 (60%) — a modest, not dominant,
edge, concentrated in a handful of standout folds (2009-10: +42.9%→+56.7%,
2020-21: +40.1%→+55.4%, 2016-17: +14.6%→+23.0%) offsetting many near-coin-flip
folds elsewhere.

## Conclusion

Neither factor individually beats the existing proxy it would replace/complement
(`ebitda_ev_yield`, `roic`). The full-period composite-level Sharpe gain (0.952 →
0.996) does not hold up as a consistent period-by-period edge — fold win rate is
close to a coin flip once the low-breadth early-1990s ties are excluded. **Not
promoted into the live composite** (`historic_fundamentals/baselines.py`
`_VALUE_COLS`/`_QUALITY_COLS` left untouched). `ebit_ev_yield` and `greenblatt_roc`
columns are kept in `monthly_pe` for future use, same treatment as the PEGY
growth-rate columns.

The pure 2-factor literal Magic Formula replication (section 3) is a separate,
interesting standalone result — not evaluated here as a candidate for the live
capital process, but a reasonable candidate for an explainable, book-faithful
screener preset if that is still wanted.

## 6. Pure Greenblatt, made investable, vs. the actual live composite

The 19.79%/1.127 headline in section 3 has no guardrails, no sector cap, and no
liquidity filter — none of which the live composite goes without. Layering those in
one at a time (`scripts/test_greenblatt_pure_robust.py`):

```
Layer                                          CAGR    Sharpe
Fully unconstrained (section 3)               +19.79%   1.127
+ $5M ADV liquidity filter                    +18.56%   1.039
+ guardrails + 25% sector cap (investable)    +16.27%   0.890
```

Walk-forward fold win rate vs. the naive equal-weight universe benchmark: 69%
unconstrained, 66% constrained — genuinely more consistent than the augmented
composite's 51% vs. its own baseline. But that comparison uses an easy opponent
(naive universe average) that the existing composite already beats too.

**The decision-relevant test** (`scripts/test_greenblatt_vs_composite.py`): constrained
Greenblatt vs. the live composite baseline, identical universe, identical guardrails/
sector cap/liquidity filter, same 36 folds:

```
                CAGR    Sharpe    MaxDD
composite     +16.13%   0.905   -39.18%
greenblatt    +16.45%   0.896   -38.20%
```

Greenblatt beats the composite in 18/35 folds (51%) — a coin flip, statistically
indistinguishable from the composite. The two-line formula and the 10-factor
sector-neutral composite land in the same place historically; there is no edge to
capture by switching. **Final conclusion: keep the existing composite as the live
process.** No changes to `_VALUE_COLS`/`_QUALITY_COLS`. The pure-Greenblatt screen
remains a reasonable Finview UI feature for manual exploration, not a live-capital
candidate.
