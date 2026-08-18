"""Calibration report for the Phase 1 cyclicality gate.

Runs the labelled sample from PLAN_CYCLE_AWARENESS.md Phase 1, then classifies the full
universe and reports the fire rate by sector and size. The gate's hard requirement is zero
false positives on mega-cap compounders: a false positive puts a spurious cycle verdict on a
company where the whole rubric is inapplicable, which is the defect this phase exists to fix.

Usage: uv run python scripts/cyclicality_calibration.py [--universe]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.cycle_data import (  # noqa: E402
    CYCLICAL, INSUFFICIENT_HISTORY, NON_CYCLICAL, AMPLITUDE_MIN, classify_cyclicality,
)

_DATA = Path(__file__).parent.parent / "data"

# The plan's formal gate.
GATE_NON_CYCLICAL = ["AAPL", "MSFT", "KO", "PG", "COST", "V", "WMT", "JNJ", "UNH"]
GATE_CYCLICAL = ["MU", "CLF", "NUE", "F", "GM", "DAL", "UAL", "OXY", "DVN", "AAL"]

# Wider sanity set, added during calibration. Not part of the plan's pass/fail gate.
EXTRA_NON_CYCLICAL = ["PEP", "MCD", "MDLZ", "CL", "KMB", "ADP", "MA", "INTU", "ORCL", "ABT",
                      "MRK", "TMO", "LIN", "NEE", "SO", "DUK", "VZ", "CME", "SPGI", "WM"]
EXTRA_CYCLICAL = ["CAT", "DE", "AA", "FCX", "LUV", "CCL", "RCL", "HAL", "SLB", "EOG",
                  "CF", "MOS", "DOW", "LYB", "WHR"]


def _report(title: str, tickers: list[str], expected: str) -> list[str]:
    print(f"\n--- {title} (expect {expected}) ---")
    print(f"  {'ticker':8}{'verdict':22}{'amp':>7}{'beta':>7}{'facSd':>7}{'ownSd':>7}  peer group")
    wrong = []
    for t in tickers:
        c = classify_cyclicality(t)
        if c.verdict == INSUFFICIENT_HISTORY:
            print(f"  {t:8}{c.verdict:22}{'':28}  {c.reason}")
            continue
        if c.verdict != expected:
            wrong.append(t)
        mark = "  <== MISS" if c.verdict != expected else ""
        print(f"  {t:8}{c.verdict:22}{c.amplitude:7.3f}{c.beta:7.2f}{c.factor_sd:7.3f}"
              f"{c.own_sd:7.3f}  {(c.peer_group or '')[:30]}{mark}")
    print(f"  errors: {len(wrong)}/{len(tickers)}" + (f"  {wrong}" if wrong else ""))
    return wrong


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", action="store_true",
                    help="also classify every ticker in monthly_pe (slow, several minutes)")
    args = ap.parse_args()

    print(f"Cyclicality gate calibration — amplitude threshold {AMPLITUDE_MIN}")

    fp = _report("FORMAL GATE: mega-cap compounders", GATE_NON_CYCLICAL, NON_CYCLICAL)
    fn = _report("FORMAL GATE: known cyclicals", GATE_CYCLICAL, CYCLICAL)
    print(f"\n{'=' * 70}")
    print(f"FORMAL GATE: {len(fp)} false positives, {len(fn)} false negatives")
    print(f"  false positives (hard requirement is zero): {fp or 'none'}")
    print(f"  false negatives: {fn or 'none'}")
    print("=" * 70)

    _report("wider sanity set: non-cyclical", EXTRA_NON_CYCLICAL, NON_CYCLICAL)
    _report("wider sanity set: cyclical", EXTRA_CYCLICAL, CYCLICAL)

    if args.universe:
        universe_report()
    else:
        print("\n(pass --universe for the full-universe confusion matrix)")
    return 1 if fp else 0


def universe_report() -> None:
    conn = duckdb.connect(str(_DATA / "historic_fundamentals.duckdb"), read_only=True)
    conn.execute(f"ATTACH '{_DATA / 'av_financials.duckdb'}' AS av (READ_ONLY)")
    tickers = [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM monthly_pe ORDER BY 1").fetchall()]
    meta = dict(conn.execute("SELECT ticker, sector FROM av.company_overview").fetchall())
    mcap = dict(conn.execute("""
        SELECT ticker, median(price * shares) FROM monthly_pe
        WHERE month_end_date >= CURRENT_DATE - INTERVAL 7 YEARS AND price IS NOT NULL
        GROUP BY ticker
    """).fetchall())
    conn.close()

    print(f"\n=== FULL UNIVERSE (n={len(tickers)}) ===")
    verdicts: dict[str, str] = {}
    for i, t in enumerate(tickers, 1):
        verdicts[t] = classify_cyclicality(t).verdict
        if i % 250 == 0:
            print(f"  ... {i}/{len(tickers)}")

    counts = {v: sum(1 for x in verdicts.values() if x == v)
              for v in (CYCLICAL, NON_CYCLICAL, INSUFFICIENT_HISTORY)}
    for k, v in counts.items():
        print(f"  {k:22} {v:5d}  {v / len(tickers) * 100:5.1f}%")
    scored = counts[CYCLICAL] + counts[NON_CYCLICAL]
    if scored:
        print(f"  cyclical share of scored names: {counts[CYCLICAL] / scored * 100:.1f}%")

    large = [t for t in tickers if mcap.get(t) and mcap[t] > 10e9 and verdicts[t] != INSUFFICIENT_HISTORY]
    if large:
        rate = sum(verdicts[t] == CYCLICAL for t in large) / len(large)
        print(f"\n  large caps (median mcap > $10B, n={len(large)}): {rate * 100:.1f}% cyclical")
        print(f"\n  {'sector':26}{'n':>5}{'cyclical':>10}")
        for s in sorted({meta.get(t) or "UNKNOWN" for t in large}):
            ts = [t for t in large if (meta.get(t) or "UNKNOWN") == s]
            if len(ts) < 5:
                continue
            r = sum(verdicts[t] == CYCLICAL for t in ts) / len(ts)
            print(f"  {s:26}{len(ts):5d}{r * 100:9.0f}%")


if __name__ == "__main__":
    sys.exit(main())
