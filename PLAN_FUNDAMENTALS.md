# Fundamentals Tab — Implementation Plan

## Goal

Add a "Fundamentals" tab to the Finview dashboard that answers: Is this stock cheap or expensive vs its own history? Is the business growing and improving? What is a fair price 1–3 years from now?

---

## Data available (no new imports needed)

| Source | Location | Key fields |
|--------|----------|------------|
| `pe_stats` | `data/historic_fundamentals.duckdb` | Current/forward/LT median/percentiles for P/E, P/FCF, EV/EBITDA, P/S, ROA, ROE, ROIC, P/BV; revenue/earnings CAGRs; margin stats; goal prices |
| `monthly_pe` | `data/historic_fundamentals.duckdb` | ~120 monthly rows per ticker: all multiples + 5yr rolling medians + margins + returns |
| `company_overview` | `data/av_financials.duckdb` | Name, sector, industry, market cap, analyst target price, analyst ratings counts |
| `earnings_estimates` | `data/historic_fundamentals.duckdb` | Forward EPS and revenue estimates by fiscal year/quarter |

If a ticker is missing from `pe_stats` (not yet in `historic_fundamentals.duckdb`), return a 404 with a clear message. No auto-refresh — consistent with existing app behavior.

---

## Architecture

### Backend

One new endpoint added to `api/av_router.py`:

```
GET /av-fundamentals/{ticker}
```

Opens `data/historic_fundamentals.duckdb` and `data/av_financials.duckdb` read-only (same pattern as the existing `/av-financials` endpoint — direct `duckdb.connect`, no shared connection needed). Queries four tables and assembles a single JSON response.

No new Python module needed. The endpoint is ~50 lines in `av_router.py`.

### Frontend

One new component `web/components/FundamentalsViewer.tsx` (~450 lines). Self-contained: fetches its own data on mount, manages its own loading/error state. Follows the same pattern as `AvFinancialsViewer.tsx`.

New tab `"fundamentals"` added to `web/app/page.tsx` — always visible alongside "AV Data" and "AV DCF" (no conditional visibility).

New TypeScript types added to `web/lib/dcf-types.ts`.

---

## API response shape

