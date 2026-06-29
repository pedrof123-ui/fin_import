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
import numpy as np
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
from historic_fundamentals.model import _apply_sector_zscore  # noqa: E402

log = logging.getLogger(__name__)

# Backtest reference metrics — sector-neutral composite score (Phase 3 validation).
# Full universe 1983–2026, 404 months guardrailed, vol-weighted, regime-filtered.
# rf_vw_* entries use vol-weighting + regime filter (the live portfolio configuration).
_BACKTEST_METRICS: dict[str, dict] = {
    "gr_top_n_25":           dict(cagr="17.0%", sharpe="0.960", max_dd="-39.7%", beta="0.781", win_rate="65.6%", months=404),
    "vw_gr_top_n_25":        dict(cagr="16.7%", sharpe="1.000", max_dd="-35.4%", beta="0.735", win_rate="67.1%", months=404),
    "rf_gr_top_n_25":        dict(cagr="15.6%", sharpe="1.015", max_dd="-25.7%", beta="0.634", win_rate="67.1%", months=404),
    "rf_vw_gr_top_n_25":     dict(cagr="15.6%", sharpe="1.015", max_dd="-25.7%", beta="0.634", win_rate="67.1%", months=404),
    "xgb_gr_top_n_25":       dict(cagr="20.5%", sharpe="1.076", max_dd="-26.6%", beta="1.054", win_rate="62.6%", months=211),
    "vw_xgb_gr_top_n_25":    dict(cagr="19.5%", sharpe="1.089", max_dd="-23.5%", beta="0.989", win_rate="62.6%", months=211),
    "rf_xgb_gr_top_n_25":    dict(cagr="18.0%", sharpe="1.143", max_dd="-21.5%", beta="0.870", win_rate="62.6%", months=211),
    "rf_vw_xgb_gr_top_n_25": dict(cagr="18.0%", sharpe="1.143", max_dd="-21.5%", beta="0.870", win_rate="62.6%", months=211),
}


def _portfolio_label(use_model: bool, vol_weighted: bool, regime_active: bool, top_n: int) -> str:
    parts = []
    if regime_active:
        parts.append("rf")
    if vol_weighted:
        parts.append("vw")
    parts.append("xgb_gr" if use_model else "gr")
    parts.append(f"top_n_{top_n}")
    return "_".join(parts)


# Columns to include in output (skip gracefully if absent)
_OUTPUT_COLS = [
    "rank", "percentile", "ticker", "company_name", "score",
    "sector", "market_cap", "price",
    "liquidity",
    "weight_pct", "alloc_pct",
    "pe_ratio", "fcf_yield", "earnings_yield", "ttm_gross_margin",
    "ttm_operating_margin", "debt_to_ebitda", "roa",
    "top_factor",
    "value_trap", "missing_factor_count", "data_quality",
    "feature_available_date",
]

# Factors used for missing-data count — explicit ordered list (deterministic, Python 3.7+ dict order)
_FACTOR_COLS_FOR_MISSING = [col for _, (col, _) in BASELINE_FACTORS.items()]


def _load_latest_features(hf_db_path: str, today=None) -> pd.DataFrame:
    """Load most recent PIT-safe row per ticker from monthly_pe.

    For each ticker, picks the most recent month_end_date where
    feature_available_date <= today. This avoids dropping tickers whose
    current-month row has a future feature_available_date (e.g. the May row
    is built on March filings with a 60-day lag, available May 30, but today
    is May 17 — so the April row is used instead).
    """
    today_ts = pd.Timestamp(today or date.today())

    conn = duckdb.connect(hf_db_path, read_only=True)
    df = conn.execute("SELECT * FROM monthly_pe").df()
    conn.close()

    df["month_end_date"] = pd.to_datetime(df["month_end_date"])
    if "feature_available_date" in df.columns:
        df["feature_available_date"] = pd.to_datetime(df["feature_available_date"])

    # Keep only rows whose feature data is available as of today
    if "feature_available_date" in df.columns:
        pit_ok = df["feature_available_date"].isna() | (df["feature_available_date"] <= today_ts)
        n_future = (~pit_ok).sum()
        if n_future:
            log.info("Skipping %d future rows (feature_available_date > today); using prior month for those tickers", n_future)
        df = df[pit_ok]

    # Most recent available row per ticker
    df = (
        df.sort_values(["ticker", "month_end_date"])
        .groupby("ticker", as_index=False)
        .last()
    )
    log.info("Loaded %d tickers from monthly_pe (most recent PIT-safe row each)", len(df))
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

    # Deduplicate: company_overview may have multiple rows per ticker (historical snapshots)
    overview = overview.drop_duplicates(subset=["ticker"], keep="last")

    # Rename name -> company_name for clarity
    if "name" in overview.columns:
        overview = overview.rename(columns={"name": "company_name"})

    ov_cols = [c for c in ["ticker", "company_name", "sector", "industry", "market_cap"]
               if c in overview.columns]

    # Single merge bringing in all overview columns at once
    df = df.merge(overview[ov_cols], on="ticker", how="left", suffixes=("", "_ov"))
    for col in ["sector", "market_cap"]:
        ov_col = f"{col}_ov"
        if ov_col in df.columns:
            if col in df.columns:
                df[col] = df[col].fillna(df[ov_col])
            else:
                df[col] = df[ov_col]
            df.drop(columns=[ov_col], inplace=True)

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


