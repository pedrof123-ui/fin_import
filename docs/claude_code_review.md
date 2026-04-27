# Code Review: fin_import2

Date: 2026-04-02

## Overview

This project is a financial data import pipeline that extracts normalized financial statements (income, balance sheet, cash flow) from SEC EDGAR XBRL filings. It solves the hard problem of XBRL concept heterogeneity: different companies use different concept names for the same line item (e.g., `RevenueFromContractWithCustomerExcludingAssessedTax` vs. `Revenues` vs. `SalesRevenueNet`). The approach is a hybrid two-pass system: a large hand-curated static mapping handles the common cases, and an LLM with a DuckDB-backed discovery cache handles the rest.

The core architecture is sound and the central design decisions are good. Most issues are maintenance and hygiene problems from iterative development rather than fundamental design flaws.

---

## Architecture Summary

```
Ticker + filing type
  -> edgartools (XBRL document)
  -> Pass 1: static mapping lookup (xbrl_mappings/ dicts)
  -> Pass 2a: DB cache of prior AI discoveries (xbrl_mappings_multi.duckdb)
  -> Pass 2b: batch LLM classification (xbrl_concept_mapper.py via openai-agents)
  -> financial_statements.duckdb (output storage)
```

Two DuckDB databases with distinct responsibilities:
- `xbrl_mappings_multi.duckdb` — mapping intelligence, AI discovery queue, promotion pipeline
- `financial_statements.duckdb` — final output (wide-format normalized statements)

---

## Strengths

**Two-pass extraction design.** Pass 1 is a zero-cost static lookup. Pass 2a uses a DB cache so that concepts seen in prior extractions never require another AI call. Pass 2b is a last resort that batches all remaining unmapped concepts in one LLM call (rather than one call per concept). This is a well-considered cost/latency optimization.

**Promotion pipeline.** `XBRLMappingManager.get_promotion_candidates()` / `promote_ai_to_core()` provide a path for AI-discovered concepts to graduate into the static mapping once they've been used successfully 10+ times with 90%+ accuracy. The system genuinely learns over time without code changes.

**`test_prefix_stripping.py`** is a proper, focused unit test with mock DataFrames covering all three statement types and edge cases (namespace prefixes, aggregation, missing concepts). It is the best file in the project.

**Utility scripts** (`export_mappings.py`, `delete_statement_concepts.py`, `strip_cf_prefixes.py`) are clean and focused. `strip_cf_prefixes.py` in particular demonstrates good discipline: preview before act, check for duplicates, verify result.

**DuckDB is the right tool.** Analytical queries over wide DataFrames, no server overhead, good pandas interop via `.df()`.

---

## Issues

### Critical

**1. `financial_statements_db.py:309-337` — Destructive schema migration runs on every init**

Every instantiation of `FinancialStatementsDB` runs a temp-table migration sequence:
```python
# Runs unconditionally in __init__ -> _create_schema()
CREATE TABLE IF NOT EXISTS extraction_log_temp AS SELECT * FROM extraction_log
DROP TABLE IF EXISTS extraction_log
CREATE TABLE extraction_log (...)         # adds DEFAULT nextval(...)
INSERT INTO extraction_log SELECT * FROM extraction_log_temp
DROP TABLE extraction_log_temp
```
If anything crashes between the `DROP` and `CREATE`, data is permanently lost. The fix is to remove the workaround entirely: DuckDB supports `CREATE SEQUENCE IF NOT EXISTS` (already done at line 309) and `CREATE TABLE IF NOT EXISTS` with `DEFAULT nextval(...)`. The migration block is unnecessary from first principles.

**2. `financial_statements_db.py:366` — `fields_extracted` counts emoji, not actual coverage**

Coverage is calculated as:
```python
fields_extracted = len(df[df['Status'] == '✓'])
```
This hardcodes a UI emoji as a sentinel value in business logic, coupling the display layer to storage. If the extractor ever changes the status marker, coverage silently becomes 0%.

**3. `map_cf_concepts.py:162-164` — Bug: result dict always uses last `gemini_response`**

```python
grok_response_dicts = [
    {"concept": concept[0], "cashflow_mapping": gemini_response.choices[0].message.content}
    for concept, response in zip(concepts_list, grok_response)
]
```
`gemini_response` is the loop variable from the last iteration — it is not the per-concept response. The `response` variable from `zip` (which holds the correctly-chosen result) is unused. This means the output file contains the last concept's Gemini response for every concept, discarding the decider's choices entirely. Same bug is present in `map_bs_concepts.py` and `map_inc_concepts.py`.

---

### High

**4. `get_filing()` and `parse_date()` are copy-pasted across all three extractors**

Both functions are verbatim copies in `income_statement_extractor.py`, `balance_sheet_extractor.py`, and `cash_flow_extractor.py`. A bug fix must be applied three times. These belong in a shared module (e.g., `extractors/edgar_helpers.py` or directly in `extractors/__init__.py`).

The same applies to the ~35-line AI discovery logging block at the end of each `extract_*` function body (differs only in the string literal `'income'`/`'balance'`/`'cashflow'`).

**5. `map_inc_concepts.py:105-108` — API key printed to stdout in a loop**

```python
for concept in concepts_list:
    openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
    print(openrouter_api_key)   # leaks key to console on every iteration
```
The key is re-fetched and printed on each loop iteration. Same pattern in `map_bs_concepts.py` and `map_cf_concepts.py`.

