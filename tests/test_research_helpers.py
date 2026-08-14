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


# ---------------------------------------------------------------------------
# _ml_comps_row — ML comps triangulation row (PLAN_ML_COMPS_TRIANGULATION.md Phase 1)
# ---------------------------------------------------------------------------

_ML_COMPS_COLUMNS = """
    ticker VARCHAR, status VARCHAR,
    ml_fair_price_low DOUBLE, ml_fair_price_mid DOUBLE, ml_fair_price_high DOUBLE,
    ml_fair_price_basis VARCHAR,
    ml_fair_pe_low DOUBLE, ml_fair_pe_mid DOUBLE, ml_fair_pe_high DOUBLE,
    ml_fair_pfcf_low DOUBLE, ml_fair_pfcf_mid DOUBLE, ml_fair_pfcf_high DOUBLE,
    ml_fair_ps_low DOUBLE, ml_fair_ps_mid DOUBLE, ml_fair_ps_high DOUBLE
"""


def _make_ml_comps_db(db_path):
    conn = duckdb.connect(str(db_path))
    conn.execute(f"CREATE TABLE ml_comps_valuation ({_ML_COMPS_COLUMNS})")
    conn.close()


def _insert_ml_comps_row_direct(db_path, ticker, status, **kw):
    """Inserts one ml_comps_valuation row, defaulting every column not passed to NULL. Keeps
    each test's INSERT focused on the fields it's exercising instead of repeating all 15
    columns positionally."""
    defaults = {
        "ml_fair_price_low": None, "ml_fair_price_mid": None, "ml_fair_price_high": None,
        "ml_fair_price_basis": None,
        "ml_fair_pe_low": None, "ml_fair_pe_mid": None, "ml_fair_pe_high": None,
        "ml_fair_pfcf_low": None, "ml_fair_pfcf_mid": None, "ml_fair_pfcf_high": None,
        "ml_fair_ps_low": None, "ml_fair_ps_mid": None, "ml_fair_ps_high": None,
    }
    defaults.update(kw)
    cols = ["ticker", "status"] + list(defaults.keys())
    values = [ticker, status] + [defaults[c] for c in list(defaults.keys())]
    conn = duckdb.connect(str(db_path))
    conn.execute(
        f"INSERT INTO ml_comps_valuation ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        values,
    )
    conn.close()


def test_ml_comps_row_present_and_formatted(tmp_path, monkeypatch):
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    _make_ml_comps_db(db_path)
    _insert_ml_comps_row_direct(
        db_path, "AAPL", "ok",
        ml_fair_price_low=202.07, ml_fair_price_mid=279.63, ml_fair_price_high=400.62,
        ml_fair_price_basis="median(pe,pfcf,ps)",
        ml_fair_pe_low=24.35, ml_fair_pe_mid=33.69, ml_fair_pe_high=55.70,
        ml_fair_pfcf_low=24.11, ml_fair_pfcf_mid=33.09, ml_fair_pfcf_high=45.80,
        ml_fair_ps_low=2.88, ml_fair_ps_mid=6.04, ml_fair_ps_high=9.13,
    )

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    row = rr._ml_comps_row("AAPL")

    assert row == ["ML Comps (peer-relative)", "$202.07", "$279.63", "$400.62"]


def test_ml_comps_row_omitted_when_status_not_ok(tmp_path, monkeypatch):
    """status='insufficient_peers' (e.g. BBBY — zero sector, zero peers by construction) must
    omit the row entirely, not render an "n/a" placeholder."""
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    _make_ml_comps_db(db_path)
    _insert_ml_comps_row_direct(db_path, "BBBY", "insufficient_peers")

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    assert rr._ml_comps_row("BBBY") is None


def test_ml_comps_row_omitted_when_capped(tmp_path, monkeypatch):
    """Phase 0.2 finding (ACHR): a predicted multiple hitting the scoring script's 500x sanity
    cap collapses into a near-worthless dollar figure — not a usable absolute anchor."""
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    _make_ml_comps_db(db_path)
    _insert_ml_comps_row_direct(
        db_path, "ACHR", "ok",
        ml_fair_price_low=0.0048, ml_fair_price_mid=0.3352, ml_fair_price_high=1.2388,
        ml_fair_price_basis="median(ps)",
        ml_fair_ps_low=1.95, ml_fair_ps_mid=135.30, ml_fair_ps_high=499.999999,
    )

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    assert rr._ml_comps_row("ACHR") is None


def test_ml_comps_row_omitted_when_near_cap_not_exactly_capped(tmp_path, monkeypatch):
    """Real finding (CE, 2026-08-14): a predicted multiple doesn't need to hit the exact 500x
    cap to be just as unreliable. ml_fair_pfcf_high=485.09 (97% of the cap, not the cap itself)
    produced ml_fair_price_high=$2830.92 for a stock trading at $44.72 — the exact-equality
    guardrail let it through. Any multiple within 10% of the cap must now be treated the same
    as a literal cap hit."""
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    _make_ml_comps_db(db_path)
    _insert_ml_comps_row_direct(
        db_path, "CE", "ok",
        ml_fair_price_low=51.284759, ml_fair_price_mid=137.221706, ml_fair_price_high=2830.916511,
        ml_fair_price_basis="median(pfcf,ps)",
        ml_fair_pfcf_low=6.368186, ml_fair_pfcf_mid=21.125898, ml_fair_pfcf_high=485.089458,
        ml_fair_ps_low=0.599598, ml_fair_ps_mid=1.226321, ml_fair_ps_high=20.743056,
    )

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    assert rr._ml_comps_row("CE") is None


