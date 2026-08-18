"""Before/after on the defect PLAN_CYCLE_AWARENESS.md was written to fix.

Finding 3 measured the original peak-earnings rubric firing on 40.5% of the universe, with
AAPL, MSFT, KO, PG and COST all flagged as peak-earnings traps. This replays that rubric against
the current data and scores the shipped pipeline on the same universe, so the fix is verified
against the original measurement rather than asserted.

Usage: uv run python scripts/cycle_defect_before_after.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.cycle_data import (  # noqa: E402
    CYCLICAL, MID, NOT_CYCLICAL_POSITION, PEAK, TROUGH, evaluate_cycle_position,
)

_DATA = Path(__file__).parent.parent / "data"
_CACHE = _DATA / "cycle_position_calibration_inputs.json"
_NAMED = ["AAPL", "MSFT", "KO", "PG", "COST"]


def old_rubric_fires(r: dict) -> bool:
    """The original 5-condition rubric, TWO or more required.

    Conditions 1 and 4 are the pair finding 3 showed were 99.7% redundant: condition 4 compared
    current P/E to normalized_pe_5y (= today's price / 5yr average EPS), which is mechanically
    below current P/E for any company whose EPS is rising, so a grower tripped both at once.
    """
    c = [
        r["ttm_eps"] is not None and r["eps_max"] not in (None, 0)
        and r["ttm_eps"] >= 0.90 * r["eps_max"],
        r["ttm_eps"] not in (None, 0) and r["fwd_eps"] is not None
        and r["fwd_eps"] / r["ttm_eps"] - 1 <= -0.05,
        r["earn_growth_1yr"] is not None and r["earn_cagr_3yr"] is not None
        and r["earn_growth_1yr"] > r["earn_cagr_3yr"],
        r["pe"] is not None and r["normalized_pe_5y"] is not None
        and 0 < r["pe"] < r["normalized_pe_5y"],
        r["operating_margin"] is not None and r["operating_margin_median"] is not None
        and r["operating_margin"] > r["operating_margin_median"],
    ]
    return sum(bool(x) for x in c) >= 2


def main() -> int:
    if not _CACHE.exists():
        print("run scripts/cycle_position_calibration.py --refresh first")
        return 1
    rows = json.loads(_CACHE.read_text())

    conn = duckdb.connect(str(_DATA / "historic_fundamentals.duckdb"), read_only=True)
    norm = dict(conn.execute("SELECT ticker, normalized_pe_5y FROM pe_stats").fetchall())
    conn.close()
    for r in rows:
        r["normalized_pe_5y"] = norm.get(r["ticker"])

    usable = [r for r in rows if r["ttm_eps"] is not None]
    before = [r for r in usable if old_rubric_fires(r)]

    scored = {r["ticker"]: evaluate_cycle_position(r["verdict"], **{k: r[k] for k in (
        "ttm_eps", "fwd_eps", "earn_growth_1yr", "earn_cagr_3yr", "operating_margin",
        "operating_margin_median", "pe", "pe_median", "rev_growth_1yr", "eps_max",
        "eps_midcycle")}) for r in rows}
    after_peak = [r for r in usable if scored[r["ticker"]].position == PEAK]

    print(f"universe with usable data: {len(usable)}\n")
    print("Note: finding 3 quoted 40.5%, which was specifically the conditions-1-and-4 pair that")
    print("alone trips the 'TWO or more' threshold. The replay below scores all five original")
    print("conditions, so it is the full-rubric figure and reads higher. Both measure the same")
    print("defect; the after-state is what the comparison turns on.\n")
    print(f"BEFORE — original rubric fires a peak-earnings trap: "
          f"{len(before)} ({len(before) / len(usable) * 100:.1f}%)")
    print(f"AFTER  — pipeline reports PEAK:                     "
          f"{len(after_peak)} ({len(after_peak) / len(usable) * 100:.1f}%)")

    print("\nThe five names finding 3 called out by name:")
    print(f"  {'ticker':8}{'before':>10}{'after':>16}")
    for t in _NAMED:
        r = next((x for x in usable if x["ticker"] == t), None)
        if r is None:
            print(f"  {t:8}{'(no data)':>10}")
            continue
        print(f"  {t:8}{'TRAP' if old_rubric_fires(r) else 'clean':>10}"
              f"{scored[t].position:>16}")

    print("\nAfter-state breakdown:")
    for label, position in (("PEAK", PEAK), ("TROUGH", TROUGH), ("MID", MID),
                            ("NOT_CYCLICAL", NOT_CYCLICAL_POSITION)):
        n = sum(1 for r in usable if scored[r["ticker"]].position == position)
        print(f"  {label:14} {n:5d}  {n / len(usable) * 100:5.1f}%")

    ok = all(scored[t].position == NOT_CYCLICAL_POSITION for t in _NAMED
             if any(x["ticker"] == t for x in usable))
    print("\n" + ("PASS: none of the named compounders is placed on a cycle"
                  if ok else "FAIL: a named compounder still carries a cycle position"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
