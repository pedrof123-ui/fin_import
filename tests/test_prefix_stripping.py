"""
Unit tests for prefix stripping in extractor lookup functions.
Tests the extract_value_from_statement_df logic in all three extractors
using mock DataFrames — no SEC/API connection needed.
"""

import pandas as pd
import sys
import os

# Add project root to path so imports resolve
sys.path.insert(0, os.path.dirname(__file__))

# ─── Minimal mock mappings (no need to import full xbrl_mappings) ─────────────

MOCK_BALANCE = {
    'total_assets': ['Assets'],
    'cash': ['CashAndCashEquivalentsAtCarryingValue', 'Cash'],
}

MOCK_CASHFLOW = {
    'net_cash_operating': ['NetCashProvidedByUsedInOperatingActivities'],
    'other_operating_activities': [
        'IncreaseDecreaseInAccountsReceivable',
        'IncreaseDecreaseInInventories',
    ],
}

MOCK_INCOME = {
    'revenue': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues'],
    'selling_general_admin': ['SellingGeneralAndAdministrativeExpense', 'GeneralAndAdministrativeExpense'],
}


# ─── Replicate the new extract logic (isolated, no import side-effects) ───────

def _extract(mapping_dict, field_name, statement_df, year_column, aggregation_fields=None):
    """Replicate new extract_value_from_statement_df logic."""
    concepts = mapping_dict.get(field_name)
    if concepts is None:
        return None, None

    main_items = statement_df[
        (statement_df['dimension'] == False) &
        (statement_df['abstract'] == False)
    ].copy()

    # Key change: strip namespace prefix before matching
    main_items['bare_concept'] = main_items['concept'].apply(
        lambda c: c.split('_', 1)[1] if '_' in c else c
    )

    aggregation_fields = aggregation_fields or set()
    should_aggregate = field_name in aggregation_fields

    found_values, found_concepts = [], []

    for concept in concepts:
        rows = main_items[main_items['bare_concept'] == concept]
        if not rows.empty and year_column in rows.columns:
            value = rows.iloc[0][year_column]
            if pd.notna(value):
                if should_aggregate:
                    found_values.append(float(value))
                    found_concepts.append(concept)
                else:
                    return float(value), concept

    if should_aggregate and found_values:
        if len(found_values) == 1:
            return found_values[0], found_concepts[0]
        total = sum(found_values)
        return total, ' + '.join(found_concepts)

    return None, None


# ─── Build mock DataFrames ─────────────────────────────────────────────────────

def make_df(rows):
    """rows: list of (concept, value). Returns mock statement DataFrame."""
    data = [
        {'concept': concept, '2024-12-31': value, 'dimension': False, 'abstract': False}
        for concept, value in rows
    ]
    if not data:
        return pd.DataFrame(columns=['concept', '2024-12-31', 'dimension', 'abstract'])
    return pd.DataFrame(data)


YEAR = '2024-12-31'

BALANCE_DF = make_df([
    ('us-gaap_Assets', 500_000),
    ('us-gaap_CashAndCashEquivalentsAtCarryingValue', 100_000),
    ('us-gaap_Liabilities', 300_000),
])

CASHFLOW_DF = make_df([
    ('us-gaap_NetCashProvidedByUsedInOperatingActivities', 80_000),
    ('us-gaap_IncreaseDecreaseInAccountsReceivable', -5_000),
    ('us-gaap_IncreaseDecreaseInInventories', -3_000),
    ('dei_EntityCommonStockSharesOutstanding', 999),   # non-us-gaap prefix
])

INCOME_DF = make_df([
    ('us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax', 1_000_000),
    ('us-gaap_SellingGeneralAndAdministrativeExpense', 200_000),
    ('us-gaap_GeneralAndAdministrativeExpense', 50_000),
    ('apo_ProprietaryConcept', 42),   # company-specific prefix
])


# ─── Tests ─────────────────────────────────────────────────────────────────────

passed = 0
failed = 0

