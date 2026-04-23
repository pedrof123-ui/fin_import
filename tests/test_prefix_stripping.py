"""
Unit tests for XBRL prefix stripping in extractor lookup logic.
No network or SEC connection needed — uses mock DataFrames.
"""

import pandas as pd
import pytest


# Minimal mock mappings
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


def _extract(mapping_dict, field_name, statement_df, year_column, aggregation_fields=None):
    """Replicate extract_value_from_statement_df logic in isolation."""
    concepts = mapping_dict.get(field_name)
    if concepts is None:
        return None, None

    main_items = statement_df[
        (statement_df['dimension'] == False) &
        (statement_df['abstract'] == False)
    ].copy()
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
        return sum(found_values), ' + '.join(found_concepts)

    return None, None


def make_df(rows):
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
    ('dei_EntityCommonStockSharesOutstanding', 999),
])
INCOME_DF = make_df([
    ('us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax', 1_000_000),
    ('us-gaap_SellingGeneralAndAdministrativeExpense', 200_000),
    ('us-gaap_GeneralAndAdministrativeExpense', 50_000),
    ('apo_ProprietaryConcept', 42),
])


# --- Balance sheet ---

def test_bs_prefix_stripped():
    v, c = _extract(MOCK_BALANCE, 'total_assets', BALANCE_DF, YEAR)
    assert v == 500_000
    assert 'Assets' in c

def test_bs_first_matching_concept():
    v, c = _extract(MOCK_BALANCE, 'cash', BALANCE_DF, YEAR)
    assert v == 100_000
    assert 'CashAndCashEquivalentsAtCarryingValue' in c

def test_bs_missing_concept_returns_none():
    v, c = _extract(MOCK_BALANCE, 'total_assets', make_df([]), YEAR)
    assert v is None
    assert c is None


# --- Cash flow ---

def test_cf_prefix_stripped():
    v, c = _extract(MOCK_CASHFLOW, 'net_cash_operating', CASHFLOW_DF, YEAR)
    assert v == 80_000
    assert 'NetCashProvidedByUsedInOperatingActivities' in c

def test_cf_aggregation_sums_components():
    v, c = _extract(MOCK_CASHFLOW, 'other_operating_activities', CASHFLOW_DF, YEAR,
                    aggregation_fields={'other_operating_activities'})
    assert v == -8_000.0
    assert '+' in c

def test_cf_dei_prefix_stripped():
    mapping = {'shares_outstanding': ['EntityCommonStockSharesOutstanding']}
    v, c = _extract(mapping, 'shares_outstanding', CASHFLOW_DF, YEAR)
    assert v == 999
    assert 'EntityCommonStockSharesOutstanding' in c


# --- Income statement ---

def test_inc_prefix_stripped():
    v, c = _extract(MOCK_INCOME, 'revenue', INCOME_DF, YEAR)
    assert v == 1_000_000
    assert 'RevenueFromContractWithCustomerExcludingAssessedTax' in c

def test_inc_aggregation():
    v, c = _extract(MOCK_INCOME, 'selling_general_admin', INCOME_DF, YEAR,
                    aggregation_fields={'selling_general_admin'})
    assert v == 250_000.0
    assert '+' in c

def test_inc_company_specific_prefix_stripped():
    mapping = {'proprietary': ['ProprietaryConcept']}
    v, c = _extract(mapping, 'proprietary', INCOME_DF, YEAR)
    assert v == 42
    assert 'ProprietaryConcept' in c


# --- Bare concept name stripping ---

@pytest.mark.parametrize("full,expected", [
    ('us-gaap_NetIncomeLoss',    'NetIncomeLoss'),
    ('dei_EntityCIK',            'EntityCIK'),
    ('srt_ConsolidatedEntities', 'ConsolidatedEntities'),
    ('apo_FreeCashFlow',         'FreeCashFlow'),
    ('BareNoPrefixConcept',      'BareNoPrefixConcept'),
])
def test_strip_prefix(full, expected):
    bare = full.split('_', 1)[1] if '_' in full else full
    assert bare == expected
