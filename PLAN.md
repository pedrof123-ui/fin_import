# PLAN: Integrate edgartools gaap_mappings as Expanded Static Concept Layer

**Goal:** Replace AI-fallback concept resolution with expanded static mappings derived from
edgartools' `gaap_mappings.json` (2,924 concepts), add industry-override support using the
Fama-French 48 SIC classification already in edgartools, and harden the DCF against NULL
fields caused by coverage gaps.

**Constraint:** No schema changes to DuckDB tables. No changes to the DCF model logic.
All changes are in the ingestion layer (extractors + xbrl_mappings).

---

## Pre-implementation findings

Analysis of `gaap_mappings.json` against the existing mappings revealed three facts that
shape implementation decisions:

**1. Expansion at confidence ≥ 0.7 is conservative — 132 net-new concepts total.**
The median confidence in gaap_mappings is 0.50; the 0.7 threshold filters out ~80% of
candidates. Actual additions by statement at this threshold:

| Statement | Currently | +conf≥0.7 | +conf≥0.5 (tiered) |
|-----------|-----------|-----------|---------------------|
| Income | 125 | +31 | +~350 additional |
| Balance | 71 | +54 | +~500 additional |
| Cash flow | 62 | +47 | +~200 additional |

Phase 2 uses a **tiered approach**: concepts with confidence ≥ 0.7 are appended
immediately after existing entries (high trust); concepts with confidence 0.5–0.69 are
appended after those (lower trust, last-resort fallback). This captures broader coverage
while preserving priority ordering.

**2. Five existing intra-statement duplicates must be fixed before expansion.**
The current mapping files already contain these conflicts (found by inspection):

| Statement | Concept | Conflicting fields |
|-----------|---------|-------------------|
| income | `InterestAndDividendIncomeOperating` | `revenue` and `interest_income` |
| income | `CostOfGoodsAndServicesSold` | `cost_of_revenue` (listed twice — exact duplicate) |
| income | `NetIncomeLossAvailableToCommonStockholdersBasic` | `net_income` and `net_income_attributable_to_parent` |
| cashflow | `ShareBasedCompensation` | `stock_based_compensation` and `non_cash_stock_based_comp` |
| cashflow | `CashCashEquivalentsRestrictedCash...` | `cash_beginning_of_period` and `cash_end_of_period` |

The expansion script must deduplicate against every field in the statement (not just the
target field) to avoid inheriting these patterns into new concepts. Fixing the five
existing duplicates is a prerequisite for Phase 2.

**3. The 15 apparent statement-type conflicts are not real conflicts.**
Several concepts (e.g., `NetIncomeLoss`, `DepreciationDepletionAndAmortization`,
`DeferredIncomeTaxExpenseBenefit`) appear in both the existing cashflow mapping and as
`IncomeStatement` entries in gaap_mappings. This is correct: XBRL allows dual-statement
concepts, and edgartools classifies them by most common occurrence (income statement)
while fin_import2 correctly reads them from the cash flow statement for CF purposes.
The expansion script's statement-based filter (`statement=CashFlowStatement` for CF
fields) prevents these from being added to the wrong statement.

**4. Phase 3 (industry overrides) delivers more DCF value than Phase 2 (generic expansion).**
The critical DCF NULLs — revenue for banks, debt fields for financials — live in the
industry-specific override layer, not in the generic confidence-filtered expansion.
Phase 2 at 0.7 confidence adds 132 concepts that mostly improve coverage for already
well-covered non-financial companies. Phase 3 fixes the fields that currently produce
wrong or missing intrinsic values for JPM, BAC, GS, and UNH. If schedule pressure
requires choosing, Phase 3 should be prioritised over Phase 2.

---

## Architecture overview

```
edgartools/edgar/xbrl/standardization/
  gaap_mappings.json          ← 2,924 raw GAAP concept → {standard_tag, statement,
                                  section, confidence, industry_overrides}
  sic_industry.py             ← SIC range → FF48 industry code

fin_import2/
  xbrl_mappings/
    bridge_mapping.json       ← NEW: standard_tag → field_name (one-time manual)
    income_statement_xbrl_mapping.py   ← EXPANDED
    balance_sheet_xbrl_mapping.py      ← EXPANDED
    cash_flow_xbrl_mapping.py          ← EXPANDED
    industry_overrides.py     ← NEW: field_name × ff48_code → [concept, ...]
  extractors/
    statement_extractor.py    ← MODIFIED: _extract_value accepts sic_code
    income_statement_extractor.py  ← MODIFIED: pass sic to extract_statement
    balance_sheet_extractor.py     ← MODIFIED: pass sic to extract_statement
    cash_flow_extractor.py         ← MODIFIED: pass sic to extract_statement
  scripts/
    generate_expanded_mappings.py  ← NEW: one-shot expansion script
    measure_coverage.py            ← NEW: baseline + regression metrics
  tests/
    test_xbrl_mapping_expansion.py ← NEW
    test_industry_overrides.py     ← NEW
    test_dcf_coverage.py           ← NEW
```

