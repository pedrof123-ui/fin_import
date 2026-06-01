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
        # --- edgartools high-confidence ---
        "AvailableForSaleSecuritiesDebtSecurities",  # edgartools-expanded (conf=0.95)
        # --- edgartools lower-confidence ---
        "AvailableForSaleDebtSecuritiesAmortizedCostBasis",  # edgartools-expanded (conf=0.50)
        "AvailableForSaleSecuritiesAmortizedCost",  # edgartools-expanded (conf=0.50)
        "AvailableForSaleSecuritiesEquitySecuritiesCurrent",  # edgartools-expanded (conf=0.50)
        "CashAndBankBalancesAtCentralBanks",  # edgartools-expanded (conf=0.50)
        "CashAndCashEquivalentsFairValueDisclosure",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesAvailableForSaleAmortizedCostCurrent",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesAvailableForSaleExcludingAccruedInterest",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesHeldToMaturityAllowanceForCreditLossCurrent",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesHeldToMaturityAmortizedCostAfterAllowanceForCreditLoss",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesHeldToMaturityAmortizedCostAfterAllowanceForCreditLossCurrent",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesHeldToMaturityExcludingAccruedInterestAfterAllowanceForCreditLossCurrent",  # edgartools-expanded (conf=0.50)
        "DueFromBanks",  # edgartools-expanded (conf=0.50)
        "HeldToMaturitySecurities",  # edgartools-expanded (conf=0.50)
        "HeldToMaturitySecuritiesAccumulatedUnrecognizedHoldingGain",  # edgartools-expanded (conf=0.50)
        "HeldToMaturitySecuritiesAccumulatedUnrecognizedHoldingLoss",  # edgartools-expanded (conf=0.50)
        "HeldToMaturitySecuritiesCurrent",  # edgartools-expanded (conf=0.50)
        "HeldToMaturitySecuritiesFairValue",  # edgartools-expanded (conf=0.50)
        "MarketableSecurities",  # edgartools-expanded (conf=0.50)
        "MoneyMarketFundsAtCarryingValue",  # edgartools-expanded (conf=0.50)
        "OtherCashEquivalentsAtCarryingValue",  # edgartools-expanded (conf=0.50)
        "TradingSecuritiesEquity",  # edgartools-expanded (conf=0.50)
        "USGovernmentAgenciesSecuritiesAtCarryingValue",  # edgartools-expanded (conf=0.50)
    ],
    
    "short_term_investments": [
        "AvailableForSaleSecuritiesCurrent",
        "MarketableSecuritiesCurrent",
        "ShortTermInvestments",
        # --- edgartools lower-confidence ---
        "ShorttermInvestmentsClassifiedAsCashEquivalents",  # edgartools-expanded (conf=0.50)
    ],
    
    "accounts_receivable": [
        "AccountsReceivableNetCurrent",
        "AccountsReceivableNet",
        "ReceivablesNetCurrent",
        # --- edgartools lower-confidence ---
        "AccountsNotesAndLoansReceivableNetCurrent",  # edgartools-expanded (conf=0.50)
        "AccountsReceivableBilledForLongTermContractsOrPrograms",  # edgartools-expanded (conf=0.50)
        "AccountsReceivableFromSecuritization",  # edgartools-expanded (conf=0.50)
        "AccountsReceivableGross",  # edgartools-expanded (conf=0.50)
        "AllowanceForNotesAndLoansReceivableCurrent",  # edgartools-expanded (conf=0.50)
        "BilledContractReceivables",  # edgartools-expanded (conf=0.50)
        "ContractWithCustomerAssetAccumulatedAllowanceForCreditLoss",  # edgartools-expanded (conf=0.50)
        "ContractWithCustomerReceivableBeforeAllowanceForCreditLossCurrent",  # edgartools-expanded (conf=0.50)
        "ContractsReceivableClaimsAndUncertainAmounts",  # edgartools-expanded (conf=0.50)
        "TradeAndOtherCurrentReceivables",  # edgartools-expanded (conf=0.50)
        "UnbilledContractsReceivable",  # edgartools-expanded (conf=0.50)
    ],
    
    "inventory": [
        "InventoryNet",
        "Inventory",
        # --- edgartools lower-confidence ---
        "AgriculturalRelatedInventory",  # edgartools-expanded (conf=0.50)
        "AirlineRelatedInventory",  # edgartools-expanded (conf=0.50)
        "AirlineRelatedInventoryAircraftFuel",  # edgartools-expanded (conf=0.50)
        "AirlineRelatedInventoryAircraftParts",  # edgartools-expanded (conf=0.50)
        "CrudeOilAndNaturalGasLiquids",  # edgartools-expanded (conf=0.50)
        "EnergyRelatedInventory",  # edgartools-expanded (conf=0.50)
        "EnergyRelatedInventoryChemicals",  # edgartools-expanded (conf=0.50)
        "EnergyRelatedInventoryCoal",  # edgartools-expanded (conf=0.50)
        "EnergyRelatedInventoryGasStoredUnderground",  # edgartools-expanded (conf=0.50)
        "EnergyRelatedInventoryNaturalGasInStorage",  # edgartools-expanded (conf=0.50)
        "EnergyRelatedInventoryOtherFossilFuel",  # edgartools-expanded (conf=0.50)
        "EnergyRelatedInventoryPetroleum",  # edgartools-expanded (conf=0.50)
        "EnergyRelatedInventoryPropaneGas",  # edgartools-expanded (conf=0.50)
        "FIFOInventoryAmount",  # edgartools-expanded (conf=0.50)
        "InventoryAdjustments",  # edgartools-expanded (conf=0.50)
        "InventoryCrudeOilProductsAndMerchandise",  # edgartools-expanded (conf=0.50)
        "InventoryFinishedGoods",  # edgartools-expanded (conf=0.50)
        "InventoryFinishedGoodsAndWorkInProcess",  # edgartools-expanded (conf=0.50)
        "InventoryFinishedGoodsAndWorkInProcessNetOfReserves",  # edgartools-expanded (conf=0.50)
        "InventoryForLongTermContractsOrPrograms",  # edgartools-expanded (conf=0.50)
        "InventoryGross",  # edgartools-expanded (conf=0.50)
        "InventoryLIFOReserve",  # edgartools-expanded (conf=0.50)
        "InventoryNetOfAllowancesCustomerAdvancesAndProgressBillings",  # edgartools-expanded (conf=0.50)
        "InventoryOreStockpilesOnLeachPads",  # edgartools-expanded (conf=0.50)
        "InventoryPartsAndComponentsNetOfReserves",  # edgartools-expanded (conf=0.50)
        "InventoryRawMaterials",  # edgartools-expanded (conf=0.50)
        "InventoryRawMaterialsAndPurchasedPartsNetOfReserves",  # edgartools-expanded (conf=0.50)
        "InventoryRawMaterialsAndSuppliesNetOfReserves",  # edgartools-expanded (conf=0.50)
        "InventoryRawMaterialsNetOfReserves",  # edgartools-expanded (conf=0.50)
        "InventorySuppliesNetOfReserves",  # edgartools-expanded (conf=0.50)
        "InventoryValuationReserves",  # edgartools-expanded (conf=0.50)
        "InventoryWorkInProcess",  # edgartools-expanded (conf=0.50)
        "InventoryWorkInProcessAndRawMaterials",  # edgartools-expanded (conf=0.50)
        "InventoryWorkInProcessAndRawMaterialsNetOfReserves",  # edgartools-expanded (conf=0.50)
        "InventoryWorkInProcessNetOfReserves",  # edgartools-expanded (conf=0.50)
        "OtherInventoriesSpareParts",  # edgartools-expanded (conf=0.50)
        "OtherInventory",  # edgartools-expanded (conf=0.50)
        "OtherInventoryCapitalizedCosts",  # edgartools-expanded (conf=0.50)
        "OtherInventoryInTransit",  # edgartools-expanded (conf=0.50)
        "OtherInventoryNetOfReserves",  # edgartools-expanded (conf=0.50)
        "PropertySubjectToOrAvailableForOperatingLeaseAccumulatedDepreciation",  # edgartools-expanded (conf=0.50)
        "PropertySubjectToOrAvailableForOperatingLeaseNet",  # edgartools-expanded (conf=0.50)
        "RetailRelatedInventory",  # edgartools-expanded (conf=0.50)
        "WeightedAverageCostInventoryAmount",  # edgartools-expanded (conf=0.50)
    ],
    
    "prepaid_expenses": [
        "PrepaidExpenseAndOtherAssetsCurrent",
        "PrepaidExpenseCurrent",
        # --- edgartools lower-confidence ---
        "Prepayments",  # edgartools-expanded (conf=0.50)
    ],
    
    "other_current_assets": [
        "OtherAssetsCurrent",
        "DeferredTaxAssetsNetCurrent",
        # --- edgartools high-confidence ---
        "AssetsOfDisposalGroupIncludingDiscontinuedOperationCurrent",  # edgartools-expanded (conf=0.97)
        # --- edgartools lower-confidence ---
        "AccountsReceivableRelatedParties",  # edgartools-expanded (conf=0.50)
        "AdvanceRoyaltiesCurrent",  # edgartools-expanded (conf=0.50)
        "AllowanceForDoubtfulOtherReceivablesCurrent",  # edgartools-expanded (conf=0.50)
        "AmountOfDeferredCostsRelatedToLongTermContracts",  # edgartools-expanded (conf=0.50)
        "AssetsHeldForSaleNotPartOfDisposalGroupCurrentOther",  # edgartools-expanded (conf=0.50)
        "AssetsHeldInTrustCurrent",  # edgartools-expanded (conf=0.50)
        "AssetsOfDisposalGroupIncludingDiscontinuedOperation",  # edgartools-expanded (conf=0.50)
        "BusinessAcquisitionCostOfAcquiredEntityTransactionCosts",  # edgartools-expanded (conf=0.50)
        "BusinessCombinationContingentConsiderationAsset",  # edgartools-expanded (conf=0.50)
        "BusinessCombinationContingentConsiderationAssetCurrent",  # edgartools-expanded (conf=0.50)
        "BusinessCombinationIndemnificationAssetsAmountAsOfAcquisitionDate",  # edgartools-expanded (conf=0.50)
        "CapitalizedContractCostGross",  # edgartools-expanded (conf=0.50)
        "CapitalizedContractCostNet",  # edgartools-expanded (conf=0.50)
        "CapitalizedContractCostNetCurrent",  # edgartools-expanded (conf=0.50)
        "CommodityContractAssetCurrent",  # edgartools-expanded (conf=0.50)
        "ConstructionContractorReceivableRetainage",  # edgartools-expanded (conf=0.50)
        "ContractAssets",  # edgartools-expanded (conf=0.50)
        "ContractWithCustomerAssetAccumulatedAllowanceForCreditLossCurrent",  # edgartools-expanded (conf=0.50)
        "ContractWithCustomerAssetGrossCurrent",  # edgartools-expanded (conf=0.50)
        "CostsInExcessOfBillingsOnUncompletedContractsOrPrograms",  # edgartools-expanded (conf=0.50)
        "CostsInExcessOfBillingsOnUncompletedContractsOrProgramsExpectedToBeCollectedWithinOneYear",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesAvailableForSaleAccruedInterestAfterAllowanceForCreditLossCurrent",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesAvailableForSaleAmortizedCostExcludingAccruedInterestAfterAllowanceForCreditLossCurrent",  # edgartools-expanded (conf=0.50)
        "DeferredCostsAndOtherAssets",  # edgartools-expanded (conf=0.50)
        "DeferredCostsCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredCostsLeasingNetCurrent",  # edgartools-expanded (conf=0.50)
        "DeferredFinanceCostsGross",  # edgartools-expanded (conf=0.50)
        "DeferredFinanceCostsNet",  # edgartools-expanded (conf=0.50)
        "DeferredFuelCost",  # edgartools-expanded (conf=0.50)
        "DeferredGasCost",  # edgartools-expanded (conf=0.50)
        "DeferredOfferingCosts",  # edgartools-expanded (conf=0.50)
        "DeferredRentAssetNetCurrent",  # edgartools-expanded (conf=0.50)
        "DerivativeAssets",  # edgartools-expanded (conf=0.50)
        "DerivativeFairValueOfDerivativeAsset",  # edgartools-expanded (conf=0.50)
        "DerivativeLiabilityFairValueOfCollateral",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationAccountsNotesAndLoansReceivableNet",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationCash",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationCashAndCashEquivalents",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationIntangibleAssetsCurrent",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationInventory1",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationInventoryCurrent",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationOtherAssets",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationOtherCurrentAssets",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationPrepaidAndOtherAssetsCurrent",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationPropertyPlantAndEquipment",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationPropertyPlantAndEquipmentCurrent",  # edgartools-expanded (conf=0.50)
        "DueFromAffiliateCurrent",  # edgartools-expanded (conf=0.50)
        "DueFromEmployeesCurrent",  # edgartools-expanded (conf=0.50)
        "DueFromJointVenturesCurrent",  # edgartools-expanded (conf=0.50)
        "DueFromOfficersOrStockholdersCurrent",  # edgartools-expanded (conf=0.50)
        "DueFromOtherRelatedPartiesCurrent",  # edgartools-expanded (conf=0.50)
        "EscrowDeposit",  # edgartools-expanded (conf=0.50)
        "FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLossCurrent",  # edgartools-expanded (conf=0.50)
        "ForeignCurrencyContractAssetFairValueDisclosure",  # edgartools-expanded (conf=0.50)
        "GovernmentAssistanceAmountCumulativeCurrent",  # edgartools-expanded (conf=0.50)
        "GrantsReceivable",  # edgartools-expanded (conf=0.50)
        "GrantsReceivableCurrent",  # edgartools-expanded (conf=0.50)
        "HedgingAssetsCurrent",  # edgartools-expanded (conf=0.50)
        "InterestRateDerivativeAssetsAtFairValue",  # edgartools-expanded (conf=0.50)
        "InterestReceivableCurrent",  # edgartools-expanded (conf=0.50)
        "LandAvailableForSale",  # edgartools-expanded (conf=0.50)
        "LeaseIncentiveReceivableCurrent",  # edgartools-expanded (conf=0.50)
        "LossContingencyReceivable",  # edgartools-expanded (conf=0.50)
        "LossContingencyReceivableCurrent",  # edgartools-expanded (conf=0.50)
        "MarginDepositAssets",  # edgartools-expanded (conf=0.50)
        "MaterialsSuppliesAndOther",  # edgartools-expanded (conf=0.50)
        "NetInvestmentInLeaseCurrent",  # edgartools-expanded (conf=0.50)
        "NontradeReceivables",  # edgartools-expanded (conf=0.50)
        "NotesAndLoansReceivableGrossCurrent",  # edgartools-expanded (conf=0.50)
        "NotesReceivableGross",  # edgartools-expanded (conf=0.50)
        "NotesReceivableNet",  # edgartools-expanded (conf=0.50)
        "NotesReceivableRelatedPartiesCurrent",  # edgartools-expanded (conf=0.50)
        "OtherAssetsMiscellaneous",  # edgartools-expanded (conf=0.50)
        "OtherAssetsMiscellaneousCurrent",  # edgartools-expanded (conf=0.50)
        "OtherDeferredCostsNet",  # edgartools-expanded (conf=0.50)
        "OtherReceivablesGrossCurrent",  # edgartools-expanded (conf=0.50)
        "OtherRestrictedAssetsCurrent",  # edgartools-expanded (conf=0.50)
        "PledgedAssetsSeparatelyReportedOtherAssetsPledgedAsCollateralAtFairValue",  # edgartools-expanded (conf=0.50)
        "PrepaidAdvertising",  # edgartools-expanded (conf=0.50)
        "PrepaidInsurance",  # edgartools-expanded (conf=0.50)
        "PrepaidInterest",  # edgartools-expanded (conf=0.50)
        "PrepaidRent",  # edgartools-expanded (conf=0.50)
        "PrepaidRoyalties",  # edgartools-expanded (conf=0.50)
        "PrepaidTaxes",  # edgartools-expanded (conf=0.50)
        "ReinsuranceRecoverables",  # edgartools-expanded (conf=0.50)
        "ReinsuranceRecoverablesOnPaidLosses",  # edgartools-expanded (conf=0.50)
        "RelatedPartyTransactionDueFromToRelatedParty",  # edgartools-expanded (conf=0.50)
        "RelatedPartyTransactionDueFromToRelatedPartyCurrent",  # edgartools-expanded (conf=0.50)
        "RestrictedCashAndInvestments",  # edgartools-expanded (conf=0.50)
        "SalesTypeLeaseNetInvestmentInLeaseExcludingAccruedInterestAfterAllowanceForCreditLossCurrent",  # edgartools-expanded (conf=0.50)
        "SecuritiesForReverseRepurchaseAgreements",  # edgartools-expanded (conf=0.50)
        "TradeAndLoansReceivablesHeldForSaleNetNotPartOfDisposalGroup",  # edgartools-expanded (conf=0.50)
        "ValueAddedTaxReceivable",  # edgartools-expanded (conf=0.50)
        "ValueAddedTaxReceivableCurrent",  # edgartools-expanded (conf=0.50)
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
        # --- edgartools lower-confidence ---
        "AcquisitionCostsCumulative",  # edgartools-expanded (conf=0.50)
        "BuildingsAndImprovementsGross",  # edgartools-expanded (conf=0.50)
        "CapitalLeasedAssetsGross",  # edgartools-expanded (conf=0.50)
        "CapitalizedComputerSoftwareAccumulatedAmortization",  # edgartools-expanded (conf=0.50)
        "CapitalizedComputerSoftwareGross",  # edgartools-expanded (conf=0.50)
        "CapitalizedCostsOfUnprovedPropertiesExcludedFromAmortizationCumulative",  # edgartools-expanded (conf=0.50)
        "CapitalizedCostsSupportEquipmentAndFacilities",  # edgartools-expanded (conf=0.50)
        "CapitalizedCostsUnprovedProperties",  # edgartools-expanded (conf=0.50)
        "FinanceLeaseRightOfUseAssetBeforeAccumulatedAmortization",  # edgartools-expanded (conf=0.50)
        "FixturesAndEquipmentGross",  # edgartools-expanded (conf=0.50)
        "FlightEquipmentGross",  # edgartools-expanded (conf=0.50)
        "FurnitureAndFixturesGross",  # edgartools-expanded (conf=0.50)
        "LeaseholdImprovementsGross",  # edgartools-expanded (conf=0.50)
        "MachineryAndEquipmentGross",  # edgartools-expanded (conf=0.50)
        "MineralPropertiesGross",  # edgartools-expanded (conf=0.50)
        "OilAndGasPropertyFullCostMethodNet",  # edgartools-expanded (conf=0.50)
        "OilAndGasPropertySuccessfulEffortMethodAccumulatedDepreciationDepletionAmortizationAndImpairment",  # edgartools-expanded (conf=0.50)
        "OilAndGasPropertySuccessfulEffortMethodAccumulatedDepreciationDepletionAndAmortization",  # edgartools-expanded (conf=0.50)
        "OilAndGasPropertySuccessfulEffortMethodGross",  # edgartools-expanded (conf=0.50)
        "OilAndGasPropertySuccessfulEffortMethodNet",  # edgartools-expanded (conf=0.50)
        "OtherOilAndGasPropertySuccessfulEffortMethod",  # edgartools-expanded (conf=0.50)
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetBeforeAccumulatedDepreciationAndAmortization",  # edgartools-expanded (conf=0.50)
        "PropertyPlantAndEquipmentExcludingLessorAssetUnderOperatingLeaseAccumulatedDepreciation",  # edgartools-expanded (conf=0.50)
        "PropertyPlantAndEquipmentExcludingLessorAssetUnderOperatingLeaseAfterAccumulatedDepreciation",  # edgartools-expanded (conf=0.50)
        "PropertyPlantAndEquipmentNetExcludingCapitalLeasedAssets",  # edgartools-expanded (conf=0.50)
        "PropertyPlantAndEquipmentOtherAccumulatedDepreciation",  # edgartools-expanded (conf=0.50)
        "PropertyPlantAndEquipmentOtherNet",  # edgartools-expanded (conf=0.50)
        "PropertyPlantAndEquipmentOwnedAccumulatedDepreciation",  # edgartools-expanded (conf=0.50)
        "PropertySubjectToOrAvailableForOperatingLeaseGross",  # edgartools-expanded (conf=0.50)
        "TimberAndTimberlands",  # edgartools-expanded (conf=0.50)
        "UnprovedOilAndGasPropertySuccessfulEffortMethod",  # edgartools-expanded (conf=0.50)
    ],
    
    "ppe_gross": [
        "PropertyPlantAndEquipmentGross",
    ],
    
    "accumulated_depreciation": [
        "AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
    ],
    
    "goodwill": [
        "Goodwill",
        # --- edgartools lower-confidence ---
        "GoodwillGross",  # edgartools-expanded (conf=0.50)
        "GoodwillImpairedAccumulatedImpairmentLoss",  # edgartools-expanded (conf=0.50)
        "IndefiniteLivedContractualRights",  # edgartools-expanded (conf=0.50)
        "IndefiniteLivedFranchiseRights",  # edgartools-expanded (conf=0.50)
        "IndefiniteLivedTrademarks",  # edgartools-expanded (conf=0.50)
        "OtherIndefiniteLivedIntangibleAssets",  # edgartools-expanded (conf=0.50)
    ],
    
    "intangible_assets": [
        "IntangibleAssetsNetExcludingGoodwill",
        "FiniteLivedIntangibleAssetsNet",
        # --- edgartools lower-confidence ---
        "FiniteLivedCustomerListsGross",  # edgartools-expanded (conf=0.50)
        "FiniteLivedCustomerRelationshipsGross",  # edgartools-expanded (conf=0.50)
        "FiniteLivedIntangibleAssetOffMarketLeaseFavorableGross",  # edgartools-expanded (conf=0.50)
        "FiniteLivedNoncompeteAgreementsGross",  # edgartools-expanded (conf=0.50)
        "FiniteLivedPatentsGross",  # edgartools-expanded (conf=0.50)
        "FiniteLivedTradeNamesGross",  # edgartools-expanded (conf=0.50)
        "FiniteLivedTrademarksGross",  # edgartools-expanded (conf=0.50)
        "GoodwillAndIntangibleAssetsNet",  # edgartools-expanded (conf=0.50)
        "IntangibleAssetsGrossExcludingGoodwill",  # edgartools-expanded (conf=0.50)
        "IntangibleAssetsNetIncludingGoodwill",  # edgartools-expanded (conf=0.50)
        "OtherFiniteLivedIntangibleAssetsGross",  # edgartools-expanded (conf=0.50)
    ],
    
    "long_term_investments": [
        "AvailableForSaleSecuritiesNoncurrent",
        "LongTermInvestments",
        # --- edgartools lower-confidence ---
        "AdvancesToAffiliate",  # edgartools-expanded (conf=0.50)
        "AvailableForSaleSecuritiesEquitySecuritiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "CapitalLeasesLessorBalanceSheetNetInvestmentInDirectFinancingLeasesNoncurrent",  # edgartools-expanded (conf=0.50)
        "CostMethodInvestments",  # edgartools-expanded (conf=0.50)
        "CostMethodInvestmentsOriginalCost",  # edgartools-expanded (conf=0.50)
        "DerivativeAssetsLiabilitiesAtFairValueNet",  # edgartools-expanded (conf=0.50)
        "DerivativeInstrumentsNotDesignatedAsHedgingInstrumentsAssetAtFairValue",  # edgartools-expanded (conf=0.50)
        "EquityMethodInvestmentAggregateCost",  # edgartools-expanded (conf=0.50)
        "EquityMethodInvestmentQuotedMarketValue",  # edgartools-expanded (conf=0.50)
        "EquitySecuritiesFVNINoncurrent",  # edgartools-expanded (conf=0.50)
        "FinancialInstrumentsOwnedPrincipalInvestmentsAtFairValue",  # edgartools-expanded (conf=0.50)
        "HeldToMaturitySecuritiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "InventoryRealEstate",  # edgartools-expanded (conf=0.50)
        "InvestmentsInAffiliatesSubsidiariesAssociatesAndJointVenturesFairValueDisclosure",  # edgartools-expanded (conf=0.50)
        "InvestmentsInAndAdvancesToAffiliatesBalancePrincipalAmount",  # edgartools-expanded (conf=0.50)
        "LongTermInvestmentsAndReceivablesNet",  # edgartools-expanded (conf=0.50)
        "OtherInvestmentsAndSecuritiesAtCost",  # edgartools-expanded (conf=0.50)
        "RealEstateHeldForDevelopmentAndSale",  # edgartools-expanded (conf=0.50)
    ],
    
    "deferred_tax_assets": [
        "DeferredIncomeTaxAssetsNet",
        "DeferredTaxAssetsNetNoncurrent",
        # --- edgartools lower-confidence ---
        "DeferredIncomeTaxesAndOtherAssetsCurrent",  # edgartools-expanded (conf=0.50)
        "DeferredIncomeTaxesAndOtherAssetsNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredIncomeTaxesAndOtherTaxReceivableCurrent",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsCapitalLossCarryforwards",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsDeferredIncome",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsGross",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsGrossNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsInventory",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsLiabilitiesNet",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsLiabilitiesNetNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsNet",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsOperatingLossCarryforwards",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsOther",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsPropertyPlantAndEquipment",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsTaxCreditCarryforwards",  # edgartools-expanded (conf=0.50)
        "DeferredTaxAssetsTaxDeferredExpenseReservesAndAccruals",  # edgartools-expanded (conf=0.50)
        "IncomeTaxesReceivableNoncurrent",  # edgartools-expanded (conf=0.50)
    ],

    "other_noncurrent_assets": [
        "OtherAssetsNoncurrent",
        # ASC 842 operating lease right-of-use assets (mandatory post-2019)
        "OperatingLeaseRightOfUseAsset",
        "FinanceLeaseRightOfUseAsset",
        # --- edgartools high-confidence ---
        "AssetsHeldInTrustNoncurrent",  # edgartools-expanded (conf=0.97)
        "RestrictedCashNoncurrent",  # edgartools-expanded (conf=0.96)
        # --- edgartools lower-confidence ---
        "AccountsReceivableExcludingAccruedInterestAfterAllowanceForCreditLossNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccountsReceivableRelatedPartiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccruedFeesAndOtherRevenueReceivable",  # edgartools-expanded (conf=0.50)
        "AccumulatedAmortizationOfNoncurrentDeferredFinanceCosts",  # edgartools-expanded (conf=0.50)
        "AdvanceRoyaltiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "AllowanceForDoubtfulAccountsReceivableNoncurrent",  # edgartools-expanded (conf=0.50)
        "AllowanceForNotesAndLoansReceivableNoncurrent",  # edgartools-expanded (conf=0.50)
        "AmortizationMethodQualifiedAffordableHousingProjectInvestments",  # edgartools-expanded (conf=0.50)
        "AssetRecoveryDamagedPropertyCostsNoncurrent",  # edgartools-expanded (conf=0.50)
        "AssetsNoncurrentOtherThanNoncurrentInvestmentsAndPropertyPlantAndEquipment",  # edgartools-expanded (conf=0.50)
        "BusinessCombinationContingentConsiderationAssetNoncurrent",  # edgartools-expanded (conf=0.50)
        "CapitalLeasesBalanceSheetAssetsByMajorClassNet",  # edgartools-expanded (conf=0.50)
        "CapitalizedComputerSoftwareNet",  # edgartools-expanded (conf=0.50)
        "CashSurrenderValueFairValueDisclosure",  # edgartools-expanded (conf=0.50)
        "CashSurrenderValueOfLifeInsurance",  # edgartools-expanded (conf=0.50)
        "CommodityContractAssetNoncurrent",  # edgartools-expanded (conf=0.50)
        "ContractWithCustomerAssetGrossNoncurrent",  # edgartools-expanded (conf=0.50)
        "ContractWithCustomerReceivableBeforeAllowanceForCreditLossNoncurrent",  # edgartools-expanded (conf=0.50)
        "CreditCardReceivables",  # edgartools-expanded (conf=0.50)
        "DebtIssuanceCostsLineOfCreditArrangementsNet",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesAvailableForSaleAccruedInterestAfterAllowanceForCreditLossNoncurrent",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesAvailableForSaleAmortizedCostExcludingAccruedInterestAfterAllowanceForCreditLossNoncurrent",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesHeldToMaturityAmortizedCostAfterAllowanceForCreditLossNoncurrent",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesHeldToMaturityExcludingAccruedInterestAfterAllowanceForCreditLossNoncurrent",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "DecommissioningFundInvestments",  # edgartools-expanded (conf=0.50)
        "DeferredCostsLeasingNetNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredRentReceivablesNetNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredSalesCommission",  # edgartools-expanded (conf=0.50)
        "DeferredSalesInducementsNet",  # edgartools-expanded (conf=0.50)
        "DeferredSetUpCostsNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredSubscriberAcquisitionCostsNoncurrent",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanFairValueOfPlanAssets",  # edgartools-expanded (conf=0.50)
        "DerivativeInstrumentsAndHedgesNoncurrent",  # edgartools-expanded (conf=0.50)
        "DirectFinancingLeaseNetInvestmentInLeaseExcludingAccruedInterestAfterAllowanceForCreditLossNoncurrent",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationAccruedIncomeTaxPayableNoncurrent",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationDeferredTaxAssets",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationGoodwillNoncurrent",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationIntangibleAssetsNoncurrent",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationOtherNoncurrentAssets",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationPropertyPlantAndEquipmentNoncurrent",  # edgartools-expanded (conf=0.50)
        "DividendsReceivable",  # edgartools-expanded (conf=0.50)
        "DueFromAffiliateNoncurrent",  # edgartools-expanded (conf=0.50)
        "DueFromEmployeesNoncurrent",  # edgartools-expanded (conf=0.50)
        "DueFromJointVenturesNoncurrent",  # edgartools-expanded (conf=0.50)
        "DueFromOtherRelatedPartiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "EnergyMarketingContractsAssetsNoncurrent",  # edgartools-expanded (conf=0.50)
        "EquitySecuritiesFvNiRestricted",  # edgartools-expanded (conf=0.50)
        "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLossNoncurrent",  # edgartools-expanded (conf=0.50)
        "GovernmentAssistanceAmountCumulativeNoncurrent",  # edgartools-expanded (conf=0.50)
        "GrantsReceivableNoncurrent",  # edgartools-expanded (conf=0.50)
        "HedgingAssetsNoncurrent",  # edgartools-expanded (conf=0.50)
        "IncentiveToLessee",  # edgartools-expanded (conf=0.50)
        "InsuranceReceivableForMalpracticeNoncurrent",  # edgartools-expanded (conf=0.50)
        "InsuranceSettlementsReceivable",  # edgartools-expanded (conf=0.50)
        "InsuranceSettlementsReceivableNoncurrent",  # edgartools-expanded (conf=0.50)
        "InventoryLandHeldForSale",  # edgartools-expanded (conf=0.50)
        "InvestmentOwnedBalancePrincipalAmount",  # edgartools-expanded (conf=0.50)
        "LandAvailableForDevelopment",  # edgartools-expanded (conf=0.50)
        "LifeInsuranceCorporateOrBankOwnedAmount",  # edgartools-expanded (conf=0.50)
        "LifeSettlementContractsFairValueMethodCarryingAmount",  # edgartools-expanded (conf=0.50)
        "LoansAndLeasesReceivableRelatedParties",  # edgartools-expanded (conf=0.50)
        "LoansReceivableNet",  # edgartools-expanded (conf=0.50)
        "LossContingencyReceivableNoncurrent",  # edgartools-expanded (conf=0.50)
        "MembershipsInExchangesOwned",  # edgartools-expanded (conf=0.50)
        "NetInvestmentInLeaseExcludingAccruedInterestAfterAllowanceForCreditLossNoncurrent",  # edgartools-expanded (conf=0.50)
        "NetInvestmentInLeaseNoncurrent",  # edgartools-expanded (conf=0.50)
        "NontradeReceivablesNoncurrent",  # edgartools-expanded (conf=0.50)
        "NotesAndLoansReceivableGrossNoncurrent",  # edgartools-expanded (conf=0.50)
        "OilAndGasJointInterestBillingReceivables",  # edgartools-expanded (conf=0.50)
        "OtherInventoryNoncurrent",  # edgartools-expanded (conf=0.50)
        "OtherRestrictedAssetsNoncurrent",  # edgartools-expanded (conf=0.50)
        "PrepaidExpenseOtherNoncurrent",  # edgartools-expanded (conf=0.50)
        "PrepaidMineralRoyaltiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "PrepaidPensionCosts",  # edgartools-expanded (conf=0.50)
        "PreproductionCostsRelatedToLongTermSupplyArrangementsCostsCapitalized",  # edgartools-expanded (conf=0.50)
        "PropertyPlantAndEquipmentCollectionsNotCapitalized",  # edgartools-expanded (conf=0.50)
        "RegulatedEntityOtherAssetsNoncurrent",  # edgartools-expanded (conf=0.50)
        "RestrictedCashAndInvestmentsNoncurrent",  # edgartools-expanded (conf=0.50)
        "RestrictedCashEquivalentsNoncurrent",  # edgartools-expanded (conf=0.50)
        "SalesTypeLeaseNetInvestmentInLeaseExcludingAccruedInterestAfterAllowanceForCreditLossNoncurrent",  # edgartools-expanded (conf=0.50)
        "SecuritizedRegulatoryTransitionAssetsNoncurrent",  # edgartools-expanded (conf=0.50)
        "ValueAddedTaxReceivableNoncurrent",  # edgartools-expanded (conf=0.50)
    ],
    
    "total_noncurrent_assets": [
        "AssetsNoncurrent",
        # --- edgartools high-confidence ---
        "NoncurrentAssets",  # edgartools-expanded (conf=0.97)
    ],
    
    "total_assets": [
        "Assets",
        # --- edgartools lower-confidence ---
        "AssetsNet",  # edgartools-expanded (conf=0.50)
    ],
    
    # ============================================================================
    # CURRENT LIABILITIES
    # ============================================================================
    
    "accounts_payable": [
        "AccountsPayableCurrent",
        "AccountsPayable",
        # --- edgartools lower-confidence ---
        "AccountsPayableInterestBearingCurrent",  # edgartools-expanded (conf=0.50)
        "AccountsPayableTradeCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccountsPayableUnderwritersPromotersAndEmployeesOtherThanSalariesAndWagesCurrent",  # edgartools-expanded (conf=0.50)
        "AccruedParticipationLiabilitiesDueInNextOperatingCycle",  # edgartools-expanded (conf=0.50)
        "AccruedRoyaltiesCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "BusinessCombinationRecognizedIdentifiableAssetsAcquiredAndLiabilitiesAssumedCurrentLiabilitiesAccountsPayable",  # edgartools-expanded (conf=0.50)
        "CommissionsPayableToBrokerDealersAndClearingOrganizations",  # edgartools-expanded (conf=0.50)
        "ContractualObligation",  # edgartools-expanded (conf=0.50)
        "EnergyMarketingAccountsPayable",  # edgartools-expanded (conf=0.50)
        "GasImbalancePayableCurrent",  # edgartools-expanded (conf=0.50)
        "GasPurchasePayableCurrent",  # edgartools-expanded (conf=0.50)
        "OilAndGasSalesPayableCurrent",  # edgartools-expanded (conf=0.50)
        "ProgramRightsObligationsCurrent",  # edgartools-expanded (conf=0.50)
        "ReinsurancePayable",  # edgartools-expanded (conf=0.50)
        "SupplierFinanceProgramObligationCurrent",  # edgartools-expanded (conf=0.50)
    ],
    
    "short_term_debt": [
        "ShortTermBorrowings",
        "DebtCurrent",
        # --- edgartools lower-confidence ---
        "BankLoans",  # edgartools-expanded (conf=0.50)
        "BankOverdrafts",  # edgartools-expanded (conf=0.50)
        "BorrowingsUnderGuaranteedInvestmentAgreements",  # edgartools-expanded (conf=0.50)
        "BridgeLoan",  # edgartools-expanded (conf=0.50)
        "CapitalLeaseObligations",  # edgartools-expanded (conf=0.50)
        "CapitalLeaseObligationsCurrent",  # edgartools-expanded (conf=0.50)
        "CommercialPaper",  # edgartools-expanded (conf=0.50)
        "ConstructionLoan",  # edgartools-expanded (conf=0.50)
        "ConvertibleDebt",  # edgartools-expanded (conf=0.50)
        "ConvertibleSubordinatedDebtCurrent",  # edgartools-expanded (conf=0.50)
        "DebtInstrumentCarryingAmount",  # edgartools-expanded (conf=0.50)
        "DebtInstrumentFaceAmount",  # edgartools-expanded (conf=0.50)
        "DebtInstrumentIncreaseDecreaseForPeriodNet",  # edgartools-expanded (conf=0.50)
        "DebtInstrumentUnamortizedDiscountPremiumAndDebtIssuanceCostsNet",  # edgartools-expanded (conf=0.50)
        "DebtInstrumentUnamortizedPremium",  # edgartools-expanded (conf=0.50)
        "DebtLongtermAndShorttermCombinedAmount",  # edgartools-expanded (conf=0.50)
        "DeferredFinanceCostsCurrentGross",  # edgartools-expanded (conf=0.50)
        "FederalHomeLoanBankAdvancesCurrent",  # edgartools-expanded (conf=0.50)
        "JuniorSubordinatedNotesCurrent",  # edgartools-expanded (conf=0.50)
        "LineOfCreditFacilityFairValueOfAmountOutstanding",  # edgartools-expanded (conf=0.50)
        "LoansPayableToBankCurrent",  # edgartools-expanded (conf=0.50)
        "LongTermCommercialPaperCurrent",  # edgartools-expanded (conf=0.50)
        "LongTermConstructionLoanCurrent",  # edgartools-expanded (conf=0.50)
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",  # edgartools-expanded (conf=0.50)
        "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",  # edgartools-expanded (conf=0.50)
        "LongtermCommercialPaperCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "LongtermPollutionControlBondCurrent",  # edgartools-expanded (conf=0.50)
        "LongtermTransitionBondCurrent",  # edgartools-expanded (conf=0.50)
        "MediumtermNotesCurrent",  # edgartools-expanded (conf=0.50)
        "NotesAndLoansPayable",  # edgartools-expanded (conf=0.50)
        "NotesPayableToBankCurrent",  # edgartools-expanded (conf=0.50)
        "OtherLongTermDebtCurrent",  # edgartools-expanded (conf=0.50)
        "ShortTermBankLoansAndNotesPayable",  # edgartools-expanded (conf=0.50)
        "ShortTermNonBankLoansAndNotesPayable",  # edgartools-expanded (conf=0.50)
        "SubordinatedDebtCurrent",  # edgartools-expanded (conf=0.50)
    ],
    
    "current_portion_long_term_debt": [
        "LongTermDebtCurrent",
        # --- edgartools lower-confidence ---
        # Excluded from auto-expansion because it has industry_overrides; added manually.
        # Used by 366 companies (conf=0.50); standard_tag=CurrentPortionOfLongTermDebt.
        "LongTermDebtAndCapitalLeaseObligationsCurrent",  # edgartools-expanded (conf=0.50)
    ],
    
    "accrued_expenses": [
        "AccruedLiabilitiesCurrent",
        "EmployeeRelatedLiabilitiesCurrent",
    ],
    
    "deferred_revenue_current": [
        "DeferredRevenueCurrent",
        "ContractWithCustomerLiabilityCurrent",
        # --- edgartools lower-confidence ---
        "ContractLiabilities",  # edgartools-expanded (conf=0.50)
        "ContractWithCustomerRefundLiabilityCurrent",  # edgartools-expanded (conf=0.50)
        "DeferredIncomeIncludingContractLiabilities",  # edgartools-expanded (conf=0.50)
        "DeferredIncomeOtherThanContractLiabilities",  # edgartools-expanded (conf=0.50)
        "UnearnedRevenue",  # edgartools-expanded (conf=0.50)
    ],
    
    "other_current_liabilities": [
        "OtherLiabilitiesCurrent",
        "OperatingLeaseLiabilityCurrent",
        "FinanceLeaseLiabilityCurrent",
        # --- edgartools high-confidence ---
        "AccruedIncomeTaxesCurrent",  # edgartools-expanded (conf=0.97)
        "InterestPayableCurrent",  # edgartools-expanded (conf=1.00)
        "LiabilitiesOfDisposalGroupIncludingDiscontinuedOperationCurrent",  # edgartools-expanded (conf=0.97)
        # --- edgartools lower-confidence ---
        "AccrualForEnvironmentalLossContingencies",  # edgartools-expanded (conf=0.50)
        "AccrualForTaxesOtherThanIncomeTaxesCurrent",  # edgartools-expanded (conf=0.50)
        "AccrualForTaxesOtherThanIncomeTaxesCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccruedAdvertisingCurrent",  # edgartools-expanded (conf=0.50)
        "AccruedBonusesCurrent",  # edgartools-expanded (conf=0.50)
        "AccruedBonusesCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccruedCappingClosurePostClosureAndEnvironmentalCosts",  # edgartools-expanded (conf=0.50)
        "AccruedEmployeeBenefitsCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccruedEnvironmentalLossContingenciesCurrent",  # edgartools-expanded (conf=0.50)
        "AccruedExchangeFeeRebateCurrent",  # edgartools-expanded (conf=0.50)
        "AccruedInsuranceCurrent",  # edgartools-expanded (conf=0.50)
        "AccruedLiabilitiesForCommissionsExpenseAndTaxes",  # edgartools-expanded (conf=0.50)
        "AccruedMarketingCostsCurrent",  # edgartools-expanded (conf=0.50)
        "AccruedPayrollTaxesCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccruedProfessionalFeesCurrent",  # edgartools-expanded (conf=0.50)
        "AccruedProfessionalFeesCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccruedReclamationCostsCurrent",  # edgartools-expanded (conf=0.50)
        "AccruedRentCurrent",  # edgartools-expanded (conf=0.50)
        "AccruedRentCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccruedSalariesCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccruedSalesCommissionCurrent",  # edgartools-expanded (conf=0.50)
        "AccruedSalesCommissionCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccruedUtilitiesCurrent",  # edgartools-expanded (conf=0.50)
        "AccruedVacationCurrent",  # edgartools-expanded (conf=0.50)
        "AssetAcquisitionContingentConsiderationLiabilityCurrent",  # edgartools-expanded (conf=0.50)
        "AssetRetirementObligationCurrent",  # edgartools-expanded (conf=0.50)
        "BillingsInExcessOfCost",  # edgartools-expanded (conf=0.50)
        "BillingsInExcessOfCostCurrent",  # edgartools-expanded (conf=0.50)
        "BusinessCombinationContingentConsiderationLiability",  # edgartools-expanded (conf=0.50)
        "CashFlowHedgeDerivativeInstrumentLiabilitiesAtFairValue",  # edgartools-expanded (conf=0.50)
        "ConstructionPayableCurrent",  # edgartools-expanded (conf=0.50)
        "ConstructionPayableCurrentAndNoncurrent",  # edgartools-expanded (conf=0.50)
        "ContractWithCustomerRefundLiability",  # edgartools-expanded (conf=0.50)
        "CustomerAdvancesAndDeposits",  # edgartools-expanded (conf=0.50)
        "CustomerAdvancesAndDepositsCurrent",  # edgartools-expanded (conf=0.50)
        "CustomerDepositsCurrent",  # edgartools-expanded (conf=0.50)
        "CustomerFunds",  # edgartools-expanded (conf=0.50)
        "CustomerLoyaltyProgramLiabilityCurrent",  # edgartools-expanded (conf=0.50)
        "CustomerRefundLiabilityCurrent",  # edgartools-expanded (conf=0.50)
        "DeferredCreditsAndOtherLiabilities",  # edgartools-expanded (conf=0.50)
        "DeferredCreditsAndOtherLiabilitiesCurrent",  # edgartools-expanded (conf=0.50)
        "DeferredGainOnSaleOfProperty",  # edgartools-expanded (conf=0.50)
        "DeferredGasPurchasesCurrent",  # edgartools-expanded (conf=0.50)
        "DeferredRentCreditCurrent",  # edgartools-expanded (conf=0.50)
        "DeferredRevenueAndCredits",  # edgartools-expanded (conf=0.50)
        "DeferredRevenueAndCreditsCurrent",  # edgartools-expanded (conf=0.50)
        "DepositLiabilitiesAccruedInterest",  # edgartools-expanded (conf=0.50)
        "DepositsReceivedForSecuritiesLoanedAtCarryingValue",  # edgartools-expanded (conf=0.50)
        "DerivativeAssetFairValueOfCollateral",  # edgartools-expanded (conf=0.50)
        "DerivativeCollateralObligationToReturnCash",  # edgartools-expanded (conf=0.50)
        "DerivativeFairValueOfDerivativeLiability",  # edgartools-expanded (conf=0.50)
        "DerivativeLiabilities",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationAccountsPayable",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationAccountsPayableAndAccruedLiabilities",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationAccountsPayableAndAccruedLiabilitiesCurrent",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationAccountsPayableCurrent",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationAccruedLiabilities",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationAccruedLiabilitiesCurrent",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationDeferredRevenueCurrent",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationOtherCurrentLiabilities",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationOtherLiabilities",  # edgartools-expanded (conf=0.50)
        "DividendsPayableCurrent",  # edgartools-expanded (conf=0.50)
        "DueToAffiliateCurrent",  # edgartools-expanded (conf=0.50)
        "DueToEmployeesCurrent",  # edgartools-expanded (conf=0.50)
        "DueToOtherRelatedPartiesClassifiedCurrent",  # edgartools-expanded (conf=0.50)
        "EntertainmentLicenseAgreementForProgramMaterialLiabilityCurrent",  # edgartools-expanded (conf=0.50)
        "ExtendedProductWarrantyAccrual",  # edgartools-expanded (conf=0.50)
        "ExtendedProductWarrantyAccrualCurrent",  # edgartools-expanded (conf=0.50)
        "ForeignCurrencyContractsLiabilityFairValueDisclosure",  # edgartools-expanded (conf=0.50)
        "HedgingLiabilitiesCurrent",  # edgartools-expanded (conf=0.50)
        "InterestAndDividendsPayableCurrent",  # edgartools-expanded (conf=0.50)
        "InterestRateDerivativeLiabilitiesAtFairValue",  # edgartools-expanded (conf=0.50)
        "LeaseIncentivePayableCurrent",  # edgartools-expanded (conf=0.50)
        "LiabilitiesOfBusinessTransferredUnderContractualArrangementCurrent",  # edgartools-expanded (conf=0.50)
        "LiabilitiesOfDisposalGroupIncludingDiscontinuedOperation",  # edgartools-expanded (conf=0.50)
        "LiabilityForClaimsAndClaimsAdjustmentExpense",  # edgartools-expanded (conf=0.50)
        "LiabilityForUncertainTaxPositionsCurrent",  # edgartools-expanded (conf=0.50)
        "LitigationReserve",  # edgartools-expanded (conf=0.50)
        "LitigationReserveCurrent",  # edgartools-expanded (conf=0.50)
        "LossContingencyAccrualAtCarryingValue",  # edgartools-expanded (conf=0.50)
        "LossContingencyAccrualCarryingValueCurrent",  # edgartools-expanded (conf=0.50)
        "MandatorilyRedeemablePreferredStockFairValueDisclosure",  # edgartools-expanded (conf=0.50)
        "OtherEmployeeRelatedLiabilitiesCurrent",  # edgartools-expanded (conf=0.50)
        "OtherPayablesToBrokerDealersAndClearingOrganizations",  # edgartools-expanded (conf=0.50)
        "OtherSundryLiabilitiesCurrent",  # edgartools-expanded (conf=0.50)
        "ProductWarrantyAccrual",  # edgartools-expanded (conf=0.50)
        "ProductWarrantyAccrualClassifiedCurrent",  # edgartools-expanded (conf=0.50)
        "ProvisionForLossOnContracts",  # edgartools-expanded (conf=0.50)
        "RestructuringReserve",  # edgartools-expanded (conf=0.50)
        "RestructuringReserveCurrent",  # edgartools-expanded (conf=0.50)
        "RevenueRemainingPerformanceObligation",  # edgartools-expanded (conf=0.50)
        "SecuritiesLoaned",  # edgartools-expanded (conf=0.50)
        "StandardProductWarrantyAccrualCurrent",  # edgartools-expanded (conf=0.50)
        "ValuationAllowancesAndReservesBalance",  # edgartools-expanded (conf=0.50)
    ],
    
    "total_current_liabilities": [
        "LiabilitiesCurrent",
        # --- edgartools high-confidence ---
        "CurrentLiabilities",  # edgartools-expanded (conf=0.98)
    ],
    
    # ============================================================================
    # NON-CURRENT LIABILITIES
    # ============================================================================
    
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        # --- edgartools lower-confidence ---
        "CapitalLeaseObligationsNoncurrent",  # edgartools-expanded (conf=0.50)
        "CommercialPaperNoncurrent",  # edgartools-expanded (conf=0.50)
        "ConstructionLoanNoncurrent",  # edgartools-expanded (conf=0.50)
        "ConvertibleSubordinatedDebtNoncurrent",  # edgartools-expanded (conf=0.50)
        "DebtInstrumentUnamortizedDiscountPremiumNet",  # edgartools-expanded (conf=0.50)
        "DebtInstrumentUnamortizedPremiumNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredFinanceCostsNoncurrentGross",  # edgartools-expanded (conf=0.50)
        "InterestRateFairValueHedgeLiabilityAtFairValue",  # edgartools-expanded (conf=0.50)
        "JuniorSubordinatedDebentureOwedToUnconsolidatedSubsidiaryTrustNoncurrent",  # edgartools-expanded (conf=0.50)
        "JuniorSubordinatedLongTermNotes",  # edgartools-expanded (conf=0.50)
        "LongTermPollutionControlBond",  # edgartools-expanded (conf=0.50)
        "LongTermTransitionBond",  # edgartools-expanded (conf=0.50)
        "LongtermFederalHomeLoanBankAdvancesNoncurrent",  # edgartools-expanded (conf=0.50)
        "MediumTermNotes",  # edgartools-expanded (conf=0.50)
        "MediumtermNotesNoncurrent",  # edgartools-expanded (conf=0.50)
        "NotesPayableToBank",  # edgartools-expanded (conf=0.50)
        "NotesPayableToBankNoncurrent",  # edgartools-expanded (conf=0.50)
        "OtherLoansPayableLongTerm",  # edgartools-expanded (conf=0.50)
        "OtherLongTermNotesPayable",  # edgartools-expanded (conf=0.50)
        "SpecialAssessmentBondNoncurrent",  # edgartools-expanded (conf=0.50)
        "SubordinatedLongTermDebt",  # edgartools-expanded (conf=0.50)
        "TransfersAccountedForAsSecuredBorrowingsAssociatedLiabilitiesCarryingAmount",  # edgartools-expanded (conf=0.50)
        "UnamortizedLossReacquiredDebtNoncurrent",  # edgartools-expanded (conf=0.50)
        "UnsecuredLongTermDebt",  # edgartools-expanded (conf=0.50)
    ],
    
    "deferred_tax_liabilities": [
        "DeferredTaxLiabilitiesNoncurrent",
        # --- edgartools lower-confidence ---
        "AccumulatedDeferredInvestmentTaxCredit",  # edgartools-expanded (conf=0.50)
        "DeferredIncomeTaxLiabilities",  # edgartools-expanded (conf=0.50)
        "DeferredIncomeTaxesAndOtherLiabilitiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredTaxLiabilities",  # edgartools-expanded (conf=0.50)
        "DeferredTaxLiabilitiesCurrent",  # edgartools-expanded (conf=0.50)
        "DeferredTaxLiabilitiesDeferredExpense",  # edgartools-expanded (conf=0.50)
        "DeferredTaxLiabilitiesDeferredExpenseCapitalizedPatentCosts",  # edgartools-expanded (conf=0.50)
        "DeferredTaxLiabilitiesDerivatives",  # edgartools-expanded (conf=0.50)
        "DeferredTaxLiabilitiesGoodwillAndIntangibleAssets",  # edgartools-expanded (conf=0.50)
        "DeferredTaxLiabilitiesGoodwillAndIntangibleAssetsIntangibleAssets",  # edgartools-expanded (conf=0.50)
        "DeferredTaxLiabilitiesOther",  # edgartools-expanded (conf=0.50)
        "DeferredTaxLiabilitiesPrepaidExpenses",  # edgartools-expanded (conf=0.50)
        "DeferredTaxLiabilitiesTaxDeferredIncome",  # edgartools-expanded (conf=0.50)
        "IncomeTaxExaminationLiabilityRefundAdjustmentFromSettlementWithTaxingAuthority",  # edgartools-expanded (conf=0.50)
        "TaxCutsAndJobsActOf2017TransitionTaxForAccumulatedForeignEarningsLiabilityNoncurrent",  # edgartools-expanded (conf=0.50)
    ],
    
    "deferred_revenue_noncurrent": [
        "DeferredRevenueNoncurrent",
        "ContractWithCustomerLiabilityNoncurrent",
    ],
    
    "other_noncurrent_liabilities": [
        "OtherLiabilitiesNoncurrent",
        "OperatingLeaseLiabilityNoncurrent",
        "FinanceLeaseLiabilityNoncurrent",
        # --- edgartools lower-confidence ---
        "AccountsPayableInterestBearingNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccountsPayableRelatedPartiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccruedEnvironmentalLossContingenciesNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccruedInsuranceNoncurrent",  # edgartools-expanded (conf=0.50)
        "AccruedRentNoncurrent",  # edgartools-expanded (conf=0.50)
        "AssetAcquisitionContingentConsiderationLiabilityNoncurrent",  # edgartools-expanded (conf=0.50)
        "AssetRetirementObligationsNoncurrent",  # edgartools-expanded (conf=0.50)
        "CededPremiumsPayable",  # edgartools-expanded (conf=0.50)
        "DeferredCompensationCashbasedArrangementsLiabilityClassifiedNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredCompensationLiabilityClassifiedNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredCompensationSharebasedArrangementsLiabilityClassifiedNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredCreditsAndOtherLiabilitiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "DeferredRentCreditNoncurrent",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanBenefitObligation",  # edgartools-expanded (conf=0.50)
        "DerivativeAssetFairValueGrossLiability",  # edgartools-expanded (conf=0.50)
        "DerivativeInstrumentsAndHedgesLiabilitiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "DiscontinuedOperationAmountsOfMaterialContingentLiabilitiesRemaining",  # edgartools-expanded (conf=0.50)
        "DisposalGroupIncludingDiscontinuedOperationDeferredTaxLiabilities",  # edgartools-expanded (conf=0.50)
        "DueToAffiliateNoncurrent",  # edgartools-expanded (conf=0.50)
        "DueToEmployeesNoncurrent",  # edgartools-expanded (conf=0.50)
        "DueToOfficersOrStockholdersNoncurrent",  # edgartools-expanded (conf=0.50)
        "DueToOtherRelatedPartiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "EnergyMarketingContractLiabilitiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "GuaranteeObligationsCurrentCarryingValue",  # edgartools-expanded (conf=0.50)
        "GuarantyLiabilities",  # edgartools-expanded (conf=0.50)
        "HedgingLiabilitiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "IncentiveFromLessor",  # edgartools-expanded (conf=0.50)
        "IncomeTaxExaminationPenaltiesAndInterestAccrued",  # edgartools-expanded (conf=0.50)
        "LeaseDepositLiability",  # edgartools-expanded (conf=0.50)
        "LiabilitiesOfBusinessTransferredUnderContractualArrangementNoncurrent",  # edgartools-expanded (conf=0.50)
        "LiabilitiesOtherThanLongtermDebtNoncurrent",  # edgartools-expanded (conf=0.50)
        "LiabilitiesSubjectToCompromise",  # edgartools-expanded (conf=0.50)
        "LossContingencyAccrualCarryingValueNoncurrent",  # edgartools-expanded (conf=0.50)
        "OffMarketLeaseUnfavorable",  # edgartools-expanded (conf=0.50)
        "OperatingLeaseLiabilityStatementOfFinancialPositionExtensibleList",  # edgartools-expanded (conf=0.50)
        "OtherLiabilitiesAndDeferredRevenueNoncurrent",  # edgartools-expanded (conf=0.50)
        "OtherSundryLiabilitiesNoncurrent",  # edgartools-expanded (conf=0.50)
        "ProgramRightsObligationsNoncurrent",  # edgartools-expanded (conf=0.50)
        "QualifiedAffordableHousingProjectInvestmentsCommitment",  # edgartools-expanded (conf=0.50)
        "SaleLeasebackTransactionDeferredGainNet",  # edgartools-expanded (conf=0.50)
        "SelfInsuranceReserveNoncurrent",  # edgartools-expanded (conf=0.50)
        "WorkersCompensationLiabilityNoncurrent",  # edgartools-expanded (conf=0.50)
    ],
    
    "total_noncurrent_liabilities": [
        "LiabilitiesNoncurrent",
        # --- edgartools high-confidence ---
        "NoncurrentLiabilities",  # edgartools-expanded (conf=0.97)
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
        # --- edgartools high-confidence ---
        "TreasuryStockCommonShares",  # edgartools-expanded (conf=0.99)
        "TreasuryStockShares",  # edgartools-expanded (conf=0.96)
        # --- edgartools lower-confidence ---
        "TreasuryShares",  # edgartools-expanded (conf=0.50)
    ],
    
    "accumulated_other_comprehensive_income": [
        "AccumulatedOtherComprehensiveIncomeLossNetOfTax",
        "AOCI",
        # --- edgartools lower-confidence ---
        "AccumulatedOtherComprehensiveIncomeLossCumulativeChangesInNetGainLossFromCashFlowHedgesEffectNetOfTax",  # edgartools-expanded (conf=0.50)
        "AccumulatedOtherComprehensiveIncomeLossDefinedBenefitPensionAndOtherPostretirementPlansNetOfTax",  # edgartools-expanded (conf=0.50)
    ],
    
    "noncontrolling_interest": [
        "MinorityInterest",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        # --- edgartools lower-confidence ---
        "MinorityInterestInJointVentures",  # edgartools-expanded (conf=0.50)
        "MinorityInterestInOperatingPartnerships",  # edgartools-expanded (conf=0.50)
        "NoncontrollingInterestInVariableInterestEntity",  # edgartools-expanded (conf=0.50)
        "NonredeemableNoncontrollingInterest",  # edgartools-expanded (conf=0.50)
        "OtherMinorityInterests",  # edgartools-expanded (conf=0.50)
        "PartnersCapitalAttributableToNoncontrollingInterest",  # edgartools-expanded (conf=0.50)
    ],
    
    "total_equity": [
        "StockholdersEquity",
        "Equity",
        # --- edgartools high-confidence ---
        "TreasuryStockCommonValue",  # edgartools-expanded (conf=0.98)
        # --- edgartools lower-confidence ---
        "AociBeforeTaxAttributableToParent",  # edgartools-expanded (conf=0.50)
        "AociDerivativeQualifyingAsHedgeExcludedComponentAfterTax",  # edgartools-expanded (conf=0.50)
        "AociIncludingPortionAttributableToNoncontrollingInterestTax",  # edgartools-expanded (conf=0.50)
        "AociLossCashFlowHedgeCumulativeGainLossAfterTax",  # edgartools-expanded (conf=0.50)
        "CommonStockHeldBySubsidiary",  # edgartools-expanded (conf=0.50)
        "CommonStockHeldInTrust",  # edgartools-expanded (conf=0.50)
        "CommonStockIssuedEmployeeStockTrust",  # edgartools-expanded (conf=0.50)
        "CommonStockIssuedEmployeeTrustDeferred",  # edgartools-expanded (conf=0.50)
        "CommonStockShareSubscribedButUnissuedSubscriptionsReceivable",  # edgartools-expanded (conf=0.50)
        "CommonStockSharesHeldInEmployeeTrust",  # edgartools-expanded (conf=0.50)
        "CommonStocksIncludingAdditionalPaidInCapital",  # edgartools-expanded (conf=0.50)
        "CommonStocksIncludingAdditionalPaidInCapitalNetOfDiscount",  # edgartools-expanded (conf=0.50)
        "CompensationAndBenefitsTrust",  # edgartools-expanded (conf=0.50)
        "DebtSecuritiesAvailableForSaleAccumulatedGrossUnrealizedGainLossBeforeTax",  # edgartools-expanded (conf=0.50)
        "DeferredCompensationEquity",  # edgartools-expanded (conf=0.50)
        "DefinedBenefitPlanAccumulatedOtherComprehensiveIncomeNetPriorServiceCostCreditAfterTax",  # edgartools-expanded (conf=0.50)
        "EquityAttributableToOwnersOfParent",  # edgartools-expanded (conf=0.50)
        "LimitedLiabilityCompanyLlcMembersEquityIncludingPortionAttributableToNoncontrollingInterest",  # edgartools-expanded (conf=0.50)
        "OtherAdditionalCapital",  # edgartools-expanded (conf=0.50)
        "PartnersCapital",  # edgartools-expanded (conf=0.50)
        "PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest",  # edgartools-expanded (conf=0.50)
        "ReceivableFromOfficersAndDirectorsForIssuanceOfCapitalStock",  # edgartools-expanded (conf=0.50)
        "ReceivableFromShareholdersOrAffiliatesForIssuanceOfCapitalStock",  # edgartools-expanded (conf=0.50)
        "ReclassificationFromAociCurrentPeriodNetOfTaxAttributableToParent",  # edgartools-expanded (conf=0.50)
        "RetainedEarningsAppropriated",  # edgartools-expanded (conf=0.50)
        "RetainedEarningsUnappropriated",  # edgartools-expanded (conf=0.50)
        "StockholdersEquityBeforeTreasuryStock",  # edgartools-expanded (conf=0.50)
        "TreasuryStockDeferredEmployeeStockOwnershipPlan",  # edgartools-expanded (conf=0.50)
        "UnearnedESOPShares",  # edgartools-expanded (conf=0.50)
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
