# XBRL Ingestion — Implementation Reference

## Overview

The XBRL ingestion system resolves SEC EDGAR XBRL filing concepts to standardized financial
field names and writes results into `data/financial_statements.duckdb`. It is designed around
three ordered resolution layers that minimise AI API usage while maximising field coverage
across diverse company types.

---

## File map

```
xbrl_mappings/
  __init__.py                        Exports INCOME_STATEMENT_MAPPING, BALANCE_SHEET_MAPPING,
                                     CASH_FLOW_MAPPING (loaded once at import time)
  income_statement_xbrl_mapping.py   30 fields, 415 concepts
  balance_sheet_xbrl_mapping.py      38 fields, 693 concepts
  cash_flow_xbrl_mapping.py          32 fields, 129 concepts
  industry_overrides.py              8,140 concepts keyed by [statement][ff48_code][field]
  sic_lookup.py                      get_ff48(sic) → Fama-French 48 code or None
  bridge_mapping.json                131 edgartools standard_tag → fin_import2 field_name

extractors/
  statement_extractor.py             _extract_value(), extract_statement() — shared core
  income_statement_extractor.py      extract_income_statement(filing, ticker, form, ff48_code)
  balance_sheet_extractor.py         extract_balance_sheet(filing, ticker, form, ff48_code)
  cash_flow_extractor.py             extract_cash_flow(filing, ticker, form, ff48_code)
  ai_batch_helper.py                 Phase A (DB lookup) + Phase B (Claude Haiku via OpenRouter)

api/
  importer.py                        import_ticker() — resolves ff48_code, calls all extractors
  main.py                            FastAPI app; POST /import triggers import_ticker()

scripts/
  generate_expanded_mappings.py      One-shot: expands .py mapping files from gaap_mappings.json
  measure_coverage.py                Reads missed_concepts → per-ticker hit rate report
  reimport_all.py                    Re-imports tickers from EDGAR into financial_statements.duckdb

data/
  financial_statements.duckdb        Main DB: income_statements, balance_sheets, cash_flow_statements
  xbrl_mappings_multi.duckdb         AI audit DB: ai_discovery_queue, missed_concepts
```

---

## Resolution order inside `_extract_value()`

```
Call: _extract_value(statement_df, field_name, year_column, mapping,
                     aggregation_fields, max_fields, ff48_code)

1. Build concept list
   a. Start with mapping[field_name]                  (static expanded list)
   b. Prepend get_industry_concepts(stmt, ff48, field) (industry overrides, tried first)
   c. Deduplicate preserving order

2. Scan XBRL DataFrame rows (non-dimension, non-abstract only)
   - Default:            first matching concept → return value
   - aggregation_fields: sum all matching concepts
   - max_fields:         take max value across all matches

3. Return (value, concept_name) or (None, None)
```

---

## Static mapping structure

Each `.py` mapping file is a plain dict: `{field_name: [concept, ...]}`. Concepts are ordered
by resolution priority — the first match in the XBRL filing wins for most fields.

Within each field the ordering is:

```python
"revenue": [
    # 1. Hand-curated core (original, manually verified)
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    # ...

    # 2. High-confidence edgartools expansion (conf >= 0.7)
    # --- edgartools high-confidence ---
    "SalesRevenueNet",               # edgartools-expanded (conf=0.85)

    # 3. Lower-confidence edgartools expansion (conf 0.5-0.69, last resort)
    # --- edgartools lower-confidence ---
    "RevenueFromRelatedParties",     # edgartools-expanded (conf=0.50)
]
```

**Invariants enforced by the test suite:**
- No concept appears in more than one field within the same statement
- All hand-curated concepts appear before any edgartools-expanded concept in the same field
- High-confidence concepts precede lower-confidence concepts within each field

---

## Industry overrides

`xbrl_mappings/industry_overrides.py` was generated from `gaap_mappings.json` industry_overrides
entries using `scripts/generate_expanded_mappings.py --industry-overrides-only`. It contains
concepts for 48 Fama-French industry codes × 3 statements, selectively covering fields where
industry structure diverges from the generic mapping (primarily revenue and debt fields for
financial companies).

Key examples:

