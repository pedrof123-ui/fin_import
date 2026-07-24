# CANSLIM Factor Test

Evaluates William O'Neil's CANSLIM criteria as factors backfilled into
`monthly_pe`, following the plan in `CANSLIM_FACTOR_TEST_PLAN.md`. Seven
sub-factor columns, six of the seven letters (I dropped, no historical data —
see below):

- `q_earn_accel` (C) — `scripts/backfill_canslim_factors.py`: current-quarter
  EPS YoY growth minus the prior quarter's EPS YoY growth (acceleration, not
  just growth). EPS = net_income / diluted shares as of each quarter, not a
  single current share count, so buyback-driven EPS growth shows distinctly
  from net-income growth. Point-in-time safe (60-day quarterly reporting lag,
  matching `build_monthly_pe`'s policy — stricter than
  `backfill_greenblatt_factors.py`'s unlagged `_get_ttm_sum` calls, a
  pre-existing gap in that script not replicated here). Coverage 67.1%/60.7%.
- `earn_cagr_3yr`, `roe` (A) — already existed in `monthly_pe`, not
  previously part of the live composite.
- `pct_off_52wk_high` (N), `vol_surge_ratio`, `up_down_vol_ratio` (S) —
  `scripts/backfill_canslim_technicals.py`, from `trade_systems` daily OHLCV.
  Coverage 97.2%/99.4%/99.4%.
- `rs_rating` (L) — `scripts/backfill_canslim_rs.py`: IBD-style weighted
  3/6/9/12-month return (`0.4/0.2/0.2/0.2`), cross-sectionally
  percentile-ranked 1-99 within each month. Coverage 96.5%.
- **I (institutional sponsorship) — cut entirely.**
  `company_overview`/`earnings_estimates` only span ~2.5 months
  (2026-05 to 2026-07, live-refresh feeds with no historical archive), so no
  I factor could ever be tested against `monthly_pe`'s multi-decade history.
  Building it anyway would have produced columns nothing in this plan reads.
- **M (market direction) — not a per-stock factor.** Reused as a
  portfolio-level regime gate (`scripts/run_backtest.py::_compute_regime_exposure`),
  not tested here; not part of the cross-sectional composite.

## Bugs found & fixed en route

`historic_fundamentals/baselines.py::quintile_returns()` crashed on
`pct_off_52wk_high`: heavy exact-zero ties (many tickers sitting right at
their 52-week high in the same month) collapsed `pd.qcut`'s bin edges below 5
after `duplicates="drop"`, which the function didn't guard against. Fixed
generically — skip that month, same treatment already given to low-breadth
months — since this is a latent bug in the shared utility that any
heavily-tied factor could trigger, not specific to this test.

## 1. IC test (ret_1y, 431 months, universe: mkt cap >= $1B, financials/
real-estate excluded, 264,660 rows / 1,941 tickers)

| factor | mean IC | ICIR | hit rate | t-stat | Q1-Q5 spread |
|---|---|---|---|---|---|
| `q_earn_accel` (C) | 0.0002 | 0.004 | 53.3% | 0.07 | +0.29% |
| `earn_cagr_3yr` (A) | -0.0005 | -0.005 | 55.3% | -0.10 | +1.20% |
| `roe` (A) | 0.0255 | 0.212 | 61.6% | 4.39 | -1.52% |
| `pct_off_52wk_high` (N) | 0.0297 | 0.177 | 63.6% | 3.67 | -0.78% |
| `vol_surge_ratio` (S) | 0.0014 | 0.016 | 51.7% | 0.34 | -0.46% |
| `up_down_vol_ratio` (S) | 0.0116 | 0.102 | 54.3% | 2.12 | +2.40% |
| `rs_rating` (L) | 0.0149 | 0.085 | 57.0% | 1.77 | +4.18% |

