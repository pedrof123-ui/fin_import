#!/usr/bin/env python3
"""
Monthly Telegram report on ml_comps_valuation calibration health, and progress
toward a real Phase 9 decision (features/historic_fundamentals/
ml_comps_valuation_plan.md — replacing goal_pe/goal_low/goal_high with this
model outright).

Runs after scripts/validate_ml_comps_valuation.py, which persists each
production multiple's (P/E, P/FCF, P/S) latest walk-forward OOS metrics to
ml_model_metadata (see historic_fundamentals.db.update_active_ml_model_oos_metrics).
This script reads that history back out, checks the current month against the
same Phase 3 gate criteria, and computes a consecutive-months-passing streak
per multiple by walking model_version history newest-first until it hits a
month that failed, or a gap (no OOS metrics recorded that month at all —
treated the same as a fail, since we don't actually know that month held).

Mirrors scripts/mda_sweep_report.py's Telegram-reporting pattern. Exits
non-zero if the send fails, so cron_wrap.sh alerts on a broken channel.

Usage:
    uv run scripts/report_ml_comps_calibration.py
    uv run scripts/report_ml_comps_calibration.py --dry-run   # print, don't send
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH_DEFAULT  # noqa: E402
from historic_fundamentals.ml_comps_model import PASSING_MULTIPLES  # noqa: E402

TELEGRAM_ENV = Path.home() / ".claude" / "channels" / "telegram" / ".env"
CHAT_ID = "8351706654"

# Same thresholds validate_ml_comps_valuation.py's Phase 3 gate uses — a
# multiple's month only counts toward the streak if it would have passed the
# gate that month, not just "ran without error".
RMSE_IMPROVEMENT_THRESHOLD = 0.15
COVERAGE_LOW, COVERAGE_HIGH = 0.70, 0.90

# Consecutive months of held calibration, across ALL THREE production
# multiples simultaneously, before this script flags the report as ready for
# a real Phase 9 go/no-go conversation. Not in the plan doc numerically —
# 6 was chosen as "long enough to rule out a lucky short streak, short enough
# to not be a years-long wait" and is easy to change here if that's wrong.
READY_FOR_REVIEW_MONTHS = 6

# Mirrors api.ai_dcf_router._RECONCILIATION_LOG_DB's path construction — not imported directly
# to avoid pulling in that module's much heavier FastAPI/agents-SDK dependencies for what's just
# a path constant.
RECONCILIATION_LOG_DB_DEFAULT = str(Path(__file__).resolve().parent.parent / "data" / "dcf_reconciliation_log.duckdb")

# Volume gate for the ML comps triangulation-divergence question
# (PLAN_ML_COMPS_TRIANGULATION.md's deferred anchor-promotion follow-up). AI Researcher reports
# are generated on demand, not on a batch schedule, so a calendar gate (like
# READY_FOR_REVIEW_MONTHS above) doesn't guarantee enough data points — gate on volume instead.
# 30 was chosen the same way as READY_FOR_REVIEW_MONTHS: "enough to see a real pattern, not so
# many it's a multi-year wait" — easy to change here if that's wrong.
ML_COMPS_ANCHOR_REVIEW_COUNT = 30

# Same "material divergence" bar already used for mechanical-vs-AI-DCF divergence
# (api.ai_dcf_router._DIVERGENCE_WARN_THRESHOLD) — reused rather than inventing a second
# definition of "material" for the ML comps case.
ML_COMPS_DIVERGENCE_THRESHOLD = 0.20


def bot_token() -> str:
    for line in TELEGRAM_ENV.read_text().splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"TELEGRAM_BOT_TOKEN not found in {TELEGRAM_ENV}")


def _passed_gate(oos_rmse_vs_baseline_pct, oos_coverage_p10_p90) -> bool | None:
    """None = no data for this month (never validated, or validation failed
    before persisting) — treated as a streak-breaking gap by the caller, but
    reported distinctly from an actual fail."""
    if oos_rmse_vs_baseline_pct is None or oos_coverage_p10_p90 is None:
        return None
    return (
        oos_rmse_vs_baseline_pct >= RMSE_IMPROVEMENT_THRESHOLD
        and COVERAGE_LOW <= oos_coverage_p10_p90 <= COVERAGE_HIGH
    )


def build_ml_comps_triangulation_section(reconciliation_log_db: str) -> str:
    """Answers 'does ML comps diverge from the Valuation Analyst's actual fair value often
    enough to earn its own anchor in the Chief's target_price_validation triangulation' with
    real logged data (api.ai_dcf_router.log_dcf_reconciliation), instead of guessing —
    PLAN_ML_COMPS_TRIANGULATION.md's deferred follow-up."""
    if not Path(reconciliation_log_db).exists():
        return (
            "\nML comps triangulation: no dcf_reconciliation_log.duckdb yet — no AI Researcher "
            "reports generated since this tracking was added."
        )
    conn = duckdb.connect(reconciliation_log_db, read_only=True)
    try:
        n, n_diverging = conn.execute("""
            SELECT COUNT(*), SUM(CASE WHEN ABS(ml_comps_divergence_pct) > ? THEN 1 ELSE 0 END)
            FROM dcf_reconciliation_log
            WHERE ml_comps_divergence_pct IS NOT NULL
        """, [ML_COMPS_DIVERGENCE_THRESHOLD]).fetchone()
    finally:
        conn.close()

    if not n:
        return "\nML comps triangulation: 0 report(s) logged with an ML comps anchor yet."

    pct_diverging = n_diverging / n
    lines = [
        f"\nML comps triangulation: {n} report(s) logged, {n_diverging} ({pct_diverging:.0%}) "
        f"diverged >{ML_COMPS_DIVERGENCE_THRESHOLD:.0%} from the Valuation Analyst's fair value."
    ]
    if n >= ML_COMPS_ANCHOR_REVIEW_COUNT:
        lines.append(
            f"{n} >= {ML_COMPS_ANCHOR_REVIEW_COUNT} logged — enough volume for a real "
            "conversation about promoting ML comps to its own anchor in target_price_validation."
        )
    else:
        lines.append(f"{ML_COMPS_ANCHOR_REVIEW_COUNT - n} more needed before that conversation makes sense.")
    return "\n".join(lines)


