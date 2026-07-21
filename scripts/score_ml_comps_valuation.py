#!/usr/bin/env python3
"""
Monthly batch: score the current universe with the ML comps-valuation models
and cache the result in historic_fundamentals.duckdb::ml_comps_valuation, for
the additive "ML Fair Value" field in the fundamentals API/UI (see
features/historic_fundamentals/ml_comps_valuation_plan.md Phase 4).

Only scores multiples that cleared the Phase 3 gate
(historic_fundamentals.ml_comps_model.PASSING_MULTIPLES — currently P/E,
P/FCF, and P/S). Fair price per multiple = predicted multiple x the ticker's
own current EPS/FCF-per-share/revenue-per-share; ml_fair_price_{low,mid,high}
blends whichever bases are available (median across bases, documented in
ml_fair_price_basis).

Usage:
    uv run scripts/score_ml_comps_valuation.py                    # all tickers
    uv run scripts/score_ml_comps_valuation.py --tickers AAPL,JPM,WMT
    uv run scripts/score_ml_comps_valuation.py --verbose

Writes one row per ticker to ml_comps_valuation (status='ok'/'insufficient_peers'/
'no_price_basis'/'error'), full rebuild each run — mirrors compute_dcf_batch.py's
rebuild style, not an incremental merge.
"""

from __future__ import annotations

import argparse
import logging
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
    MULTIPLE_TARGETS,
    PASSING_MULTIPLES,
    apply_zscore_stats,
    predict_quantiles,
)

log = logging.getLogger(__name__)

MODEL_DIR = ROOT / "data" / "ml_comps_valuation"
_MIN_PEERS = 5
MAX_MULTIPLE = 500.0  # sanity cap; see comment at point of use


def _load_latest_snapshot(hf_conn, av_conn) -> pd.DataFrame:
    """Latest monthly_pe row per ticker, joined with sector + peer group size."""
    df = hf_conn.execute("""
        SELECT m.*
        FROM monthly_pe m
        QUALIFY ROW_NUMBER() OVER (PARTITION BY m.ticker ORDER BY m.month_end_date DESC) = 1
    """).df()
    sector_map = av_conn.execute("""
        SELECT ticker, sector FROM company_overview
        QUALIFY fetch_date = MAX(fetch_date) OVER (PARTITION BY ticker)
    """).df()
    df = df.merge(sector_map, on="ticker", how="left")

    # sector_stats is recomputed monthly by hf_update.py and can lag monthly_pe
    # by up to a month (e.g. monthly_pe already has a partial next month while
    # sector_stats hasn't rebuilt yet) — use sector_stats' own latest available
    # month rather than requiring an exact match to monthly_pe's max date.
    sector_stats = hf_conn.execute("""
        SELECT group_name AS sector, ticker_count
        FROM sector_stats
        WHERE group_type = 'sector'
          AND month_end_date = (SELECT MAX(month_end_date) FROM sector_stats WHERE group_type = 'sector')
    """).df()
    df = df.merge(sector_stats, on="sector", how="left")
    return df


def _load_bundle(target: str):
    path = MODEL_DIR / f"{target}_latest.joblib"
    if not path.exists():
        return None
    return joblib.load(path)


def _predict_multiple(bundle: dict, df: pd.DataFrame) -> np.ndarray | None:
    """Batch prediction using the z-score stats persisted at training time
    (fit_sector_zscore_stats/apply_zscore_stats), not recomputed from the live
    scoring snapshot — recomputing from a single cross-section applies a
    different reference distribution than the model was trained on and produces
    badly miscalibrated (unbounded) quantile predictions in practice."""
    model = bundle["model"]
    feature_cols = bundle["feature_cols"]
    zscore_stats = bundle["zscore_stats"]

    scored_df = apply_zscore_stats(df, feature_cols, "sector", zscore_stats)

    X = scored_df[[c for c in feature_cols if c in scored_df.columns]].copy()
    for f in feature_cols:
        if f not in X.columns:
            X[f] = np.nan
    X = X[feature_cols]
    X = X.fillna(X.median())
    return predict_quantiles(model, X.to_numpy(dtype=float))


