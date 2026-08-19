"""
ML comps-based fair valuation: predicts a ticker's fair P/E, EV/EBITDA,
P/FCF, and P/S multiple cross-sectionally against sector peers, from
fundamentals already computed in monthly_pe. Additive to goal_pe/goal_low/
goal_high (which compare a ticker to its own multiple history, not peers) — see
features/historic_fundamentals/ml_comps_valuation_plan.md for the full design
rationale and the go/no-go validation gate this model must clear before use.

Public API
----------
build_training_frame()         Cross-sectional (ticker, month) training frame.
fit_quantile_model()            Fit one XGBoost quantile-regression model.
predict_quantiles()             Predict sorted (p10, p50, p90) per row.
walk_forward_validate_quantile()  Time-based walk-forward validation vs. a
                                   naive sector-median baseline.

Design notes
------------
- Target is a same-month cross-sectional log-multiple, not a forward return,
  so there is no forward-looking label to leak and embargo_months defaults to 0
  (unlike historic_fundamentals.model.walk_forward_validate, which embargoes
  12 months for its ret_1y target).
- feature_available_date point-in-time filtering is applied here; the existing
  ret_1y model's training script does not apply this filter today — not
  repeated in this module.
- Peer-median columns (pe_median/evebitda_median/pfcf_median/ps_median from
  sector_stats) are used only for the naive baseline comparison, not as model
  features. The model must earn its keep from ticker-specific fundamentals,
  sector-relative
  z-scored via the reused _apply_sector_zscore, not from being handed the
  answer directly.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from historic_fundamentals.model import _apply_sector_zscore

log = logging.getLogger(__name__)

_MIN_PEERS = 5  # matches historic_fundamentals/sector.py

FEATURE_COLS = [
    "rev_growth_1yr", "rev_cagr_3yr", "rev_cagr_5yr",
    "fcf_growth_1yr", "fcf_cagr_3yr",
    "ttm_gross_margin", "gross_margin_5y_median",
    "ttm_operating_margin", "operating_margin_5y_median", "operating_margin_slope_5y",
    "ttm_fcf_margin", "fcf_margin_5y_median",
    "roa", "roe", "roic", "roa_stability_5y",
    "debt_to_ebitda", "interest_coverage",
    "earnings_quality", "asset_growth", "momentum_12_1",
    "log_market_cap",
]

MULTIPLE_TARGETS = {
    "pe": {"source_col": "pe_ratio", "peer_col": "pe_median"},
    "evebitda": {"source_col": "ev_ebitda", "peer_col": "evebitda_median"},
    "pfcf": {"source_col": "pfcf_ratio", "peer_col": "pfcf_median"},
    "ps": {"source_col": "ps_ratio", "peer_col": "ps_median"},
}

# Multiples that cleared the Phase 3 go/no-go gate. 2026-07-20 run: P/E and
# P/FCF passed all 3 criteria; EV/EBITDA missed the RMSE-improvement bar by
# 0.3pp and was excluded from production scoring until revisited. 2026-07-21
# run: P/S added as a 4th candidate and passed all 3 criteria (+23.6% RMSE
# improvement, the best of the four, 100% fold win rate, 74.7% coverage — see
# ml_comps_valuation_plan.md). Training/scoring scripts default to this list.
#
# 2026-08-19: EV/EBITDA added. That 0.3pp miss was never a modelling shortfall —
# its enterprise-value input counted only the current portion of debt (see
# PLAN_CYCLE_AWARENESS.md Phase 9). With debt fixed and the universe recomputed
# it clears all three criteria decisively: +26.4% RMSE improvement (second-best
# of the four, up from +14.8%), 100% fold win rate, 74.5% coverage. Included on
# the same basis P/E, P/FCF and P/S were — one passing gate run each. The
# 6-month calibration streak gates the separate Phase 9 anchor promotion
# (replacing goal_pe/goal_low/goal_high), not membership in this list.
#
# Note this constant gates four things at once: training, production scoring,
# the streak report, and the tests. Until EV/EBITDA was added here it had no
# active model row, so update_active_ml_model_oos_metrics no-op'd for it and its
# monthly validation result was discarded every month — it could never have
# accumulated the streak its own promotion depends on.
PASSING_MULTIPLES = ["pe", "evebitda", "pfcf", "ps"]

DEFAULT_QUANTILE_PARAMS: dict = {
    "objective": "reg:quantileerror",
    "quantile_alpha": [0.1, 0.5, 0.9],
    "multi_strategy": "one_output_per_tree",
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 20,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_jobs": -1,
    "verbosity": 0,
}


# ── Dataset assembly ──────────────────────────────────────────────────────────

def _load_sector_map(av_conn) -> pd.DataFrame:
    """Current sector per ticker. Same query as historic_fundamentals/sector.py's
    compute_sector_stats — current classification applied retroactively to all
    history is a known, already-accepted limitation, not solved here."""
    return av_conn.execute("""
        SELECT ticker, sector
        FROM company_overview
        QUALIFY fetch_date = MAX(fetch_date) OVER (PARTITION BY ticker)
    """).df()


def build_training_frame(hf_conn, av_conn) -> pd.DataFrame:
    """
    Assemble the cross-sectional training frame: one row per (ticker, month)
    with FEATURE_COLS, peer-median context (for the baseline), and
    target_log_{pe,evebitda,pfcf,ps} columns.
    """
    df = hf_conn.execute("SELECT * FROM monthly_pe ORDER BY ticker, month_end_date").df()
    df["month_end_date"] = pd.to_datetime(df["month_end_date"])
    df["feature_available_date"] = pd.to_datetime(df["feature_available_date"])
    df = df[df["feature_available_date"] <= df["month_end_date"]]

    sector_map = _load_sector_map(av_conn)
    df = df.merge(sector_map, on="ticker", how="left")

    sector_stats = hf_conn.execute("""
        SELECT group_name AS sector, month_end_date, ticker_count,
               pe_median, evebitda_median, pfcf_median, ps_median
        FROM sector_stats
        WHERE group_type = 'sector'
    """).df()
    sector_stats["month_end_date"] = pd.to_datetime(sector_stats["month_end_date"])
    df = df.merge(sector_stats, on=["sector", "month_end_date"], how="left")
    df = df[df["ticker_count"].fillna(0) >= _MIN_PEERS]

    df = df[(df["shares"] > 0) & (df["price"] > 0)]
    df["log_market_cap"] = np.log(df["shares"] * df["price"])

    for name, spec in MULTIPLE_TARGETS.items():
        src = spec["source_col"]
        df[f"target_log_{name}"] = np.where(df[src] > 0, np.log(df[src]), np.nan)

    return df.reset_index(drop=True)


# ── Sector z-score: fit/transform split for production train -> score ─────────
#
# historic_fundamentals.model._apply_sector_zscore fits and transforms in one
# call, which is correct for fold-safe walk-forward validation (train and test
# fold are both in hand at once) but wrong for production: if scoring recomputes
# stats from just the live scoring snapshot (as scripts/score_live.py's existing
# convention does), the model sees features normalized against a completely
# different reference distribution than it was trained on. In practice this
# produced wildly miscalibrated quantile predictions (P/E "high" bands in the
# thousands). fit_sector_zscore_stats()/apply_zscore_stats() persist the
# training-time stats so scoring applies the identical transform.

def fit_sector_zscore_stats(df: pd.DataFrame, feature_cols: list[str], sector_col: str) -> dict:
    stats: dict = {}
    global_medians = df[feature_cols].median()
    global_stds = df[feature_cols].std(ddof=1)
    for col in feature_cols:
        if col not in df.columns:
            continue
        global_med = float(global_medians[col])
        global_std = float(global_stds[col])
        if not global_std or np.isnan(global_std):
            global_std = 1.0
        by_sector = {}
        for sector, grp in df.groupby(sector_col)[col]:
            med = float(grp.median())
            std = float(grp.std(ddof=1))
            if not std or np.isnan(std):
                std = global_std
            by_sector[sector] = (med, std)
        stats[col] = {"by_sector": by_sector, "global": (global_med, global_std)}
    return stats


def apply_zscore_stats(df: pd.DataFrame, feature_cols: list[str], sector_col: str, stats: dict) -> pd.DataFrame:
    df = df.copy()
    for col in feature_cols:
        if col not in df.columns or col not in stats:
            continue
        by_sector = stats[col]["by_sector"]
        global_med, global_std = stats[col]["global"]
        result = df[col].astype(float).copy()
        for sector, grp_idx in df.groupby(sector_col).groups.items():
            med, std = by_sector.get(sector, (global_med, global_std))
            result.loc[grp_idx] = (df.loc[grp_idx, col] - med) / (std or global_std)
        missing_sector = df[sector_col].isna()
        if missing_sector.any():
            result.loc[missing_sector] = (df.loc[missing_sector, col] - global_med) / global_std
        df[col] = result
    return df


# ── Model fit / predict ───────────────────────────────────────────────────────

def fit_quantile_model(
    X: np.ndarray, y: np.ndarray, params: dict | None = None
) -> XGBRegressor:
    model = XGBRegressor(**{**DEFAULT_QUANTILE_PARAMS, **(params or {})})
    model.fit(X, y)
    return model


def predict_quantiles(model: XGBRegressor, X: np.ndarray) -> np.ndarray:
    """Predict (p10, p50, p90) per row, sorted as a safety net against the rare
    case of quantile crossing in the raw model output."""
    preds = np.asarray(model.predict(X)).reshape(len(X), -1)
    return np.sort(preds, axis=1)


# ── Walk-forward validation ───────────────────────────────────────────────────

def _pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, alpha: float) -> float:
    diff = y_true - y_pred
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def walk_forward_validate_quantile(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    peer_col: str,
    sector_col: str = "sector",
    train_years: int = 5,
    test_years: int = 1,
    min_train_months: int = 36,
    quantile_params: dict | None = None,
    embargo_months: int = 0,
) -> dict:
    """
    Time-based walk-forward validation for a single multiple's quantile model,
    against a naive "predict the peer_col sector median" baseline.

    Mirrors the fold-loop skeleton of historic_fundamentals.model.walk_forward_validate
    (same temporal walk, reuses _apply_sector_zscore fold-safely on features only).
    Differs deliberately: embargo_months=0 by default (no forward-looking label
    to leak), and per-fold metrics are RMSE/pinball-loss/coverage in log-multiple
    space rather than IC/ICIR, which measure return-prediction skill, not
    valuation-level accuracy.
    """
    params = {**DEFAULT_QUANTILE_PARAMS, **(quantile_params or {})}

    df = df.copy()
    df["month_end_date"] = pd.to_datetime(df["month_end_date"])
    df = df.sort_values("month_end_date").reset_index(drop=True)

    all_months = sorted(df["month_end_date"].unique())
    if not all_months:
        return {"fold_results": [], "aggregate": {}}

    train_months = train_years * 12
    test_months = test_years * 12

    fold_results = []
    fold_idx = 0
    t = train_months

    while t < len(all_months):
        train_end_month = all_months[t - 1]
        test_start_month = all_months[t]
        train_start_idx = max(0, t - train_months)
        train_window = all_months[train_start_idx:t]

        if len(train_window) < min_train_months:
            t += test_months
            continue

        test_end_idx = min(t + test_months, len(all_months))
        test_window = all_months[t:test_end_idx]
        if not test_window:
            break
        test_end_month = test_window[-1]

        train_mask = df["month_end_date"].isin(set(train_window))
        test_mask = df["month_end_date"].isin(set(test_window))
        train_df = df[train_mask].copy()
        test_df = df[test_mask].copy()

        if embargo_months > 0:
            embargo_cutoff = pd.Timestamp(train_end_month) - pd.DateOffset(months=embargo_months)
            train_df = train_df[train_df["month_end_date"] <= embargo_cutoff].copy()

        train_df = train_df[train_df[target_col].notna()].copy()
        test_df = test_df[test_df[target_col].notna() & test_df[peer_col].notna()].copy()

        if len(train_df) < min_train_months or len(test_df) == 0:
            t += test_months
            continue

        if sector_col in train_df.columns:
            train_df, test_df = _apply_sector_zscore(train_df, test_df, feature_cols, sector_col)

        present_features = [c for c in feature_cols if c in train_df.columns]
        X_train = train_df[present_features].to_numpy(dtype=float, copy=True)
        y_train = train_df[target_col].to_numpy(dtype=float, copy=True)
        X_test = test_df[present_features].to_numpy(dtype=float, copy=True)
        y_test = test_df[target_col].to_numpy(dtype=float, copy=True)
        baseline_pred = np.log(test_df[peer_col].to_numpy(dtype=float, copy=True))

        col_medians = np.nanmedian(X_train, axis=0)
        for j in range(X_train.shape[1]):
            X_train[np.isnan(X_train[:, j]), j] = col_medians[j]
            X_test[np.isnan(X_test[:, j]), j] = col_medians[j]

        # Progress logging: this loop fits 3 quantile models per fold across 36 folds and 4
        # multiples (432 fits), takes tens of minutes, and previously emitted nothing between
        # "training frame loaded" and the final report — so a run could not be distinguished from
        # a hang, and a 50-minute attempt was killed by a timeout with no way to tell how far it
        # had got.
        log.info("  fold %d: train=%d rows test=%d rows (%s)",
                 len(fold_results) + 1, len(train_df), len(test_df), target_col)
        model = fit_quantile_model(X_train, y_train, params)
        preds = predict_quantiles(model, X_test)
        p10, p50, p90 = preds[:, 0], preds[:, 1], preds[:, 2]

        rmse_log = float(np.sqrt(np.mean((y_test - p50) ** 2)))
        baseline_rmse_log = float(np.sqrt(np.mean((y_test - baseline_pred) ** 2)))
        coverage = float(np.mean((y_test >= p10) & (y_test <= p90)))
        below = float(np.mean(y_test < p10))
        above = float(np.mean(y_test > p90))

        fold_results.append({
            "fold": f"fold_{fold_idx:02d}",
            "train_end": str(train_end_month)[:10],
            "test_start": str(test_start_month)[:10],
            "test_end": str(test_end_month)[:10],
            "n_train_obs": len(train_df),
            "n_test_obs": len(test_df),
            "rmse_log": rmse_log,
            "baseline_rmse_log": baseline_rmse_log,
            "pinball_p10": _pinball_loss(y_test, p10, 0.1),
            "pinball_p50": _pinball_loss(y_test, p50, 0.5),
            "pinball_p90": _pinball_loss(y_test, p90, 0.9),
            "coverage_p10_p90": coverage,
            "below_p10_rate": below,
            "above_p90_rate": above,
            "model_wins": bool(rmse_log < baseline_rmse_log),
        })

        fold_idx += 1
        t += test_months

    if not fold_results:
        return {"fold_results": [], "aggregate": {}}

    rmse_vals = [f["rmse_log"] for f in fold_results]
    baseline_vals = [f["baseline_rmse_log"] for f in fold_results]
    mean_rmse = float(np.mean(rmse_vals))
    mean_baseline = float(np.mean(baseline_vals))
    aggregate = {
        "n_folds": len(fold_results),
        "mean_rmse_log": mean_rmse,
        "mean_baseline_rmse_log": mean_baseline,
        "pct_improvement_vs_baseline": float(1 - mean_rmse / mean_baseline) if mean_baseline else np.nan,
        "fold_win_rate": float(np.mean([f["model_wins"] for f in fold_results])),
        "mean_coverage_p10_p90": float(np.mean([f["coverage_p10_p90"] for f in fold_results])),
        "mean_below_p10_rate": float(np.mean([f["below_p10_rate"] for f in fold_results])),
        "mean_above_p90_rate": float(np.mean([f["above_p90_rate"] for f in fold_results])),
    }

    return {"fold_results": fold_results, "aggregate": aggregate}
