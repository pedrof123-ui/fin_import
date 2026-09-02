"""
Tests for debt_maturity/db.py's get_tranches read helper (PLAN_DEBT_MATURITY.md Phase 5).
Round-trips against a scratch DuckDB file, same convention as tests/test_wacc.py's mocked
debt_maturity.db checks -- this one exercises the real storage layer instead.
"""

from debt_maturity import db


def test_get_tranches_missing_file_returns_empty(tmp_path):
    assert db.get_tranches("ZZZZ", db_path=tmp_path / "nonexistent.duckdb") == []


def test_get_tranches_missing_ticker_returns_empty(tmp_path):
    db_path = tmp_path / "scratch.duckdb"
    conn = db.open_db(db_path)
    conn.close()
    assert db.get_tranches("ZZZZ", db_path=db_path) == []


def test_get_tranches_round_trips_saved_rows(tmp_path):
    db_path = tmp_path / "scratch.duckdb"
    conn = db.open_db(db_path)
    rows = [
        {"cik": "12345", "fiscal_year": 2025, "filed_date": "2026-03-01", "currency": "USD",
         "coupon_rate": 0.037, "maturity_year": 2026, "amount": 5800.0,
         "source_concept": "debt_instruments", "raw_label": "3.7% notes"},
        {"cik": "12345", "fiscal_year": 2025, "filed_date": "2026-03-01", "currency": "USD",
         "coupon_rate": None, "maturity_year": None, "amount": 34348.0,
         "source_concept": "maturities_ladder", "raw_label": "Thereafter"},
    ]
    db.save_tranches(conn, "ACME", rows)
    conn.close()

    fetched = db.get_tranches("acme", db_path=db_path)  # lowercase ticker -- must uppercase
    assert len(fetched) == 2
    dated = next(r for r in fetched if r["maturity_year"] == 2026)
    assert dated["coupon_rate"] == 0.037
    assert dated["amount"] == 5800.0
    assert dated["raw_label"] == "3.7% notes"
    undated = next(r for r in fetched if r["maturity_year"] is None)
    assert undated["raw_label"] == "Thereafter"


def test_get_tranches_isolated_by_ticker(tmp_path):
    db_path = tmp_path / "scratch.duckdb"
    conn = db.open_db(db_path)
    db.save_tranches(conn, "ACME", [
        {"cik": "1", "fiscal_year": 2025, "filed_date": "2026-01-01", "currency": "USD",
         "coupon_rate": 0.05, "maturity_year": 2030, "amount": 100.0,
         "source_concept": "debt_instruments", "raw_label": "acme note"},
    ])
    db.save_tranches(conn, "OTHER", [
        {"cik": "2", "fiscal_year": 2025, "filed_date": "2026-01-01", "currency": "USD",
         "coupon_rate": 0.06, "maturity_year": 2031, "amount": 200.0,
         "source_concept": "debt_instruments", "raw_label": "other note"},
    ])
    conn.close()

    acme_rows = db.get_tranches("ACME", db_path=db_path)
    assert len(acme_rows) == 1
    assert acme_rows[0]["raw_label"] == "acme note"