```typescript
interface FundamentalsData {
  ticker: string;

  // Company overview (from company_overview table)
  company_name: string | null;
  sector: string | null;
  industry: string | null;
  market_cap_b: number | null;
  current_price: number | null;
  analyst_target_price: number | null;
  analyst_strong_buy: number | null;
  analyst_buy: number | null;
  analyst_hold: number | null;
  analyst_sell: number | null;
  analyst_strong_sell: number | null;
  overview_updated_at: string | null;

  // Valuation multiples (from pe_stats)
  current_pe: number | null;
  forward_pe: number | null;
  pe_lt_median: number | null;
  pe_p25: number | null;
  pe_p75: number | null;
  pe_rolling_5yr_median: number | null;

  current_pfcf: number | null;
  forward_pfcf: number | null;
  pfcf_lt_median: number | null;
  pfcf_p25: number | null;
  pfcf_p75: number | null;
  pfcf_rolling_5yr_median: number | null;

  current_evebitda: number | null;
  forward_evebitda: number | null;
  evebitda_lt_median: number | null;
  evebitda_p25: number | null;
  evebitda_p75: number | null;
  evebitda_rolling_5yr_median: number | null;

  current_ps: number | null;
  forward_ps: number | null;
  ps_lt_median: number | null;
  ps_p25: number | null;
  ps_p75: number | null;
  ps_rolling_5yr_median: number | null;

  current_pbv: number | null;
  pbv_lt_median: number | null;
  pbv_rolling_5yr_median: number | null;

  // Returns (from pe_stats)
  current_roa: number | null;
  roa_lt_median: number | null;
  roa_rolling_5yr_median: number | null;

  current_roe: number | null;
  roe_lt_median: number | null;
  roe_rolling_5yr_median: number | null;

  current_roic: number | null;
  roic_lt_median: number | null;
  roic_rolling_5yr_median: number | null;

  // Growth rates (from pe_stats)
  rev_growth_1yr: number | null;
  rev_cagr_3yr: number | null;
  rev_cagr_5yr: number | null;
  rev_ntm_growth_est: number | null;
  earn_growth_1yr: number | null;
  earn_cagr_3yr: number | null;
  earn_cagr_5yr: number | null;
  earn_ntm_growth_est: number | null;

  // Margins (from pe_stats)
  current_gross_margin: number | null;
  gross_margin_5y_median: number | null;
  gross_margin_slope_5y: number | null;
  current_operating_margin: number | null;
  operating_margin_5y_median: number | null;
  operating_margin_change_3y: number | null;
  current_fcf_margin: number | null;
  fcf_margin_5y_median: number | null;
  fcf_margin_change_3y: number | null;

  // Goal prices (from pe_stats)
  goal_pe: number | null;
  goal_pcf: number | null;
  goal_peg: number | null;
  goal_bv: number | null;
  goal_2x: number | null;
  goal_low: number | null;
  goal_high: number | null;

  // EPS & dividends (from pe_stats)
  current_ttm_eps: number | null;
  forward_12m_eps: number | null;
  dividend_yield: number | null;

  // Debt & coverage (from pe_stats)
  debt_to_ebitda: number | null;
  interest_coverage: number | null;

  // Monthly time series — last 10 years (from monthly_pe)
  monthly_series: MonthlyDataPoint[];

  // Analyst estimates — forward dates only (from earnings_estimates)
  analyst_estimates: AnalystEstimate[];

  // When pe_stats was last updated
  stats_updated_at: string | null;
}

interface MonthlyDataPoint {
  date: string;
  price: number | null;
  pe_ratio: number | null;
  pe_rolling_5yr_median: number | null;
  pfcf_ratio: number | null;
  pfcf_rolling_5yr_median: number | null;
  ev_ebitda: number | null;
  ev_ebitda_rolling_5yr_median: number | null;
  ps_ratio: number | null;
  ps_rolling_5yr_median: number | null;
  ttm_gross_margin: number | null;
  ttm_operating_margin: number | null;
  ttm_fcf_margin: number | null;
  roa: number | null;
  roe: number | null;
  roic: number | null;
}

interface AnalystEstimate {
  date: string;
  horizon: string;  // "fiscal year" | "fiscal quarter"
  eps_avg: number | null;
  eps_high: number | null;
  eps_low: number | null;
  eps_count: number | null;
  rev_avg: number | null;
  rev_high: number | null;
  rev_low: number | null;
  rev_count: number | null;
}
```

---

## Component layout (FundamentalsViewer.tsx)

Single scrollable page. Sections rendered top to bottom.

### Section 1 — Header

```
AAPL  ·  Apple Inc.  ·  Technology · Consumer Electronics
$189.30   Mkt Cap $2.9T   Target $213  +12.5%↑   [Updated Jun 2 2026]
[■■■■■■■■■□□] 12 Strong Buy  8 Buy  5 Hold  1 Sell  0 Strong Sell
```

Analyst ratings rendered as a proportional colored bar:
- dark green = strong buy, green = buy, gray = hold, orange = sell, red = strong sell

### Section 2 — Snapshot KPI grid (8 cards, 4×2)

Each card: label, big number (current), small secondary (vs 5yr median).
Color-coded dot: green if current < 5yr median (cheap vs history), red if above.

```
┌────────────────┬────────────────┬────────────────┬────────────────┐
│  P/E           │  EV/EBITDA     │  P/FCF         │  P/S           │
│  28.5x  ● RED  │  20.1x  ● RED  │  35.2x  ● RED  │  8.2x   ● GRAY │
│  fwd 25.1x     │  fwd 18.5x     │  fwd 31.0x     │  fwd 7.4x      │
│  5yr med 24.5x │  5yr med 16.8x │  5yr med 28.1x │  5yr med 7.1x  │
├────────────────┼────────────────┼────────────────┼────────────────┤
│  Rev Growth    │  Op Margin     │  FCF Margin    │  ROE           │
│  +8.2% (1yr)   │  29.8%  ● GRN  │  26.3%  ● GRN  │  156.2% ● GRN  │
│  3yr 9.5%      │  5yr med 28.1% │  5yr med 24.8% │  5yr med 121.3%│
│  NTM est 7.1%  │  3yr chg +1.7% │  3yr chg +1.5% │                │
└────────────────┴────────────────┴────────────────┴────────────────┘
```

