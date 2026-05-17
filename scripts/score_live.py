#!/usr/bin/env python3
"""
Live scoring pipeline for the fundamentals-alpha model.

This script:
1. Loads latest features from HF_DB_PATH (monthly_pe table), most recent
   month_end_date per ticker. Filters to feature_available_date <= today.
2. Joins sector/industry/market_cap from AV_DB_PATH (company_overview).
3. Applies universe filters via filter_universe(UNIVERSE_DEFAULTS).
4. Computes composite score via composite_score() from baselines.
5. Attempts to load saved XGBoost model from model.joblib; falls back to
   composite baseline score if not found.
6. Ranks tickers by score (descending, 1 = best).
7. Attaches risk flags via value_trap_flags().
8. Computes missing-data flags per row.
9. Prints top-N table and writes CSV to docs/live_scores_{YYYYMMDD}.csv.

Usage:
    uv run scripts/score_live.py
    uv run scripts/score_live.py --top 50 --verbose
    uv run scripts/score_live.py --output /tmp/scores.csv --model /tmp/model.joblib

Environment variables:
    HF_DB_PATH      path to historic_fundamentals.duckdb
    AV_DB_PATH      path to av_financials.duckdb
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from historic_fundamentals.universe import UNIVERSE_DEFAULTS, filter_universe  # noqa: E402
from historic_fundamentals.baselines import (  # noqa: E402
    BASELINE_FACTORS,
    composite_score,
    _VALUE_COLS,
    _VALUE_SIGN,
    _QUALITY_COLS,
    _QUALITY_SIGN,
    _MOMENTUM_COL,
)
from historic_fundamentals.risk import value_trap_flags  # noqa: E402

log = logging.getLogger(__name__)

# Columns to include in output (skip gracefully if absent)
_OUTPUT_COLS = [
    "rank", "percentile", "ticker", "company_name", "score",
    "sector", "market_cap", "price",
    "liquidity",  # liquidity: not yet populated (no ADV data); column included for schema stability
    "pe_ratio", "fcf_yield", "earnings_yield", "ttm_gross_margin",
    "ttm_operating_margin", "debt_to_ebitda", "roa",
    "top_factor",
    "value_trap", "missing_factor_count", "data_quality",
    "feature_available_date",
]

# Factors used for missing-data count — explicit ordered list (deterministic, Python 3.7+ dict order)
_FACTOR_COLS_FOR_MISSING = [col for _, (col, _) in BASELINE_FACTORS.items()]


def _load_latest_features(hf_db_path: str) -> pd.DataFrame:
    """Load most recent month_end_date per ticker from monthly_pe."""
    conn = duckdb.connect(hf_db_path, read_only=True)
    df = conn.execute("SELECT * FROM monthly_pe").df()
    conn.close()

    df["month_end_date"] = pd.to_datetime(df["month_end_date"])
    if "feature_available_date" in df.columns:
        df["feature_available_date"] = pd.to_datetime(df["feature_available_date"])

    # Keep only most recent month_end_date per ticker
    df = (
        df.sort_values(["ticker", "month_end_date"])
        .groupby("ticker", as_index=False)
        .last()
    )
    log.info("Loaded %d tickers from monthly_pe (most recent row each)", len(df))
    return df


def _enforce_pit(df: pd.DataFrame, today=None) -> pd.DataFrame:
    """Filter to rows where feature_available_date <= today. Log violations."""
    today_ts = pd.Timestamp(today or date.today())
    if "feature_available_date" not in df.columns:
        if "updated_at" in df.columns:
            df = df.copy()
            df["feature_available_date"] = pd.to_datetime(df["updated_at"])
        else:
            log.warning("Neither feature_available_date nor updated_at found — PIT not enforced")
            df = df.copy()
            df["feature_available_date"] = pd.NaT
    # always apply mask
    mask = df["feature_available_date"].isna() | (df["feature_available_date"] <= today_ts)
    excluded = (~mask).sum()
    if excluded:
        log.warning("PIT filter: excluding %d rows with feature_available_date > today", excluded)
    return df[mask].copy()


def _join_overview(df: pd.DataFrame, av_db_path: str) -> pd.DataFrame:
    """Join sector, industry, market_cap, company_name from company_overview."""
    try:
        conn = duckdb.connect(av_db_path, read_only=True)
        overview = conn.execute(
            "SELECT ticker, name, sector, industry, market_cap FROM company_overview"
        ).df()
        conn.close()
    except Exception as exc:
        log.warning("Could not load company_overview from AV_DB_PATH: %s", exc)
        return df

    # Rename name -> company_name for clarity
    if "name" in overview.columns:
        overview = overview.rename(columns={"name": "company_name"})

    ov_cols = [c for c in ["ticker", "company_name", "sector", "industry", "market_cap"]
               if c in overview.columns]

    # Bring in sector if missing; market_cap from overview as fallback
    if "sector" not in df.columns or df["sector"].isna().all():
        df = df.merge(overview[["ticker", "sector"]], on="ticker", how="left")
    else:
        df = df.merge(
            overview[ov_cols],
            on="ticker", how="left", suffixes=("", "_ov"),
        )
        if "sector_ov" in df.columns:
            df["sector"] = df["sector"].fillna(df["sector_ov"])
            df.drop(columns=["sector_ov"], inplace=True)
        if "market_cap_ov" in df.columns and "market_cap" in df.columns:
            df["market_cap"] = df["market_cap"].fillna(df["market_cap_ov"])
            df.drop(columns=["market_cap_ov"], inplace=True)

    if "industry" not in df.columns and "industry" in overview.columns:
        df = df.merge(overview[["ticker", "industry"]], on="ticker", how="left")

    log.info("After overview join: %d tickers with sector", df["sector"].notna().sum())
    return df


def _load_liquidity(prices_db_path: str, tickers: list[str], lookback_days: int = 30) -> pd.Series:
    """Return 30-day average daily dollar volume per ticker (volume * adj_close)."""
    try:
        conn = duckdb.connect(prices_db_path, read_only=True)
        placeholders = ", ".join(["?"] * len(tickers))
        df_vol = conn.execute(
            f"""
            SELECT ticker, AVG(volume * adj_close) AS addv
            FROM stock_prices
            WHERE ticker IN ({placeholders})
              AND date >= (SELECT MAX(date) - INTERVAL '{lookback_days} days' FROM stock_prices)
            GROUP BY ticker
            """,
            tickers,
        ).df()
        conn.close()
        return df_vol.set_index("ticker")["addv"]
    except Exception as exc:
        log.warning("Could not load liquidity from PRICES_DB_PATH: %s", exc)
        return pd.Series(dtype=float)


def _compute_market_cap(df: pd.DataFrame) -> pd.DataFrame:
    """Compute market_cap = shares * price if not already present."""
    if "market_cap" not in df.columns or df["market_cap"].isna().all():
        if "shares" in df.columns and "price" in df.columns:
            df["market_cap"] = df["shares"] * df["price"]
    elif "shares" in df.columns and "price" in df.columns:
        df["market_cap"] = df["market_cap"].fillna(df["shares"] * df["price"])
    return df


def _compute_composite_score(df: pd.DataFrame) -> pd.Series:
    """Build composite score using value+quality+momentum factors available."""
    value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
    value_sign = {c: _VALUE_SIGN[c] for c in value_cols}

    quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
    quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}

    has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()

    if value_cols and quality_cols and has_momentum:
        cols = value_cols + quality_cols + [_MOMENTUM_COL]
        sign_map = {**value_sign, **quality_sign, _MOMENTUM_COL: False}
        log.info("Composite: value+quality+momentum (%d factors)", len(cols))
    elif value_cols and quality_cols:
        cols = value_cols + quality_cols
        sign_map = {**value_sign, **quality_sign}
        log.info("Composite: value+quality (%d factors)", len(cols))
    elif value_cols:
        cols = value_cols
        sign_map = value_sign
        log.info("Composite: value only (%d factors)", len(cols))
    else:
        log.warning("No composite factor columns found — score defaults to 0.")
        return pd.Series(0.0, index=df.index)

    # For live scoring, cross-sectional grouping on a single date is correct:
    # add a dummy date column if month_end_date is not present
    group_col = "month_end_date" if "month_end_date" in df.columns else "_dummy_date"
    if group_col == "_dummy_date":
        df = df.copy()
        df["_dummy_date"] = "live"

    return composite_score(df, cols, sign_map, group_col=group_col)


def _load_model(model_path: str):
    """Load joblib model. Returns None if not found."""
    import joblib
    p = Path(model_path)
    if not p.exists():
        log.warning("Model not found at %s — using composite baseline score.", model_path)
        return None
    try:
        model = joblib.load(p)
        log.info("Loaded model from %s", p)
        return model
    except Exception as exc:
        log.warning("Could not load model from %s: %s — using baseline score.", p, exc)
        return None


def _predict_with_model(model, df: pd.DataFrame) -> pd.Series:
    """Score using XGBoost model. Falls back to 0.0 if feature columns missing."""
    try:
        feature_names = model.get_booster().feature_names
        present = [f for f in feature_names if f in df.columns]
        missing_feats = [f for f in feature_names if f not in df.columns]
        if missing_feats:
            log.warning("Model features missing from data: %s", missing_feats)
        X = df[present].copy()
        # Fill remaining model features with 0
        for f in feature_names:
            if f not in X.columns:
                X[f] = 0.0
        X = X[feature_names]
        preds = model.predict(X)
        return pd.Series(preds, index=df.index)
    except Exception as exc:
        log.warning("Model prediction failed: %s — using baseline score.", exc)
        return None


def _missing_factor_stats(df: pd.DataFrame, factor_cols: list[str]) -> pd.DataFrame:
    """Add missing_factor_count and data_quality columns."""
    present = [c for c in factor_cols if c in df.columns]
    df = df.copy()
    df["missing_factor_count"] = df[present].isna().sum(axis=1) if present else len(factor_cols)

    def _quality(n: int) -> str:
        if n == 0:
            return "good"
        if n <= 2:
            return "partial"
        return "poor"

    df["data_quality"] = df["missing_factor_count"].apply(_quality)
    return df


def _attach_value_trap(df: pd.DataFrame, score_col: str) -> pd.DataFrame:
    """Attach value_trap boolean column."""
    df = df.copy()
    df["value_trap"] = False

    required_for_vtf = any(c in df.columns for c in ["ttm_operating_margin", "debt_to_ebitda", "roa"])
    if not required_for_vtf:
        log.warning("value_trap_flags: no flag columns found — value_trap set to False for all.")
        return df

    flagged = value_trap_flags(df, score_col=score_col)
    if flagged.empty:
        return df

    if "ticker" in flagged.columns:
        trap_tickers = set(flagged["ticker"])
        df["value_trap"] = df["ticker"].isin(trap_tickers)
    return df


def _compute_top_factor(df: pd.DataFrame, factor_map: dict) -> pd.Series:
    """For each row, return the name of the factor with the highest |z-score|."""
    zscores = {}
    for name, (col, lower_is_better) in factor_map.items():
        if col not in df.columns:
            continue
        vals = df[col].copy()
        mu, sigma = vals.mean(), vals.std()
        if sigma == 0 or pd.isna(sigma):
            continue
        z = (vals - mu) / sigma
        if lower_is_better:
            z = -z
        zscores[name] = z.abs()
    if not zscores:
        return pd.Series("", index=df.index)
    zdf = pd.DataFrame(zscores, index=df.index)
    # idxmax raises on all-NaN rows; mask those rows and fill with ""
    all_nan_mask = zdf.isna().all(axis=1)
    result = pd.Series("", index=df.index, dtype=object)
    if (~all_nan_mask).any():
        result[~all_nan_mask] = zdf[~all_nan_mask].idxmax(axis=1)
    return result


def _select_output_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Select OUTPUT_COLS that exist in df."""
    cols = [c for c in _OUTPUT_COLS if c in df.columns]
    return df[cols]


