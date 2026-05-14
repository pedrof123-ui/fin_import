"""
PE, P/FCF, EV/EBITDA, and valuation goal calculation engine for historic fundamentals.

Computes monthly timeseries and statistics for a ticker using data already
present in av_financials.duckdb and prices.duckdb. No Alpha Vantage API calls
are made.

Usage:
    import duckdb
    from historic_fundamentals.pe import process_ticker, enrich_goals, extract_goal_stats

    av_conn     = duckdb.connect("data/av_financials.duckdb", read_only=True)
    prices_conn = duckdb.connect("/path/to/prices.duckdb", read_only=True)
    hf_conn     = duckdb.connect("data/historic_fundamentals.duckdb")

    monthly_pe, stats = process_ticker("AAPL", av_conn, prices_conn)
    monthly_pe = enrich_goals(monthly_pe, stats, hf_conn, "AAPL")
    stats.update(extract_goal_stats(monthly_pe))

    av_conn.close()
    prices_conn.close()

monthly_pe columns:
    month_end_date, price, ttm_eps, pe_ratio, pe_rolling_5yr_median,
    ttm_source, shares, ttm_dividend, dividend_yield, ttm_revenue,
    ttm_fcf, pfcf_ratio, pfcf_rolling_5yr_median, fcf_yield,
    ttm_ebitda, ev_ebitda, ev_ebitda_rolling_5yr_median,
    ps_ratio, ps_rolling_5yr_median,
    roa, roa_rolling_5yr_median, roe, roe_rolling_5yr_median,
    roic, roic_rolling_5yr_median,
    pbv, pbv_rolling_5yr_median, ptbv, ptbv_rolling_5yr_median,
    goal_pe, goal_pcf, goal_peg, goal_bv, goal_2x, goal_low, goal_high

stats keys (PE):
    ticker, current_price, pe_lt_median, pe_p10, pe_p25, pe_p75, pe_p90,
    months_available, pe_rolling_5yr_median, current_pe, current_ttm_eps,
    forward_pe, forward_12m_eps, ttm_dividend, dividend_yield

stats keys (FCF):
    current_pfcf, pfcf_lt_median, pfcf_p25, pfcf_p75, pfcf_rolling_5yr_median,
    current_fcf_yield, fcf_growth_1yr, fcf_cagr_3yr, fcf_cagr_5yr,
    fcf_margin_5yr_median

stats keys (EV/EBITDA):
    current_evebitda, evebitda_lt_median, evebitda_p25, evebitda_p75,
    evebitda_rolling_5yr_median

stats keys (P/S):
    current_ps, ps_lt_median, ps_p25, ps_p75, ps_rolling_5yr_median

stats keys (ROA/ROE/ROIC):
    current_roa, roa_lt_median, roa_p25, roa_p75, roa_rolling_5yr_median
    current_roe, roe_lt_median, roe_p25, roe_p75, roe_rolling_5yr_median
    current_roic, roic_lt_median, roic_p25, roic_p75, roic_rolling_5yr_median

stats keys (P/BV, P/TBV):
    current_pbv, pbv_lt_median, pbv_p25, pbv_p75, pbv_rolling_5yr_median
    current_ptbv, ptbv_lt_median, ptbv_p25, ptbv_p75, ptbv_rolling_5yr_median

stats keys (Goals):
    goal_pe, goal_pcf, goal_peg, goal_bv, goal_2x, goal_low, goal_high

TTM EPS method:
    Shares source (primary): shares_outstanding.shares_outstanding_diluted
    Shares source (fallback): balance_sheets.common_stock_shares_outstanding
    Quarterly available (>= 4 periods): sum last 4 quarters net_income / shares
    Quarterly not available: most recent annual net_income / shares (proxy)
    pe_ratio is NULL for months where ttm_eps <= 0

TTM FCF:
    FCF = operating_cashflow - capital_expenditures (AV reports capex as positive)
    Requires >= 4 quarterly cash flow periods; fallback to most recent annual.
    pfcf_ratio and fcf_yield are NULL when TTM FCF <= 0.

EV/EBITDA:
    TTM EBITDA: sum of last 4 quarterly ebitda; fallback to most recent annual.
    EV = price * shares + total_debt - cash
    total_debt = long_term_debt_noncurrent + short_term_debt + current_long_term_debt
    cash = cash_and_short_term_investments
    ev_ebitda is NULL when TTM EBITDA <= 0 or balance sheet data is unavailable.

Rolling 5yr medians:
    Require 60 consecutive monthly rows (min_periods=60). NULL for first 59 months.

Goal prices (enrich_goals):
    Fair-value price implied by trading at the long-term median multiple.
    goal_pe  = ttm_eps x pe_lt_median
    goal_pcf = (ttm_fcf / shares) x pfcf_lt_median
    goal_peg = forward_12m_eps (as-of month) x pe_lt_median
    goal_bv  = (price / pbv) x pbv_lt_median
    goal_2x  = 2 x price
    goal_low = min(avg of valid goals, goal_peg)   valid = non-null and > 0
    goal_high= max of valid goals
    goal_peg is NULL for months with no stored earnings_estimates.
    Requires hf_conn (historic_fundamentals DB) for historical forward EPS lookup.
"""

import logging
from datetime import UTC, date, datetime, timedelta

import duckdb
import pandas as pd

log = logging.getLogger(__name__)


