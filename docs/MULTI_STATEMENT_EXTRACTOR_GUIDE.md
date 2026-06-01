# Multi-Statement Extractor System

## Architecture

Three financial statement extractors share a single core in `extractors/statement_extractor.py`.
Each statement type is a thin wrapper that supplies its own XBRL mapping, field sets, and
alternative statement names.

```
extractors/
  statement_extractor.py           Shared core: _extract_value(), extract_statement()
  income_statement_extractor.py    Wrapper: _AGG_FIELDS, _MAX_FIELDS, validation helpers
  balance_sheet_extractor.py       Wrapper: aggregation_fields=set()
  cash_flow_extractor.py           Wrapper: _AGG_FIELDS for "other_*_activities"

xbrl_mappings/
  income_statement_xbrl_mapping.py   30 fields, 415 concepts (tiered)
  balance_sheet_xbrl_mapping.py      38 fields, 693 concepts (tiered)
  cash_flow_xbrl_mapping.py          32 fields, 129 concepts (tiered)
  industry_overrides.py              8,140 industry-specific concepts (48 FF48 × 3 statements)
  sic_lookup.py                      SIC code → Fama-French 48 industry code
  bridge_mapping.json                131 edgartools standard_tag → field_name mappings
```

---

## Concept resolution — 3-layer pipeline

Every call to `_extract_value()` tries concepts in this order, stopping at the first match:

### Layer 1 — Industry overrides (prepended, tried first)

`xbrl_mappings/industry_overrides.py` holds 8,140 concepts keyed by
`INDUSTRY_OVERRIDES[statement][ff48_code][field_name]`. These are derived from
edgartools' `gaap_mappings.json` industry_overrides entries (confidence ≥ 0.6).

Before iterating the generic concept list, `_extract_value()` prepends the industry-specific
concepts for the company's Fama-French 48 industry code:

```python
from xbrl_mappings.industry_overrides import get_industry_concepts

concepts = list(mapping.get(field_name) or [])
if ff48_code:
    override = get_industry_concepts(statement_type, ff48_code, field_name)
    concepts = override + [c for c in concepts if c not in override]
```

This is the primary accuracy gain for banks (FF48=`Fin`), insurers (`Insur`), and REITs
(`RlEst`), which use completely different revenue and debt concepts than non-financial companies.

The `ff48_code` is resolved from the company's SIC code in `api/importer.py`:

```python
company = await asyncio.to_thread(lambda: Company(ticker))
sic = getattr(company, 'sic', None)
from xbrl_mappings.sic_lookup import get_ff48
ff48_code = get_ff48(sic)   # delegates to edgartools sic_to_fama_french()
```

### Layer 2 — Expanded static mapping (tiered by confidence)

Each field's concept list in the `.py` mapping files is ordered by resolution priority:

1. **Hand-curated core concepts** — original manually-verified entries (~5–10 per field)
2. **High-confidence edgartools expansion** (conf ≥ 0.7) — marked `# edgartools-expanded (conf=X.XX)`
3. **Lower-confidence edgartools expansion** (conf 0.5–0.69) — same tag, lower-trust last-resort

The expansion was generated from edgartools' `gaap_mappings.json` (2,924 raw concepts) via
`scripts/generate_expanded_mappings.py`, bridged to fin_import2 field names through
`xbrl_mappings/bridge_mapping.json` (131 standard_tag → field_name entries).

Concept counts before and after expansion:

| Statement | Fields | Pre-expansion | Post-expansion |
|-----------|--------|--------------|----------------|
| Income    | 30     | 125          | 415            |
| Balance   | 38     | 71           | 693            |
| Cash flow | 32     | 62           | 129            |

No concept appears in more than one field within the same statement (enforced by
`test_no_duplicate_concepts_across_fields_same_statement`).

### Layer 3 — AI fallback (optional, `use_ai_fallback=True`)

Unfound fields after Layers 1–2 go to `extractors/ai_batch_helper.py`:

- **Phase A** — free DB lookup: checks `ai_discovery_queue` in `xbrl_mappings_multi.duckdb`
  for prior AI classifications (seen ≥ 2 times auto-enriches the in-memory mapping)
- **Phase B** — batch API call: sends remaining unmapped XBRL concepts to Claude Haiku via
  OpenRouter in chunks of 20; requires `OPENROUTER_API_KEY` in `.env`

Newly discovered mappings are written to `ai_discovery_queue`. Unresolved fields and concepts
are written to `missed_concepts` with a reason code (`ai_disabled`, `no_match`, `api_failure`).
See `docs/AI_DISCOVERY_DATABASE_LOGGING.md`.