def test_ml_comps_row_not_capped_below_near_cap_threshold(tmp_path, monkeypatch):
    """A predicted multiple comfortably below the near-cap threshold (90% of 500 = 450) must
    still render normally — the widened guardrail shouldn't suppress genuinely high-but-plausible
    multiples."""
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    _make_ml_comps_db(db_path)
    _insert_ml_comps_row_direct(
        db_path, "HYPERGROWTH", "ok",
        ml_fair_price_low=50.0, ml_fair_price_mid=80.0, ml_fair_price_high=120.0,
        ml_fair_price_basis="median(ps)",
        ml_fair_ps_low=20.0, ml_fair_ps_mid=35.0, ml_fair_ps_high=60.0,  # well under 450
    )

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    row = rr._ml_comps_row("HYPERGROWTH")

    assert row == ["ML Comps (peer-relative)", "$50.00", "$80.00", "$120.00"]


def test_ml_comps_row_only_checks_contributing_multiples(tmp_path, monkeypatch):
    """A capped multiple that did NOT contribute to ml_fair_price_basis (e.g. P/E capped for a
    company with no valid EPS basis, so only P/S was used) must not suppress a good row."""
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    _make_ml_comps_db(db_path)
    _insert_ml_comps_row_direct(
        db_path, "FAKE", "ok",
        ml_fair_price_low=10.0, ml_fair_price_mid=15.0, ml_fair_price_high=20.0,
        ml_fair_price_basis="median(ps)",
        ml_fair_pe_high=499.999999,  # capped but not in the basis — must not suppress the row
        ml_fair_ps_low=8.5, ml_fair_ps_mid=9.0, ml_fair_ps_high=9.5,
    )

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    row = rr._ml_comps_row("FAKE")

    assert row == ["ML Comps (peer-relative)", "$10.00", "$15.00", "$20.00"]


def test_ml_comps_row_missing_ticker(tmp_path, monkeypatch):
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    _make_ml_comps_db(db_path)

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    assert rr._ml_comps_row("NODATA") is None


def test_ml_comps_row_missing_db(tmp_path, monkeypatch):
    import api.research_router as rr

    monkeypatch.setattr(rr, "_HIST_FUND_DB", tmp_path / "does_not_exist.duckdb")
    assert rr._ml_comps_row("AAPL") is None


# ---------------------------------------------------------------------------
# _format_ml_comps_summary — Valuation Analyst context (PLAN_ML_COMPS_TRIANGULATION.md Phase 2)
# ---------------------------------------------------------------------------

def test_format_ml_comps_summary_unavailable(tmp_path, monkeypatch):
    import api.research_router as rr

    monkeypatch.setattr(rr, "_HIST_FUND_DB", tmp_path / "does_not_exist.duckdb")
    result = rr._format_ml_comps_summary("AAPL")

    assert result.startswith("[INFO]")
    assert "unavailable" in result.lower()


def test_format_ml_comps_summary_present(tmp_path, monkeypatch):
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    _make_ml_comps_db(db_path)
    _insert_ml_comps_row_direct(
        db_path, "AAPL", "ok",
        ml_fair_price_low=202.07, ml_fair_price_mid=279.63, ml_fair_price_high=400.62,
        ml_fair_price_basis="median(pe,pfcf,ps)",
        ml_fair_pe_low=24.35, ml_fair_pe_mid=33.69, ml_fair_pe_high=55.70,
        ml_fair_pfcf_low=24.11, ml_fair_pfcf_mid=33.09, ml_fair_pfcf_high=45.80,
        ml_fair_ps_low=2.88, ml_fair_ps_mid=6.04, ml_fair_ps_high=9.13,
    )

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    result = rr._format_ml_comps_summary("AAPL")

    assert "ML COMPS-BASED FAIR VALUE" in result
    assert "$279.63" in result
    assert "CAPPED" not in result


def test_format_ml_comps_summary_flags_capped_prediction(tmp_path, monkeypatch):
    """Unlike the display row, a capped prediction is surfaced (not hidden) here — with an
    explicit low-confidence flag so the analyst can still use it as directional evidence."""
    import api.research_router as rr

    db_path = tmp_path / "historic_fundamentals.duckdb"
    _make_ml_comps_db(db_path)
    _insert_ml_comps_row_direct(
        db_path, "ACHR", "ok",
        ml_fair_price_low=0.0048, ml_fair_price_mid=0.3352, ml_fair_price_high=1.2388,
        ml_fair_price_basis="median(ps)",
        ml_fair_ps_low=1.95, ml_fair_ps_mid=135.30, ml_fair_ps_high=499.999999,
    )

    monkeypatch.setattr(rr, "_HIST_FUND_DB", db_path)
    result = rr._format_ml_comps_summary("ACHR")

    assert "CAPPED" in result
    assert "$0.34" in result  # p50 fair price still stated, alongside the low-confidence flag
