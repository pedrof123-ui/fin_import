# XBRL Income Statement Mapping - Documentation

## Overview

This mapping file contains **148 XBRL concept variations** across **30 income statement fields**, based on analysis of **100+ companies** from actual SEC EDGAR 10-K and 10-Q filings.

## Key Statistics

- **Total fields mapped**: 30 essential income statement line items
- **Total concept variations**: 148 different XBRL concepts
- **Unique concepts**: 144 (some concepts appear in multiple fields)
- **Average variations per field**: 4.9
- **Coverage**: Handles differences across industries (Tech, Retail, Banking, Insurance, Manufacturing, etc.)

## Major Changes from Original Mapping

### ✅ Added (New Concepts Found in Real Data)

1. **Revenue alternatives**:
   - `RevenueNotFromContractWithCustomer` (GM Financial)
   - `PremiumsEarnedNet` (Insurance companies)
   - `NoninterestIncome` (Banks)

2. **Cost of revenue**:
   - `CostsAndExpenses` (154 occurrences - some companies combine COGS + OpEx)
   - `OperatingCostsAndExpenses`
   - Company-specific: Broadcom's separate product vs. subscription costs

3. **New expense categories**:
   - `depreciation_amortization` (was missing - critical for EBITDA!)
   - `restructuring_charges` (71 occurrences)
   - `other_operating_expenses` (labor, occupancy, fulfillment, etc.)

4. **Interest variations**:
   - `InterestExpenseNonoperating` (184 occurrences - most common!)
   - `InterestExpenseOperating` (58 occurrences - banking)
   - Separate concepts for different debt types

5. **Investment income**:
   - `equity_method_investments` (94 occurrences)
   - `investment_gains_losses` (securities, crypto)

6. **Comprehensive income components** (optional but useful)

### 🔄 Reorganized

1. **Clearer structure**: Organized by income statement flow (top to bottom)
2. **Frequency-based ordering**: Most common concepts listed first
3. **Industry grouping**: Insurance, banking, tech concepts grouped together
4. **Company-specific concepts**: Marked with prefixes (e.g., `gm_`, `tsla_`, `avgo_`)

### ❌ Removed

Nothing removed - all original concepts kept, just reorganized

## Field Mapping Details

### Top Fields by Variation Count

| Field | Variations | Most Common Concept | Occurrences |
|-------|-----------|-------------------|-------------|
| `revenue` | 14 | `RevenueFromContractWithCustomerExcludingAssessedTax` | 245 |
| `cost_of_revenue` | 10 | `CostOfGoodsAndServicesSold` | 253 |
| `other_nonoperating_income` | 10 | `OtherNonoperatingIncomeExpense` | 271 |
| `selling_general_admin` | 8 | `SellingGeneralAndAdministrativeExpense` | 244 |
| `other_operating_expenses` | 8 | `OtherOperatingIncomeExpenseNet` | 50 |
| `operating_income` | 6 | `OperatingIncomeLoss` | 341 |
| `pretax_income` | 6 | `IncomeLossFromContinuingOperationsBeforeIncomeTaxes...` | 367 |

## Usage Examples

### Basic Usage

```python
from income_statement_xbrl_mapping import INCOME_STATEMENT_MAPPING, get_concepts_with_prefix

# Get concepts to try for revenue (with prefix)
revenue_concepts = get_concepts_with_prefix('revenue')

# Try each concept in order
for concept in revenue_concepts:
    rows = xbrl_df[xbrl_df['concept'] == concept]
    if not rows.empty:
        revenue = rows.iloc[0][year_column]
        break
```

### Integration with Extractor

