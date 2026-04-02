"""Strip namespace prefixes from cashflow concepts in ai_discovered_mappings.

Handles duplicate conflicts by keeping one row per (statement_type, field_name, stripped_concept)
group before applying the UPDATE.
"""

import duckdb

DB_PATH = "data/xbrl_mappings_multi.duckdb"

con = duckdb.connect(DB_PATH)

# 1. Preview
print("=== Preview ===")
count = con.execute(
    "SELECT COUNT(*) FROM ai_discovered_mappings WHERE statement_type = 'cashflow' AND concept LIKE '%_%'"
).fetchone()[0]
total_cf = con.execute(
    "SELECT COUNT(*) FROM ai_discovered_mappings WHERE statement_type = 'cashflow'"
).fetchone()[0]
print(f"Total cashflow rows: {total_cf}")
print(f"Rows with prefix to strip: {count}")

print("\nSample before/after:")
samples = con.execute(
    """
    SELECT concept, substr(concept, strpos(concept, '_') + 1) AS new_concept
    FROM ai_discovered_mappings
    WHERE statement_type = 'cashflow' AND concept LIKE '%_%'
    LIMIT 10
    """
).fetchall()
for orig, new in samples:
    print(f"  {orig!r:60s} -> {new!r}")

# 2. Duplicate check
print("\n=== Duplicate Check ===")
dupes = con.execute(
    """
    SELECT statement_type, field_name, substr(concept, strpos(concept, '_') + 1) AS new_concept, COUNT(*) AS n
    FROM ai_discovered_mappings
    WHERE statement_type = 'cashflow' AND concept LIKE '%_%'
    GROUP BY 1, 2, 3
    HAVING n > 1
    ORDER BY n DESC, field_name
    """
).fetchall()
if dupes:
    print(f"Found {len(dupes)} duplicate groups (will delete extras, keeping one per group):")
    for row in dupes:
        print(f"  field={row[1]!r:35s} concept={row[2]!r:50s} count={row[3]}")
else:
    print("No duplicates — safe to proceed directly.")

# 3. Delete duplicate rows (keep one per future key using rowid min)
if dupes:
    print("\n=== Deleting Duplicate Extras ===")
    # Count rows that will be deleted
    to_delete = con.execute(
        """
        WITH ranked AS (
            SELECT rowid,
                   ROW_NUMBER() OVER (
                       PARTITION BY statement_type, field_name, substr(concept, strpos(concept, '_') + 1)
                       ORDER BY concept  -- deterministic: alphabetical, keeps 'us-gaap_...' first
                   ) AS rn
            FROM ai_discovered_mappings
            WHERE statement_type = 'cashflow' AND concept LIKE '%_%'
        )
        SELECT COUNT(*) FROM ranked WHERE rn > 1
        """
    ).fetchone()[0]
    print(f"Rows to delete (duplicates): {to_delete}")

    con.execute(
        """
        DELETE FROM ai_discovered_mappings
        WHERE rowid IN (
            SELECT rowid FROM (
                SELECT rowid,
                       ROW_NUMBER() OVER (
                           PARTITION BY statement_type, field_name, substr(concept, strpos(concept, '_') + 1)
                           ORDER BY concept
                       ) AS rn
                FROM ai_discovered_mappings
                WHERE statement_type = 'cashflow' AND concept LIKE '%_%'
            ) t
            WHERE rn > 1
        )
        """
    )
    print("Duplicates deleted.")

    remaining = con.execute(
        "SELECT COUNT(*) FROM ai_discovered_mappings WHERE statement_type = 'cashflow'"
    ).fetchone()[0]
    print(f"Cashflow rows after dedup: {remaining}")

# 4. Apply the UPDATE
print("\n=== Applying Update ===")
con.execute(
    """
    UPDATE ai_discovered_mappings
    SET concept = substr(concept, strpos(concept, '_') + 1)
    WHERE statement_type = 'cashflow'
      AND concept LIKE '%_%'
    """
)
print("UPDATE executed.")

# 5. Verify
print("\n=== Verification ===")
final_count = con.execute(
    "SELECT COUNT(*) FROM ai_discovered_mappings WHERE statement_type = 'cashflow'"
).fetchone()[0]
still_prefixed = con.execute(
    """
    SELECT COUNT(*) FROM ai_discovered_mappings
    WHERE statement_type = 'cashflow'
      AND (concept LIKE 'us-gaap_%' OR concept LIKE 'us_gaap_%'
           OR concept LIKE 'dei_%' OR concept LIKE 'srt_%')
    """
).fetchone()[0]
print(f"Total cashflow rows: {final_count}")
print(f"Rows still matching known prefix patterns: {still_prefixed}")

print("\nSample updated concepts (first 15):")
updated = con.execute(
    """
    SELECT field_name, concept FROM ai_discovered_mappings
    WHERE statement_type = 'cashflow'
    ORDER BY field_name, concept
    LIMIT 15
    """
).fetchall()
for field, c in updated:
    print(f"  {field!r:35s}  {c}")

con.close()
print("\nDone.")
