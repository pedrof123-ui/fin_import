"""
Phase 0 DCF Screener tests — scripts/compute_dcf_batch.py.

Runs against a copy of the real historic_fundamentals.duckdb (via tmp_path) so the
batch script's writes never touch production data. av_financials.duckdb is read
read-only from its real location, same as valuation_data.py's pattern.

See DCF_SCREENER_PLAN.md Phase 0.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest

from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH, HistoricFundamentalsDB
from scripts.compute_dcf_batch import compute_dcf_batch

_TICKERS = ["AAPL", "JPM", "WMT", "BRUN"]  # BRUN: known thin-data ticker (< 8 quarters)


@pytest.fixture
def hf_db_copy(tmp_path) -> str:
    if not Path(HF_DB_PATH).exists():
        pytest.skip("historic_fundamentals.duckdb not present")
    dest = tmp_path / "historic_fundamentals.duckdb"
    shutil.copy(HF_DB_PATH, dest)
    return str(dest)


def test_batch_writes_one_row_per_ticker_with_correct_status(hf_db_copy):
    hf_db = HistoricFundamentalsDB(hf_db_copy)
    try:
        df = compute_dcf_batch(_TICKERS, hf_db.conn)
        hf_db.upsert_dcf_results(df)

        rows = hf_db.conn.execute(
            "SELECT ticker, intrinsic_value_per_share, status, error_message "
            "FROM dcf_results WHERE ticker = ANY(?) ORDER BY ticker",
            [_TICKERS],
        ).fetchall()
    finally:
        hf_db.close()

    assert [r[0] for r in rows] == sorted(_TICKERS)

    by_ticker = {r[0]: r for r in rows}
    for ticker in ("AAPL", "JPM", "WMT"):
        _, intrinsic, status, error_message = by_ticker[ticker]
        assert status == "ok", f"{ticker}: expected status='ok', got {status!r} ({error_message})"
        assert intrinsic is not None and intrinsic > 0, f"{ticker}: expected positive intrinsic value"
        assert error_message is None

    _, brun_intrinsic, brun_status, brun_error = by_ticker["BRUN"]
    assert brun_status == "error"
    assert brun_intrinsic is None
    assert brun_error is not None and "quarterly period" in brun_error


def test_rerun_overwrites_previous_row(hf_db_copy):
    """A ticker that fails on a later run overwrites its earlier 'ok' row (full rebuild, not merge)."""
    hf_db = HistoricFundamentalsDB(hf_db_copy)
    try:
        df_ok = compute_dcf_batch(["AAPL"], hf_db.conn)
        hf_db.upsert_dcf_results(df_ok)
        assert hf_db.conn.execute(
            "SELECT status FROM dcf_results WHERE ticker = 'AAPL'"
        ).fetchone()[0] == "ok"

        # Simulate a failed re-run for the same ticker.
        import pandas as pd
        from datetime import UTC, datetime
        df_error = pd.DataFrame([{
            "ticker": "AAPL", "intrinsic_value_per_share": None, "wacc": None,
            "terminal_growth_rate": None, "enterprise_value": None, "net_debt": None,
            "diluted_shares": None, "status": "error", "error_message": "simulated failure",
            "computed_at": datetime.now(UTC),
        }])
        hf_db.upsert_dcf_results(df_error)

        count, status = hf_db.conn.execute(
            "SELECT COUNT(*), MAX(status) FROM dcf_results WHERE ticker = 'AAPL'"
        ).fetchone()
        assert count == 1, "expected exactly one row per ticker after rebuild, not an accumulated history"
        assert status == "error"
    finally:
        hf_db.close()