---

## Phase 0 — Baseline measurement ✓ COMPLETE

**Purpose:** Establish quantitative before-state so each subsequent phase has a measurable
pass/fail criterion. No production code changes.

### 0.1 Build a coverage measurement script

Create `scripts/measure_coverage.py`:

```
uv run scripts/measure_coverage.py --tickers AAPL,MSFT,JPM,BAC,UNH,GS,WMT,XOM,PFE,BRK-B \
    --form 10-K --db data/financial_statements.duckdb --out docs/coverage_baseline.json
```

The script reads existing imported data from DuckDB and computes per-ticker, per-statement:
- `fields_found` / `fields_total` — static hit rate
- `fields_ai_discovered` — AI fallback rate
- `fields_null` — permanently missing after all passes
- `ai_cost_calls` — AI API calls during last import (from DuckDB ai_discovery_queue)

Critical DCF fields to track explicitly:
`revenue`, `operating_income`, `gross_profit`, `cost_of_revenue`, `long_term_debt`,
`short_term_debt`, `current_portion_long_term_debt`, `cash_and_equivalents`,
`depreciation_amortization` (CF), `capital_expenditures`, `diluted_shares`, `pretax_income`.

### 0.2 Snapshot DCF outputs

For each ticker in the baseline corpus, run `run_dcf()` and record:
- `intrinsic_value_per_share`
- `wacc`
- `net_debt`
- `diluted_shares`
- `terminal_value`

Store to `docs/dcf_baseline.json`. This is the regression anchor for Phase 4 and 5.

### 0.3 Measure AI fallback rate on a fresh re-import

Re-import 3 tickers (one standard: AAPL, one bank: JPM, one insurance: UNH) with
`use_ai_fallback=True` and count API calls logged to `ai_discovery_queue`. Record in
`docs/ai_baseline.json`.

**Exit criteria:** `docs/coverage_baseline.json`, `docs/dcf_baseline.json`, and
`docs/ai_baseline.json` all written. No code changes merged yet.

**Results (2026-05-31):** Baseline captured for 12 tickers. Income hit rate 47–63%,
balance 53–82%, cash flow 56–97%. DCF-critical misses: `depreciation_amortization` (IS,
9 tickers), `current_portion_long_term_debt` (BS, 9 tickers), `gross_profit` (IS, 5),
`operating_income` (IS, 3). DCF baseline written via API for 14/15 tickers.

---

## Phase 1 — Bridge mapping: standard_tags → field_names ✓ COMPLETE

**Purpose:** Create a durable, human-reviewed mapping between edgartools' 235 `standard_tags`
and fin_import2's 100 `field_names`. This is a one-time artifact, not generated code.

### 1.1 Generate candidate mapping

Create `scripts/generate_bridge_candidates.py`:

```python
# Loads gaap_mappings.json, extracts all unique standard_tags, groups by statement type,
# and produces a candidate JSON with auto-matched and unmatched tags.
```

Auto-match logic:
- Normalize both sides: lowercase, strip underscores/camelCase → snake_case tokens
- Exact token match → `status: auto`
- No match → `status: manual`

Output `xbrl_mappings/bridge_mapping_candidates.json` (not committed as final).

### 1.2 Manual review and finalization

Review the candidates file and produce `xbrl_mappings/bridge_mapping.json`:

