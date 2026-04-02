# Metadata Fields - Income Statement Extraction

## Overview

Each extracted income statement now includes **7 metadata fields** that provide context about the filing and period.

## Metadata Fields

### 1. **Ticker** (String)
- Company ticker symbol
- Example: `"AAPL"`, `"MSFT"`, `"TSLA"`
- Source: User input

### 2. **Fiscal_Year** (Integer)
- Fiscal year of the financial statement
- Example: `2024`, `2023`, `2022`
- Source: 
  - User input (if provided)
  - Extracted from `period_of_report` date (if not provided)
- Note: This is the fiscal year end, not the filing year

### 3. **Period_End_Date** (String, Format: YYYY-MM-DD)
- The end date of the reporting period
- Example: `"2024-09-28"`, `"2024-06-30"`
- Source: Extracted from XBRL data (most recent period in the statement)
- This is the actual date the financial period ended

### 4. **Filing_Date** (String, Format: YYYY-MM-DD)
- Date the filing was submitted to the SEC
- Example: `"2024-11-01"` (filed after period end)
- Source: Extracted from filing metadata
- Note: Always comes after Period_End_Date (companies file weeks after period ends)

### 5. **Filing_Type** (String)
- Type of SEC filing
- Examples: 
  - `"10-K"` - Annual report
  - `"10-Q"` - Quarterly report
  - `"10-K/A"` - Amended annual report
  - `"10-Q/A"` - Amended quarterly report
- Source: Extracted from filing metadata

### 6. **Period_Type** (String)
- Whether this is an annual or quarterly period
- Values:
  - `"Annual"` - For 10-K filings
  - `"Quarterly"` - For 10-Q filings
- Source: Derived from Filing_Type
- Logic: `"Annual"` if "K" in filing type and "Q" not in filing type

