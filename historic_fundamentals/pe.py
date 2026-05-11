"""
PE calculation engine for historic fundamentals.

Computes monthly PE timeseries and statistics for a ticker using data
already present in av_financials.duckdb and prices.duckdb.
No Alpha Vantage API calls are made.

Usage:
    import duckdb
    from historic_fundamentals.pe import process_ticker, compute_pe_stats

    av_conn     = duckdb.connect("data/av_financials.duckdb", read_only=True)
    prices_conn = duckdb.connect("/path/to/prices.duckdb", read_only=True)

    # Returns (monthly_pe DataFrame, stats dict)
    monthly_pe, stats = process_ticker("AAPL", av_conn, prices_conn)

    # monthly_pe columns:
    #   month_end_date, price, ttm_eps, pe_ratio,
    #   pe_rolling_5yr_median, ttm_source, shares, ttm_dividend, dividend_yield
    # stats keys:
    #   ticker, pe_lt_median, pe_p10, pe_p25, pe_p75, pe_p90, months_available,
    #   pe_rolling_5yr_median, current_pe, current_ttm_eps,
    #   ttm_dividend, dividend_yield

    av_conn.close()
    prices_conn.close()

TTM EPS method:
    Shares source (primary): shares_outstanding.shares_outstanding_diluted (most recent <= month_end)
    Shares source (fallback): balance_sheets.common_stock_shares_outstanding
    Quarterly available (>= 4 periods): sum last 4 quarters net_income / shares
    Quarterly not available: most recent annual net_income / shares (proxy)
    pe_ratio is NULL for months where ttm_eps <= 0 (loss-making periods)

Dividend yield:
    ttm_dividend: sum of dividends.amount where ex_dividend_date in trailing 12 months
    dividend_yield: ttm_dividend / price (NULL when no dividend data)

Rolling 5yr median:
    Stored per month in monthly_pe. Requires 60 consecutive monthly rows (min_periods=60).
    NULL for the first 59 months of a ticker's history.
"""

import logging
from datetime import UTC, date, datetime, timedelta

import duckdb
import pandas as pd

log = logging.getLogger(__name__)


