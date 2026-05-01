"""
XBRL Cash Flow Statement Concept Mapping
Based on analysis of 100+ companies from SEC EDGAR filings

Usage:
    from cash_flow_xbrl_mapping import CASH_FLOW_MAPPING
    
    concepts_to_try = CASH_FLOW_MAPPING['net_cash_operating_activities']
    for concept in concepts_to_try:
        # Try to find value using this concept
        ...

Notes:
- Concepts are ordered by frequency (most common first)
- All concepts are WITHOUT the 'us-gaap_' prefix (add when using)
- Cash flow can be direct or indirect method
"""

CASH_FLOW_MAPPING = {
    
    # =============================================================================
    # OPERATING ACTIVITIES (Indirect Method)
    # =============================================================================
    
    "net_income_starting_point": [
        # Starting point for indirect method
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAmortizationAndOther",      # MSFT and similar
        "OtherDepreciationAndAmortization",
        "AmortizationOfIntangibleAssets",
        "Depreciation",
    ],
    
    "stock_based_compensation": [
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense",
    ],
    
    "deferred_taxes": [
        "DeferredIncomeTaxExpenseBenefit",
        "DeferredIncomeTaxesAndTaxCredits",       # MSFT
        "IncreaseDecreaseInDeferredIncomeTaxes",
    ],
    
    "change_accounts_receivable": [
        "IncreaseDecreaseInAccountsReceivable",
        "IncreaseDecreaseInReceivables",
    ],
    
    "change_inventory": [
        "IncreaseDecreaseInInventories",
    ],
    
    "change_accounts_payable": [
        "IncreaseDecreaseInAccountsPayable",
    ],
    
    "change_accrued_expenses": [
        "IncreaseDecreaseInAccruedLiabilities",
        "IncreaseDecreaseInEmployeeRelatedLiabilities",
    ],

    "change_deferred_revenue": [
        "IncreaseDecreaseInDeferredRevenue",
        "IncreaseDecreaseInContractWithCustomerLiability",
    ],

    "other_operating_activities": [
        "IncreaseDecreaseInOtherOperatingCapitalNet",
        "OtherOperatingActivitiesCashFlowStatement",
    ],
    
    "net_cash_operating_activities": [
        # Most important - total operating cash flow
        "NetCashProvidedByUsedInOperatingActivities",
    ],
    
    # =============================================================================
    # INVESTING ACTIVITIES
    # =============================================================================
    
    "capital_expenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "CapitalExpendituresIncurredButNotYetPaid",
    ],
    
    "acquisitions": [
        "PaymentsToAcquireBusinessesNetOfCashAcquired",
        "PaymentsToAcquireBusinessesGross",
        "AcquisitionsNetOfCashAcquiredAndPurchasesOfIntangibleAndOtherAssets",  # MSFT
    ],
    
    "purchase_investments": [
        "PaymentsToAcquireInvestments",
        "PaymentsToAcquireAvailableForSaleSecurities",
    ],

    "sale_investments": [
        "ProceedsFromSaleOfAvailableForSaleSecurities",
        "ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",
        "ProceedsFromInvestments",                # MSFT and others
    ],
    
    "other_investing_activities": [
        "PaymentsForProceedsFromOtherInvestingActivities",
    ],
    
    "net_cash_investing_activities": [
        "NetCashProvidedByUsedInInvestingActivities",
    ],
    
    # =============================================================================
    # FINANCING ACTIVITIES
    # =============================================================================
    
    "debt_issuance": [
        "ProceedsFromIssuanceOfDebt",
        "ProceedsFromIssuanceOfLongTermDebt",
    ],
    
    "debt_repayment": [
        "RepaymentsOfDebt",
        "RepaymentsOfLongTermDebt",
        "RepaymentsOfDebtMaturingInMoreThanThreeMonths",       # MSFT
        "RepaymentsOfShortTermDebtMaturingInThreeMonthsOrLess", # MSFT
    ],
    
    "common_stock_issuance": [
        "ProceedsFromIssuanceOfCommonStock",
        "ProceedsFromStockOptionsExercised",
    ],
    
    "stock_repurchase": [
        "PaymentsForRepurchaseOfCommonStock",
        "TreasuryStockValueAcquiredCostMethod",
    ],
    
    "dividends_paid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
    ],
    
    "other_financing_activities": [
        "ProceedsFromPaymentsForOtherFinancingActivities",
    ],
    
    "net_cash_financing_activities": [
        "NetCashProvidedByUsedInFinancingActivities",
    ],
    
    # =============================================================================
    # SUMMARY
    # =============================================================================
    
    "effect_of_exchange_rate": [
        "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    
    "net_change_in_cash": [
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "CashAndCashEquivalentsPeriodIncreaseDecrease",
    ],
    
    "cash_beginning_of_period": [
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",  # Beginning balance
    ],
    
    "cash_end_of_period": [
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",  # Ending balance
    ],
    
    # =============================================================================
    # SUPPLEMENTAL DISCLOSURES
    # =============================================================================
    
    "cash_paid_for_interest": [
        "InterestPaidNet",
        "InterestPaid",
    ],
    
    "cash_paid_for_taxes": [
        "IncomeTaxesPaid",
        "IncomeTaxesPaidNet",
    ],
    
    # Non-cash activities
    "PaymentsRelatedToTaxWithholdingForShareBasedCompensation": [],
    "non_cash_stock_based_comp": [
        "ShareBasedCompensation",
    ],
}