**6. `xbrl_concept_mapper.py:47-49` — Global singleton with no reset path on failure**

```python
_agent = None
_file_server = None
_initialized = False
```
If `_initialize_agent()` fails partway through, `_initialized` stays `False` and every subsequent call retries initialization from scratch, potentially spawning duplicate MCP servers. There is no cleanup path for a partial init.

**7. `extractors/__init__.py` only exports income statement functions**

The package exports `get_filing` and `extract_income_statement` but not `extract_balance_sheet` or `extract_cash_flow`. Callers cannot import all three extractors via the package interface consistently.

---

### Medium

**8. `financial_statements_db.py:extraction_log` is dead infrastructure**

The `extraction_log` table in `financial_statements.duckdb` is built and maintained but never written to by the actual extraction pipeline. All extraction logging uses `ai_discovery_queue` and `extraction_log` in `xbrl_mappings_multi.duckdb` instead. This creates confusion about where to look for audit data.

**9. Bare `except:` in multiple extractors**

Several exception handlers use `except:` (no type) instead of `except Exception:`, which silently swallows `KeyboardInterrupt`, `SystemExit`, and other non-error exceptions:
- `cash_flow_extractor.py:277`
- `balance_sheet_extractor.py:255`
- `income_statement_extractor.py:287`
- `xbrl_concept_mapper.py:386` (cleanup block)

**10. `map_*.py` scripts import unused symbols**

All three `map_*` scripts import `AsyncOpenAI`, `asyncio`, `random`, and `tqdm` but never use them. An `openai` client is also defined at module level but unused. These accumulate from iterative development but add noise.

**11. `pyproject.toml:9` — `asyncio` is a stdlib module, not a pip dependency**

```toml
"asyncio>=4.0.0",
```
`asyncio` is part of the Python standard library and should not be in `dependencies`. The `>=4.0.0` version constraint is also non-sensical (the stdlib module has no public PyPI version). Similarly, `dotenv>=0.9.9` should be `python-dotenv` (already listed separately as `"python-dotenv"`), and `agents>=1.4.0` duplicates `openai-agents>=0.8.0`.

**12. `map_*.py` model names appear non-existent**

`openai_model = "gpt-5.2-2025-12-11"` and `gemini_model = "gemini-3-flash-preview"` do not correspond to real model names and would fail at runtime. Since these are offline utilities the impact is contained, but they should be updated to real model identifiers or removed.

---

### Low

**13. Emoji in production print statements throughout**

`financial_statements_db.py`, `income_statement_extractor.py`, `balance_sheet_extractor.py`, `cash_flow_extractor.py`, and `bulk_import_10k.py` all use emoji (`✓`, `✗`, `📋`, `💾`, `🚀`) in `print()` statements. The project's own `CLAUDE.md` prohibits emoji.

**14. `map_bs_concepts.py` docstring says "MAPS CF CONCEPTS"**

Copy-paste artifact — the module docstring (and `map_cf_concepts.py` similarly) reference the wrong statement type.

**15. `compare_files.py` and `compare_files_notebook.py` are dead code**

Both files reference hardcoded paths to files that no longer exist (`step35_response_dicts.txt`, `qwen_response_dicts.txt`) and appear to be abandoned development artifacts.

---

## Testing

The only automated test is `test_prefix_stripping.py`. It uses a home-rolled assertion framework (`check()` function, `passed`/`failed` counters) instead of pytest. Coverage is limited to the concept extraction logic for a mocked single-row DataFrame.

There are no tests for:
- The two-pass extraction flow end-to-end
- Phase A DB discovery in `ai_batch_helper.py`
- `XBRLMappingManager` methods
- `FinancialStatementsDB` insert/query correctness
- Bulk import orchestration

The `.ipynb` files (`test_xbrl_mapper.ipynb`, `test_concepts_agent.ipynb`) are exploratory notebooks, not automated tests.

---

## Dependency Notes

| Dependency | Note |
|---|---|
| `asyncio>=4.0.0` | stdlib module, remove from pyproject.toml |
| `dotenv>=0.9.9` | wrong package name; `python-dotenv` already listed |
| `agents>=1.4.0` | appears to duplicate `openai-agents>=0.8.0` |
| `edgartools` | no version pin — consider pinning for reproducibility |

---

## Prioritized Recommendations

1. **Fix the destructive schema init** in `financial_statements_db.py:309-337` — data loss risk on crash.
2. **Extract `get_filing()` and `parse_date()`** to a shared module — eliminates the three-way copy-paste.
3. **Fix the result-dict bug** in `map_cf_concepts.py:162-164` (and equivalents in `map_bs_concepts.py`, `map_inc_concepts.py`).
4. **Remove API key `print()`** from the `map_*.py` loops.
5. **Fix `pyproject.toml`** — remove `asyncio`, deduplicate `dotenv`/`python-dotenv` and `agents`/`openai-agents`.
6. **Replace bare `except:` with `except Exception:`** in the three extractors and `xbrl_concept_mapper.py`.
7. **Decouple `fields_extracted` from the emoji sentinel** in `financial_statements_db.py`.
8. **Add pytest** and write integration tests for the two-pass extraction flow and `XBRLMappingManager`.