def _load_av_data(av_conn: duckdb.DuckDBPyConnection, ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (quarterly_df, annual_df).
    Columns: fiscal_date_ending, net_income, total_revenue, ebitda, shares,
             long_term_debt_noncurrent, short_term_debt, current_long_term_debt, cash
    shares is from balance_sheets (fallback when shares_outstanding is unavailable).
    """
    sql = """
        SELECT
            i.fiscal_date_ending,
            i.net_income,
            i.total_revenue,
            i.ebitda,
            i.ebit,
            i.income_tax_expense,
            i.income_before_tax,
            b.common_stock_shares_outstanding AS shares,
            b.total_assets,
            b.total_shareholder_equity,
            b.intangible_assets_excl_goodwill,
            b.goodwill,
            b.long_term_debt_noncurrent,
            b.short_term_debt,
            b.current_long_term_debt,
            b.cash_and_short_term_investments AS cash
        FROM income_statements i
        LEFT JOIN balance_sheets b
            ON  i.ticker      = b.ticker
            AND i.fiscal_date_ending = b.fiscal_date_ending
            AND i.period_type = b.period_type
        WHERE i.ticker = ? AND i.period_type = ?
        ORDER BY i.fiscal_date_ending
    """
    quarterly = av_conn.execute(sql, [ticker, "quarterly"]).df()
    annual    = av_conn.execute(sql, [ticker, "annual"]).df()
    return quarterly, annual


def _load_cashflow_data(av_conn: duckdb.DuckDBPyConnection, ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (cashflow_quarterly_df, cashflow_annual_df).
    Columns: fiscal_date_ending, operating_cashflow, capital_expenditures
    AV reports capital_expenditures as a positive number.
    FCF = operating_cashflow - capital_expenditures
    """
    sql = """
        SELECT fiscal_date_ending, operating_cashflow, capital_expenditures
        FROM cash_flow_statements
        WHERE ticker = ? AND period_type = ?
        ORDER BY fiscal_date_ending
    """
    quarterly = av_conn.execute(sql, [ticker, "quarterly"]).df()
    annual    = av_conn.execute(sql, [ticker, "annual"]).df()
    return quarterly, annual


def _load_shares_ts(av_conn: duckdb.DuckDBPyConnection, ticker: str) -> pd.DataFrame:
    """
    Returns DataFrame with columns: date, shares_outstanding_diluted.
    Empty if no data for this ticker.
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
    Returns DataFrame with columns: ex_dividend_date, amount.
    Empty if no dividend data for this ticker.
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
    Returns DataFrame with: month_end_date, price (adj_close on last trading day of month).
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
    Fallback: most recent balance-sheet shares from quarterly, then annual.
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


def _get_ttm_fcf(
    month_end,
    cashflow_q: pd.DataFrame,
    cashflow_a: pd.DataFrame,
) -> float | None:
    """
    TTM FCF = operating_cashflow - capital_expenditures, summed over trailing 4 quarters.
    Falls back to most recent annual if quarterly unavailable.
    AV reports capital_expenditures as positive; NULL capex is treated as zero.
    """
    if not cashflow_q.empty:
        avail = cashflow_q[cashflow_q["fiscal_date_ending"] <= month_end]
        if len(avail) >= 4:
            last4 = avail.tail(4)
            ocf = last4["operating_cashflow"].dropna()
            if len(ocf) == 4:
                capex = last4["capital_expenditures"].fillna(0)
                return float(ocf.sum()) - float(capex.sum())

    if not cashflow_a.empty:
        avail = cashflow_a[cashflow_a["fiscal_date_ending"] <= month_end]
        if not avail.empty:
            row = avail.iloc[-1]
            ocf = row["operating_cashflow"]
            if pd.notna(ocf):
                capex = float(row["capital_expenditures"]) if pd.notna(row["capital_expenditures"]) else 0.0
                return float(ocf) - capex

    return None


def _get_ttm_ebitda(
    month_end,
    quarterly: pd.DataFrame,
    annual: pd.DataFrame,
) -> float | None:
    """
    TTM EBITDA = sum of ebitda over trailing 4 quarters.
    Falls back to most recent annual ebitda.
    Returns None if not computable.
    """
    if not quarterly.empty:
        avail = quarterly[quarterly["fiscal_date_ending"] <= month_end]
        if len(avail) >= 4:
            last4 = avail.tail(4)["ebitda"].dropna()
            if len(last4) == 4:
                return float(last4.sum())

    if not annual.empty:
        avail = annual[annual["fiscal_date_ending"] <= month_end]
        if not avail.empty:
            v = avail.iloc[-1]["ebitda"]
            if pd.notna(v) and float(v) > 0:
                return float(v)

    return None


def _get_ttm_nopat(
    month_end,
    quarterly: pd.DataFrame,
    annual: pd.DataFrame,
) -> float | None:
    """
    TTM NOPAT = TTM EBIT × (1 − effective_tax_rate).
    Effective tax rate = TTM income_tax_expense / TTM income_before_tax, clamped [0, 0.5].
    Uses 0.21 default when income_before_tax is not positive.
    Returns None when EBIT data is unavailable.
    """
    if not quarterly.empty:
        avail = quarterly[quarterly["fiscal_date_ending"] <= month_end]
        if len(avail) >= 4:
            last4 = avail.tail(4)
            ebit_vals = last4["ebit"].dropna()
            if len(ebit_vals) == 4:
                ttm_ebit = float(ebit_vals.sum())
                ibt = float(last4["income_before_tax"].dropna().sum())
                tax = float(last4["income_tax_expense"].dropna().sum())
                rate = min(max(tax / ibt, 0.0), 0.5) if ibt > 0 else 0.21
                return ttm_ebit * (1.0 - rate)

    if not annual.empty:
        avail = annual[annual["fiscal_date_ending"] <= month_end]
        if not avail.empty:
            row = avail.iloc[-1]
            ebit = row.get("ebit")
            if pd.notna(ebit):
                ibt = row.get("income_before_tax")
                tax = row.get("income_tax_expense")
                ibt_f = float(ibt) if pd.notna(ibt) else 0.0
                tax_f = float(tax) if pd.notna(tax) else 0.0
                rate = min(max(tax_f / ibt_f, 0.0), 0.5) if ibt_f > 0 else 0.21
                return float(ebit) * (1.0 - rate)

    return None


def _get_ev_debt_cash(
    month_end,
    quarterly: pd.DataFrame,
    annual: pd.DataFrame,
) -> tuple[float | None, float | None]:
    """
    Return (total_debt, cash) from the most recent balance sheet as of month_end.
    total_debt = long_term_debt_noncurrent + short_term_debt + current_long_term_debt
    At least one debt component must be non-NULL to produce a debt figure.
    """
    for df in (quarterly, annual):
        if df.empty:
            continue
        avail = df[df["fiscal_date_ending"] <= month_end]
        if avail.empty:
            continue
        row = avail.iloc[-1]

        ltdn = row.get("long_term_debt_noncurrent")
        std  = row.get("short_term_debt")
        cltd = row.get("current_long_term_debt")
        cash = row.get("cash")

        has_debt = pd.notna(ltdn) or pd.notna(std) or pd.notna(cltd)
        if not has_debt:
            continue

        total_debt = (
            (float(ltdn) if pd.notna(ltdn) else 0.0)
            + (float(std)  if pd.notna(std)  else 0.0)
            + (float(cltd) if pd.notna(cltd) else 0.0)
        )
        cash_val = float(cash) if pd.notna(cash) else None
        return total_debt, cash_val

    return None, None


def build_monthly_pe(
    quarterly: pd.DataFrame,
    annual: pd.DataFrame,
    prices: pd.DataFrame,
    shares_ts: pd.DataFrame | None = None,
    dividends: pd.DataFrame | None = None,
    cashflow_q: pd.DataFrame | None = None,
    cashflow_a: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Build monthly PE, P/FCF, and EV/EBITDA timeseries.

    For each month with price data:
    - TTM EPS: sum of last 4 quarterly net_income / shares; fallback to annual
    - TTM FCF: sum of last 4 quarterly (operating_cashflow - capex); fallback to annual
    - TTM EBITDA: sum of last 4 quarterly ebitda; fallback to annual
    - EV = price * shares + total_debt - cash (balance sheet as of month_end)
    - pe_ratio, pfcf_ratio, ev_ebitda are NULL when denominators are <= 0
    - Rolling 5yr medians require 60 consecutive monthly rows (min_periods=60)

    Returns DataFrame with columns:
    month_end_date, price, ttm_eps, pe_ratio, pe_rolling_5yr_median, ttm_source,
    shares, ttm_dividend, dividend_yield, ttm_revenue,
    ttm_fcf, pfcf_ratio, pfcf_rolling_5yr_median, fcf_yield,
    ttm_ebitda, ev_ebitda, ev_ebitda_rolling_5yr_median,
    ps_ratio, ps_rolling_5yr_median,
    roa, roa_rolling_5yr_median, roe, roe_rolling_5yr_median,
    roic, roic_rolling_5yr_median,
    pbv, pbv_rolling_5yr_median, ptbv, ptbv_rolling_5yr_median
    """
    if prices.empty:
        return pd.DataFrame()

    q  = quarterly.copy()
    a  = annual.copy()
    p  = prices.copy()
    st = shares_ts.copy() if shares_ts is not None and not shares_ts.empty else pd.DataFrame()
    dv = dividends.copy() if dividends is not None and not dividends.empty else pd.DataFrame()
    cfq = cashflow_q.copy() if cashflow_q is not None and not cashflow_q.empty else pd.DataFrame()
    cfa = cashflow_a.copy() if cashflow_a is not None and not cashflow_a.empty else pd.DataFrame()

    for df in (q, a):
        if not df.empty:
            df["fiscal_date_ending"] = pd.to_datetime(df["fiscal_date_ending"]).dt.date
    for df in (cfq, cfa):
        if not df.empty:
            df["fiscal_date_ending"] = pd.to_datetime(df["fiscal_date_ending"]).dt.date
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

        # ── Shares ────────────────────────────────────────────────────────────
        sh = _get_shares(month_end, st, q, a)

        # ── TTM EPS / PE ──────────────────────────────────────────────────────
        ttm_eps = None
        source = None

        if sh is not None and not q.empty:
            avail = q[q["fiscal_date_ending"] <= month_end]
            if len(avail) >= 4:
                last4 = avail.tail(4)
                ni_vals = last4["net_income"].dropna()
                if len(ni_vals) == 4:
                    ttm_eps = float(ni_vals.sum()) / sh
                    source = "quarterly"

        if ttm_eps is None and sh is not None and not a.empty:
            avail = a[a["fiscal_date_ending"] <= month_end]
            if not avail.empty:
                ni = avail.iloc[-1]["net_income"]
                if pd.notna(ni):
                    ttm_eps = float(ni) / sh
                    source = "annual"

        if ttm_eps is None:
            continue

        pe = float(price) / ttm_eps if ttm_eps > 0 else None

        # ── Dividends ─────────────────────────────────────────────────────────
        ttm_dividend = None
        dividend_yield = None
        if not dv.empty:
            window_start = month_end - timedelta(days=365)
            window = dv[(dv["ex_dividend_date"] > window_start) & (dv["ex_dividend_date"] <= month_end)]
            if not window.empty:
                ttm_dividend = float(window["amount"].sum())
                dividend_yield = ttm_dividend / float(price)

        # ── TTM Revenue ───────────────────────────────────────────────────────
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

        # ── TTM FCF / P/FCF ───────────────────────────────────────────────────
        ttm_fcf = _get_ttm_fcf(month_end, cfq, cfa)
        fcf_per_share = None
        pfcf_ratio = None
        fcf_yield = None
        if ttm_fcf is not None and sh is not None and sh > 0:
            fcf_per_share = ttm_fcf / sh
            if fcf_per_share > 0:
                pfcf_ratio = float(price) / fcf_per_share
            fcf_yield = fcf_per_share / float(price)  # always defined; negative when FCF < 0

        # ── TTM EBITDA / EV/EBITDA ────────────────────────────────────────────
        # sh is sourced from shares_outstanding_diluted (split-adjusted) so
        # price * sh gives the correct split-adjusted market cap.
        ttm_ebitda = _get_ttm_ebitda(month_end, q, a)
        ev = None
        ev_ebitda = None
        ebitda_ev_yield = None
        if sh is not None:
            total_debt, cash = _get_ev_debt_cash(month_end, q, a)
            if total_debt is not None and cash is not None:
                computed_ev = float(price) * sh + total_debt - cash
                if computed_ev > 0:
                    ev = computed_ev
                    if ttm_ebitda is not None and ttm_ebitda > 0:
                        ev_ebitda = ev / ttm_ebitda
                    if ttm_ebitda is not None:
                        ebitda_ev_yield = ttm_ebitda / ev  # always defined; negative when EBITDA < 0

        # ── Balance sheet snapshot for new metrics ────────────────────────────
        bs_equity = bs_assets = bs_intang = bs_gw = None
        for _df in (q, a):
            if _df.empty:
                continue
            _avail = _df[_df["fiscal_date_ending"] <= month_end]
            if _avail.empty:
                continue
            _r = _avail.iloc[-1]
            if bs_equity is None:
                _v = _r.get("total_shareholder_equity")
                if pd.notna(_v):
                    bs_equity = float(_v)
            if bs_assets is None:
                _v = _r.get("total_assets")
                if pd.notna(_v) and float(_v) > 0:
                    bs_assets = float(_v)
            if bs_intang is None:
                _ieg = _r.get("intangible_assets_excl_goodwill")
                _gw  = _r.get("goodwill")
                if pd.notna(_ieg) or pd.notna(_gw):
                    bs_intang = float(_ieg) if pd.notna(_ieg) else 0.0
                    bs_gw     = float(_gw)  if pd.notna(_gw)  else 0.0
            if bs_equity is not None and bs_assets is not None and bs_intang is not None:
                break

        # ── P/S ──────────────────────────────────────────────────────────────
        ps_ratio = None
        if ttm_revenue is not None and ttm_revenue > 0 and sh is not None and sh > 0:
            ps_ratio = float(price) * sh / ttm_revenue

        # ── ROA, ROE ─────────────────────────────────────────────────────────
        ttm_net_income = ttm_eps * sh  # safe: both non-None after the continue guard
        roa = roe = None
        if bs_assets is not None:
            roa = ttm_net_income / bs_assets
        if bs_equity is not None and bs_equity > 0:
            roe = ttm_net_income / bs_equity

        # ── ROIC ─────────────────────────────────────────────────────────────
        nopat = _get_ttm_nopat(month_end, q, a)
        roic = None
        if nopat is not None and bs_equity is not None:
            _td, _cash = _get_ev_debt_cash(month_end, q, a)
            invested_capital = bs_equity + (_td or 0.0) - (_cash or 0.0)
            if invested_capital > 0:
                roic = nopat / invested_capital

        # ── P/BV, P/TBV ──────────────────────────────────────────────────────
        pbv = ptbv = None
        if sh is not None and sh > 0:
            if bs_equity is not None and bs_equity > 0:
                pbv = float(price) / (bs_equity / sh)
            if bs_equity is not None and bs_intang is not None and bs_gw is not None:
                tbv = bs_equity - bs_intang - bs_gw
                if tbv > 0:
                    ptbv = float(price) / (tbv / sh)

        rows.append({
            "month_end_date": month_end,
            "price":          float(price),
            "ttm_eps":        ttm_eps,
            "pe_ratio":       pe,
            "ttm_source":     source,
            "shares":         sh,
            "ttm_dividend":   ttm_dividend,
            "dividend_yield": dividend_yield,
            "ttm_revenue":    ttm_revenue,
            "ttm_fcf":          ttm_fcf,
            "fcf_per_share":    fcf_per_share,
            "pfcf_ratio":       pfcf_ratio,
            "fcf_yield":        fcf_yield,
            "ttm_ebitda":       ttm_ebitda,
            "ev":               ev,
            "ev_ebitda":        ev_ebitda,
            "ebitda_ev_yield":  ebitda_ev_yield,
            "ps_ratio":         ps_ratio,
            "roa":            roa,
            "roe":            roe,
            "roic":           roic,
            "pbv":            pbv,
            "ptbv":           ptbv,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("month_end_date").reset_index(drop=True)
    df["pe_rolling_5yr_median"]        = df["pe_ratio"].rolling(60, min_periods=36).median()
    df["pfcf_rolling_5yr_median"]      = df["pfcf_ratio"].rolling(60, min_periods=36).median()
    df["ev_ebitda_rolling_5yr_median"] = df["ev_ebitda"].rolling(60, min_periods=36).median()
    df["ps_rolling_5yr_median"]        = df["ps_ratio"].rolling(60, min_periods=36).median()
    df["roa_rolling_5yr_median"]       = df["roa"].rolling(60, min_periods=36).median()
    df["roe_rolling_5yr_median"]       = df["roe"].rolling(60, min_periods=36).median()
    df["roic_rolling_5yr_median"]      = df["roic"].rolling(60, min_periods=36).median()
    df["pbv_rolling_5yr_median"]       = df["pbv"].rolling(60, min_periods=36).median()
    df["ptbv_rolling_5yr_median"]      = df["ptbv"].rolling(60, min_periods=36).median()

    # Earnings yield = EPS / price (meaningful even when negative; avoids P/E blow-up)
    df["earnings_yield"]        = df["ttm_eps"] / df["price"]
    df["earnings_yield_3y_avg"] = df["earnings_yield"].rolling(36, min_periods=24).mean()
    df["earnings_yield_5y_avg"] = df["earnings_yield"].rolling(60, min_periods=36).mean()

    # Normalized P/E: price / avg(TTM EPS over 5yr). Includes negative EPS years honestly.
    avg_eps_5y = df["ttm_eps"].rolling(60, min_periods=36).mean()
    df["normalized_pe_5y"] = (df["price"] / avg_eps_5y).where(avg_eps_5y > 0)

    # FCF yield rolling avgs + normalized P/FCF (fcf_yield is now always defined when FCF computable)
    df["fcf_yield_3y_avg"]  = df["fcf_yield"].rolling(36, min_periods=24).mean()
    df["fcf_yield_5y_avg"]  = df["fcf_yield"].rolling(60, min_periods=36).mean()
    avg_fcf_ps_5y = df["fcf_per_share"].rolling(60, min_periods=36).mean()
    df["normalized_pfcf_5y"] = (df["price"] / avg_fcf_ps_5y).where(avg_fcf_ps_5y > 0)

    # EBITDA/EV yield rolling avgs + normalized EV/EBITDA
    df["ebitda_ev_yield_3y_avg"]  = df["ebitda_ev_yield"].rolling(36, min_periods=24).mean()
    df["ebitda_ev_yield_5y_avg"]  = df["ebitda_ev_yield"].rolling(60, min_periods=36).mean()
    avg_ebitda_5y = df["ttm_ebitda"].rolling(60, min_periods=36).mean()
    df["normalized_evebitda_5y"] = (df["ev"] / avg_ebitda_5y).where(avg_ebitda_5y > 0)

    # Normalized P/S: market_cap / avg(TTM revenue over 5yr)
    avg_revenue_5y = df["ttm_revenue"].rolling(60, min_periods=36).mean()
    df["normalized_ps_5y"] = (df["price"] * df["shares"] / avg_revenue_5y).where(avg_revenue_5y > 0)

    return df


def compute_pe_stats(
    ticker: str,
    monthly_pe: pd.DataFrame,
    forward_pe: float | None = None,
    forward_12m_eps: float | None = None,
) -> dict | None:
    """
    Compute PE, P/FCF, and EV/EBITDA statistics from the monthly timeseries.
    """
    if monthly_pe.empty:
        return None

    pe_series = monthly_pe["pe_ratio"].dropna()
    last = monthly_pe.iloc[-1]

    def _f(v) -> float | None:
        return float(v) if pd.notna(v) else None

    def _stats(series: pd.Series, prefix: str) -> dict:
        if series.empty:
            return {}
        return {
            f"{prefix}_lt_median": _f(series.median()),
            f"{prefix}_p25":       _f(series.quantile(0.25)),
            f"{prefix}_p75":       _f(series.quantile(0.75)),
        }

    current_price = _f(last.get("price"))
    forward_earnings_yield = None
    if forward_12m_eps is not None and current_price and current_price > 0:
        forward_earnings_yield = forward_12m_eps / current_price

    result = {
        "ticker":                 ticker,
        "updated_at":             datetime.now(UTC),
        "current_price":          current_price,
        # PE
        "pe_lt_median":           _f(pe_series.median()),
        "pe_p10":                 _f(pe_series.quantile(0.10)),
        "pe_p25":                 _f(pe_series.quantile(0.25)),
        "pe_p75":                 _f(pe_series.quantile(0.75)),
        "pe_p90":                 _f(pe_series.quantile(0.90)),
        "months_available":       int(len(pe_series)),
        "pe_rolling_5yr_median":  _f(last.get("pe_rolling_5yr_median")),
        "current_pe":             _f(last.get("pe_ratio")),
        "current_ttm_eps":        _f(last.get("ttm_eps")),
        "forward_pe":             forward_pe,
        "forward_12m_eps":        forward_12m_eps,
        "ttm_dividend":           _f(last.get("ttm_dividend")),
        "dividend_yield":         _f(last.get("dividend_yield")),
        # Earnings yield
        "current_earnings_yield": _f(last.get("earnings_yield")),
        "earnings_yield_3y_avg":  _f(last.get("earnings_yield_3y_avg")),
        "earnings_yield_5y_avg":  _f(last.get("earnings_yield_5y_avg")),
        "forward_earnings_yield": forward_earnings_yield,
        # Normalized P/E (CAPE-style: price / avg 5yr TTM EPS, includes loss years)
        "normalized_pe_5y":       _f(last.get("normalized_pe_5y")),
    }

    # FCF
    pfcf_series = monthly_pe["pfcf_ratio"].dropna() if "pfcf_ratio" in monthly_pe.columns else pd.Series(dtype=float)
    result.update(_stats(pfcf_series, "pfcf"))
    result.update({
        "current_pfcf":            _f(last.get("pfcf_ratio")),
        "pfcf_rolling_5yr_median": _f(last.get("pfcf_rolling_5yr_median")),
        "current_fcf_yield":       _f(last.get("fcf_yield")),
        "fcf_yield_3y_avg":        _f(last.get("fcf_yield_3y_avg")),
        "fcf_yield_5y_avg":        _f(last.get("fcf_yield_5y_avg")),
        "normalized_pfcf_5y":      _f(last.get("normalized_pfcf_5y")),
    })

    # EV/EBITDA
    ev_series = monthly_pe["ev_ebitda"].dropna() if "ev_ebitda" in monthly_pe.columns else pd.Series(dtype=float)
    result.update(_stats(ev_series, "evebitda"))
    result.update({
        "current_evebitda":            _f(last.get("ev_ebitda")),
        "evebitda_rolling_5yr_median": _f(last.get("ev_ebitda_rolling_5yr_median")),
        "current_ebitda_ev_yield":     _f(last.get("ebitda_ev_yield")),
        "ebitda_ev_yield_3y_avg":      _f(last.get("ebitda_ev_yield_3y_avg")),
        "ebitda_ev_yield_5y_avg":      _f(last.get("ebitda_ev_yield_5y_avg")),
        "normalized_evebitda_5y":      _f(last.get("normalized_evebitda_5y")),
    })

    # P/S
    ps_series = monthly_pe["ps_ratio"].dropna() if "ps_ratio" in monthly_pe.columns else pd.Series(dtype=float)
    result.update(_stats(ps_series, "ps"))
    result.update({
        "current_ps":            _f(last.get("ps_ratio")),
        "ps_rolling_5yr_median": _f(last.get("ps_rolling_5yr_median")),
        "normalized_ps_5y":      _f(last.get("normalized_ps_5y")),
    })

    # ROA
    roa_series = monthly_pe["roa"].dropna() if "roa" in monthly_pe.columns else pd.Series(dtype=float)
    result.update(_stats(roa_series, "roa"))
    result.update({
        "current_roa":            _f(last.get("roa")),
        "roa_rolling_5yr_median": _f(last.get("roa_rolling_5yr_median")),
    })

    # ROE
    roe_series = monthly_pe["roe"].dropna() if "roe" in monthly_pe.columns else pd.Series(dtype=float)
    result.update(_stats(roe_series, "roe"))
    result.update({
        "current_roe":            _f(last.get("roe")),
        "roe_rolling_5yr_median": _f(last.get("roe_rolling_5yr_median")),
    })

    # ROIC
    roic_series = monthly_pe["roic"].dropna() if "roic" in monthly_pe.columns else pd.Series(dtype=float)
    result.update(_stats(roic_series, "roic"))
    result.update({
        "current_roic":            _f(last.get("roic")),
        "roic_rolling_5yr_median": _f(last.get("roic_rolling_5yr_median")),
    })

    # P/BV
    pbv_series = monthly_pe["pbv"].dropna() if "pbv" in monthly_pe.columns else pd.Series(dtype=float)
    result.update(_stats(pbv_series, "pbv"))
    result.update({
        "current_pbv":            _f(last.get("pbv")),
        "pbv_rolling_5yr_median": _f(last.get("pbv_rolling_5yr_median")),
    })

    # P/TBV
    ptbv_series = monthly_pe["ptbv"].dropna() if "ptbv" in monthly_pe.columns else pd.Series(dtype=float)
    result.update(_stats(ptbv_series, "ptbv"))
    result.update({
        "current_ptbv":            _f(last.get("ptbv")),
        "ptbv_rolling_5yr_median": _f(last.get("ptbv_rolling_5yr_median")),
    })

    return result


def compute_revenue_stats(annual: pd.DataFrame) -> dict:
    """
    Compute revenue growth metrics from annual income statement data.

    Returns dict with any subset of:
        rev_growth_1yr, rev_cagr_3yr, rev_cagr_5yr
    All values are decimals (e.g. 0.12 = 12% growth).
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


def compute_earnings_stats(annual: pd.DataFrame) -> dict:
    """
    Compute EPS growth metrics from annual income statement data.

    Returns dict with any subset of:
        earn_growth_1yr, earn_cagr_3yr, earn_cagr_5yr
    EPS = net_income / shares. Only computed when both EPS values are positive.
    """
    if annual.empty:
        return {}

    a = annual.copy()
    a["fiscal_date_ending"] = pd.to_datetime(a["fiscal_date_ending"]).dt.date
    a = a.dropna(subset=["net_income", "shares"])
    a = a[(a["net_income"] > 0) & (a["shares"] > 0)].sort_values("fiscal_date_ending").reset_index(drop=True)

    if a.empty:
        return {}

    a["eps"] = a["net_income"] / a["shares"]

    latest_date: date = a.iloc[-1]["fiscal_date_ending"]
    latest_eps = float(a.iloc[-1]["eps"])
    result = {}

    for key, n_years in [("earn_growth_1yr", 1), ("earn_cagr_3yr", 3), ("earn_cagr_5yr", 5)]:
        target = latest_date - timedelta(days=int(n_years * 365.25))
        diffs = a["fiscal_date_ending"].apply(lambda d: abs((d - target).days))
        idx = int(diffs.idxmin())
        diff_days = int(diffs[idx])
        base_date: date = a.loc[idx, "fiscal_date_ending"]
        if diff_days <= 180 and base_date < latest_date:
            base_eps = float(a.loc[idx, "eps"])
            actual_years = (latest_date - base_date).days / 365.25
            if actual_years > 0 and base_eps > 0:
                result[key] = (latest_eps / base_eps) ** (1.0 / actual_years) - 1.0

    return result


def compute_fcf_stats(cashflow_annual: pd.DataFrame, income_annual: pd.DataFrame) -> dict:
    """
    Compute FCF growth metrics and 5-year median FCF margin from annual data.

    FCF = operating_cashflow - capital_expenditures (AV reports capex as positive).
    FCF margin = FCF / total_revenue.
    Growth metrics use the same CAGR pattern as revenue and earnings.
    Only positive FCF years are used for growth/margin calculations.

    Returns dict with any subset of:
        fcf_growth_1yr, fcf_cagr_3yr, fcf_cagr_5yr, fcf_margin_5yr_median
    """
    if cashflow_annual.empty:
        return {}

    cf = cashflow_annual.copy()
    cf["fiscal_date_ending"] = pd.to_datetime(cf["fiscal_date_ending"]).dt.date
    cf = cf.dropna(subset=["operating_cashflow"])
    capex = cf["capital_expenditures"].fillna(0)
    cf["fcf"] = cf["operating_cashflow"] - capex
    cf = cf[cf["fcf"] > 0].sort_values("fiscal_date_ending").reset_index(drop=True)

    if cf.empty:
        return {}

    latest_date: date = cf.iloc[-1]["fiscal_date_ending"]
    latest_fcf = float(cf.iloc[-1]["fcf"])
    result = {}

    for key, n_years in [("fcf_growth_1yr", 1), ("fcf_cagr_3yr", 3), ("fcf_cagr_5yr", 5)]:
        target = latest_date - timedelta(days=int(n_years * 365.25))
        diffs = cf["fiscal_date_ending"].apply(lambda d: abs((d - target).days))
        idx = int(diffs.idxmin())
        diff_days = int(diffs[idx])
        base_date: date = cf.loc[idx, "fiscal_date_ending"]
        if diff_days <= 180 and base_date < latest_date:
            base_fcf = float(cf.loc[idx, "fcf"])
            actual_years = (latest_date - base_date).days / 365.25
            if actual_years > 0 and base_fcf > 0:
                result[key] = (latest_fcf / base_fcf) ** (1.0 / actual_years) - 1.0

    if not income_annual.empty:
        ia = income_annual.copy()
        ia["fiscal_date_ending"] = pd.to_datetime(ia["fiscal_date_ending"]).dt.date
        ia = ia.dropna(subset=["total_revenue"])
        ia = ia[ia["total_revenue"] > 0]

        # 5yr median FCF margin
        merged = cf.merge(ia[["fiscal_date_ending", "total_revenue"]], on="fiscal_date_ending", how="inner")
        last5_fcf = merged.sort_values("fiscal_date_ending").tail(5)
        if not last5_fcf.empty:
            margins = (last5_fcf["fcf"] / last5_fcf["total_revenue"]).dropna()
            if not margins.empty:
                result["fcf_margin_5yr_median"] = float(margins.median())

        # 5yr median EBITDA margin
        ia_ebitda = ia.dropna(subset=["ebitda"])
        ia_ebitda = ia_ebitda[ia_ebitda["ebitda"] > 0].sort_values("fiscal_date_ending")
        last5_eb = ia_ebitda.tail(5)
        if not last5_eb.empty:
            eb_margins = (last5_eb["ebitda"] / last5_eb["total_revenue"]).dropna()
            if not eb_margins.empty:
                result["ebitda_margin_5yr_median"] = float(eb_margins.median())

    return result


def _compute_peg_eps_series(
    hf_conn: duckdb.DuckDBPyConnection,
    ticker: str,
    month_end_dates: list,
) -> dict:
    """
    {month_end_date: forward_12m_eps} using earnings_estimates stored in hf_conn.
    For each date, uses the most recent snapshot available as of that date.
    Sums next 4 quarterly eps_avg; falls back to next annual estimate.
    Returns empty dict when no estimates exist.
    """
    try:
        q_df = hf_conn.execute("""
            SELECT fiscal_date::DATE AS fiscal_date,
                   fetched_at::DATE AS fetched_date,
                   eps_avg
            FROM earnings_estimates
            WHERE ticker = ? AND horizon = 'fiscal quarter' AND eps_avg IS NOT NULL
        """, [ticker]).df()
        a_df = hf_conn.execute("""
            SELECT fiscal_date::DATE AS fiscal_date,
                   fetched_at::DATE AS fetched_date,
                   eps_avg
            FROM earnings_estimates
            WHERE ticker = ? AND horizon = 'fiscal year' AND eps_avg IS NOT NULL
        """, [ticker]).df()
    except Exception:
        return {}

    if q_df.empty and a_df.empty:
        return {}

    for df in (q_df, a_df):
        if not df.empty:
            df["fiscal_date"] = pd.to_datetime(df["fiscal_date"]).dt.date
            df["fetched_date"] = pd.to_datetime(df["fetched_date"]).dt.date

    result: dict = {}
    for month_end in month_end_dates:
        fwd_eps = None

        if not q_df.empty:
            avail = q_df[q_df["fetched_date"] <= month_end]
            if not avail.empty:
                latest = (
                    avail.sort_values("fetched_date")
                    .groupby("fiscal_date", sort=False)
                    .last()
                    .reset_index()
                )
                future = latest[latest["fiscal_date"] > month_end].sort_values("fiscal_date")
                if len(future) >= 4:
                    fwd_eps = float(future.head(4)["eps_avg"].sum())

        if fwd_eps is None and not a_df.empty:
            avail = a_df[a_df["fetched_date"] <= month_end]
            if not avail.empty:
                latest = (
                    avail.sort_values("fetched_date")
                    .groupby("fiscal_date", sort=False)
                    .last()
                    .reset_index()
                )
                future = latest[latest["fiscal_date"] > month_end].sort_values("fiscal_date")
                if not future.empty:
                    fwd_eps = float(future.iloc[0]["eps_avg"])

        result[month_end] = fwd_eps

    return result


def enrich_goals(
    monthly_pe: pd.DataFrame,
    stats: dict,
    hf_conn: duckdb.DuckDBPyConnection,
    ticker: str,
) -> pd.DataFrame:
    """
    Add goal price columns to the monthly timeseries.

    Goals are the implied fair-value price if the stock traded at its historical
    median multiple:
        goal_pe  = ttm_eps × pe_lt_median
        goal_pcf = (ttm_fcf / shares) × pfcf_lt_median
        goal_peg = forward_12m_eps (as-of month) × pe_lt_median
        goal_bv  = (price / pbv) × pbv_lt_median
        goal_2x  = 2 × price
        goal_low = min(avg of valid goals, goal_peg)
        goal_high= max of valid goals  [valid = non-null and > 0]

    goal_peg is NULL for months without stored earnings_estimates.
    """
    if monthly_pe.empty or not stats:
        return monthly_pe

    pe_lt   = stats.get("pe_lt_median")
    pfcf_lt = stats.get("pfcf_lt_median")
    pbv_lt  = stats.get("pbv_lt_median")

    month_end_dates = list(monthly_pe["month_end_date"])
    peg_map = _compute_peg_eps_series(hf_conn, ticker, month_end_dates) if hf_conn is not None else {}

    rows_out = []
    for row in monthly_pe.itertuples(index=False):
        month_end = row.month_end_date
        price     = float(row.price)

        g_pe = None
        eps = getattr(row, "ttm_eps", None)
        if pe_lt and eps is not None and pd.notna(eps) and float(eps) > 0:
            g_pe = float(eps) * pe_lt

        g_pcf = None
        fcf = getattr(row, "ttm_fcf", None)
        sh  = getattr(row, "shares", None)
        if (pfcf_lt and fcf is not None and sh is not None
                and pd.notna(fcf) and pd.notna(sh)
                and float(fcf) > 0 and float(sh) > 0):
            g_pcf = (float(fcf) / float(sh)) * pfcf_lt

        g_peg = None
        fwd = peg_map.get(month_end)
        if pe_lt and fwd is not None and fwd > 0:
            g_peg = fwd * pe_lt

        g_bv = None
        pbv = getattr(row, "pbv", None)
        if pbv_lt and pbv is not None and pd.notna(pbv) and float(pbv) > 0:
            g_bv = (price / float(pbv)) * pbv_lt

        g_2x = price * 2.0

        valid = [g for g in (g_pe, g_pcf, g_peg, g_bv) if g is not None and g > 0]
        if valid:
            avg    = sum(valid) / len(valid)
            g_low  = min(avg, g_peg) if (g_peg is not None and g_peg > 0) else avg
            g_high = max(valid)
        else:
            g_low = g_high = None

        rows_out.append({
            **row._asdict(),
            "goal_pe":   g_pe,
            "goal_pcf":  g_pcf,
            "goal_peg":  g_peg,
            "goal_bv":   g_bv,
            "goal_2x":   g_2x,
            "goal_low":  g_low,
            "goal_high": g_high,
        })

    return pd.DataFrame(rows_out)


def extract_goal_stats(monthly_pe: pd.DataFrame) -> dict:
    """Extract current (latest row) goal values for merging into pe_stats."""
    if monthly_pe.empty:
        return {}
    last = monthly_pe.iloc[-1]
    def _f(v):
        return float(v) if pd.notna(v) else None
    return {k: _f(last.get(k)) for k in ("goal_pe", "goal_pcf", "goal_peg", "goal_bv", "goal_2x", "goal_low", "goal_high")}


def process_ticker(
    ticker: str,
    av_conn: duckdb.DuckDBPyConnection,
    prices_conn: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, dict | None]:
    """
    Load data, build monthly timeseries, compute stats.
    Returns (monthly_df, stats_dict). Both may be empty/None on failure.
    """
    quarterly, annual = _load_av_data(av_conn, ticker)

    if quarterly.empty and annual.empty:
        log.warning("%s: no financial data in av_financials", ticker)
        return pd.DataFrame(), None

    prices = _load_monthly_prices(prices_conn, ticker)
    if prices.empty:
        log.warning("%s: no price data", ticker)
        return pd.DataFrame(), None

    shares_ts  = _load_shares_ts(av_conn, ticker)
    dividends  = _load_dividends(av_conn, ticker)
    cashflow_q, cashflow_a = _load_cashflow_data(av_conn, ticker)

    monthly_pe = build_monthly_pe(
        quarterly, annual, prices, shares_ts, dividends, cashflow_q, cashflow_a
    )
    stats = compute_pe_stats(ticker, monthly_pe)
    if stats:
        stats.update(compute_revenue_stats(annual))
        stats.update(compute_earnings_stats(annual))
        stats.update(compute_fcf_stats(cashflow_a, annual))
    return monthly_pe, stats
