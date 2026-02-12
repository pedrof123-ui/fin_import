# Running Bulk Import - Quick Reference

## ✅ YES - You Can Use UV!

```bash
uv run run_bulk_import.py tickers.csv
```

---

## 🚀 Quick Start

### **1. Create tickers.csv**
```csv
ticker
AAPL
MSFT
GOOGL
```

### **2. Run with UV**
```bash
uv run run_bulk_import.py tickers.csv
```

---

## 📋 Command Options

### **Basic Usage:**
```bash
# Import last 20 years (default)
uv run run_bulk_import.py tickers.csv

# Shorter version
python run_bulk_import.py tickers.csv
```

---

### **Specify Number of Years:**
```bash
# Import last 10 years
uv run run_bulk_import.py tickers.csv --periods 10

# Import last 5 years
uv run run_bulk_import.py tickers.csv --periods 5
```

---

### **Enable AI for Better Coverage:**
```bash
# Use AI mapper (slower but 80-90% coverage vs 60-70%)
uv run run_bulk_import.py tickers.csv --ai
```

---

### **Custom Database:**
```bash
# Use different database file
uv run run_bulk_import.py tickers.csv --db my_database.duckdb
```

---

### **Re-import Existing Data:**
```bash
# Don't skip existing filings (re-import everything)
uv run run_bulk_import.py tickers.csv --no-skip
```

---

### **Faster Rate (Careful!):**
```bash
# 0.5 second delay instead of 1 second
uv run run_bulk_import.py tickers.csv --delay 0.5
```

---

### **Custom Output Directory:**
```bash
# Save reports to different location
uv run run_bulk_import.py tickers.csv --output ./my_results
```

---

## 🎯 Common Commands

### **Quick Test (3 companies, 5 years):**
```bash
# Create test_tickers.csv with 3 companies
echo -e "ticker\nAAPL\nMSFT\nGOOGL" > test_tickers.csv

# Run test
uv run run_bulk_import.py test_tickers.csv --periods 5
```

---

### **Production Run (many companies, 20 years, AI):**
```bash
uv run run_bulk_import.py all_companies.csv --periods 20 --ai
```

---

### **Update Latest Filings Only:**
```bash
# Just check for latest year
uv run run_bulk_import.py all_companies.csv --periods 1
```

---

### **Full Re-import with AI:**
```bash
# Re-import everything with AI for better coverage
uv run run_bulk_import.py tickers.csv --periods 20 --ai --no-skip
```

---

## 📊 Example Run

```bash
$ uv run run_bulk_import.py tickers.csv --periods 10 --ai

================================================================================
BULK IMPORT CONFIGURATION
================================================================================
Ticker CSV:       tickers.csv
Periods:          10
Database:         financial_statements.duckdb
AI Fallback:      Enabled
Skip Existing:    Yes
Rate Limit:       1.0s
Output Dir:       ./bulk_import_results
Log File:         bulk_import.log
================================================================================

Proceed with import? [y/N]: y

================================================================================
BULK 10-K IMPORT
================================================================================

📋 Reading tickers from tickers.csv...
✓ Found 5 tickers

💾 Connecting to database...
✓ Connected

🚀 Starting bulk extraction...

[1/5] Processing AAPL...
...
```

---

## 🛠️ All Options

```bash
uv run run_bulk_import.py --help

usage: run_bulk_import.py [-h] [--periods PERIODS] [--db DB] [--log LOG]
                          [--output OUTPUT] [--ai] [--no-skip] [--delay DELAY]
                          ticker_csv

Bulk import 10-K statements from SEC EDGAR

positional arguments:
  ticker_csv         Path to CSV file with ticker list

optional arguments:
  -h, --help         show this help message and exit
  --periods PERIODS  Number of years to import per ticker (default: 20)
  --db DB           Database file path (default: financial_statements.duckdb)
  --log LOG         Log file path (default: bulk_import.log)
  --output OUTPUT   Output directory for reports (default: ./bulk_import_results)
  --ai              Enable AI fallback for better coverage (slower)
  --no-skip         Re-import existing filings (default: skip existing)
  --delay DELAY     Delay between requests in seconds (default: 1.0)
```

---

## 🔄 Different Ways to Run

### **Option 1: With UV (Recommended)**
```bash
uv run run_bulk_import.py tickers.csv
```

### **Option 2: With Python Directly**
```bash
python run_bulk_import.py tickers.csv
```

### **Option 3: Make Executable (Unix/Mac)**
```bash
chmod +x run_bulk_import.py
./run_bulk_import.py tickers.csv
```

### **Option 4: From Python Code**
```python
import asyncio
from bulk_import_10k import bulk_import_10k

results = asyncio.run(bulk_import_10k(
    ticker_csv='tickers.csv',
    periods=20
))
```

---

## ⏱️ Time Estimates

| Command | Companies | Years | AI | Time |
|---------|-----------|-------|-----|------|
| `--periods 5` | 10 | 5 | No | ~5-10 min |
| `--periods 10` | 10 | 10 | No | ~10-15 min |
| `--periods 20` | 10 | 20 | No | ~15-20 min |
| `--periods 10 --ai` | 10 | 10 | Yes | ~20-30 min |
| `--periods 20 --ai` | 50 | 20 | Yes | ~4-8 hours |

---

## 📁 What Gets Created

After running, you'll have:

```
.
├── tickers.csv                          # Your input
├── financial_statements.duckdb          # Database with all data
├── bulk_import.log                      # Detailed log
└── bulk_import_results/
    ├── summary_report.csv               # Per-ticker stats
    ├── detailed_log.csv                 # All log entries
    ├── failures.csv                     # Errors (if any)
    └── overall_statistics.txt           # Summary
```

---

## ✅ Summary

**YES - You can use UV:**
```bash
uv run run_bulk_import.py tickers.csv
```

**With options:**
```bash
uv run run_bulk_import.py tickers.csv --periods 10 --ai
```

**That's it!** 🚀