```json
{
  "_meta": {
    "source": "edgartools/edgar/xbrl/standardization/gaap_mappings.json",
    "generated": "2026-05-31",
    "total_tags": 235,
    "mapped": 0,
    "unmapped": 0
  },
  "IncomeStatement": {
    "NetRevenue":              "revenue",
    "CostOfGoodsAndServicesSold": "cost_of_revenue",
    "GrossProfit":             "gross_profit",
    "OperatingIncome":         "operating_income",
    "EBIT":                    "operating_income",
    "ResearchAndDevelopment":  "research_development",
    "SellingGeneralAdmin":     "selling_general_admin",
    "InterestExpense":         "interest_expense",
    "InterestIncome":          "interest_income",
    "PreTaxIncome":            "pretax_income",
    "IncomeTaxExpense":        "income_tax_expense",
    "NetIncome":               "net_income",
    "EPS":                     "diluted_eps",
    "BasicEPS":                "basic_eps",
    "DilutedEPS":              "diluted_eps",
    "DilutedShares":           "diluted_shares",
    "BasicShares":             "basic_shares",
    "DepreciationAndAmortization": "depreciation_amortization"
  },
  "BalanceSheet": {
    "CashAndCashEquivalents":  "cash_and_equivalents",
    "ShortTermInvestments":    "short_term_investments",
    "TradeReceivables":        "accounts_receivable",
    "Inventories":             "inventory",
    "CurrentAssetsTotal":      "total_current_assets",
    "PropertyPlantEquipment":  "ppe_net",
    "Goodwill":                "goodwill",
    "IntangibleAssets":        "intangible_assets",
    "Assets":                  "total_assets",
    "AccountsPayable":         "accounts_payable",
    "ShortTermDebt":           "short_term_debt",
    "CurrentPortionOfLongTermDebt": "current_portion_long_term_debt",
    "AccruedLiabilities":      "accrued_expenses",
    "CurrentLiabilitiesTotal": "total_current_liabilities",
    "LongTermDebt":            "long_term_debt",
    "DeferredTaxNonCurrentLiabilities": "deferred_tax_liabilities",
    "Liabilities":             "total_liabilities",
    "CommonEquity":            "total_equity",
    "RetainedEarnings":        "retained_earnings",
    "AdditionalPaidInCapital": "additional_paid_in_capital",
    "TreasuryStock":           "treasury_stock"
  },
  "CashFlowStatement": {
    "OperatingCashFlow":       "net_cash_operating_activities",
    "CapitalExpenses":         "capital_expenditures",
    "InvestingCashFlow":       "net_cash_investing_activities",
    "FinancingCashFlow":       "net_cash_financing_activities",
    "DeferredIncomeTaxCF":     "deferred_taxes",
    "StockBasedCompensation":  "stock_based_compensation",
    "DepreciationAmortizationCF": "depreciation_amortization",
    "ChangeInReceivables":     "change_accounts_receivable",
    "ChangeInInventory":       "change_inventory",
    "ChangeInPayables":        "change_accounts_payable",
    "AcquisitionsNet":         "acquisitions",
    "DebtRepayments":          "repayment_of_debt",
    "DebtProceeds":            "proceeds_from_debt",
    "CommonDividendsPaid":     "payments_of_dividends"
  },
  "_unmapped": []
}
```

Tags in `_unmapped` have no fin_import2 field equivalent (e.g., equity statement items,
comprehensive income sub-items). They are intentionally excluded.

### 1.3 Validate bridge mapping

`tests/test_xbrl_mapping_expansion.py::test_bridge_mapping_coverage`:
- All bridge_mapping.json values are valid field_names that exist in the three mapping dicts
- No duplicate field_name assignments within a statement group
- `_unmapped` entries do not appear as values anywhere

**Exit criteria:** `bridge_mapping.json` committed, test passes, >= 80 standard_tags mapped.

**Results (2026-05-31):** `bridge_mapping.json` maps 131/204 standard_tags (73 unmapped —
industry-specific or no fin_import2 equivalent). Auto-match script got 38/204; 93 resolved
manually. All 6 Phase 1 tests pass. 3 Phase 2 gating tests fail on the pre-existing
duplicates — expected, and the gate for Phase 2.0 cleanup.
Commit: `bf8cd0e`.

---

## Phase 2 — Expand static mapping files ✓ COMPLETE

**Purpose:** Use `bridge_mapping.json` + `gaap_mappings.json` to expand the three
existing `xbrl_mappings/*.py` files in-place, appending new concepts directly to each
field's list with `# edgartools-expanded` comments marking provenance. Industry-specific
concepts are deferred to Phase 3.

**Approach — Option A (modify in-place):** At 132 net-new concepts at the 0.7 threshold
(and ~1,050 with the 0.5–0.69 tier), the expansion is modest enough that appending
to the existing hand-curated files does not hurt readability. No merge layer or separate
expansion files are needed. Each appended concept carries a `# edgartools-expanded`
comment for easy identification and revert.

### 2.0 Fix existing duplicates (prerequisite)

Before running the expansion script, resolve the five known intra-statement duplicates
identified in pre-implementation analysis. These are all in the existing `.py` files:

- `income_statement_xbrl_mapping.py`: remove the duplicate `CostOfGoodsAndServicesSold`
  entry in `cost_of_revenue`; decide whether `InterestAndDividendIncomeOperating`
  belongs in `revenue` or `interest_income` (not both) — keep in `interest_income` only,
  since `Revenues` already covers general revenue; remove
  `NetIncomeLossAvailableToCommonStockholdersBasic` from `net_income` (keep only in
  `net_income_attributable_to_parent` where it is semantically correct).
