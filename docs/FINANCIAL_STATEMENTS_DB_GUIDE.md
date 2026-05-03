# Financial Statements Database - Usage Guide

## Overview

A comprehensive DuckDB database for storing and analyzing 10-K and 10-Q financial statements.

**Features:**
- Stores all 3 financial statements (Income, Balance Sheet, Cash Flow)
- Tracks filing dates (published date) and period end dates
- Supports both annual (10-K) and quarterly (10-Q) filings
- Data quality metrics
- Time series analysis
- Company master data
- Easy querying and export

---

## Database Schema

### **Tables Created:**

1. **`companies`** - Master company list
2. **`income_statements`** - Income statement data (30 fields)
3. **`balance_sheets`** - Balance sheet data (38 fields)
4. **`cash_flow_statements`** - Cash flow data (30 fields)
5. **`extraction_log`** - Extraction history

### **Key Fields in Each Statement:**

#### **Metadata (all tables):**
- `ticker` - Company ticker symbol
- `filing_date` - **Filing/published date** (when filed with SEC)
- `period_end_date` - Period end date (fiscal period)
- `filing_type` - 10-K, 10-Q, etc.
- `fiscal_year` - Fiscal year
- `fiscal_quarter` - 1-4 for quarterly, NULL for annual
- `period_type` - 'Annual' or 'Quarterly'

#### **Data Quality:**
- `extraction_date` - When data was extracted
- `fields_extracted` - Number of fields found
- `total_fields` - Total fields attempted
- `coverage_pct` - Data quality percentage

#### **Financial Data:**
- All ~30-40 financial fields specific to each statement

---

## Quick Start

### **1. Initialize Database**

```python
from financial_statements_db import FinancialStatementsDB

# Create/connect to database
db = FinancialStatementsDB('financial_statements.duckdb')
```

**Output:**
```
- Connected to financial statements database: financial_statements.duckdb
- Database schema created/verified
```

---

### **2. Insert Statements**

```python
from extractors.income_statement_extractor import get_filing, extract_income_statement
from extractors.balance_sheet_extractor import extract_balance_sheet
from extractors.cash_flow_extractor import extract_cash_flow

# Extract statements (see notebook for details)
filing = get_filing('AAPL', '10-K', 2025)
income_df = await extract_income_statement(filing, 'AAPL', '10-K')
balance_df = await extract_balance_sheet(filing, 'AAPL', '10-K')
cashflow_df = await extract_cash_flow(filing, 'AAPL', '10-K')

# Insert into database
db.insert_income_statement(income_df)
db.insert_balance_sheet(balance_df)
db.insert_cash_flow(cashflow_df)

# Or insert all at once
results = db.insert_all_statements(income_df, balance_df, cashflow_df)
```

**Output:**
```
- Inserted income statement: AAPL 10-K 2024-09-28 (86.7% coverage)
- Inserted balance sheet: AAPL 10-K 2024-09-28 (92.1% coverage)
- Inserted cash flow: AAPL 10-K 2024-09-28 (90.0% coverage)
```

The bulk import and API paths call `log_extraction()` automatically after each filing.
To log manually when using the extractors directly:

```python
db.log_extraction(
    ticker='AAPL',
    filing_type='10-K',
    fiscal_year=2024,
    fiscal_quarter=None,
    statements_extracted='income,balance,cashflow',
    overall_coverage_pct=89.6,
    success=True,
    execution_time_seconds=12.4,
)
```

Query the log:

```python
db.conn.execute("""
    SELECT ticker, filing_type, fiscal_year, statements_extracted,
           overall_coverage_pct, success, execution_time_seconds
    FROM extraction_log
    ORDER BY extraction_date DESC
    LIMIT 20
""").fetchdf()
```

---

### **3. Query Data**

#### **Get All Statements for a Company:**

```python
# Get everything
statements = db.get_company_statements('AAPL')
print(statements['income'])
print(statements['balance'])
print(statements['cashflow'])

# Get just income statements
income_only = db.get_company_statements('AAPL', statement_type='income')
```

---

#### **Get Time Series:**

```python
# Revenue over time
revenue_ts = db.get_time_series('AAPL', 'income', 'revenue')
print(revenue_ts)
```

**Output:**
```
  period_end_date  filing_date  fiscal_year  fiscal_quarter         value
0      2020-09-26   2020-10-29         2020            None  274515000000
1      2021-09-25   2021-10-28         2021            None  365817000000
2      2022-09-24   2022-10-27         2022            None  394328000000
3      2023-09-30   2023-11-02         2023            None  383285000000
4      2024-09-28   2024-11-01         2024            None  391035000000
```

