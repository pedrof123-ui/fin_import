"""
Query helpers for the financial statements database.
"""

import json
import pandas as pd
from financial_statements_db import FinancialStatementsDB

# Columns that are metadata, not financial data
_METADATA_COLS = {
    "filing_date",
    "extraction_date",
    "fields_extracted",
    "total_fields",
    "coverage_pct",
    "filing_type",
    "ytd_cashflow",
}

_NON_FINANCIAL = {"ticker", "period_end_date", "fiscal_year", "fiscal_quarter", "period_type", "ytd_cashflow"}

_TABLE_MAP = {
    "income": "income_statements",
    "balance": "balance_sheets",
    "cashflow": "cash_flow_statements",
}


def list_tickers(db: FinancialStatementsDB) -> list[str]:
    return db.query_companies()["ticker"].tolist()


def _decumulate_cashflows(df: pd.DataFrame) -> pd.DataFrame:
    """Convert YTD Q2/Q3 cash flow values to standalone quarterly values.

    10-Q filings report cash flows on a YTD basis for Q2 (6 months) and Q3
    (9 months). Standalone quarter = current YTD - previous quarter YTD.
    Q1 is already standalone (3 months = YTD Q1).
    """
    if df.empty or "fiscal_quarter" not in df.columns:
        return df

    financial_cols = [c for c in df.columns if c not in _NON_FINANCIAL]
    df = df.sort_values(["fiscal_year", "fiscal_quarter"]).reset_index(drop=True)
    original = df[financial_cols].copy()

    for i, row in df.iterrows():
        if not row.get("ytd_cashflow", False):
            continue
        q = row.get("fiscal_quarter")
        if q not in (2, 3):
            continue
        prev = df[
            (df["fiscal_year"] == row["fiscal_year"]) & (df["fiscal_quarter"] == q - 1)
        ]
        if prev.empty:
            continue
        prev_idx = prev.index[0]
        for col in financial_cols:
            curr_val = original.at[i, col]
            prev_val = original.at[prev_idx, col]
            if pd.notna(curr_val) and pd.notna(prev_val):
                df.at[i, col] = curr_val - prev_val

    return df


def get_statements(
    db: FinancialStatementsDB,
    ticker: str,
    stmt_type: str,
    period_type: str,
    periods: int,
) -> list[dict] | None:
    table = _TABLE_MAP.get(stmt_type)
    if not table:
        return None

    pt = "Annual" if period_type == "FY" else "Quarterly"

    # For quarterly cash flows fetch all rows — de-cumulation needs prior quarters
    # that may fall outside the requested window. Limit is applied after.
    limit_sql = "" if (stmt_type == "cashflow" and pt == "Quarterly") else "LIMIT ?"
    params = [ticker, pt] if limit_sql == "" else [ticker, pt, periods]

    df = db.conn.execute(
        f"""
        SELECT * FROM {table}
        WHERE ticker = ? AND period_type = ?
        ORDER BY period_end_date DESC
        {limit_sql}
        """,
        params,
    ).df()

    if df.empty:
        return None

    df = df.drop(columns=[c for c in _METADATA_COLS if c in df.columns])

    if stmt_type == "cashflow" and pt == "Quarterly":
        df = _decumulate_cashflows(df)
        df = df.sort_values("period_end_date", ascending=False).head(periods).reset_index(drop=True)

    return json.loads(df.to_json(orient="records", date_format="iso"))
