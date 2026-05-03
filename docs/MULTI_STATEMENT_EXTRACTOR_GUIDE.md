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
  income_statement_xbrl_mapping.py  30 fields, 125+ concepts
  balance_sheet_xbrl_mapping.py     37 fields, 63 concepts
  cash_flow_xbrl_mapping.py         31 fields, 50 concepts
```

## Extraction pipeline

Each call to `extract_statement()` opens a single `XBRLMappingManager` connection for the
duration of the call, then runs:

**Mapping enrichment (before Pass 1)**

`get_enriched_mapping()` reads `ai_discovery_queue` in `data/xbrl_mappings_multi.duckdb` and
appends any concept seen **2 or more times** to the in-memory mapping dict. These enriched
concepts resolve in Pass 1 at zero API cost — no AI call needed.

**Pass 1 — static mapping**

For each field in the mapping, scan the XBRL DataFrame (non-dimension, non-abstract rows only)
for matching concepts. Three resolution modes:

| Mode | Fields | Behaviour |
|------|--------|-----------|
| Default | most fields | first concept match wins |
| `aggregation_fields` | e.g. SG&A, D&A | sum all matching concepts |
| `max_fields` | `revenue`, `net_income`, `pretax_income`, `operating_income` | take the largest value across all matches |

The `max_fields` mode prevents understatement when a company reports both a specific concept
(e.g. `RevenueFromContractWithCustomerExcludingAssessedTax`) and a broader aggregate (`Revenues`).
The larger value is always the correct total line — verified against WMT (Walmart), which splits
contract revenue ($706B) from membership/other income ($6.75B), summing to `Revenues` ($713B).

**Pass 2 — AI fallback (on by default, disable with `--no-ai`)**

Unfound fields are resolved via `extractors/ai_batch_helper.py`:

- **Phase A** — free DB lookup: checks `ai_discovery_queue` for prior AI classifications
- **Phase B** — batch API call: sends remaining unmapped concepts to Claude Haiku via OpenRouter
  in chunks of 20; requires `OPENROUTER_API_KEY` in `.env`

Newly discovered mappings are logged to `ai_discovery_queue`. Every concept or field that
remains unresolved after all passes is logged to `missed_concepts` with a reason code
(`ai_disabled`, `no_match`, `api_failure`). See `docs/AI_DISCOVERY_DATABASE_LOGGING.md`.

**Async design**

`extract_statement()` is fully async. The blocking SEC network call (`filing.xbrl()`) is
wrapped in `asyncio.to_thread()` so it does not hold the event loop during concurrent
bulk imports.

## edgartools compatibility

- `stmt.to_dataframe(presentation=False)` — extracts raw XBRL values with original signs.
  Do not use the default `presentation=True`, which negates expense/outflow values to match
  SEC HTML display; this causes sign inconsistency across companies imported at different times.
- Date column detection handles edgartools v5+ suffixes: `"2024-06-30 (FY)"`, `"2024-03-31 (Q1)"`,
  `"2024-06-30 (YTD)"` for duration periods; balance sheet instant periods use plain `"2024-06-30"`.
- `filing.report_date` is preferred over `filing.period_of_report` on `EntityFiling` objects —
  `report_date` is populated at zero cost; `period_of_report` triggers an SGML file download.

## Fields extracted

### Income Statement (30 fields)

| Category | Fields |
|----------|--------|
| Revenue | `revenue`, `other_revenue` |
| Costs | `cost_of_revenue`, `gross_profit` |
| Operating | `selling_general_admin`, `research_development`, `depreciation_amortization`, `other_operating_expenses`, `total_operating_expenses`, `operating_income` |
| Non-operating | `interest_expense`, `interest_income`, `other_non_operating`, `pretax_income` |
| Tax & Net | `income_tax`, `net_income`, `minority_interest`, `net_income_common` |
| Per share | `eps_basic`, `eps_diluted`, `shares_basic`, `shares_diluted` |
| Other | `ebitda`, `ebit`, `total_revenue` |

### Balance Sheet (37 fields)

| Category | Fields |
|----------|--------|
| Current assets | `cash`, `short_term_investments`, `accounts_receivable`, `inventory`, `other_current_assets`, `total_current_assets` |
| Non-current assets | `ppe_net`, `goodwill`, `intangible_assets`, `long_term_investments`, `other_non_current_assets`, `total_non_current_assets`, `total_assets` |
| Current liabilities | `accounts_payable`, `short_term_debt`, `accrued_expenses`, `deferred_revenue_current`, `other_current_liabilities`, `total_current_liabilities` |
| Non-current liabilities | `long_term_debt`, `deferred_tax_liabilities`, `other_non_current_liabilities`, `total_non_current_liabilities`, `total_liabilities` |
| Equity | `common_stock`, `retained_earnings`, `aoci`, `additional_paid_in_capital`, `treasury_stock`, `total_equity`, `total_liabilities_and_equity` |
| Other | `minority_interest_bs`, `total_debt` |

### Cash Flow (31 fields)

| Category | Fields |
|----------|--------|
| Operating | `net_income_cf`, `depreciation_amortization_cf`, `stock_based_compensation`, `change_working_capital`, `other_operating_activities`, `operating_cash_flow` |
| Investing | `capital_expenditures`, `acquisitions`, `purchase_investments`, `sale_investments`, `other_investing_activities`, `investing_cash_flow` |
| Financing | `debt_issuance`, `debt_repayment`, `stock_issuance`, `stock_repurchase`, `dividends_paid`, `other_financing_activities`, `financing_cash_flow` |
| Summary | `net_change_cash`, `beginning_cash`, `ending_cash` |
| Supplemental | `cash_interest_paid`, `cash_taxes_paid`, `free_cash_flow` |

## Usage

```python
import asyncio
from edgar import set_identity, Company
from extractors.income_statement_extractor import extract_income_statement
from extractors.balance_sheet_extractor import extract_balance_sheet
from extractors.cash_flow_extractor import extract_cash_flow

async def extract_all(ticker: str):
    set_identity('Your Name your@email.com')
    c = Company(ticker)
    filing = c.latest('10-K')

    # AI fallback is on by default; pass use_ai_fallback=False to skip
    income_df  = await extract_income_statement(filing, ticker, '10-K')
    balance_df = await extract_balance_sheet(filing, ticker, '10-K')
    cf_df      = await extract_cash_flow(filing, ticker, '10-K')
    return income_df, balance_df, cf_df

income, balance, cashflow = asyncio.run(extract_all('AAPL'))
```

## Alternative statement names

Each wrapper supplies a fallback list tried when the primary accessor returns `None`:

| Statement | Primary accessor | Alt names tried |
|-----------|-----------------|-----------------|
| Income | `xbrl.statements.income_statement()` | `CONSOLIDATEDSTATEMENTSOFOPERATIONS`, `CONSOLIDATEDSTATEMENTSOFEARNINGS`, `StatementsOfIncome`, ... |
| Balance sheet | `xbrl.statements.balance_sheet()` | `CONDENSEDCONSOLIDATEDBALANCESHEETS`, `CONSOLIDATEDSTATEMENTSOFFINANCIALPOSITION`, `BalanceSheets`, ... |
| Cash flow | `xbrl.statements.cash_flow_statement()` | `CONDENSEDCONSOLIDATEDSTATEMENTSOFCASHFLOWS`, `CONSOLIDATEDSTATEMENTSOFCASHFLOWS`, `StatementsOfCashFlows`, ... |
