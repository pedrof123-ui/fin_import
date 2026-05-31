"""
Cash flow statement extractor — thin wrapper around the shared statement_extractor core.
"""

import pandas as pd
from typing import Optional

from .filing import get_filing
from .statement_extractor import extract_statement

try:
    from xbrl_mappings import CASH_FLOW_MAPPING
    print(f"Loaded cash flow XBRL mapping ({sum(len(v) for v in CASH_FLOW_MAPPING.values())} concepts, {len(CASH_FLOW_MAPPING)} fields)")
except ImportError as e:
    print("ERROR: Could not import from xbrl_mappings package")
    raise SystemExit(f"Import Error: {e}")

_ALT_NAMES = [
    'CONDENSEDCONSOLIDATEDSTATEMENTSOFCASHFLOWS',
    'CONSOLIDATEDSTATEMENTSOFCASHFLOWS',
    'StatementsOfCashFlows',
    'CashFlowStatements',
]

_AGG_FIELDS = {
    'other_operating_activities',
    'other_investing_activities',
    'other_financing_activities',
}

_PRIOR_PERIOD_FIELDS = frozenset({'cash_beginning_of_period'})


async def extract_cash_flow(
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
        mapping=CASH_FLOW_MAPPING,
        get_stmt_fn=lambda xbrl: xbrl.statements.cashflow_statement(),
        alt_names=_ALT_NAMES,
        aggregation_fields=_AGG_FIELDS,
        statement_type='cashflow',
        label='CASH FLOW STATEMENT',
        year=year,
        quarter=quarter,
        use_ai_fallback=use_ai_fallback,
        prior_period_fields=_PRIOR_PERIOD_FIELDS,
        ff48_code=ff48_code,
    )
