"""
Phase 1/2 tests for historic_fundamentals/ml_comps_model.py — feature/dataset
assembly and quantile model fitting for the ML comps-based fair valuation model.

See features/historic_fundamentals/ml_comps_valuation_plan.md.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from av_financials_db import DEFAULT_DB_PATH as AV_DB_PATH
from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH
from historic_fundamentals.ml_comps_model import (
    FEATURE_COLS,
    build_training_frame,
    fit_quantile_model,
    predict_quantiles,
)

_TICKERS = ["AAPL", "MSFT", "JPM", "XOM"]


@pytest.fixture
def frame() -> pd.DataFrame:
    if not Path(HF_DB_PATH).exists() or not Path(AV_DB_PATH).exists():
        pytest.skip("historic_fundamentals.duckdb / av_financials.duckdb not present")
    hf_conn = duckdb.connect(HF_DB_PATH, read_only=True)
    av_conn = duckdb.connect(AV_DB_PATH, read_only=True)
    try:
        df = build_training_frame(hf_conn, av_conn)
    finally:
        hf_conn.close()
        av_conn.close()
    return df[df["ticker"].isin(_TICKERS)].reset_index(drop=True)


def test_point_in_time_filter_holds(frame):
    assert (frame["feature_available_date"] <= frame["month_end_date"]).all()


def test_target_null_iff_source_multiple_not_positive(frame):
    negative_or_null_pe = frame["pe_ratio"].isna() | (frame["pe_ratio"] <= 0)
    assert (frame.loc[negative_or_null_pe, "target_log_pe"].isna()).all()

    positive_pe = frame["pe_ratio"] > 0
    assert frame.loc[positive_pe, "target_log_pe"].notna().all()


def test_peer_median_present_whenever_target_present(frame):
    has_target = frame["target_log_pe"].notna()
    assert frame.loc[has_target, "pe_median"].notna().all()


def test_all_feature_cols_present(frame):
    for col in FEATURE_COLS:
        assert col in frame.columns, f"missing feature column: {col}"


def test_min_peers_filter_applied(frame):
    assert (frame["ticker_count"] >= 5).all()


# ── Phase 2: quantile model sanity (synthetic data) ────────────────────────

def test_predict_quantiles_monotonic_and_accurate():
    rng = np.random.default_rng(42)
    n = 2000
    X = rng.normal(size=(n, 4))
    noise_std = 0.3
    y = 2.0 + 0.5 * X[:, 0] - 0.2 * X[:, 1] + rng.normal(scale=noise_std, size=n)

    model = fit_quantile_model(X, y, params={"n_estimators": 100, "max_depth": 3})
    preds = predict_quantiles(model, X)

    assert preds.shape == (n, 3)
    p10, p50, p90 = preds[:, 0], preds[:, 1], preds[:, 2]
    assert np.all(p10 <= p50) and np.all(p50 <= p90)

    rmse = float(np.sqrt(np.mean((y - p50) ** 2)))
    assert rmse < 2 * noise_std