- `cash_flow_xbrl_mapping.py`: consolidate `ShareBasedCompensation` into one field
  (keep in `stock_based_compensation`, remove from `non_cash_stock_based_comp`);
  `CashCashEquivalentsRestrictedCash...` belongs in `cash_end_of_period` only —
  remove from `cash_beginning_of_period`.

Test after cleanup: `uv run pytest tests/test_xbrl_mapping_expansion.py -k "duplicate"`.

### 2.1 Create the expansion script

`scripts/generate_expanded_mappings.py`:

```
uv run scripts/generate_expanded_mappings.py \
    --gaap-mappings edgartools/edgar/xbrl/standardization/gaap_mappings.json \
    --bridge xbrl_mappings/bridge_mapping.json \
    --industry-overrides-only false \
    --dry-run              # prints diff without writing
```

Algorithm:
1. Load `gaap_mappings.json` and `bridge_mapping.json`.
2. Build a **statement-wide seen set** for each statement: all bare concept names already
   present across every field in that statement. A concept is skipped if it appears
   anywhere in the statement — not just in the target field. This prevents cross-field
   duplicates and is how the five known conflicts are kept out of the expansion.
3. For each entry in gaap_mappings where `industry_overrides` is empty or absent
   (sector-agnostic concepts only):
   - Look up `standard_tag` in bridge_mapping to get `field_name`. Skip if no bridge
     mapping exists.
   - Determine the statement type from the entry's `statement` field. Skip if the
     statement type doesn't match the target file (handles the 15 dual-statement concepts
     that gaap_mappings classifies as IncomeStatement but fin_import2 reads as CF).
   - Strip the `us-gaap_` prefix (fin_import2 convention).
   - Skip if the bare concept is already in the statement-wide seen set.
4. **Tiered append** within each field:
   - `confidence >= 0.7`: append in a `# --- edgartools high-confidence ---` block
     immediately after the last existing concept in the field.
   - `confidence 0.5–0.69`: append in a `# --- edgartools lower-confidence ---` block
     after the high-confidence block. These are tried last, after all existing and
     high-confidence concepts have failed.
5. Write updated `.py` files. Each new concept gets `# edgartools-expanded (conf=X.XX)`.

The script is idempotent: re-running produces no diff against already-expanded files.

### 2.2 Apply expansion and review diff

```bash
uv run scripts/generate_expanded_mappings.py \
    --gaap-mappings edgartools/edgar/xbrl/standardization/gaap_mappings.json \
    --bridge xbrl_mappings/bridge_mapping.json \
    --confidence 0.7
```

Review the diff. Verify:
- No existing concepts removed or reordered
- New concepts have `# edgartools-expanded (conf=X.XX)` comment
- Concept names are valid Python strings (no namespace prefix)
- No concept appears in more than one field within the same statement
- Expected additions at confidence ≥ 0.7 (high-confidence block only):
  income +31, balance +54, cash flow +47 (total 132)
- Expected additions including 0.5–0.69 tier: income +~380, balance +~550, cashflow +~250

### 2.3 Write unit tests

`tests/test_xbrl_mapping_expansion.py`:

```python
def test_no_duplicate_concepts_within_field():
    # Each field list must have no duplicate concept strings

def test_no_duplicate_concepts_across_fields_same_statement():
    # No concept appears in more than one field within the same statement
    # This is the cross-field deduplication that catches the known 5 conflicts

def test_known_duplicates_resolved():
    # Verify the five pre-existing duplicates are gone:
    # - CostOfGoodsAndServicesSold appears exactly once in income mapping
    # - InterestAndDividendIncomeOperating in interest_income only, not revenue
    # - NetIncomeLossAvailableToCommonStockholdersBasic not in net_income
    # - ShareBasedCompensation in stock_based_compensation only
    # - CashCashEquivalentsRestrictedCash... in cash_end_of_period only

def test_all_concepts_are_strings():
    # All entries in every list are non-empty strings

def test_existing_concepts_preserved_and_ordered_first():
    # All concepts present in the pre-expansion snapshot are still present
    # and appear before any edgartools-expanded concept in the same field

def test_expansion_high_confidence_block_size():
    # High-confidence (>=0.7) additions: income +31, balance +54, cashflow +47
    # Allow ±5 tolerance for bridge mapping coverage variation

def test_no_concept_from_wrong_statement():
    # None of the 15 dual-statement concepts (e.g. NetIncomeLoss, DepreciationDepletionAndAmortization)
    # appear in the income mapping as a result of the expansion
    # (they are already in the cashflow mapping and blocked by the seen set)

def test_tiered_ordering():
    # In any field that received both tiers, all conf>=0.7 entries precede all conf<0.7 entries

def test_idempotent():
    # Running the script twice produces no change to the files
```

