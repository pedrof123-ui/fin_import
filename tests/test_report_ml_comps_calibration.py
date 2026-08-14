"""Tests for scripts/report_ml_comps_calibration.py's streak logic and message content."""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from historic_fundamentals.db import HistoricFundamentalsDB  # noqa: E402

from report_ml_comps_calibration import (  # noqa: E402
    ML_COMPS_ANCHOR_REVIEW_COUNT, READY_FOR_REVIEW_MONTHS, build_ml_comps_triangulation_section,
    build_message,
)


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

    msg = build_message(str(db_path), str(tmp_path / "no_reconciliation_log.duckdb"))
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

    msg = build_message(str(db_path), str(tmp_path / "no_reconciliation_log.duckdb"))
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

    msg = build_message(str(db_path), str(tmp_path / "no_reconciliation_log.duckdb"))
    assert "pe (2026-08-01): OK, 2 consecutive month(s) holding" in msg


def test_missing_oos_metrics_month_breaks_streak_as_a_gap(tmp_path):
    db_path = tmp_path / "hf.duckdb"
    HistoricFundamentalsDB(str(db_path)).close()
    conn = duckdb.connect(str(db_path))
    _seed_month(conn, "pe", "2026-07-01", None, None)  # gap — no OOS metrics that month
    _seed_month(conn, "pe", "2026-08-01", 0.18, 0.80, is_active=True)
    conn.close()

    msg = build_message(str(db_path), str(tmp_path / "no_reconciliation_log.duckdb"))
    assert "pe (2026-08-01): OK, 1 consecutive month(s) holding" in msg


def test_no_history_at_all_reports_warning_not_crash(tmp_path):
    db_path = tmp_path / "hf.duckdb"
    HistoricFundamentalsDB(str(db_path)).close()

    msg = build_message(str(db_path), str(tmp_path / "no_reconciliation_log.duckdb"))
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

    msg = build_message(str(db_path), str(tmp_path / "no_reconciliation_log.duckdb"))
    assert "ready for a real Phase 9 review" in msg


# ---------------------------------------------------------------------------
# ML comps triangulation-divergence section (PLAN_ML_COMPS_TRIANGULATION.md follow-up)
# ---------------------------------------------------------------------------

def _seed_reconciliation_row(conn, ticker, ml_comps_divergence_pct):
    conn.execute("""
        INSERT INTO dcf_reconciliation_log
            (ticker, model, generated_at, mechanical_base, ai_base, divergence_pct, anchor,
             reconciliation_text, ml_comps_fair_value, ml_comps_ground_truth, ml_comps_divergence_pct)
        VALUES (?, 'test-model', now(), 50.0, 55.0, 0.1, 'mechanical', '', 60.0, 60.0, ?)
    """, [ticker, ml_comps_divergence_pct])


def _make_reconciliation_db(db_path):
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE dcf_reconciliation_log (
            ticker VARCHAR, model VARCHAR, generated_at TIMESTAMP,
            mechanical_base DOUBLE, ai_base DOUBLE, divergence_pct DOUBLE, anchor VARCHAR,
            reconciliation_text VARCHAR, ml_comps_fair_value DOUBLE, ml_comps_ground_truth DOUBLE,
            ml_comps_divergence_pct DOUBLE
        )
    """)
    return conn


def test_ml_comps_triangulation_section_no_db_file(tmp_path):
    section = build_ml_comps_triangulation_section(str(tmp_path / "does_not_exist.duckdb"))
    assert "no dcf_reconciliation_log.duckdb yet" in section


def test_ml_comps_triangulation_section_no_rows_logged(tmp_path):
    db_path = tmp_path / "log.duckdb"
    _make_reconciliation_db(db_path).close()

    section = build_ml_comps_triangulation_section(str(db_path))
    assert "0 report(s) logged" in section


def test_ml_comps_triangulation_section_reports_divergence_rate(tmp_path):
    db_path = tmp_path / "log.duckdb"
    conn = _make_reconciliation_db(db_path)
    _seed_reconciliation_row(conn, "AAPL", 0.05)   # not material
    _seed_reconciliation_row(conn, "MSFT", 0.35)   # material (> 20%)
    _seed_reconciliation_row(conn, "NVDA", -0.25)  # material (abs > 20%)
    conn.close()

    section = build_ml_comps_triangulation_section(str(db_path))
    assert "3 report(s) logged, 2 (67%) diverged" in section
    assert f"{ML_COMPS_ANCHOR_REVIEW_COUNT - 3} more needed" in section


def test_ml_comps_triangulation_section_flags_ready_for_review(tmp_path):
    db_path = tmp_path / "log.duckdb"
    conn = _make_reconciliation_db(db_path)
    for i in range(ML_COMPS_ANCHOR_REVIEW_COUNT):
        _seed_reconciliation_row(conn, f"T{i}", 0.05)
    conn.close()

    section = build_ml_comps_triangulation_section(str(db_path))
    assert "enough volume for a real conversation" in section