The Phase 2/3 expansion reduced the AI discovery queue by ~20% (71/348 concepts now covered
statically) and eliminates AI calls for the most common financial-sector concepts entirely.

---

## Extraction pipeline detail

Each call to `extract_statement()` runs:

**Mapping enrichment (before Pass 1)**

`get_enriched_mapping()` reads `ai_discovery_queue` and appends any concept seen ≥ 2 times to
the in-memory mapping dict. These resolve in Pass 1 at zero API cost.

**Pass 1 — static + industry mapping**

For each field, scan the XBRL DataFrame (non-dimension, non-abstract rows only) with concepts
ordered as: industry overrides → hand-curated → high-confidence expansion → lower-confidence
expansion → AI-enriched. Three resolution modes:

| Mode | Fields | Behaviour |
|------|--------|-----------|
| Default | most fields | first concept match wins |
| `aggregation_fields` | e.g. SG&A, D&A | sum all matching concepts |
| `max_fields` | `revenue`, `net_income`, `pretax_income`, `operating_income` | take the largest value across all matches |

The `max_fields` mode prevents understatement when a company reports both a specific concept
(`RevenueFromContractWithCustomerExcludingAssessedTax`) and a broader aggregate (`Revenues`).

**Pass 2 — AI fallback** (see Layer 3 above)

**Async design**

`extract_statement()` is fully async. The blocking SEC network call (`filing.xbrl()`) is
wrapped in `asyncio.to_thread()` so it does not hold the event loop during concurrent
bulk imports.

---

## edgartools compatibility

- `stmt.to_dataframe(presentation=False)` — extracts raw XBRL values with original signs.
  Do not use the default `presentation=True`, which negates expense/outflow values to match
  SEC HTML display; this causes sign inconsistency across companies imported at different times.
- Date column detection handles edgartools v5+ suffixes: `"2024-06-30 (FY)"`, `"2024-03-31 (Q1)"`,
  `"2024-06-30 (YTD)"` for duration periods; balance sheet instant periods use plain `"2024-06-30"`.
- `filing.report_date` is preferred over `filing.period_of_report` on `EntityFiling` objects —
  `report_date` is populated at zero cost; `period_of_report` triggers an SGML file download.

---

## Usage

```python
import asyncio
from edgar import set_identity, Company
from extractors.income_statement_extractor import extract_income_statement
from extractors.balance_sheet_extractor import extract_balance_sheet
from extractors.cash_flow_extractor import extract_cash_flow
from xbrl_mappings.sic_lookup import get_ff48

async def extract_all(ticker: str):
    set_identity('Your Name your@email.com')
    c = Company(ticker)
    filing = c.latest('10-K')

    # Resolve industry code from SIC for Layer 1 overrides
    ff48_code = get_ff48(getattr(c, 'sic', None))

    # AI fallback is on by default; pass use_ai_fallback=False to skip
    income_df  = await extract_income_statement(filing, ticker, '10-K', ff48_code=ff48_code)
    balance_df = await extract_balance_sheet(filing, ticker, '10-K', ff48_code=ff48_code)
    cf_df      = await extract_cash_flow(filing, ticker, '10-K', ff48_code=ff48_code)
    return income_df, balance_df, cf_df

income, balance, cashflow = asyncio.run(extract_all('AAPL'))
```

The `api/importer.py` entry point resolves `ff48_code` automatically and threads it through
all three extractor calls — callers using the HTTP API do not need to pass it manually.

---

## Fields extracted

### Income Statement (30 fields)

| Category | Fields |
|----------|--------|
| Revenue | `revenue`, `other_revenue` |
| Costs | `cost_of_revenue`, `gross_profit` |
| Operating | `selling_general_admin`, `research_development`, `depreciation_amortization`, `other_operating_expenses`, `total_operating_expenses`, `operating_income` |
| Non-operating | `interest_expense`, `interest_income`, `other_non_operating`, `pretax_income` |
| Tax & Net | `income_tax_expense`, `net_income`, `net_income_attributable_to_nci`, `net_income_attributable_to_parent` |
| Per share | `basic_eps`, `diluted_eps`, `basic_shares`, `diluted_shares` |
| Other | `restructuring_charges`, `other_comprehensive_income`, `comprehensive_income`, `discontinued_operations`, `investment_gains_losses`, `equity_method_investments`, `antidilutive_securities`, `net_income_continuing_ops`, `dividends_per_share`, `interest_income` |

### Balance Sheet (38 fields)

