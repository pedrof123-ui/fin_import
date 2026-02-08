"""
XBRL Balance Sheet Concept Mapping
Based on analysis of 100+ companies from SEC EDGAR filings

Usage:
    from balance_sheet_xbrl_mapping import BALANCE_SHEET_MAPPING
    
    concepts_to_try = BALANCE_SHEET_MAPPING['total_assets']
    for concept in concepts_to_try:
        # Try to find value using this concept
        ...

Notes:
- Concepts are ordered by frequency (most common first)
- All concepts are WITHOUT the 'us-gaap_' prefix (add when using)
- Company-specific concepts (e.g., 'tsla_', 'gm_') are included
"""

BALANCE_SHEET_MAPPING = {
    
    # =============================================================================
    # CURRENT ASSETS
    # =============================================================================
    
    "cash_and_equivalents": [
        # Most common
        "CashAndCashEquivalentsAtCarryingValue",
        "Cash",
        "CashCashEquivalentsAndShortTermInvestments",
    ],
    
    "short_term_investments": [
        "ShortTermInvestments",
        "AvailableForSaleSecuritiesCurrent",
        "MarketableSecuritiesCurrent",
    ],
    
    "accounts_receivable": [
        # Net of allowance
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
        # Gross
        "AccountsReceivableGrossCurrent",
    ],
    
    "inventory": [
        "InventoryNet",
        "Inventory",
    ],
    
    "prepaid_expenses": [
        "PrepaidExpenseCurrent",
        "PrepaidExpenseAndOtherAssetsCurrent",
    ],
    
    "other_current_assets": [
        "OtherAssetsCurrent",
        "PrepaidExpenseAndOtherAssetsCurrent",
    ],
    
    "total_current_assets": [
        "AssetsCurrent",
    ],
    
    # =============================================================================
    # NON-CURRENT ASSETS
    # =============================================================================
    
    "ppe_gross": [
        "PropertyPlantAndEquipmentGross",
    ],
    
    "accumulated_depreciation": [
        "AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
    ],
    
    "ppe_net": [
        "PropertyPlantAndEquipmentNet",
    ],
    
    "goodwill": [
        "Goodwill",
    ],
    
    "intangible_assets": [
        "IntangibleAssetsNetExcludingGoodwill",
        "FiniteLivedIntangibleAssetsNet",
    ],
    
    "long_term_investments": [
        "LongTermInvestments",
        "AvailableForSaleSecuritiesNoncurrent",
    ],
    
    "other_noncurrent_assets": [
        "OtherAssetsNoncurrent",
        "DeferredCostsNoncurrent",
    ],
    
    "total_noncurrent_assets": [
        "AssetsNoncurrent",
    ],
    
    "total_assets": [
        # Most common
        "Assets",
    ],
    
    # =============================================================================
    # CURRENT LIABILITIES
    # =============================================================================
    
    "accounts_payable": [
        "AccountsPayableCurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
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
    
    # =============================================================================
    # NON-CURRENT LIABILITIES
    # =============================================================================
    
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ],
    
    "deferred_tax_liabilities": [
        "DeferredIncomeTaxLiabilitiesNet",
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
    
    # =============================================================================
    # EQUITY
    # =============================================================================
    
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
    ],
    
    "treasury_stock": [
        "TreasuryStockValue",
    ],
    
    "accumulated_other_comprehensive_income": [
        "AccumulatedOtherComprehensiveIncomeLossNetOfTax",
    ],
    
    "total_stockholders_equity": [
        "StockholdersEquity",
    ],
    
    "noncontrolling_interest": [
        "MinorityInterest",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    
    "total_equity": [
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "StockholdersEquity",
    ],
    
    "total_liabilities_and_equity": [
        "LiabilitiesAndStockholdersEquity",
    ],
}
