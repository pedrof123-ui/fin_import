"""
Balance Sheet XBRL Concept Mapping
Maps standardized balance sheet line items to XBRL concept variations

This file contains mappings for 38 balance sheet fields covering:
- Current Assets (9 fields)
- Non-Current Assets (8 fields)
- Current Liabilities (6 fields)
- Non-Current Liabilities (4 fields)
- Stockholders' Equity (6 fields)
- Totals (5 fields)

Total concepts mapped: 61 unique XBRL tags
"""

BALANCE_SHEET_MAPPING = {
    # ============================================================================
    # CURRENT ASSETS
    # ============================================================================
    
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
        "Cash",
        "CashAndDueFromBanks",
    ],
    
    "short_term_investments": [
        "AvailableForSaleSecuritiesCurrent",
        "MarketableSecuritiesCurrent",
        "ShortTermInvestments",
    ],
    
    "accounts_receivable": [
        "AccountsReceivableNetCurrent",
        "AccountsReceivableNet",
        "ReceivablesNetCurrent",
    ],
    
    "inventory": [
        "InventoryNet",
        "Inventory",
    ],
    
    "prepaid_expenses": [
        "PrepaidExpenseAndOtherAssetsCurrent",
        "PrepaidExpenseCurrent",
    ],
    
    "other_current_assets": [
        "OtherAssetsCurrent",
        "DeferredTaxAssetsNetCurrent",
    ],
    
    "total_current_assets": [
        "AssetsCurrent",
        "CurrentAssets",
    ],
    
    # ============================================================================
    # NON-CURRENT ASSETS
    # ============================================================================
    
    "ppe_net": [
        "PropertyPlantAndEquipmentNet",
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
    ],
    
    "ppe_gross": [
        "PropertyPlantAndEquipmentGross",
    ],
    
    "accumulated_depreciation": [
        "AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
    ],
    
    "goodwill": [
        "Goodwill",
    ],
    
    "intangible_assets": [
        "IntangibleAssetsNetExcludingGoodwill",
        "FiniteLivedIntangibleAssetsNet",
    ],
    
    "long_term_investments": [
        "AvailableForSaleSecuritiesNoncurrent",
        "LongTermInvestments",
    ],
    
    "deferred_tax_assets": [
        "DeferredIncomeTaxAssetsNet",
        "DeferredTaxAssetsNetNoncurrent",
    ],

    "other_noncurrent_assets": [
        "OtherAssetsNoncurrent",
    ],
    
    "total_noncurrent_assets": [
        "AssetsNoncurrent",
    ],
    
    "total_assets": [
        "Assets",
    ],
    
    # ============================================================================
    # CURRENT LIABILITIES
    # ============================================================================
    
    "accounts_payable": [
        "AccountsPayableCurrent",
        "AccountsPayable",
    ],
    
    "short_term_debt": [
        "ShortTermBorrowings",
        "DebtCurrent",
    ],
    
    "current_portion_long_term_debt": [
        "LongTermDebtCurrent",
    ],
    
    "accrued_expenses": [
        "AccruedLiabilitiesCurrent",
        "EmployeeRelatedLiabilitiesCurrent",
    ],
    
    "deferred_revenue_current": [
        "DeferredRevenueCurrent",
        "ContractWithCustomerLiabilityCurrent",
    ],
    
    "other_current_liabilities": [
        "OtherLiabilitiesCurrent",
    ],
    
    "total_current_liabilities": [
        "LiabilitiesCurrent",
    ],
    
    # ============================================================================
    # NON-CURRENT LIABILITIES
    # ============================================================================
    
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ],
    
    "deferred_tax_liabilities": [
        "DeferredTaxLiabilitiesNoncurrent",
    ],
    
    "deferred_revenue_noncurrent": [
        "DeferredRevenueNoncurrent",
        "ContractWithCustomerLiabilityNoncurrent",
    ],
    
    "other_noncurrent_liabilities": [
        "OtherLiabilitiesNoncurrent",
    ],
    
    "total_noncurrent_liabilities": [
        "LiabilitiesNoncurrent",
    ],
    
    "total_liabilities": [
        "Liabilities",
    ],
    
    # ============================================================================
    # STOCKHOLDERS' EQUITY
    # ============================================================================
    
    "common_stock": [
        "CommonStockValue",
        "CommonStockSharesOutstanding",
    ],
    
    "additional_paid_in_capital": [
        "AdditionalPaidInCapital",
        "AdditionalPaidInCapitalCommonStock",
    ],
    
    "retained_earnings": [
        "RetainedEarningsAccumulatedDeficit",
        "RetainedEarnings",
    ],
    
    "treasury_stock": [
        "TreasuryStockValue",
    ],
    
    "accumulated_other_comprehensive_income": [
        "AccumulatedOtherComprehensiveIncomeLossNetOfTax",
        "AOCI",
    ],
    
    "noncontrolling_interest": [
        "MinorityInterest",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    
    "total_equity": [
        "StockholdersEquity",
        "Equity",
    ],
    
    "total_liabilities_and_equity": [
        "LiabilitiesAndStockholdersEquity",
    ],
}

# Metadata
BALANCE_SHEET_FIELDS = list(BALANCE_SHEET_MAPPING.keys())
BALANCE_SHEET_CONCEPT_COUNT = sum(len(concepts) for concepts in BALANCE_SHEET_MAPPING.values())

if __name__ == "__main__":
    print("Balance Sheet XBRL Mapping")
    print("=" * 80)
    print(f"Total fields: {len(BALANCE_SHEET_FIELDS)}")
    print(f"Total concepts: {BALANCE_SHEET_CONCEPT_COUNT}")
    print("\nFields:")
    for field in BALANCE_SHEET_FIELDS:
        concept_count = len(BALANCE_SHEET_MAPPING[field])
        print(f"  - {field}: {concept_count} concepts")