def _compute_composite_score(df: pd.DataFrame, sector_neutral: bool = True) -> pd.Series:
    """Build composite score using value+quality+momentum factors available.

    sector_neutral=True (default): z-score each factor within (date, sector)
    so Apple is ranked against tech peers, not against ExxonMobil. Sectors
    with fewer than 3 stocks fall back to market-wide z-score for that group.
    Validated in Phase 3: +0.3pp CAGR, +0.004 Sharpe, -1pp MaxDD improvement
    over market-wide on rf_gr_top_n_25 across 404 months.
    """
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

    return composite_score(df, cols, sign_map, group_col=group_col, sector_neutral=sector_neutral)


def _load_model(model_path):
    """Load joblib model. Returns None if not found or model_path is None."""
    if model_path is None:
        return None
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
    """Score using XGBoost model. Falls back to None if feature columns missing."""
    try:
        feature_names = model.get_booster().feature_names
        missing_feats = [f for f in feature_names if f not in df.columns]
        if missing_feats:
            log.warning("Model features missing from data: %s", missing_feats)

        # Apply sector-relative z-scores to match the transformation used at training time.
        # _apply_sector_zscore(train, test, ...) computes stats from train and applies to both;
        # passing empty test mirrors what train_model.py does on the full training set.
        sector_col = "sector"
        present_features = [f for f in feature_names if f in df.columns]
        if sector_col in df.columns and df[sector_col].notna().any():
            scored_df, _ = _apply_sector_zscore(
                df, df.head(0), present_features, sector_col
            )
            log.info("Sector z-scores applied before model prediction.")
        else:
            scored_df = df.copy()
            log.warning("No sector column — skipping sector z-score normalization.")

        X = scored_df[present_features].copy()
        for f in feature_names:
            if f not in X.columns:
                X[f] = np.nan
        X = X[feature_names]
        # Fill NaN with column medians (same strategy as training)
        col_medians = X.median()
        X = X.fillna(col_medians)
        preds = model.predict(X.to_numpy(dtype=float))
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


def _compute_stock_vols(prices_db_path: str, tickers: list[str], lookback_months: int = 12) -> pd.Series:
    """Trailing 12-month monthly return vol per ticker (std of monthly returns)."""
    try:
        conn = duckdb.connect(prices_db_path, read_only=True)
        placeholders = ", ".join(["?"] * len(tickers))
        df_px = conn.execute(
            f"SELECT ticker, date, adj_close FROM stock_prices "
            f"WHERE ticker IN ({placeholders}) ORDER BY ticker, date",
            tickers,
        ).df()
        conn.close()
    except Exception as exc:
        log.warning("Could not load prices for vol computation: %s", exc)
        return pd.Series(dtype=float)

    if df_px.empty:
        return pd.Series(dtype=float)

    df_px["date"] = pd.to_datetime(df_px["date"])
    # Monthly prices: last price in each calendar month
    df_px["month"] = df_px["date"].dt.to_period("M")
    monthly = (
        df_px.sort_values("date")
        .groupby(["ticker", "month"])["adj_close"]
        .last()
        .reset_index()
    )
    monthly = monthly.sort_values(["ticker", "month"])
    monthly["ret"] = monthly.groupby("ticker")["adj_close"].pct_change()

    # Keep only the trailing lookback_months return observations per ticker
    vols = (
        monthly.groupby("ticker")["ret"]
        .apply(lambda s: s.dropna().tail(lookback_months).std())
    )
    vols.name = "vol_12m"
    log.info("Vol computed for %d / %d tickers", vols.notna().sum(), len(tickers))
    return vols


