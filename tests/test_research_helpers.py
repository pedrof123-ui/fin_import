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