Color logic:
- For valuation multiples: green dot = current below 5yr median (potentially cheaper), red = above
- For margins/returns: green = current above 5yr median (improving), red = below

### Section 3 — Valuation multiples history (2 charts)

**Chart A**: P/E over time + 5yr rolling median (dashed)
- X-axis: month labels (years shown)
- Y-axis: multiple (x)
- Solid line: actual P/E, dashed line: 5yr rolling median
- Color: indigo for actual, dimmed violet for median

**Chart B**: EV/EBITDA and P/FCF over time + their respective 5yr medians
- Same style, two lines + two dashed medians

Both charts use `ResponsiveContainer` + `LineChart` from recharts, consistent with `DcfIncomeChart.tsx`.

### Section 4 — Margins & Returns history (2 charts)

**Chart A**: Gross margin, operating margin, FCF margin over time
- Y-axis in % format
- Three lines (green/orange/violet) — same palette as `DcfIncomeChart` margins chart

**Chart B**: ROE, ROIC over time
- Two lines

### Section 5 — Price targets table

```
Price Target Analysis         Current: $189.30
─────────────────────────────────────────────
Method               Target    Upside
─────────────────────────────────────────────
5yr Median P/E       $215.0    +13.6%  ↑
5yr Median P/FCF     $198.5    +4.9%   ↑
5yr Median EV/EBITDA $204.2    +7.9%   ↑
Analyst Consensus    $213.0    +12.5%  ↑
DCF Intrinsic*       $231.0    +22.0%  ↑
─────────────────────────────────────────────
Range (Low – High)   $165 – $225
─────────────────────────────────────────────
* See AV DCF tab for full model
```

"5yr median P/E" target = `pe_rolling_5yr_median × forward_12m_eps` (or `goal_pe` from `pe_stats` if available).
"5yr median P/FCF" = `pfcf_rolling_5yr_median × (forward FCF/share from pe_stats)`.
DCF intrinsic is just a reference note — no re-fetch needed; user can go to AV DCF tab.

### Section 6 — Valuation multiples detail table

Full table showing current / forward / 5yr median / LT median / percentile for each multiple:

```
Multiple    Current   Forward   5yr Med   LT Med    Pctile   Signal
P/E         28.5x     25.1x     24.5x     22.3x     75th     ● Elevated
EV/EBITDA   20.1x     18.5x     16.8x     15.2x     80th     ● High
P/FCF       35.2x     31.0x     28.1x     26.0x     70th     ● Elevated
P/S         8.2x      7.4x      7.1x      6.3x      65th     ● Fair
P/BV        45.5x     —         38.2x     32.1x     85th     ● High
```

Percentile is computed client-side from `pe_p25`, `pe_p75`, `pe_lt_median`: if current < p25 → "Cheap", p25–p75 → "Fair"/"Elevated", >p75 → "High".

### Section 7 — Growth & Quality summary table

```
Growth Rates
─────────────────────────────────────────────
              1 yr    3yr CAGR  5yr CAGR  NTM Est
Revenue       +8.2%   +9.5%     +12.4%    +7.1%
Earnings      +11.2%  +14.5%    +18.3%    +9.5%
FCF           +9.1%   +11.2%    +15.6%    —

Profitability
─────────────────────────────────────────────
              Current   5yr Med   3yr Chg
Gross Margin  44.3%     42.3%     +2.0%
EBIT Margin   29.8%     28.1%     +1.7%
FCF Margin    26.3%     24.8%     +1.5%
ROA           29.8%     27.1%     +2.7%
ROE           156.2%    121.3%    +34.9%
ROIC          54.8%     42.3%     +12.5%
```

### Section 8 — Analyst estimates

