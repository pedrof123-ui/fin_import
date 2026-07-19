"""
Phase 1 DCF Screener tests — dcf_upside filter in api/screener_router.py.

Hits the real historic_fundamentals.duckdb / av_financials.duckdb directly (same
convention as test_valuation_data.py) rather than mocking DuckDB. Assertions are
written as invariants rather than fixed counts, since dcf_results' population grows
over time (Phase 0 seeded a handful of tickers; Phase 3 will backfill the full
universe) — see DCF_SCREENER_PLAN.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.main as main_module  # noqa: E402 — path must be set first
from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH  # noqa: E402


@pytest.fixture
def client(tmp_path):
    # screener_router reads historic_fundamentals.duckdb / av_financials.duckdb directly
    # (real data, same as test_valuation_data.py); only the app's own financial_statements.duckdb
    # connection needs redirecting to avoid lock conflicts with a live dev server.
    main_module.DB_PATH = tmp_path / "test.duckdb"
    with TestClient(main_module.app) as c:
        yield c


def _has_dcf_results() -> bool:
    if not Path(HF_DB_PATH).exists():
        return False
    import duckdb
    conn = duckdb.connect(HF_DB_PATH, read_only=True)
    try:
        n = conn.execute("SELECT COUNT(*) FROM dcf_results WHERE status = 'ok'").fetchone()[0]
        return n > 0
    except duckdb.CatalogException:
        return False
    finally:
        conn.close()


def test_dcf_fields_present_in_unfiltered_results(client):
    if not _has_dcf_results():
        pytest.skip("dcf_results not populated — run scripts/compute_dcf_batch.py first")
    resp = client.post("/screen", json={})
    assert resp.status_code == 200
    body = resp.json()
    by_ticker = {r["ticker"]: r for r in body["results"]}
    assert "AAPL" in by_ticker, "AAPL should have a dcf_results row (seeded in Phase 0)"
    assert by_ticker["AAPL"]["dcf_intrinsic_value"] > 0
    assert isinstance(by_ticker["AAPL"]["dcf_upside"], float)


def test_dcf_upside_filter_only_returns_matching_and_non_null_rows(client):
    if not _has_dcf_results():
        pytest.skip("dcf_results not populated — run scripts/compute_dcf_batch.py first")
    threshold = -0.9
    resp = client.post("/screen", json={"dcf_upside_min": threshold})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] > 0
    for row in body["results"]:
        assert row["dcf_upside"] is not None
        assert row["dcf_upside"] >= threshold


def test_unfiltered_universe_count_matches_pe_stats(client):
    """The LEFT JOIN to dcf_results (ticker is its PRIMARY KEY) must not fan out or drop rows."""
    import duckdb
    conn = duckdb.connect(HF_DB_PATH, read_only=True)
    try:
        expected = conn.execute("SELECT COUNT(DISTINCT ticker) FROM pe_stats").fetchone()[0]
    finally:
        conn.close()

    resp = client.post("/screen", json={})
    assert resp.json()["count"] == expected


def test_dcf_upside_composes_with_existing_filter(client):
    if not _has_dcf_results():
        pytest.skip("dcf_results not populated — run scripts/compute_dcf_batch.py first")
    resp = client.post("/screen", json={"dcf_upside_min": -0.9, "roic_min": 0})
    assert resp.status_code == 200
    for row in resp.json()["results"]:
        assert row["dcf_upside"] >= -0.9
        assert row["current_roic"] >= 0
