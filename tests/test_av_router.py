"""
Tests for the /quote/{ticker} endpoint in api/av_router.py — specifically the DuckDB
connection-leak fix in the latest-close fallback path (used when no live AV quote is
available, e.g. ALPHA_VANTAGE_API_KEY is unset).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.main as main_module  # noqa: E402
import api.av_router as av_router_module  # noqa: E402


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