Table of forward EPS + revenue estimates (fiscal year + fiscal quarter, future dates only):

```
Period       Horizon   EPS (avg)  EPS Range      Rev (avg)   # Analysts
FY 2025      Annual    $7.23      $6.55 – $7.89  $420.5B     18
FY 2026      Annual    $8.12      $7.21 – $9.04  $461.3B     14
Q1 FY2025    Quarter   $2.31      $2.15 – $2.47  $124.8B     12
```

---

## Implementation steps

### Step 1 — Backend endpoint (api/av_router.py)

Add to `av_router.py`:

```python
_HF_DB = Path(os.environ.get(
    "HF_DB_PATH",
    str(Path(__file__).parent.parent / "data" / "historic_fundamentals.duckdb"),
))

@router.get("/av-fundamentals/{ticker}")
async def av_fundamentals(ticker: str):
    t = ticker.upper()
    try:
        hf = duckdb.connect(str(_HF_DB), read_only=True)
        av = duckdb.connect(str(_AV_DB), read_only=True)

        # pe_stats snapshot
        stats = hf.execute("SELECT * FROM pe_stats WHERE ticker = ?", [t]).df()
        if stats.empty:
            raise HTTPException(status_code=404, detail=f"No fundamentals data for {t}. Import via manage_tickers.py.")

        # monthly_pe — last 10 years
        series = hf.execute(
            """SELECT month_end_date, price, pe_ratio, pe_rolling_5yr_median,
                      pfcf_ratio, pfcf_rolling_5yr_median, ev_ebitda, ev_ebitda_rolling_5yr_median,
                      ps_ratio, ps_rolling_5yr_median, roa, roe, roic,
                      ttm_gross_margin, ttm_operating_margin, ttm_fcf_margin
               FROM monthly_pe
               WHERE ticker = ?
                 AND month_end_date >= (CURRENT_DATE - INTERVAL 10 YEAR)
               ORDER BY month_end_date ASC""",
            [t],
        ).df()

        # analyst estimates — future dates only
        estimates = hf.execute(
            """SELECT date, horizon, eps_avg, eps_high, eps_low, eps_count,
                      rev_avg, rev_high, rev_low, rev_count
               FROM earnings_estimates
               WHERE ticker = ?
                 AND fetched_at = (SELECT MAX(fetched_at) FROM earnings_estimates WHERE ticker = ?)
                 AND date > CURRENT_DATE
               ORDER BY date ASC""",
            [t, t],
        ).df()

        # company overview
        overview = av.execute(
            """SELECT name, sector, industry, market_capitalization,
                      analyst_target_price,
                      analyst_rating_strong_buy, analyst_rating_buy,
                      analyst_rating_hold, analyst_rating_sell,
                      analyst_rating_strong_sell,
                      trailing_pe, forward_pe, price_to_sales_ttm,
                      price_to_book, ev_to_ebitda,
                      diluted_eps_ttm, quarterly_revenue_growth_yoy,
                      fetch_date
               FROM company_overview
               WHERE ticker = ?
               ORDER BY fetch_date DESC LIMIT 1""",
            [t],
        ).df()

        hf.close()
        av.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    row = stats.iloc[0].to_dict()
    ov = overview.iloc[0].to_dict() if not overview.empty else {}

    return _sanitize({
        "ticker": t,
        "company_name": ov.get("name"),
        "sector": ov.get("sector"),
        "industry": ov.get("industry"),
        "market_cap_b": _safe_div(ov.get("market_capitalization"), 1e9),
        "current_price": row.get("current_price"),
        "analyst_target_price": _safe_float(ov.get("analyst_target_price")),
        "analyst_strong_buy": _safe_int(ov.get("analyst_rating_strong_buy")),
        "analyst_buy": _safe_int(ov.get("analyst_rating_buy")),
        "analyst_hold": _safe_int(ov.get("analyst_rating_hold")),
        "analyst_sell": _safe_int(ov.get("analyst_rating_sell")),
        "analyst_strong_sell": _safe_int(ov.get("analyst_rating_strong_sell")),
        "overview_updated_at": str(ov.get("fetch_date", "")),
        **{k: row.get(k) for k in [
            "current_pe", "forward_pe", "pe_lt_median", "pe_p25", "pe_p75", "pe_rolling_5yr_median",
            "current_pfcf", "forward_pfcf", "pfcf_lt_median", "pfcf_p25", "pfcf_p75", "pfcf_rolling_5yr_median",
            "current_evebitda", "forward_evebitda", "evebitda_lt_median", "evebitda_p25", "evebitda_p75", "evebitda_rolling_5yr_median",
            "current_ps", "forward_ps", "ps_lt_median", "ps_p25", "ps_p75", "ps_rolling_5yr_median",
            "current_pbv", "pbv_lt_median", "pbv_rolling_5yr_median",
            "current_roa", "roa_lt_median", "roa_rolling_5yr_median",
            "current_roe", "roe_lt_median", "roe_rolling_5yr_median",
            "current_roic", "roic_lt_median", "roic_rolling_5yr_median",
            "rev_growth_1yr", "rev_cagr_3yr", "rev_cagr_5yr", "rev_ntm_growth_est",
            "earn_growth_1yr", "earn_cagr_3yr", "earn_cagr_5yr", "earn_ntm_growth_est",
            "current_gross_margin", "gross_margin_5y_median", "gross_margin_slope_5y",
            "current_operating_margin", "operating_margin_5y_median", "operating_margin_change_3y",
            "current_fcf_margin", "fcf_margin_5y_median", "fcf_margin_change_3y",
            "goal_pe", "goal_pcf", "goal_peg", "goal_bv", "goal_2x", "goal_low", "goal_high",
            "current_ttm_eps", "forward_12m_eps", "dividend_yield",
            "debt_to_ebitda", "interest_coverage",
        ]},
        "monthly_series": json.loads(
            series.rename(columns={"month_end_date": "date"})
                  .to_json(orient="records", date_format="iso")
        ),
        "analyst_estimates": json.loads(
            estimates.to_json(orient="records", date_format="iso")
        ),
        "stats_updated_at": str(row.get("updated_at", "")),
    })


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None

def _safe_int(v) -> int | None:
    f = _safe_float(v)
    return int(f) if f is not None else None

def _safe_div(v, d) -> float | None:
    f = _safe_float(v)
    return f / d if f is not None else None
```

