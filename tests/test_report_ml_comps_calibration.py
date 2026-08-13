"""Tests for scripts/report_ml_comps_calibration.py's streak logic and message content."""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from historic_fundamentals.db import HistoricFundamentalsDB  # noqa: E402

from report_ml_comps_calibration import READY_FOR_REVIEW_MONTHS, build_message  # noqa: E402


def _seed_month(conn, target, version, rmse_pct, coverage, is_active=False):
    conn.execute("""
        INSERT INTO ml_model_metadata
        (model_name, model_version, target, trained_at, oos_rmse_vs_baseline_pct,
         oos_coverage_p10_p90, is_active)
        VALUES ('ml_comps_valuation', ?, ?, ?, ?, ?, ?)
    """, [version, target, datetime.now(UTC), rmse_pct, coverage, is_active])


def test_all_passing_reports_correct_streak(tmp_path):
    db_path = tmp_path / "hf.duckdb"
    HistoricFundamentalsDB(str(db_path)).close()
    conn = duckdb.connect(str(db_path))
    for target in ("pe", "pfcf", "ps"):
        for i, month in enumerate(["2026-06-01", "2026-07-01", "2026-08-01"]):
            _seed_month(conn, target, month, 0.18, 0.80, is_active=(i == 2))
    conn.close()

    msg = build_message(str(db_path))
    assert "3 consecutive month(s) holding" in msg
    assert "WARNING" not in msg
    assert f"{READY_FOR_REVIEW_MONTHS - 3} more needed" in msg


def test_one_multiple_failing_this_month_is_flagged(tmp_path):
    db_path = tmp_path / "hf.duckdb"
    HistoricFundamentalsDB(str(db_path)).close()
    conn = duckdb.connect(str(db_path))
    _seed_month(conn, "pe", "2026-08-01", 0.18, 0.80, is_active=True)
    _seed_month(conn, "pfcf", "2026-08-01", 0.05, 0.80, is_active=True)  # below 15% threshold
    _seed_month(conn, "ps", "2026-08-01", 0.20, 0.95, is_active=True)   # coverage above 90%
    conn.close()

    msg = build_message(str(db_path))
    assert "pe (2026-08-01): OK" in msg
    assert "pfcf (2026-08-01): WARNING gate FAILED" in msg
    assert "ps (2026-08-01): WARNING gate FAILED" in msg
    assert "Shortest current streak: 0 month(s)" in msg


def test_streak_breaks_at_first_failure_looking_backward(tmp_path):
    """A pass this month after a fail two months ago should NOT count the pre-fail
    months — the streak is consecutive-from-latest, not total-passing-count."""
    db_path = tmp_path / "hf.duckdb"
    HistoricFundamentalsDB(str(db_path)).close()
    conn = duckdb.connect(str(db_path))
    _seed_month(conn, "pe", "2026-05-01", 0.20, 0.80)   # pass (but broken by a later fail)
    _seed_month(conn, "pe", "2026-06-01", 0.05, 0.80)   # FAIL — breaks the streak here
    _seed_month(conn, "pe", "2026-07-01", 0.18, 0.80)   # pass
    _seed_month(conn, "pe", "2026-08-01", 0.19, 0.82, is_active=True)  # pass
    conn.close()

    msg = build_message(str(db_path))
    assert "pe (2026-08-01): OK, 2 consecutive month(s) holding" in msg


def test_missing_oos_metrics_month_breaks_streak_as_a_gap(tmp_path):
    db_path = tmp_path / "hf.duckdb"
    HistoricFundamentalsDB(str(db_path)).close()
    conn = duckdb.connect(str(db_path))
    _seed_month(conn, "pe", "2026-07-01", None, None)  # gap — no OOS metrics that month
    _seed_month(conn, "pe", "2026-08-01", 0.18, 0.80, is_active=True)
    conn.close()

    msg = build_message(str(db_path))
    assert "pe (2026-08-01): OK, 1 consecutive month(s) holding" in msg


def test_no_history_at_all_reports_warning_not_crash(tmp_path):
    db_path = tmp_path / "hf.duckdb"
    HistoricFundamentalsDB(str(db_path)).close()

    msg = build_message(str(db_path))
    assert "pe: WARNING no ml_model_metadata rows at all" in msg


def test_ready_for_review_threshold_flags_all_three(tmp_path):
    db_path = tmp_path / "hf.duckdb"
    HistoricFundamentalsDB(str(db_path)).close()
    conn = duckdb.connect(str(db_path))
    months = [f"2026-{m:02d}-01" for m in range(1, READY_FOR_REVIEW_MONTHS + 1)]
    for target in ("pe", "pfcf", "ps"):
        for i, month in enumerate(months):
            _seed_month(conn, target, month, 0.18, 0.80, is_active=(i == len(months) - 1))
    conn.close()

    msg = build_message(str(db_path))
    assert "ready for a real Phase 9 review" in msg
