# Code Review

## Findings

### High

1. `skip_existing` can permanently hide partially imported filings.
   Files:
   `bulk_import_10k.py:309`
   `bulk_import_10k.py:316`

   The bulk importer decides whether to skip a filing by checking only `income_statements` for the `(ticker, fiscal_year)` pair. If a previous run inserted the income statement but failed on the balance sheet or cash flow, the default `skip_existing=True` path will skip that filing forever on subsequent runs. This leaves the database in a silently incomplete state while reporting the filing as already imported.

2. The extractor modules fail at import time when `SEC_ID` is missing, which breaks local testing and any code path that only needs pure DataFrame helpers.
   Files:
   `extractors/income_statement_extractor.py:19`
   `extractors/income_statement_extractor.py:21`
   `extractors/balance_sheet_extractor.py:19`
   `extractors/balance_sheet_extractor.py:21`
   `extractors/cash_flow_extractor.py:19`
   `extractors/cash_flow_extractor.py:21`

   All three extractors raise immediately during module import if `SEC_ID` is not present. That means even offline-safe functions like `extract_value_from_statement_df()` cannot be imported in tests or scripts unless SEC credentials are configured first. This is a hard coupling between configuration and import that makes the modules brittle and much harder to reuse.

### Medium

3. Filing selection can pick amended filings and the wrong yearly candidate because the code does not exclude amendments or explicitly choose the latest matching filing.
   Files:
   `bulk_import_10k.py:286`
   `bulk_import_10k.py:293`
   `extractors/income_statement_extractor.py:76`
   `extractors/income_statement_extractor.py:116`
   `extractors/balance_sheet_extractor.py:76`
   `extractors/balance_sheet_extractor.py:116`
   `extractors/cash_flow_extractor.py:76`
   `extractors/cash_flow_extractor.py:116`

   `company.get_filings(form='10-K')` uses the library default `amendments=True`, so `10-K/A` filings are eligible everywhere this pattern appears. The helper functions then select the first filtered result with `filings_filtered[0]` instead of explicitly asking for the latest unamended filing. In practice that can make extraction and bulk import operate on amended filings or on an arbitrary match when a year has multiple related filings.

4. `companies.total_filings` is overstated because it increments once per statement insert, not once per filing.
   Files:
   `financial_statements_db.py:414`
   `financial_statements_db.py:501`
   `financial_statements_db.py:580`
   `financial_statements_db.py:620`
   `financial_statements_db.py:632`

   Each successful statement insert calls `_update_company()`, and `_update_company()` increments `total_filings` every time. A single 10-K with all three statements therefore increments the count by three. Any reporting based on `companies.total_filings` will be wrong and will drift farther as more imports succeed.

5. Database initialization rewrites `extraction_log` on every startup by creating a temp copy, dropping the real table, and recreating it.
   Files:
   `financial_statements_db.py:292`
   `financial_statements_db.py:314`
   `financial_statements_db.py:318`
   `financial_statements_db.py:335`

   `_create_schema()` always runs this migration block, even when no schema change is needed. That introduces unnecessary destructive DDL during normal startup. If the process crashes between `DROP TABLE` and the final restore, or if the restore fails because of a schema mismatch, the log can be lost or left corrupted. This should be a one-time migration, not part of routine initialization.

6. The mapping database never resyncs core mappings after the first database creation, so Python mapping updates can silently diverge from DuckDB state.
   Files:
   `xbrl_mapping_manager_multi_statement.py:79`
   `xbrl_mapping_manager_multi_statement.py:85`
   `xbrl_mapping_manager_multi_statement.py:88`

   `_sync_core_mappings()` only runs when the database has no tables at all. Once `xbrl_mappings_multi.duckdb` exists, changes made in the Python mapping files are not propagated. That creates a stale-cache problem where the codebase and the DB disagree about the current mapping set, which is especially risky for AI fallback behavior and analytics.

## Open Questions / Assumptions

- I assumed the intended behavior is to import unamended annual filings unless explicitly requested otherwise. The code and docs both read that way, but the current `get_filings(form='10-K')` calls do not enforce it.
- I treated incomplete multi-statement imports as a correctness bug rather than a reporting issue because downstream queries appear to expect all three statements for a filing.

## Testing Gaps

- I could not run a normal pytest suite because the project currently does not expose `pytest` in the environment. Running `uv run pytest -q` failed with `Failed to spawn: pytest`.
- The existing test coverage also appears fragmented: for example, [`test_prefix_stripping.py`](/home/pedro/projects/fin_import2/test_prefix_stripping.py) is a script with manual assertions rather than a pytest-collected test module. That makes regression detection harder and helps explain how the import-time configuration coupling and partial-import skip bug could slip through.

## Short Summary

The biggest correctness risks are in filing lifecycle handling: the importer can skip incomplete years, filing selection is too loose around amendments, and company-level filing counts are inflated. The next tier of risk is operational: extractors are hard to import without SEC credentials, and the database initialization path performs destructive log-table churn on every startup.