### 2.4 Re-import test corpus and measure coverage delta

Re-import the 10-ticker baseline corpus with `use_ai_fallback=False` (to isolate static
coverage gain from AI):

```bash
uv run scripts/measure_coverage.py --tickers AAPL,MSFT,JPM,BAC,UNH,GS,WMT,XOM,PFE,BRK-B \
    --form 10-K --no-ai --out docs/coverage_phase2.json
```

**Pass criteria:**
- Balance sheet static hit rate: >= +5 percentage points vs baseline (conservative at 0.7
  threshold; the 0.5–0.69 tier should bring an additional +10 pp)
- Income statement static hit rate: >= +3 percentage points vs baseline
- Cash flow static hit rate: >= +3 percentage points vs baseline
- No field previously found as `found` is now `not_found` (no regression)
- No new cross-field duplicates introduced (verified by `test_no_duplicate_concepts_across_fields_same_statement`)

**Exit criteria:** Tests pass, coverage delta documented, diff reviewed and approved.

**Results (2026-05-31):** Phase 2.0 cleaned 5 duplicates (253 clean concepts).
Phase 2.1 expansion script applied: 253 → 1,236 concepts (+983). Breakdown:
income 125→415, balance 71→692, cashflow 62→129. All 12 tests pass; idempotency
confirmed. 20% of AI discovery queue (71/348) now covered statically.
Re-import needed to reflect improvement in missed_concepts table.
Commit: `d86ca7e`.

---

## Phase 3 — Industry override infrastructure

**Purpose:** Pass SIC code through the extraction chain and apply
`gaap_mappings.json::industry_overrides` before the generic concept list. This is the
primary accuracy gain for banks (SIC 6000-6199), insurers (6300-6411), and REITs (6500-6552).

### 3.1 Build the industry_overrides module

`xbrl_mappings/industry_overrides.py`:

```python
"""
Industry-specific XBRL concept overrides derived from edgartools gaap_mappings.json.
Generated by scripts/generate_expanded_mappings.py --industry-overrides-only.

Structure:
    INDUSTRY_OVERRIDES[statement_type][ff48_code][field_name] = [concept, ...]

Usage:
    from xbrl_mappings.industry_overrides import get_industry_concepts
    concepts = get_industry_concepts('income', 'Fin', 'revenue')
    # Returns bank-specific revenue concepts or [] if no override
"""
```

Generation script extension (same script, `--industry-overrides-only` flag):
1. For each gaap_mappings entry where `industry_overrides` is non-empty:
   - Look up `standard_tag` in bridge_mapping
   - For each (ff48_code, override_dict) in `industry_overrides`:
     - If `override_dict.confidence >= 0.6` (lower threshold for industry-specific)
     - Emit `INDUSTRY_OVERRIDES[statement][ff48_code][field_name] = [concept, ...]`
2. Sort concepts within each list by override confidence descending.

### 3.2 Add SIC lookup utility

`xbrl_mappings/sic_lookup.py`:

```python
"""
Resolve a 4-digit SIC code to a Fama-French 48 industry code.
Delegates to edgartools' sic_industry.py — no duplication.
"""
import sys
from pathlib import Path

_EDGAR_PATH = Path(__file__).parent.parent / "edgartools"
if str(_EDGAR_PATH) not in sys.path:
    sys.path.insert(0, str(_EDGAR_PATH))

from edgar.xbrl.standardization.sic_industry import sic_to_fama_french  # actual function name


def get_ff48(sic: int | str | None) -> str | None:
    """Return FF48 code for a SIC code, or None if unknown."""
    if sic is None:
        return None
    try:
        return sic_to_fama_french(int(sic))
    except Exception:
        return None
```

### 3.3 Modify _extract_value() to accept sic_code

`extractors/statement_extractor.py` — change signature:

```python
def _extract_value(
    statement_df: pd.DataFrame,
    field_name: str,
    year_column: str,
    mapping: dict,
    aggregation_fields: set,
    max_fields: set = frozenset(),
    ff48_code: str | None = None,   # NEW
) -> tuple[Optional[float], Optional[str]]:
```

Logic change — before iterating `mapping[field_name]`, prepend industry-specific concepts:

```python
from xbrl_mappings.industry_overrides import get_industry_concepts

concepts = list(mapping.get(field_name) or [])
if ff48_code:
    override = get_industry_concepts(statement_type, ff48_code, field_name)
    # Prepend overrides; generic list acts as fallback
    concepts = override + [c for c in concepts if c not in override]
```