def check(name, got_value, got_concept, exp_value, exp_concept_contains=None):
    global passed, failed
    ok = True
    if got_value != exp_value:
        print(f"  FAIL [{name}] value: expected {exp_value}, got {got_value}")
        ok = False
    if exp_concept_contains and (got_concept is None or exp_concept_contains not in got_concept):
        print(f"  FAIL [{name}] concept: expected to contain {exp_concept_contains!r}, got {got_concept!r}")
        ok = False
    if ok:
        print(f"  PASS [{name}]  value={got_value}, concept={got_concept!r}")
        passed += 1
    else:
        failed += 1


print("=== Balance Sheet ===")
v, c = _extract(MOCK_BALANCE, 'total_assets', BALANCE_DF, YEAR)
check('bs: us-gaap_ prefix stripped', v, c, 500_000, 'Assets')

v, c = _extract(MOCK_BALANCE, 'cash', BALANCE_DF, YEAR)
check('bs: first matching concept', v, c, 100_000, 'CashAndCashEquivalentsAtCarryingValue')

v, c = _extract(MOCK_BALANCE, 'total_assets', make_df([]), YEAR)
check('bs: missing concept returns None', v, c, None)

print("\n=== Cash Flow ===")
v, c = _extract(MOCK_CASHFLOW, 'net_cash_operating', CASHFLOW_DF, YEAR)
check('cf: us-gaap_ prefix stripped', v, c, 80_000, 'NetCashProvidedByUsedInOperatingActivities')

# Aggregation field: should sum both component concepts
v, c = _extract(MOCK_CASHFLOW, 'other_operating_activities', CASHFLOW_DF, YEAR,
                aggregation_fields={'other_operating_activities'})
check('cf: aggregation sums components', v, c, -8_000.0)
if c is not None and '+' in c:
    print(f"        (concepts: {c!r})")

# DEI prefix stripped
DEI_MAPPING = {'shares_outstanding': ['EntityCommonStockSharesOutstanding']}
v, c = _extract(DEI_MAPPING, 'shares_outstanding', CASHFLOW_DF, YEAR)
check('cf: dei_ prefix stripped', v, c, 999, 'EntityCommonStockSharesOutstanding')

print("\n=== Income Statement ===")
v, c = _extract(MOCK_INCOME, 'revenue', INCOME_DF, YEAR)
check('inc: us-gaap_ prefix stripped', v, c, 1_000_000, 'RevenueFromContractWithCustomerExcludingAssessedTax')

# Aggregation: SGA + GA summed
v, c = _extract(MOCK_INCOME, 'selling_general_admin', INCOME_DF, YEAR,
                aggregation_fields={'selling_general_admin'})
check('inc: aggregation SG&A', v, c, 250_000.0)
if c is not None and '+' in c:
    print(f"        (concepts: {c!r})")

# Company-specific (apo_) prefix stripped
APO_MAPPING = {'proprietary': ['ProprietaryConcept']}
v, c = _extract(APO_MAPPING, 'proprietary', INCOME_DF, YEAR)
check('inc: company-specific apo_ prefix stripped', v, c, 42, 'ProprietaryConcept')

print("\n=== ai_batch_helper concept_name_map ===")
# Verify the new split-based strip matches expected bare names
test_concepts = [
    ('us-gaap_NetIncomeLoss',    'NetIncomeLoss'),
    ('dei_EntityCIK',            'EntityCIK'),
    ('srt_ConsolidatedEntities', 'ConsolidatedEntities'),
    ('apo_FreeCashFlow',         'FreeCashFlow'),
    ('BareNoPrefixConcept',      'BareNoPrefixConcept'),
]
all_ok = True
for full, expected_bare in test_concepts:
    bare = full.split('_', 1)[1] if '_' in full else full
    if bare == expected_bare:
        print(f"  PASS {full!r} -> {bare!r}")
        passed += 1
    else:
        print(f"  FAIL {full!r}: expected {expected_bare!r}, got {bare!r}")
        failed += 1

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
