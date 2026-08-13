"""Tests for scripts/build_dispersion_snapshots.py, against a throwaway DuckDB file."""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from historic_fundamentals.db import HistoricFundamentalsDB  # noqa: E402

from build_dispersion_snapshots import MIN_TICKERS_PER_MONTH, _build_month, _month_end  # noqa: E402


def _insert_estimate(db, ticker, fiscal_date, horizon, fetched_at, **kw):
    db.conn.execute("""
        INSERT OR REPLACE INTO earnings_estimates
        (ticker, fiscal_date, horizon, fetched_at, eps_avg, eps_high, eps_low, eps_count,
         eps_avg_30d, eps_rev_up_30d, eps_rev_down_30d, rev_avg, rev_high, rev_low, rev_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        ticker, fiscal_date, horizon, fetched_at,
        kw.get("eps_avg"), kw.get("eps_high"), kw.get("eps_low"), kw.get("eps_count"),
        kw.get("eps_avg_30d"), kw.get("eps_rev_up_30d"), kw.get("eps_rev_down_30d"),
        kw.get("rev_avg"), kw.get("rev_high"), kw.get("rev_low"), kw.get("rev_count"),
    ])


def _future_fy_row(db, ticker, fetched_at, eps_avg=10.0, eps_high=12.0, eps_low=8.0, eps_count=20):
    """A single future-dated 'fiscal year' estimate row, safely far in the future."""
    _insert_estimate(
        db, ticker, date(2099, 12, 31), "fiscal year", fetched_at,
        eps_avg=eps_avg, eps_high=eps_high, eps_low=eps_low, eps_count=eps_count,
    )


def test_two_tickers_three_snapshots_one_month_yields_two_fy1_rows(tmp_path):
    db = HistoricFundamentalsDB(str(tmp_path / "t.duckdb"))
    try:
        early = datetime(2026, 6, 2)
        mid = datetime(2026, 6, 15)
        late = datetime(2026, 6, 28)
        for t in ("AAA", "BBB"):
            _future_fy_row(db, t, early, eps_avg=9.0)
            _future_fy_row(db, t, mid, eps_avg=9.5)
            _future_fy_row(db, t, late, eps_avg=10.0)

        n = _build_month(db, 2026, 6)
        assert n == 0  # below MIN_TICKERS_PER_MONTH, so the caller's built/skipped counter treats it as skipped

        rows = db.conn.execute(
            "SELECT ticker, eps_avg, snapshot_at FROM estimates_dispersion "
            "WHERE horizon_slot = 'FY1' ORDER BY ticker"
        ).fetchall()
        # Below the ticker-count floor, so nothing should have been written at all.
        assert rows == []
    finally:
        db.close()


def test_month_above_floor_writes_rows_sourced_from_latest_fetch(tmp_path):
    db = HistoricFundamentalsDB(str(tmp_path / "t.duckdb"))
    try:
        early = datetime(2026, 6, 2)
        late = datetime(2026, 6, 28)
        tickers = [f"T{i:04d}" for i in range(MIN_TICKERS_PER_MONTH)]
        for t in tickers:
            _future_fy_row(db, t, early, eps_avg=9.0)
            _future_fy_row(db, t, late, eps_avg=10.0)

        n = _build_month(db, 2026, 6)
        assert n == MIN_TICKERS_PER_MONTH

        rows = db.conn.execute(
            "SELECT ticker, eps_avg, snapshot_at FROM estimates_dispersion WHERE horizon_slot = 'FY1'"
        ).fetchall()
        assert len(rows) == MIN_TICKERS_PER_MONTH
        for _, eps_avg, snapshot_at in rows:
            assert eps_avg == 10.0  # sourced from the LATE snapshot, not the early one
            assert snapshot_at == late

        # month_end_date is the last calendar day of June.
        month_ends = db.conn.execute(
            "SELECT DISTINCT month_end_date FROM estimates_dispersion"
        ).fetchall()
        assert month_ends == [(_month_end(2026, 6),)]
    finally:
        db.close()


def test_rebuild_is_idempotent(tmp_path):
    db = HistoricFundamentalsDB(str(tmp_path / "t.duckdb"))
    try:
        tickers = [f"T{i:04d}" for i in range(MIN_TICKERS_PER_MONTH)]
        for t in tickers:
            _future_fy_row(db, t, datetime(2026, 6, 28), eps_avg=10.0)

        _build_month(db, 2026, 6)
        first = db.conn.execute(
            "SELECT * FROM estimates_dispersion ORDER BY ticker, horizon_slot"
        ).df()

        _build_month(db, 2026, 6)
        second = db.conn.execute(
            "SELECT * FROM estimates_dispersion ORDER BY ticker, horizon_slot"
        ).df()

        # NaN columns (e.g. eps_avg_30d, unset in this fixture) compare unequal with ==,
        # so use pandas' NaN-aware frame comparison rather than raw tuple equality.
        pd.testing.assert_frame_equal(first, second)
    finally:
        db.close()


def test_ticker_with_no_future_fiscal_date_produces_no_row(tmp_path):
    db = HistoricFundamentalsDB(str(tmp_path / "t.duckdb"))
    try:
        tickers = [f"T{i:04d}" for i in range(MIN_TICKERS_PER_MONTH)]
        for t in tickers[:-1]:
            _future_fy_row(db, t, datetime(2026, 6, 28))
        # Last ticker has only a PAST fiscal_date — should be silently skipped, not error.
        _insert_estimate(
            db, tickers[-1], date(2020, 1, 1), "fiscal year", datetime(2026, 6, 28),
            eps_avg=5.0, eps_high=6.0, eps_low=4.0, eps_count=10,
        )

        n = _build_month(db, 2026, 6)
        assert n == MIN_TICKERS_PER_MONTH  # still counted in the snapshot's ticker_count

        rows = db.conn.execute(
            "SELECT ticker FROM estimates_dispersion WHERE horizon_slot = 'FY1'"
        ).fetchall()
        assert len(rows) == MIN_TICKERS_PER_MONTH - 1
        assert (tickers[-1],) not in rows
    finally:
        db.close()


def test_small_month_is_skipped_entirely(tmp_path):
    db = HistoricFundamentalsDB(str(tmp_path / "t.duckdb"))
    try:
        for t in ("AAA", "BBB", "CCC"):  # far below MIN_TICKERS_PER_MONTH
            _future_fy_row(db, t, datetime(2026, 5, 10))

        n = _build_month(db, 2026, 5)
        assert n == 0

        count = db.conn.execute("SELECT COUNT(*) FROM estimates_dispersion").fetchone()[0]
        assert count == 0
    finally:
        db.close()


def test_month_with_no_data_returns_zero(tmp_path):
    db = HistoricFundamentalsDB(str(tmp_path / "t.duckdb"))
    try:
        n = _build_month(db, 2026, 1)
        assert n == 0
    finally:
        db.close()


def test_per_ticker_distinct_fetched_at_matches_real_estimates_update_behavior(tmp_path):
    """Regression test for a real bug: estimates_update.py stamps fetched_at = now() once
    PER TICKER as it's processed, not once per run — a ~37-minute run across ~2,650 tickers
    produces ~2,650 distinct fetched_at values, not one shared batch timestamp. The builder
    must use each ticker's own latest fetched_at within the month, not a single
    MAX(fetched_at) that (in production) only ever matches the very last ticker processed."""
    db = HistoricFundamentalsDB(str(tmp_path / "t.duckdb"))
    try:
        tickers = [f"T{i:04d}" for i in range(MIN_TICKERS_PER_MONTH)]
        base = datetime(2026, 6, 2, 9, 34, 0)
        for i, t in enumerate(tickers):
            # Each ticker fetched one second apart, like the real rate-limited run.
            _future_fy_row(db, t, base + pd.Timedelta(seconds=i), eps_avg=10.0)

        n = _build_month(db, 2026, 6)
        assert n == MIN_TICKERS_PER_MONTH  # must NOT collapse to 1 (the old MAX(fetched_at) bug)

        rows = db.conn.execute(
            "SELECT ticker FROM estimates_dispersion WHERE horizon_slot = 'FY1'"
        ).fetchall()
        assert len(rows) == MIN_TICKERS_PER_MONTH
    finally:
        db.close()
