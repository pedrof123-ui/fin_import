"""
Phase 2.1 — Expand static XBRL mapping files using edgartools gaap_mappings.json.

Reads gaap_mappings.json + bridge_mapping.json and appends new sector-agnostic
concepts to the three xbrl_mappings/*.py files in-place. New entries are tagged
with '# edgartools-expanded (conf=X.XX)' for easy identification and revert.

Tiered append within each field:
  confidence >= 0.7  → high-confidence block (tried before lower-confidence)
  confidence 0.5–0.69 → lower-confidence block (last resort before AI fallback)

Concepts below 0.5 confidence, with industry_overrides, or not in the bridge
mapping are skipped entirely.

The script is idempotent: re-running produces no diff on already-expanded files.

Usage:
    uv run scripts/generate_expanded_mappings.py --dry-run    # show diff only
    uv run scripts/generate_expanded_mappings.py              # apply changes
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

GAAP_PATH = ROOT / "edgartools" / "edgar" / "xbrl" / "standardization" / "gaap_mappings.json"
BRIDGE_PATH = ROOT / "xbrl_mappings" / "bridge_mapping.json"

MAPPING_FILES = {
    "income":   ROOT / "xbrl_mappings" / "income_statement_xbrl_mapping.py",
    "balance":  ROOT / "xbrl_mappings" / "balance_sheet_xbrl_mapping.py",
    "cashflow": ROOT / "xbrl_mappings" / "cash_flow_xbrl_mapping.py",
}

STMT_INTERNAL = {
    "IncomeStatement":   "income",
    "BalanceSheet":      "balance",
    "CashFlowStatement": "cashflow",
}

HIGH_CONF = 0.70
LOW_CONF  = 0.50

MARKER_HIGH = "# --- edgartools high-confidence ---"
MARKER_LOW  = "# --- edgartools lower-confidence ---"


def _load_existing_concepts(stmt: str) -> set[str]:
    """Return bare concept names (no prefix) already in the mapping for a statement."""
    from xbrl_mappings import INCOME_STATEMENT_MAPPING, BALANCE_SHEET_MAPPING, CASH_FLOW_MAPPING
    mapping = {"income": INCOME_STATEMENT_MAPPING, "balance": BALANCE_SHEET_MAPPING,
               "cashflow": CASH_FLOW_MAPPING}[stmt]
    seen = set()
    for concepts in mapping.values():
        for c in concepts:
            bare = c.split("_", 1)[1] if "_" in c else c
            seen.add(bare)
    return seen


def _build_additions(gaap: dict, bridge: dict) -> dict[str, dict[str, dict[str, list]]]:
    """
    Returns: additions[stmt][field_name] = {"high": [...], "low": [...]}

    Each entry is a (concept, confidence) pair represented as a string
    "Concept  # edgartools-expanded (conf=X.XX)".
    """
    additions: dict[str, dict[str, dict[str, list]]] = {
        s: defaultdict(lambda: {"high": [], "low": []})
        for s in STMT_INTERNAL.values()
    }
    existing = {s: _load_existing_concepts(s) for s in STMT_INTERNAL.values()}

    for concept, meta in gaap.items():
        stmt_raw = meta.get("statement", "")
        stmt = STMT_INTERNAL.get(stmt_raw)
        if stmt is None:
            continue
        if meta.get("industry_overrides"):
            continue  # Phase 3 handles these

        conf = meta.get("confidence", 0.0)
        if conf < LOW_CONF:
            continue

        # Skip non-US-GAAP taxonomy concepts (IFRS, country-specific, etc.)
        if ":" in concept:
            continue

        # Strip us-gaap_ prefix (fin_import2 convention stores bare names)
        bare = concept.removeprefix("us-gaap_")

        if bare in existing[stmt]:
            continue  # already covered

        # Find a field via any standard_tag
        field = None
        stmt_bridge = bridge.get(stmt_raw, {})
        for tag in meta.get("standard_tags", []):
            if tag in stmt_bridge and tag != "_unmapped":
                field = stmt_bridge[tag]
                break
        if field is None:
            continue

        entry = f'        "{bare}",  # edgartools-expanded (conf={conf:.2f})'
        tier = "high" if conf >= HIGH_CONF else "low"
        additions[stmt][field][tier].append(entry)
        existing[stmt].add(bare)  # prevent duplicates from multiple tags→same field

    return additions


def _field_pattern(field: str) -> re.Pattern:
    """Regex matching the opening of a field's list in the .py file."""
    escaped = re.escape(field)
    return re.compile(rf'^\s*"{escaped}"\s*:\s*\[', re.MULTILINE)


