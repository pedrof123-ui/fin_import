# Capex / R&D Intensity Factor Test

Evaluates the four candidate factors built on the capex/R&D intensity ratios added in
PLAN_CAPEX_RD_RATIOS.md Phases 1-2, via `scripts/test_capex_rd_factors.py`:

- `capex_intensity`             = `ttm_capex_intensity` (level)
- `capex_intensity_change_3y`   = `ttm_capex_intensity` minus its value 36 months prior
- `rd_intensity`                = `ttm_rd_intensity` (level)
- `rd_intensity_change_3y`      = `ttm_rd_intensity` minus its value 36 months prior

Direction was not assumed a priori — `historic_fundamentals/pe.py`'s feature-direction
reference block explicitly documents these as "not unambiguously directional" (high
capex/R&D can mean wasteful overinvestment or a genuine growth advantage depending on
company/sector), unlike the margin factors it marks as safely "higher is better". All four
were tested with `lower_is_better=False`; a negative mean IC is exactly as valid a result as
a positive one here — it means the empirical relationship runs the other way, not that the
test failed.

Universe: standard filters (mkt cap ≥ $1B, price ≥ $5, financials/real-estate excluded),
1,953 tickers, 267,598 rows.

## 1. IC test (ret_1y, full period)

| factor | mean IC | ICIR | hit rate | t-stat | months |
|---|---|---|---|---|---|
| `capex_intensity` | -0.0055 | -0.047 | 48.2% | -0.97 | 427 |
| `capex_intensity_change_3y` | +0.0105 | 0.141 | 53.5% | 2.78 | 391 |
| `rd_intensity` | +0.0055 | 0.034 | 56.8% | 0.67 | 389 |
| `rd_intensity_change_3y` | +0.0176 | 0.196 | 55.8% | 3.87 | 389 |

Same pattern on ret_6m (weaker but directionally consistent — see script output).
`rd_intensity_change_3y` is the strongest of the four by a clear margin on the full period,
and the only one whose t-stat alone would clear a conventional significance bar.

## 2. Quintile spread (ret_1y, Q1 best − Q5 worst)

```
capex_intensity              Q1=+15.26%  Q5=+16.06%  spread= -0.80%
capex_intensity_change_3y    Q1=+15.09%  Q5=+14.25%  spread= +0.84%
rd_intensity                 Q1=+17.18%  Q5=+18.40%  spread= -1.22%
rd_intensity_change_3y       Q1=+19.24%  Q5=+16.27%  spread= +2.96%
```

`rd_intensity_change_3y` again stands out — the only factor with both a meaningfully
positive full-period IC and a meaningfully positive quintile spread pointing the same
direction. `rd_intensity`'s level (not the change) has the widest spread of the other three
but in the *wrong* direction relative to its own (barely positive, insignificant) IC sign —
itself a small internal-consistency flag against that one.

## 3. In-sample / out-of-sample sign stability (ret_1y, split at 2006-06-30, 243 months each half)

This is the test that has killed every prior full-period-promising factor in this repo
(Greenblatt's augmented composite, CANSLIM's regime gate, the MD&A composite) — a real
effect should not flip sign between the first and second half of a 36-year sample.

```
capex_intensity              IS mean_ic=+0.0568 (t=+7.39)   OOS mean_ic=-0.0579 (t=-9.05)   SIGN FLIP
capex_intensity_change_3y    IS mean_ic=+0.0312 (t=+4.49)   OOS mean_ic=-0.0036 (t=-0.91)   SIGN FLIP
rd_intensity                 IS mean_ic=-0.0050 (t=-0.31)   OOS mean_ic=+0.0126 (t=+1.45)   SIGN FLIP
rd_intensity_change_3y       IS mean_ic=+0.0278 (t=+2.81)   OOS mean_ic=+0.0106 (t=+2.96)   STABLE
```

Three of four factors fail outright — `capex_intensity`'s full-period IC in particular
(-0.0055, looking like noise) is masking a strong, exactly-canceling sign flip (+0.057 IS,
-0.058 OOS): the full-period number is not "no effect", it's "two large, opposite effects
in different eras averaging to near zero." `rd_intensity`'s weak full-period IC is
consistent with genuine noise both ways. `capex_intensity_change_3y` looked real in-sample
(t=4.49) but the OOS IC is statistically indistinguishable from zero.

