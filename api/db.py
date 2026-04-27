"""
Query helpers for the financial statements database.
"""

import json
from financial_statements_db import FinancialStatementsDB

# Columns that are metadata, not financial data
_METADATA_COLS = {
    "filing_date",
    "extraction_date",
    "fields_extracted",
    "total_fields",
    "coverage_pct",
    "filing_type",
    "fiscal_quarter",
}

_TABLE_MAP = {
    "income": "income_statements",
    "balance": "balance_sheets",
    "cashflow": "cash_flow_statements",
}


def list_tickers(db: FinancialStatementsDB) -> list[str]:
    return db.query_companies()["ticker"].tolist()


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

    df = db.conn.execute(
        f"""
        SELECT * FROM {table}
        WHERE ticker = ? AND period_type = ?
        ORDER BY period_end_date DESC
        LIMIT ?
        """,
        [ticker, pt, periods],
    ).df()

    if df.empty:
        return None

    # Drop metadata, keep ticker + period info + financial columns
    df = df.drop(columns=[c for c in _METADATA_COLS if c in df.columns])

    # to_json handles NaN → null and date serialization; parse back to get Python objects
    return json.loads(df.to_json(orient="records", date_format="iso"))