### Step 2 — TypeScript types (web/lib/dcf-types.ts)

Append `FundamentalsData`, `MonthlyDataPoint`, `AnalystEstimate` interfaces.

### Step 3 — Component (web/components/FundamentalsViewer.tsx)

Single file, self-contained. Sections implemented as inline sub-components or render functions within the main component. Re-uses:
- Recharts `LineChart` / `ResponsiveContainer` / `Line` / `CartesianGrid` / `Tooltip` — same as `DcfIncomeChart`
- Tailwind class patterns from `AvFinancialsViewer` and `DcfSummary`
- `API` from `lib/config`
- `oklch` color tokens already defined in existing components

### Step 4 — Wire into page.tsx

- Add `"fundamentals"` to the `Tab` union type
- Add `"Fundamentals"` to `TAB_LABELS`
- Add to `tabs` array (always visible, alongside AV Data and AV DCF)
- Add `<FundamentalsViewer ticker={loadedTicker} />` panel block

---

## File changes summary

| File | Change |
|------|--------|
| `api/av_router.py` | Add `GET /av-fundamentals/{ticker}` endpoint (~80 lines) |
| `web/lib/dcf-types.ts` | Append 3 new interfaces |
| `web/components/FundamentalsViewer.tsx` | New file (~450 lines) |
| `web/app/page.tsx` | Add tab + panel (~10 lines) |

No new Python modules. No schema changes. No new API calls to Alpha Vantage.

---

## What is NOT in scope (Phase 2)

- Peer comparison (sector/industry median overlaid on each multiple) — `sector_stats` table already has this data; will be a natural follow-on
- Intra-tab navigation / mini-tabs
- Auto-refresh of stale fundamentals data