def _compute_regime(prices_db_path: str, high: float = 0.25, low: float = -0.20) -> tuple[float, float, str]:
    """Compute SPY 12-month trailing return and derive regime exposure.

    Returns (exposure_fraction, spy_12m_return, label).
    exposure_fraction = 0.5 if SPY 12m > high or < low, else 1.0.
    """
    try:
        conn = duckdb.connect(prices_db_path, read_only=True)
        spy = conn.execute(
            "SELECT date, adj_close FROM etf_prices WHERE ticker='SPY' ORDER BY date"
        ).df()
        conn.close()
    except Exception as exc:
        log.warning("Could not load SPY for regime: %s", exc)
        return 1.0, float("nan"), "UNKNOWN"

    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.set_index("date").sort_index()
    spy_monthly = spy["adj_close"].resample("ME").last().dropna()

    if len(spy_monthly) < 13:
        return 1.0, float("nan"), "UNKNOWN"

    r12 = float(spy_monthly.iloc[-1] / spy_monthly.iloc[-13] - 1)
    if r12 > high or r12 < low:
        label = f"REDUCED 50% (SPY 12m={r12:+.1%} {'>' if r12 > high else '<'} {high if r12 > high else low:.0%})"
        return 0.5, r12, label
    return 1.0, r12, f"FULL 100% (SPY 12m={r12:+.1%})"


def _select_output_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Select OUTPUT_COLS that exist in df."""
    cols = [c for c in _OUTPUT_COLS if c in df.columns]
    return df[cols]


def _apply_bcd_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Remove stocks where bcd_misp > 0 or NULL (BCD hard filter: require structural underpricing)."""
    if "bcd_misp" not in df.columns:
        log.warning("bcd_misp column not found — BCD filter skipped")
        return df
    mask = df["bcd_misp"].notna() & (df["bcd_misp"] <= 0.0)
    n_removed = int((~mask).sum())
    log.info("BCD filter: removed %d stocks (bcd_misp > 0 or NULL) → %d remain", n_removed, int(mask.sum()))
    return df[mask].copy()


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

    # 1. Load features (PIT-safe: picks most recent available row per ticker)
    df = _load_latest_features(hf_db_path, today=today)

    # 2. PIT filter
    df = _enforce_pit(df, today)
    if df.empty:
        log.warning("No rows remain after PIT filter.")
        return df

    # 3. Join sector/industry/market_cap
    df = _join_overview(df, av_db_path)
    df = _compute_market_cap(df)

    # 4. Load ADV for liquidity filter (must happen before filter_universe)
    prices_db = os.getenv("PRICES_DB_PATH", "")
    if prices_db and Path(prices_db).exists():
        liq = _load_liquidity(prices_db, df["ticker"].tolist())
        df["avg_dollar_volume"] = df["ticker"].map(liq)
        log.info("ADV loaded: %d/%d tickers have avg_dollar_volume",
                 df["avg_dollar_volume"].notna().sum(), len(df))
    else:
        df["avg_dollar_volume"] = float("nan")

    n_before = len(df)
    # 5. Universe filters (includes liquidity filter via avg_dollar_volume column)
    df = filter_universe(df, **uk)
    log.info("Universe filter: %d -> %d tickers (%d removed)",
             n_before, len(df), n_before - len(df))

    if df.empty:
        log.warning("No tickers pass universe filter.")
        return df

    # Map avg_dollar_volume → liquidity for display
    df = df.copy()
    df["liquidity"] = df["avg_dollar_volume"] if "avg_dollar_volume" in df.columns else float("nan")

    # 6. Compute composite score
    df["_composite_score"] = _compute_composite_score(df)

    # 7. Attempt model load; fall back to composite
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

    # 8. Rank by score descending
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    n_ranked = len(df)
    df["rank"] = range(1, n_ranked + 1)
    # percentile: rank=1 -> 100, rank=N -> near 0
    df["percentile"] = (1.0 - (df["rank"] - 1) / n_ranked) * 100.0

    # 9. Top-factor reason code (composite-score path)
    df["top_factor"] = _compute_top_factor(df, BASELINE_FACTORS)

    # 10. Risk flags
    df = _attach_value_trap(df, score_col="score")

    # 11. Missing-data flags
    factor_cols = _FACTOR_COLS_FOR_MISSING
    df = _missing_factor_stats(df, factor_cols)

    # 12. Output validation (warn only)
    _validate_feature_dates(df, today)

    return df


