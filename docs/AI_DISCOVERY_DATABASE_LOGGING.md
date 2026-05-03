# AI Discovery and Missed Concept Logging

## Overview

The pipeline maintains two complementary audit trails for XBRL concept resolution:

- **`ai_discovery_queue`** — concepts the AI successfully classified to a field
- **`missed_concepts`** — concepts or fields that could not be resolved, with the reason

Both tables live in `data/xbrl_mappings_multi.duckdb`.

---

## How AI discoveries flow

When `extract_statement()` runs with AI fallback enabled and encounters an XBRL concept
not in the static mapping:

1. **Phase A** — checks `ai_discovery_queue` for a prior AI classification (free, no API call)
2. **Phase B** — sends remaining unmapped concepts to Claude Haiku via OpenRouter in batches of 20
3. Successful classifications are written to `ai_discovery_queue`
4. On the next extraction of the same statement type, `get_enriched_mapping()` promotes any
   concept seen **2 or more times** in `ai_discovery_queue` into the in-memory mapping before
   Pass 1 — so it resolves statically at zero API cost going forward

The static `.py` mapping files (`xbrl_mappings/`) are **not modified at runtime**. All
runtime persistence is DB-only. To permanently promote a discovery into the static files,
use `write_concept_to_mapping()` manually after review.

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
from xbrl_mapping_manager_multi_statement import XBRLMappingManager

mapper = XBRLMappingManager('data/xbrl_mappings_multi.duckdb')

# All discoveries, most recent first
mapper.conn.execute("""
    SELECT ticker, statement_type, field_name, concept, discovered_date
    FROM ai_discovery_queue
    ORDER BY discovered_date DESC
""").fetchdf()

# Concepts validated across multiple companies (ready to promote)
mapper.conn.execute("""
    SELECT field_name, concept, COUNT(DISTINCT ticker) as companies
    FROM ai_discovery_queue
    WHERE statement_type = 'income'
    GROUP BY field_name, concept
    HAVING COUNT(DISTINCT ticker) >= 3
    ORDER BY companies DESC
""").fetchdf()

# What already enriches Pass 1 (seen >= 2 times)
mapper.conn.execute("""
    SELECT field_name, concept, COUNT(*) as times_seen
    FROM ai_discovery_queue
    WHERE statement_type = 'balance'
    GROUP BY field_name, concept
    HAVING COUNT(*) >= 2
    ORDER BY times_seen DESC
""").fetchdf()

mapper.close()
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
# Which fields are consistently missing across companies?
mapper.conn.execute("""
    SELECT field_name, statement_type, COUNT(DISTINCT ticker) as companies, reason
    FROM missed_concepts
    GROUP BY field_name, statement_type, reason
    ORDER BY companies DESC
""").fetchdf()

# Concepts AI couldn't classify (candidates for manual mapping)
mapper.conn.execute("""
    SELECT concept, COUNT(*) as times_seen, COUNT(DISTINCT ticker) as companies
    FROM missed_concepts
    WHERE reason = 'no_match' AND concept IS NOT NULL
    GROUP BY concept
    ORDER BY companies DESC
""").fetchdf()

# API failures (may indicate key or connectivity issues)
mapper.conn.execute("""
    SELECT DATE(logged_date) as day, COUNT(*) as failures
    FROM missed_concepts
    WHERE reason = 'api_failure'
    GROUP BY day
    ORDER BY day DESC
""").fetchdf()
```

---

## Promotion workflow

After reviewing discoveries, permanently add high-confidence concepts to the static mapping:

```python
from xbrl_concept_mapper import write_concept_to_mapping

# Manually promote a concept to the static .py file
write_concept_to_mapping(
    concept='MarketableSecuritiesNoncurrent',
    field_name='long_term_investments',
    statement_type='balance',
    ticker='AAPL',  # used in the comment tag
)
```

Or use the `XBRLMappingManager` DB promotion (promotes to `core_concept_mappings`):

```python
import asyncio
from xbrl_mapping_manager_multi_statement import XBRLMappingManager

mapper = XBRLMappingManager('data/xbrl_mappings_multi.duckdb')
asyncio.run(mapper.promote_ai_to_core(
    statement_type='balance',
    field_name='long_term_investments',
    concept='MarketableSecuritiesNoncurrent',
))
mapper.close()
```

---

## Recommended workflow

**After each bulk import run:**
- Check `missed_concepts` for any `api_failure` rows — may indicate a key or network issue
- Review `ai_discovery_queue` for new concepts with `COUNT(*) >= 2` — these already enrich Pass 1

**Periodically (e.g. monthly):**
- Promote concepts seen across 3+ companies from `ai_discovery_queue` to the static `.py` files
- Review `missed_concepts` with `no_match` — identify XBRL tags worth adding manually to the mapping
