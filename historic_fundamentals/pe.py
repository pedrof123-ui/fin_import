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
    #   rolling_5yr_median, ttm_source, shares
    # stats keys:
    #   ticker, lt_median, p10, p25, p75, p90, months_available,
    #   rolling_5yr_median, current_pe, current_ttm_eps

    av_conn.close()
    prices_conn.close()

TTM EPS method:
    Quarterly available (>= 4 periods): sum last 4 quarters net_income / latest shares
    Quarterly not available: most recent annual net_income / shares (proxy)
    pe_ratio is NULL for months where ttm_eps <= 0 (loss-making periods)

Rolling 5yr median:
    Stored per month in monthly_pe. Requires 60 consecutive monthly rows (min_periods=60).
    NULL for the first 59 months of a ticker's history.
"""

import logging
from datetime import UTC, datetime

import duckdb
import pandas as pd

log = logging.getLogger(__name__)


def _load_av_data(av_conn: duckdb.DuckDBPyConnection, ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (quarterly_df, annual_df).
    Each has columns: fiscal_date_ending (date), net_income (float), shares (float).
    """
    quarterly = av_conn.execute("""
        SELECT
            i.fiscal_date_ending,
            i.net_income,
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


def build_monthly_pe(
    quarterly: pd.DataFrame,
    annual: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build monthly PE timeseries.

    For each month with price data:
    - If >= 4 quarterly periods available (fiscal_date_ending <= month_end): use TTM from quarters
    - Else if any annual period available: use annual net_income / shares as TTM proxy
    - pe_ratio is NULL when ttm_eps <= 0

    Returns DataFrame with columns:
    month_end_date, price, ttm_eps, pe_ratio, rolling_5yr_median, ttm_source, shares
    """
    if prices.empty:
        return pd.DataFrame()

    q = quarterly.copy()
    a = annual.copy()
    p = prices.copy()

    if not q.empty:
        q["fiscal_date_ending"] = pd.to_datetime(q["fiscal_date_ending"]).dt.date
    if not a.empty:
        a["fiscal_date_ending"] = pd.to_datetime(a["fiscal_date_ending"]).dt.date
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

        if not q.empty:
            avail = q[q["fiscal_date_ending"] <= month_end]
            if len(avail) >= 4:
                last4 = avail.tail(4)
                ni_vals = last4["net_income"].dropna()
                sh_vals = last4["shares"].dropna()
                if len(ni_vals) == 4 and not sh_vals.empty:
                    sh = sh_vals.iloc[-1]
                    if sh > 0:
                        ttm_eps = float(ni_vals.sum()) / float(sh)
                        shares = float(sh)
                        source = "quarterly"

        if ttm_eps is None and not a.empty:
            avail = a[a["fiscal_date_ending"] <= month_end]
            if not avail.empty:
                last = avail.iloc[-1]
                ni = last["net_income"]
                sh = last["shares"]
                if pd.notna(ni) and pd.notna(sh) and float(sh) > 0:
                    ttm_eps = float(ni) / float(sh)
                    shares = float(sh)
                    source = "annual"

        if ttm_eps is None:
            continue

        pe = float(price) / ttm_eps if ttm_eps > 0 else None

        rows.append({
            "month_end_date": month_end,
            "price": float(price),
            "ttm_eps": ttm_eps,
            "pe_ratio": pe,
            "ttm_source": source,
            "shares": shares,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("month_end_date").reset_index(drop=True)
    # Rolling 5yr median: require at least 60 rows in the window
    df["rolling_5yr_median"] = df["pe_ratio"].rolling(60, min_periods=60).median()
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
    r5 = last.get("rolling_5yr_median")

    def _f(v) -> float | None:
        return float(v) if pd.notna(v) else None

    return {
        "ticker": ticker,
        "updated_at": datetime.now(UTC),
        "lt_median": _f(pe_series.median()),
        "p10": _f(pe_series.quantile(0.10)),
        "p25": _f(pe_series.quantile(0.25)),
        "p75": _f(pe_series.quantile(0.75)),
        "p90": _f(pe_series.quantile(0.90)),
        "months_available": int(len(pe_series)),
        "rolling_5yr_median": _f(r5),
        "current_pe": _f(last.get("pe_ratio")),
        "current_ttm_eps": _f(last.get("ttm_eps")),
        "forward_pe": forward_pe,
        "forward_12m_eps": forward_12m_eps,
    }


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

    monthly_pe = build_monthly_pe(quarterly, annual, prices)
    stats = compute_pe_stats(ticker, monthly_pe)
    return monthly_pe, stats
