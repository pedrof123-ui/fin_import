---
name: verify-sec-edgar
description: Verify downloaded SEC Edgar filing data matches the source filing for accuracy. Use when validating income statement downloads, checking XBRL data extraction, or when the user mentions verification, validation, or accuracy of SEC data.
---

# Verify SEC Edgar Filing Data

## Purpose

Verify that downloaded income statement data accurately matches the source SEC Edgar filing. Focus on value accuracy and data integrity.

## When to Use

- After downloading income statement data via edgartools
- When user requests verification of SEC data
- Before using data for financial analysis
- When troubleshooting data discrepancies

## Verification Workflow

### Step 1: Identify Source Filing

Collect filing metadata:
- Ticker symbol
- Form type (10-K or 10-Q)
- Fiscal period (year/quarter)
- Filing date
- Accession number

**Access source:** Visit `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=[TICKER]`

### Step 2: Locate Source Financial Statement

1. Find the specific filing in Edgar
2. Open the **complete filing** (HTML or XBRL viewer)
3. Navigate to "Consolidated Statements of Income" or equivalent
4. Note the exact statement title used by the company

### Step 3: Verify Critical Line Items

Compare downloaded values against source for these key items:

**Revenue Section:**
- Total Revenue / Net Sales
- Cost of Revenue / COGS
- Gross Profit (verify calculation)

**Operating Section:**
- Operating Expenses (R&D, SG&A)
- Operating Income / EBIT

**Bottom Line:**
- Pretax Income / EBT
- Income Tax Expense
- Net Income
- Net Income Attributable to Common Shareholders

**Per Share:**
- Diluted EPS
- Diluted Weighted Average Shares Outstanding

### Step 4: Check for Common Issues

**Value mismatches:**
- Unit scaling (thousands vs millions)
- Sign conventions (expenses as positive vs negative)
- Parent vs subsidiary attribution

**Missing items:**
- Company uses non-standard labels
- Line items nested under "Other"
- Discontinued operations separately reported

**Period mismatches:**
- YTD vs quarterly values
- Restated prior periods
- Fiscal vs calendar year differences

### Step 5: Document Findings

Generate a verification report (see template below).

## Verification Report Template

Use this structure for your verification report:

```markdown
# SEC Filing Verification Report

## Filing Information
- **Company:** [Company Name] ([Ticker])
- **Form Type:** [10-K / 10-Q]
- **Fiscal Period:** [Year / Quarter]
- **Filing Date:** [Date]
- **Accession Number:** [SEC Accession Number]
- **Source URL:** [Edgar URL]

## Verification Status
- **Overall Status:** [PASS / FAIL / PARTIAL]
- **Date Verified:** [Today's date]
- **Verified By:** [Your name or "Automated"]

## Line Item Verification

| Line Item | Source Value | Downloaded Value | Status | Notes |
|-----------|--------------|------------------|--------|-------|
| Revenue | $X,XXX | $X,XXX | ✓ PASS | |
| COGS | $X,XXX | $X,XXX | ✓ PASS | |
| Gross Profit | $X,XXX | $X,XXX | ✓ PASS | |
| Operating Income | $X,XXX | $X,XXX | ✗ FAIL | Off by $XXX |
| Net Income | $X,XXX | $X,XXX | ✓ PASS | |
| Diluted EPS | $X.XX | $X.XX | ✓ PASS | |

## Issues Found

### Critical Issues
- [Description of any critical mismatches]

### Warnings
- [Description of any concerns or non-critical issues]

### Missing Data
- [List any required line items not found in download]

## Calculation Verification

Verify key calculations:
- [ ] Gross Profit = Revenue - COGS
- [ ] Operating Income = Gross Profit - Operating Expenses
- [ ] Net Income = Pretax Income - Tax Expense
- [ ] Diluted EPS = Net Income / Diluted Shares

## Recommendations

[Based on findings, recommend next steps:]
- Re-download with different parameters
- Manual adjustment needed
- Data quality acceptable for use
- Investigate specific line items

## Conclusion

[One-paragraph summary of verification outcome and data quality assessment]
```

## Tips for Accurate Verification

**Unit Consistency:**
All values in source SEC filings are typically in thousands or millions. Check the header note: "In thousands, except per share data" or similar.

**Negative Values:**
Some companies report expenses as positive, others as negative. Be consistent with your convention.

**Label Matching:**
SEC filers use different terminology:
- "Net Sales" vs "Revenue" vs "Total Revenue"
- "Cost of Sales" vs "Cost of Revenue" vs "COGS"
- "Income Before Taxes" vs "Pretax Income" vs "EBT"

**Multi-Period Statements:**
Ensure you're comparing the correct column (current year vs prior year).

**Amended Filings:**
Check if an amended filing (10-K/A or 10-Q/A) supersedes the original.

## Edgar Resources

**Human-readable filing:**
`https://www.sec.gov/cgi-bin/viewer?action=view&cik=[CIK]&accession_number=[ACCESSION]&xbrl_type=v`

**XBRL instance document:**
Use edgartools to access programmatically or download directly from filing documents.

## Common Verification Scenarios

### Scenario 1: Values Don't Match
1. Check unit scaling (thousands vs millions)
2. Verify correct fiscal period
3. Check for restatements in footnotes
4. Confirm using most recent filing version

### Scenario 2: Missing Line Items
1. Check alternative labels in XBRL taxonomy
2. Look for items aggregated under "Other"
3. Review notes for discontinued operations
4. Verify item exists in this period (may be zero or N/A)

### Scenario 3: Calculation Doesn't Foot
1. Check for rounding differences
2. Look for subtotals vs totals
3. Review non-controlling interests
4. Check for extraordinary items

## Success Criteria

Verification passes when:
- ✓ All critical line items match source (within rounding)
- ✓ Calculations reconcile
- ✓ Metadata (period, ticker, date) is correct
- ✓ No unexplained variances > 0.1%

## Next Steps After Verification

**If PASS:** Proceed with financial analysis

**If FAIL:** 
1. Re-download data
2. Check edgartools version and parameters
3. Review XBRL mapping logic
4. Document known limitations

**If PARTIAL:**
1. Document which items failed
2. Manual correction if variance is small
3. Flag for review before critical use