# Columns stored as fractions (0–1) that should display as percentages
_PCT_FRACTION_COLS = {
    "ttm_gross_margin", "ttm_operating_margin", "ttm_fcf_margin",
    "roa", "roe", "roic",
    "fcf_yield", "earnings_yield", "ebitda_ev_yield",
}
# Columns already in percentage points (0–100) that just need a % suffix
_PCT_POINT_COLS = {
    "percentile", "weight_pct", "alloc_pct",
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
        return f"{v/1e9:.0f}B"
    if v >= 1e6:
        return f"{v/1e6:.0f}M"
    return f"{v:.0f}"


def _format_display(df: pd.DataFrame) -> pd.DataFrame:
    """Return a string-formatted copy of df for display and CSV output."""
    out = df.copy()
    for col in out.columns:
        if col == "feature_available_date" and pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d").fillna("")
            continue
        if not pd.api.types.is_numeric_dtype(out[col]):
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
                        help="Explicit path to model.joblib to use XGBoost scoring")
    parser.add_argument("--use-model", action="store_true",
                        help="Use saved XGBoost model from HF_DB_PATH directory")
    parser.add_argument("--no-model", action="store_true",
                        help="Force composite score (default; kept for backwards compatibility)")
    parser.add_argument("--guardrails", action="store_true", default=True,
                        help="Exclude value traps and poor data quality (default: on)")
    parser.add_argument("--no-guardrails", dest="guardrails", action="store_false",
                        help="Disable guardrail filters (include value traps and partial data)")
    parser.add_argument("--max-missing", type=int, default=2,
                        help="Max missing features before a stock is excluded (default: 2)")
    parser.add_argument("--max-sector-pct", type=float, default=0.25,
                        help="Max fraction of portfolio from any single sector (default: 0.25 = 25%%)")
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
    # Composite score is default; XGBoost requires --use-model or --model PATH
    if args.no_model or (not args.use_model and not args.model):
        model_path = None
    elif args.model:
        model_path = args.model
    else:
        model_path = str(Path(hf_db).parent / "model.joblib")
    use_model = model_path is not None

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

    # Apply BCD hard filter before column selection (bcd_misp is dropped by _select_output_columns)
    if args.guardrails:
        ranked = _apply_bcd_filter(ranked)
        ranked = ranked.reset_index(drop=True)
        ranked["rank"] = range(1, len(ranked) + 1)

    out_df = _select_output_columns(ranked)

    # Apply guardrail filters
    if args.guardrails:
        n_before = len(out_df)
        vt_mask = out_df["value_trap"] == True if "value_trap" in out_df.columns else pd.Series(False, index=out_df.index)
        dq_mask = out_df["missing_factor_count"] > args.max_missing if "missing_factor_count" in out_df.columns else pd.Series(False, index=out_df.index)
        exclude_mask = vt_mask | dq_mask
        out_df = out_df[~exclude_mask].copy()
        # Re-rank after exclusions
        out_df = out_df.reset_index(drop=True)
        out_df["rank"] = range(1, len(out_df) + 1)
        n_vt = int(vt_mask.sum())
        n_dq = int(dq_mask.sum())
        log.info(
            "Guardrails applied: removed %d stocks (%d value traps, %d poor data quality) → %d remain",
            n_before - len(out_df), n_vt, n_dq, len(out_df),
        )

    # Print top N (sector-capped)
    top_n = min(args.top, len(out_df))
    if args.max_sector_pct < 1.0 and "sector" in out_df.columns:
        # Walk ranked list, enforce max sector_pct × top_n per sector in the display portfolio
        max_per_sector = max(1, int(args.top * args.max_sector_pct))
        sector_counts: dict = {}
        capped_idx = []
        for _, row in out_df.iterrows():
            if len(capped_idx) >= args.top:
                break
            sec = row.get("sector")
            if pd.isna(sec) or sector_counts.get(sec, 0) < max_per_sector:
                capped_idx.append(row.name)
                if not pd.isna(sec):
                    sector_counts[sec] = sector_counts.get(sec, 0) + 1
        top_display = out_df.loc[capped_idx]
    else:
        top_display = out_df.head(top_n)
    # Regime signal and inverse-vol position sizing
    prices_db = os.getenv("PRICES_DB_PATH", "")
    regime_exposure, spy_r12, regime_label = 1.0, float("nan"), "UNKNOWN (no PRICES_DB_PATH)"
    if prices_db and Path(prices_db).exists():
        regime_exposure, spy_r12, regime_label = _compute_regime(prices_db)

    # Compute inverse-vol weights for the top-display portfolio
    top_tickers = top_display["ticker"].tolist() if "ticker" in top_display.columns else []
    max_position_pct = 10.0  # cap any single position at 10% to prevent extreme concentration
    if top_tickers and prices_db and Path(prices_db).exists():
        vols = _compute_stock_vols(prices_db, top_tickers)
        inv_vols = {t: 1.0 / vols[t] for t in top_tickers if t in vols.index and np.isfinite(vols[t]) and vols[t] > 0}
        if inv_vols:
            # Initial weights (pct)
            total_iv = sum(inv_vols.values())
            n_no_vol = len(top_tickers) - len(inv_vols)
            vw_frac = len(inv_vols) / len(top_tickers) if n_no_vol > 0 else 1.0
            ew_weight = (n_no_vol / len(top_tickers) / n_no_vol * 100.0) if n_no_vol > 0 else 0.0
            raw_weights = {
                t: (inv_vols[t] / total_iv) * vw_frac * 100.0 if t in inv_vols else ew_weight
                for t in top_tickers
            }
            # Iterative cap-and-renormalize: cap at max_position_pct, redistribute excess
            weights = dict(raw_weights)
            for _ in range(20):
                capped = {t: min(w, max_position_pct) for t, w in weights.items()}
                total = sum(capped.values())
                if abs(total - 100.0) < 0.01:
                    break
                scale = 100.0 / total
                weights = {t: min(w * scale, max_position_pct) for t, w in capped.items()}
            top_display = top_display.copy()
            top_display["weight_pct"] = top_display["ticker"].map(weights)
        else:
            top_display = top_display.copy()
            top_display["weight_pct"] = 100.0 / len(top_tickers) if top_tickers else float("nan")
    else:
        top_display = top_display.copy()
        top_display["weight_pct"] = 100.0 / len(top_tickers) if top_tickers else float("nan")

    top_display["alloc_pct"] = top_display["weight_pct"] * regime_exposure

    # Propagate weight_pct/alloc_pct back to out_df for CSV (NaN for non-portfolio stocks)
    out_df = out_df.copy()
    out_df["weight_pct"] = float("nan")
    out_df["alloc_pct"] = float("nan")
    if "ticker" in out_df.columns and "ticker" in top_display.columns:
        weight_map = top_display.set_index("ticker")["weight_pct"].to_dict()
        alloc_map = top_display.set_index("ticker")["alloc_pct"].to_dict()
        out_df["weight_pct"] = out_df["ticker"].map(weight_map)
        out_df["alloc_pct"] = out_df["ticker"].map(alloc_map)

    vol_weighted = bool(prices_db and Path(prices_db).exists())
    regime_active = regime_exposure < 1.0
    port_label = _portfolio_label(use_model, vol_weighted, regime_active, top_n)
    metrics = _BACKTEST_METRICS.get(port_label, {})

    cash_pct = (1.0 - regime_exposure) * 100.0
    guardrail_note = " [guardrails on]" if args.guardrails else ""
    print(f"\nFundamentals Alpha — Live Scores ({today})")
    print(f"Portfolio: {port_label}{guardrail_note}")
    print(f"Scoring:   {'XGBoost model' if use_model else 'Composite (value + quality + momentum, sector-neutral)'}")
    print(f"Universe:  {len(out_df)} tickers after filters")
    print(f"Regime:    {regime_label}")
    if cash_pct > 0:
        print(f"           {cash_pct:.0f}% cash — reduce all positions proportionally")
    if metrics:
        print(f"Backtest:  CAGR {metrics['cagr']}  Sharpe {metrics['sharpe']}  "
              f"MaxDD {metrics['max_dd']}  Beta {metrics['beta']}  "
              f"WinRate {metrics['win_rate']}  ({metrics['months']}m)")
    print(f"\nTop {top_n} (sector-capped, inverse-vol weighted):")
    print(_format_display(top_display).to_string(index=False))

    # Write CSV with metadata header
    out_date = today.strftime("%Y%m%d")
    if args.output:
        csv_path = Path(args.output)
    else:
        docs_dir = ROOT / "docs"
        docs_dir.mkdir(exist_ok=True)
        csv_path = docs_dir / f"live_scores_{out_date}_{port_label}.csv"

    _format_display(top_display).to_csv(csv_path, index=False)
    log.info("Wrote %d rows to %s", len(top_display), csv_path)
    print(f"\nWrote {len(top_display)} rows to {csv_path}")

    # Record score snapshot to tracker DB if configured
    tracker_db = os.getenv("IB_TRACKER_DB")
    if tracker_db:
        try:
            from ib_trader.tracker import init_tracker_db, record_score_snapshot
            tracker_conn = init_tracker_db(tracker_db)
            record_score_snapshot(tracker_conn, "fundamentals_alpha", out_df, snapshot_date=today)
            tracker_conn.close()
            print(f"Recorded score snapshot ({len(out_df)} tickers) to tracker DB.")
        except Exception as exc:
            log.warning("Could not record score snapshot to tracker: %s", exc)


if __name__ == "__main__":
    main()