---

#### **Get Latest Filing:**

```python
# Get most recent 10-K
latest = db.get_latest_filing('AAPL', 'income')
print(latest[['filing_date', 'period_end_date', 'revenue', 'net_income']])
```

---

#### **List All Companies:**

```python
companies = db.query_companies()
print(companies[['ticker', 'total_filings', 'first_filing_date', 'last_filing_date']])
```

**Output:**
```
  ticker  total_filings  first_filing_date  last_filing_date
0   AAPL             15         2015-10-28        2024-11-01
1   MSFT             12         2016-07-21        2024-10-30
2  GOOGL              8         2018-02-05        2024-10-29
```

---

#### **Data Quality Summary:**

```python
quality = db.get_data_quality_summary()
print(quality[['ticker', 'period_end_date', 'income_coverage', 'balance_coverage', 'cashflow_coverage', 'avg_coverage']])
```

**Output:**
```
  ticker  period_end_date  income_coverage  balance_coverage  cashflow_coverage  avg_coverage
0   AAPL       2024-09-28             86.7              92.1               90.0          89.6
1   AAPL       2023-09-30             83.3              89.5               86.7          86.5
2   MSFT       2024-06-30             90.0              94.7               93.3          92.7
```

---

### **4. Export to Excel**

```python
# Export all statements for Apple to Excel
db.export_to_excel('AAPL', 'AAPL_financial_statements.xlsx')
```

**Output:**
```
- Exported AAPL to AAPL_financial_statements.xlsx
```

**Excel file contains:**
- Sheet 1: Income Statements
- Sheet 2: Balance Sheets
- Sheet 3: Cash Flow

---

## Advanced Queries

### **Query 1: Revenue Growth Analysis**

```python
import pandas as pd

# Get revenue time series
revenue = db.get_time_series('AAPL', 'income', 'revenue', annual_only=True)

# Calculate YoY growth
revenue['yoy_growth'] = revenue['value'].pct_change() * 100

print(revenue[['fiscal_year', 'value', 'yoy_growth']])
```

**Output:**
```
   fiscal_year         value  yoy_growth
0         2020  274515000000         NaN
1         2021  365817000000       33.27
2         2022  394328000000        7.79
3         2023  383285000000       -2.80
4         2024  391035000000        2.02
```

---

### **Query 2: Compare Multiple Companies**

```python
# Get latest revenue for multiple companies
query = """
    SELECT 
        ticker,
        fiscal_year,
        revenue,
        net_income,
        (net_income / revenue * 100) as net_margin
    FROM income_statements
    WHERE period_type = 'Annual'
    AND fiscal_year = 2024
    ORDER BY revenue DESC
"""

comparison = db.conn.execute(query).df()
print(comparison)
```

---

### **Query 3: Balance Sheet Health Check**

```python
query = """
    SELECT 
        ticker,
        period_end_date,
        total_assets,
        total_liabilities,
        total_equity,
        (total_liabilities / total_assets * 100) as debt_ratio,
        (total_current_assets / total_current_liabilities) as current_ratio
    FROM balance_sheets
    WHERE period_type = 'Annual'
    ORDER BY period_end_date DESC
"""

health = db.conn.execute(query).df()
print(health)
```

---

### **Query 4: Cash Flow Analysis**

```python
query = """
    SELECT 
        ticker,
        fiscal_year,
        net_cash_operating_activities,
        capital_expenditures,
        (net_cash_operating_activities + capital_expenditures) as free_cash_flow,
        dividends_paid,
        stock_repurchase
    FROM cash_flow_statements
    WHERE period_type = 'Annual'
    ORDER BY ticker, fiscal_year
"""

fcf = db.conn.execute(query).df()
print(fcf)
```

---

## Batch Processing

### **Insert Multiple Companies:**

```python
tickers = ['AAPL', 'MSFT', 'GOOGL', 'META', 'TSLA']

for ticker in tickers:
    print(f"\nProcessing {ticker}...")
    
    try:
        # Extract
        filing = get_filing(ticker, '10-K', 2024)
        income = await extract_income_statement(filing, ticker, '10-K')
        balance = await extract_balance_sheet(filing, ticker, '10-K')
        cashflow = await extract_cash_flow(filing, ticker, '10-K')
        
        # Insert
        db.insert_all_statements(income, balance, cashflow)
        
        print(f"- {ticker} complete")
        
    except Exception as e:
        print(f"✗ {ticker} failed: {e}")

print("\n- Batch processing complete!")
```

