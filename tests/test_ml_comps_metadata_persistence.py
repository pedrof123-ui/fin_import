"""
Tests for the OOS-metrics persistence added to scripts/validate_ml_comps_valuation.py
and HistoricFundamentalsDB.update_active_ml_model_oos_metrics.

Without this, validate_ml_comps_valuation.py only wrote docs/ml_comps_validation_report.md
and docs/ml_comps_validation_folds.csv — both overwritten on every run, so a month-over-
month calibration history never accumulated anywhere queryable. The fix attaches each
multiple's aggregate OOS metrics to its currently-active ml_model_metadata row, which is
already keyed by the model_version that changes every training run.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from historic_fundamentals.db import HistoricFundamentalsDB  # noqa: E402

from validate_ml_comps_valuation import persist_oos_metrics  # noqa: E402


def _seed_active_row(db: HistoricFundamentalsDB, target: str, model_version: str, is_active: bool = True) -> None:
    import pandas as pd
    db.upsert_ml_model_metadata(pd.DataFrame([{
        "model_name": "ml_comps_valuation",
        "model_version": model_version,
        "target": target,
        "trained_at": datetime.now(UTC),
        "n_train_rows": 1000,
        "n_tickers": 100,
        "is_active": is_active,
    }]))


def test_update_active_ml_model_oos_metrics_writes_to_active_row(tmp_path):
    db = HistoricFundamentalsDB(str(tmp_path / "hf.duckdb"))
    try:
        _seed_active_row(db, "pe", "2026-08-01")

        wrote = db.update_active_ml_model_oos_metrics(
            target="pe", oos_rmse_log=0.234, oos_rmse_vs_baseline_pct=0.183, oos_coverage_p10_p90=0.81,
        )
        assert wrote is True

        row = db.conn.execute(
            "SELECT oos_rmse_log, oos_rmse_vs_baseline_pct, oos_coverage_p10_p90, n_train_rows, trained_at "
            "FROM ml_model_metadata WHERE target = 'pe' AND is_active = TRUE"
        ).fetchone()
        assert row[0] == 0.234
        assert row[1] == 0.183
        assert row[2] == 0.81
        # Training-time columns must survive a targeted update, not get nulled out.
        assert row[3] == 1000
        assert row[4] is not None
    finally:
        db.close()


def test_update_active_ml_model_oos_metrics_only_touches_active_version(tmp_path):
    """A stale (is_active=False) version of the same target must not be affected,
    and only the currently active version's row should be updated."""
    db = HistoricFundamentalsDB(str(tmp_path / "hf.duckdb"))
    try:
        _seed_active_row(db, "pe", "2026-07-01", is_active=False)
        _seed_active_row(db, "pe", "2026-08-01", is_active=True)

        db.update_active_ml_model_oos_metrics(
            target="pe", oos_rmse_log=0.1, oos_rmse_vs_baseline_pct=0.2, oos_coverage_p10_p90=0.8,
        )

        stale = db.conn.execute(
            "SELECT oos_rmse_log FROM ml_model_metadata WHERE target = 'pe' AND model_version = '2026-07-01'"
        ).fetchone()
        active = db.conn.execute(
            "SELECT oos_rmse_log FROM ml_model_metadata WHERE target = 'pe' AND model_version = '2026-08-01'"
        ).fetchone()
        assert stale[0] is None
        assert active[0] == 0.1
    finally:
        db.close()


def test_update_active_ml_model_oos_metrics_no_active_row_returns_false(tmp_path):
    """evebitda never clears the Phase 3 gate, so train_ml_comps_valuation.py never
    writes a row for it — persistence must degrade to a no-op, not raise."""
    db = HistoricFundamentalsDB(str(tmp_path / "hf.duckdb"))
    try:
        wrote = db.update_active_ml_model_oos_metrics(
            target="evebitda", oos_rmse_log=0.5, oos_rmse_vs_baseline_pct=0.05, oos_coverage_p10_p90=0.6,
        )
        assert wrote is False
    finally:
        db.close()


def test_persist_oos_metrics_writes_for_each_evaluation(tmp_path, monkeypatch):
    db_path = tmp_path / "hf.duckdb"
    db = HistoricFundamentalsDB(str(db_path))
    _seed_active_row(db, "pe", "2026-08-01")
    _seed_active_row(db, "pfcf", "2026-08-01")
    _seed_active_row(db, "ps", "2026-08-01")
    db.close()

    evaluations = [
        {"multiple": "pe", "mean_rmse_log": 0.20, "pct_improvement_vs_baseline": 0.183, "mean_coverage_p10_p90": 0.75},
        {"multiple": "pfcf", "mean_rmse_log": 0.25, "pct_improvement_vs_baseline": 0.187, "mean_coverage_p10_p90": 0.73},
        {"multiple": "ps", "mean_rmse_log": 0.18, "pct_improvement_vs_baseline": 0.236, "mean_coverage_p10_p90": 0.77},
        # evebitda: no active row seeded — must be skipped gracefully, not raise.
        {"multiple": "evebitda", "mean_rmse_log": 0.30, "pct_improvement_vs_baseline": 0.147, "mean_coverage_p10_p90": 0.72},
    ]

    persist_oos_metrics(str(db_path), evaluations)

    db2 = HistoricFundamentalsDB(str(db_path))
    try:
        rows = db2.conn.execute(
            "SELECT target, oos_rmse_vs_baseline_pct FROM ml_model_metadata WHERE is_active = TRUE ORDER BY target"
        ).fetchall()
        assert dict(rows) == {"pe": 0.183, "pfcf": 0.187, "ps": 0.236}
        # evebitda got no row written at all (never had an active version to attach to).
        n_evebitda = db2.conn.execute(
            "SELECT COUNT(*) FROM ml_model_metadata WHERE target = 'evebitda'"
        ).fetchone()[0]
        assert n_evebitda == 0
    finally:
        db2.close()
