#!/usr/bin/env python3
"""
Go/no-go validation gate for the ML comps-based fair valuation model.

Runs walk-forward validation for each candidate multiple in
historic_fundamentals.ml_comps_model.MULTIPLE_TARGETS (P/E, EV/EBITDA, P/FCF,
P/S) against a naive "predict the sector-median multiple" baseline, and
decides pass/fail per features/historic_fundamentals/ml_comps_valuation_plan.md
Phase 3 criteria:

    1. Aggregate OOS rmse_log at least 15% better than the naive baseline.
    2. Model beats baseline in at least 60% of individual folds (not just
       the aggregate — this is the check that would have caught the existing
       fundamentals-alpha model's flat-IC-hidden-by-good-backtest problem).
    3. coverage_p10_p90 between 70% and 90%, miss rate roughly symmetric.

Each multiple is judged independently against these three criteria; a
multiple only moves from MULTIPLE_TARGETS into
historic_fundamentals.ml_comps_model.PASSING_MULTIPLES (wired into batch
scoring/API/frontend) if it passes all three on its own — passing/failing is
not decided relative to the other candidates.

Each passing multiple's aggregate OOS metrics are also attached to its
currently active model_version row in ml_model_metadata (a targeted column
update, not a full-row replace — see HistoricFundamentalsDB.
update_active_ml_model_oos_metrics), so a real month-over-month calibration
history accumulates there instead of only living in the report/CSV below,
which this script overwrites on every run. That history is the actual
prerequisite for a future Phase 9 decision (replacing goal_pe/goal_low/
goal_high with this model) — see features/historic_fundamentals/
ml_comps_valuation_plan.md Phase 9.

Usage:
    uv run scripts/validate_ml_comps_valuation.py
    uv run scripts/validate_ml_comps_valuation.py --train-years 5 --test-years 1

Environment variables:
    HF_DB_PATH   path to historic_fundamentals.duckdb
    AV_DB_PATH (or AV_FINANCIALS_DB_PATH)  path to av_financials.duckdb
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH as AV_DB_PATH_DEFAULT  # noqa: E402
from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH_DEFAULT, HistoricFundamentalsDB  # noqa: E402
from historic_fundamentals.ml_comps_model import (  # noqa: E402
    FEATURE_COLS,
    MULTIPLE_TARGETS,
    build_training_frame,
    walk_forward_validate_quantile,
)

log = logging.getLogger(__name__)

RMSE_IMPROVEMENT_THRESHOLD = 0.15
FOLD_WIN_RATE_THRESHOLD = 0.60
COVERAGE_LOW, COVERAGE_HIGH = 0.70, 0.90
N_MULTIPLES_REQUIRED = 2


def _fmt(v, pct=False):
    if v is None:
        return "  N/A"
    return f"{v * 100:+.1f}%" if pct else f"{v:.4f}"


def evaluate_multiple(name: str, spec: dict, df, train_years: int, test_years: int) -> dict:
    target_col = f"target_log_{name}"
    result = walk_forward_validate_quantile(
        df,
        feature_cols=FEATURE_COLS,
        target_col=target_col,
        peer_col=spec["peer_col"],
        train_years=train_years,
        test_years=test_years,
    )
    agg = result.get("aggregate", {})
    if not agg:
        return {"multiple": name, "passed": False, "reason": "no folds produced", **agg}

    criterion_1 = agg["pct_improvement_vs_baseline"] >= RMSE_IMPROVEMENT_THRESHOLD
    criterion_2 = agg["fold_win_rate"] >= FOLD_WIN_RATE_THRESHOLD
    criterion_3 = COVERAGE_LOW <= agg["mean_coverage_p10_p90"] <= COVERAGE_HIGH
    passed = criterion_1 and criterion_2 and criterion_3

    return {
        "multiple": name,
        "passed": passed,
        "criterion_1_rmse_improvement": criterion_1,
        "criterion_2_fold_win_rate": criterion_2,
        "criterion_3_coverage": criterion_3,
        "fold_results": result["fold_results"],
        **agg,
    }


def build_report(evaluations: list[dict], overall_pass: bool) -> str:
    lines = [
        "# ML Comps Valuation — Walk-Forward Validation Report\n",
        f"**Gate**: at least {N_MULTIPLES_REQUIRED} of 3 multiples must pass "
        f"(RMSE improvement >= {RMSE_IMPROVEMENT_THRESHOLD:.0%}, "
        f"fold win rate >= {FOLD_WIN_RATE_THRESHOLD:.0%}, "
        f"coverage in [{COVERAGE_LOW:.0%}, {COVERAGE_HIGH:.0%}])\n",
        f"**Overall result**: {'PASS' if overall_pass else 'FAIL'}\n",
        "\n## Summary\n",
        "```",
        f"{'Multiple':<10} {'RMSE(model)':>12} {'RMSE(base)':>12} {'Improve':>9}"
        f" {'FoldWin':>8} {'Coverage':>9} {'Result':>7}",
        "-" * 76,
    ]
    for ev in evaluations:
        lines.append(
            f"{ev['multiple']:<10} {_fmt(ev.get('mean_rmse_log')):>12}"
            f" {_fmt(ev.get('mean_baseline_rmse_log')):>12}"
            f" {_fmt(ev.get('pct_improvement_vs_baseline'), pct=True):>9}"
            f" {_fmt(ev.get('fold_win_rate'), pct=True):>8}"
            f" {_fmt(ev.get('mean_coverage_p10_p90'), pct=True):>9}"
            f" {'PASS' if ev.get('passed') else 'FAIL':>7}"
        )
    lines.append("```\n")

    for ev in evaluations:
        lines.append(f"\n## {ev['multiple']} — per-fold detail\n")
        lines.append("```")
        lines.append(
            f"{'Fold':<10} {'Test period':<20} {'N test':>7} {'RMSE':>8}"
            f" {'Baseline':>9} {'Coverage':>9} {'Wins?':>6}"
        )
        lines.append("-" * 74)
        for fold in ev.get("fold_results", []):
            period = f"{fold['test_start'][:7]} - {fold['test_end'][:7]}"
            lines.append(
                f"{fold['fold']:<10} {period:<20} {fold['n_test_obs']:>7,}"
                f" {_fmt(fold['rmse_log']):>8}"
                f" {_fmt(fold['baseline_rmse_log']):>9}"
                f" {_fmt(fold['coverage_p10_p90'], pct=True):>9}"
                f" {'yes' if fold['model_wins'] else 'no':>6}"
            )
        lines.append("```\n")

    return "\n".join(lines)


def persist_oos_metrics(hf_db: str, evaluations: list[dict]) -> None:
    """Attach each multiple's aggregate OOS metrics to its currently active
    model_version row in ml_model_metadata, so calibration history accumulates
    across monthly runs instead of only living in the overwritten report/CSV
    (see PLAN note: this is what actually lets a future Phase 9 decision — go/
    no-go on replacing goal_pe/goal_low/goal_high — point to N consecutive
    months of maintained calibration, not just "it looked fine today").

    Silently skips multiples with no active row (e.g. evebitda, which never
    cleared the Phase 3 gate and so was never trained) — nothing to attach to.
    """
    db = HistoricFundamentalsDB(hf_db)
    try:
        for ev in evaluations:
            wrote = db.update_active_ml_model_oos_metrics(
                target=ev["multiple"],
                oos_rmse_log=ev.get("mean_rmse_log"),
                oos_rmse_vs_baseline_pct=ev.get("pct_improvement_vs_baseline"),
                oos_coverage_p10_p90=ev.get("mean_coverage_p10_p90"),
            )
            if wrote:
                log.info("Persisted OOS metrics for %s to ml_model_metadata (active version)", ev["multiple"])
            else:
                log.info("No active model_version for %s — OOS metrics not persisted (report/CSV only)",
                          ev["multiple"])
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="ML comps valuation go/no-go gate.")
    parser.add_argument("--train-years", type=int, default=5)
    parser.add_argument("--test-years", type=int, default=1)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    hf_db = os.getenv("HF_DB_PATH", HF_DB_PATH_DEFAULT)
    av_db = os.getenv("AV_DB_PATH", os.getenv("AV_FINANCIALS_DB_PATH", AV_DB_PATH_DEFAULT))

    log.info("Loading training frame from %s / %s", hf_db, av_db)
    hf_conn = duckdb.connect(hf_db, read_only=True)
    av_conn = duckdb.connect(av_db, read_only=True)
    try:
        df = build_training_frame(hf_conn, av_conn)
    finally:
        hf_conn.close()
        av_conn.close()
    log.info("Training frame: %d rows, %d tickers", len(df), df["ticker"].nunique())

    evaluations = [
        evaluate_multiple(name, spec, df, args.train_years, args.test_years)
        for name, spec in MULTIPLE_TARGETS.items()
    ]

    n_passed = sum(1 for ev in evaluations if ev["passed"])
    overall_pass = n_passed >= N_MULTIPLES_REQUIRED

    persist_oos_metrics(hf_db, evaluations)

    report = build_report(evaluations, overall_pass)
    print(report)

    out_path = ROOT / "docs" / "ml_comps_validation_report.md"
    out_path.write_text(report)
    log.info("Report written to %s", out_path)

    # Machine-readable fold-level results, for the Phase 8 monitoring notebook
    # (notebooks/ml_comps_valuation.ipynb) to plot coverage/RMSE over time
    # without re-running the ~1hr walk-forward gate on every notebook execution.
    import pandas as pd
    fold_rows = []
    for ev in evaluations:
        for fold in ev.get("fold_results", []):
            fold_rows.append({"multiple": ev["multiple"], **fold})
    if fold_rows:
        csv_path = ROOT / "docs" / "ml_comps_validation_folds.csv"
        pd.DataFrame(fold_rows).to_csv(csv_path, index=False)
        log.info("Fold-level results written to %s", csv_path)

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