---

### **Insert Multiple Years:**

```python
ticker = 'AAPL'
years = [2020, 2021, 2022, 2023, 2024]

for year in years:
    print(f"\nProcessing {ticker} {year}...")
    
    try:
        filing = get_filing(ticker, '10-K', year)
        income = await extract_income_statement(filing, ticker, '10-K', year)
        balance = await extract_balance_sheet(filing, ticker, '10-K', year)
        cashflow = await extract_cash_flow(filing, ticker, '10-K', year)
        
        db.insert_all_statements(income, balance, cashflow)
        
    except Exception as e:
        print(f"✗ {year} failed: {e}")

print(f"\n- All years for {ticker} complete!")
```

---

## Integration with Notebook

Add this cell to your notebook after Section 8 (Export):

```python
# ============================================================================
# SECTION 9: Save to Database
# ============================================================================

from financial_statements_db import FinancialStatementsDB

print("="*80)
print("SAVING TO DATABASE")
print("="*80)

# Initialize database
db = FinancialStatementsDB('financial_statements.duckdb')

# Insert all statements
results = db.insert_all_statements(income_df, balance_df, cashflow_df)

print(f"\nDatabase Results:")
print(f"  Income:   {'✓' if results.get('income') else '✗'}")
print(f"  Balance:  {'✓' if results.get('balance') else '✗'}")
print(f"  Cash Flow: {'✓' if results.get('cashflow') else '✗'}")

# Show what's in database
companies = db.query_companies()
print(f"\n- Total companies in database: {len(companies)}")
print(f"- Total filings: {companies['total_filings'].sum()}")

db.close()
```

---

## Key Features

### **1. Filing Date vs Period End Date:**
- **`filing_date`** = When the filing was **published/filed** with SEC
- **`period_end_date`** = End of the **fiscal period** being reported
- Example: Q3 2024 ends Sept 30, but filed on Nov 1

### **2. Primary Key:**
- `(ticker, filing_date, period_end_date)` uniquely identifies each filing
- Prevents duplicates
- Allows updates (upsert logic)

### **3. Data Quality Tracking:**
- `fields_extracted` / `total_fields` = `coverage_pct`
- Helps identify incomplete extractions
- Track improvements over time

### **4. Upsert Behavior:**
- Re-inserting same filing **updates** existing record
- No duplicates created
- Safe to re-run extractions

---

## Important Notes

1. **Date Format:** All dates stored as DATE type (YYYY-MM-DD)
2. **NULL Values:** Missing fields stored as NULL (not 0)
3. **Currency:** All values in USD (no currency conversion)
4. **Company Updates:** Company record auto-updated on each insert
5. **Performance:** DuckDB is fast - handles 10,000+ filings easily

---

## Common Use Cases

### **Use Case 1: Build Time Series Dataset**
```python
# Get 5 years of revenue data
years = [2020, 2021, 2022, 2023, 2024]
for year in years:
    # extract and insert

# Query time series
revenue_ts = db.get_time_series('AAPL', 'income', 'revenue')
```

### **Use Case 2: Compare Competitors**
```python
# Extract all FAANG companies
faang = ['META', 'AAPL', 'AMZN', 'NFLX', 'GOOGL']
for ticker in faang:
    # extract and insert

# Compare metrics
query = "SELECT ticker, revenue, net_income FROM income_statements WHERE fiscal_year = 2024"
comparison = db.conn.execute(query).df()
```

### **Use Case 3: Quarterly Trend Analysis**
```python
# Extract all quarters for a year
for quarter in [1, 2, 3, 4]:
    filing = get_filing('AAPL', '10-Q', 2024, quarter)
    # extract and insert

# Analyze quarterly trends
quarterly = db.get_time_series('AAPL', 'income', 'revenue', annual_only=False)
```

---

## Summary

**What You Have:**
- Complete financial statements database
- Filing dates (published dates) tracked
- Time series analysis ready
- Multi-company support
- Data quality tracking
- Easy querying and export

**Next Steps:**
1. Run your notebook to extract statements
2. Insert into database using `db.insert_all_statements()`
3. Query and analyze your data
4. Build dashboards or exports

**Your financial data is now persistent and query-able!** 🎉
