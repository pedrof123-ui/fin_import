import duckdb
import pandas as pd
from pathlib import Path

PRICES_DB = Path("/home/pedro/projects/trade_systems/data/prices.duckdb")
FRED_DB = Path("/home/pedro/projects/trade_systems/data/fred.duckdb")

MIN_QUARTERLY_PERIODS = 8


def _fill_gross_profit(df: pd.DataFrame) -> pd.DataFrame:
    """Derive gross_profit from revenue - cost_of_revenue when the field is missing."""
    if "gross_profit" not in df.columns:
        df = df.copy()
        df["gross_profit"] = float("nan")
    missing = df["gross_profit"].isna()
    if missing.any() and "revenue" in df.columns and "cost_of_revenue" in df.columns:
        df.loc[missing, "gross_profit"] = df.loc[missing, "revenue"] - df.loc[missing, "cost_of_revenue"]
    return df


def load_quarterly_financials(db, ticker: str) -> dict[str, pd.DataFrame]:
    """Load quarterly financials sorted oldest→newest. Raises ValueError if insufficient."""
    stmts = {}
    for key, table in [
        ("income", "income_statements"),
        ("balance", "balance_sheets"),
        ("cashflow", "cash_flow_statements"),
    ]:
        stmts[key] = db.conn.execute(
            f"SELECT * FROM {table} WHERE ticker = ? AND period_type = 'Quarterly' ORDER BY period_end_date ASC",
            [ticker],
        ).df()

    n = len(stmts["income"])
    if n < MIN_QUARTERLY_PERIODS:
        raise ValueError(
            f"{ticker} has only {n} quarterly period(s). "
            f"Re-import as quarterly (Q) with at least {MIN_QUARTERLY_PERIODS} periods."
        )
    stmts["income"] = _fill_gross_profit(stmts["income"])
    return stmts


def load_annual_financials(db, ticker: str) -> dict[str, pd.DataFrame]:
    """Load last 5 annual periods sorted newest→oldest."""
    stmts = {}
    for key, table in [
        ("income", "income_statements"),
        ("balance", "balance_sheets"),
        ("cashflow", "cash_flow_statements"),
    ]:
        stmts[key] = db.conn.execute(
            f"SELECT * FROM {table} WHERE ticker = ? AND period_type = 'Annual' ORDER BY period_end_date DESC LIMIT 5",
            [ticker],
        ).df()
    stmts["income"] = _fill_gross_profit(stmts["income"])
    return stmts


def load_current_price(ticker: str) -> float | None:
    try:
        conn = duckdb.connect(str(PRICES_DB), read_only=True)
        row = conn.execute(
            "SELECT close FROM stock_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            [ticker],
        ).fetchone()
        conn.close()
        return float(row[0]) if row else None
    except Exception:
        return None


def load_risk_free_rate() -> float | None:
    """Returns DGS10 as decimal (e.g. 0.045 for 4.5%). Returns None if unavailable."""
    try:
        conn = duckdb.connect(str(FRED_DB), read_only=True)
        row = conn.execute(
            "SELECT value FROM economic_indicators WHERE series_id = 'DGS10' ORDER BY date DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return float(row[0]) / 100.0 if row else None
    except Exception:
        return None
