# Survivorship Bias Quantification

Open item from `project_next_steps` memory, given fresh urgency by the
Fibonacci-factor test (`docs/fibonacci_factors_test.md`), whose standalone
"pure Fibonacci in an uptrend" backtest produced an implausible 80% CAGR /
3.7 Sharpe — a number only explainable by survivorship bias in the backing
universe. This quantifies the size and shape of that bias directly
(`scripts/analyze_survivorship_bias.py`).

## Method

`monthly_pe` (fin_import2) and `stock_prices` (trade_systems) are both built
by manually adding tickers that matter *today*
(`scripts/manage_tickers.py add`), not from a point-in-time historical
constituent list. Any company that mattered historically but no longer exists
is invisible to a backtest unless someone happened to add it before it
disappeared.

Ground truth for "real, formerly-investable large caps that exited": the
already-present `trade_systems/data/sp500_removed_since_2016.csv` — 221
genuine S&P 500 exits since 2016 (bankruptcy, M&A, take-private, or simple
market-cap decline), each with a name and removal date. This isn't a perfect
point-in-time universe (S&P 500 membership ≠ this project's $1B+ cap universe
exactly), but it's real, independently-sourced, and not cherry-picked by this
project's own pipeline — exactly the kind of external check needed.

## 1. Coverage

```
Tracked in monthly_pe (fin_import2) today:              94 / 221  (43%)
Price history only (trade_systems), no fundamentals:    14 / 221  ( 6%)
ZERO footprint in either database:                      113 / 221 (51%)
```

**Just over half of real S&P 500 exits over the last decade have no footprint
at all in this project's data.** Any backtest run today, on any factor, over
any period touching 2016-2026, silently excludes all 113 of them from the
choice set for that entire period — even though they were real, liquid,
investable large caps at the time.

## 2. Of the tickers that DO have data, did their series end correctly?

```
Price data continues to present day:            96 / 108 present tickers (89%)
Price data genuinely ends in the past:            2
adj_close entirely NULL (data-quality gap only):  10
```

Most of the 96 "still trading" tickers are legitimate — real companies that
simply fell below the S&P 500 cutoff (e.g. `TRIP`, `PENN`, `KSS`) and are
correctly still present and still tradeable. That's not bias, that's the
$1B-cap universe filter doing its job on real, current data.

A smaller but structurally important subset is worse than "missing": **the
original S&P 500 constituent ceased to exist, and an unrelated company later
took over the same ticker symbol, silently splicing two different companies'
histories under one label with no error or gap to signal it.** Two confirmed
cases in this project's own data:

- **`BBBY`** — the original Bed Bath & Beyond Corporation filed Chapter 11 in
  April 2023; equity was wiped to zero. Checked the daily price series
  through that window: no gap, no discontinuity, no crash to near-zero —
  price moves smoothly from ~$18 to ~$37 across 2023. That's because
  Overstock.com Inc bought the brand out of bankruptcy and renamed *itself*
  "Bed Bath & Beyond, Inc." in August 2023, and the price/company_overview
  data under ticker `BBBY` is Overstock's continuous history (its
  `company_overview.name` field even confirms "Bed Bath & Beyond, Inc." with
  `sector`/`industry` both `NONE`, i.e. not yet fully re-classified by Alpha
  Vantage). Any backtest that scores or holds "BBBY" gets a real, unrelated
  e-commerce company under a bankrupt retailer's old ticker, and the original
  shareholders' -100% wipeout is nowhere in this project's data.
- **`CTRA`** — this project's `stock_prices` table has a "CTRA" series ending
  1998-12-31 (an unrelated 1990s company, likely also a recycled symbol from
  before that). The 2022 S&P 500 removal referenced in the ground-truth CSV
  is Coterra Energy (formed 2021 from Cimarex Energy + Cabot Oil & Gas) —
  which is not tracked under `CTRA` in this project at all. In this case the
  stale pre-1998 data is at least clearly dated and wouldn't be picked up by
  a modern-era backtest, but it illustrates the same underlying failure mode:
  ticker symbols get reused, and nothing in this pipeline checks for it.

Only 2 tickers (`AET`, `CTRA`) show a price series that stops where it
plausibly should. `AET` is the clean case: Aetna's last trading day (Nov 28,
2018, $212.70, its CVS-merger close price) is exactly where the real company
ended — proof the underlying price data CAN terminate correctly when a ticker
isn't reused afterward.

## Conclusion

Two distinct, independently-confirmed problems, not one:

1. **Missing-entirely bias (51% of real exits, 113/221):** the textbook
   survivorship-bias mechanism — companies that failed or were removed simply
   aren't in the universe, inflating every historical backtest run against
   `monthly_pe` or `stock_prices` by an unknown but clearly nontrivial amount
   (rough external benchmark: academic large/mid-cap survivorship studies
   typically find ~1-4 points/year of return inflation; this project's
   universe is missing *more than half* of known real exits, so should be
   assumed to sit at or above the high end of that range, not the low end).
2. **Silent misattribution bias (at least 1 confirmed case, `BBBY`, likely
   more given no systematic check exists):** worse than missing data, because
   it looks like coverage. A ticker-keyed join across a corporate rename or
   ticker-reuse event returns a different, unrelated company's history with
   no error, so a backtest can appear to "cover" a name that actually failed
   while quietly scoring a survivor instead.

Recommended follow-ups (not done here, scoping only):
- Add a periodic check against `sp500_removed_since_2016.csv` (or a broader
  historical delisting list) that flags any removed ticker whose price series
  in `stock_prices` continues past its removal date, cross-checked against
  `company_overview.name` for a mismatch — this generalizes the `BBBY`
  detection into something that runs automatically instead of relying on
  manual discovery.
- When reporting any backtest CAGR/Sharpe on the current `monthly_pe`
  universe, treat it as a ceiling, not a point estimate — the 80% CAGR
  Fibonacci-uptrend result and (to a lesser, real extent) the ~15-25% CAGR
  numbers reported for the live composite and CANSLIM/Greenblatt tests all
  carry this same bias in the same direction.
- No fix attempted here to `monthly_pe`/`stock_prices` themselves — backfilling
  113 genuinely-dead tickers' historical price/fundamentals data would require
  a paid historical-delisted-securities data source this project doesn't
  currently have.
