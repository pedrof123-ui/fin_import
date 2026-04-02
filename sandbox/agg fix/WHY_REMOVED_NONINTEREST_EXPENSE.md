# Why NoninterestExpense and OtherNoninterestExpense Were Removed

## The Question

Why add `NoninterestExpense` and `OtherNoninterestExpense` to the SG&A mapping?

**Answer: We shouldn't! They've been removed.**

## The Problem

### Issue 1: NoninterestExpense is the TOTAL

```
NoninterestExpense: $91.797B  ← This is the SUM
  ├─ LaborAndRelatedExpense: $51.357B
  ├─ OccupancyNet: $5.026B
  ├─ CommunicationsAndInformationTechnology: $9.831B
  ├─ ProfessionalAndContractServicesExpense: $11.057B
  ├─ MarketingAndAdvertisingExpense: $4.974B
  └─ OtherNoninterestExpense: $9.552B
```

**If we include both the total AND the components:**
- Risk of finding the total first → stops aggregation → misses breakdown
- OR risk of aggregating total + components → double counting

**Better approach:** Only include the **components**, not the total.

### Issue 2: OtherNoninterestExpense is a Catch-All

`OtherNoninterestExpense` ($9.552B) may include:
- ✗ One-time charges
- ✗ Restructuring costs (should be in separate field)
- ✗ Regulatory fines/settlements
- ✗ Non-operating items
- ✗ Miscellaneous non-recurring items

**These shouldn't be in SG&A** - they should be:
- Excluded (if non-operating)
- Captured in `other_operating_expenses` field
- Captured in `restructuring_charges` field

## The Solution

**Keep only specific, recurring operating expense components:**

✅ **LaborAndRelatedExpense** - Employee compensation
✅ **OccupancyNet** - Rent, facilities, real estate
✅ **CommunicationsAndInformationTechnology** - IT, telecom, software
✅ **ProfessionalAndContractServicesExpense** - Legal, consulting, audit
✅ **MarketingAndAdvertisingExpense** - Marketing (already in mapping)

❌ **NoninterestExpense** - REMOVED (it's the total)
❌ **OtherNoninterestExpense** - REMOVED (catch-all, may have non-operating items)

## Impact on JP Morgan

### What Gets Captured:
```
selling_general_admin will aggregate:
  + LaborAndRelatedExpense: $51.357B
  + OccupancyNet: $5.026B
  + CommunicationsAndInformationTechnology: $9.831B
  + ProfessionalAndContractServicesExpense: $11.057B
  + MarketingAndAdvertisingExpense: $4.974B
  ────────────────────────────────────────
  = Total: $82.245B
```

### What Doesn't Get Captured:
```
OtherNoninterestExpense: $9.552B
  ↓
Should be analyzed separately to determine if it's:
  - Restructuring charges → goes in restructuring_charges field
  - Other operating expenses → goes in other_operating_expenses field
  - Non-operating items → excluded or goes elsewhere
```

## Validation

We can validate our extraction:

```python
# From JPM's filing
reported_noninterest_expense = 91.797B

# What we capture in SG&A
our_sga_total = 82.245B

# Difference
difference = 91.797B - 82.245B = 9.552B

# This should equal OtherNoninterestExpense
assert difference == other_noninterest_expense  # $9.552B ✓
```

## Why This Is Better

### 1. **Avoids Double-Counting**
- If `NoninterestExpense` (total) came first in priority → we'd get $91.797B
- But if components came first → we'd aggregate to $91.797B
- Inconsistent depending on what XBRL tags the bank uses

### 2. **More Granular**
- We get the breakdown, not just the lump sum
- Can analyze what's in each component
- Better for ratio analysis (e.g., compensation as % of revenue)

### 3. **Cleaner SG&A**
- Excludes catch-all "Other" bucket
- Only recurring operating expenses
- More comparable across companies

### 4. **Proper Categorization**
- `OtherNoninterestExpense` can be examined separately
- One-time items go to appropriate fields
- Non-operating items excluded from SG&A

## What to Do with OtherNoninterestExpense?

You have options:

### Option 1: Map to other_operating_expenses
If it's truly operating expenses (just miscellaneous), add to mapping:

```python
"other_operating_expenses": [
    "OtherOperatingIncomeExpenseNet",
    "OtherCostAndExpenseOperating",
    "OtherNoninterestExpense",  # ← Add here for banks
    ...
]
```

### Option 2: Leave unmapped
Let it be analyzed manually to determine what's actually in there.

### Option 3: Create new field
If banks commonly report this and it's significant:

```python
"other_noninterest_expense": [
    "OtherNoninterestExpense",
]
```

**Recommendation:** Start with Option 2 (leave unmapped), then decide after analyzing what's actually in `OtherNoninterestExpense` for multiple banks.

## Final Mapping

**Banking SG&A concepts (4 new ones):**
1. LaborAndRelatedExpense
2. OccupancyNet
3. CommunicationsAndInformationTechnology
4. ProfessionalAndContractServicesExpense

Plus `MarketingAndAdvertisingExpense` which was already there.

**Total SG&A concepts:** 12 (was 14, removed 2)

## Testing

When you run JPM extraction now:

**Expected:**
```
✓ selling_general_admin: $82,245,000,000
  Concept: "LaborAndRelatedExpense + OccupancyNet + 
            CommunicationsAndInformationTechnology + 
            ProfessionalAndContractServicesExpense + 
            MarketingAndAdvertisingExpense"
```

**Not:**
```
✓ selling_general_admin: $91,797,000,000
  Concept: "NoninterestExpense"
```

The $9.552B difference is `OtherNoninterestExpense`, which should be analyzed separately.