Industry concepts are tried first; if they match, the generic list is never touched.
If no industry override exists for that field, behavior is identical to today.

### 3.4 Thread SIC through extract_statement()

`extractors/statement_extractor.py::extract_statement()` — add parameter:

```python
async def extract_statement(
    ...
    ff48_code: str | None = None,  # NEW
) -> pd.DataFrame:
```

Pass `ff48_code` to all `_extract_value()` calls inside the function.

### 3.5 Thread SIC through importer and extractor wrappers

`api/importer.py`:

```python
company = await asyncio.to_thread(lambda: Company(ticker))
sic = getattr(company, 'sic', None)
from xbrl_mappings.sic_lookup import get_ff48
ff48_code = get_ff48(sic)
```

Pass `ff48_code` to each extractor call:

```python
df = await extractor(filing, ticker, form, year, quarter=quarter,
                     use_ai_fallback=True, ff48_code=ff48_code)
```

Update each extractor wrapper (`income_statement_extractor.py`,
`balance_sheet_extractor.py`, `cash_flow_extractor.py`) to accept and forward `ff48_code`.

### 3.6 Tests

`tests/test_industry_overrides.py`:

```python
def test_get_industry_concepts_bank():
    # SIC 6020 → 'Fin'; revenue field should return bank-specific concepts
    ff48 = get_ff48(6020)
    assert ff48 == 'Fin'
    concepts = get_industry_concepts('income', 'Fin', 'revenue')
    assert len(concepts) > 0
    assert any('Interest' in c or 'Noninterest' in c for c in concepts)

def test_get_industry_concepts_unknown_sic():
    # Unknown SIC → no crash, returns []
    assert get_industry_concepts('income', None, 'revenue') == []

def test_get_industry_concepts_no_override():
    # Field with no industry override returns []
    assert get_industry_concepts('cashflow', 'Fin', 'capital_expenditures') == []

def test_extract_value_uses_industry_first(mock_stmt_df):
    # Build a mock DataFrame with a bank-specific concept present.
    # Verify _extract_value() returns the bank concept when ff48='Fin',
    # and falls back to generic when ff48=None.

def test_sic_lookup_known_ranges():
    assert get_ff48(6020) == 'Fin'
    assert get_ff48(2100) == 'Smoke'
    assert get_ff48(7372) == 'Softw'
    assert get_ff48(9999) is None

def test_sic_lookup_none_input():
    assert get_ff48(None) is None
```

### 3.7 Industry-specific integration test

Re-import JPM (bank, SIC 6020) and UNH (insurance, SIC 6324) with and without ff48_code:

```bash
uv run scripts/measure_coverage.py --tickers JPM,UNH,BAC,GS \
    --form 10-K --out docs/coverage_phase3_financial.json
```

**Pass criteria for financial sector tickers (JPM, BAC, GS, UNH):**
- `revenue` found rate: 100% (currently unreliable without industry overrides)
- `operating_income` found rate: >= 75%
- No regression on non-financial tickers (AAPL, MSFT, WMT, XOM must be unchanged)

**Exit criteria:** All tests pass. Financial sector coverage delta documented. No regressions
on non-financial tickers verified by re-running `measure_coverage.py` on full corpus.

---

## Phase 4 — DCF hardening

**Purpose:** Target the specific fields that, when NULL, silently break the DCF model.
Three sub-tasks: (a) expand debt field coverage, (b) revenue industry fallback for
full-sector failures, (c) NULL guard for `diluted_shares`.

### 4.1 Debt field expansion (balance sheet)

The three debt fields (`long_term_debt`, `short_term_debt`, `current_portion_long_term_debt`)
are the most DCF-critical balance sheet fields and currently have 5 concepts total.

After Phase 2, the static mapping will include additional concepts from gaap_mappings.
Note that at confidence ≥ 0.7, only 5 concepts are added to these three fields combined —
the main gains for debt fields come from Phase 3 industry overrides for FF48='Fin'.
Verify with:

```bash
python3 -c "
from xbrl_mappings import BALANCE_SHEET_MAPPING
for f in ['long_term_debt', 'short_term_debt', 'current_portion_long_term_debt']:
    print(f, len(BALANCE_SHEET_MAPPING[f]))
"
```

If any of these fields has fewer than 10 concepts post-Phase 2, manually audit
`gaap_mappings.json` for `LongTermDebt`, `ShortTermDebt`, `CurrentPortionOfLongTermDebt`
standard_tags and add missing high-confidence (>= 0.6) concepts.

