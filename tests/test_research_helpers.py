"""
AI Researcher — deterministic helper tests (no LLM calls).

Covers the P/S valuation cross-check helpers in api/research_router.py:
  - _forward_revenue_estimate must use the same next-12-month horizon as forward_12m_eps
    (sum of next 4 quarterly consensus estimates, not the nearest fiscal-year estimate).
  - _latest_diluted_shares must prefer the dedicated shares_outstanding table over the
    coarser annual balance-sheet figure.
"""
from __future__ import annotations

from datetime import date, datetime

import duckdb
import pytest

_TEST_TICKERS = ["NVDA", "UPS", "KO"]


def test_forward_revenue_estimate_sums_next_four_quarters(tmp_path, monkeypatch):
    """A ticker with 4 quarterly estimates and a differing annual estimate must use the
    quarterly sum (true NTM revenue) — not silently jump to the nearest fiscal-year figure."""
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE earnings_estimates (
            ticker VARCHAR, fiscal_date DATE, horizon VARCHAR, fetched_at TIMESTAMP,
            rev_avg DOUBLE
        )
    """)
    fetched = datetime(2026, 7, 1)
    quarterly = [
        (date(2026, 9, 30), 100.0),
        (date(2026, 12, 31), 110.0),
        (date(2027, 3, 31), 120.0),
        (date(2027, 6, 30), 130.0),
    ]
    for fiscal_date, rev in quarterly:
        conn.execute(
            "INSERT INTO earnings_estimates VALUES ('FAKE', ?, 'fiscal quarter', ?, ?)",
            [fiscal_date, fetched, rev],
        )
    # Deliberately different annual estimate — must NOT be what gets returned.
    conn.execute(
        "INSERT INTO earnings_estimates VALUES ('FAKE', ?, 'fiscal year', ?, ?)",
        [date(2027, 9, 30), fetched, 999.0],
    )
    conn.close()

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    result = rr._forward_revenue_estimate("FAKE")

    assert result == pytest.approx(sum(r for _, r in quarterly))
    assert result != 999.0


def test_forward_revenue_estimate_falls_back_to_annual(tmp_path, monkeypatch):
    """With fewer than 4 quarterly estimates, fall back to the next fiscal-year estimate."""
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE earnings_estimates (
            ticker VARCHAR, fiscal_date DATE, horizon VARCHAR, fetched_at TIMESTAMP,
            rev_avg DOUBLE
        )
    """)
    conn.execute(
        "INSERT INTO earnings_estimates VALUES ('FAKE', ?, 'fiscal year', ?, ?)",
        [date(2027, 9, 30), datetime(2026, 7, 1), 500.0],
    )
    conn.close()

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    assert rr._forward_revenue_estimate("FAKE") == 500.0


def test_forward_revenue_estimate_missing_db(tmp_path, monkeypatch):
    import api.research_router as rr

    monkeypatch.setattr(rr, "_HIST_FUND_DB", tmp_path / "does_not_exist.duckdb")
    assert rr._forward_revenue_estimate("FAKE") is None


