"""
Import logic: fetch SEC filings for a ticker and store them in DuckDB.
Supports both annual (10-K / FY) and quarterly (10-Q / Q) filings.
"""

import asyncio
import time
import pandas as pd
from fastapi import HTTPException
from edgar import Company, CompanyNotFoundError

from financial_statements_db import FinancialStatementsDB
from extractors.income_statement_extractor import extract_income_statement
from extractors.balance_sheet_extractor import extract_balance_sheet
from extractors.cash_flow_extractor import extract_cash_flow


def _fye_month(company) -> int:
    """Return the fiscal year end month (1–12) from the Company object, defaulting to 12."""
    fye = getattr(company, 'fiscal_year_end', None)
    if isinstance(fye, str) and fye:
        try:
            # Common formats: "0930" (MMDD) or "09-30"
            digits = fye.replace('-', '')
            return int(digits[:2])
        except (ValueError, IndexError):
            pass
    return 12


def _fiscal_quarter(period_month: int, fye_month: int, period_day: int = 15) -> int:
    """Return fiscal quarter (1–3) for a 10-Q given the period end month and FYE month.

    Some companies end quarters on the 1st of the following month (e.g. AAPL Q2 FY2023
    ends 2023-04-01). Treat period_day <= 7 as belonging to the prior month.
    """
    if period_day <= 7:
        period_month = 12 if period_month == 1 else period_month - 1
    return ((period_month - fye_month - 1) % 12) // 3 + 1


async def import_ticker(
    ticker: str,
    periods: int,
    period_type: str,
    db: FinancialStatementsDB,
    force: bool = False,
) -> dict:
    form = "10-K" if period_type == "FY" else "10-Q"

    try:
        company = await asyncio.to_thread(lambda: Company(ticker))
    except CompanyNotFoundError:
        raise HTTPException(status_code=404, detail=f"No company found for ticker {ticker}")
    from xbrl_mappings.sic_lookup import get_ff48
    ff48_code = get_ff48(getattr(company, 'sic', None))

    if periods == 1:
        latest = await asyncio.to_thread(lambda: company.latest(form))
        if latest is None:
            raise HTTPException(status_code=404, detail=f"No {form} filings found for {ticker}")
        filings_list = [latest]
    else:
        filings_obj = await asyncio.to_thread(lambda: company.get_filings(form=form))
        if filings_obj.empty:
            raise HTTPException(status_code=404, detail=f"No {form} filings found for {ticker}")
        filings_list = list(filings_obj)[:periods]

    fye = _fye_month(company)
    processed = 0
    failed = 0
    errors: list[str] = []

    for filing in filings_list:
        try:
            period_date = pd.to_datetime(getattr(filing, 'report_date', None) or filing.period_of_report)
            quarter = _fiscal_quarter(period_date.month, fye, period_date.day) if form == "10-Q" else None
            # Use effective month (day-adjusted) for fiscal year determination so that
            # period-end dates landing on day 1 of a month (e.g. AAPL Apr 1 = Q2 end)
            # don't cross the FYE boundary incorrectly.
            eff_month = period_date.month
            if period_date.day <= 7:
                eff_month = eff_month - 1 if eff_month > 1 else 12
            if form == "10-Q" and eff_month > fye:
                year = period_date.year + 1
            else:
                year = period_date.year
            period_end = period_date.date()
        except Exception:
            failed += 1
            continue

        if not force and db.filing_exists(ticker, period_end):
            continue

        t0 = time.monotonic()
        n_ok, errs = await _extract_and_insert(filing, ticker, year, form, db, quarter=quarter, ff48_code=ff48_code)
        elapsed = time.monotonic() - t0
        errors.extend(errs)

        db.log_extraction(
            ticker=ticker,
            filing_type=form,
            fiscal_year=year,
            fiscal_quarter=quarter,
            statements_extracted='income,balance,cashflow' if n_ok == 3 else f"{n_ok}/3 ok",
            overall_coverage_pct=None,
            success=n_ok > 0,
            error_message='; '.join(errs) if errs else None,
            execution_time_seconds=elapsed,
        )

        if n_ok > 0:
            processed += 1
        else:
            failed += 1

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
    ff48_code: str | None = None,
) -> tuple[int, list[str]]:
    n_ok = 0
    errors: list[str] = []

    for name, extractor, inserter in [
        ("income", extract_income_statement, db.insert_income_statement),
        ("balance", extract_balance_sheet, db.insert_balance_sheet),
        ("cashflow", extract_cash_flow, db.insert_cash_flow),
    ]:
        try:
            df = await extractor(filing, ticker, form, year, quarter=quarter, use_ai_fallback=True, ff48_code=ff48_code)
            inserter(df)
            n_ok += 1
        except Exception as e:
            errors.append(f"{name}: {e}")

    return n_ok, errors
