# Multi-Statement Extractor Notebook - Quick Reference

## 📓 Notebook Overview

**File:** `Lab_Multi_Statement_Extractor.ipynb`

**Purpose:** Extract all 3 financial statements (Income, Balance Sheet, Cash Flow) from SEC filings

---

## 🎯 Testable Sections

The notebook is organized into **9 independent, testable sections**:

### **Section 1: Setup & Configuration** ⚙️
**Cells:** 
- `setup_imports` - Import core libraries
- `config_variables` - Set ticker, year, filing type

**Test:** Run both cells, verify no import errors

**Troubleshoot:** 
- Check .env file exists
- Verify all packages installed
- Check folder structure

---

### **Section 2: Test Imports & Verify Setup** ✅
**Cells:**
- `test_extractors` - Verify all 3 extractors load
- `test_mappings` - Verify all 3 mapping files load  
- `test_database` - Test DuckDB connection

**Test:** All cells should show ✓ marks

**Troubleshoot:**
- Check `extractors/` folder structure
- Check `xbrl_mappings/` folder has `__init__.py`
- Verify database file exists or can be created

---

### **Section 3: Download SEC Filing** 📥
**Cells:**
- `download_filing` - Download from EDGAR

**Test:** Should display filing metadata

**Troubleshoot:**
- Check ticker is valid
- Check year has filings
- Verify SEC_ID in .env
- Check internet connection

---

### **Section 4: Extract Income Statement** 💰
**Cells:**
- `extract_income` - Run extraction
- `display_income` - Display by section

**Test:** Should extract 25-28 out of 30 fields

**Troubleshoot:**
- Try with `USE_AI_FALLBACK = False`
- Check filing has XBRL data
- Verify AI mapper is working

---

### **Section 5: Extract Balance Sheet** 📊
**Cells:**
- `extract_balance` - Run extraction
- `display_balance` - Display by section

**Test:** Should extract 32-36 out of 38 fields

**Troubleshoot:** Same as income statement

---

### **Section 6: Extract Cash Flow Statement** 💵
**Cells:**
- `extract_cashflow` - Run extraction
- `display_cashflow` - Display by section

**Test:** Should extract 25-28 out of 30 fields

**Troubleshoot:** Same as income statement

---

### **Section 7: Combined Analysis & Metrics** 📈
**Cells:**
- `overall_summary` - Show overall coverage
- `cross_statement_validation` - Validate balance sheet equation, net income consistency
- `financial_ratios` - Calculate margins, ratios

**Test:** Validations should pass (or show < 1% variance)

**Troubleshoot:**
- Large variances indicate data quality issues
- Check if fields were extracted correctly

---

### **Section 8: Export All Statements** 💾
**Cells:**
- `export_csv` - Save 3 individual CSV files
- `export_excel` - Save combined Excel workbook
- `log_to_database` - Log to DuckDB (optional)

**Test:** Files should be created in `./financial_statements/`

**Troubleshoot:**
- Check write permissions
- Verify openpyxl installed for Excel export

---

### **Section 9: Batch Processing** 🔄
**Cells:**
- `batch_setup` - Configure ticker list
- `batch_process` - Extract all tickers

**Test:** Should process all tickers in list

**Troubleshoot:**
- Processing multiple tickers can take time (2-3 min each)
- Some tickers may fail - check batch summary

---

## 🚀 Quick Start

### **Option 1: Single Company (Quick)**
1. Run Section 1 (Setup)
2. Change `TICKER` in `config_variables`
3. Run Sections 3-8 sequentially
4. Check `./financial_statements/` for output

**Time:** 2-5 minutes

---

### **Option 2: With Validation (Recommended)**
1. Run Section 1 (Setup)
2. Run Section 2 (Verify Setup)
3. Change `TICKER` in `config_variables`
4. Run Sections 3-8 sequentially
5. Review Section 7 validation results

**Time:** 3-7 minutes

---

### **Option 3: Batch Processing (Production)**
1. Run Section 1 (Setup)
2. Run Section 2 (Verify Setup)
3. Modify `TICKER_LIST` in Section 9
4. Run Section 9 batch cells
5. Review `batch_summary.csv`

**Time:** 15-30 minutes for 10 companies

---

## 📊 Expected Output

### **Files Created:**

```
./financial_statements/
├── AAPL_10-K_2024_income_statement.csv
├── AAPL_10-K_2024_balance_sheet.csv
├── AAPL_10-K_2024_cash_flow.csv
└── AAPL_10-K_2024_all_statements.xlsx
    ├── Sheet: Income Statement
    ├── Sheet: Balance Sheet
    ├── Sheet: Cash Flow
    └── Sheet: Summary
```

