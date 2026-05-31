"""
Balance sheet extractor — thin wrapper around the shared statement_extractor core.
"""

import pandas as pd
from typing import Optional

from .filing import get_filing
from .statement_extractor import extract_statement

try:
    from xbrl_mappings import BALANCE_SHEET_MAPPING
    print(f"Loaded balance sheet XBRL mapping ({sum(len(v) for v in BALANCE_SHEET_MAPPING.values())} concepts, {len(BALANCE_SHEET_MAPPING)} fields)")
except ImportError as e:
    print("ERROR: Could not import from xbrl_mappings package")
    raise SystemExit(f"Import Error: {e}")

_ALT_NAMES = [
    'CONDENSEDCONSOLIDATEDBALANCESHEETS',
    'CONSOLIDATEDBALANCESHEETS',
    'CONSOLIDATEDSTATEMENTSOFFINANCIALPOSITION',
    'StatementsOfFinancialPosition',
    'BalanceSheets',
]


async def extract_balance_sheet(
    filing,
    ticker: str,
    filing_type: str,
    year: Optional[int] = None,
    quarter: Optional[int] = None,
    use_ai_fallback: bool = True,
    ff48_code: str | None = None,
) -> pd.DataFrame:
    return await extract_statement(
        filing=filing,
        ticker=ticker,
        filing_type=filing_type,
        mapping=BALANCE_SHEET_MAPPING,
        get_stmt_fn=lambda xbrl: xbrl.statements.balance_sheet(),
        alt_names=_ALT_NAMES,
        aggregation_fields=set(),
        statement_type='balance',
        label='BALANCE SHEET',
        year=year,
        quarter=quarter,
        use_ai_fallback=use_ai_fallback,
        ff48_code=ff48_code,
    )
