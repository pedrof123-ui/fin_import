# Bulk 10-K Import - Usage Guide

## 🎯 Overview

Automatically download and import up to 20 years of 10-K statements for multiple companies from SEC EDGAR into your DuckDB database.

**Key Features:**
- ✅ Processes multiple companies from CSV
- ✅ Downloads last N years of 10-K filings
- ✅ Handles missing statements gracefully
- ✅ Comprehensive logging
- ✅ Progress tracking
- ✅ Automatic retry logic
- ✅ Rate limiting (be nice to SEC)
- ✅ Skip existing filings
- ✅ Detailed reports

---

## 📋 Quick Start

### **Step 1: Create Ticker CSV**

Create a file `tickers.csv` with your companies:

**Option A: Simple (just tickers)**
```csv
ticker
AAPL
MSFT
GOOGL
META
TSLA
AMZN
NVDA
JPM
V
WMT
```

**Option B: With metadata (optional)**
```csv
ticker,company_name,sector
AAPL,Apple Inc,Technology
MSFT,Microsoft Corp,Technology
GOOGL,Alphabet Inc,Technology
META,Meta Platforms,Technology
TSLA,Tesla Inc,Automotive
```

---

### **Step 2: Run Bulk Import**

```python
import asyncio
from bulk_import_10k import bulk_import_10k

# Run bulk import
results = asyncio.run(bulk_import_10k(
    ticker_csv='tickers.csv',
    periods=20,                              # Last 20 years
    db_path='financial_statements.duckdb',
    use_ai_fallback=False,                   # Set True for better coverage
    skip_existing=True,                      # Skip already-imported filings
    rate_limit_delay=1.0                     # 1 second between requests
))
```

---

### **Step 3: Review Results**

Check the `bulk_import_results/` directory for:
- `summary_report.csv` - Overview by ticker
- `detailed_log.csv` - Line-by-line status
- `failures.csv` - What failed (if any)
- `overall_statistics.txt` - Summary stats

---

## 📊 Expected Output

```
================================================================================
BULK 10-K IMPORT
================================================================================

📋 Reading tickers from tickers.csv...
✓ Found 10 tickers

💾 Connecting to database: financial_statements.duckdb...
✓ Connected to financial statements database
✓ Database schema created/verified

🚀 Starting bulk extraction...
   Rate limit: 1.0s between requests
   AI fallback: Disabled
   Skip existing: Yes

[1/10] Processing AAPL...
--------------------------------------------------------------------------------
2024-02-10 14:23:01 | INFO    | [AAPL] Retrieved company: Apple Inc
2024-02-10 14:23:02 | INFO    | [AAPL] Found 25 10-K filings
2024-02-10 14:23:05 | SUCCESS | [AAPL 2024] Income statement: 86.7% coverage
2024-02-10 14:23:06 | SUCCESS | [AAPL 2024] Balance sheet: 92.1% coverage
2024-02-10 14:23:07 | SUCCESS | [AAPL 2024] Cash flow: 90.0% coverage
2024-02-10 14:23:10 | SUCCESS | [AAPL 2023] Income statement: 83.3% coverage
...

✓ AAPL complete:
  Filings found: 20
  Filings processed: 20
  Filings skipped: 0
  Filings failed: 0
  Statements success: 60
  Statements failed: 0
  Duration: 45.2s

[2/10] Processing MSFT...
...

================================================================================
BULK IMPORT COMPLETE
================================================================================

📊 Overall Statistics:
   Tickers processed:  10
   Filings found:      200
   Filings processed:  195
   Filings skipped:    0
   Filings failed:     5
   Statements success: 585
   Statements failed:  15

⏱️  Duration: 450.3s (7.5 minutes)
   Average per ticker: 45.0s
   Success rate: 97.5%

📁 Reports saved to: ./bulk_import_results/
```

---

## 🔧 Parameters Explained

### **Required Parameters:**

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `ticker_csv` | str | Path to CSV with tickers | `'tickers.csv'` |

### **Optional Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `periods` | int | 20 | Number of years to import per ticker |
| `db_path` | str | `'financial_statements.duckdb'` | Database file path |
| `log_file` | str | `'bulk_import.log'` | Log file path |
| `output_dir` | str | `'./bulk_import_results'` | Output directory for reports |
| `use_ai_fallback` | bool | False | Enable AI mapper for unmapped concepts |
| `skip_existing` | bool | True | Skip filings already in database |
| `rate_limit_delay` | float | 1.0 | Seconds between requests |

