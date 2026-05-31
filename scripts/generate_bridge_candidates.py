"""
Phase 1.1 — Generate bridge mapping candidates.

Reads gaap_mappings.json, extracts all unique standard_tags per statement type,
and attempts to auto-match each tag to a fin_import2 field_name via snake_case
normalisation. Outputs a candidates JSON for human review.

The final bridge_mapping.json is produced by human review of this output.

Usage:
    uv run scripts/generate_bridge_candidates.py
    uv run scripts/generate_bridge_candidates.py --out xbrl_mappings/bridge_mapping_candidates.json
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

GAAP_MAPPINGS = ROOT / "edgartools" / "edgar" / "xbrl" / "standardization" / "gaap_mappings.json"
STMT_MAP = {
    "IncomeStatement":   "income",
    "BalanceSheet":      "balance",
    "CashFlowStatement": "cashflow",
}


def _to_snake(name: str) -> str:
    """CamelCase / PascalCase → lowercase_snake (strips trailing 'CF', 'IS', 'BS')."""
    name = re.sub(r"(CF|IS|BS)$", "", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    name = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", name)
    return name.lower().strip("_")


def _load_field_names() -> dict[str, set[str]]:
    from xbrl_mappings import INCOME_STATEMENT_MAPPING, BALANCE_SHEET_MAPPING, CASH_FLOW_MAPPING
    return {
        "income":   set(INCOME_STATEMENT_MAPPING.keys()),
        "balance":  set(BALANCE_SHEET_MAPPING.keys()),
        "cashflow": set(CASH_FLOW_MAPPING.keys()),
    }


def _auto_match(tag: str, field_names: set[str]) -> str | None:
    """Try direct snake-case match, then partial token match."""
    snake = _to_snake(tag)
    if snake in field_names:
        return snake
    # Try removing common suffixes/prefixes and matching
    for field in field_names:
        if snake == field or field in snake or snake in field:
            if abs(len(snake) - len(field)) <= 8:
                return field
    return None


def generate_candidates() -> dict:
    with open(GAAP_MAPPINGS) as f:
        gaap = json.load(f)

    field_names = _load_field_names()

    # Collect unique standard_tags per statement from gaap_mappings entries
    tag_by_stmt: dict[str, set[str]] = defaultdict(set)
    for concept, meta in gaap.items():
        stmt_raw = meta.get("statement", "")
        stmt = STMT_MAP.get(stmt_raw)
        if stmt is None:
            continue
        for tag in meta.get("standard_tags", []):
            tag_by_stmt[stmt].add(tag)

    result: dict[str, dict] = {}
    all_auto, all_manual = 0, 0

    for stmt_raw, stmt in STMT_MAP.items():
        tags = sorted(tag_by_stmt[stmt])
        mappings = {}
        for tag in tags:
            match = _auto_match(tag, field_names[stmt])
            status = "auto" if match else "manual"
            mappings[tag] = {"field": match, "status": status}
            if match:
                all_auto += 1
            else:
                all_manual += 1
        result[stmt_raw] = mappings

    total = all_auto + all_manual
    print(f"Total tags: {total}  auto-matched: {all_auto}  needs manual: {all_manual}")
    for stmt_raw, stmt in STMT_MAP.items():
        n_auto = sum(1 for v in result[stmt_raw].values() if v["status"] == "auto")
        n_total = len(result[stmt_raw])
        print(f"  {stmt_raw}: {n_auto}/{n_total} auto-matched")
        manual_tags = [t for t, v in result[stmt_raw].items() if v["status"] == "manual"]
        if manual_tags:
            print(f"    Manual: {', '.join(manual_tags)}")

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "xbrl_mappings" / "bridge_mapping_candidates.json"))
    args = parser.parse_args()

    candidates = generate_candidates()
    Path(args.out).write_text(json.dumps(candidates, indent=2))
    print(f"\nCandidates written to: {args.out}")
    print("Review and produce xbrl_mappings/bridge_mapping.json from this output.")


if __name__ == "__main__":
    main()
