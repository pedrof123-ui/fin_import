# Project Structure

```
fin_import2/
├── api/
│   ├── main.py                          FastAPI app and route definitions
│   ├── importer.py                      Import logic: fetch SEC filings, extract, insert
│   └── db.py                            DuckDB connection wrapper
│
├── web/                                 Next.js frontend (port 3000)
│   ├── app/
│   │   ├── page.tsx                     Main UI: ticker input, FY/Q selector, statements view
│   │   └── layout.tsx
│   └── components/                      Shared UI components
│
├── extractors/
│   ├── income_statement_extractor.py    Extracts income statement from XBRL filing
│   ├── balance_sheet_extractor.py       Extracts balance sheet
│   └── cash_flow_extractor.py           Extracts cash flow statement
│
├── xbrl_mappings/
│   ├── income_statement_xbrl_mapping.py Static XBRL concept → field mappings
│   ├── balance_sheet_xbrl_mapping.py
│   └── cash_flow_xbrl_mapping.py
│
├── tests/
│   ├── conftest.py                      Mocks openai-agents submodules for fast tests
│   └── test_api.py                      API tests (fast + integration)
│
├── data/
│   └── financial_statements.duckdb      DuckDB database
│
├── financial_statements_db.py           DuckDB schema definition and insert helpers
├── xbrl_concept_mapper.py               AI fallback mapper (openai-agents)
├── xbrl_mapping_manager_multi_statement.py  XBRL mapping persistence
├── bulk_import_10k.py                   Core async bulk import logic
├── run_bulk_import.py                   CLI entry point for bulk imports
├── pyproject.toml                       Dependencies and pytest config
└── CLAUDE.md                            Coding standards
```

## Data flow

### Web app import

1. User submits ticker + period_type (FY/Q) + periods in browser
2. `POST /import` → `api/importer.py:import_ticker()`
3. Fetches 10-K or 10-Q filings from SEC EDGAR via `edgartools`
4. For each filing, calls all 3 extractors (income, balance, cash flow)
5. Each extractor maps XBRL concepts to standard fields via static mappings
6. Results inserted into DuckDB (`income_statements`, `balance_sheets`, `cash_flow_statements`)
7. `GET /statements/{ticker}/{type}` queries and returns rows as JSON

### Bulk import (CLI)

1. `run_bulk_import.py` parses CLI args, prompts for confirmation
2. Calls `bulk_import_10k.bulk_import_10k()` with form=10-K or 10-Q
3. Iterates tickers from CSV, for each: fetches filings, extracts, inserts
4. Writes summary reports to `bulk_import_results/`

## Database tables

| Table | Key columns |
|-------|-------------|
| `income_statements` | ticker, period_end_date, fiscal_year, period_type, revenue, net_income, ... |
| `balance_sheets` | ticker, period_end_date, fiscal_year, period_type, total_assets, ... |
| `cash_flow_statements` | ticker, period_end_date, fiscal_year, period_type, operating_cash_flow, ... |

Duplicate prevention: `ON CONFLICT (ticker, period_end_date) DO NOTHING` on all 3 tables.
