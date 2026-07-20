"""
Phase 4 tests for scripts/score_ml_comps_valuation.py — batch scoring +
ml_comps_valuation upsert. Runs against a copy of the real historic_fundamentals.duckdb
(via tmp_path) so the batch script's writes never touch production data, mirroring
tests/test_compute_dcf_batch.py's pattern. Requires trained models to already exist
at data/ml_comps_valuation/{pe,pfcf}_latest.joblib (run
scripts/train_ml_comps_valuation.py first) — skipped otherwise.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest

from av_financials_db import DEFAULT_DB_PATH as AV_DB_PATH
from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH, HistoricFundamentalsDB
from historic_fundamentals.ml_comps_model import PASSING_MULTIPLES
from scripts.score_ml_comps_valuation import MODEL_DIR, score_ml_comps_valuation

_TICKERS = ["AAPL", "MSFT", "JPM"]


@pytest.fixture
def hf_db_copy(tmp_path) -> str:
    if not Path(HF_DB_PATH).exists():
        pytest.skip("historic_fundamentals.duckdb not present")
    if not all((MODEL_DIR / f"{name}_latest.joblib").exists() for name in PASSING_MULTIPLES):
        pytest.skip("trained ml_comps_valuation models not present — run train_ml_comps_valuation.py first")
    dest = tmp_path / "historic_fundamentals.duckdb"
    shutil.copy(HF_DB_PATH, dest)
    return str(dest)


def test_scoring_writes_one_row_per_ticker_with_correct_status(hf_db_copy):
    hf_db = HistoricFundamentalsDB(hf_db_copy)
    av_conn = duckdb.connect(AV_DB_PATH, read_only=True)
    try:
        df = score_ml_comps_valuation(_TICKERS, hf_db.conn, av_conn, version="test")
        n = hf_db.upsert_ml_comps_valuation(df)

        rows = hf_db.conn.execute(
            "SELECT ticker, status, ml_fair_price_low, ml_fair_price_mid, ml_fair_price_high "
            "FROM ml_comps_valuation WHERE ticker = ANY(?) ORDER BY ticker",
            [_TICKERS],
        ).fetchall()
    finally:
        hf_db.close()
        av_conn.close()

    assert n == len(_TICKERS)
    assert [r[0] for r in rows] == sorted(_TICKERS)

    for ticker, status, low, mid, high in rows:
        assert status in ("ok", "insufficient_peers", "no_price_basis", "error")
        if status == "ok":
            assert low is not None and mid is not None and high is not None
            assert low <= mid <= high
