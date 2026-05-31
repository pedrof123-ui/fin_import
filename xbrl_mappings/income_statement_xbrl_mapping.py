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
        # Banking/Financial (revenue only — InterestAndDividendIncomeOperating kept in interest_income)
        "NoninterestIncome",
        # Company-specific
        "bk_TotalRevenuesIncludingRevenueGeneratedByVariableInterestEntities",  # Bank of NY
        "elv_OperatingRevenue",  # Elevance Health
        # --- edgartools lower-confidence ---
        "InsuranceServicesRevenue",  # edgartools-expanded (conf=0.50)
        "OilAndGasSalesRevenue",  # edgartools-expanded (conf=0.50)
        "OperatingLeasesIncomeStatementMinimumLeaseRevenue",  # edgartools-expanded (conf=0.50)
        "PercentageRent",  # edgartools-expanded (conf=0.50)
        "PrincipalTransactionsRevenue",  # edgartools-expanded (conf=0.50)
        "ReimbursementRevenue",  # edgartools-expanded (conf=0.50)
        "ResearchAndDevelopmentArrangementContractToPerformForOthersCompensationEarned",  # edgartools-expanded (conf=0.50)
        "RetailRevenue",  # edgartools-expanded (conf=0.50)
        "SaleOfTrustAssetsToPayExpenses",  # edgartools-expanded (conf=0.50)
        "TimberRevenue",  # edgartools-expanded (conf=0.50)
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
        # Banking/Insurance
        "BenefitsLossesAndExpenses",  # Insurance (Lemonade)
        "PolicyholderBenefitsAndClaimsIncurredNet",  # Insurance
        # Company-specific
        "elv_BenefitExpense",  # Elevance Health
        # --- edgartools lower-confidence ---
        "AircraftRentalAndLandingFees",  # edgartools-expanded (conf=0.50)
        "CostDirectLabor",  # edgartools-expanded (conf=0.50)
        "CostOfGoodsAndServicesSoldOverhead",  # edgartools-expanded (conf=0.50)
        "CostOfOtherPropertyOperatingExpense",  # edgartools-expanded (conf=0.50)
        "CostOfPropertyRepairsAndMaintenance",  # edgartools-expanded (conf=0.50)
        "CostOfPurchasedPower",  # edgartools-expanded (conf=0.50)
        "CostOfPurchasedWater",  # edgartools-expanded (conf=0.50)
        "CostOfRealEstateRevenue",  # edgartools-expanded (conf=0.50)
        "CostOfRealEstateSales",  # edgartools-expanded (conf=0.50)
        "DirectCommunicationsAndUtilitiesCosts",  # edgartools-expanded (conf=0.50)
        "DirectOperatingCommunicationsCosts",  # edgartools-expanded (conf=0.50)
        "DirectOperatingMaintenanceSuppliesCosts",  # edgartools-expanded (conf=0.50)
        "DirectTaxesAndLicensesCosts",  # edgartools-expanded (conf=0.50)
        "FacilityCosts",  # edgartools-expanded (conf=0.50)
        "FuelCosts",  # edgartools-expanded (conf=0.50)
        "InventoryFirmPurchaseCommitmentLoss",  # edgartools-expanded (conf=0.50)
        "LossOnContracts",  # edgartools-expanded (conf=0.50)
        "ManufacturingCosts",  # edgartools-expanded (conf=0.50)
        "OperatingInsuranceAndClaimsCostsProduction",  # edgartools-expanded (conf=0.50)
        "PolicyholderBenefitsAndClaimsIncurredGross",  # edgartools-expanded (conf=0.50)
        "ProductionAndDistributionCosts",  # edgartools-expanded (conf=0.50)
        "ProvisionForCreditLosses",  # edgartools-expanded (conf=0.50)
        "RecoveryOfDirectCosts",  # edgartools-expanded (conf=0.50)
        "ResultsOfOperationsTransportationCosts",  # edgartools-expanded (conf=0.50)
        "WaterProductionCosts",  # edgartools-expanded (conf=0.50)
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
        # --- edgartools lower-confidence ---
        "ResearchAndDevelopmentAssetAcquiredOtherThanThroughBusinessCombinationWrittenOff",  # edgartools-expanded (conf=0.50)
        "ResearchAndDevelopmentInProcess",  # edgartools-expanded (conf=0.50)
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
        # --- edgartools high-confidence ---
        "ProfessionalFees",  # edgartools-expanded (conf=1.00)
        # --- edgartools lower-confidence ---
        "CooperativeAdvertisingExpense",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanNetPeriodicBenefitCost",  # edgartools-expanded (conf=0.50)
        "DistributionCosts",  # edgartools-expanded (conf=0.50)
        "EmployeeBenefitsExpense",  # edgartools-expanded (conf=0.50)
        "GeneralInsuranceExpense",  # edgartools-expanded (conf=0.50)
        "ProductionTaxExpense",  # edgartools-expanded (conf=0.50)
        "PumpTaxes",  # edgartools-expanded (conf=0.50)
        "RealEstateTaxesAndInsurance",  # edgartools-expanded (conf=0.50)
        "SalariesAndWages",  # edgartools-expanded (conf=0.50)
        "SalariesWagesAndOfficersCompensation",  # edgartools-expanded (conf=0.50)
        "TaxesOther",  # edgartools-expanded (conf=0.50)
        "TravelAndEntertainmentExpense",  # edgartools-expanded (conf=0.50)
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
        # --- edgartools lower-confidence ---
        "CapitalizedComputerSoftwareAmortization",  # edgartools-expanded (conf=0.50)
        "CostDepreciationAmortizationAndDepletion",  # edgartools-expanded (conf=0.50)
        "DepletionOfOilAndGasProperties",  # edgartools-expanded (conf=0.50)
        "DepreciationNonproduction",  # edgartools-expanded (conf=0.50)
        "ImpairmentOfIntangibleAssetsFinitelived",  # edgartools-expanded (conf=0.50)
        "ImpairmentOfIntangibleAssetsIndefinitelivedExcludingGoodwill",  # edgartools-expanded (conf=0.50)
        "ResultsOfOperationsDepreciationDepletionAmortizationAndAccretion",  # edgartools-expanded (conf=0.50)
        "ResultsOfOperationsDepreciationDepletionAndAmortizationAndValuationProvisions",  # edgartools-expanded (conf=0.50)
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
        # --- edgartools lower-confidence ---
        "AmortizationOfAcquisitionCosts",  # edgartools-expanded (conf=0.50)
        "BusinessExitCosts1",  # edgartools-expanded (conf=0.50)
        "CostOfGoodsAndServicesSoldAmortization",  # edgartools-expanded (conf=0.50)
        "DebtorReorganizationItemsDebtorInPossessionFacilityFinancingCosts",  # edgartools-expanded (conf=0.50)
        "DebtorReorganizationItemsLegalAndAdvisoryProfessionalFees",  # edgartools-expanded (conf=0.50)
        "DebtorReorganizationItemsProvisionForExpectedAllowedClaims",  # edgartools-expanded (conf=0.50)
        "DisposalGroupNotDiscontinuedOperationLossGainOnWriteDown",  # edgartools-expanded (conf=0.50)
        "ExplorationAbandonmentAndImpairmentExpense",  # edgartools-expanded (conf=0.50)
        "ImpairmentChargeOnReclassifiedAssets",  # edgartools-expanded (conf=0.50)
        "ImpairmentLossesRelatedToRealEstatePartnerships",  # edgartools-expanded (conf=0.50)
        "ImpairmentOfLeasehold",  # edgartools-expanded (conf=0.50)
        "ImpairmentOfOngoingProject",  # edgartools-expanded (conf=0.50)
        "ImpairmentOfRetainedInterest",  # edgartools-expanded (conf=0.50)
        "OtherRestructuringCosts",  # edgartools-expanded (conf=0.50)
        "RecapitalizationCosts",  # edgartools-expanded (conf=0.50)
        "ReorganizationItems",  # edgartools-expanded (conf=0.50)
        "RestructuringReserveAcceleratedDepreciation",  # edgartools-expanded (conf=0.50)
        "RestructuringReserveAccrualAdjustment1",  # edgartools-expanded (conf=0.50)
        "ResultsOfOperationsImpairmentOfOilAndGasProperties",  # edgartools-expanded (conf=0.50)
        "UnamortizedCostsCapitalizedLessRelatedDeferredIncomeTaxesExceedCeilingLimitationExpense",  # edgartools-expanded (conf=0.50)
    ],
    
    "other_operating_expenses": [
        # Net other operating income/expense
        "OtherOperatingIncomeExpenseNet",
        # Specific items
        "OtherCostAndExpenseOperating",
        "LossGainOnDispositionOfAssets",
        "GainLossOnSaleOfPropertyPlantEquipment",
        # --- edgartools lower-confidence ---
        "AccretionExpense",  # edgartools-expanded (conf=0.50)
        "AcquisitionCosts",  # edgartools-expanded (conf=0.50)
        "AssetRetirementObligationAccretionExpense",  # edgartools-expanded (conf=0.50)
        "CompensationExpenseExcludingCostOfGoodAndServiceSold",  # edgartools-expanded (conf=0.50)
        "CostsIncurredAssetRetirementObligationIncurred",  # edgartools-expanded (conf=0.50)
        "CostsIncurredDevelopmentCosts",  # edgartools-expanded (conf=0.50)
        "DefinedContributionPlanCostRecognized",  # edgartools-expanded (conf=0.50)
        "DevelopmentCosts",  # edgartools-expanded (conf=0.50)
        "EnvironmentalRemediationExpense",  # edgartools-expanded (conf=0.50)
        "ExplorationCosts",  # edgartools-expanded (conf=0.50)
        "FranchisorCosts",  # edgartools-expanded (conf=0.50)
        "GainsLossesOnDisposalsOfNoncurrentAssets",  # edgartools-expanded (conf=0.50)
        "GainsOnDisposalsOfNoncurrentAssets",  # edgartools-expanded (conf=0.50)
        "InformationTechnologyAndDataProcessing",  # edgartools-expanded (conf=0.50)
        "InterestExpenseOnLeaseLiabilities",  # edgartools-expanded (conf=0.50)
        "LossContingencyAccrualCarryingValuePeriodIncreaseDecrease",  # edgartools-expanded (conf=0.50)
        "LossContingencyDamagesSoughtValue",  # edgartools-expanded (conf=0.50)
        "LossOnContractTermination",  # edgartools-expanded (conf=0.50)
        "OperatingLeaseCost",  # edgartools-expanded (conf=0.50)
        "OperatingLeaseImpairmentLoss",  # edgartools-expanded (conf=0.50)
        "OtherPostretirementBenefitExpense",  # edgartools-expanded (conf=0.50)
        "OtherRecurringIncome",  # edgartools-expanded (conf=0.50)
        "PaymentsForOtherTaxes",  # edgartools-expanded (conf=0.50)
        "PensionExpense",  # edgartools-expanded (conf=0.50)
        "PostemploymentBenefitsPeriodExpense",  # edgartools-expanded (conf=0.50)
        "ProductLiabilityAccrualPeriodExpense",  # edgartools-expanded (conf=0.50)
        "ProductionCosts",  # edgartools-expanded (conf=0.50)
        "ProvisionForOtherCreditLosses",  # edgartools-expanded (conf=0.50)
        "RealEstateTaxExpense",  # edgartools-expanded (conf=0.50)
        "ReclamationAndMineShutdownProvision",  # edgartools-expanded (conf=0.50)
        "ResultsOfOperationsDryHoleCosts",  # edgartools-expanded (conf=0.50)
        "ResultsOfOperationsExplorationExpense",  # edgartools-expanded (conf=0.50)
        "RoyaltyExpense",  # edgartools-expanded (conf=0.50)
        "SharebasedCompensationArrangementBySharebasedPaymentAwardCompensationCost1",  # edgartools-expanded (conf=0.50)
    ],
    
    "total_operating_expenses": [
        # Total costs and expenses
        "CostsAndExpenses",
        "OperatingExpenses",
        "OperatingCostsAndExpenses",
        # --- edgartools lower-confidence ---
        "OperatingExpense",  # edgartools-expanded (conf=0.50)
    ],
    
    "operating_income": [
        # Most common (375 occurrences)
        "OperatingIncomeLoss",
        # Alternative terminology
        "IncomeLossFromOperations",
        # Banking
        "NoninterestExpense",  # For banks (use negative)
        # --- edgartools high-confidence ---
        "ProfitLossFromOperatingActivities",  # edgartools-expanded (conf=0.99)
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
        # --- edgartools lower-confidence ---
        "InterestIncomeForeignDeposits",  # edgartools-expanded (conf=0.50)
        "InterestIncomeMoneyMarketDeposits",  # edgartools-expanded (conf=0.50)
        "InterestIncomeOperatingAndNonoperating",  # edgartools-expanded (conf=0.50)
        "InterestIncomeOtherDomesticDeposits",  # edgartools-expanded (conf=0.50)
        "InterestIncomeRelatedParty",  # edgartools-expanded (conf=0.50)
        "InterestIncomeSecuritiesOtherUSGovernment",  # edgartools-expanded (conf=0.50)
        "InterestIncomeSecuritiesStateAndMunicipal",  # edgartools-expanded (conf=0.50)
        "InterestIncomeSecuritiesUSTreasury",  # edgartools-expanded (conf=0.50)
        "InvestmentIncomeDividend",  # edgartools-expanded (conf=0.50)
        "LitigationSettlementInterest",  # edgartools-expanded (conf=0.50)
        "OtherInterestAndDividendIncome",  # edgartools-expanded (conf=0.50)
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
        # --- edgartools high-confidence ---
        "AmortizationOfDebtDiscountPremium",  # edgartools-expanded (conf=1.00)
        "AmortizationOfFinancingCosts",  # edgartools-expanded (conf=0.99)
        # --- edgartools lower-confidence ---
        "AmortizationOfDeferredHedgeGains",  # edgartools-expanded (conf=0.50)
        "DebtRelatedCommitmentFeesAndDebtIssuanceCosts",  # edgartools-expanded (conf=0.50)
        "FinanceExpense",  # edgartools-expanded (conf=0.50)
        "GainsLossesOnExtinguishmentOfDebtBeforeWriteOffOfDeferredDebtIssuanceCost",  # edgartools-expanded (conf=0.50)
        "InterestAndDebtExpense",  # edgartools-expanded (conf=0.50)
        "InterestCostsCapitalized",  # edgartools-expanded (conf=0.50)
        "InterestCostsIncurred",  # edgartools-expanded (conf=0.50)
        "InterestCostsIncurredCapitalized",  # edgartools-expanded (conf=0.50)
        "InterestExpenseCustomerDeposits",  # edgartools-expanded (conf=0.50)
        "InterestExpenseLesseeAssetsUnderCapitalLease",  # edgartools-expanded (conf=0.50)
        "InterestExpenseRelatedParty",  # edgartools-expanded (conf=0.50)
        "InterestPaidCapitalized",  # edgartools-expanded (conf=0.50)
        "InterestRevenueExpenseNet",  # edgartools-expanded (conf=0.50)
        "WriteOffOfDeferredDebtIssuanceCost",  # edgartools-expanded (conf=0.50)
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
        # --- edgartools lower-confidence ---
        "AccretionExpenseIncludingAssetRetirementObligations",  # edgartools-expanded (conf=0.50)
        "AvailableForSaleSecuritiesGrossRealizedGainLossNet",  # edgartools-expanded (conf=0.50)
        "AvailableForSaleSecuritiesGrossRealizedGains",  # edgartools-expanded (conf=0.50)
        "AvailableforsaleSecuritiesGrossRealizedGainLossExcludingOtherThanTemporaryImpairments",  # edgartools-expanded (conf=0.50)
        "BusinessCombinationBargainPurchaseGainRecognizedAmount",  # edgartools-expanded (conf=0.50)
        "BusinessCombinationContingentConsiderationArrangementsChangeInAmountOfContingentConsiderationAsset1",  # edgartools-expanded (conf=0.50)
        "BusinessCombinationStepAcquisitionEquityInterestInAcquireeRemeasurementGainOrLoss",  # edgartools-expanded (conf=0.50)
        "BusinessCombinationStepAcquisitionEquityInterestInAcquireeRemeasurementLoss",  # edgartools-expanded (conf=0.50)
        "CapitalLeasesIncomeStatementLeaseRevenue",  # edgartools-expanded (conf=0.50)
        "ChangeInUnrealizedGainLossOnForeignCurrencyFairValueHedgingInstruments1",  # edgartools-expanded (conf=0.50)
        "CostmethodInvestmentsOtherThanTemporaryImpairment",  # edgartools-expanded (conf=0.50)
        "DebtAndEquitySecuritiesUnrealizedGainLossExcludingOtherThanTemporaryImpairment",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesAvailableForSaleAllowanceForCreditLossWriteoff",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesAvailableForSaleRealizedGain",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesAvailableForSaleRealizedLoss",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesTradingGainLoss",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesTradingRealizedGain",  # edgartools-expanded (conf=0.50)
        "DeferredCompensationArrangementWithIndividualCompensationExpense",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanActuarialGainLossImmediateRecognitionAsComponentInNetPeriodicBenefitCostCredit",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanAmortizationOfGainsLosses",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanAmortizationOfPriorServiceCostCredit",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanOtherCosts",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanPurchasesSalesAndSettlements",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanRecognizedNetGainLossDueToCurtailments",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanRecognizedNetGainLossDueToSettlements1",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanRecognizedNetGainLossDueToSettlementsAndCurtailments1",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanSettlementsBenefitObligation",  # edgartools-expanded (conf=0.50)
        "DerivativeGainOnDerivative",  # edgartools-expanded (conf=0.50)
        "EmbeddedDerivativeLossOnEmbeddedDerivative",  # edgartools-expanded (conf=0.50)
        "EquitySecuritiesFvNiRealizedGain",  # edgartools-expanded (conf=0.50)
        "EquitySecuritiesFvNiRealizedLoss",  # edgartools-expanded (conf=0.50)
        "EquitySecuritiesFvNiUnrealizedGain",  # edgartools-expanded (conf=0.50)
        "EquitySecuritiesFvNiUnrealizedLoss",  # edgartools-expanded (conf=0.50)
        "EquitySecuritiesWithoutReadilyDeterminableFairValueDownwardPriceAdjustmentAnnualAmount",  # edgartools-expanded (conf=0.50)
        "EquitySecuritiesWithoutReadilyDeterminableFairValueUpwardPriceAdjustmentAnnualAmount",  # edgartools-expanded (conf=0.50)
        "ExtinguishmentOfDebtGainLossNetOfTax",  # edgartools-expanded (conf=0.50)
        "FairValueMeasurementWithUnobservableInputsReconciliationRecurringBasisLiabilityGainLossIncludedInEarnings",  # edgartools-expanded (conf=0.50)
        "ForeignCurrencyTransactionGainLossAfterTax",  # edgartools-expanded (conf=0.50)
        "ForeignCurrencyTransactionLossBeforeTax",  # edgartools-expanded (conf=0.50)
        "ForeignExchangeGain",  # edgartools-expanded (conf=0.50)
        "ForeignExchangeLoss",  # edgartools-expanded (conf=0.50)
        "GainLossFromComponentsExcludedFromAssessmentOfCashFlowHedgeEffectivenessNet",  # edgartools-expanded (conf=0.50)
        "GainLossFromPriceRiskManagementActivity",  # edgartools-expanded (conf=0.50)
        "GainLossOnCondemnation",  # edgartools-expanded (conf=0.50)
        "GainLossOnContractTermination",  # edgartools-expanded (conf=0.50)
        "GainLossOnDispositionOfIntangibleAssets",  # edgartools-expanded (conf=0.50)
        "GainLossOnDispositionOfRealEstateDiscontinuedOperations",  # edgartools-expanded (conf=0.50)
        "GainLossOnFairValueHedgesRecognizedInEarnings",  # edgartools-expanded (conf=0.50)
        "GainLossOnForeignCurrencyDerivativeInstrumentsNotDesignatedAsHedgingInstruments",  # edgartools-expanded (conf=0.50)
        "GainLossOnForeignCurrencyFairValueHedgeDerivatives",  # edgartools-expanded (conf=0.50)
        "GainLossOnInterestRateDerivativeInstrumentsNotDesignatedAsHedgingInstruments",  # edgartools-expanded (conf=0.50)
        "GainLossOnInvestmentsExcludingOtherThanTemporaryImpairments",  # edgartools-expanded (conf=0.50)
        "GainLossOnOilAndGasHedgingActivity",  # edgartools-expanded (conf=0.50)
        "GainLossOnRepurchaseOfDebtInstrument",  # edgartools-expanded (conf=0.50)
        "GainLossOnSaleOfAccountsReceivable",  # edgartools-expanded (conf=0.50)
        "GainLossOnSaleOfCommodityContracts",  # edgartools-expanded (conf=0.50)
        "GainLossOnSaleOfDebtInvestments",  # edgartools-expanded (conf=0.50)
        "GainLossOnSaleOfEquityInvestments",  # edgartools-expanded (conf=0.50)
        "GainLossOnSaleOfInterestInProjects",  # edgartools-expanded (conf=0.50)
        "GainLossOnSaleOfNotesReceivable",  # edgartools-expanded (conf=0.50)
        "GainLossOnSaleOfOtherAssets",  # edgartools-expanded (conf=0.50)
        "GainLossOnSaleOfPreviouslyUnissuedStockBySubsidiaryOrEquityInvesteeNonoperatingIncome",  # edgartools-expanded (conf=0.50)
        "GainLossOnSaleOfProperty",  # edgartools-expanded (conf=0.50)
        "GainLossOnSaleOfStockInSubsidiaryOrEquityMethodInvestee",  # edgartools-expanded (conf=0.50)
        "GainLossOnSecuritizationOfFinancialAssets",  # edgartools-expanded (conf=0.50)
        "GainLossRelatedToLitigationSettlement",  # edgartools-expanded (conf=0.50)
        "GainOnBusinessInterruptionInsuranceRecovery",  # edgartools-expanded (conf=0.50)
        "GainOnSaleOfInvestments",  # edgartools-expanded (conf=0.50)
        "GainOrLossOnSaleOfPreviouslyUnissuedStockByEquityInvestee",  # edgartools-expanded (conf=0.50)
        "GainOrLossOnSaleOfPreviouslyUnissuedStockBySubsidiary",  # edgartools-expanded (conf=0.50)
        "GainsLossesOnSalesOfInvestmentRealEstate",  # edgartools-expanded (conf=0.50)
        "IncomeLossFromSubsidiariesBeforeTax",  # edgartools-expanded (conf=0.50)
        "IncomeTaxReconciliationNondeductibleExpenseCharitableContributions",  # edgartools-expanded (conf=0.50)
        "IncreaseDecreaseInEquitySecuritiesFvNi",  # edgartools-expanded (conf=0.50)
        "InducedConversionOfConvertibleDebtExpense",  # edgartools-expanded (conf=0.50)
        "InsuranceRecoveries",  # edgartools-expanded (conf=0.50)
        "InterestRateCashFlowHedgeGainLossReclassifiedToEarningsNet",  # edgartools-expanded (conf=0.50)
        "InventoryRecallExpense",  # edgartools-expanded (conf=0.50)
        "InvestmentIncomeAmortizationOfPremium",  # edgartools-expanded (conf=0.50)
        "LegalFees",  # edgartools-expanded (conf=0.50)
        "LifeInsuranceCorporateOrBankOwnedChangeInValue",  # edgartools-expanded (conf=0.50)
        "LitigationSettlementExpense",  # edgartools-expanded (conf=0.50)
        "LitigationSettlementLoss",  # edgartools-expanded (conf=0.50)
        "LossContingencyAccrualProvision",  # edgartools-expanded (conf=0.50)
        "LossContingencyLossInPeriod",  # edgartools-expanded (conf=0.50)
        "LossFromCatastrophes",  # edgartools-expanded (conf=0.50)
        "LossOnDerivativeInstrumentsPretax",  # edgartools-expanded (conf=0.50)
        "NetForeignExchangeGain",  # edgartools-expanded (conf=0.50)
        "NetForeignExchangeLoss",  # edgartools-expanded (conf=0.50)
        "NonoperatingGainsLosses",  # edgartools-expanded (conf=0.50)
        "OtherGainsLosses",  # edgartools-expanded (conf=0.50)
        "OtherNonrecurringExpense",  # edgartools-expanded (conf=0.50)
        "OtherNonrecurringGain",  # edgartools-expanded (conf=0.50)
        "OtherNonrecurringIncome",  # edgartools-expanded (conf=0.50)
        "OtherThanTemporaryImpairmentLossesInvestmentsPortionRecognizedInEarningsNet",  # edgartools-expanded (conf=0.50)
        "ParticipatingSecuritiesDistributedAndUndistributedEarningsLossBasic",  # edgartools-expanded (conf=0.50)
        "ProceedsFromLegalSettlements",  # edgartools-expanded (conf=0.50)
        "ProfitLossFromRealEstateOperations",  # edgartools-expanded (conf=0.50)
        "RealizedGainLossOnMarketableSecuritiesCostMethodInvestmentsAndOtherInvestments",  # edgartools-expanded (conf=0.50)
        "ReclassificationFromAccumulatedOtherComprehensiveIncomeCurrentPeriodBeforeTax",  # edgartools-expanded (conf=0.50)
        "RelatedPartyTransactionExpensesFromTransactionsWithRelatedParty",  # edgartools-expanded (conf=0.50)
        "RoyaltyIncomeNonoperating",  # edgartools-expanded (conf=0.50)
        "SaleAndLeasebackTransactionGainLossNet",  # edgartools-expanded (conf=0.50)
        "UndistributedEarningsLossAllocatedToParticipatingSecuritiesDiluted",  # edgartools-expanded (conf=0.50)
        "UnrealizedGainLossOnEnergyContracts",  # edgartools-expanded (conf=0.50)
        "UnrealizedGainLossOnSecurities",  # edgartools-expanded (conf=0.50)
        "UnrealizedGainOnSecurities",  # edgartools-expanded (conf=0.50)
        "UnusualOrInfrequentItemGainGross",  # edgartools-expanded (conf=0.50)
        "UnusualOrInfrequentItemLossGross",  # edgartools-expanded (conf=0.50)
        "UnusualOrInfrequentItemNetGainLoss",  # edgartools-expanded (conf=0.50)
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
        # --- edgartools high-confidence ---
        "ProfitLossBeforeTax",  # edgartools-expanded (conf=0.97)
    ],
    
    "income_tax_expense": [
        # Standard (440 occurrences)
        "IncomeTaxExpenseBenefit",
        # Current vs deferred breakdown
        "CurrentIncomeTaxExpenseBenefit",
        "DeferredIncomeTaxExpenseBenefit",
        # --- edgartools high-confidence ---
        "IncomeTaxExpenseContinuingOperations",  # edgartools-expanded (conf=0.97)
        # --- edgartools lower-confidence ---
        "AdjustmentsToAdditionalPaidInCapitalTaxEffectFromShareBasedCompensation",  # edgartools-expanded (conf=0.50)
        "CurrentFederalStateAndLocalTaxExpenseBenefit",  # edgartools-expanded (conf=0.50)
        "CurrentFederalTaxExpenseBenefit",  # edgartools-expanded (conf=0.50)
        "CurrentForeignTaxExpenseBenefit",  # edgartools-expanded (conf=0.50)
        "CurrentStateAndLocalTaxExpenseBenefit",  # edgartools-expanded (conf=0.50)
        "DeferredFederalStateAndLocalTaxExpenseBenefit",  # edgartools-expanded (conf=0.50)
        "DeferredForeignIncomeTaxExpenseBenefit",  # edgartools-expanded (conf=0.50)
        "DeferredStateAndLocalIncomeTaxExpenseBenefit",  # edgartools-expanded (conf=0.50)
        "DeferredTaxExpenseIncome",  # edgartools-expanded (conf=0.50)
        "DeferredTaxExpenseIncomeRecognisedInProfitOrLoss",  # edgartools-expanded (conf=0.50)
        "EffectiveIncomeTaxRateReconciliationTaxCutsAndJobsActOf2017TransitionTaxOnAccumulatedForeignEarningsAmount",  # edgartools-expanded (conf=0.50)
        "EmployeeServiceShareBasedCompensationTaxBenefitFromCompensationExpense",  # edgartools-expanded (conf=0.50)
        "FederalIncomeTaxExpenseBenefitContinuingOperations",  # edgartools-expanded (conf=0.50)
        "FederalStateAndLocalIncomeTaxExpenseBenefitContinuingOperations",  # edgartools-expanded (conf=0.50)
        "ForeignIncomeTaxExpenseBenefitContinuingOperations",  # edgartools-expanded (conf=0.50)
        "IncomeTaxEffectsAllocatedDirectlyToEquity",  # edgartools-expanded (conf=0.50)
        "IncomeTaxEffectsAllocatedDirectlyToEquityEmployeeStockOptions",  # edgartools-expanded (conf=0.50)
        "IncomeTaxExpenseBenefitContinuingOperationsAdjustmentOfDeferredTaxAssetLiability",  # edgartools-expanded (conf=0.50)
        "IncomeTaxReconciliationDispositionOfAssets",  # edgartools-expanded (conf=0.50)
        "IncomeTaxReconciliationEquityInEarningsLossesOfUnconsolidatedSubsidiary",  # edgartools-expanded (conf=0.50)
        "IncomeTaxReconciliationNondeductibleExpenseShareBasedCompensationCost",  # edgartools-expanded (conf=0.50)
        "IncomeTaxReconciliationOtherReconcilingItems",  # edgartools-expanded (conf=0.50)
        "IncomeTaxReconciliationTaxContingencies",  # edgartools-expanded (conf=0.50)
        "IncomeTaxReconciliationTaxCreditsOther",  # edgartools-expanded (conf=0.50)
        "IncomeTaxReconciliationTaxCreditsResearch",  # edgartools-expanded (conf=0.50)
        "IncomeTaxReconciliationTaxSettlements",  # edgartools-expanded (conf=0.50)
        "OtherTaxExpenseBenefit",  # edgartools-expanded (conf=0.50)
        "StateAndLocalIncomeTaxExpenseBenefitContinuingOperations",  # edgartools-expanded (conf=0.50)
        "TaxAdjustmentsSettlementsAndUnusualProvisions",  # edgartools-expanded (conf=0.50)
        "TaxCutsAndJobsActOf2017IncomeTaxExpenseBenefit",  # edgartools-expanded (conf=0.50)
        "UnrecognizedTaxBenefitsIncomeTaxPenaltiesAndInterestExpense",  # edgartools-expanded (conf=0.50)
        "ValuationAllowanceDeferredTaxAssetChangeInAmount",  # edgartools-expanded (conf=0.50)
    ],
    
    # =============================================================================
    # NET INCOME SECTION
    # =============================================================================
    
    "net_income_continuing_ops": [
        # Income from continuing operations (before discontinued ops)
        "IncomeLossFromContinuingOperations",
        "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest",
        "NetIncomeLossFromContinuingOperations",
        # --- edgartools lower-confidence ---
        "ProfitLossFromContinuingOperations",  # edgartools-expanded (conf=0.50)
    ],
    
    "discontinued_operations": [
        # Gain/loss from discontinued operations
        "IncomeLossFromDiscontinuedOperationsNetOfTax",
        "IncomeLossFromDiscontinuedOperationsNetOfTaxAttributableToReportingEntity",
        "DiscontinuedOperationIncomeLossFromDiscontinuedOperationBeforeIncomeTax",
        "DisposalGroupIncludingDiscontinuedOperationGainLossOnDisposal",
        # --- edgartools lower-confidence ---
        "ProfitLossFromDiscontinuedOperations",  # edgartools-expanded (conf=0.50)
    ],
    
    "net_income": [
        # Most common (450 occurrences)
        "NetIncomeLoss",
        # Alternative (235 occurrences)
        "ProfitLoss",
        # Available to common — diluted variant only; basic kept in net_income_attributable_to_parent
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
        # --- edgartools lower-confidence ---
        "EquityMethodInvestmentOtherThanTemporaryImpairment",  # edgartools-expanded (conf=0.50)
        "IncomeLossFromContinuingOperationsAttributableToNoncontrollingEntity",  # edgartools-expanded (conf=0.50)
        "IncomeLossFromSubsidiariesNetOfTax",  # edgartools-expanded (conf=0.50)
        "NoncontrollingInterestInNetIncomeLossOtherNoncontrollingInterestsNonredeemable",  # edgartools-expanded (conf=0.50)
        "NoncontrollingInterestInNetIncomeLossOtherNoncontrollingInterestsRedeemable",  # edgartools-expanded (conf=0.50)
        "TemporaryEquityForeignCurrencyTranslationAdjustments",  # edgartools-expanded (conf=0.50)
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