def _find_field_close(content: str, field_start: int) -> int:
    """
    From field_start (position of the opening '['), find the matching closing '],'.
    Returns the position of the '],' (start of that token).
    """
    depth = 0
    i = content.index("[", field_start)
    while i < len(content):
        ch = content[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"No closing ] found from position {field_start}")


def _already_expanded(content: str, field: str) -> bool:
    """True if this field already has edgartools-expanded markers (idempotency check)."""
    pat = _field_pattern(field)
    m = pat.search(content)
    if not m:
        return False
    close = _find_field_close(content, m.start())
    field_body = content[m.start():close]
    return MARKER_HIGH in field_body or MARKER_LOW in field_body


def _insert_additions(content: str, field: str, high: list, low: list) -> str:
    """Insert tiered additions before the closing '],' of the named field."""
    if not high and not low:
        return content

    pat = _field_pattern(field)
    m = pat.search(content)
    if not m:
        return content  # field not found in this file

    close_idx = _find_field_close(content, m.start())

    # Build the insertion block
    lines = []
    if high:
        lines.append(f"        {MARKER_HIGH}")
        lines.extend(high)
    if low:
        lines.append(f"        {MARKER_LOW}")
        lines.extend(low)

    insert = "\n".join(lines) + "\n"

    # Find the line start of the closing ']'
    line_start = content.rfind("\n", 0, close_idx) + 1
    return content[:line_start] + insert + content[line_start:]


def expand_file(stmt: str, additions: dict[str, dict[str, list]],
                dry_run: bool) -> tuple[int, int]:
    """Apply additions to one mapping file. Returns (fields_modified, concepts_added)."""
    path = MAPPING_FILES[stmt]
    content = path.read_text()
    original = content

    fields_modified = 0
    concepts_added = 0

    for field, tiers in sorted(additions.items()):
        high, low = tiers["high"], tiers["low"]
        if not high and not low:
            continue
        if _already_expanded(content, field):
            continue  # idempotent
        content = _insert_additions(content, field, high, low)
        fields_modified += 1
        concepts_added += len(high) + len(low)

    if content == original:
        return 0, 0

    if dry_run:
        _print_diff(path.name, original, content)
    else:
        path.write_text(content)

    return fields_modified, concepts_added


def _print_diff(filename: str, before: str, after: str) -> None:
    import difflib
    diff = list(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=2,
    ))
    print(f"\n--- {filename} ({len(diff)} diff lines) ---")
    # Show only added lines for brevity
    for line in diff:
        if line.startswith(("+", "-", "@")):
            print(line, end="")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change without writing files")
    parser.add_argument("--gaap-mappings", default=str(GAAP_PATH))
    parser.add_argument("--bridge", default=str(BRIDGE_PATH))
    args = parser.parse_args()

    gaap = json.loads(Path(args.gaap_mappings).read_text())
    bridge = json.loads(Path(args.bridge).read_text())

    additions = _build_additions(gaap, bridge)

    total_fields = total_concepts = 0
    for stmt in ("income", "balance", "cashflow"):
        stmt_raw = next(k for k, v in STMT_INTERNAL.items() if v == stmt)
        n_high = sum(len(v["high"]) for v in additions[stmt].values())
        n_low  = sum(len(v["low"])  for v in additions[stmt].values())
        print(f"{stmt:10s}: {n_high} high-conf additions, {n_low} lower-conf additions "
              f"across {sum(1 for v in additions[stmt].values() if v['high'] or v['low'])} fields")

        f_mod, c_add = expand_file(stmt, additions[stmt], args.dry_run)
        total_fields += f_mod
        total_concepts += c_add

    action = "Would add" if args.dry_run else "Added"
    print(f"\n{action} {total_concepts} concepts across {total_fields} fields total.")
    if args.dry_run:
        print("Re-run without --dry-run to apply.")


if __name__ == "__main__":
    main()
