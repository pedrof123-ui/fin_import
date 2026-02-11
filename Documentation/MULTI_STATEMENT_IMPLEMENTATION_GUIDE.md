# Multi-Statement XBRL Mapping System - Implementation Guide

## Overview

This system scales from 1 ticker to 1,000+ tickers across **all three financial statements**:
- Income Statement (30 fields)
- Balance Sheet (40 fields)
- Cash Flow Statement (30 fields)

**Total: ~100 fields per company**

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  PYTHON MAPPING FILES (Core/Golden Concepts)            │
│  • income_statement_xbrl_mapping.py      (30 fields)    │
│  • balance_sheet_xbrl_mapping.py         (40 fields)    │
│  • cash_flow_xbrl_mapping.py             (30 fields)    │
│  • Version controlled, manually curated                 │
│  • ~5-10 concepts per field                             │
└─────────────────────────────────────────────────────────┘
                          ↓
                     FALLBACK TO
                          ↓
┌─────────────────────────────────────────────────────────┐
│  DUCKDB DATABASE (AI Discoveries & Analytics)           │
│  • xbrl_mappings.duckdb                                 │
│  • AI-discovered concepts (10,000+)                     │
│  • Company-specific overrides                           │
│  • Usage tracking & analytics                           │
│  • Auto-promotion to Python files                       │
└─────────────────────────────────────────────────────────┘
```

---

## Files Provided

### 1. Database Schema
**`xbrl_mapping_schema_multi_statement.sql`**
- Complete DuckDB schema for all 3 statements
- 9 core tables + 5 analytics views
- Statement relationships tracking
- Field definitions registry

### 2. Python Manager
**`xbrl_mapping_manager_multi_statement.py`**
- XBRLMappingManager class
- Methods for all 3 statements
- AI discovery logging
- Analytics and reporting
- Auto-promotion system

### 3. Mapping Files (Templates)
**`balance_sheet_xbrl_mapping_template.py`**
- 40 balance sheet fields
- Current/non-current assets
- Current/non-current liabilities
- Equity section

**`cash_flow_xbrl_mapping_template.py`**
- 30 cash flow fields
- Operating activities (indirect method)
- Investing activities
- Financing activities
- Supplemental disclosures

**`income_statement_xbrl_mapping.py`** (Already provided)
- 30 income statement fields

---

## Implementation Phases

### Phase 1: Setup (Week 1)
```bash
# 1. Install DuckDB
pip install duckdb

# 2. Initialize database
python xbrl_mapping_manager_multi_statement.py
# This creates xbrl_mappings.duckdb and syncs core mappings

# 3. Verify
# Should see: "✓ Synced XXX core concept mappings across all statements"
```

### Phase 2: Test with 10 Tickers (Week 2)
```python
from xbrl_mapping_manager_multi_statement import XBRLMappingManager

mapper = XBRLMappingManager('xbrl_mappings.duckdb')

# Test extraction for AAPL
tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 
           'META', 'NVDA', 'JPM', 'BAC', 'WMT']

for ticker in tickers:
    # Extract all 3 statements
    # ... extraction code ...
    
    # Log coverage
    await mapper.update_statement_coverage(
        ticker, filing_date, '10-K', 'income', fields_found, 30
    )
    await mapper.update_statement_coverage(
        ticker, filing_date, '10-K', 'balance', fields_found, 40
    )
    await mapper.update_statement_coverage(
        ticker, filing_date, '10-K', 'cashflow', fields_found, 30
    )

# Check health
health = await mapper.get_statement_health()
print(health)
```

### Phase 3: Scale to 100 Tickers (Week 3-4)
```python
# Run batch extraction
# AI discoveries will accumulate in DB

# Weekly: Check promotion candidates
candidates = await mapper.get_promotion_candidates(limit=20)

