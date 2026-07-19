"""
Regression test for the GET /dcf/{ticker} 500 bug: financial_statements.duckdb's
earnings_estimates table was created with a column named "date", but dcf/estimates.py
(shared with historic_fundamentals.duckdb, which already used "fiscal_date") queries
"fiscal_date" — a DuckDB binder error on every call. Fixed at the schema level in
financial_statements_db.py::_create_schema(), with an in-place rename migration for
existing DBs (real data: 3,077 rows / 80 tickers were preserved, not dropped).
"""
from __future__ import annotations

from datetime import datetime

import duckdb

from financial_statements_db import FinancialStatementsDB


def test_fresh_db_creates_fiscal_date_column(tmp_path):
    db = FinancialStatementsDB(str(tmp_path / "fresh.duckdb"))
    try:
        cols = db.conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'earnings_estimates'"
        ).df()["column_name"].tolist()
        assert "fiscal_date" in cols
        assert "date" not in cols
    finally:
        db.close()


def test_legacy_date_column_is_migrated_without_losing_data(tmp_path):
    db_path = tmp_path / "legacy.duckdb"

    # Simulate a DB created before the fix: "date" instead of "fiscal_date".
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE earnings_estimates (
            ticker VARCHAR NOT NULL, date DATE NOT NULL, horizon VARCHAR NOT NULL,
            fetched_at TIMESTAMP NOT NULL, eps_avg DOUBLE,
            PRIMARY KEY (ticker, date, horizon, fetched_at)
        )
    """)
    conn.execute(
        "INSERT INTO earnings_estimates VALUES ('AAPL', '2026-09-30', 'fiscal quarter', ?, 2.0)",
        [datetime(2026, 7, 1)],
    )
    conn.close()

    db = FinancialStatementsDB(str(db_path))
    try:
        cols = db.conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'earnings_estimates'"
        ).df()["column_name"].tolist()
        assert "fiscal_date" in cols
        assert "date" not in cols

        row = db.conn.execute(
            "SELECT ticker, fiscal_date, eps_avg FROM earnings_estimates"
        ).fetchone()
        assert row == ("AAPL", datetime(2026, 9, 30).date(), 2.0)
    finally:
        db.close()


def test_fetch_and_cache_reads_cached_row_without_binder_error(tmp_path):
    """The exact pre-fix failure mode: _get_cached()'s "ORDER BY fiscal_date DESC" query
    500'd against the old "date" column. Seed a fresh-enough cached row directly (no
    network) and confirm the read path succeeds and returns it."""
    from dcf.estimates import fetch_and_cache

    db = FinancialStatementsDB(str(tmp_path / "fresh.duckdb"))
    try:
        db.conn.execute(
            "INSERT INTO earnings_estimates (ticker, fiscal_date, horizon, fetched_at, eps_avg) "
            "VALUES ('AAPL', '2026-09-30', 'fiscal quarter', ?, 2.5)",
            [datetime.now()],
        )
        result = fetch_and_cache("AAPL", db.conn)
        assert len(result) == 1
        assert result[0]["eps_avg"] == 2.5
    finally:
        db.close()