Two of seven show no signal by either measure: `q_earn_accel` (C) and
`vol_surge_ratio` (S) are indistinguishable from noise. `roe` (A) and
`pct_off_52wk_high` (N) have strong, significant IC (t=4.39, t=3.67) but
*negative* naive quintile spreads — the same IC-vs-quintile-bucketing
divergence documented for `greenblatt_roc`/`roic` in
`docs/greenblatt_factors_test.md` (a handful of extreme-value outliers
concentrate in Q1 and drag its mean down even though the full rank
correlation is real; IC is more robust to this than raw bucketing).
`up_down_vol_ratio` (S) and `rs_rating` (L) are the cleanest results —
consistent sign and magnitude on both measures, `rs_rating`'s +4.18% quintile
spread the strongest of any CANSLIM factor tested.

Notably, **C — one of CANSLIM's two headline earnings letters — carries no
measurable signal** in this dataset.

## 2. Pure CANSLIM replication (rank-sum of all 7 sub-factors, market-wide,
not sector-neutral, no guardrails, financials/real-estate excluded — matches
the book's literal method; requires all 7 present: 149,900 rows / 1,267
tickers)

```
Portfolio                       CAGR    Sharpe    MaxDD   WinRate  Months
canslim_top_n_25              +13.52%   0.745   -46.03%   62.2%    405
canslim_top_n_30              +13.14%   0.730   -47.07%   62.0%    405
canslim_top_pct_20            +12.06%   0.677   -43.85%   62.6%    404
universe_ew (canslim univ.)   +12.80%   0.717   -42.94%   64.0%    405
SPY                             +9.45%   0.650   -61.22%   63.6%    522
```

Beats SPY, but the edge over its **own** naive universe average is thin
(top_n_25: +0.72pp CAGR, +0.028 Sharpe) and MaxDD is *worse* than the
universe benchmark. Contrast with Greenblatt's pure replication, which beat
its universe by +4.95pp CAGR / +0.205 Sharpe with a *better* MaxDD — the
composite-level echo of section 1's finding that two of the seven sub-factors
carry no signal and are diluting the ones that do.

## 3. Augmented composite A/B (sector-neutral, guardrailed, top_n_25,
identical universe/dates, both computed in the same run)

```
                                     CAGR    Sharpe    MaxDD   WinRate  Months
baseline (current live factors)   +15.96%   0.952   -40.07%   66.0%    406
augmented (+7 CANSLIM factors)    +14.57%   0.893   -42.95%   64.0%    406
```

Worse on every metric — CAGR -1.39pp, Sharpe -0.059, MaxDD 2.9pp deeper, win
rate -2.0pp.

## 4. Walk-forward fold stability (36 non-overlapping annual test folds,
train=5y/test=1y, same fold structure as `walk_forward_portfolio_backtest.py`)

**Augmented beats baseline in 8/35 folds (23%)** — folds 2-6 (1992-1996) are
identical between both composites (same low-breadth sector-cap-absorbs-
everything effect as the Greenblatt walk-forward test); excluding those,
8/30 (27%). Far worse than a coin flip, and much weaker than Greenblatt's
51%/60% fold win rates against the same baseline. This is not one bad
sub-period dragging down an otherwise-decent signal — augmented loses
consistently across three decades.

## 5. Investable-constrained comparison: standalone pure-CANSLIM vs. the
actual live composite

The unconstrained 13.52%/0.745 headline in section 2 has no guardrails, no
sector cap, no liquidity filter. Layering those in
(`scripts/test_canslim_vs_composite.py`), identical universe/guardrails/
sector cap/liquidity filter as the composite baseline, same 36 folds:

```
                                     CAGR    Sharpe    MaxDD   WinRate  Months
composite (live baseline)         +16.13%   0.905   -39.18%   65.6%    404
canslim (constrained, standalone) +13.17%   0.855   -47.75%   62.7%    354
```

Canslim beats composite in 8/31 valid folds (26%). Loses on every aggregate
metric, and MaxDD is materially worse — worse tail risk on top of lower and
less consistent returns.

## Conclusion

CANSLIM, as implemented here, is not a source of edge on this dataset — not
blended into the live composite (section 3-4) and not run as its own
standalone selection rule (section 5). The result is consistent and
one-directional across every angle tested, unlike the Greenblatt test (which
landed at "statistically indistinguishable, coin flip"): here CANSLIM loses
more often than not, by a wide margin, with worse drawdowns. **Not promoted**
— `historic_fundamentals/baselines.py` `_VALUE_COLS`/`_QUALITY_COLS` left
untouched.