def score_ml_comps_valuation(tickers: list[str], hf_conn, av_conn, version: str) -> pd.DataFrame:
    snapshot = _load_latest_snapshot(hf_conn, av_conn)
    snapshot = snapshot[snapshot["ticker"].isin(tickers)].reset_index(drop=True)

    bundles = {name: _load_bundle(name) for name in PASSING_MULTIPLES}
    missing = [name for name, b in bundles.items() if b is None]
    if missing:
        log.warning("No trained model found for: %s (run train_ml_comps_valuation.py first)", missing)

    now = datetime.now(UTC)
    preds = {}
    for name in PASSING_MULTIPLES:
        bundle = bundles.get(name)
        preds[name] = _predict_multiple(bundle, snapshot) if bundle is not None else None

    rows = []
    by_ticker = {t: i for i, t in enumerate(snapshot["ticker"])}
    for ticker in tickers:
        idx = by_ticker.get(ticker)
        if idx is None:
            rows.append({"ticker": ticker, "computed_at": now, "model_version": version,
                         "status": "error", "error_message": "no monthly_pe data"})
            continue

        row = snapshot.iloc[idx]
        if pd.isna(row.get("ticker_count")) or row["ticker_count"] < _MIN_PEERS:
            rows.append({"ticker": ticker, "computed_at": now, "model_version": version,
                         "sector": row.get("sector"),
                         "status": "insufficient_peers", "error_message": None})
            continue

        out = {"ticker": ticker, "computed_at": now, "model_version": version,
               "sector": row.get("sector"), "error_message": None}
        price_bases = []

        for name, spec in MULTIPLE_TARGETS.items():
            if name not in PASSING_MULTIPLES or preds.get(name) is None:
                continue
            # Tree-based quantile regression occasionally extrapolates to
            # implausible multiples for unusual feature combinations (observed
            # up to ~1000x+ pre-clip on a small tail of the universe); cap at
            # MAX_MULTIPLE so a "fair value" figure never shows something
            # absurd. Bulk of predictions are well under this bound already.
            p10, p50, p90 = np.exp(np.minimum(preds[name][idx], np.log(MAX_MULTIPLE)))
            out[f"ml_fair_{name}_low"] = float(p10)
            out[f"ml_fair_{name}_mid"] = float(p50)
            out[f"ml_fair_{name}_high"] = float(p90)

            basis = None
            if name == "pe" and pd.notna(row.get("ttm_eps")) and row["ttm_eps"] > 0:
                basis = row["ttm_eps"]
            elif name == "pfcf" and pd.notna(row.get("ttm_fcf")) and pd.notna(row.get("shares")) and row["ttm_fcf"] > 0 and row["shares"] > 0:
                basis = row["ttm_fcf"] / row["shares"]
            elif name == "ps" and pd.notna(row.get("ttm_revenue")) and pd.notna(row.get("shares")) and row["ttm_revenue"] > 0 and row["shares"] > 0:
                basis = row["ttm_revenue"] / row["shares"]

            if basis is not None:
                price_bases.append((name, np.array([p10, p50, p90]) * basis))

        if price_bases:
            stacked = np.stack([p for _, p in price_bases], axis=0)
            blended = np.median(stacked, axis=0)
            out["ml_fair_price_low"], out["ml_fair_price_mid"], out["ml_fair_price_high"] = (
                float(blended[0]), float(blended[1]), float(blended[2])
            )
            out["ml_fair_price_basis"] = "median(" + ",".join(n for n, _ in price_bases) + ")"
            out["status"] = "ok"
        else:
            out["ml_fair_price_basis"] = None
            out["status"] = "no_price_basis"

        rows.append(out)

    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-score the ML comps valuation model.")
    parser.add_argument("--tickers", help="Comma-separated tickers (default: all in company_overview)")
    parser.add_argument("--version", default=None, help="Model version tag to record (default: today)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    hf_db = HF_DB_PATH_DEFAULT
    av_db = AV_DB_PATH_DEFAULT
    version = args.version or datetime.now(UTC).strftime("%Y-%m-%d")

    av_conn = duckdb.connect(av_db, read_only=True)
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        tickers = [r[0] for r in av_conn.execute(
            "SELECT DISTINCT ticker FROM company_overview ORDER BY ticker"
        ).fetchall()]

    hf_db_rw = HistoricFundamentalsDB(hf_db)
    try:
        df = score_ml_comps_valuation(tickers, hf_db_rw.conn, av_conn, version)
        n = hf_db_rw.upsert_ml_comps_valuation(df)
        log.info("Scored %d tickers -> ml_comps_valuation (%d rows written)", len(tickers), n)
        log.info("Status breakdown:\n%s", df["status"].value_counts().to_string())
    finally:
        hf_db_rw.close()
        av_conn.close()


if __name__ == "__main__":
    main()