@pytest.mark.parametrize("ticker", _TEST_TICKERS)
def test_latest_diluted_shares_prefers_shares_outstanding_table(ticker):
    """Where the dedicated shares_outstanding table has data for the ticker, it must be the
    source used (not silently skipped in favor of the coarser annual balance-sheet figure)."""
    import api.research_router as rr

    if not rr._AV_FIN_DB.exists():
        pytest.skip("av_financials.duckdb not present in this environment")

    conn = duckdb.connect(str(rr._AV_FIN_DB), read_only=True)
    dedicated = conn.execute(
        "SELECT shares_outstanding_diluted FROM shares_outstanding "
        "WHERE ticker = ? AND shares_outstanding_diluted IS NOT NULL "
        "ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    conn.close()

    result = rr._latest_diluted_shares(ticker)
    if dedicated:
        assert result == pytest.approx(dedicated[0])
    else:
        assert result is None or result > 0


# ---------------------------------------------------------------------------
# get_estimates_summary — dispersion/staleness line (PLAN_DISPERSION.md Phase 5)
# ---------------------------------------------------------------------------

def _make_estimates_db(db_path):
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE earnings_estimates (
            ticker VARCHAR, fiscal_date DATE, horizon VARCHAR, fetched_at TIMESTAMP,
            eps_avg DOUBLE, eps_high DOUBLE, eps_low DOUBLE, eps_count INTEGER,
            eps_avg_7d DOUBLE, eps_avg_30d DOUBLE,
            eps_rev_up_7d INTEGER, eps_rev_down_7d INTEGER,
            eps_rev_up_30d INTEGER, eps_rev_down_30d INTEGER,
            rev_avg DOUBLE
        )
    """)
    conn.execute("""
        CREATE TABLE estimates_dispersion (
            ticker VARCHAR, month_end_date DATE, horizon_slot VARCHAR, fiscal_date DATE,
            snapshot_at TIMESTAMP, eps_avg DOUBLE, eps_high DOUBLE, eps_low DOUBLE,
            eps_count INTEGER
        )
    """)
    conn.close()


def test_get_estimates_summary_no_data_returns_info_string(tmp_path, monkeypatch):
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    _make_estimates_db(db_path)
    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)

    result = rr.get_estimates_summary("NODATA")
    assert result == "[INFO] No analyst estimates found for NODATA"


def test_get_estimates_summary_includes_spread_and_revisions(tmp_path, monkeypatch):
    """With a future FY1 estimate and a >=50-row dispersion population, the summary must
    carry a Spread column, a percentile clause, and a net-revisions figure."""
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    _make_estimates_db(db_path)
    conn = duckdb.connect(str(db_path))

    fetched = datetime(2026, 7, 1)
    fy1_date = date(2027, 1, 31)
    conn.execute(
        "INSERT INTO earnings_estimates VALUES "
        "('FAKE', ?, 'fiscal year', ?, 12.7644, 16.00, 9.65, 50, NULL, 12.50, NULL, NULL, 3, 7, NULL)",
        [fy1_date, fetched],
    )
    month_end = date(2026, 7, 31)
    for i in range(60):
        eps_avg = 10.0
        half = (0.1 + i * 0.005) / 2
        conn.execute(
            "INSERT INTO estimates_dispersion VALUES (?, ?, 'FY1', ?, ?, ?, ?, ?, ?)",
            [f"POP{i:03d}", month_end, fy1_date, fetched, eps_avg, eps_avg + half, eps_avg - half, 10],
        )
    conn.close()

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    result = rr.get_estimates_summary("FAKE")

    assert "Spread" in result
    assert "FY1 dispersion:" in result
    assert "percentile of covered universe" in result
    assert "net revisions -4 over 30d" in result  # 3 up - 7 down
    assert "50 analysts" in result


def test_get_estimates_summary_missing_dispersion_table_degrades_gracefully(tmp_path, monkeypatch):
    """estimates_dispersion missing entirely must not break the revisions table — only the
    percentile clause (and its dependents) drop out."""
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE earnings_estimates (
            ticker VARCHAR, fiscal_date DATE, horizon VARCHAR, fetched_at TIMESTAMP,
            eps_avg DOUBLE, eps_high DOUBLE, eps_low DOUBLE, eps_count INTEGER,
            eps_avg_7d DOUBLE, eps_avg_30d DOUBLE,
            eps_rev_up_7d INTEGER, eps_rev_down_7d INTEGER,
            eps_rev_up_30d INTEGER, eps_rev_down_30d INTEGER,
            rev_avg DOUBLE
        )
    """)
    # Deliberately no estimates_dispersion table at all.
    conn.execute(
        "INSERT INTO earnings_estimates VALUES "
        "('FAKE', ?, 'fiscal year', ?, 10.0, 12.0, 8.0, 20, NULL, NULL, NULL, NULL, NULL, NULL, NULL)",
        [date(2027, 1, 31), datetime(2026, 7, 1)],
    )
    conn.close()

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    result = rr.get_estimates_summary("FAKE")

    assert "[ERROR]" not in result
    assert "Spread" in result  # per-row spread still computed from earnings_estimates directly
    assert "percentile of covered universe" not in result  # no population to rank against


def test_get_estimates_summary_live_nvda_smoke():
    """Loose smoke test against the real DB, if present — just checks the function doesn't
    error and produces a well-formed table for a real, heavily-covered ticker."""
    import api.research_router as rr

    if not rr._HIST_FUND_DB.exists():
        pytest.skip("historic_fundamentals.duckdb not present in this environment")

    result = rr.get_estimates_summary("NVDA")
    assert "[ERROR]" not in result
    if "No analyst estimates found" not in result:
        assert "Spread" in result