---

## 📈 Performance Expectations

### **Time Estimates:**

| Tickers | Periods | AI Fallback | Estimated Time |
|---------|---------|-------------|----------------|
| 10 | 10 | No | ~5-10 minutes |
| 10 | 20 | No | ~10-15 minutes |
| 50 | 10 | No | ~25-50 minutes |
| 100 | 20 | No | ~2-4 hours |
| 10 | 20 | Yes | ~20-40 minutes |

**Factors:**
- Rate limit delay (default 1.0s)
- Network speed
- SEC server response time
- AI fallback (adds ~2-5s per filing)

---

## 🔍 What Gets Logged

### **Log Levels:**

**INFO** - Progress updates
```
2024-02-10 14:23:01 | INFO    | [AAPL] Retrieved company: Apple Inc
2024-02-10 14:23:02 | INFO    | [AAPL] Found 25 10-K filings
```

**SUCCESS** - Statement inserted
```
2024-02-10 14:23:05 | SUCCESS | [AAPL 2024] Income statement: 86.7% coverage
```

**WARNING** - Non-critical issue
```
2024-02-10 14:23:10 | WARNING | [AAPL 2015] Cash flow statement not available
2024-02-10 14:23:12 | INFO    | [AAPL 2014] Already in database, skipping
```

**ERROR** - Failed operation
```
2024-02-10 14:23:15 | ERROR   | [XYZ 2020] Filing processing failed: XBRL data unavailable
```

---

## 📁 Output Reports

### **1. summary_report.csv**

Per-ticker summary:

```csv
ticker,filings_found,filings_processed,filings_skipped,filings_failed,statements_success,statements_failed,duration_seconds
AAPL,20,20,0,0,60,0,45.2
MSFT,20,19,0,1,57,3,43.1
GOOGL,15,15,0,0,45,0,35.7
```

---

### **2. detailed_log.csv**

All log entries:

```csv
timestamp,level,ticker,year,message
2024-02-10 14:23:01,INFO,AAPL,,Retrieved company: Apple Inc
2024-02-10 14:23:05,SUCCESS,AAPL,2024,Income statement: 86.7% coverage
2024-02-10 14:23:15,ERROR,MSFT,2015,Filing processing failed
```

---

### **3. failures.csv**

Only ERROR entries for easy review:

```csv
timestamp,level,ticker,year,message
2024-02-10 14:23:15,ERROR,MSFT,2015,Filing processing failed: XBRL data unavailable
2024-02-10 14:24:30,ERROR,XYZ,2020,Ticker processing failed: Company not found
```

---

### **4. overall_statistics.txt**

Summary stats:

```
BULK IMPORT STATISTICS
================================================================================

Started:  2024-02-10T14:23:00
Finished: 2024-02-10T14:30:30
Duration: 450.3s (7.5 minutes)

Tickers processed: 10
Filings found:     200
Filings processed: 195
Filings skipped:   0
Filings failed:    5

Statements success: 585
Statements failed:  15

Average time per ticker: 45.0s
Success rate: 97.5%
```

---

## 💡 Common Use Cases

### **Use Case 1: Import FAANG Stocks (10 years)**

```python
# Create tickers.csv:
ticker
META
AAPL
AMZN
NFLX
GOOGL

# Run import
results = asyncio.run(bulk_import_10k(
    ticker_csv='faang.csv',
    periods=10,
    use_ai_fallback=True  # Better coverage
))
```

**Expected:** ~5-10 minutes, ~150 statements

---

### **Use Case 2: Import S&P 500 (5 years)**

```python
# Create sp500.csv with 500 tickers

# Run import (will take ~4-8 hours)
results = asyncio.run(bulk_import_10k(
    ticker_csv='sp500.csv',
    periods=5,
    use_ai_fallback=False,  # Faster
    rate_limit_delay=0.5    # Faster (but be careful)
))
```

**Expected:** ~4-8 hours, ~7,500 statements

---

### **Use Case 3: Update Existing Database**