| Industry (FF48) | Field | Industry concepts |
|----------------|-------|-------------------|
| `Fin` (banks) | `revenue` | `InterestAndFeeIncomeLoansAndLeases`, `NoninterestIncome`, ... |
| `Fin` (banks) | `long_term_debt` | `ConvertibleDebtNoncurrent`, `FinanceLeaseLiabilityNoncurrent`, ... |
| `Insur` | `cost_of_revenue` | `PolicyholderBenefitsAndClaimsIncurredNet`, ... |

The `sic_lookup.get_ff48(sic)` function delegates to edgartools' `sic_to_fama_french()` with
no duplication of the SIC range tables.

---

## How the importer threads ff48_code

```python
# api/importer.py (simplified)
async def import_ticker(ticker, periods, period_type, db, ...):
    company = await asyncio.to_thread(lambda: Company(ticker))
    ff48_code = get_ff48(getattr(company, 'sic', None))

    for filing in filings:
        income_df  = await extract_income_statement(filing, ticker, form,
                                                     ff48_code=ff48_code)
        balance_df = await extract_balance_sheet(filing, ticker, form,
                                                  ff48_code=ff48_code)
        cf_df      = await extract_cash_flow(filing, ticker, form,
                                              ff48_code=ff48_code)
        db.insert_income_statement(income_df)
        db.insert_balance_sheet(balance_df)
        db.insert_cash_flow_statement(cf_df)
```

---

## AI fallback

The AI layer is a last resort after both industry overrides and the 1,237-concept static
mapping fail. It sends unresolved XBRL concepts to Claude Haiku via OpenRouter in batches of 20.

Key behaviour:
- Phase A (free): checks `ai_discovery_queue` for prior classifications — concepts seen ≥ 2
  times across any tickers are auto-promoted into the in-memory mapping before Pass 1
- Phase B (paid): batch API call only for truly novel concepts
- All results (success and failure) are written to `xbrl_mappings_multi.duckdb`

To disable: pass `use_ai_fallback=False` to any extractor, or omit `OPENROUTER_API_KEY` from `.env`.

---

## Mapping expansion workflow

The static mapping was expanded from edgartools' `gaap_mappings.json` (2,924 raw concepts)
via `bridge_mapping.json` (131 standard_tag → field_name entries). To re-generate or extend:

```bash
# Preview changes (safe, no writes)
uv run scripts/generate_expanded_mappings.py \
    --gaap-mappings edgartools/edgar/xbrl/standardization/gaap_mappings.json \
    --bridge xbrl_mappings/bridge_mapping.json \
    --dry-run

# Apply (idempotent — re-running produces no diff)
uv run scripts/generate_expanded_mappings.py \
    --gaap-mappings edgartools/edgar/xbrl/standardization/gaap_mappings.json \
    --bridge xbrl_mappings/bridge_mapping.json

# Run tests to verify no regressions
uv run pytest tests/test_xbrl_mapping_expansion.py tests/test_industry_overrides.py -v
```

Concepts with `industry_overrides` in `gaap_mappings.json` are intentionally excluded from
the generic expansion and handled only via `industry_overrides.py`. Any concept appearing in
the generic expansion was confirmed to have no industry_overrides (sector-agnostic).

---

## Coverage measurement

```bash
# Measure field hit rates from missed_concepts in xbrl_mappings_multi.duckdb
uv run scripts/measure_coverage.py --tickers AAPL,MSFT,JPM,BAC --skip-dcf

# Re-import tickers to apply expanded mappings to historical data
uv run scripts/reimport_all.py --tickers AAPL MSFT JPM --annual-only
```

Coverage reads the most-recent period per ticker from the `missed_concepts` table. Improvement
from mapping expansion is only visible after re-importing; the DB stores the mapping state at
import time, not the current state of the `.py` files.

---

## DCF NULL guard

`dcf/model.py::_run_dcf_core()` checks 8 critical fields on entry and appends non-blocking
warnings to the result when any are NULL across all periods:

```
income:  revenue, operating_income, pretax_income, income_tax_expense, diluted_shares
balance: long_term_debt, cash_and_equivalents
cashflow: depreciation_amortization, capital_expenditures
```

These warnings surface in the API response and web UI without blocking computation.
