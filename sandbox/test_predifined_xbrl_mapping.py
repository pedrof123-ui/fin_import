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
        # Most common (245 occurrences)
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        # Second most common (203 occurrences)
        "Revenues",
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
    # COST OF REVENUE / COGS
    # =============================================================================
    
    "cost_of_revenue": [
        # Most common (253 occurrences)
        "CostOfGoodsAndServicesSold",
        # Second most common (86 occurrences)
        "CostOfRevenue",
        # Separate components
        "CostOfGoodsSold",
        "CostOfServices",
        # Combined with expenses
        "CostsAndExpenses",  # 154 occurrences
        "OperatingCostsAndExpenses",
        # Industry-specific
        "LiabilityForUnpaidClaimsAndClaimsAdjustmentExpenseIncurredClaims1",  # Insurance
        "BenefitsLossesAndExpenses",  # Insurance total expenses
        # Company-specific variations
        "avgo_CostofProductsSold",  # Broadcom
        "avgo_CostofSubscriptionsandServices",  # Broadcom
    ],
    
    "gross_profit": [
        # Standard (175 occurrences)
        "GrossProfit",
        # Percentage versions (for verification)
        "jnj_GrossProfitPercentToSales",  # J&J
        "low_GrossProfitPercent",  # Lowe's
    ],
    
    # =============================================================================
    # OPERATING EXPENSES
    # =============================================================================
    
    "research_development": [
        # Most common (145 occurrences)
        "ResearchAndDevelopmentExpense",
        # Alternative naming
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
        # Company-specific
        "glw_ResearchDevelopmentAndEngineeringExpenses",  # Corning
        "pypl_TechnologyAndDevelopmentExpense",  # PayPal
    ],
    
    "selling_general_admin": [
        # Most common (244 occurrences)
        "SellingGeneralAndAdministrativeExpense",
        # Separate components (139 + 60 occurrences)
        "GeneralAndAdministrativeExpense",
        "SellingAndMarketingExpense",
        "SellingExpense",
        "MarketingExpense",
        "MarketingAndAdvertisingExpense",
        # Combined variations
        "SellingGeneralAndAdministrativeExpenseIncludingIntersegmentRevenue",
        # Banking/Financial Services operating expense components
        # Banks report operating expenses as components of NoninterestExpense
        # We aggregate the specific components (NOT the total NoninterestExpense)
        "LaborAndRelatedExpense",  # Compensation expense (banks)
        "OccupancyNet",  # Occupancy/rent expense (banks, retail)
        "CommunicationsAndInformationTechnology",  # Technology expense (banks)
        "ProfessionalAndContractServicesExpense",  # Professional services (banks)
        # Company-specific
        "kmb_MarketingResearchAndGeneralExpenses",  # Kimberly-Clark
    ],
    
    "depreciation_amortization": [
        # Combined D&A (56 occurrences)
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        # Separate items
        "Depreciation",
        "AmortizationOfIntangibleAssets",  # 75 occurrences
        # In cost of revenue
        "avgo_Amortizationofacquisitionrelatedintangibleassetscostofproductssold",  # Broadcom
        # In operating expenses
        "avgo_Amortizationofacquisitionrelatedintangibleassetsoperatingexpenses",  # Broadcom
        "adbe_OperatingExpensesAmortizationOfPurchasedIntangibles",  # Adobe
    ],
    
    "restructuring_charges": [
        # Standard (71 occurrences)
        "RestructuringCharges",
        "RestructuringSettlementAndImpairmentProvisions",
        "AssetImpairmentCharges",
        "GainsLossesOnRestructuring",
        # Company-specific
        "tsla_RestructuringAndOtherExpenses",  # Tesla
        "avgo_RestructuringChargesCostOfProductsSold",  # Broadcom
        "aeo_ImpairmentAndRestructuringCharges",  # American Eagle
    ],
    
    "other_operating_expenses": [
        # Standard (50 occurrences)
        "OtherOperatingIncomeExpenseNet",
        "OtherCostAndExpenseOperating",
        # Specific types
        "LaborAndRelatedExpense",  # 66 occurrences
        "OccupancyNet",  # 46 occurrences (retail/banking)
        # Industry-specific
        "lmnd_OtherInsuranceExpense",  # Lemonade
        "cmcsa_ProgrammingAndProductionCosts",  # Comcast
        "amzn_FulfillmentExpense",  # Amazon
        "amzn_TechnologyAndInfrastructureExpense",  # Amazon
    ],
    
    "total_operating_expenses": [
        # Standard (122 occurrences)
        "OperatingExpenses",
        # Alternative
        "CostsAndExpenses",  # May include COGS
        # Banking
        "NoninterestExpense",  # 48 occurrences
    ],
    
    # =============================================================================
    # OPERATING INCOME (EBIT)
    # =============================================================================
    
    "operating_income": [
        # Most common (341 occurrences)
        "OperatingIncomeLoss",
        # Alternatives
        "OperatingProfitLoss",
        "OperatingProfit",
        # Before certain items
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",  # 54 occ
        "IncomeLossFromContinuingOperationsBeforeInterestExpenseInterestIncomeAndIncomeTaxes",
        # Company-specific
        "all_IncomeLossFromOperationsBeforeIncomeTaxExpenseBenefit",  # Allstate
    ],
    
    # =============================================================================
    # NON-OPERATING ITEMS
    # =============================================================================
    
    "interest_income": [
        # Most common (91 occurrences)
        "InvestmentIncomeInterest",
        "InterestIncomeOther",
        # Combined with dividends (42 occurrences)
        "InterestAndDividendIncomeOperating",
        # Net interest (68 occurrences)
        "InterestIncomeExpenseNet",
        "InterestIncomeExpenseNonoperatingNet",  # 42 occurrences
        # Company-specific
        "adm_InterestAndInvestmentIncome",  # ADM
    ],
    
    "interest_expense": [
        # Most common variations
        "InterestExpense",  # 88 occurrences
        "InterestExpenseNonoperating",  # 184 occurrences
        "InterestExpenseDebt",
        "InterestExpenseOperating",  # 58 occurrences
        # Specific debt types
        "cof_InterestExpenseOtherBorrowings",  # Capital One
        "cof_InterestExpenseSecuredDebt",  # Capital One
        "cof_InterestExpenseUnsecuredDebt",  # Capital One
    ],
    
    "equity_method_investments": [
        # Standard (94 occurrences)
        "IncomeLossFromEquityMethodInvestments",
        # Company-specific
        "gm_IncomeLossFromEquityMethodInvestmentsLessIncomeFromOperationalJointVenture",  # GM
    ],
    
    "investment_gains_losses": [
        # Securities
        "GainLossOnInvestmentSecurities",
        "GainLossOnSaleOfInvestments",
        "EquitySecuritiesFvNiGainLoss",  # Fair value (Tesla)
        "OtherInvestmentIncome",
        # Crypto (newer)
        "CryptoAssetUnrealizedGainLossNonoperating",
        # Insurance-specific
        "all_RealizedInvestmentGainsLossesContinuingOperations",  # Allstate
    ],
    
    "other_nonoperating_income": [
        # Most common (271 occurrences)
        "OtherNonoperatingIncomeExpense",
        # Alternatives
        "OtherNonoperatingIncome",
        "OtherNonoperatingExpense",
        # Combined
        "NonoperatingIncomeExpense",  # 179 occurrences
        "NonoperatingGainsLosses",
        # Specific items
        "GainsLossesOnExtinguishmentOfDebt",  # 46 occurrences
        "OtherIncome",
        "OtherExpenses",
        # Company-specific
        "apd_OtherIncomeExpenseNet",  # Air Products
        "ibm_OtherExpenseAndIncome",  # IBM
    ],
    
    # =============================================================================
    # PRETAX INCOME
    # =============================================================================
    
    "pretax_income": [
        # Most common (367 occurrences)
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        # Shorter versions
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        # Alternative naming
        "IncomeLossIncludingPortionAttributableToNoncontrollingInterest",
        # Company-specific
        "bk_IncomeLossFromContinuingOperationsBeforeIncomeTaxes",  # Bank of NY
        "cma_IncomeLossFromContinuingOperationsBeforeIncomeTaxes",  # Comerica
    ],
    
    # =============================================================================
    # INCOME TAX
    # =============================================================================
    
    "income_tax_expense": [
        # Most common (457 occurrences)
        "IncomeTaxExpenseBenefit",
        "IncomeTaxExpense",
        # Components
        "CurrentIncomeTaxExpenseBenefit",
        "DeferredIncomeTaxExpenseBenefit",
        # Company-specific
        "tem_ProvisionForIncomeTaxExpenseBenefit",  # Tempus AI
    ],
    
    # =============================================================================
    # NET INCOME
    # =============================================================================
    
    "net_income_continuing_ops": [
        # With NCI (44 occurrences)
        "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest",
        # Without NCI
        "IncomeLossFromContinuingOperations",
    ],
    
    "discontinued_operations": [
        # Net of tax
        "IncomeLossFromDiscontinuedOperationsNetOfTax",
        "DiscontinuedOperationGainLossOnDisposalOfDiscontinuedOperationNetOfTax",
        # Before tax
        "DiscontinuedOperationIncomeLossFromDiscontinuedOperationBeforeIncomeTax",
        # Per share
        "IncomeLossFromDiscontinuedOperationsNetOfTaxPerBasicShare",  # 43 occurrences
        "IncomeLossFromDiscontinuedOperationsNetOfTaxPerDilutedShare",  # 44 occurrences
    ],
    
    "net_income": [
        # Most common (450 occurrences)
        # This is total net income INCLUDING noncontrolling interests
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
        # This comes AFTER net_income and net_income_attributable_to_nci
        "NetIncomeLossAttributableToParent",
        # Variations
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    
    # =============================================================================
    # EARNINGS PER SHARE
    # =============================================================================
    
    "basic_eps": [
        # Most common (462 occurrences)
        "EarningsPerShareBasic",
        # Continuing operations (53 occurrences)
        "IncomeLossFromContinuingOperationsPerBasicShare",
        # Undistributed (for two-class method)
        "EarningsPerShareBasicUndistributed",
    ],
    
    "diluted_eps": [
        # Most common (461 occurrences)
        "EarningsPerShareDiluted",
        # Continuing operations (52 occurrences)
        "IncomeLossFromContinuingOperationsPerDilutedShare",
        # Undistributed
        "EarningsPerShareDilutedUndistributed",
    ],
    
    # =============================================================================
    # SHARES OUTSTANDING
    # =============================================================================
    
    "basic_shares": [
        # Most common (383 occurrences)
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
    
    "diluted_shares": [
        # Most common (383 occurrences)
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        # Adjustment
        "WeightedAverageNumberDilutedSharesOutstandingAdjustment",
    ],
    
    "antidilutive_securities": [
        # For disclosure
        "AntidilutiveSecuritiesExcludedFromComputationOfEarningsPerShareAmount",
    ],
    
    # =============================================================================
    # COMPREHENSIVE INCOME (OPTIONAL)
    # =============================================================================
    
    "comprehensive_income": [
        # Total (47 occurrences)
        "ComprehensiveIncomeNetOfTax",
        "ComprehensiveIncomeNetOfTaxIncludingPortionAttributableToNoncontrollingInterest",
        "ComprehensiveIncomeNetOfTaxAttributableToNoncontrollingInterest",
    ],
    
    "other_comprehensive_income": [
        # Total
        "OtherComprehensiveIncomeLossNetOfTax",
        # Components
        "OtherComprehensiveIncomeLossForeignCurrencyTransactionAndTranslationAdjustmentNetOfTax",
        "OtherComprehensiveIncomeLossCashFlowHedgeGainLossAfterReclassificationAndTax",
        "OtherComprehensiveIncomeAvailableforsaleSecuritiesAdjustmentNetOfTaxPortionAttributableToParent",
    ],
    
    # =============================================================================
    # DIVIDENDS (for reference)
    # =============================================================================
    
    "dividends_per_share": [
        # Declared (42 occurrences)
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
    ],
}


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_concepts_with_prefix(field_name: str, prefix: str = "us-gaap_") -> list:
    """
    Get list of concepts for a field with the specified prefix added
    
    Args:
        field_name: Key from INCOME_STATEMENT_MAPPING
        prefix: Prefix to add (default 'us-gaap_')
    
    Returns:
        List of concepts with prefix
    
    Example:
        >>> get_concepts_with_prefix('revenue')
        ['us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax', 
         'us-gaap_Revenues', ...]
    """
    concepts = INCOME_STATEMENT_MAPPING.get(field_name, [])
    
    result = []
    for concept in concepts:
        # If concept already has a prefix (company-specific), keep it
        if '_' in concept and not concept.startswith('us-gaap'):
            result.append(concept)
        else:
            result.append(f"{prefix}{concept}")
    
    return result


def get_all_unique_concepts() -> set:
    """Get set of all unique concepts across all fields"""
    all_concepts = set()
    for concepts_list in INCOME_STATEMENT_MAPPING.values():
        all_concepts.update(concepts_list)
    return all_concepts


def print_mapping_summary():
    """Print summary statistics of the mapping"""
    print("=" * 80)
    print("INCOME STATEMENT XBRL MAPPING SUMMARY")
    print("=" * 80)
    
    total_fields = len(INCOME_STATEMENT_MAPPING)
    total_concepts = sum(len(v) for v in INCOME_STATEMENT_MAPPING.values())
    unique_concepts = len(get_all_unique_concepts())
    
    print(f"Total fields mapped: {total_fields}")
    print(f"Total concept variations: {total_concepts}")
    print(f"Unique concepts: {unique_concepts}")
    print(f"Average concepts per field: {total_concepts / total_fields:.1f}")
    
    print("\nFields with most variations:")
    sorted_fields = sorted(
        INCOME_STATEMENT_MAPPING.items(), 
        key=lambda x: len(x[1]), 
        reverse=True
    )
    for field, concepts in sorted_fields[:10]:
        print(f"  {field:30s}: {len(concepts):2d} variations")


if __name__ == "__main__":
    print_mapping_summary()
    
    # Example usage
    print("\n" + "=" * 80)
    print("EXAMPLE: Revenue concepts with us-gaap_ prefix")
    print("=" * 80)
    for i, concept in enumerate(get_concepts_with_prefix('revenue')[:5], 1):
        print(f"{i}. {concept}")