def _validate_feature_dates(df: pd.DataFrame, today: date) -> None:
    """Warn (do not crash) if any feature_available_date > today."""
    if "feature_available_date" not in df.columns:
        return
    today_ts = pd.Timestamp(today)
    bad = df[df["feature_available_date"].notna() & (df["feature_available_date"] > today_ts)]
    if not bad.empty:
        log.warning(
            "Output validation: %d rows have feature_available_date > today (%s). Tickers: %s",
            len(bad), today, list(bad["ticker"].head(10)),
        )


def score_universe(
    hf_db_path: str,
    av_db_path: str,
    model_path: str,
    today: date | None = None,
    universe_kwargs: dict | None = None,
) -> pd.DataFrame:
    """
    Core scoring logic. Returns ranked DataFrame.

    Parameters
    ----------
    hf_db_path : str
        Path to historic_fundamentals.duckdb.
    av_db_path : str
        Path to av_financials.duckdb.
    model_path : str
        Path to model.joblib.
    today : date or None
        PIT cutoff date. Defaults to date.today().
    universe_kwargs : dict or None
        Overrides for UNIVERSE_DEFAULTS.

    Returns
    -------
    pd.DataFrame
        Ranked, filtered DataFrame with all diagnostic columns.
    """
    if today is None:
        today = date.today()

    uk = {**UNIVERSE_DEFAULTS, **(universe_kwargs or {})}

    # 1. Load features
    df = _load_latest_features(hf_db_path)

    # 2. PIT filter
    df = _enforce_pit(df, today)
    if df.empty:
        log.warning("No rows remain after PIT filter.")
        return df

    # 3. Join sector/industry/market_cap
    df = _join_overview(df, av_db_path)
    df = _compute_market_cap(df)

    n_before = len(df)
    # 4. Universe filters
    df = filter_universe(df, **uk)
    log.info("Universe filter: %d -> %d tickers (%d removed)",
             n_before, len(df), n_before - len(df))

    if df.empty:
        log.warning("No tickers pass universe filter.")
        return df

    # 5. Compute composite score
    df = df.copy()
    df["_composite_score"] = _compute_composite_score(df)

    # 6. Attempt model load; fall back to composite
    model = _load_model(model_path)
    if model is not None:
        preds = _predict_with_model(model, df)
        if preds is not None:
            df["score"] = preds
            log.info("Using XGBoost model scores.")
        else:
            df["score"] = df["_composite_score"]
    else:
        df["score"] = df["_composite_score"]

    # 7. Rank by score descending
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    n_ranked = len(df)
    df["rank"] = range(1, n_ranked + 1)
    # percentile: rank=1 -> 100, rank=N -> near 0
    df["percentile"] = (1.0 - (df["rank"] - 1) / n_ranked) * 100.0

    # liquidity: 30-day average daily dollar volume from prices.duckdb
    prices_db = os.getenv("PRICES_DB_PATH", "")
    if prices_db and Path(prices_db).exists():
        liq = _load_liquidity(prices_db, df["ticker"].tolist())
        df["liquidity"] = df["ticker"].map(liq)
    else:
        df["liquidity"] = float("nan")

    # 7b. Top-factor reason code (composite-score path)
    df["top_factor"] = _compute_top_factor(df, BASELINE_FACTORS)

    # 8. Risk flags
    df = _attach_value_trap(df, score_col="score")

    # 9. Missing-data flags
    factor_cols = _FACTOR_COLS_FOR_MISSING
    df = _missing_factor_stats(df, factor_cols)

    # 10. Output validation (warn only)
    _validate_feature_dates(df, today)

    return df