```python
from income_statement_xbrl_mapping import INCOME_STATEMENT_MAPPING

class XBRLExtractor:
    def __init__(self):
        self.mapping = INCOME_STATEMENT_MAPPING
    
    def extract_value(self, xbrl_df, field_name, year_col):
        # Filter main items
        main_items = xbrl_df[
            (xbrl_df['dimension'] == False) & 
            (xbrl_df['abstract'] == False)
        ]
        
        # Try each concept for this field
        concepts = self.mapping.get(field_name, [])
        
        for concept in concepts:
            # Add us-gaap_ prefix if not company-specific
            if '_' not in concept or concept.startswith('us-gaap'):
                full_concept = f"us-gaap_{concept}"
            else:
                full_concept = concept
            
            rows = main_items[main_items['concept'] == full_concept]
            if not rows.empty and year_col in rows.columns:
                value = rows.iloc[0][year_col]
                if pd.notna(value):
                    return float(value)
        
        return None
```

### Industry-Specific Extraction

```python
# For insurance companies, revenue might be premiums
insurance_revenue_concepts = [
    'us-gaap_PremiumsEarnedNet',
    'us-gaap_NetInvestmentIncome',
    'us-gaap_InsuranceCommissionsAndFees',
]

# For banks, revenue might be interest income
banking_revenue_concepts = [
    'us-gaap_InterestAndDividendIncomeOperating',
    'us-gaap_NoninterestIncome',
]

# The mapping includes these automatically in the revenue field
```

## Industry Coverage

### Technology Companies
- Apple, Microsoft, Tesla, Broadcom, Adobe, PayPal
- Specific concepts: subscription revenue, technology development expenses

### Automotive
- GM, Tesla
- Specific concepts: automotive vs. financial services revenue

### Retail
- Lowe's, Kimberly-Clark, American Eagle
- Specific concepts: fulfillment expenses, occupancy costs

### Financial Services
- Bank of NY, Capital One, PNC, Comerica
- Specific concepts: interest income/expense, noninterest income/expense

### Insurance
- Lemonade, Allstate, Elevance Health
- Specific concepts: premiums earned, claims expenses

### Manufacturing/Industrial
- Corning, Air Products, J&J
- Specific concepts: labor costs, research expenses

## Company-Specific Concepts

### Format: `{ticker}_{ConceptName}`

Examples:
- `gm_IncomeLossFromEquityMethodInvestmentsLessIncomeFromOperationalJointVenture` (GM)
- `tsla_RestructuringAndOtherExpenses` (Tesla)
- `avgo_CostofProductsSold` (Broadcom)
- `amzn_FulfillmentExpense` (Amazon)
- `lmnd_OtherInsuranceExpense` (Lemonade)
- `adm_InterestAndInvestmentIncome` (ADM)

**Important**: These concepts are preserved in the mapping and will be tried automatically.

## Critical Fields for Financial Analysis

### For DCF Valuation
1. ✅ `revenue` - Top line
2. ✅ `operating_income` - EBIT
3. ✅ `depreciation_amortization` - For EBITDA
4. ✅ `income_tax_expense` - For tax rate
5. ✅ `net_income` - Bottom line
6. ✅ `diluted_shares` - For per-share calculations

### For Ratio Analysis
1. ✅ `gross_profit` - Gross margin
2. ✅ `operating_income` - Operating margin
3. ✅ `interest_expense` - Interest coverage
4. ✅ `pretax_income` - Effective tax rate
5. ✅ `net_income` - Net margin, ROE, ROA

## Best Practices

### 1. Always Use Priority Order
```python
# GOOD - tries most common first
for concept in INCOME_STATEMENT_MAPPING['revenue']:
    # Try to find value
    ...

# BAD - random order
concepts = set(INCOME_STATEMENT_MAPPING['revenue'])
for concept in concepts:  # Order not guaranteed
    ...
```

### 2. Handle Missing Concepts Gracefully
```python
# GOOD - returns None if not found
value = extract_value(xbrl_df, 'revenue', year_col)
if value is None:
    print(f"Warning: Revenue not found for {company}")
    data_quality_score -= 0.1

# BAD - assumes concept exists
value = xbrl_df[xbrl_df['concept'] == 'us-gaap_Revenues'][year_col]  # May fail
```

