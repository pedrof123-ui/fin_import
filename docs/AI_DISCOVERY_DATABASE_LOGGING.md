# AI Discovery and Missed Concept Logging

## Overview

The pipeline maintains two complementary audit trails for XBRL concept resolution:

- **`ai_discovery_queue`** — concepts the AI successfully classified to a field
- **`missed_concepts`** — concepts or fields that could not be resolved, with the reason

Both tables live in `data/xbrl_mappings_multi.duckdb`.

---

## How AI discoveries flow

When `extract_statement()` runs with AI fallback enabled and encounters an XBRL concept
not in the static mapping or industry overrides:

1. **Phase A** — checks `ai_discovery_queue` for a prior AI classification (free, no API call)
2. **Phase B** — sends remaining unmapped concepts to Claude Haiku via OpenRouter in batches of 20
3. Successful classifications are written to `ai_discovery_queue`
4. On the next extraction of the same statement type, `get_enriched_mapping()` promotes any
   concept seen **2 or more times** in `ai_discovery_queue` into the in-memory mapping before
   Pass 1 — so it resolves statically at zero API cost going forward

The static `.py` mapping files (`xbrl_mappings/`) are **not modified at runtime**. All
runtime persistence is DB-only.

**Impact of the Phase 2/3 mapping expansion:** The 1,237-concept static mapping (up from 258)
and 8,140 industry-specific concepts cover ~20% of what was previously AI-discovered,
eliminating those API calls on re-import. For financial-sector tickers (banks, insurers),
revenue and debt fields that previously required AI resolution are now covered by
`industry_overrides.py`.

---

## `ai_discovery_queue` table

```sql
CREATE TABLE ai_discovery_queue (
    id               INTEGER PRIMARY KEY,
    ticker           VARCHAR,    -- e.g. 'AAPL'
    statement_type   VARCHAR,    -- 'income', 'balance', 'cashflow'
    field_name       VARCHAR,    -- standardized field, e.g. 'revenue'
    concept          VARCHAR,    -- XBRL concept, e.g. 'RevenueFromContract...'
    value            DOUBLE,     -- extracted numeric value
    filing_date      DATE,
    period_end_date  DATE,
    discovered_date  TIMESTAMP
)
```

### Query examples

```python
import duckdb
conn = duckdb.connect('data/xbrl_mappings_multi.duckdb', read_only=True)

# All discoveries, most recent first
conn.execute("""
    SELECT ticker, statement_type, field_name, concept, discovered_date
    FROM ai_discovery_queue
    ORDER BY discovered_date DESC
""").fetchdf()

# Concepts validated across multiple companies (ready to promote to static mapping)
conn.execute("""
    SELECT field_name, concept, COUNT(DISTINCT ticker) as companies
    FROM ai_discovery_queue
    WHERE statement_type = 'income'
    GROUP BY field_name, concept
    HAVING COUNT(DISTINCT ticker) >= 3
    ORDER BY companies DESC
""").fetchdf()

# What already enriches Pass 1 (seen >= 2 times — auto-enriched at extraction time)
conn.execute("""
    SELECT field_name, concept, COUNT(*) as times_seen
    FROM ai_discovery_queue
    WHERE statement_type = 'balance'
    GROUP BY field_name, concept
    HAVING COUNT(*) >= 2
    ORDER BY times_seen DESC
""").fetchdf()

conn.close()
```

---

## `missed_concepts` table

Every concept or field that could not be resolved after all passes is recorded here.

```sql
CREATE TABLE missed_concepts (
    id              INTEGER PRIMARY KEY,
    ticker          VARCHAR,
    statement_type  VARCHAR,    -- 'income', 'balance', 'cashflow'
    field_name      VARCHAR,    -- standardized field (NULL for concept-level misses)
    concept         VARCHAR,    -- XBRL concept name (NULL for field-level misses)
    reason          VARCHAR,    -- see below
    filing_date     DATE,
    period_end_date DATE,
    logged_date     TIMESTAMP
)
```

### Reason codes

| Reason | Meaning |
|--------|---------|
| `ai_disabled` | `--no-ai` was set; concept never attempted |
| `no_match` | AI was called but returned no valid field mapping |
| `api_failure` | OpenRouter API call failed entirely |

### Query examples

```python
import duckdb
conn = duckdb.connect('data/xbrl_mappings_multi.duckdb', read_only=True)

# Which fields are consistently missing across companies?
conn.execute("""
    SELECT field_name, statement_type, COUNT(DISTINCT ticker) as companies, reason
    FROM missed_concepts
    GROUP BY field_name, statement_type, reason
    ORDER BY companies DESC
""").fetchdf()

# Concepts AI couldn't classify (candidates for manual mapping)
conn.execute("""
    SELECT concept, COUNT(*) as times_seen, COUNT(DISTINCT ticker) as companies
    FROM missed_concepts
    WHERE reason = 'no_match' AND concept IS NOT NULL
    GROUP BY concept
    ORDER BY companies DESC
""").fetchdf()

# API failures (may indicate key or connectivity issues)
conn.execute("""
    SELECT DATE(logged_date) as day, COUNT(*) as failures
    FROM missed_concepts
    WHERE reason = 'api_failure'
    GROUP BY day
    ORDER BY day DESC
""").fetchdf()

conn.close()
```

---

## Promotion workflow

After reviewing discoveries, permanently add high-confidence concepts to the static mapping
files by editing `xbrl_mappings/income_statement_xbrl_mapping.py`, `balance_sheet_xbrl_mapping.py`,
or `cash_flow_xbrl_mapping.py` directly. Add the concept to the appropriate field list with
a comment indicating provenance:

```python
# In balance_sheet_xbrl_mapping.py, field "long_term_investments":
"MarketableSecuritiesNoncurrent",  # promoted from ai_discovery_queue (seen 5× across AAPL, MSFT, ...)
```

Run the mapping tests after any manual edit to confirm no cross-field duplicates were introduced:

```bash
uv run pytest tests/test_xbrl_mapping_expansion.py -v
```

---

## Recommended workflow

**After each bulk import run:**
- Check `missed_concepts` for any `api_failure` rows — may indicate a key or network issue
- Review `ai_discovery_queue` for new concepts with `COUNT(*) >= 2` — these already enrich Pass 1

**Periodically (e.g. monthly):**
- Promote concepts seen across 3+ companies from `ai_discovery_queue` to the static `.py` files
- Review `missed_concepts` with `no_match` — identify XBRL tags worth adding manually to the mapping
- Re-run `scripts/generate_expanded_mappings.py --dry-run` after any edgartools update to check
  for newly available concepts to absorb