# Columns stored as fractions (0–1) that should display as percentages
_PCT_FRACTION_COLS = {
    "ttm_gross_margin", "ttm_operating_margin", "ttm_fcf_margin", "roa", "roe", "roic",
}
# Columns already in percentage points that just need a % suffix
_PCT_POINT_COLS = {
    "percentile", "fcf_yield", "earnings_yield", "ebitda_ev_yield",
}
# Columns to display with 1 decimal (plain numbers)
_DECIMAL_COLS = {
    "score", "price", "pe_ratio", "pfcf_ratio", "ev_ebitda", "ps_ratio", "pbv", "ptbv",
    "debt_to_ebitda", "interest_coverage",
}


def _fmt_market_cap(v) -> str:
    if pd.isna(v):
        return ""
    if v >= 1e12:
        return f"{v/1e12:.1f}T"
    if v >= 1e9:
        return f"{v/1e9:.1f}B"
    if v >= 1e6:
        return f"{v/1e6:.1f}M"
    return f"{v:.0f}"


def _format_display(df: pd.DataFrame) -> pd.DataFrame:
    """Return a string-formatted copy of df for terminal display only (does not affect CSV)."""
    out = df.copy()
    for col in out.columns:
        if col not in out or not pd.api.types.is_numeric_dtype(out[col]):
            continue
        if col in ("market_cap", "liquidity"):
            out[col] = out[col].apply(_fmt_market_cap)
        elif col in _PCT_FRACTION_COLS:
            out[col] = out[col].apply(
                lambda v: f"{v*100:.1f}%" if pd.notna(v) else ""
            )
        elif col in _PCT_POINT_COLS:
            out[col] = out[col].apply(
                lambda v: f"{v:.1f}%" if pd.notna(v) else ""
            )
        elif col in _DECIMAL_COLS:
            out[col] = out[col].apply(
                lambda v: f"{v:.1f}" if pd.notna(v) else ""
            )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live scoring pipeline for the fundamentals-alpha model."
    )
    parser.add_argument("--top", type=int, default=25,
                        help="Print top N tickers (default: 25)")
    parser.add_argument("--min-rank-pct", type=float, default=1.0,
                        help="Only output stocks in top X fraction (default: 1.0 = all)")
    parser.add_argument("--output", type=str, default=None,
                        help="Override output CSV path")
    parser.add_argument("--model", type=str, default=None,
                        help="Override model.joblib path")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))

    if not Path(hf_db).exists():
        log.error("HF_DB_PATH not found: %s", hf_db)
        sys.exit(1)

    today = date.today()
    model_path = args.model or str(Path(hf_db).parent / "model.joblib")

    ranked = score_universe(
        hf_db_path=hf_db,
        av_db_path=av_db,
        model_path=model_path,
        today=today,
    )

    if ranked.empty:
        log.error("No tickers scored. Check database and filters.")
        sys.exit(1)

    # Apply min-rank-pct filter
    if args.min_rank_pct < 1.0:
        cutoff = max(1, int(len(ranked) * args.min_rank_pct))
        ranked = ranked[ranked["rank"] <= cutoff].copy()

    out_df = _select_output_columns(ranked)

    # Print top N
    top_n = min(args.top, len(out_df))
    print(f"\nFundamentals Alpha — Live Scores ({today})")
    print(f"Universe: {len(ranked)} tickers after filters")
    print(f"\nTop {top_n}:")
    print(_format_display(out_df.head(top_n)).to_string(index=False))

    # Write CSV
    out_date = today.strftime("%Y%m%d")
    if args.output:
        csv_path = Path(args.output)
    else:
        docs_dir = ROOT / "docs"
        docs_dir.mkdir(exist_ok=True)
        csv_path = docs_dir / f"live_scores_{out_date}.csv"

    out_df.to_csv(csv_path, index=False)
    log.info("Wrote %d rows to %s", len(out_df), csv_path)
    print(f"\nWrote {len(out_df)} rows to {csv_path}")


if __name__ == "__main__":
    main()
