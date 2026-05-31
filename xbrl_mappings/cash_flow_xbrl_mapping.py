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
        # --- edgartools lower-confidence ---
        "EmployeeServiceShareBasedCompensationAllocationOfRecognizedPeriodCostsCapitalizedAmount",  # edgartools-expanded (conf=0.50)
    ],
    
    "deferred_taxes": [
        "DeferredIncomeTaxExpenseBenefit",
        "DeferredIncomeTaxesAndTaxCredits",       # MSFT
        "IncreaseDecreaseInDeferredIncomeTaxes",
    ],
    
    "change_accounts_receivable": [
        "IncreaseDecreaseInAccountsReceivable",
        "IncreaseDecreaseInReceivables",
        # --- edgartools lower-confidence ---
        "IncreaseDecreaseInAccountsAndNotesReceivable",  # edgartools-expanded (conf=0.50)
    ],
    
    "change_inventory": [
        "IncreaseDecreaseInInventories",
        # --- edgartools lower-confidence ---
        "AdjustmentsForDecreaseIncreaseInInventories",  # edgartools-expanded (conf=0.50)
    ],
    
    "change_accounts_payable": [
        "IncreaseDecreaseInAccountsPayable",
        # --- edgartools lower-confidence ---
        "AdjustmentsForIncreaseDecreaseInTradeAccountPayable",  # edgartools-expanded (conf=0.50)
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
        # --- edgartools high-confidence ---
        "IncreaseDecreaseInOtherCurrentAssets",  # edgartools-expanded (conf=0.97)
        "IncreaseDecreaseInOtherCurrentLiabilities",  # edgartools-expanded (conf=0.96)
        "IncreaseDecreaseInOtherOperatingAssets",  # edgartools-expanded (conf=1.00)
        "IncreaseDecreaseInOtherOperatingLiabilities",  # edgartools-expanded (conf=0.98)
        # --- edgartools lower-confidence ---
        "AdjustmentsForImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",  # edgartools-expanded (conf=0.50)
        "ImpairmentOfLongLivedAssetsToBeDisposedOf",  # edgartools-expanded (conf=0.50)
        "IncreaseDecreaseInOperatingCapital",  # edgartools-expanded (conf=0.50)
        "OtherNoncashIncome",  # edgartools-expanded (conf=0.50)
    ],
    
    "net_cash_operating_activities": [
        # Most important - total operating cash flow
        "NetCashProvidedByUsedInOperatingActivities",
        # --- edgartools high-confidence ---
        "CashFlowsFromUsedInOperatingActivities",  # edgartools-expanded (conf=0.99)
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",  # edgartools-expanded (conf=0.98)
    ],
    
    # =============================================================================
    # INVESTING ACTIVITIES
    # =============================================================================
    
    "capital_expenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "CapitalExpendituresIncurredButNotYetPaid",
        # --- edgartools lower-confidence ---
        "PaymentsToAcquireOtherProductiveAssets",  # edgartools-expanded (conf=0.50)
        "PaymentsToAcquireOtherPropertyPlantAndEquipment",  # edgartools-expanded (conf=0.50)
    ],
    
    "acquisitions": [
        "PaymentsToAcquireBusinessesNetOfCashAcquired",
        "PaymentsToAcquireBusinessesGross",
        "AcquisitionsNetOfCashAcquiredAndPurchasesOfIntangibleAndOtherAssets",  # MSFT
        # --- edgartools lower-confidence ---
        "AcquisitionOfSubsidiariesNetOfCashAcquired",  # edgartools-expanded (conf=0.50)
    ],
    
    "purchase_investments": [
        "PaymentsToAcquireInvestments",
        "PaymentsToAcquireAvailableForSaleSecurities",
        # --- edgartools high-confidence ---
        "PaymentsToAcquireAvailableForSaleSecuritiesDebt",  # edgartools-expanded (conf=0.98)
        "PaymentsToAcquireMarketableSecurities",  # edgartools-expanded (conf=0.97)
        "PaymentsToAcquireShortTermInvestments",  # edgartools-expanded (conf=0.96)
        # --- edgartools lower-confidence ---
        "PaymentsToAcquireHeldToMaturitySecurities",  # edgartools-expanded (conf=0.50)
        "PaymentsToAcquireOtherInvestments",  # edgartools-expanded (conf=0.50)
    ],

    "sale_investments": [
        "ProceedsFromSaleOfAvailableForSaleSecurities",
        "ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",
        "ProceedsFromInvestments",                # MSFT and others
        # --- edgartools high-confidence ---
        "ProceedsFromSaleAndMaturityOfMarketableSecurities",  # edgartools-expanded (conf=0.97)
        "ProceedsFromSaleOfAvailableForSaleSecuritiesDebt",  # edgartools-expanded (conf=0.98)
        # --- edgartools lower-confidence ---
        "ProceedsFromMaturitiesOfInvestments",  # edgartools-expanded (conf=0.50)
        "ProceedsFromMaturitiesPrepaymentsAndCallsOfHeldToMaturitySecurities",  # edgartools-expanded (conf=0.50)
        "ProceedsFromMaturitiesPrepaymentsAndCallsOfShorttermInvestments",  # edgartools-expanded (conf=0.50)
        "ProceedsFromSaleOfShortTermInvestments",  # edgartools-expanded (conf=0.50)
    ],
    
    "other_investing_activities": [
        "PaymentsForProceedsFromOtherInvestingActivities",
        # --- edgartools high-confidence ---
        "GainLossOnDispositionOfAssets",  # edgartools-expanded (conf=0.96)
        "ProceedsFromSaleOfProductiveAssets",  # edgartools-expanded (conf=0.95)
        # --- edgartools lower-confidence ---
        "AdjustmentsForLossesGainsOnDisposalOfNoncurrentAssets",  # edgartools-expanded (conf=0.50)
        "GainLossOnSaleOfAssets",  # edgartools-expanded (conf=0.50)
    ],
    
    "net_cash_investing_activities": [
        "NetCashProvidedByUsedInInvestingActivities",
        # --- edgartools high-confidence ---
        "CashFlowsFromUsedInInvestingActivities",  # edgartools-expanded (conf=0.99)
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",  # edgartools-expanded (conf=0.96)
    ],
    
    # =============================================================================
    # FINANCING ACTIVITIES
    # =============================================================================
    
    "debt_issuance": [
        "ProceedsFromIssuanceOfDebt",
        "ProceedsFromIssuanceOfLongTermDebt",
        # --- edgartools high-confidence ---
        "ProceedsFromConvertibleDebt",  # edgartools-expanded (conf=1.00)
        "ProceedsFromLongTermLinesOfCredit",  # edgartools-expanded (conf=0.97)
        "ProceedsFromNotesPayable",  # edgartools-expanded (conf=1.00)
        "ProceedsFromShortTermDebt",  # edgartools-expanded (conf=0.97)
        # --- edgartools lower-confidence ---
        "ProceedsFromBankDebt",  # edgartools-expanded (conf=0.50)
        "ProceedsFromIssuanceOfMediumTermNotes",  # edgartools-expanded (conf=0.50)
        "ProceedsFromIssuanceOfSeniorLongTermDebt",  # edgartools-expanded (conf=0.50)
        "ProceedsFromNoncurrentBorrowings",  # edgartools-expanded (conf=0.50)
    ],
    
    "debt_repayment": [
        "RepaymentsOfDebt",
        "RepaymentsOfLongTermDebt",
        "RepaymentsOfDebtMaturingInMoreThanThreeMonths",       # MSFT
        "RepaymentsOfShortTermDebtMaturingInThreeMonthsOrLess", # MSFT
        # --- edgartools high-confidence ---
        "RepaymentsOfLongTermLinesOfCredit",  # edgartools-expanded (conf=0.97)
        "RepaymentsOfNotesPayable",  # edgartools-expanded (conf=0.99)
        "RepaymentsOfShortTermDebt",  # edgartools-expanded (conf=0.97)
        # --- edgartools lower-confidence ---
        "RepaymentsOfCurrentBorrowings",  # edgartools-expanded (conf=0.50)
        "RepaymentsOfNoncurrentBorrowings",  # edgartools-expanded (conf=0.50)
        "RepaymentsOfSeniorDebt",  # edgartools-expanded (conf=0.50)
    ],
    
    "common_stock_issuance": [
        "ProceedsFromIssuanceOfCommonStock",
        "ProceedsFromStockOptionsExercised",
        # --- edgartools high-confidence ---
        "ProceedsFromIssuanceOfPreferredStockAndPreferenceStock",  # edgartools-expanded (conf=0.96)
        "ProceedsFromStockPlans",  # edgartools-expanded (conf=0.96)
        # --- edgartools lower-confidence ---
        "ProceedsFromIssuanceOfShares",  # edgartools-expanded (conf=0.50)
    ],
    
    "stock_repurchase": [
        "PaymentsForRepurchaseOfCommonStock",
        "TreasuryStockValueAcquiredCostMethod",
        # --- edgartools lower-confidence ---
        "PaymentsForRepurchaseOfEquity",  # edgartools-expanded (conf=0.50)
        "PaymentsForRepurchaseOfOtherEquity",  # edgartools-expanded (conf=0.50)
        "PaymentsForRepurchaseOfPreferredStockAndPreferenceStock",  # edgartools-expanded (conf=0.50)
        "PurchaseOfTreasuryShares",  # edgartools-expanded (conf=0.50)
    ],
    
    "dividends_paid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
        # --- edgartools high-confidence ---
        "DividendsCommonStockCash",  # edgartools-expanded (conf=0.98)
        # --- edgartools lower-confidence ---
        "DividendsCash",  # edgartools-expanded (conf=0.50)
        "DividendsPaidClassifiedAsFinancingActivities",  # edgartools-expanded (conf=0.50)
    ],
    
    "other_financing_activities": [
        "ProceedsFromPaymentsForOtherFinancingActivities",
        # --- edgartools high-confidence ---
        "FinanceLeasePrincipalPayments",  # edgartools-expanded (conf=0.97)
        "PaymentsOfDebtIssuanceCosts",  # edgartools-expanded (conf=0.99)
        "PaymentsOfFinancingCosts",  # edgartools-expanded (conf=0.98)
        "PaymentsToMinorityShareholders",  # edgartools-expanded (conf=0.96)
        # --- edgartools lower-confidence ---
        "PaymentsOfDividendsMinorityInterest",  # edgartools-expanded (conf=0.50)
        "RepaymentsOfLongTermCapitalLeaseObligations",  # edgartools-expanded (conf=0.50)
    ],
    
    "net_cash_financing_activities": [
        "NetCashProvidedByUsedInFinancingActivities",
        # --- edgartools high-confidence ---
        "CashFlowsFromUsedInFinancingActivities",  # edgartools-expanded (conf=0.99)
        # --- edgartools lower-confidence ---
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",  # edgartools-expanded (conf=0.50)
    ],
    
    # =============================================================================
    # SUMMARY
    # =============================================================================
    
    "effect_of_exchange_rate": [
        "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        # --- edgartools lower-confidence ---
        "EffectOfExchangeRateOnCashAndCashEquivalents",  # edgartools-expanded (conf=0.50)
    ],
    
    "net_change_in_cash": [
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "CashAndCashEquivalentsPeriodIncreaseDecrease",
        # --- edgartools high-confidence ---
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect",  # edgartools-expanded (conf=1.00)
        "IncreaseDecreaseInCashAndCashEquivalents",  # edgartools-expanded (conf=0.96)
    ],
    
    "cash_beginning_of_period": [
        # Same XBRL concept as cash_end_of_period but read from the prior-period column
        # via _PRIOR_PERIOD_FIELDS in the extractor. Concept excluded here to avoid
        # cross-field duplicate detection; populated by prior_period column lookup in extractor.
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
    "non_cash_stock_based_comp": [],  # ShareBasedCompensation consolidated into stock_based_compensation
}