### **Data Quality:**

| Statement | Typical Coverage |
|-----------|------------------|
| Income | 75-85% (25-28/30 fields) |
| Balance Sheet | 85-95% (32-36/38 fields) |
| Cash Flow | 80-90% (25-28/30 fields) |
| **Overall** | **80-90%** |

---

## 🔧 Configuration Variables

Located in Section 1, cell `config_variables`:

```python
TICKER = "AAPL"              # Change this
FILING_TYPE = "10-K"         # "10-K" or "10-Q"
YEAR = 2024                  # Fiscal year
QUARTER = None               # For 10-Q: 1, 2, 3, or 4
USE_AI_FALLBACK = True       # AI concept mapping
OUTPUT_DIR = "./financial_statements"
DB_PATH = "xbrl_mappings_multi.duckdb"
```

---

## ⚠️ Common Issues

### **1. Import Errors**
```
ImportError: No module named 'extractors'
```
**Fix:** Make sure `extractors/` folder has `__init__.py`

---

### **2. Mapping Not Found**
```
ERROR: Could not import from xbrl_mappings package
```
**Fix:** Check `xbrl_mappings/` has:
- `__init__.py`
- `income_statement_xbrl_mapping.py`
- `balance_sheet_xbrl_mapping.py`
- `cash_flow_xbrl_mapping.py`

---

### **3. Low Data Quality**
```
Data Quality: 15/30 (50%)
```
**Possible causes:**
- Wrong filing type (used 10-Q instead of 10-K)
- Company doesn't file XBRL
- Statement not available for that period

**Fix:** Try different year or filing type

---

### **4. Filing Not Found**
```
FileNotFoundError: No 10-K filings found for XYZ in year 2024
```
**Fix:**
- Check ticker is correct
- Check year is correct
- Try `YEAR = None` for most recent

---

### **5. AI Mapper Timeout**
```
Error mapping concept: timeout
```
**Fix:** Set `USE_AI_FALLBACK = False` to skip AI mapper

---

## 💡 Tips & Tricks

### **Tip 1: Test with Apple First**
Apple (AAPL) has excellent XBRL data quality. Always test with AAPL first to verify setup.

### **Tip 2: Disable AI for Speed**
Set `USE_AI_FALLBACK = False` for faster extraction (but slightly lower coverage)

### **Tip 3: Use Batch for Multiple Years**
Modify Section 9 to loop through years:
```python
for year in [2020, 2021, 2022, 2023, 2024]:
    # Extract for each year
```

### **Tip 4: Export to Database for Analysis**
Enable database logging in Section 8 to track data quality over time

### **Tip 5: Check Validations**
Section 7 validations catch data extraction errors. Always review them!

---

## 📈 Performance Expectations

### **Single Company:**
- Time: 2-5 minutes
- AI calls: 0-9 (if enabled)
- Files created: 4 (3 CSVs + 1 Excel)

### **Batch (10 Companies):**
- Time: 20-30 minutes
- AI calls: 0-90 (if enabled)
- Files created: 31 (30 CSVs + 1 summary)

---

## ✅ Success Criteria

After running the notebook, you should have:

1. ✅ All 3 statements extracted (98 total fields)
2. ✅ Data quality > 80% overall
3. ✅ Balance sheet equation validates (< 1% variance)
4. ✅ Net income consistency between statements
5. ✅ Files saved to output directory
6. ✅ No critical errors

---

## 🆘 Getting Help

**If a section fails:**

1. **Check the troubleshooting section** for that specific section above
2. **Review error messages** - they usually indicate the issue
3. **Run earlier sections again** - especially Section 2 (Verify Setup)
4. **Try with a different ticker** - Some companies have better data than others
5. **Disable AI fallback** - Set `USE_AI_FALLBACK = False`

**Still stuck?** Check:
- File structure is correct
- All packages installed (`pip install -r requirements.txt`)
- .env file has SEC_ID
- Internet connection working

---

## 🎯 Next Steps After Extraction

1. **Review data quality** in Section 7
2. **Analyze AI discoveries** - Check which concepts were found
3. **Update mapping files** - Add successful AI discoveries
4. **Run batch processing** - Extract multiple companies
5. **Build dashboards** - Use exported data for visualization

---

**Your multi-statement extraction notebook is ready!** 🚀