def _load_av_data(av_conn: duckdb.DuckDBPyConnection, ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (quarterly_df, annual_df).
    Each has columns: fiscal_date_ending (date), net_income (float), total_revenue (float), shares (float).
    shares is from balance_sheets and used only as fallback when shares_outstanding is unavailable.
    """
    quarterly = av_conn.execute("""
        SELECT
            i.fiscal_date_ending,
            i.net_income,
            i.total_revenue,
            b.common_stock_shares_outstanding AS shares
        FROM income_statements i
        LEFT JOIN balance_sheets b
            ON  i.ticker      = b.ticker
            AND i.fiscal_date_ending = b.fiscal_date_ending
            AND i.period_type = b.period_type
        WHERE i.ticker = ? AND i.period_type = 'quarterly'
        ORDER BY i.fiscal_date_ending
    """, [ticker]).df()

    annual = av_conn.execute("""
        SELECT
            i.fiscal_date_ending,
            i.net_income,
            i.total_revenue,
            b.common_stock_shares_outstanding AS shares
        FROM income_statements i
        LEFT JOIN balance_sheets b
            ON  i.ticker      = b.ticker
            AND i.fiscal_date_ending = b.fiscal_date_ending
            AND i.period_type = b.period_type
        WHERE i.ticker = ? AND i.period_type = 'annual'
        ORDER BY i.fiscal_date_ending
    """, [ticker]).df()

    return quarterly, annual


def _load_shares_ts(av_conn: duckdb.DuckDBPyConnection, ticker: str) -> pd.DataFrame:
    """
    Returns DataFrame with columns: date (date), shares_outstanding_diluted (float).
    Empty if the shares_outstanding table has no data for this ticker.
    """
    try:
        return av_conn.execute("""
            SELECT date, shares_outstanding_diluted
            FROM shares_outstanding
            WHERE ticker = ?
            ORDER BY date
        """, [ticker]).df()
    except Exception:
        return pd.DataFrame()


def _load_dividends(av_conn: duckdb.DuckDBPyConnection, ticker: str) -> pd.DataFrame:
    """
    Returns DataFrame with columns: ex_dividend_date (date), amount (float).
    Empty if no dividend data exists for this ticker.
    """
    try:
        return av_conn.execute("""
            SELECT ex_dividend_date, amount
            FROM dividends
            WHERE ticker = ? AND amount IS NOT NULL
            ORDER BY ex_dividend_date
        """, [ticker]).df()
    except Exception:
        return pd.DataFrame()


def _load_monthly_prices(prices_conn: duckdb.DuckDBPyConnection, ticker: str) -> pd.DataFrame:
    """
    Returns DataFrame with: month_end_date (date), price (float).
    month_end_date is the last calendar day of each month.
    price is the adj_close on the last trading day of that month.
    """
    return prices_conn.execute("""
        SELECT
            (date_trunc('month', date) + interval '1 month' - interval '1 day')::DATE AS month_end_date,
            LAST(adj_close ORDER BY date) AS price
        FROM stock_prices
        WHERE ticker = ?
        GROUP BY date_trunc('month', date)
        ORDER BY month_end_date
    """, [ticker]).df()


def _get_shares(
    month_end,
    shares_ts: pd.DataFrame,
    quarterly: pd.DataFrame,
    annual: pd.DataFrame,
) -> float | None:
    """
    Return diluted shares as of month_end.
    Primary: dedicated shares_outstanding timeseries.
    Fallback: most recent balance-sheet shares from quarterly, then annual filing.
    """
    if not shares_ts.empty:
        avail = shares_ts[shares_ts["date"] <= month_end]
        if not avail.empty:
            sh = avail.iloc[-1]["shares_outstanding_diluted"]
            if pd.notna(sh) and float(sh) > 0:
                return float(sh)

    for df in (quarterly, annual):
        if df.empty:
            continue
        avail = df[df["fiscal_date_ending"] <= month_end]
        if avail.empty:
            continue
        sh_vals = avail["shares"].dropna()
        if sh_vals.empty:
            continue
        sh = float(sh_vals.iloc[-1])
        if sh > 0:
            return sh

    return None


def build_monthly_pe(
    quarterly: pd.DataFrame,
    annual: pd.DataFrame,
    prices: pd.DataFrame,
    shares_ts: pd.DataFrame | None = None,
    dividends: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Build monthly PE timeseries.

    For each month with price data:
    - Shares: prefer shares_outstanding_diluted endpoint; fall back to balance sheet
    - If >= 4 quarterly periods available (fiscal_date_ending <= month_end): use TTM from quarters
    - Else if any annual period available: use annual net_income / shares as TTM proxy
    - pe_ratio is NULL when ttm_eps <= 0
    - ttm_dividend: sum of dividends with ex_dividend_date in trailing 365 days
    - dividend_yield: ttm_dividend / price
    - ttm_revenue: sum of last 4 quarters total_revenue; fallback to most recent annual total_revenue

    Returns DataFrame with columns:
    month_end_date, price, ttm_eps, pe_ratio, pe_rolling_5yr_median, ttm_source,
    shares, ttm_dividend, dividend_yield, ttm_revenue
    """
    if prices.empty:
        return pd.DataFrame()

    q = quarterly.copy()
    a = annual.copy()
    p = prices.copy()
    st = shares_ts.copy() if shares_ts is not None and not shares_ts.empty else pd.DataFrame()
    dv = dividends.copy() if dividends is not None and not dividends.empty else pd.DataFrame()

    if not q.empty:
        q["fiscal_date_ending"] = pd.to_datetime(q["fiscal_date_ending"]).dt.date
    if not a.empty:
        a["fiscal_date_ending"] = pd.to_datetime(a["fiscal_date_ending"]).dt.date
    if not st.empty:
        st["date"] = pd.to_datetime(st["date"]).dt.date
    if not dv.empty:
        dv["ex_dividend_date"] = pd.to_datetime(dv["ex_dividend_date"]).dt.date
    p["month_end_date"] = pd.to_datetime(p["month_end_date"]).dt.date

    rows = []
    for price_row in p.itertuples(index=False):
        month_end = price_row.month_end_date
        price = price_row.price

        if price is None or pd.isna(price) or price <= 0:
            continue

        ttm_eps = None
        shares = None
        source = None

        sh = _get_shares(month_end, st, q, a)

        if sh is not None and not q.empty:
            avail = q[q["fiscal_date_ending"] <= month_end]
            if len(avail) >= 4:
                last4 = avail.tail(4)
                ni_vals = last4["net_income"].dropna()
                if len(ni_vals) == 4:
                    ttm_eps = float(ni_vals.sum()) / sh
                    shares = sh
                    source = "quarterly"

        if ttm_eps is None and sh is not None and not a.empty:
            avail = a[a["fiscal_date_ending"] <= month_end]
            if not avail.empty:
                ni = avail.iloc[-1]["net_income"]
                if pd.notna(ni):
                    ttm_eps = float(ni) / sh
                    shares = sh
                    source = "annual"

        if ttm_eps is None:
            continue

        pe = float(price) / ttm_eps if ttm_eps > 0 else None

        # Trailing 12-month dividend
        ttm_dividend = None
        dividend_yield = None
        if not dv.empty:
            window_start = month_end - timedelta(days=365)
            window = dv[(dv["ex_dividend_date"] > window_start) & (dv["ex_dividend_date"] <= month_end)]
            if not window.empty:
                ttm_dividend = float(window["amount"].sum())
                dividend_yield = ttm_dividend / float(price)

        # Trailing 12-month revenue
        ttm_revenue = None
        if not q.empty:
            avail_rev = q[q["fiscal_date_ending"] <= month_end]
            if len(avail_rev) >= 4:
                last4_rev = avail_rev.tail(4)["total_revenue"].dropna()
                if len(last4_rev) == 4:
                    ttm_revenue = float(last4_rev.sum())
        if ttm_revenue is None and not a.empty:
            avail_ann = a[a["fiscal_date_ending"] <= month_end]
            if not avail_ann.empty:
                rev = avail_ann.iloc[-1]["total_revenue"]
                if pd.notna(rev) and float(rev) > 0:
                    ttm_revenue = float(rev)

        rows.append({
            "month_end_date": month_end,
            "price": float(price),
            "ttm_eps": ttm_eps,
            "pe_ratio": pe,
            "ttm_source": source,
            "shares": shares,
            "ttm_dividend": ttm_dividend,
            "dividend_yield": dividend_yield,
            "ttm_revenue": ttm_revenue,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("month_end_date").reset_index(drop=True)
    df["pe_rolling_5yr_median"] = df["pe_ratio"].rolling(60, min_periods=60).median()
    return df


def compute_pe_stats(
    ticker: str,
    monthly_pe: pd.DataFrame,
    forward_pe: float | None = None,
    forward_12m_eps: float | None = None,
) -> dict | None:
    if monthly_pe.empty:
        return None

    pe_series = monthly_pe["pe_ratio"].dropna()
    if pe_series.empty:
        return None

    last = monthly_pe.iloc[-1]

    def _f(v) -> float | None:
        return float(v) if pd.notna(v) else None

    return {
        "ticker": ticker,
        "updated_at": datetime.now(UTC),
        "pe_lt_median": _f(pe_series.median()),
        "pe_p10": _f(pe_series.quantile(0.10)),
        "pe_p25": _f(pe_series.quantile(0.25)),
        "pe_p75": _f(pe_series.quantile(0.75)),
        "pe_p90": _f(pe_series.quantile(0.90)),
        "months_available": int(len(pe_series)),
        "pe_rolling_5yr_median": _f(last.get("pe_rolling_5yr_median")),
        "current_pe": _f(last.get("pe_ratio")),
        "current_ttm_eps": _f(last.get("ttm_eps")),
        "forward_pe": forward_pe,
        "forward_12m_eps": forward_12m_eps,
        "ttm_dividend": _f(last.get("ttm_dividend")),
        "dividend_yield": _f(last.get("dividend_yield")),
    }


def compute_revenue_stats(annual: pd.DataFrame) -> dict:
    """
    Compute revenue growth metrics from annual income statement data.

    Returns dict with any subset of:
        rev_growth_1yr  — year-over-year revenue growth
        rev_cagr_3yr    — 3-year revenue CAGR
        rev_cagr_5yr    — 5-year revenue CAGR

    All values are decimals (e.g. 0.12 = 12% growth). Returns {} when data is
    insufficient or all revenue values are non-positive.
    """
    if annual.empty:
        return {}

    a = annual.copy()
    a["fiscal_date_ending"] = pd.to_datetime(a["fiscal_date_ending"]).dt.date
    a = a.dropna(subset=["total_revenue"])
    a = a[a["total_revenue"] > 0].sort_values("fiscal_date_ending").reset_index(drop=True)

    if a.empty:
        return {}

    latest_date: date = a.iloc[-1]["fiscal_date_ending"]
    latest_rev = float(a.iloc[-1]["total_revenue"])
    result = {}

    for key, n_years in [("rev_growth_1yr", 1), ("rev_cagr_3yr", 3), ("rev_cagr_5yr", 5)]:
        target = latest_date - timedelta(days=int(n_years * 365.25))
        diffs = a["fiscal_date_ending"].apply(lambda d: abs((d - target).days))
        idx = int(diffs.idxmin())
        diff_days = int(diffs[idx])
        base_date: date = a.loc[idx, "fiscal_date_ending"]
        if diff_days <= 180 and base_date < latest_date:
            base_rev = float(a.loc[idx, "total_revenue"])
            actual_years = (latest_date - base_date).days / 365.25
            if actual_years > 0 and base_rev > 0:
                result[key] = (latest_rev / base_rev) ** (1.0 / actual_years) - 1.0

    return result


def process_ticker(
    ticker: str,
    av_conn: duckdb.DuckDBPyConnection,
    prices_conn: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, dict | None]:
    """
    Load data, build monthly PE series, compute stats.
    Returns (monthly_pe_df, stats_dict). Both may be empty/None on failure.
    """
    quarterly, annual = _load_av_data(av_conn, ticker)

    if quarterly.empty and annual.empty:
        log.warning("%s: no financial data in av_financials", ticker)
        return pd.DataFrame(), None

    prices = _load_monthly_prices(prices_conn, ticker)
    if prices.empty:
        log.warning("%s: no price data", ticker)
        return pd.DataFrame(), None

    shares_ts = _load_shares_ts(av_conn, ticker)
    dividends = _load_dividends(av_conn, ticker)

    monthly_pe = build_monthly_pe(quarterly, annual, prices, shares_ts, dividends)
    stats = compute_pe_stats(ticker, monthly_pe)
    if stats:
        stats.update(compute_revenue_stats(annual))
    return monthly_pe, stats
