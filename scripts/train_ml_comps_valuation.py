#!/usr/bin/env python3
"""
Train final ML comps-valuation quantile models on all available data and save
to data/ml_comps_valuation/{target}_{version}.joblib (+ a "_latest.joblib"
pointer), recording metrics in ml_model_metadata.

Only trains multiples that cleared the Phase 3 go/no-go gate
(historic_fundamentals.ml_comps_model.PASSING_MULTIPLES — currently P/E,
P/FCF, and P/S; EV/EBITDA excluded, see ml_comps_valuation_plan.md).

Run after scripts/validate_ml_comps_valuation.py confirms the gate passes.
Do not enable in run_pipeline.py (--enable-ml-comps) until it does.

Usage:
    uv run scripts/train_ml_comps_valuation.py
    uv run scripts/train_ml_comps_valuation.py --version 2026-07-20

Environment variables:
    HF_DB_PATH   path to historic_fundamentals.duckdb
    AV_DB_PATH (or AV_FINANCIALS_DB_PATH)  path to av_financials.duckdb
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH as AV_DB_PATH_DEFAULT  # noqa: E402
from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH_DEFAULT, HistoricFundamentalsDB  # noqa: E402
from historic_fundamentals.ml_comps_model import (  # noqa: E402
    DEFAULT_QUANTILE_PARAMS,
    FEATURE_COLS,
    MULTIPLE_TARGETS,
    PASSING_MULTIPLES,
    apply_zscore_stats,
    build_training_frame,
    fit_quantile_model,
    fit_sector_zscore_stats,
)

log = logging.getLogger(__name__)

MODEL_DIR = ROOT / "data" / "ml_comps_valuation"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train ML comps valuation quantile models.")
    parser.add_argument("--version", default=None, help="Model version tag (default: today's date)")
    parser.add_argument("--multiples", nargs="+", default=None,
                         help=f"Multiples to train (default: {PASSING_MULTIPLES})")
    parser.add_argument("--rolling-years", type=int, default=5,
                         help="Train on most recent N years only (default: 5, matching the "
                              "train_years used by the Phase 3 walk-forward gate and "
                              "train_model.py's convention for the existing model). Set 0 for "
                              "all history — not recommended: a full-history single-shot fit "
                              "was found to produce badly miscalibrated quantile tails (P/E "
                              "'high' bands in the thousands) versus a period-matched window.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    version = args.version or datetime.now(UTC).strftime("%Y-%m-%d")
    multiples = args.multiples or PASSING_MULTIPLES

    hf_db = os.getenv("HF_DB_PATH", HF_DB_PATH_DEFAULT)
    av_db = os.getenv("AV_DB_PATH", os.getenv("AV_FINANCIALS_DB_PATH", AV_DB_PATH_DEFAULT))

    log.info("Loading training frame from %s / %s", hf_db, av_db)
    hf_conn_ro = duckdb.connect(hf_db, read_only=True)
    av_conn = duckdb.connect(av_db, read_only=True)
    try:
        df = build_training_frame(hf_conn_ro, av_conn)
    finally:
        hf_conn_ro.close()
        av_conn.close()
    log.info("Training frame: %d rows, %d tickers", len(df), df["ticker"].nunique())

    if args.rolling_years:
        cutoff = df["month_end_date"].max() - pd.DateOffset(years=args.rolling_years)
        df = df[df["month_end_date"] >= cutoff].copy()
        log.info("Rolling window (%dyr): keeping %s onward — %d rows remain",
                 args.rolling_years, str(cutoff)[:10], len(df))

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    hf_db_rw = HistoricFundamentalsDB(hf_db)
    try:
        for name in multiples:
            spec = MULTIPLE_TARGETS[name]
            target_col = f"target_log_{name}"
            train_df = df[df[target_col].notna()].copy()

            feature_cols = [c for c in FEATURE_COLS if c in train_df.columns]
            zscore_stats = fit_sector_zscore_stats(train_df, feature_cols, "sector")
            train_df = apply_zscore_stats(train_df, feature_cols, "sector", zscore_stats)

            X = train_df[feature_cols].to_numpy(dtype=float, copy=True)
            y = train_df[target_col].to_numpy(dtype=float, copy=True)
            medians = np.nanmedian(X, axis=0)
            for j in range(X.shape[1]):
                X[np.isnan(X[:, j]), j] = medians[j]

            log.info(
                "Training %s on %d rows (%d tickers, %s to %s) ...",
                name, len(train_df), train_df["ticker"].nunique(),
                str(train_df["month_end_date"].min())[:10],
                str(train_df["month_end_date"].max())[:10],
            )

            model = fit_quantile_model(X, y, DEFAULT_QUANTILE_PARAMS)
            model.get_booster().feature_names = feature_cols

            bundle = {"model": model, "zscore_stats": zscore_stats, "feature_cols": feature_cols}
            model_path = MODEL_DIR / f"{name}_{version}.joblib"
            latest_path = MODEL_DIR / f"{name}_latest.joblib"
            joblib.dump(bundle, model_path)
            joblib.dump(bundle, latest_path)
            log.info("Saved %s (+ %s)", model_path, latest_path)

            hf_db_rw.deactivate_ml_model_versions(target=name)
            meta = pd.DataFrame([{
                "model_name": "ml_comps_valuation",
                "model_version": version,
                "target": name,
                "trained_at": datetime.now(UTC),
                "train_start_date": train_df["month_end_date"].min().date(),
                "train_end_date": train_df["month_end_date"].max().date(),
                "n_train_rows": len(train_df),
                "n_tickers": int(train_df["ticker"].nunique()),
                "feature_cols": json.dumps(feature_cols),
                "model_params": json.dumps(DEFAULT_QUANTILE_PARAMS),
                "oos_rmse_log": None,
                "oos_rmse_vs_baseline_pct": None,
                "oos_coverage_p10_p90": None,
                "file_path": str(model_path),
                "is_active": True,
                "notes": "OOS metrics recorded separately by validate_ml_comps_valuation.py",
            }])
            hf_db_rw.upsert_ml_model_metadata(meta)
    finally:
        hf_db_rw.close()

    log.info("Done.")


if __name__ == "__main__":
    main()
