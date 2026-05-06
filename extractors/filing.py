"""
Shared filing retrieval helpers used by all statement extractors.
"""

import os
from typing import Optional, Literal
from dotenv import load_dotenv
import pandas as pd
from edgar import Company, set_identity

load_dotenv()

sec_identity = os.getenv("SEC_ID")
if not sec_identity:
    raise ValueError("SEC_ID not found in .env file")

set_identity(sec_identity)


def _fye_month(company) -> int:
    """Return fiscal year end month (1–12), defaulting to December."""
    fye = getattr(company, 'fiscal_year_end', None)
    if isinstance(fye, str) and fye:
        try:
            return int(fye.replace('-', '')[:2])
        except (ValueError, IndexError):
            pass
    return 12


def _fiscal_quarter(period_month: int, fye_month: int) -> int:
    return ((period_month - fye_month - 1) % 12) // 3 + 1


def parse_date(date_str):
    """Parse a date string to datetime object."""
    if isinstance(date_str, str):
        try:
            return pd.to_datetime(date_str)
        except Exception:
            return None
    return date_str


def get_filing(
    ticker: str,
    filing_type: Literal["10-K", "10-Q"],
    year: Optional[int] = None,
    quarter: Optional[int] = None
):
    """
    Retrieve a specific SEC filing for a company.

    Args:
        ticker: Company ticker symbol
        filing_type: Either "10-K" (annual) or "10-Q" (quarterly)
        year: Fiscal year (if None, gets the most recent)
        quarter: Fiscal quarter (1-4, only for 10-Q)

    Returns:
        Filing object from edgartools
    """
    if filing_type == "10-Q" and quarter is not None:
        if not 1 <= quarter <= 4:
            raise ValueError("Quarter must be between 1 and 4")

    company = Company(ticker)
    print(f"Retrieved company: {company.name} ({ticker})")
    fye = _fye_month(company)

    filings = company.get_filings(form=filing_type)

    if filings.empty:
        raise FileNotFoundError(f"No {filing_type} filings found for {ticker}")

    if year is not None:
        filings_filtered = []

        for f in filings:
            filing_date = parse_date(f.filing_date) if hasattr(f, 'filing_date') else None
            period_date = parse_date(f.period_of_report) if hasattr(f, 'period_of_report') else None

            filing_year_match = filing_date and filing_date.year == year
            period_year_match = period_date and period_date.year == year

            if filing_year_match or period_year_match:
                f._parsed_filing_date = filing_date
                f._parsed_period_date = period_date
                filings_filtered.append(f)

        if not filings_filtered:
            raise FileNotFoundError(f"No {filing_type} filings found for {ticker} in year {year}")

        if filing_type == "10-Q" and quarter is not None:
            quarter_filtered = []

            for f in filings_filtered:
                period_date = f._parsed_period_date
                if period_date:
                    file_quarter = _fiscal_quarter(period_date.month, fye)
                    if file_quarter == quarter:
                        quarter_filtered.append(f)

            if not quarter_filtered:
                raise FileNotFoundError(f"No {filing_type} filings found for {ticker} in Q{quarter} {year}")

            filings_filtered = quarter_filtered

        filing = filings_filtered[0]
    else:
        filing = filings[0]

    filing_date = filing.filing_date if hasattr(filing, 'filing_date') else 'Unknown'
    period = filing.period_of_report if hasattr(filing, 'period_of_report') else 'Unknown'

    print(f"Retrieved {filing_type} filing")
    print(f"  Filing Date: {filing_date}")
    print(f"  Period of Report: {period}")

    return filing
