"""
Tests for GET /estimates/{ticker} in api/estimates_router.py — specifically the
eps_dispersion / rev_dispersion fields added in PLAN_DISPERSION.md Phase 3.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.main as main_module  # noqa: E402
import api.estimates_router as estimates_router_module  # noqa: E402
from historic_fundamentals.db import HistoricFundamentalsDB  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    main_module.DB_PATH = tmp_path / "test.duckdb"
    with TestClient(main_module.app) as c:
        yield c


@pytest.fixture
def hf_path(tmp_path, monkeypatch):
    path = tmp_path / "hf.duckdb"
    HistoricFundamentalsDB(str(path)).close()
    monkeypatch.setattr(estimates_router_module, "_HF_DB", path)
    return path


def _seed(hf_path: Path, ticker: str, fiscal_date, horizon, fetched_at, **kw) -> None:
    db = HistoricFundamentalsDB(str(hf_path))
    try:
        db.upsert_estimates(ticker, [{
            "fiscal_date": fiscal_date, "horizon": horizon, "fetched_at": fetched_at, **kw,
        }])
    finally:
        db.close()


def test_get_estimates_periods_carry_dispersion_fields(client, hf_path):
    fiscal_date = date.today() + timedelta(days=30)
    _seed(
        hf_path, "NVDA", fiscal_date, "fiscal quarter", datetime.now(),
        eps_avg=2.0793, eps_high=2.20, eps_low=2.0313, eps_count=40,
        rev_avg=100.0, rev_high=120.0, rev_low=90.0, rev_count=35,
    )

    resp = client.get("/estimates/NVDA")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["periods"]) == 1
    period = body["periods"][0]
    assert period["eps_dispersion"] == pytest.approx((2.20 - 2.0313) / 2.0793, abs=1e-4)
    assert period["rev_dispersion"] == pytest.approx((120.0 - 90.0) / 100.0, abs=1e-4)


def test_get_estimates_eps_floor_nulls_dispersion_only(client, hf_path):
    fiscal_date = date.today() + timedelta(days=30)
    _seed(
        hf_path, "THIN", fiscal_date, "fiscal quarter", datetime.now(),
        eps_avg=0.02, eps_high=0.10, eps_low=-0.05, eps_count=8,
        rev_avg=50.0, rev_high=60.0, rev_low=40.0, rev_count=6,
    )

    resp = client.get("/estimates/THIN")
    assert resp.status_code == 200
    period = resp.json()["periods"][0]
    assert period["eps_dispersion"] is None
    assert period["eps_count"] == 8  # untouched by the floor guard
    assert period["rev_dispersion"] == pytest.approx((60.0 - 40.0) / 50.0, abs=1e-4)


def test_get_estimates_no_data_returns_404(client, hf_path):
    resp = client.get("/estimates/NOPE")
    assert resp.status_code == 404


def test_get_estimates_missing_db_returns_503(client, monkeypatch, tmp_path):
    monkeypatch.setattr(estimates_router_module, "_HF_DB", tmp_path / "does_not_exist.duckdb")
    resp = client.get("/estimates/NVDA")
    assert resp.status_code == 503
