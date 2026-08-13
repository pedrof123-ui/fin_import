"""
Tests for api/av_router.py:
- /quote/{ticker} — the DuckDB connection-leak fix in the latest-close fallback path
  (used when no live AV quote is available, e.g. ALPHA_VANTAGE_API_KEY is unset).
- /av-fundamentals/{ticker} — the dispersion/staleness fields added in PLAN_DISPERSION.md
  Phase 3 (eps_dispersion, eps_dispersion_pctile, coverage, net_revisions_30d,
  eps_drift_30d, dispersion_fiscal_date, dispersion_as_of).
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import duckdb
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.main as main_module  # noqa: E402
import api.av_router as av_router_module  # noqa: E402
from historic_fundamentals.db import HistoricFundamentalsDB  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    main_module.DB_PATH = tmp_path / "test.duckdb"
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    with TestClient(main_module.app) as c:
        yield c


def test_quote_missing_prices_db_returns_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr(av_router_module, "_PRICES_DB", tmp_path / "does_not_exist.duckdb")
    resp = client.get("/quote/AAPL")
    assert resp.status_code == 404


def test_quote_fallback_closes_connection_on_query_error(client, monkeypatch):
    """If the fallback query raises, the connection must still be closed — not leaked."""
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.execute.side_effect = RuntimeError("boom")
    monkeypatch.setattr(av_router_module.duckdb, "connect", lambda *a, **k: mock_conn)

    resp = client.get("/quote/AAPL")

    assert resp.status_code == 404
    mock_conn.__exit__.assert_called_once()


def test_quote_fallback_closes_connection_on_success(client, monkeypatch):
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = (123.45, "2026-07-16")
    monkeypatch.setattr(av_router_module.duckdb, "connect", lambda *a, **k: mock_conn)

    resp = client.get("/quote/AAPL")

    assert resp.status_code == 200
    body = resp.json()
    assert body["price"] == 123.45
    assert body["is_live"] is False
    mock_conn.__exit__.assert_called_once()


# ---------------------------------------------------------------------------
# /av-fundamentals/{ticker} — dispersion fields (PLAN_DISPERSION.md Phase 3)
#
# Each _seed_* helper opens its own HistoricFundamentalsDB, writes, and closes — mirroring
# how the real writers (estimates_update.py, build_dispersion_snapshots.py) behave, and
# avoiding a DuckDB "same file, different configuration" conflict with the endpoint's own
# read_only connection if a write connection were left open across the client.get() call.
# ---------------------------------------------------------------------------

def _seed_pe_stats(hf_path: Path, ticker: str) -> None:
    db = HistoricFundamentalsDB(str(hf_path))
    try:
        db.upsert_pe_stats({
            "ticker": ticker,
            "current_price": 100.0,
            "updated_at": datetime.now(),
        })
    finally:
        db.close()


def _seed_future_fy1(
    hf_path: Path, ticker: str, fetched_at: datetime, *,
    eps_avg=None, eps_high=None, eps_low=None, eps_count=None,
    eps_avg_30d=None, eps_rev_up_30d=None, eps_rev_down_30d=None,
) -> None:
    """Insert a single future-dated 'fiscal year' earnings_estimates row for `ticker`."""
    fiscal_date = date.today() + timedelta(days=400)
    db = HistoricFundamentalsDB(str(hf_path))
    try:
        db.upsert_estimates(ticker, [{
            "fiscal_date": fiscal_date,
            "horizon": "fiscal year",
            "fetched_at": fetched_at,
            "eps_avg": eps_avg, "eps_high": eps_high, "eps_low": eps_low, "eps_count": eps_count,
            "eps_avg_30d": eps_avg_30d,
            "eps_rev_up_30d": eps_rev_up_30d, "eps_rev_down_30d": eps_rev_down_30d,
        }])
    finally:
        db.close()


def _seed_dispersion_population(hf_path: Path, rows: list[dict]) -> None:
    db = HistoricFundamentalsDB(str(hf_path))
    try:
        db.upsert_dispersion_snapshots(rows)
    finally:
        db.close()


def _drop_dispersion_table(hf_path: Path) -> None:
    db = HistoricFundamentalsDB(str(hf_path))
    try:
        db.conn.execute("DROP TABLE estimates_dispersion")
    finally:
        db.close()


def _make_av_db(tmp_path: Path, name: str = "av.duckdb") -> Path:
    """Minimal company_overview table — empty is fine, the query just needs it to exist."""
    path = tmp_path / name
    conn = duckdb.connect(str(path))
    conn.execute("""
        CREATE TABLE company_overview (
            ticker VARCHAR, name VARCHAR, sector VARCHAR, industry VARCHAR,
            market_cap DOUBLE, analyst_target_price DOUBLE,
            analyst_rating_strong_buy DOUBLE, analyst_rating_buy DOUBLE,
            analyst_rating_hold DOUBLE, analyst_rating_sell DOUBLE,
            analyst_rating_strong_sell DOUBLE, fetch_date DATE
        )
    """)
    conn.close()
    return path


@pytest.fixture
def dispersion_dbs(client, tmp_path, monkeypatch):
    """Wires fresh (empty) hf/av DB paths into api.av_router for a single test.

    Creates the hf DB up front (so its schema — including estimates_dispersion —
    exists) then closes it immediately; tests seed data via the _seed_* helpers above,
    each of which opens and closes its own connection.
    """
    hf_path = tmp_path / "hf.duckdb"
    HistoricFundamentalsDB(str(hf_path)).close()
    av_path = _make_av_db(tmp_path)
    monkeypatch.setattr(av_router_module, "_HF_DB", hf_path)
    monkeypatch.setattr(av_router_module, "_AV_DB", av_path)
    return hf_path


def test_av_fundamentals_no_estimates_returns_null_dispersion_fields(client, dispersion_dbs):
    _seed_pe_stats(dispersion_dbs, "NOEST")

    resp = client.get("/av-fundamentals/NOEST")
    assert resp.status_code == 200
    body = resp.json()
    assert body["eps_dispersion"] is None
    assert body["eps_dispersion_pctile"] is None
    assert body["coverage"] is None
    assert body["net_revisions_30d"] is None
    assert body["eps_drift_30d"] is None
    assert body["dispersion_fiscal_date"] is None
    assert body["dispersion_as_of"] is None


def test_av_fundamentals_eps_floor_trips_dispersion_null_but_coverage_present(client, dispersion_dbs):
    _seed_pe_stats(dispersion_dbs, "THIN")
    _seed_future_fy1(
        dispersion_dbs, "THIN", datetime(2026, 7, 1),
        eps_avg=0.05, eps_high=0.20, eps_low=-0.10, eps_count=12,
    )

    resp = client.get("/av-fundamentals/THIN")
    assert resp.status_code == 200
    body = resp.json()
    assert body["eps_dispersion"] is None
    assert body["coverage"] == 12


def test_av_fundamentals_returns_dispersion_fields_when_available(client, dispersion_dbs):
    _seed_pe_stats(dispersion_dbs, "NVDA")
    fetched_at = datetime(2026, 7, 1, 13, 52, 29)
    _seed_future_fy1(
        dispersion_dbs, "NVDA", fetched_at,
        eps_avg=12.7644, eps_high=16.00, eps_low=9.65, eps_count=50,
        eps_avg_30d=12.50, eps_rev_up_30d=3, eps_rev_down_30d=7,
    )

    resp = client.get("/av-fundamentals/NVDA")
    assert resp.status_code == 200
    body = resp.json()
    assert body["eps_dispersion"] == pytest.approx((16.00 - 9.65) / 12.7644, abs=1e-4)
    assert body["coverage"] == 50
    assert body["net_revisions_30d"] == 3 - 7
    assert body["eps_drift_30d"] == pytest.approx((12.7644 - 12.50) / 12.50, abs=1e-4)
    assert body["dispersion_fiscal_date"] == str(date.today() + timedelta(days=400))
    assert body["dispersion_as_of"] == "2026-07-01"
    # No estimates_dispersion population seeded — percentile stays null (< 50-entry minimum).
    assert body["eps_dispersion_pctile"] is None


def test_av_fundamentals_percentile_computed_with_sufficient_population(client, dispersion_dbs):
    _seed_pe_stats(dispersion_dbs, "WIDE")
    _seed_future_fy1(
        dispersion_dbs, "WIDE", datetime(2026, 7, 1),
        eps_avg=10.0, eps_high=20.0, eps_low=0.5, eps_count=20,  # dispersion ~1.95, high end
    )

    # 60-row population, dispersion ranging ~0.06 to ~0.65, all eligible (eps_count >= 5).
    rows = []
    month_end = date(2026, 7, 31)
    for i in range(60):
        eps_avg = 10.0
        half_spread = (0.5 + i * 0.01) / 2
        rows.append({
            "ticker": f"POP{i:03d}", "month_end_date": month_end, "horizon_slot": "FY1",
            "fiscal_date": date.today() + timedelta(days=400),
            "snapshot_at": datetime(2026, 7, 28),
            "eps_avg": eps_avg, "eps_high": eps_avg + half_spread, "eps_low": eps_avg - half_spread,
            "eps_count": 10,
        })
    _seed_dispersion_population(dispersion_dbs, rows)

    resp = client.get("/av-fundamentals/WIDE")
    assert resp.status_code == 200
    body = resp.json()
    assert body["eps_dispersion"] is not None
    assert body["eps_dispersion_pctile"] == pytest.approx(1.0)  # WIDE's ~1.95 exceeds the whole population


def test_av_fundamentals_missing_dispersion_table_degrades_gracefully(client, dispersion_dbs):
    _seed_pe_stats(dispersion_dbs, "NOTBL")
    _seed_future_fy1(
        dispersion_dbs, "NOTBL", datetime(2026, 7, 1),
        eps_avg=10.0, eps_high=12.0, eps_low=8.0, eps_count=20,
    )
    _drop_dispersion_table(dispersion_dbs)

    resp = client.get("/av-fundamentals/NOTBL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["eps_dispersion"] is not None  # unaffected — computed off earnings_estimates directly
    assert body["eps_dispersion_pctile"] is None
