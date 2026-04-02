"""Export XBRL concept mappings for a financial statement to a readable text file."""

import sys
import pprint
import duckdb
from pathlib import Path
from collections import defaultdict

DB_PATH = Path(__file__).parent.parent / "data" / "xbrl_mappings_multi.duckdb"

STATEMENT_ALIASES = {
    "income": "income",
    "income_statement": "income",
    "balance": "balance",
    "balance_sheet": "balance",
    "cashflow": "cashflow",
    "cash_flow": "cashflow",
    "cf": "cashflow",
}


def export_mappings(statement: str, include_ai: bool = True, output_dir=None) -> Path:
    stmt = STATEMENT_ALIASES.get(statement.lower())
    if stmt is None:
        valid = ", ".join(sorted(STATEMENT_ALIASES.keys()))
        raise ValueError(f"Unknown statement {statement!r}. Valid options: {valid}")

    con = duckdb.connect(str(DB_PATH), read_only=True)

    core_rows = con.execute("""
        SELECT field_name, concept FROM core_concept_mappings
        WHERE statement_type = ? ORDER BY field_name, priority
    """, [stmt]).fetchall()

    ai_rows = []
    if include_ai:
        ai_rows = con.execute("""
            SELECT field_name, concept FROM ai_discovered_mappings
            WHERE statement_type = ? AND promoted_to_core = FALSE
            ORDER BY field_name, confidence_score DESC
        """, [stmt]).fetchall()

    con.close()

    core_map = defaultdict(list)
    for field_name, concept in core_rows:
        core_map[field_name].append(concept)

    ai_map = defaultdict(list)
    for field_name, concept in ai_rows:
        ai_map[field_name].append(concept)

    all_fields = sorted(set(core_map.keys()) | set(ai_map.keys()))
    result = []
    for field_name in all_fields:
        entry = {
            "field_name": field_name,
            "core_concepts": core_map[field_name],
        }
        if include_ai:
            entry["ai_discovered_concepts"] = ai_map[field_name]
        result.append(entry)

    out_dir = Path(output_dir) if output_dir else Path.cwd()
    out_path = out_dir / f"{stmt}_concept_mappings.txt"
    with open(out_path, "w") as f:
        pprint.pprint(result, stream=f, width=120, sort_dicts=False)

    print(f"Wrote {len(result)} fields to {out_path}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python export_mappings.py <statement> [--no-ai]")
        print("  statement: income, balance, cashflow (and aliases)")
        sys.exit(1)

    statement_arg = sys.argv[1]
    include_ai_arg = "--no-ai" not in sys.argv

    export_mappings(statement_arg, include_ai=include_ai_arg)