### 7. **Quarter** (Integer or None)
- Fiscal quarter number (1-4)
- Values:
  - `1` - Q1 (typically Jan-Mar or similar)
  - `2` - Q2 (typically Apr-Jun or similar)
  - `3` - Q3 (typically Jul-Sep or similar)
  - `4` - Q4 (typically Oct-Dec or similar, but many companies don't file 10-Q for Q4)
  - `None` - For annual filings (10-K)
- Source:
  - User input (if provided)
  - Calculated from Period_End_Date month
- Calculation: `quarter = ((month - 1) // 3) + 1`

## CSV Output Structure

The CSV now has this structure:

```csv
Ticker,Fiscal_Year,Period_End_Date,Filing_Date,Filing_Type,Period_Type,Quarter,Status,Field,Value,Concept
AAPL,2024,2024-09-28,2024-11-01,10-K,Annual,,✓,revenue,391035000000.0,RevenueFromContract...
AAPL,2024,2024-09-28,2024-11-01,10-K,Annual,,✓,cost_of_revenue,210352000000.0,CostOfGoodsAndServices...
AAPL,2024,2024-09-28,2024-11-01,10-K,Annual,,✓,gross_profit,180683000000.0,GrossProfit
...
```

**Key Points:**
- Metadata is repeated on every row (same for all line items)
- This makes the CSV easy to filter and aggregate
- Each row is self-contained with full context

## Display Output

### Metadata Section (New)
```
INCOME STATEMENT - AAPL
================================================================================

Filing Metadata:
  Ticker:           AAPL
  Fiscal Year:      2024
  Period End Date:  2024-09-28
  Filing Date:      2024-11-01
  Filing Type:      10-K
  Period Type:      Annual
```

### Quarterly Example
```
Filing Metadata:
  Ticker:           MSFT
  Fiscal Year:      2024
  Period End Date:  2024-06-30
  Filing Date:      2024-07-30
  Filing Type:      10-Q
  Period Type:      Quarterly
  Quarter:          Q2
```

## Use Cases

### 1. Database Loading
```python
import pandas as pd

# Load CSV with metadata
df = pd.read_csv('AAPL_10-K_2024_income_statement.csv')

# Each row has all context needed for database insert
for _, row in df.iterrows():
    insert_sql = """
        INSERT INTO income_statement 
        (ticker, fiscal_year, period_end_date, filing_date, 
         filing_type, period_type, quarter, field_name, value)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    cursor.execute(insert_sql, (
        row['Ticker'], row['Fiscal_Year'], row['Period_End_Date'],
        row['Filing_Date'], row['Filing_Type'], row['Period_Type'],
        row['Quarter'], row['Field'], row['Value']
    ))
```

### 2. Multi-Company Analysis
```python
# Combine multiple extractions
files = [
    'AAPL_10-K_2024_income_statement.csv',
    'MSFT_10-K_2024_income_statement.csv',
    'GOOGL_10-K_2024_income_statement.csv'
]

all_data = pd.concat([pd.read_csv(f) for f in files])

# Filter to specific fields and periods
revenue_data = all_data[
    (all_data['Field'] == 'revenue') &
    (all_data['Fiscal_Year'] == 2024) &
    (all_data['Period_Type'] == 'Annual')
]

# Compare revenue across companies
revenue_comparison = revenue_data.pivot(
    index='Ticker', 
    columns='Field', 
    values='Value'
)
```

### 3. Time Series Analysis
```python
# Load multiple periods for one company
files = [
    'AAPL_10-K_2024_income_statement.csv',
    'AAPL_10-K_2023_income_statement.csv',
    'AAPL_10-K_2022_income_statement.csv'
]

historical = pd.concat([pd.read_csv(f) for f in files])

# Track revenue growth
revenue_over_time = historical[
    historical['Field'] == 'revenue'
].sort_values('Fiscal_Year')

revenue_over_time['YoY_Growth'] = revenue_over_time['Value'].pct_change()
```

### 4. Quarterly Trends
```python
# Load quarterly data
q_files = [
    'MSFT_10-Q_2024_Q1_income_statement.csv',
    'MSFT_10-Q_2024_Q2_income_statement.csv',
    'MSFT_10-Q_2024_Q3_income_statement.csv'
]

quarterly = pd.concat([pd.read_csv(f) for f in q_files])

# Analyze quarterly progression
quarterly_revenue = quarterly[
    (quarterly['Field'] == 'revenue') &
    (quarterly['Fiscal_Year'] == 2024)
].sort_values('Quarter')
```

## Filename Convention

Filenames are auto-generated with metadata:

**Format:** `{Ticker}_{Filing_Type}_{Fiscal_Year}[_Q{Quarter}]_income_statement.csv`

**Examples:**
- Annual: `AAPL_10-K_2024_income_statement.csv`
- Quarterly: `MSFT_10-Q_2024_Q2_income_statement.csv`
- Amended: `TSLA_10-K-A_2024_income_statement.csv`

**Notes:**
- `/` in filing type is replaced with `-` (e.g., `10-K/A` → `10-K-A`)
- Quarter only included for quarterly filings
- Clear, sortable, no special characters

## Database Schema Update

Add metadata columns to your database:

```sql
ALTER TABLE income_statement
ADD COLUMN ticker VARCHAR(10),
ADD COLUMN fiscal_year INT,
ADD COLUMN period_end_date DATE,
ADD COLUMN filing_date DATE,
ADD COLUMN filing_type VARCHAR(10),
ADD COLUMN period_type VARCHAR(20),
ADD COLUMN quarter INT;

-- Update primary key to include period info
ALTER TABLE income_statement
DROP CONSTRAINT income_statement_pkey,
ADD PRIMARY KEY (ticker, period_end_date);

-- Add indexes for common queries
CREATE INDEX idx_income_ticker_year ON income_statement(ticker, fiscal_year);
CREATE INDEX idx_income_filing_type ON income_statement(filing_type);
CREATE INDEX idx_income_period_type ON income_statement(period_type, quarter);
```

## Common Queries

### Get Annual Data Only
```sql
SELECT * FROM income_statement
WHERE period_type = 'Annual'
AND fiscal_year = 2024;
```

### Get Quarterly Progression
```sql
SELECT ticker, fiscal_year, quarter, revenue, net_income
FROM income_statement
WHERE period_type = 'Quarterly'
AND fiscal_year = 2024
ORDER BY ticker, quarter;
```

### Compare Filing vs Period Dates
```sql
SELECT 
    ticker,
    period_end_date,
    filing_date,
    filing_date - period_end_date AS days_to_file
FROM income_statement
WHERE filing_type = '10-K';
```

## Validation Examples

### Check for Missing Quarters
```python
# Expected: Q1, Q2, Q3 for most companies (Q4 included in 10-K)
df = pd.read_csv('company_extractions.csv')

quarterly = df[df['Period_Type'] == 'Quarterly']
quarters_found = quarterly.groupby(['Ticker', 'Fiscal_Year'])['Quarter'].unique()

for (ticker, year), quarters in quarters_found.items():
    if len(quarters) < 3:
        print(f"⚠ {ticker} {year}: Only has quarters {sorted(quarters)}")
```

### Verify Fiscal Year Consistency
```python
# Period_End_Date should align with Fiscal_Year
df['Period_Year'] = pd.to_datetime(df['Period_End_Date']).dt.year

mismatches = df[df['Period_Year'] != df['Fiscal_Year']]

if not mismatches.empty:
    print("⚠ Fiscal year mismatches found:")
    print(mismatches[['Ticker', 'Fiscal_Year', 'Period_End_Date']])
```

## Benefits

1. **Self-Contained Data** - Each CSV has complete context
2. **Easy Filtering** - Filter by year, quarter, filing type
3. **Database Ready** - All metadata needed for proper storage
4. **Traceability** - Can trace back to exact SEC filing
5. **Time Series** - Easy to combine multiple periods
6. **Audit Trail** - Filing date shows when data was available

## Migration Note

Old CSV format:
```csv
Status,Field,Value,Concept
✓,revenue,391035000000.0,RevenueFromContract...
```

New CSV format (7 additional columns):
```csv
Ticker,Fiscal_Year,Period_End_Date,Filing_Date,Filing_Type,Period_Type,Quarter,Status,Field,Value,Concept
AAPL,2024,2024-09-28,2024-11-01,10-K,Annual,,✓,revenue,391035000000.0,RevenueFromContract...
```

**Impact:** Minimal - just additional columns at the beginning. Old code that reads from the CSV will still work if it accesses columns by name.