for c in candidates:
    print(f"{c['statement_type']}.{c['field_name']}: {c['concept']}")
    print(f"  Used {c['times_used']} times, {c['success_rate']:.1%} success")
    
    # Promote top performers
    if c['success_rate'] > 0.95 and c['times_used'] > 15:
        await mapper.promote_ai_to_core(
            c['statement_type'], c['field_name'], c['concept']
        )
```

### Phase 4: Production (1,000+ Tickers)
```python
# Automated weekly cron job
# 1. Extract all filings
# 2. Log to database
# 3. Auto-promote successful discoveries
# 4. Generate reports

# Monthly: Update Python mapping files
# Export promoted concepts to Python files
# Git commit and deploy
```

---

## Key Features by Scale

| Tickers | What to Use |
|---------|-------------|
| 1-10 | Python files only (fast, simple) |
| 10-100 | Python + DuckDB logging (start tracking) |
| 100-500 | Add AI auto-discovery (build knowledge) |
| 500-1,000 | Add company overrides (handle outliers) |
| 1,000+ | Full production (auto-promotion, analytics) |

---

## Database Tables Explained

### Core Tables

**1. `core_concept_mappings`**
- Golden standard mappings from Python files
- One row per (statement_type, field_name, concept)
- Priority ordering for each field

**2. `ai_discovered_mappings`**
- Concepts discovered by AI during extraction
- Tracks success/failure rates
- Auto-promotes when success_rate >= 90% and times_used >= 10

**3. `company_specific_mappings`**
- Overrides for outlier companies
- E.g., Tesla uses `tsla_AutomotiveRevenue` instead of standard `Revenues`

**4. `extraction_log`**
- Every extraction attempt logged
- Used for analytics and identifying difficult fields

**5. `statement_coverage_stats`**
- Per-filing coverage metrics
- Tracks data quality over time

**6. `field_definitions`**
- Central registry of all fields
- Display names, categories, sort order
- Marks required vs optional fields

**7. `statement_relationships`**
- Cross-statement validation
- E.g., net_income from income statement = starting point in cash flow

### Analytics Views

**`ai_promotion_candidates`**
```sql
SELECT * FROM ai_promotion_candidates
WHERE statement_type = 'balance'
LIMIT 10;
```

**`company_outliers_by_statement`**
```sql
SELECT * FROM company_outliers_by_statement
WHERE statement_type = 'income';
```

**`difficult_fields_by_statement`**
```sql
SELECT * FROM difficult_fields_by_statement
WHERE statement_type = 'cashflow'
ORDER BY success_rate_pct ASC;
```

---

## API Reference

### Get Concepts
```python
concepts = await mapper.get_concepts_for_field(
    ticker='AAPL',
    statement_type='income',  # or 'balance', 'cashflow'
    field_name='revenue',
    include_ai=True
)
# Returns: [('RevenueFromContract...', 'core'), ('Revenues', 'core'), ...]
```

### Log Extraction
```python
await mapper.log_extraction(
    ticker='AAPL',
    statement_type='balance',
    field_name='total_assets',
    concept='Assets',
    value=364980000000,
    success=True,
    filing_date=date(2024, 11, 1),
    period_end_date=date(2024, 9, 28),
    filing_type='10-K',
    source='core'
)
```

### Add AI Discovery
```python
await mapper.add_ai_discovery(
    ticker='TSLA',
    statement_type='cashflow',
    field_name='capital_expenditures',
    concept='tsla_PurchaseOfPropertyAndEquipment',
    value=10000000000,
    filing_date=date(2024, 1, 29)
)
```

### Get Quality Metrics
```python
# Overall quality for one company
quality = await mapper.get_overall_quality('AAPL')
print(f"Overall: {quality['overall_coverage']:.1f}%")
print(f"By statement: {quality['by_statement']}")

# System-wide health
health = await mapper.get_statement_health()
for stmt, metrics in health.items():
    print(f"{stmt}: {metrics['avg_coverage']:.1f}% avg")
```

### Find Difficult Fields
```python
difficult = await mapper.get_difficult_fields(
    statement_type='balance',
    min_attempts=10
)

