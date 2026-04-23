"""
Import logic: fetch SEC filings for a ticker and store them in DuckDB.
Supports both annual (10-K / FY) and quarterly (10-Q / Q) filings.
"""

import asyncio
import pandas as pd
from fastapi import HTTPException
from edgar import Company

from financial_statements_db import FinancialStatementsDB
from extractors.income_statement_extractor import extract_income_statement
from extractors.balance_sheet_extractor import extract_balance_sheet
from extractors.cash_flow_extractor import extract_cash_flow


async def import_ticker(
    ticker: str,
    periods: int,
    period_type: str,
    db: FinancialStatementsDB,
) -> dict:
    form = "10-K" if period_type == "FY" else "10-Q"

    company = await asyncio.to_thread(lambda: Company(ticker))
    filings_obj = await asyncio.to_thread(lambda: company.get_filings(form=form))

    if filings_obj.empty:
        raise HTTPException(status_code=404, detail=f"No {form} filings found for {ticker}")

    filings_list = list(filings_obj)[:periods]

    processed = 0
    failed = 0
    errors: list[str] = []

    for filing in filings_list:
        try:
            period_date = pd.to_datetime(filing.period_of_report)
            year = period_date.year
            quarter = ((period_date.month - 1) // 3 + 1) if form == "10-Q" else None
            period_end = period_date.date()
        except Exception:
            failed += 1
            continue

        if db.filing_exists(ticker, period_end):
            continue

        n_ok, errs = await _extract_and_insert(filing, ticker, year, form, db, quarter=quarter)
        errors.extend(errs)

        if n_ok > 0:
            processed += 1
        else:
            failed += 1

        await asyncio.sleep(1.0)

    return {
        "status": "ok",
        "ticker": ticker,
        "filings_processed": processed,
        "filings_failed": failed,
        "errors": errors[:10],
    }


async def _extract_and_insert(
    filing,
    ticker: str,
    year: int,
    form: str,
    db: FinancialStatementsDB,
    quarter: int | None = None,
) -> tuple[int, list[str]]:
    n_ok = 0
    errors: list[str] = []

    for name, extractor, inserter in [
        ("income", extract_income_statement, db.insert_income_statement),
        ("balance", extract_balance_sheet, db.insert_balance_sheet),
        ("cashflow", extract_cash_flow, db.insert_cash_flow),
    ]:
        try:
            df = await extractor(filing, ticker, form, year, quarter=quarter, use_ai_fallback=False)
            inserter(df)
            n_ok += 1
        except Exception as e:
            errors.append(f"{name}: {e}")

    return n_ok, errors
