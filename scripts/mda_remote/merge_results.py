"""Merge RunPod sweep results (jsonl) into data/mda_features.duckdb.

Only merges rows from the canonical model (qwen3:8b by default) -- comparison-model
rows share the same primary key and must not overwrite them; analyze those with
compare_models.py instead.

Usage: uv run scripts/mda_remote/merge_results.py results_8b.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import mda_feature_sweep as sweep  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--model", default="qwen3:8b")
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.jsonl).read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["model"] == args.model and r["prompt_version"] == sweep.PROMPT_VERSION]
    if not rows:
        sys.exit(f"no rows for model {args.model} in {args.jsonl}")

    con = duckdb.connect(str(sweep.FEATURES_DB))
    before = con.execute("select count(*) from mda_features").fetchone()[0]
    for r in rows:
        con.execute("insert or replace into mda_features values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            r["ticker"], r["form"], r["fiscal_period_end"], r["prompt_version"],
            r["prior_fiscal_period_end"], r["filing_date"], r["accession_no"],
            r["guidance_direction"], r["tone_delta"], r["new_risk_language"],
            r["specificity"], r["hedging_change"], r["rationale"],
            r["model"], r["cur_chars"], r["prior_chars"], r["elapsed_s"], r["extracted_at"],
        ])
    after = con.execute("select count(*) from mda_features").fetchone()[0]
    con.close()
    print(f"{datetime.now():%Y-%m-%d %H:%M} merged {len(rows)} rows: {before} -> {after} "
          f"({after - before} new, {len(rows) - (after - before)} replaced)")


if __name__ == "__main__":
    main()