Also add bank-specific debt equivalents as industry overrides in Phase 3's
`industry_overrides.py` for FF48 = 'Fin':
- `long_term_debt`: add `LongTermDebtNoncurrent`, `FederalHomeLoanBankAdvancesLongTerm`,
  `SubordinatedDebt`, `JuniorSubordinatedNotes`
- `short_term_debt`: add `FederalFundsPurchased`, `SecuredDebt`,
  `FederalHomeLoanBankAdvancesShortTerm`, `ShorttermBorrowings`

### 4.2 DCF NULL guard: warn on critical missing fields

`dcf/model.py::_run_dcf_core()` — add a post-load check that emits warnings (not errors)
for NULL critical fields. Append to the existing `warnings` list:

```python
_DCF_CRITICAL_FIELDS = {
    'income': ['revenue', 'operating_income', 'pretax_income',
               'income_tax_expense', 'diluted_shares'],
    'balance': ['long_term_debt', 'cash_and_equivalents'],
    'cashflow': ['depreciation_amortization', 'capital_expenditures'],
}

for stmt_key, fields in _DCF_CRITICAL_FIELDS.items():
    df = annual[stmt_key] if stmt_key != 'balance' else quarterly['balance']
    for field in fields:
        if field in df.columns and df[field].notna().any():
            continue
        warnings.append(
            f"Critical field '{field}' ({stmt_key}) is NULL for all periods — "
            f"DCF output may be unreliable. Re-import {ticker} to resolve."
        )
```

These warnings surface in the DCF result and in the web UI without blocking computation.

### 4.3 DCF regression tests

`tests/test_dcf_coverage.py`:

```python
def test_dcf_critical_fields_present_aapl():
    # Load from DuckDB, run DCF for AAPL, assert zero warnings about critical fields

def test_dcf_critical_fields_present_jpm():
    # Run DCF for JPM (bank) after Phase 3 industry overrides are applied
    # Assert revenue and long_term_debt are non-NULL

def test_dcf_intrinsic_value_unchanged_after_expansion():
    # Load docs/dcf_baseline.json (Phase 0 snapshot)
    # Re-run DCF for each baseline ticker
    # Assert intrinsic_value_per_share within 2% of baseline
    # (Difference > 2% indicates a NULL field was previously masking a bug)
    # Note: larger differences are flagged, not failed — they may be corrections

def test_dcf_no_zero_shares():
    # Run DCF for all baseline tickers, assert diluted_shares > 0 for all
```

**Pass criteria:**
- All baseline tickers: zero critical-field warnings
- DCF intrinsic values within 2% of Phase 0 baseline for non-financial tickers
- Financial tickers (JPM, GS, BAC): not regressed vs baseline (or, if different,
  the difference is explained by previously-NULL fields now being populated)

**Exit criteria:** All DCF tests pass. Deviations > 2% from baseline are documented
in `docs/dcf_phase4_deltas.md` with explanations.

---

## Phase 5 — Integration test and cleanup

**Purpose:** Full end-to-end regression across the import pipeline, confirming AI fallback
rate reduction and no regressions in downstream features (DCF, alpha model feature
engineering).

### 5.1 Full coverage re-measurement

Re-import all 10 baseline tickers from scratch (drop existing data in test DB):

```bash
uv run scripts/measure_coverage.py --tickers AAPL,MSFT,JPM,BAC,UNH,GS,WMT,XOM,PFE,BRK-B \
    --form 10-K --reimport --out docs/coverage_phase5.json
```

Compare `coverage_phase5.json` vs `coverage_baseline.json`.

**Pass criteria (aggregated across 10 tickers):**
- Mean static hit rate: >= 90% (vs baseline target: whatever Phase 0 measured)
- AI fallback calls: reduced by >= 50% vs `ai_baseline.json`
- Fields permanently NULL: no increase vs baseline
- Financial sector (JPM, BAC, GS, UNH): `revenue` = 100% found, `long_term_debt` = 100% found

### 5.2 Alpha model feature smoke test

The alpha model reads `revenue`, `gross_profit`, `operating_income`, `total_assets`,
`total_equity`, `depreciation_amortization` from the feature engineering pipeline.
Run a smoke test that ingests one period and confirms these columns are non-NULL:

```bash
uv run pytest tests/test_features.py -k "test_fundamentals_not_null" -v
```

If `test_features.py` does not already have such a test, add one that loads the last
annual period for AAPL and MSFT from the DB and asserts no NULL in the above fields.

### 5.3 Bulk import timing benchmark

Record wall-clock time for importing 5 tickers (AAPL, MSFT, JPM, WMT, XOM) with
`use_ai_fallback=True` before and after the expansion:

```bash
time uv run scripts/reimport_all.py --tickers AAPL,MSFT,JPM,WMT,XOM --form 10-K
```

**Target:** >= 20% time reduction due to fewer AI API calls.

### 5.4 Run full test suite

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tee docs/test_phase5.log
```

**Pass criteria:** All previously-passing tests still pass. Zero new failures.

### 5.5 Cleanup

- Remove `xbrl_mappings/bridge_mapping_candidates.json` (intermediate artifact)
- Confirm `scripts/generate_expanded_mappings.py` is idempotent (re-running produces
  no diff against already-expanded files)
- Update `README.md` or `PIPELINE.md` with one paragraph describing the expanded
  mapping architecture and the SIC override mechanism

**Exit criteria:** Full test suite green, coverage targets met, timing benchmark documented.

---

## Phase sequencing and dependencies

```
Phase 0 (baseline)
    ↓
Phase 1 (bridge mapping)   ← manual work, no code changes
    ↓
Phase 2 (fix duplicates + expand static files)  ← depends on Phase 1
    ↓
Phase 3 (industry overrides)  ← highest DCF value; can run after Phase 1 if Phase 2 is deprioritised
    ↓
Phase 4 (DCF hardening)       ← depends on Phase 3 (needs financial sector coverage)
    ↓
Phase 5 (integration)         ← depends on Phases 2, 3, 4
```

Phases 1 and 2 are independent of edgartools runtime — they use only the JSON files.
Phases 3–5 require the edgartools repo to be present at `./edgartools/` (already the case).

**Priority note:** Phase 2 (generic expansion) and Phase 3 (industry overrides) are
independent after Phase 1. If schedule is constrained, Phase 3 should be done first:
it fixes DCF-breaking NULLs for the financial sector. Phase 2 at confidence ≥ 0.7 adds
only 132 concepts and improves coverage for already well-served non-financial companies.
The duplicate cleanup in Phase 2.0 should still happen early as it is a correctness fix.

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Bridge mapping error: wrong field for a standard_tag | Medium | High | Phase 1.3 test validates all values exist as real fields; Phase 2.4 coverage measurement catches regressions |
| Industry override incorrectly applied to wrong SIC range | Medium | Medium | Phase 3.6 tests cover known SIC → FF48 mappings; non-financial coverage checked |
| Generic expansion (Phase 2) adds fewer concepts than expected | Known — not a risk | Low | At confidence ≥ 0.7, exactly 132 net-new concepts are added (pre-measured). The 0.5–0.69 tiered block adds ~980 more at lower certainty. Both tiers are included by default. |
| Lower-confidence tier (0.5–0.69) introduces wrong concept for a field | Low | Medium | Lower-confidence concepts are appended last in each field, so they are only reached after all existing and high-confidence concepts have failed to match. `test_tiered_ordering` verifies ordering. |
| Cross-field duplicate introduced by expansion | Low | Medium | `test_no_duplicate_concepts_across_fields_same_statement` catches this; expansion script uses a statement-wide seen set. |
| DCF output changes after previously-NULL fields are populated | Medium | Medium | Phase 4.3 regression test flags but does not fail on changes > 2%; analyst reviews delta doc |
| edgartools gaap_mappings.json has wrong concept for a field | Low | Medium | All new concepts get `# edgartools-expanded` tag; easy to revert individual entries |
| Performance regression from loading industry_overrides.py | Low | Low | Module is loaded once at import time; no per-row overhead |

---

## File deliverables by phase

| Phase | New files | Modified files |
|-------|-----------|----------------|
| 0 | `scripts/measure_coverage.py` | — |
| 1 | `scripts/generate_bridge_candidates.py`, `xbrl_mappings/bridge_mapping.json` | — |
| 2 | `scripts/generate_expanded_mappings.py`, `tests/test_xbrl_mapping_expansion.py` | `xbrl_mappings/income_statement_xbrl_mapping.py` (duplicate cleanup + expansion), `xbrl_mappings/balance_sheet_xbrl_mapping.py` (expansion), `xbrl_mappings/cash_flow_xbrl_mapping.py` (duplicate cleanup + expansion) |
| 3 | `xbrl_mappings/industry_overrides.py`, `xbrl_mappings/sic_lookup.py`, `tests/test_industry_overrides.py` | `extractors/statement_extractor.py`, `extractors/income_statement_extractor.py`, `extractors/balance_sheet_extractor.py`, `extractors/cash_flow_extractor.py`, `api/importer.py` |
| 4 | `tests/test_dcf_coverage.py` | `dcf/model.py` |
| 5 | — | `README.md` or `PIPELINE.md` |
