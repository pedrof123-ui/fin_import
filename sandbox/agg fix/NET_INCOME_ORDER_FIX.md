# Net Income Order Fix

## The Change

**Before:** Net income attributable to NCI came AFTER net income attributable to parent
**After:** Net income attributable to NCI comes BEFORE net income attributable to parent

## Why This Matters

The correct flow on an income statement is:

```
Income before taxes                                   $120,000
Less: Income tax expense                              (20,000)
                                                      ─────────
Net income (including noncontrolling interests)       $100,000  ← Total net income

Less: Net income attributable to noncontrolling        (5,000)  ← Subtract NCI portion
      interests
                                                      ─────────
Net income attributable to [Company Name]             $95,000  ← Parent's share
                                                      ═════════
```

## The Correct Order

### Field Extraction Order:

1. **`net_income_continuing_ops`** - Net income from continuing operations (before discontinued)
2. **`discontinued_operations`** - Gain/loss from discontinued operations
3. **`net_income`** - Total net income (including NCI)
4. **`net_income_attributable_to_nci`** - **Portion belonging to noncontrolling interests** ← Comes BEFORE parent!
5. **`net_income_attributable_to_parent`** - Net income attributable to parent shareholders

### Why This Order?

**This is the reconciliation:**
```python
net_income_attributable_to_parent = net_income - net_income_attributable_to_nci
```

You need to know:
1. Total net income first
2. Then subtract NCI portion
3. To get parent's net income

## Real Example: Tesla

```
INCOME STATEMENT - TESLA
======================================================================

Income before income taxes                            $11,176M
Provision for income taxes                            (1,490)M
                                                      ─────────
Net income                                            $9,686M   ← Field #20

Net income (loss) attributable to noncontrolling       ($15)M  ← Field #21 (SUBTRACT)
interests and redeemable noncontrolling interests
                                                      ─────────
Net income attributable to common stockholders        $9,701M   ← Field #22 (RESULT)
                                                      ═════════

Earnings per share:
  Basic                                               $3.25
  Diluted                                             $3.12
```

## Output Format

When you run the extractor, it will now show in this order:

```
NET INCOME:
Status  Field                              Value              Concept
✓       pretax_income                      $11,176,000,000    IncomeLossFromContinuing...
✓       income_tax_expense                 $1,490,000,000     IncomeTaxExpenseBenefit
✓       net_income_continuing_ops          $9,686,000,000     IncomeLossFromContinuing...
✗       discontinued_operations            Not Found
✓       net_income                         $9,686,000,000     NetIncomeLoss
✓       net_income_attributable_to_nci     -$15,000,000      NetIncomeLossAttributable...  ← BEFORE parent
✓       net_income_attributable_to_parent  $9,701,000,000     NetIncomeLossAttributable...  ← AFTER NCI

PER SHARE DATA:
✓       basic_eps                          $3.25              EarningsPerShareBasic
✓       diluted_eps                        $3.12              EarningsPerShareDiluted
```

## Validation

The order also helps with validation:

```python
# Check: Net Income - NCI = Parent Net Income
if all fields present:
    calculated_parent = net_income - net_income_attributable_to_nci
    reported_parent = net_income_attributable_to_parent
    
    if abs(calculated_parent - reported_parent) < tolerance:
        print("✓ PASS - NCI Reconciliation")
```

## Database Schema (Unchanged)

The database table order doesn't need to change - it's just the extraction order:

```sql
CREATE TABLE income_statement (
    -- ... other fields ...
    
    net_income NUMERIC(20, 2),
    net_income_attributable_to_nci NUMERIC(20, 2),
    net_income_attributable_to_parent NUMERIC(20, 2),
    
    -- ... per share fields ...
);
```

But now when you display or analyze the data, the logical flow is correct.

## Companies That Report NCI

Not all companies have noncontrolling interests. These typically do:

- **Subsidiaries not 100% owned** - Parent owns 51-99%
- **Joint ventures** - Consolidated but partners have minority stake
- **Recent acquisitions** - Acquired majority but not all shares

Examples:
- Tesla (has some subsidiaries with NCI)
- General Motors (various international JVs)
- Banks (sometimes have minority stakes in consolidated entities)

## What If NCI Is Not Found?

Many companies don't have NCI. That's fine:

```
✓       net_income                         $100,000,000       NetIncomeLoss
✗       net_income_attributable_to_nci     Not Found          
✓       net_income_attributable_to_parent  $100,000,000       NetIncomeLossAttributable...
```

In this case:
```python
net_income == net_income_attributable_to_parent  # Because no NCI
```

## Technical Note

The change was made in `income_statement_xbrl_mapping.py`:

```python
INCOME_STATEMENT_MAPPING = {
    # ... revenue, expenses, etc. ...
    
    "net_income": [...],                          # Field 20
    "net_income_attributable_to_nci": [...],      # Field 21 ← Moved here
    "net_income_attributable_to_parent": [...],   # Field 22 ← After NCI
    
    # ... per share data ...
}
```

Since Python dicts maintain insertion order (Python 3.7+), the extraction loop processes fields in this order.

## Summary

✅ **Changed:** `net_income_attributable_to_nci` now comes BEFORE `net_income_attributable_to_parent`

✅ **Why:** Matches standard income statement flow: Total NI → Less NCI → Parent NI

✅ **Impact:** Better readability, correct logical flow, easier validation

✅ **Database:** No schema changes needed, just extraction/display order
