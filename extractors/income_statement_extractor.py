"""
Income statement extractor — thin wrapper around the shared statement_extractor core.
"""

import pandas as pd
from typing import Optional

from .filing import get_filing, parse_date
from .statement_extractor import extract_statement

try:
    from xbrl_mappings import INCOME_STATEMENT_MAPPING
    print(f"Loaded comprehensive XBRL mapping ({sum(len(v) for v in INCOME_STATEMENT_MAPPING.values())} concepts, {len(INCOME_STATEMENT_MAPPING)} fields)")
except ImportError as e:
    print("ERROR: Could not import from xbrl_mappings package")
    raise SystemExit(f"Import Error: {e}")

_ALT_NAMES = [
    'CONDENSEDCONSOLIDATEDSTATEMENTSOFOPERATIONSUnaudited',
    'CONSOLIDATEDSTATEMENTSOFOPERATIONS',
    'CONSOLIDATEDSTATEMENTSOFEARNINGS',
    'StatementsOfIncome',
    'StatementsOfOperations',
]

_AGG_FIELDS = {
    'selling_general_admin',
    'depreciation_amortization',
    'other_operating_expenses',
    'interest_expense',
    'interest_income',
}

# For total-line fields, take the maximum across all matching concepts.
# When a company reports both a specific concept (e.g. RFCWCEA) and a broader
# aggregate (e.g. Revenues), the larger value is the correct total figure.
_MAX_FIELDS = {
    'revenue',
    'net_income',
    'pretax_income',
    'operating_income',
}


async def extract_income_statement(
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
        mapping=INCOME_STATEMENT_MAPPING,
        get_stmt_fn=lambda xbrl: xbrl.statements.income_statement(),
        alt_names=_ALT_NAMES,
        aggregation_fields=_AGG_FIELDS,
        max_fields=_MAX_FIELDS,
        statement_type='income',
        label='INCOME STATEMENT',
        year=year,
        quarter=quarter,
        use_ai_fallback=use_ai_fallback,
        ff48_code=ff48_code,
    )


def format_for_display(df: pd.DataFrame) -> pd.DataFrame:
    def format_value(row):
        val = row['Value']
        field = row['Field']
        if pd.isna(val):
            return "Not Found"
        if 'eps' in field.lower():
            return f"${val:,.2f}"
        elif 'shares' in field.lower():
            return f"{val:,.0f}"
        else:
            return f"${val:,.0f}"

    formatted_df = df.copy()
    formatted_df['Formatted_Value'] = formatted_df.apply(format_value, axis=1)
    display_df = formatted_df[['Status', 'Field', 'Formatted_Value', 'Concept']]
    return display_df.rename(columns={'Formatted_Value': 'Value'})


def validate_income_statement(df: pd.DataFrame) -> dict:
    data = dict(zip(df['Field'], df['Value']))
    validations = {}

    if all(k in data and pd.notna(data[k]) for k in ['revenue', 'cost_of_revenue', 'gross_profit']):
        calculated_gp = data['revenue'] - data['cost_of_revenue']
        reported_gp = data['gross_profit']
        variance = abs(calculated_gp - reported_gp) / reported_gp if reported_gp != 0 else 0
        validations['gross_profit_calc'] = {
            'passed': variance < 0.02,
            'variance': f"{variance:.1%}",
            'calculated': f"${calculated_gp:,.0f}",
            'reported': f"${reported_gp:,.0f}",
        }

    if all(k in data and pd.notna(data[k]) for k in ['gross_profit', 'operating_income']):
        validations['operating_income_logical'] = {
            'passed': data['operating_income'] <= data['gross_profit'],
            'operating_income': f"${data['operating_income']:,.0f}",
            'gross_profit': f"${data['gross_profit']:,.0f}",
        }

    if all(k in data and pd.notna(data[k]) for k in ['pretax_income', 'net_income']):
        validations['tax_logical'] = {
            'passed': data['net_income'] <= data['pretax_income'],
            'net_income': f"${data['net_income']:,.0f}",
            'pretax_income': f"${data['pretax_income']:,.0f}",
        }

    return validations


def print_validation_results(validations: dict):
    if not validations:
        print("\nNo validations could be performed (missing required fields)")
        return

    print("\n" + "="*80)
    print("VALIDATION CHECKS")
    print("="*80)

    all_passed = True
    for check_name, result in validations.items():
        passed = result.get('passed', False)
        if not passed:
            all_passed = False
        print(f"\n{'PASS' if passed else 'FAIL'} - {check_name.replace('_', ' ').title()}")
        for key, value in result.items():
            if key != 'passed':
                print(f"  {key}: {value}")

    print("\nAll validation checks passed!" if all_passed else "\nSome validation checks failed. Review the data carefully.")