def build_message(hf_db: str, reconciliation_log_db: str = RECONCILIATION_LOG_DB_DEFAULT) -> str:
    conn = duckdb.connect(hf_db, read_only=True)
    try:
        lines = [f"ML comps calibration report — {__import__('datetime').date.today()}"]
        min_streak = None

        for target in PASSING_MULTIPLES:
            history = conn.execute("""
                SELECT model_version, oos_rmse_vs_baseline_pct, oos_coverage_p10_p90
                FROM ml_model_metadata
                WHERE model_name = 'ml_comps_valuation' AND target = ?
                ORDER BY model_version DESC
            """, [target]).fetchall()

            if not history:
                lines.append(f"{target}: WARNING no ml_model_metadata rows at all — never trained?")
                min_streak = 0
                continue

            streak = 0
            for _version, rmse_pct, coverage in history:
                result = _passed_gate(rmse_pct, coverage)
                if result is not True:
                    break
                streak += 1
            min_streak = streak if min_streak is None else min(min_streak, streak)

            latest_version, latest_rmse, latest_coverage = history[0]
            this_month = _passed_gate(latest_rmse, latest_coverage)
            if this_month is None:
                status = "WARNING no OOS metrics for latest run — validation step may have failed"
            elif this_month is False:
                rmse_str = f"{latest_rmse:+.1%}" if latest_rmse is not None else "n/a"
                cov_str = f"{latest_coverage:.1%}" if latest_coverage is not None else "n/a"
                status = f"WARNING gate FAILED this month (rmse improve {rmse_str}, coverage {cov_str})"
            else:
                status = f"OK, {streak} consecutive month(s) holding"
            lines.append(f"{target} ({latest_version}): {status}")

        if min_streak is not None and min_streak >= READY_FOR_REVIEW_MONTHS:
            lines.append(
                f"\nAll {len(PASSING_MULTIPLES)} production multiples have held calibration for "
                f"{min_streak}+ consecutive months — ready for a real Phase 9 review "
                f"(features/historic_fundamentals/ml_comps_valuation_plan.md)."
            )
        elif min_streak is not None:
            lines.append(
                f"\nShortest current streak: {min_streak} month(s) "
                f"({READY_FOR_REVIEW_MONTHS - min_streak} more needed before a Phase 9 review makes sense)."
            )

        lines.append(build_ml_comps_triangulation_section(reconciliation_log_db))

        return "\n".join(lines)
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Monthly ml_comps calibration report.")
    parser.add_argument("--db", default=os.getenv("HF_DB_PATH", HF_DB_PATH_DEFAULT))
    parser.add_argument("--reconciliation-log-db", default=RECONCILIATION_LOG_DB_DEFAULT)
    parser.add_argument("--dry-run", action="store_true", help="Print only, don't send to Telegram")
    args = parser.parse_args()

    msg = build_message(args.db, args.reconciliation_log_db)
    print(msg)
    if args.dry_run:
        return 0

    r = requests.post(
        f"https://api.telegram.org/bot{bot_token()}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg}, timeout=30,
    )
    if not (r.ok and r.json().get("ok")):
        print(f"telegram send failed: {r.status_code} {r.text[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