`rd_intensity_change_3y` is the one factor that holds a stable, same-sign, individually
significant IC in both halves (t=2.81 IS, t=2.96 OOS) — a company's R&D intensity *rising*
over the trailing 3 years carries a real, durable, positive signal for forward 1-year
returns across this 36-year sample, distinct from the level of R&D intensity itself (which
does not).

## Conclusion

**Three of four rejected**: `capex_intensity`, `capex_intensity_change_3y`, and
`rd_intensity` all fail the IS/OOS sign-stability bar — same fate as
[[project_greenblatt_factors_result]], [[project_canslim_factors_result]], and
[[project_mda_factors_result]]. Not promoted; columns kept in `monthly_pe`/`sector_stats`
for the DCF use (Phase 4) and possible future use, same treatment as the PEGY growth-rate
columns.

`rd_intensity_change_3y` initially passed everything the single-factor test ran —
full-period IC significance, quintile spread direction matching IC sign, and a single-split
IS/OOS sign-stability check — a genuinely more promising standalone result than any of the
other 15 factors tested across this repo's four prior factor-gauntlet rounds. That result
alone was deliberately not treated as a promotion, since every prior factor that got a real
promote-or-reject decision (Greenblatt, the CANSLIM regime gate) was put through a full
30+-fold walk-forward backtest and a composite-level A/B against the live baseline first —
the follow-up below is that same fuller test, via `scripts/test_capex_rd_walkforward.py`.

## 4. Augmented composite A/B (full period, live sector-neutral guardrailed composite,
`top_n_25`, identical universe/dates, `rd_intensity_change_3y` added as an 11th factor
alongside the existing 10)

```
                                          CAGR    Sharpe    MaxDD     PF     R-Exp   WinRate  Months
baseline (current live factors)        +16.90%    0.996   -43.05%   2.10   +0.0143   65.2%    408
augmented (+rd_intensity_change_3y)    +16.75%    0.974   -44.18%   2.08   +0.0143   66.4%    408
SPY                                     +9.54%    0.656   -61.22%   1.67   +0.0087   63.9%    523
```

Worse on every metric except win rate: lower CAGR, lower Sharpe, deeper drawdown, lower
Profit Factor, flat R-Expectancy. The standalone single-factor signal from sections 1-3 does
not translate into composite-level value — the composite's existing quality factors (`roic`,
`roa`, `operating_margin_slope_5y`, `earnings_quality`, `asset_growth`) already capture
enough of what a rising-R&D-intensity signal would add that the 11th factor mostly dilutes
rather than complements it. This is the same pattern Greenblatt's two factors showed: real
standalone IC significance that didn't survive contact with an already-strong composite.

## 5. Walk-forward fold stability (33 non-overlapping annual test folds, train=5y/test=1y,
same fold structure as `walk_forward_portfolio_backtest.py`)

**Augmented beats baseline in 15 / 33 folds (45%)** — below a coin flip, and below every
other augmented-composite fold win rate tested in this repo (Greenblatt 51%, CANSLIM
regime gate ~51-54%). Full period aggregate over the walk-forward-evaluable range confirms
the same direction: baseline CAGR +18.66%/Sharpe 1.123 vs. augmented +18.50%/Sharpe 1.095.

## Conclusion

**All four factors rejected.** `capex_intensity`, `capex_intensity_change_3y`, and
`rd_intensity` fail the IS/OOS sign-stability bar outright (section 3) — same fate as
[[project_greenblatt_factors_result]], [[project_canslim_factors_result]], and
[[project_mda_factors_result]]. `rd_intensity_change_3y` passed the single-factor stability
check but fails decisively at composite level (sections 4-5) — worse on every metric except
win rate, and a sub-coin-flip 45% fold win rate. **Not promoted.** No changes to
`historic_fundamentals/baselines.py` `_VALUE_COLS`/`_QUALITY_COLS` or `scripts/score_live.py`.
All 4 raw/change columns are kept in `monthly_pe`/`sector_stats` — capex/rd_intensity for
the DCF use (Phase 4 of PLAN_CAPEX_RD_RATIOS.md), the rest for possible future use, same
treatment as the PEGY growth-rate columns.

This closes the factor-testing question for these ratios. No further follow-up is
recommended on this specific composite-augmentation angle — the standalone signal is real
(section 3) but the composite-level test (sections 4-5) is the decision-relevant one, and it
is unambiguous.
