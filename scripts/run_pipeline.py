#!/usr/bin/env python3
"""
End-to-end pipeline runner for the fundamentals-alpha model.

Runs each step in the correct order, stops on failure, and reports timing.

Default pipeline (fast path, no AV data fetch):
    1. hf_update        — rebuild monthly_pe features from existing financials DB
    1b. compute_dcf_batch — refresh dcf_results cache for the Screener's DCF-upside
                            filter (~15 min for the full universe)
    2. validate_model   — walk-forward validation (OOS IC, ICIR, SHAP)
    3. train_model      — train XGBoost on full history, save model.joblib
    4. run_backtest     — composite + XGBoost + guardrails backtest, save report
    5. score_live       — score current universe, save ranked CSV

With --av-update (slow, ~30 min, rate-limited to 75 calls/min):
    0. av_update      — fetch latest financials from Alpha Vantage API
    then steps 1–5 as above.

Usage:
    uv run scripts/run_pipeline.py                  # fast path
    uv run scripts/run_pipeline.py --av-update      # full refresh including AV
    uv run scripts/run_pipeline.py --skip-validate  # skip walk-forward (faster)
    uv run scripts/run_pipeline.py --skip-train     # reuse existing model.joblib
    uv run scripts/run_pipeline.py --skip-dcf       # skip DCF batch (saves ~15 min)
    uv run scripts/run_pipeline.py --quarterly      # quarterly backtest
    uv run scripts/run_pipeline.py --tc-bps 20      # higher transaction cost
    uv run scripts/run_pipeline.py --dry-run        # print commands without running

Environment variables required:
    HF_DB_PATH      path to historic_fundamentals.duckdb
    AV_DB_PATH      path to av_financials.duckdb
    PRICES_DB_PATH  path to prices.duckdb (for SPY benchmark)
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger(__name__)


def _run(cmd: list[str], label: str, dry_run: bool = False, fatal: bool = True) -> float:
    """Run a command, stream output, return elapsed seconds.

    fatal=True (default): non-zero exit aborts the whole pipeline — right for
    anything the live trading pipeline (train_model/run_backtest/score_live)
    actually depends on.
    fatal=False: log and continue. Use for steps whose exit code encodes a
    pass/fail judgment about themselves, not a real error — e.g.
    validate_ml_comps_valuation.py deliberately returns 1 when this month's
    re-validation gate fails, which must not block train_model/score_live
    (the actual live-trading refresh) from running just because an additive,
    non-trading-critical experimental sub-model's calibration dipped.
    """
    print(f"\n{'=' * 70}")
    print(f"STEP: {label}")
    print(f"CMD:  {' '.join(cmd)}")
    print(f"{'=' * 70}")

    if dry_run:
        print("[dry-run] skipped")
        return 0.0

    t0 = time.time()
    result = subprocess.run(cmd, cwd=ROOT)
    elapsed = time.time() - t0

    if result.returncode != 0:
        if fatal:
            print(f"\nFAILED: {label} exited with code {result.returncode}. Pipeline stopped.")
            sys.exit(result.returncode)
        print(f"\nWARNING: {label} exited with code {result.returncode} — continuing "
              f"(non-fatal step) ({elapsed:.1f}s)")
        return elapsed

    print(f"\nDone: {label} ({elapsed:.1f}s)")
    return elapsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="End-to-end fundamentals-alpha pipeline runner."
    )
    parser.add_argument("--av-update", action="store_true",
                        help="Run av_update first (slow: ~30 min, rate-limited)")
    parser.add_argument("--skip-validate", action="store_true",
                        help="Skip walk-forward validation (saves ~30s)")
    parser.add_argument("--skip-train", action="store_true",
                        help="Skip model training (reuse existing model.joblib)")
    parser.add_argument("--skip-dcf", action="store_true",
                        help="Skip DCF batch (saves ~15 min for the full universe)")
    parser.add_argument("--enable-ml-comps", action="store_true",
                        help="Train + score + re-validate the ML comps valuation model "
                             "(P/E, P/FCF, P/S; ~90 min total, ~85 of it the walk-forward "
                             "re-validation). Off by default — see features/"
                             "historic_fundamentals/ml_comps_valuation_plan.md for the "
                             "Phase 3 gate this passed before being wired in here, and "
                             "Phase 9 for why re-validating monthly matters.")
    parser.add_argument("--quarterly", action="store_true",
                        help="Run quarterly backtest in addition to monthly")
    parser.add_argument("--tc-bps", type=float, default=10.0,
                        help="Transaction cost in bps (default: 10)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print commands without executing them")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    uv_bin = shutil.which("uv") or "/home/pedro/.local/bin/uv"
    uv = [uv_bin, "run"]
    timings: dict[str, float] = {}

    print(f"\n{'#' * 70}")
    print("  Fundamentals Alpha — End-to-End Pipeline")
    print(f"{'#' * 70}")
    if args.av_update:
        print("  AV update: YES (slow path)")
    else:
        print("  AV update: NO  (fast path — using existing financials DB)")
    if args.skip_validate:
        print("  Walk-forward validation: SKIPPED")
    if args.skip_train:
        print("  Model training: SKIPPED (reusing model.joblib)")
    if args.skip_dcf:
        print("  DCF batch: SKIPPED")
    if args.enable_ml_comps:
        print("  ML Comps Valuation: ENABLED")
    print(f"  TC: {args.tc_bps:.0f} bps")
    print()

    # Step 0: AV update (optional, slow)
    if args.av_update:
        timings["av_update"] = _run(
            uv + ["scripts/av_update.py"],
            "AV Update — fetch latest financials from Alpha Vantage",
            dry_run=args.dry_run,
        )

    # Step 1: hf_update
    timings["hf_update"] = _run(
        uv + ["scripts/hf_update.py"],
        "HF Update — rebuild monthly_pe features",
        dry_run=args.dry_run,
    )

    # Step 1b: DCF batch (refreshes dcf_results for the Screener's DCF-upside filter)
    if not args.skip_dcf:
        timings["compute_dcf_batch"] = _run(
            uv + ["scripts/compute_dcf_batch.py"],
            "DCF Batch — refresh dcf_results cache for the Screener",
            dry_run=args.dry_run,
        )

    # Step 1c: ML comps valuation (opt-in; additive to goal_pe/goal_low/goal_high)
    if args.enable_ml_comps:
        timings["train_ml_comps"] = _run(
            uv + ["scripts/train_ml_comps_valuation.py"],
            "ML Comps Valuation — train quantile models (P/E, P/FCF, P/S)",
            dry_run=args.dry_run,
        )
        timings["score_ml_comps"] = _run(
            uv + ["scripts/score_ml_comps_valuation.py"],
            "ML Comps Valuation — batch score current universe",
            dry_run=args.dry_run,
        )
        timings["validate_ml_comps"] = _run(
            uv + ["scripts/validate_ml_comps_valuation.py"],
            "ML Comps Valuation — walk-forward gate + calibration history (~85 min)",
            dry_run=args.dry_run, fatal=False,
        )
        timings["report_ml_comps"] = _run(
            uv + ["scripts/report_ml_comps_calibration.py"],
            "ML Comps Valuation — Telegram calibration report",
            dry_run=args.dry_run, fatal=False,
        )

    # Step 2: walk-forward validation
    if not args.skip_validate:
        timings["validate_model"] = _run(
            uv + ["scripts/validate_model.py"],
            "Walk-Forward Validation — OOS IC, ICIR, feature importance",
            dry_run=args.dry_run,
        )

    # Step 3: train model
    if not args.skip_train:
        timings["train_model"] = _run(
            uv + ["scripts/train_model.py"],
            "Train Model — fit XGBoost on full history, save model.joblib",
            dry_run=args.dry_run,
        )

    # Step 4: backtest (monthly, model + guardrails)
    backtest_cmd = uv + [
        "scripts/run_backtest.py",
        "--model", "--guardrails",
        "--tc-bps", str(args.tc_bps),
    ]
    timings["run_backtest"] = _run(
        backtest_cmd,
        "Backtest — composite + XGBoost + guardrails (monthly)",
        dry_run=args.dry_run,
    )

    # Step 4b: quarterly backtest (optional)
    if args.quarterly:
        timings["run_backtest_quarterly"] = _run(
            backtest_cmd + ["--quarterly"],
            "Backtest — composite + XGBoost + guardrails (quarterly)",
            dry_run=args.dry_run,
        )

    # Step 5: live scoring
    timings["score_live"] = _run(
        uv + ["scripts/score_live.py"],
        "Live Scoring — score current universe, save ranked CSV",
        dry_run=args.dry_run,
    )

    # Summary
    total = sum(timings.values())
    print(f"\n{'#' * 70}")
    print("  Pipeline Complete")
    print(f"{'#' * 70}")
    print(f"  {'Step':<30} {'Time':>8}")
    print(f"  {'-' * 40}")
    for step, t in timings.items():
        print(f"  {step:<30} {t:>7.1f}s")
    print(f"  {'-' * 40}")
    print(f"  {'TOTAL':<30} {total:>7.1f}s")
    print()
    print("  Outputs:")
    print(f"    docs/backtest_results_model_guardrails.md")
    print(f"    docs/validation_report.md")
    print(f"    docs/live_scores_*.csv")
    if not args.skip_dcf:
        print(f"    data/historic_fundamentals.duckdb::dcf_results (screener DCF cache)")
    if not args.skip_train:
        print(f"    data/model.joblib")
    print()


if __name__ == "__main__":
    main()