Two individual sub-factors showed genuine standalone signal in section 1 and
are worth retaining as candidates for a future, narrower test, separate from
the CANSLIM bundle that diluted them here:

- `rs_rating` (L) — cleanest result of the seven: significant IC, strongest
  quintile spread (+4.18%). A true cross-sectional RS Rating, distinct from
  the existing `momentum_12_1` (raw, unranked).
- `up_down_vol_ratio` (S) — modest but consistent signal (IC t=2.12, quintile
  spread +2.40%), a genuine accumulation/distribution proxy.

`q_earn_accel` (C) and `vol_surge_ratio` (S) showed no signal in this test
and are not promising candidates for a narrower follow-up. `roe`/
`pct_off_52wk_high`'s IC-vs-quintile divergence is worth a closer look before
any future retest (same open question the Greenblatt doc left for
`roic`/`greenblatt_roc`) — possibly sector-neutralizing or winsorizing before
ranking would resolve it, not attempted here.

All seven columns are kept in `monthly_pe` for future use, same treatment the
Greenblatt columns received. I (institutional sponsorship) proxy columns were
never built (see `CANSLIM_FACTOR_TEST_PLAN.md` Phase 0/4) — revisit only if a
live-screener use case for CANSLIM actually materializes.

## 6. Follow-up: isolating rs_rating + up_down_vol_ratio from the bundle

Before retesting, a redundancy check: `rs_rating` vs. the composite's
existing `momentum_12_1` — mean within-month Spearman correlation **0.72**
(pooled Spearman 0.63, pooled Pearson only 0.15, since `rs_rating` is already
a percentile transform and `momentum_12_1` is raw and fat-tailed). Moderate
overlap, not a near-duplicate — worth testing empirically rather than
assuming redundancy. `up_down_vol_ratio` has no analog anywhere in the
current composite.

Re-ran the augmented A/B (`scripts/test_canslim_rs_updown_ab.py`) and
walk-forward (`scripts/test_canslim_rs_updown_walkforward.py`) with **only**
these two factors added, isolating them from `q_earn_accel` and
`vol_surge_ratio` (the two that showed no IC signal at all):

```
                                           CAGR    Sharpe    MaxDD   WinRate
baseline (current live factors)         +15.96%   0.952   -40.07%   66.0%
augmented (+rs_rating +up_down_vol_ratio) +16.40%   0.985   -45.27%   65.0%
```

Full-period CAGR and Sharpe both improve (+0.44pp, +0.033) — a real
improvement over the full 7-factor result, confirming the two noise factors
were actively hurting the bundle. But **MaxDD gets meaningfully worse**
(-40.07% -> -45.27%, 5.2pp deeper), and the walk-forward fold win rate is
**13/35 (37%)** — better than the full bundle's 23%, but still under a coin
flip. The full-period gain is concentrated in a handful of standout folds
(2020-21: +40.13%->+57.07%, 2025-26: +39.10%->+60.38%, both recovery/bull
periods), while the majority of ordinary folds still favor the baseline —
the same "average masks inconsistency" pattern flagged for Greenblatt's
augmented composite, but weaker here (37% vs. Greenblatt's 51-60%) and paired
with a real drawdown cost Greenblatt's version didn't have.

**Verdict: still not promoted**, but for a more nuanced reason than the full
bundle. `rs_rating` and `up_down_vol_ratio` are not noise — removing the two
dead factors measurably improved the result — but a <40% fold win rate plus a
5pp worse MaxDD is a real cost for a Sharpe gain of 0.033, not a free win.
This reads as a momentum/volatility-timing effect that helps in sharp
recoveries and hurts in between, not a durable structural edge. Not
compelling enough to change `_VALUE_COLS`/`_QUALITY_COLS` on this evidence.
Both columns remain available in `monthly_pe` if a future test wants to
address the drawdown cost directly (e.g. capping position concentration, or
combining `rs_rating` with an explicit regime filter rather than running it
unconditionally).
