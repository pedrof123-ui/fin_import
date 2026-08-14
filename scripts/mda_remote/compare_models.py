"""Compare feature extractions from two models on overlapping pairs.

Prints per-feature agreement, the guidance confusion matrix, and the strongest
disagreements with both rationales, to decide whether the stronger model is worth
switching to before the factor gauntlet.

Usage: uv run scripts/mda_remote/compare_models.py results_8b.jsonl results_30b.jsonl
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

FEATURES = ["guidance_direction", "tone_delta", "new_risk_language", "specificity", "hedging_change"]
GUIDANCE_RANK = {"raised": 2, "maintained": 1, "none_given": 0, "withdrawn": -1, "lowered": -2}


def load(path: str) -> dict[tuple, dict]:
    rows = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    return {(r["ticker"], r["fiscal_period_end"]): r for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline_jsonl")
    ap.add_argument("challenger_jsonl")
    args = ap.parse_args()

    a, b = load(args.baseline_jsonl), load(args.challenger_jsonl)
    keys = sorted(a.keys() & b.keys())
    if not keys:
        raise SystemExit("no overlapping pairs")
    print(f"{len(keys)} overlapping pairs "
          f"({a[keys[0]]['model']} vs {b[keys[0]]['model']})\n")

    for feat in FEATURES:
        exact = sum(a[k][feat] == b[k][feat] for k in keys)
        line = f"{feat:20s} exact agreement {exact / len(keys):5.1%}"
        if feat != "guidance_direction":
            mae = sum(abs(a[k][feat] - b[k][feat]) for k in keys) / len(keys)
            line += f"  MAE {mae:.2f}"
        print(line)

    print("\nguidance confusion (rows=baseline, cols=challenger):")
    cm = Counter((a[k]["guidance_direction"], b[k]["guidance_direction"]) for k in keys)
    labels = ["raised", "maintained", "none_given", "withdrawn", "lowered"]
    print(f"{'':12s}" + "".join(f"{l[:9]:>10s}" for l in labels))
    for ra in labels:
        print(f"{ra:12s}" + "".join(f"{cm.get((ra, cb), 0):10d}" for cb in labels))

    disagreements = sorted(
        (k for k in keys if a[k]["guidance_direction"] != b[k]["guidance_direction"]),
        key=lambda k: abs(GUIDANCE_RANK[a[k]["guidance_direction"]] - GUIDANCE_RANK[b[k]["guidance_direction"]]),
        reverse=True)
    print(f"\ntop guidance disagreements ({len(disagreements)} total):")
    for k in disagreements[:15]:
        print(f"\n{k[0]} {k[1]}: {a[k]['guidance_direction']} vs {b[k]['guidance_direction']}")
        print(f"  {a[k]['model']}: {a[k]['rationale']}")
        print(f"  {b[k]['model']}: {b[k]['rationale']}")


if __name__ == "__main__":
    main()