### 3. Log Which Concept Was Used
```python
# GOOD - track for debugging
for i, concept in enumerate(concepts):
    value = try_extract(concept)
    if value is not None:
        metadata['revenue_concept'] = concept
        metadata['revenue_priority'] = i + 1
        break

# Helps identify companies using unusual concepts
```

### 4. Validate Calculated Fields
```python
# GOOD - verify gross profit
if revenue and cost_of_revenue and gross_profit:
    calculated = revenue - cost_of_revenue
    if abs(calculated - gross_profit) / gross_profit > 0.02:
        print(f"Warning: Gross profit mismatch for {company}")
```

## Known Issues & Edge Cases

### 1. Combined Expense Lines
Some companies report `CostsAndExpenses` which includes both COGS and operating expenses.
**Solution**: If this is found, you may need to calculate COGS by subtracting operating expenses.

### 2. Banking/Insurance Different Structure
Financial services don't have traditional "revenue" or "COGS".
**Solution**: The mapping includes industry-specific alternatives (premiums, interest income).

### 3. Discontinued Operations
Some companies report continuing vs. discontinued operations separately.
**Solution**: Mapping includes both `net_income_continuing_ops` and `discontinued_operations`.

### 4. Noncontrolling Interests
Parent vs. total net income can differ.
**Solution**: Mapping includes both `net_income` (total) and `net_income_attributable_to_parent`.

## Updating the Mapping

As you encounter new companies with different concepts:

1. **Identify the concept**: Look at the XBRL filing
2. **Determine the field**: Which database field does it map to?
3. **Add to mapping**: Insert in priority order (common concepts first)
4. **Test**: Verify it extracts correctly
5. **Document**: Add comment with company ticker

Example:
```python
"revenue": [
    "RevenueFromContractWithCustomerExcludingAssessedTax",  # Most common
    "Revenues",  # Second most common
    "NewConceptDiscovered",  # NEW - found in XYZ company
    # ... rest
]
```

## Integration with Database

This mapping feeds into the PostgreSQL schema:

```sql
-- Database field names match mapping keys
CREATE TABLE income_statement (
    revenue NUMERIC(20, 2),                    -- Maps to 'revenue'
    cost_of_revenue NUMERIC(20, 2),           -- Maps to 'cost_of_revenue'
    gross_profit NUMERIC(20, 2),              -- Maps to 'gross_profit'
    research_development NUMERIC(20, 2),      -- Maps to 'research_development'
    selling_general_admin NUMERIC(20, 2),     -- Maps to 'selling_general_admin'
    depreciation_amortization NUMERIC(20, 2), -- Maps to 'depreciation_amortization'
    operating_income NUMERIC(20, 2),          -- Maps to 'operating_income'
    -- ... etc
);
```

## Testing Recommendations

1. **Test on diverse companies**: Tech, retail, banking, insurance, manufacturing
2. **Check data quality scores**: Should be >0.8 for good extractions
3. **Validate relationships**: Revenue - COGS = Gross Profit
4. **Compare to SEC filings**: Spot-check against published 10-Ks
5. **Monitor unmapped concepts**: Log concepts that aren't being caught

## Performance Notes

- **Extraction speed**: O(n × m) where n = fields, m = avg concepts per field (~5)
- **For 5,000 companies**: ~30-60 seconds total extraction time
- **Optimization**: Stop searching when concept found (don't try all variations)

## Support & Contributions

When you find new concepts:
1. Add them to the mapping
2. Document which company uses them
3. Note the frequency if you track it
4. Keep the priority order (common first)

## Version History

- **v1.0** (2025-01-30): Initial comprehensive mapping based on 100+ companies
  - 30 fields
  - 148 concept variations
  - Coverage: All major industries

---

**Next Steps**: 
1. Use this mapping with `financial_statement_extractor.py`
2. Test on your 5,000 company dataset
3. Monitor data quality scores
4. Add new concepts as discovered
