"""
Notebook-friendly query functions for av_financials.duckdb.

Usage:
    from av_financials import get_income, get_balance, get_cashflow, get_overview

    # Single ticker — returns all annual rows
    income  = get_income("AAPL")
    balance = get_balance("AAPL")
    cf      = get_cashflow("AAPL")
    overview = get_overview("AAPL")

    # Multiple tickers
    income = get_income(["AAPL", "MSFT"])

    # Quarterly from a given date
    income = get_income("AAPL", period="quarterly", start_date="2022-01-01")

All functions return a pandas DataFrame sorted by ticker, fiscal_date_ending descending.
The DB path is read from the AV_DB_PATH environment variable; if absent, defaults to
data/av_financials.duckdb relative to this file's project root.
"""

import os
from datetime import date
from pathlib import Path
from typing import Union

import duckdb
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = str(_ROOT / "data" / "av_financials.duckdb")


def _db_path() -> str:
    raw = os.environ.get("AV_DB_PATH", _DEFAULT_DB)
    p = Path(raw)
    return str(p if p.is_absolute() else _ROOT / p)


def _parse_date(d):
    """Accept a date string 'YYYY-MM-DD', a date object, or None."""
    if d is None or isinstance(d, date):
        return d
    return date.fromisoformat(d)


def _query(
    table: str,
    tickers: Union[str, list[str]],
    period: str,
    start_date,
    end_date,
    order_by: str = "ticker, fiscal_date_ending DESC",
) -> pd.DataFrame:
    if isinstance(tickers, str):
        tickers = [tickers]
    tickers = [t.upper() for t in tickers]

    start_date = _parse_date(start_date)
    end_date = _parse_date(end_date)

    placeholders = ", ".join(["?"] * len(tickers))
    params: list = list(tickers)
    where = f"WHERE ticker IN ({placeholders})"

    if period != "all":
        where += " AND period_type = ?"
        params.append(period)
    if start_date is not None:
        where += " AND fiscal_date_ending >= ?"
        params.append(start_date)
    if end_date is not None:
        where += " AND fiscal_date_ending <= ?"
        params.append(end_date)

    sql = f"SELECT * FROM {table} {where} ORDER BY {order_by}"
    conn = duckdb.connect(_db_path(), read_only=True)
    try:
        return conn.execute(sql, params).df()
    finally:
        conn.close()


def get_income(
    tickers: Union[str, list[str]],
    period: str = "annual",
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Return income statement rows as a DataFrame.

    Args:
        tickers:    Ticker symbol or list of ticker symbols.
        period:     'annual' (default), 'quarterly', or 'all'.
        start_date: Earliest fiscal_date_ending to include, e.g. '2022-01-01'.
        end_date:   Latest fiscal_date_ending to include, e.g. '2024-12-31'.

    Returns:
        DataFrame with columns: ticker, fiscal_date_ending, period_type,
        gross_profit, total_revenue, operating_income, ebitda, ebit,
        net_income, and all other income statement fields.
    """
    return _query("income_statements", tickers, period, start_date, end_date)


def get_balance(
    tickers: Union[str, list[str]],
    period: str = "annual",
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Return balance sheet rows as a DataFrame.

    Args:
        tickers:    Ticker symbol or list of ticker symbols.
        period:     'annual' (default), 'quarterly', or 'all'.
        start_date: Earliest fiscal_date_ending to include, e.g. '2022-01-01'.
        end_date:   Latest fiscal_date_ending to include, e.g. '2024-12-31'.

    Returns:
        DataFrame with columns: ticker, fiscal_date_ending, period_type,
        total_assets, total_liabilities, total_shareholder_equity, cash,
        debt columns, and all other balance sheet fields.
    """
    return _query("balance_sheets", tickers, period, start_date, end_date)


def get_cashflow(
    tickers: Union[str, list[str]],
    period: str = "annual",
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Return cash flow statement rows as a DataFrame.

    Args:
        tickers:    Ticker symbol or list of ticker symbols.
        period:     'annual' (default), 'quarterly', or 'all'.
        start_date: Earliest fiscal_date_ending to include, e.g. '2022-01-01'.
        end_date:   Latest fiscal_date_ending to include, e.g. '2024-12-31'.

    Returns:
        DataFrame with columns: ticker, fiscal_date_ending, period_type,
        operating_cashflow, capital_expenditures, cashflow_from_investment,
        cashflow_from_financing, and all other cash flow fields.
    """
    return _query("cash_flow_statements", tickers, period, start_date, end_date)


def get_overview(
    tickers: Union[str, list[str]],
    latest_only: bool = True,
) -> pd.DataFrame:
    """Return company overview rows as a DataFrame.

    Args:
        tickers:     Ticker symbol or list of ticker symbols.
        latest_only: If True (default), return only the most recent snapshot
                     per ticker. If False, return all historical snapshots.

    Returns:
        DataFrame with columns: ticker, name, sector, industry, market_cap,
        pe_ratio, beta, eps, dividend_yield, and all other overview fields.
    """
    if isinstance(tickers, str):
        tickers = [tickers]
    tickers = [t.upper() for t in tickers]

    placeholders = ", ".join(["?"] * len(tickers))
    where = f"WHERE ticker IN ({placeholders})"

    if latest_only:
        sql = f"""
            SELECT * FROM company_overview
            {where}
            QUALIFY fetch_date = MAX(fetch_date) OVER (PARTITION BY ticker)
            ORDER BY ticker
        """
    else:
        sql = f"""
            SELECT * FROM company_overview
            {where}
            ORDER BY ticker, fetch_date DESC
        """

    conn = duckdb.connect(_db_path(), read_only=True)
    try:
        return conn.execute(sql, tickers).df()
    finally:
        conn.close()
