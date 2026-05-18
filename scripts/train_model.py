#!/usr/bin/env python3
"""
Train final XGBoost model on all available labeled data and save to data/model.joblib.

This is the production training step. Run after walk-forward validation confirms
the feature set is sound. The saved model is used by score_live.py.

Usage:
    uv run scripts/train_model.py
    uv run scripts/train_model.py --output data/model.joblib --verbose

Environment variables:
    HF_DB_PATH    path to historic_fundamentals.duckdb
    AV_DB_PATH    path to av_financials.duckdb (for sector join)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from historic_fundamentals.universe import UNIVERSE_DEFAULTS, filter_universe  # noqa: E402
from historic_fundamentals.model import DEFAULT_MODEL_PARAMS, _apply_sector_zscore  # noqa: E402

log = logging.getLogger(__name__)

FEATURE_COLS = [
    "pe_ratio", "ps_ratio", "fcf_yield", "ev_ebitda", "dividend_yield",
    "earnings_yield", "roa", "roe", "roic", "pbv", "ptbv",
    "pe_rolling_5yr_median", "pfcf_ratio", "pfcf_rolling_5yr_median",
    "ps_rolling_5yr_median", "ev_ebitda_rolling_5yr_median",
    "roa_rolling_5yr_median", "roic_rolling_5yr_median",
    "gross_margin_5y_median", "gross_margin_slope_5y",
    "operating_margin_5y_median", "operating_margin_change_3y",
    "operating_margin_slope_5y", "fcf_margin_5y_median",
    "fcf_margin_change_3y", "roa_stability_5y",
    "debt_to_ebitda", "interest_coverage", "momentum_12_1",
    "earnings_yield_norm", "fcf_yield_norm", "ev_ebitda_norm", "ps_ratio_norm",
    "earnings_quality", "asset_growth",
]

TARGET_COL = "ret_1y"
RETURN_HORIZONS = {TARGET_COL: 12}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train final XGBoost model.")
    parser.add_argument("--output", default=None, help="Output path for model.joblib")
    parser.add_argument("--min-cap", type=float, default=None)
    parser.add_argument("--min-price", type=float, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    import duckdb
    from xgboost import XGBRegressor

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    model_path = args.output or str(ROOT / "data" / "model.joblib")

    # Load data
    log.info("Loading monthly_pe from %s", hf_db)
    conn = duckdb.connect(hf_db, read_only=True)
    df = conn.execute("SELECT * FROM monthly_pe ORDER BY ticker, month_end_date").df()
    conn.close()
    df["month_end_date"] = pd.to_datetime(df["month_end_date"])
    log.info("Loaded %d rows, %d tickers", len(df), df["ticker"].nunique())

    # Join sector
    try:
        conn = duckdb.connect(av_db, read_only=True)
        overview = conn.execute("SELECT ticker, sector FROM company_overview").df()
        conn.close()
        df = df.merge(overview, on="ticker", how="left")
        log.info("Sector joined: %d tickers with sector", df["sector"].notna().sum())
    except Exception as exc:
        log.warning("Could not join sector: %s", exc)

    df["market_cap"] = df["shares"] * df["price"]

    # Universe filters
    universe_kwargs = {**UNIVERSE_DEFAULTS}
    if args.min_cap is not None:
        universe_kwargs["min_market_cap"] = args.min_cap
    if args.min_price is not None:
        universe_kwargs["min_price"] = args.min_price

    df = filter_universe(df, **universe_kwargs)
    log.info("After universe filter: %d rows, %d tickers", len(df), df["ticker"].nunique())

    # Compute 1-year forward returns using per-ticker shift (memory efficient)
    log.info("Computing forward returns ...")
    df = df.sort_values(["ticker", "month_end_date"]).reset_index(drop=True)
    df[TARGET_COL] = (
        df.groupby("ticker")["price"]
        .transform(lambda s: s.shift(-12) / s - 1)
    )
    df = df[df[TARGET_COL].notna()].copy()
    log.info("After dropping rows without ret_1y: %d rows", len(df))

    if len(df) < 1000:
        log.error("Too few labeled rows (%d) to train. Aborting.", len(df))
        sys.exit(1)

    # Select features present in data
    feature_cols = [c for c in FEATURE_COLS if c in df.columns and df[c].notna().any()]
    log.info("Training on %d features: %s", len(feature_cols), feature_cols)

    sector_col = "sector" if ("sector" in df.columns and df["sector"].notna().any()) else None

    # Sector-relative z-scores on full training set
    df_train = df.copy()
    if sector_col:
        df_train, _ = _apply_sector_zscore(df_train, df_train.head(0), feature_cols, sector_col)

    X = df_train[feature_cols].to_numpy(dtype=float, copy=True)
    y = df_train[TARGET_COL].to_numpy(dtype=float, copy=True)

    # Fill NaN with column medians
    col_medians = np.nanmedian(X, axis=0)
    for j in range(X.shape[1]):
        X[np.isnan(X[:, j]), j] = col_medians[j]

    log.info(
        "Training XGBoost on %d rows (%d tickers, %s to %s) ...",
        len(df_train),
        df_train["ticker"].nunique(),
        str(df_train["month_end_date"].min())[:10],
        str(df_train["month_end_date"].max())[:10],
    )

    model = XGBRegressor(**DEFAULT_MODEL_PARAMS)
    model.fit(X, y)
    model.get_booster().feature_names = feature_cols

    joblib.dump(model, model_path)
    log.info("Model saved to %s", model_path)

    # Feature importance summary
    importance = pd.Series(model.feature_importances_, index=feature_cols)
    importance = importance.sort_values(ascending=False)
    print("\nTop feature importances:")
    for feat, imp in importance.head(15).items():
        print(f"  {feat:<40} {imp:.4f}")

    print(f"\nModel saved to {model_path}")
    print(f"Training rows: {len(df_train):,} | Tickers: {df_train['ticker'].nunique():,}")
    print(f"Date range: {str(df_train['month_end_date'].min())[:10]} to {str(df_train['month_end_date'].max())[:10]}")


if __name__ == "__main__":
    main()