for field in difficult:
    print(f"{field['field_name']}: {field['success_rate_pct']:.1f}%")
```

### Promote AI Discovery
```python
await mapper.promote_ai_to_core(
    statement_type='income',
    field_name='revenue',
    concept='tsla_AutomotiveRevenue'
)
```

---

## Analytics Queries

### Which concepts work for 90%+ of companies?
```sql
SELECT 
    statement_type,
    concept,
    COUNT(DISTINCT ticker) as companies
FROM extraction_log
WHERE success = true
GROUP BY statement_type, concept
HAVING COUNT(DISTINCT ticker) >= 900
ORDER BY companies DESC;
```

### Companies with low balance sheet coverage
```sql
SELECT 
    ticker,
    AVG(coverage_pct) as avg_coverage
FROM statement_coverage_stats
WHERE statement_type = 'balance'
GROUP BY ticker
HAVING AVG(coverage_pct) < 60
ORDER BY avg_coverage ASC;
```

### AI discoveries ready for promotion
```sql
SELECT * FROM ai_promotion_candidates
WHERE statement_type = 'cashflow'
ORDER BY success_rate DESC, times_used DESC
LIMIT 20;
```

---

## Performance Expectations

### At 1,000 Tickers (Annual Extraction)

**Total Extractions:**
- 1,000 tickers × 100 fields = 100,000 field extractions
- 3 statements per company = 3,000 statement extractions

**Lookup Performance:**
- Python dict (90% hit rate): 90,000 × 0.001s = 90 seconds
- DuckDB (10% hit rate): 10,000 × 0.005s = 50 seconds
- **Total: ~140 seconds for all lookups** ✅

**Database Size:**
- Core mappings: ~500 rows (small)
- AI discoveries: ~10,000 rows (medium)
- Extraction log: ~100,000 rows/year (manageable)
- **Total DB size: ~50-100 MB** ✅

**AI Auto-Discovery:**
- ~100 new concepts discovered per 100 tickers
- Auto-promote top 10-20 per month
- Manual review queue: ~50 pending concepts

---

## Best Practices

### 1. Start Simple
- Use Python files only for first 10-50 tickers
- Add DuckDB when you need analytics

### 2. Trust But Verify
- Review AI promotion candidates before promoting
- Check that concept actually maps to the field semantically

### 3. Handle Outliers
- Companies in different industries may use different concepts
- Add company-specific overrides when needed

### 4. Monitor Quality
- Run weekly quality reports
- Investigate companies with <50% coverage

### 5. Version Control
- Keep Python mapping files in Git
- DuckDB file in `.gitignore` (regenerate from Python files)

---

## Migration Path

### Current State (Income Only)
```python
# income_statement_xbrl_mapping.py
INCOME_STATEMENT_MAPPING = {
    'revenue': [...],
    'net_income': [...]
}
```

### Add Balance Sheet
```python
# balance_sheet_xbrl_mapping.py
BALANCE_SHEET_MAPPING = {
    'total_assets': [...],
    'total_liabilities': [...]
}
```

### Add Cash Flow
```python
# cash_flow_xbrl_mapping.py
CASH_FLOW_MAPPING = {
    'net_cash_operating_activities': [...],
    'capital_expenditures': [...]
}
```

### Initialize Multi-Statement DB
```python
mapper = XBRLMappingManager('xbrl_mappings.duckdb')
# Automatically syncs all 3 statement types
```

---

## Summary

✅ **For 1,000 tickers**: Use the hybrid system (Python + DuckDB)

✅ **Performance**: Fast enough for production (<3 minutes for 1,000 tickers)

✅ **Scalability**: Handles 10,000+ AI discoveries easily

✅ **Analytics**: Rich insights into data quality and concept usage

✅ **Auto-Learning**: AI discoveries auto-promote to core mappings

✅ **Multi-Statement**: All 3 financial statements in one system

**Start simple, scale when needed!** 🚀
