"""
XBRL Mapping Package
Provides concept mappings for all financial statements
"""

from .income_statement_xbrl_mapping import INCOME_STATEMENT_MAPPING
from .balance_sheet_xbrl_mapping import BALANCE_SHEET_MAPPING
from .cash_flow_xbrl_mapping import CASH_FLOW_MAPPING

__all__ = [
    'INCOME_STATEMENT_MAPPING',
    'BALANCE_SHEET_MAPPING',
    'CASH_FLOW_MAPPING',
]

__version__ = '1.0.0'
