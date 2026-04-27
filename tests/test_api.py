"""
API tests for the financial statements web app.

Fast tests (no network):
    uv run pytest tests/test_api.py -m "not integration"

Integration tests (hit SEC EDGAR, slow ~10-30s each):
    uv run pytest tests/test_api.py -m integration

All tests:
    uv run pytest tests/test_api.py
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.main as main_module  # noqa: E402 — path must be set first


@pytest.fixture
def client(tmp_path):
    main_module.DB_PATH = tmp_path / "test.duckdb"
    with TestClient(main_module.app) as c:
        yield c


# ---------------------------------------------------------------------------
# Fast tests — no network required
# ---------------------------------------------------------------------------


def test_list_tickers_empty(client):
    resp = client.get("/tickers")
    assert resp.status_code == 200
    assert resp.json() == []


def test_statements_returns_404_when_no_data(client):
    assert client.get("/statements/AAPL/income").status_code == 404
    assert client.get("/statements/AAPL/balance").status_code == 404
    assert client.get("/statements/AAPL/cashflow").status_code == 404


def test_statements_invalid_type_returns_422(client):
    assert client.get("/statements/AAPL/invalid").status_code == 422


def test_import_requires_ticker(client):
    resp = client.post("/import", json={"periods": 5})
    assert resp.status_code == 422


def test_import_invalid_period_type_returns_422(client):
    resp = client.post("/import", json={"ticker": "AAPL", "period_type": "MONTHLY"})
    assert resp.status_code == 422


def test_import_unknown_ticker_returns_404(client):
    resp = client.post("/import", json={"ticker": "XXXXXXXXXXXXXXX", "periods": 1, "period_type": "FY"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Integration tests — require network + ~10-30s each
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_import_annual_all_statements(client):
    """Import 1 annual 10-K for AAPL; verify all 3 statements land in DB."""
    resp = client.post("/import", json={"ticker": "AAPL", "periods": 1, "period_type": "FY"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ticker"] == "AAPL"
    assert body["filings_processed"] == 1
    assert body["filings_failed"] == 0
    assert body["errors"] == []

    for stmt in ("income", "balance", "cashflow"):
        r = client.get(f"/statements/AAPL/{stmt}?period_type=FY&periods=1")
        assert r.status_code == 200, f"{stmt} statement not found after import"
        rows = r.json()
        assert len(rows) == 1, f"expected 1 row for {stmt}, got {len(rows)}"

    assert "AAPL" in client.get("/tickers").json()


@pytest.mark.integration
def test_import_quarterly_all_statements(client):
    """Import 2 quarterly 10-Qs for AAPL; verify all 3 statements per quarter."""
    resp = client.post("/import", json={"ticker": "AAPL", "periods": 2, "period_type": "Q"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["filings_processed"] == 2
    assert body["filings_failed"] == 0

    for stmt in ("income", "balance", "cashflow"):
        r = client.get(f"/statements/AAPL/{stmt}?period_type=Q&periods=2")
        assert r.status_code == 200, f"quarterly {stmt} not found after import"
        rows = r.json()
        assert len(rows) == 2, f"expected 2 rows for quarterly {stmt}, got {len(rows)}"
        for row in rows:
            assert row["period_type"] == "Quarterly"


@pytest.mark.integration
def test_import_skips_existing_filings(client):
    """Re-importing the same period should not double-count."""
    client.post("/import", json={"ticker": "MSFT", "periods": 1, "period_type": "FY"})
    resp = client.post("/import", json={"ticker": "MSFT", "periods": 1, "period_type": "FY"})
    assert resp.status_code == 200
    assert resp.json()["filings_processed"] == 0
