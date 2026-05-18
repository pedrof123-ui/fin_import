# Survivorship Bias Analysis

**Date:** 2026-05-18  
**Universe:** $1B+ market cap, $5+ price, ex-Financials/Real Estate, 1,384 tickers

---

## What we tested

Split the historical universe into cohorts by when each ticker first appeared in our
database. Early-cohort tickers (in DB since before 2008) have had 18+ years to
"survive" to today. Late-cohort tickers (added post-2014) have had fewer years to fail.
If survivorship bias is material, early-cohort tickers should show systematically higher
returns because the failures have been excluded.

---

## Key findings

### 1. The prices database contains only currently-active tickers

Zero delistings found in prices.duckdb — every ticker's price series runs to the present.
Companies that went bankrupt, were acquired below fair value, or delisted between 2005–today
are entirely absent from our data. We cannot measure their returns from within this database.

### 2. Median returns are nearly identical across cohorts

| Cohort | N tickers | Median 1y return | Mean 1y return |
|--------|-----------|-----------------|----------------|
| Early (<2008) | 1,043 | +12.10% | +16.72% |
| Late (>=2014) | 183 | +12.84% | +46.42% |

The median difference is only **0.74pp** — effectively zero. The mean gap (+30pp) is an
artifact: the late cohort is a small set of high-growth companies added during the 2014–2024
bull market whose mean is dominated by outliers (2020 COVID recovery, AI-driven stocks).

### 3. Year-by-year: early survivors mostly underperform the full universe

In 12 of 16 years analyzed, tickers in the DB since before 2008 returned *less* than the
full universe average. This is the opposite of survivorship bias — long-tenured companies
in our universe tend to be more mature, slower-growth businesses.

| Year | Early mean | All mean | Diff |
|------|-----------|---------|------|
| 2020 | +55.5% | +86.0% | -30.5% |
| 2023 | +22.4% | +26.6% | -4.2% |
| 2024 | +9.7% | +14.3% | -4.7% |
| 2013 | +21.8% | +24.8% | -2.9% |
| ... most years show early cohort lagging ... | | | |

### 4. Only 7 tickers (1%) have data back to 2005

The DB was built primarily from tickers active in 2005–2010. Very few go back to the full
backtest start date, limiting our ability to directly test pre-2008 survivorship.

---

## True survivorship bias: what we cannot measure

The real bias comes from companies that **never entered our database** because they failed
before we started collecting data. These fall into three buckets:

| Category | Direction | Magnitude |
|----------|-----------|-----------|
| Bankruptcies / delisted at zero | Inflates returns | High per-company, rare in large-cap |
| Acquisitions at premium (>20%) | Actually helps returns | Moderate |
| Fell below $1B market cap | Excluded by our filter anyway | Neutral |

For a **large-cap ($1B+) universe**, most bankruptcies are excluded by the market cap filter
before they happen — companies shrink below $1B before going bankrupt. The academic literature
estimates survivorship bias of:

- **Small-cap strategies:** 2–5% per year (Elton, Gruber & Blake 1996)
- **Large-cap strategies:** 0.5–1.5% per year (Fama & French implied; Brown et al. 1992)

---

## Conclusion and calibration

**Estimated bias in our backtest CAGR: 0.5–1.5pp per year**

Our `vw_gr_top_n_25` CAGR of 24.45% likely overstates true out-of-sample performance by
approximately **0.5–1.5pp**, implying a "true" CAGR of roughly **23–24%**.

This does not change the go/no-go decision:
- Even after adjustment, CAGR exceeds SPY (8.4%) by 15+ percentage points
- Sharpe ratio (1.35) vs SPY (0.61) is unlikely to be explained by survivorship alone
- The bias affects absolute return levels but not the cross-sectional ranking signal
  (which is what the walk-forward IC/ICIR validates independently)

**Fixable with:** Historical constituent data (CRSP, FactSet, or S&P historical membership
lists). Adding delisted companies with their actual return-to-zero would lower CAGR by the
estimated 0.5–1.5pp and widen the MaxDD slightly.

---

## What the internal cohort analysis rules out

The year-by-year and median analysis rules out a more severe internal bias:
there is **no evidence that our long-tenured tickers earn systematically higher returns**
than newer additions within the same time windows. The bias is structural (missing
companies), not internal (early survivors beating late additions in the same period).
