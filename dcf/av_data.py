import os
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from historic_fundamentals.pe import LAG_ANNUAL, LAG_QUARTERLY

ROOT = Path(__file__).resolve().parent.parent
AV_DB = Path(os.environ.get("AV_FINANCIALS_DB_PATH", str(ROOT / "data" / "av_financials.duckdb")))
MIN_QUARTERLY_PERIODS = 8

_INCOME_RENAME = {
    "fiscal_date_ending": "period_end_date",
    "total_revenue": "revenue",
    "selling_general_and_administrative": "selling_general_admin",
    "research_and_development": "research_development",
    "income_before_tax": "pretax_income",
    "depreciation_and_amortization": "depreciation_amortization",
}

_BALANCE_RENAME = {
    "fiscal_date_ending": "period_end_date",
    "cash_and_cash_equivalents": "cash_and_equivalents",
    "current_net_receivables": "accounts_receivable",
    "current_accounts_payable": "accounts_payable",
    "current_long_term_debt": "current_portion_long_term_debt",
    # long_term_debt already present in AV as-is; long_term_debt_noncurrent is not renamed
    # to avoid duplicate column names which break pandas Series arithmetic
}

_CASHFLOW_RENAME = {
    "fiscal_date_ending": "period_end_date",
    "depreciation_depletion_and_amortization": "depreciation_amortization",
}


def _open() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(AV_DB), read_only=True)


def _as_of_clause(as_of: date | None, period_type: str) -> tuple[str, list]:
    """SQL fragment restricting rows to those publicly available on `as_of`.

    Uses the repo's single reporting-lag convention (historic_fundamentals.pe) rather than a
    second one: a fiscal period is treated as knowable only once its lag has elapsed. Returns
    an empty fragment when as_of is None, so the live path is byte-identical to before.
    """
    if as_of is None:
        return "", []
    lag = LAG_ANNUAL if period_type == "annual" else LAG_QUARTERLY
    return " AND fiscal_date_ending <= ?", [as_of - lag]


def _check(ticker: str, conn: duckdb.DuckDBPyConnection) -> None:
    row = conn.execute(
        "SELECT COUNT(*) FROM income_statements WHERE ticker = ?", [ticker]
    ).fetchone()
    if not row or row[0] == 0:
        raise ValueError(
            f"No AV data for {ticker} — import via av_financials_db first"
        )


def _add_time_cols(df: pd.DataFrame, is_quarterly: bool) -> pd.DataFrame:
    """Derive fiscal_year (and fiscal_quarter) from period_end_date."""
    if "period_end_date" not in df.columns:
        return df
    df = df.copy()
    dates = pd.to_datetime(df["period_end_date"], errors="coerce")
    df["fiscal_year"] = dates.dt.year
    if is_quarterly:
        df["fiscal_quarter"] = dates.dt.quarter
    return df


def _inject_shares(inc: pd.DataFrame, bs: pd.DataFrame) -> pd.DataFrame:
    """Add diluted_shares and diluted_eps to income df using balance sheet basic shares."""
    inc = inc.copy()
    if "common_stock_shares_outstanding" in bs.columns and "period_end_date" in bs.columns:
        shares_map = (
            bs.dropna(subset=["period_end_date"])
            .set_index("period_end_date")["common_stock_shares_outstanding"]
            .to_dict()
        )
        inc["diluted_shares"] = (
            inc["period_end_date"].astype(str).map(shares_map).astype(float)
        )
    else:
        inc["diluted_shares"] = np.nan

    if "net_income" in inc.columns:
        shares = inc["diluted_shares"].replace(0, np.nan)
        inc["diluted_eps"] = inc["net_income"] / shares
    return inc


def _fill_gross_profit(inc: pd.DataFrame) -> pd.DataFrame:
    if "gross_profit" not in inc.columns or inc["gross_profit"].isna().all():
        if "revenue" in inc.columns and "cost_of_revenue" in inc.columns:
            inc = inc.copy()
            inc["gross_profit"] = inc["revenue"] - inc["cost_of_revenue"].fillna(0)
    return inc


def load_av_annual_financials(ticker: str, as_of: date | None = None) -> dict[str, pd.DataFrame]:
    """Annual statements newest-first. `as_of` restricts to periods public by that date."""
    where, params = _as_of_clause(as_of, "annual")
    conn = _open()
    try:
        _check(ticker, conn)
        inc = conn.execute(
            f"""SELECT * FROM income_statements
               WHERE ticker = ? AND period_type = 'annual'{where}
               ORDER BY fiscal_date_ending DESC""",
            [ticker, *params],
        ).df()
        bs = conn.execute(
            f"""SELECT * FROM balance_sheets
               WHERE ticker = ? AND period_type = 'annual'{where}
               ORDER BY fiscal_date_ending DESC""",
            [ticker, *params],
        ).df()
        cf = conn.execute(
            f"""SELECT * FROM cash_flow_statements
               WHERE ticker = ? AND period_type = 'annual'{where}
               ORDER BY fiscal_date_ending DESC""",
            [ticker, *params],
        ).df()
    finally:
        conn.close()

    inc = inc.rename(columns=_INCOME_RENAME)
    bs  = bs.rename(columns=_BALANCE_RENAME)
    cf  = cf.rename(columns=_CASHFLOW_RENAME)

    inc = _add_time_cols(inc, is_quarterly=False)
    bs  = _add_time_cols(bs,  is_quarterly=False)
    cf  = _add_time_cols(cf,  is_quarterly=False)

    inc = _inject_shares(inc, bs)
    inc = _fill_gross_profit(inc)

    return {"income": inc, "balance": bs, "cashflow": cf}


def load_av_quarterly_financials(ticker: str, as_of: date | None = None) -> dict[str, pd.DataFrame]:
    """Quarterly statements oldest-first. `as_of` restricts to periods public by that date."""
    where, params = _as_of_clause(as_of, "quarterly")
    conn = _open()
    try:
        _check(ticker, conn)
        inc = conn.execute(
            f"""SELECT * FROM income_statements
               WHERE ticker = ? AND period_type = 'quarterly'{where}
               ORDER BY fiscal_date_ending ASC""",
            [ticker, *params],
        ).df()
        bs = conn.execute(
            f"""SELECT * FROM balance_sheets
               WHERE ticker = ? AND period_type = 'quarterly'{where}
               ORDER BY fiscal_date_ending ASC""",
            [ticker, *params],
        ).df()
        cf = conn.execute(
            f"""SELECT * FROM cash_flow_statements
               WHERE ticker = ? AND period_type = 'quarterly'{where}
               ORDER BY fiscal_date_ending ASC""",
            [ticker, *params],
        ).df()
    finally:
        conn.close()

    inc = inc.rename(columns=_INCOME_RENAME)
    bs  = bs.rename(columns=_BALANCE_RENAME)
    cf  = cf.rename(columns=_CASHFLOW_RENAME)

    inc = _add_time_cols(inc, is_quarterly=True)
    bs  = _add_time_cols(bs,  is_quarterly=True)
    cf  = _add_time_cols(cf,  is_quarterly=True)

    inc = _inject_shares(inc, bs)
    inc = _fill_gross_profit(inc)

    n = len(inc)
    if n < MIN_QUARTERLY_PERIODS:
        raise ValueError(
            f"{ticker} has only {n} quarterly period(s) in AV data. "
            f"Import at least {MIN_QUARTERLY_PERIODS} quarters via av_financials_db."
        )

    return {"income": inc, "balance": bs, "cashflow": cf}
