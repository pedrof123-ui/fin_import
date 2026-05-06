"""
XBRL Income Statement Concept Mapping
Based on analysis of 100+ companies from SEC EDGAR filings

Usage:
    from income_statement_xbrl_mapping import INCOME_STATEMENT_MAPPING
    
    concepts_to_try = INCOME_STATEMENT_MAPPING['revenue']
    for concept in concepts_to_try:
        # Try to find value using this concept
        ...

Notes:
- Concepts are ordered by frequency (most common first)
- All concepts are WITHOUT the 'us-gaap_' prefix (add when using)
- Company-specific concepts (e.g., 'tsla_', 'gm_') are included
- Covers 460+ companies worth of actual XBRL usage
"""

INCOME_STATEMENT_MAPPING = {
    
    # =============================================================================
    # REVENUE SECTION
    # =============================================================================
    
    "revenue": [
        # Revenues is the US-GAAP aggregate concept (includes all income sources).
        # Preferred over RFCWCEA because when both exist, RFCWCEA is a subtotal
        # (e.g. WMT: RFCWCEA=$706B contract sales, Revenues=$713B incl. membership fees).
        # Companies that only file RFCWCEA (AAPL, MSFT, AMZN) fall through correctly.
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        # Alternative revenue concepts
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        # Revenue not from contracts (e.g., GM Financial)
        "RevenueNotFromContractWithCustomer",
        # Industry-specific
        "PremiumsEarnedNet",  # Insurance (Lemonade)
        "NetInvestmentIncome",  # Insurance
        "InsuranceCommissionsAndFees",  # Insurance
        # Banking/Financial
        "InterestAndDividendIncomeOperating",
        "NoninterestIncome",
        # Company-specific
        "bk_TotalRevenuesIncludingRevenueGeneratedByVariableInterestEntities",  # Bank of NY
        "elv_OperatingRevenue",  # Elevance Health
    ],
    
    # =============================================================================
    # COST OF REVENUE SECTION  
    # =============================================================================
    
    "cost_of_revenue": [
        # Most common (340 occurrences)
        "CostOfRevenue",
        # Alternative (125 occurrences)
        "CostOfGoodsAndServicesSold",
        # Variations
        "CostOfGoodsSold",
        "CostOfServices",
        "CostOfGoodsAndServicesSold",
        # Banking/Insurance
        "BenefitsLossesAndExpenses",  # Insurance (Lemonade)
        "PolicyholderBenefitsAndClaimsIncurredNet",  # Insurance
        # Company-specific
        "elv_BenefitExpense",  # Elevance Health
    ],
    
    "gross_profit": [
        # Standard (382 occurrences)
        "GrossProfit",
        # Alternative calculation (if not provided directly)
        # revenue - cost_of_revenue
    ],
    
    # =============================================================================
    # OPERATING EXPENSES
    # =============================================================================
    
    "research_development": [
        # Most common (180 occurrences)
        "ResearchAndDevelopmentExpense",
        # With acquired IPR&D excluded
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
        # Variations
        "ResearchAndDevelopmentExpenseSoftwareExcludingAcquiredInProcessCost",
    ],
    
    "selling_general_admin": [
        # Most common (305 occurrences)
        "SellingGeneralAndAdministrativeExpense",
        # Combined with R&D
        "ResearchDevelopmentAndRelatedExpenses",  # Some companies combine
        # Individual components
        "SellingAndMarketingExpense",
        "GeneralAndAdministrativeExpense",
        "MarketingAndAdvertisingExpense",
        # Company-specific (namespace prefix stripped at match time)
        "MarketingResearchAndGeneralExpense",  # Kimberly-Clark (kmb_)
        # Banking/Financial Services operating expense components
        # Banks report operating expenses as components of NoninterestExpense
        # We aggregate the specific components (NOT the total NoninterestExpense)
        "LaborAndRelatedExpense",  # Compensation expense (banks)
        "OccupancyNet",  # Occupancy/rent expense (banks, retail)
        "CommunicationsAndInformationTechnology",  # Technology expense (banks)
        "ProfessionalAndContractServicesExpense",  # Professional services (banks)
    ],
    
    "depreciation_amortization": [
        # Standard (145 occurrences)
        "DepreciationDepletionAndAmortization",
        # Separate D&A
        "Depreciation",
        "AmortizationOfIntangibleAssets",
        # Combined with depletion
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
    ],
    
    "restructuring_charges": [
        # Most common (89 occurrences)
        "RestructuringCharges",
        "RestructuringCostsAndAssetImpairmentCharges",
        # With asset impairment and settlement
        "RestructuringSettlementAndImpairmentProvisions",
        # Just impairment
        "AssetImpairmentCharges",
        "GoodwillAndIntangibleAssetImpairment",
        "GoodwillImpairmentLoss",
    ],
    
    "other_operating_expenses": [
        # Net other operating income/expense
        "OtherOperatingIncomeExpenseNet",
        # Specific items
        "OtherCostAndExpenseOperating",
        "LossGainOnDispositionOfAssets",
        "GainLossOnSaleOfPropertyPlantEquipment",
    ],
    
    "total_operating_expenses": [
        # Total costs and expenses
        "CostsAndExpenses",
        "OperatingExpenses",
        "OperatingCostsAndExpenses",
    ],
    
    "operating_income": [
        # Most common (375 occurrences)
        "OperatingIncomeLoss",
        # Alternative terminology
        "IncomeLossFromOperations",
        # Banking
        "NoninterestExpense",  # For banks (use negative)
    ],
    
    # =============================================================================
    # NON-OPERATING ITEMS
    # =============================================================================
    
    "interest_income": [
        # Most common
        "InterestIncomeOther",
        "InvestmentIncomeInterest",
        "InterestAndDividendIncomeOperating",
        "InterestAndDividendIncomeSecurities",
        # Banking
        "InterestAndFeeIncomeLoansAndLeases",
        "InterestIncomeDepositsWithFinancialInstitutions",
    ],
    
    "interest_expense": [
        # Most common (310 occurrences)
        "InterestExpense",
        # Breakdown
        "InterestExpenseDebt",
        "InterestExpenseBorrowings",
        "InterestExpenseOther",
        # Net interest (for banks)
        "InterestIncomeExpenseNet",  # Use negative if expense exceeds income
    ],
    
    "equity_method_investments": [
        # Standard
        "IncomeLossFromEquityMethodInvestments",
        "IncomeLossFromEquityMethodInvestmentsNetOfDividendsOrDistributions",
    ],
    
    "investment_gains_losses": [
        # Realized gains/losses
        "GainLossOnInvestments",
        "RealizedInvestmentGainsLosses",
        "MarketableSecuritiesRealizedGainLoss",
        # Unrealized (mark-to-market)
        "MarketableSecuritiesUnrealizedGainLoss",
        "FairValueAdjustmentOfWarrants",
    ],
    
    "other_nonoperating_income": [
        # Catchall for other items
        "OtherNonoperatingIncomeExpense",
        "NonoperatingIncomeExpense",
        "OtherIncome",
        # Foreign currency
        "ForeignCurrencyTransactionGainLossBeforeTax",
        "ForeignCurrencyGainLossRealized",
    ],
    
    # =============================================================================
    # INCOME BEFORE TAXES
    # =============================================================================
    
    "pretax_income": [
        # Most common (420 occurrences)
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        # Shorter variations
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
        "IncomeLossFromContinuingOperationsBeforeTax",
        "IncomeLossBeforeIncomeTax",
        # Alternative terminology
        "IncomeLossAttributableToParent",  # Some companies use this
    ],
    
    "income_tax_expense": [
        # Standard (440 occurrences)
        "IncomeTaxExpenseBenefit",
        # Current vs deferred breakdown
        "CurrentIncomeTaxExpenseBenefit",
        "DeferredIncomeTaxExpenseBenefit",
    ],
    
    # =============================================================================
    # NET INCOME SECTION
    # =============================================================================
    
    "net_income_continuing_ops": [
        # Income from continuing operations (before discontinued ops)
        "IncomeLossFromContinuingOperations",
        "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest",
        "NetIncomeLossFromContinuingOperations",
    ],
    
    "discontinued_operations": [
        # Gain/loss from discontinued operations
        "IncomeLossFromDiscontinuedOperationsNetOfTax",
        "IncomeLossFromDiscontinuedOperationsNetOfTaxAttributableToReportingEntity",
        "DiscontinuedOperationIncomeLossFromDiscontinuedOperationBeforeIncomeTax",
        "DisposalGroupIncludingDiscontinuedOperationGainLossOnDisposal",
    ],
    
    "net_income": [
        # Most common (450 occurrences)
        "NetIncomeLoss",
        # Alternative (235 occurrences)
        "ProfitLoss",
        # Available to common (106 occurrences)
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "NetIncomeLossAvailableToCommonStockholdersDiluted",
        "NetIncomeLossFromContinuingOperationsAvailableToCommonShareholdersBasic",
        # Company-specific
        "pnc_NetIncomeLossAvailableToCommonStockholders",  # PNC
        "bk_NetIncomeLossAvailableToCommonShareholdersBasicAfterRequiredAdjustments",  # Bank of NY
    ],
    
    "net_income_attributable_to_nci": [
        # Standard (194 occurrences)
        # Now comes AFTER net_income (total) and BEFORE net_income_attributable_to_parent
        # Income statement flow: Net Income (total) → Less: NCI → Net Income to Parent
        "NetIncomeLossAttributableToNoncontrollingInterest",
    ],
    
    "net_income_attributable_to_parent": [
        # Standard
        # Now comes AFTER subtracting NCI
        "NetIncomeLossAttributableToParent",
        # Variations
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    
    # =============================================================================
    # PER SHARE DATA
    # =============================================================================
    
    "basic_eps": [
        # Most common (450 occurrences)
        "EarningsPerShareBasic",
        # From continuing operations only
        "IncomeLossFromContinuingOperationsPerBasicShare",
    ],
    
    "diluted_eps": [
        # Most common (445 occurrences)
        "EarningsPerShareDiluted",
        # From continuing operations only
        "IncomeLossFromContinuingOperationsPerDilutedShare",
    ],
    
    "basic_shares": [
        # Weighted average shares - basic
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "WeightedAverageNumberOfSharesIssuedBasic",
    ],
    
    "diluted_shares": [
        # Weighted average shares - diluted
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesIssuedDiluted",
    ],
    
    "antidilutive_securities": [
        # Securities excluded from diluted EPS calculation
        "AntidilutiveSecuritiesExcludedFromComputationOfEarningsPerShareAmount",
    ],
    
    # =============================================================================
    # OTHER COMPREHENSIVE INCOME
    # =============================================================================
    
    "comprehensive_income": [
        # Total comprehensive income
        "ComprehensiveIncomeNetOfTax",
        "ComprehensiveIncomeNetOfTaxIncludingPortionAttributableToNoncontrollingInterest",
        "ComprehensiveIncomeNetOfTaxAttributableToParent",
    ],
    
    "other_comprehensive_income": [
        # Other comprehensive income (OCI)
        "OtherComprehensiveIncomeLossNetOfTax",
        "OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent",
        # Components
        "OtherComprehensiveIncomeLossForeignCurrencyTransactionAndTranslationAdjustmentNetOfTax",
        "OtherComprehensiveIncomeUnrealizedHoldingGainLossOnSecuritiesArisingDuringPeriodNetOfTax",
        "OtherComprehensiveIncomeLossPensionAndOtherPostretirementBenefitPlansAdjustmentNetOfTax",
    ],
    
    "dividends_per_share": [
        # Cash dividends declared per share
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
    ],
}

