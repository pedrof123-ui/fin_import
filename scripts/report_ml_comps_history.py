#!/usr/bin/env python3
"""
Print retrain history for the ML comps valuation model from ml_model_metadata
-- the "is retraining actually improving things over time" visibility the
plan's Phase 5 calls for. Deliberately lightweight (no MLflow).

Usage:
    uv run scripts/report_ml_comps_history.py
    uv run scripts/report_ml_comps_history.py --target pe
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="ML comps valuation retrain history.")
    parser.add_argument("--target", help="Filter to one target (pe, pfcf)")
    parser.add_argument("--hf-db", default=HF_DB_PATH)
    args = parser.parse_args()

    conn = duckdb.connect(args.hf_db, read_only=True)
    try:
        where = "WHERE target = ?" if args.target else ""
        params = [args.target] if args.target else []
        rows = conn.execute(f"""
            SELECT target, model_version, trained_at, n_train_rows, n_tickers,
                   oos_rmse_log, oos_rmse_vs_baseline_pct, oos_coverage_p10_p90, is_active
            FROM ml_model_metadata
            {where}
            ORDER BY target, trained_at
        """, params).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No training runs recorded yet. Run scripts/train_ml_comps_valuation.py first.")
        return

    header = f"{'Target':<10} {'Version':<12} {'Trained At':<20} {'Rows':>10} {'Tickers':>8} {'RMSE(log)':>10} {'vsBaseline':>11} {'Coverage':>9} {'Active':>7}"
    print(header)
    print("-" * len(header))
    for target, version, trained_at, n_rows, n_tickers, rmse, vs_baseline, coverage, is_active in rows:
        print(
            f"{target:<10} {version:<12} {str(trained_at)[:19]:<20} {n_rows or 0:>10,} {n_tickers or 0:>8,}"
            f" {rmse if rmse is not None else 'N/A':>10}"
            f" {f'{vs_baseline:+.1%}' if vs_baseline is not None else 'N/A':>11}"
            f" {f'{coverage:.1%}' if coverage is not None else 'N/A':>9}"
            f" {'yes' if is_active else 'no':>7}"
        )


if __name__ == "__main__":
    main()