| Category | Fields |
|----------|--------|
| Current assets | `cash_and_equivalents`, `short_term_investments`, `accounts_receivable`, `inventory`, `prepaid_expenses`, `other_current_assets`, `total_current_assets` |
| Non-current assets | `ppe_net`, `ppe_gross`, `accumulated_depreciation`, `goodwill`, `intangible_assets`, `long_term_investments`, `deferred_tax_assets`, `other_noncurrent_assets`, `total_assets` |
| Current liabilities | `accounts_payable`, `short_term_debt`, `current_portion_long_term_debt`, `accrued_expenses`, `deferred_revenue_current`, `other_current_liabilities`, `total_current_liabilities` |
| Non-current liabilities | `long_term_debt`, `deferred_tax_liabilities`, `other_noncurrent_liabilities`, `total_liabilities` |
| Equity | `total_equity`, `retained_earnings`, `additional_paid_in_capital`, `treasury_stock`, `accumulated_other_comprehensive_income`, `noncontrolling_interest` |
| Other | `total_liabilities_and_equity`, `deferred_revenue_noncurrent`, `operating_lease_right_of_use_asset` |

### Cash Flow (32 fields)

| Category | Fields |
|----------|--------|
| Operating | `net_cash_operating_activities`, `depreciation_amortization`, `stock_based_compensation`, `deferred_taxes`, `change_accounts_receivable`, `change_inventory`, `change_accounts_payable`, `change_accrued_expenses`, `change_deferred_revenue`, `non_cash_stock_based_comp`, `other_operating_activities` |
| Investing | `capital_expenditures`, `acquisitions`, `proceeds_from_investments`, `purchases_of_investments`, `net_cash_investing_activities`, `other_investing_activities` |
| Financing | `repayment_of_debt`, `proceeds_from_debt`, `payments_of_dividends`, `common_stock_issuance`, `common_stock_repurchase`, `debt_issuance`, `other_financing_activities`, `net_cash_financing_activities` |
| Summary | `net_change_in_cash`, `cash_beginning_of_period`, `cash_end_of_period`, `effect_of_exchange_rate` |
| Supplemental | `cash_paid_for_income_taxes`, `cash_paid_for_interest` |

---

## Alternative statement names

Each wrapper supplies a fallback list tried when the primary accessor returns `None`:

| Statement | Primary accessor | Alt names tried |
|-----------|-----------------|-----------------|
| Income | `xbrl.statements.income_statement()` | `CONSOLIDATEDSTATEMENTSOFOPERATIONS`, `CONSOLIDATEDSTATEMENTSOFEARNINGS`, `StatementsOfIncome`, ... |
| Balance sheet | `xbrl.statements.balance_sheet()` | `CONDENSEDCONSOLIDATEDBALANCESHEETS`, `CONSOLIDATEDSTATEMENTSOFFINANCIALPOSITION`, `BalanceSheets`, ... |
| Cash flow | `xbrl.statements.cash_flow_statement()` | `CONDENSEDCONSOLIDATEDSTATEMENTSOFCASHFLOWS`, `CONSOLIDATEDSTATEMENTSOFCASHFLOWS`, `StatementsOfCashFlows`, ... |

---

## Mapping maintenance

### Checking coverage

```bash
uv run scripts/measure_coverage.py --tickers AAPL,MSFT,JPM --skip-dcf
```

Reads `missed_concepts` from `xbrl_mappings_multi.duckdb` for the most recent period per ticker.

### Expanding the static mapping

The expansion script is idempotent — re-running produces no changes against already-expanded files:

```bash
uv run scripts/generate_expanded_mappings.py \
    --gaap-mappings edgartools/edgar/xbrl/standardization/gaap_mappings.json \
    --bridge xbrl_mappings/bridge_mapping.json \
    --dry-run   # preview without writing
```

Remove `--dry-run` to apply. New concepts get `# edgartools-expanded (conf=X.XX)` comments.

### Adding industry overrides manually

Industry overrides for a specific FF48 code can be added directly to `xbrl_mappings/industry_overrides.py`:

```python
# In INDUSTRY_OVERRIDES['balance']['Fin']['long_term_debt']:
["LongTermDebtNoncurrent", "FederalHomeLoanBankAdvancesLongTerm", ...]
```

Use `get_industry_concepts(statement, ff48, field)` to query at runtime.

### Running the mapping test suite

```bash
uv run pytest tests/test_xbrl_mapping_expansion.py tests/test_industry_overrides.py -v
```

43 tests covering: no cross-field duplicates, known duplicate resolution, tiered ordering,
industry concept prioritisation, SIC → FF48 lookup, and extractor integration.
