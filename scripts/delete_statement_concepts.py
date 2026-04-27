"""Delete all concept entries for a given financial statement type from xbrl_mappings_multi.duckdb.

Usage:
    python delete_statement_concepts.py <statement_type> [--db PATH] [--dry-run]

Examples:
    python delete_statement_concepts.py cashflow
    python delete_statement_concepts.py income --dry-run
    python delete_statement_concepts.py balance --db /path/to/xbrl_mappings_multi.duckdb
"""

import argparse
import duckdb
import sys

TABLES = [
    "ai_discovered_mappings",
    "ai_discovery_queue",
]

def main():
    parser = argparse.ArgumentParser(description="Delete all concept entries for a financial statement type.")
    parser.add_argument("statement_type", help="Statement type to delete (e.g. cashflow, income, balance)")
    parser.add_argument("--db", default="data/xbrl_mappings_multi.duckdb", help="Path to DuckDB file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without actually deleting")
    args = parser.parse_args()

    con = duckdb.connect(args.db, read_only=args.dry_run)

    # Validate statement_type exists somewhere
    existing = con.execute(
        "SELECT DISTINCT statement_type FROM core_concept_mappings "
        "UNION SELECT DISTINCT statement_type FROM ai_discovered_mappings"
    ).fetchall()
    valid_types = sorted({r[0] for r in existing})

    if args.statement_type not in valid_types:
        print(f"Error: '{args.statement_type}' not found. Valid types: {valid_types}")
        con.close()
        sys.exit(1)

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Deleting all entries for statement_type = '{args.statement_type}'\n")

    total_deleted = 0
    for table in TABLES:
        count = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE statement_type = ?", [args.statement_type]
        ).fetchone()[0]

        if count > 0:
            print(f"  {table}: {count} rows")
            if not args.dry_run:
                con.execute(f"DELETE FROM {table} WHERE statement_type = ?", [args.statement_type])
            total_deleted += count

    print(f"\n{'Would delete' if args.dry_run else 'Deleted'} {total_deleted} total rows.")
    con.close()

if __name__ == "__main__":
    main()