```python
# Import just 2024 for all companies
results = asyncio.run(bulk_import_10k(
    ticker_csv='all_companies.csv',
    periods=1,              # Just latest
    skip_existing=True      # Skip already-imported
))
```

**Expected:** Fast - only new filings imported

---

### **Use Case 4: Re-import with AI for Better Coverage**

```python
# Re-import with AI fallback for better coverage
results = asyncio.run(bulk_import_10k(
    ticker_csv='tickers.csv',
    periods=20,
    use_ai_fallback=True,   # Enable AI
    skip_existing=False     # Re-import all
))
```

**Expected:** Slower but ~15-20% better coverage

---

## ⚠️ Error Handling

### **What Happens When:**

**Company doesn't exist:**
```
ERROR   | [INVALID] Ticker processing failed: Company not found
```
→ Logged, function continues to next ticker

**No 10-K filings:**
```
WARNING | [STARTUP] No 10-K filings found
```
→ Logged, function continues to next ticker

**Missing statement:**
```
ERROR   | [AAPL 2015] Cash flow extraction failed: Statement not available
```
→ Logged, other statements still processed, function continues

**XBRL parsing error:**
```
ERROR   | [MSFT 2010] Income statement extraction failed: XBRL data unavailable
```
→ Logged, function continues to next filing

**Database insert error:**
```
ERROR   | [GOOGL 2024] Failed to insert balance sheet
```
→ Logged, other statements still processed

---

## 🎯 Best Practices

### **1. Start Small**
Test with 2-3 companies first:
```python
# Test run
results = asyncio.run(bulk_import_10k(
    ticker_csv='test_tickers.csv',  # Just 2-3 tickers
    periods=3,                       # Just 3 years
    use_ai_fallback=False
))
```

### **2. Use Rate Limiting**
Be respectful to SEC servers:
```python
rate_limit_delay=1.0  # Default - recommended
rate_limit_delay=2.0  # More conservative
rate_limit_delay=0.5  # Faster but risky
```

### **3. Enable AI for Important Data**
```python
# Production run with AI
use_ai_fallback=True  # 15-20% better coverage
```

### **4. Skip Existing for Updates**
```python
skip_existing=True  # Only import new filings
```

### **5. Monitor the Logs**
```bash
# Watch progress in real-time
tail -f bulk_import.log
```

### **6. Check Failures**
```python
# After import, review failures
failures = pd.read_csv('bulk_import_results/failures.csv')
print(failures.groupby('ticker').size())
```

---

## 🔄 Incremental Updates

### **Daily/Weekly Updates:**

```python
# Update script to run daily
import asyncio
from bulk_import_10k import bulk_import_10k

# Import only latest period
results = asyncio.run(bulk_import_10k(
    ticker_csv='all_companies.csv',
    periods=1,              # Just check latest
    skip_existing=True,     # Skip already imported
    rate_limit_delay=1.0
))

# Check for new filings
if results['total_filings_processed'] > 0:
    print(f"✓ Imported {results['total_filings_processed']} new filings")
else:
    print("✓ No new filings found")
```

---

## 📊 Analyzing Results

### **After Import - Query Your Data:**

```python
from financial_statements_db import FinancialStatementsDB

db = FinancialStatementsDB('financial_statements.duckdb')

# Get company list
companies = db.query_companies()
print(f"Total companies: {len(companies)}")
print(f"Total filings: {companies['total_filings'].sum()}")

# Get data quality
quality = db.get_data_quality_summary()
print(f"Average coverage: {quality['avg_coverage'].mean():.1f}%")

# Time series analysis
revenue_ts = db.get_time_series('AAPL', 'income', 'revenue', annual_only=True)
print(revenue_ts)
```

---

## ✅ Summary

**What You Get:**
- ✅ Bulk import of 10-K statements
- ✅ Last 20 years (or specify)
- ✅ All 3 statements per filing
- ✅ Comprehensive logging
- ✅ Detailed reports
- ✅ Error handling
- ✅ Progress tracking

**Time Investment:**
- 10 companies, 10 years: ~10-15 minutes
- 50 companies, 10 years: ~1-2 hours
- 100 companies, 20 years: ~4-8 hours

**Data Quality:**
- Without AI: ~60-70% coverage
- With AI: ~80-90% coverage

---

**Your bulk import function is ready!** Start with a small test, then scale up! 🚀
