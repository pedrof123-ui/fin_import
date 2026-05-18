#!/usr/bin/env python3
"""
Walk-forward validation for the fundamentals-alpha XGBoost model.

Runs time-based walk-forward folds (train on past N years, test on next 1 year),
reports out-of-sample rank IC, ICIR, Newey-West ICIR, hit rate, quintile spread,
and compares against the composite baseline score.

Usage:
    uv run scripts/validate_model.py
    uv run scripts/validate_model.py --train-years 7 --test-years 1
    uv run scripts/validate_model.py --shap --verbose

Environment variables required:
    HF_DB_PATH   path to historic_fundamentals.duckdb
    AV_DB_PATH   path to av_financials.duckdb (for sector join)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from historic_fundamentals.universe import UNIVERSE_DEFAULTS, filter_universe  # noqa: E402
from historic_fundamentals.model import (  # noqa: E402
    DEFAULT_MODEL_PARAMS,
    walk_forward_validate,
    shap_stability,
    compute_oos_metrics,
)
from historic_fundamentals.baselines import (  # noqa: E402
    composite_score,
    compute_factor_ic,
    ic_summary,
    _VALUE_COLS, _VALUE_SIGN,
    _QUALITY_COLS, _QUALITY_SIGN,
    _MOMENTUM_COL,
    BASELINE_FACTORS,
)

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


def _load_data(hf_db: str, av_db: str) -> pd.DataFrame:
    import duckdb
    conn = duckdb.connect(hf_db, read_only=True)
    df = conn.execute("SELECT * FROM monthly_pe ORDER BY ticker, month_end_date").df()
    conn.close()
    df["month_end_date"] = pd.to_datetime(df["month_end_date"])

    try:
        conn = duckdb.connect(av_db, read_only=True)
        overview = conn.execute("SELECT ticker, sector FROM company_overview").df()
        conn.close()
        df = df.merge(overview, on="ticker", how="left")
        log.info("Sector joined: %d rows with sector", df["sector"].notna().sum())
    except Exception as exc:
        log.warning("Could not join sector: %s", exc)

    df["market_cap"] = df["shares"] * df["price"]
    return df


def _compute_composite(df: pd.DataFrame) -> pd.Series:
    value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
    quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
    has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()

    if value_cols and quality_cols and has_momentum:
        cols = value_cols + quality_cols + [_MOMENTUM_COL]
        sign_map = {**{c: _VALUE_SIGN[c] for c in value_cols},
                    **{c: _QUALITY_SIGN[c] for c in quality_cols},
                    _MOMENTUM_COL: False}
    elif value_cols and quality_cols:
        cols = value_cols + quality_cols
        sign_map = {**{c: _VALUE_SIGN[c] for c in value_cols},
                    **{c: _QUALITY_SIGN[c] for c in quality_cols}}
    else:
        cols = value_cols
        sign_map = {c: _VALUE_SIGN[c] for c in value_cols}

    return composite_score(df, cols, sign_map)


def _fmt(v, pct=False, decimals=4):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "   N/A"
    if pct:
        return f"{v * 100:+.2f}%"
    return f"{v:.{decimals}f}"


def _build_report(
    wf: dict,
    baseline_summary: dict,
    single_factor_summaries: dict,
    feature_cols: list[str],
    universe_kwargs: dict,
    train_years: int,
    test_years: int,
    tc_bps: float = 10.0,
) -> str:
    lines = [
        "# Walk-Forward Validation Report\n",
        f"**Features**: {len(feature_cols)}\n",
        f"**Target**: {TARGET_COL}\n",
        f"**Fold structure**: train={train_years}y rolling, test={test_years}y\n",
        f"**Universe**: min_market_cap={universe_kwargs.get('min_market_cap', 'N/A'):.0f}"
        f" | min_price={universe_kwargs.get('min_price', 'N/A'):.2f}\n",
        f"**Embargo**: 12 months (prevents ret_1y label leakage into test window)\n",
        "\n## Aggregate OOS Metrics\n",
        "```",
        f"{'Metric':<22} {'XGBoost':>10} {'Composite':>10}",
        "-" * 46,
    ]

    agg = wf.get("aggregate", {})
    metrics = [
        ("Mean Rank IC",    "mean_rank_ic",     "rank_ic"),
        ("Std Rank IC",     "std_rank_ic",      None),
        ("ICIR",            "mean_rank_icir",   "rank_icir"),
        ("NW-ICIR",         "mean_rank_icir_nw","rank_icir_nw"),
        ("Hit Rate",        "mean_hit_rate",    "hit_rate"),
        ("Mean OOS R²",     "mean_oos_r2",      "oos_r2"),
        ("Q5-Q1 Spread",    "mean_quintile_spread", None),
    ]
    for label, xgb_key, base_key in metrics:
        xgb_val = _fmt(agg.get(xgb_key))
        base_val = _fmt(baseline_summary.get(base_key)) if base_key else "   N/A"
        lines.append(f"{label:<22} {xgb_val:>10} {base_val:>10}")

    lines.append(f"{'N folds':<22} {agg.get('n_folds', 0):>10}")
    lines.append("```\n")

    # Per-fold table
    lines.append("\n## Per-Fold Results\n")
    lines.append("```")
    lines.append(
        f"{'Fold':<10} {'Test period':<24} {'N train':>8} {'N test':>7}"
        f" {'RankIC':>8} {'ICIR':>8} {'NW-ICIR':>9} {'HitRate':>8} {'Q-Spread':>10}"
    )
    lines.append("-" * 100)
    for fold in wf.get("fold_results", []):
        period = f"{fold['test_start'][:7]} – {fold['test_end'][:7]}"
        lines.append(
            f"{fold['fold']:<10} {period:<24} {fold['n_train_obs']:>8,} {fold['n_test_obs']:>7,}"
            f" {_fmt(fold.get('rank_ic')):>8}"
            f" {_fmt(fold.get('rank_icir')):>8}"
            f" {_fmt(fold.get('rank_icir_nw')):>9}"
            f" {_fmt(fold.get('hit_rate')):>8}"
            f" {_fmt(fold.get('quintile_spread'), pct=True):>10}"
        )
    lines.append("```\n")

    # Yearly breakdown
    yearly = wf.get("yearly", pd.DataFrame())
    if not yearly.empty:
        lines.append("\n## Yearly OOS Performance\n")
        lines.append("```")
        lines.append(f"{'Year':>6} {'Mean Rank IC':>14} {'Hit Rate':>10} {'Mean OOS R²':>13}")
        lines.append("-" * 48)
        for yr, row in yearly.iterrows():
            lines.append(
                f"{int(yr):>6} {_fmt(row.get('mean_rank_ic')):>14}"
                f" {_fmt(row.get('mean_hit_rate')):>10}"
                f" {_fmt(row.get('mean_oos_r2')):>13}"
            )
        lines.append("```\n")

    # Baseline factor comparison
    if single_factor_summaries:
        lines.append("\n## Baseline Factor IC Comparison\n")
        lines.append("```")
        lines.append(f"{'Factor':<24} {'Mean IC':>9} {'ICIR':>8} {'NW-ICIR':>9} {'Hit Rate':>10}")
        lines.append("-" * 65)
        for name, s in single_factor_summaries.items():
            lines.append(
                f"{name:<24} {_fmt(s.get('rank_ic')):>9}"
                f" {_fmt(s.get('rank_icir')):>8}"
                f" {_fmt(s.get('rank_icir_nw')):>9}"
                f" {_fmt(s.get('hit_rate')):>10}"
            )
        comp_label = "composite (full-sample)"
        lines.append(
            f"{comp_label:<24} {_fmt(baseline_summary.get('rank_ic')):>9}"
            f" {_fmt(baseline_summary.get('rank_icir')):>8}"
            f" {_fmt(baseline_summary.get('rank_icir_nw')):>9}"
            f" {_fmt(baseline_summary.get('hit_rate')):>10}"
        )
        lines.append("```\n")
        lines.append(
            "> Note: baseline ICs are computed on the full dataset (all dates at once). "
            "These are not OOS metrics and should only be used as a directional reference.\n"
        )

    # Feature importance
    fi = wf.get("feature_importance", pd.DataFrame())
    if not fi.empty and "mean_importance" in fi.columns:
        lines.append("\n## Feature Importance (mean across folds)\n")
        lines.append("```")
        lines.append(f"{'Feature':<40} {'Mean Importance':>16}")
        lines.append("-" * 58)
        for feat, row in fi.head(20).iterrows():
            lines.append(f"{feat:<40} {row['mean_importance']:>16.4f}")
        lines.append("```\n")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward validation for fundamentals-alpha.")
    parser.add_argument("--train-years", type=int, default=5,
                        help="Years of history per training window (default: 5)")
    parser.add_argument("--test-years", type=int, default=1,
                        help="Years per test fold (default: 1)")
    parser.add_argument("--min-cap", type=float, default=None)
    parser.add_argument("--min-price", type=float, default=None)
    parser.add_argument("--shap", action="store_true",
                        help="Run SHAP stability analysis (slower)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))

    log.info("Loading data from %s", hf_db)
    df = _load_data(hf_db, av_db)
    log.info("Loaded %d rows, %d tickers", len(df), df["ticker"].nunique())

    universe_kwargs = {**UNIVERSE_DEFAULTS}
    if args.min_cap is not None:
        universe_kwargs["min_market_cap"] = args.min_cap
    if args.min_price is not None:
        universe_kwargs["min_price"] = args.min_price

    df = filter_universe(df, **universe_kwargs)
    log.info("After universe filter: %d rows, %d tickers", len(df), df["ticker"].nunique())

    # Forward returns via per-ticker shift (memory-efficient, avoids merge OOM)
    log.info("Computing 1-year forward returns ...")
    df = df.sort_values(["ticker", "month_end_date"]).reset_index(drop=True)
    df[TARGET_COL] = df.groupby("ticker")["price"].transform(
        lambda s: s.shift(-12) / s - 1
    )
    n_labeled = df[TARGET_COL].notna().sum()
    log.info("Rows with ret_1y: %d / %d", n_labeled, len(df))

    feature_cols = [c for c in FEATURE_COLS if c in df.columns and df[c].notna().any()]
    log.info("Features available: %d / %d", len(feature_cols), len(FEATURE_COLS))

    sector_col = "sector" if "sector" in df.columns and df["sector"].notna().any() else None

    # Walk-forward validation
    log.info(
        "Running walk-forward validation (train=%dy, test=%dy) ...",
        args.train_years, args.test_years,
    )
    wf = walk_forward_validate(
        df=df,
        feature_cols=feature_cols,
        target_col=TARGET_COL,
        train_years=args.train_years,
        test_years=args.test_years,
        model_params=DEFAULT_MODEL_PARAMS,
        sector_col=sector_col,
        embargo_months=12,
    )
    log.info("Walk-forward complete: %d folds", wf["aggregate"].get("n_folds", 0))

    # Baseline: composite IC on full dataset (directional reference only)
    log.info("Computing composite baseline IC (full dataset) ...")
    df_with_ret = df[df[TARGET_COL].notna()].copy()
    df_with_ret["_composite"] = _compute_composite(df_with_ret)
    composite_ic = compute_factor_ic(df_with_ret, "_composite", TARGET_COL, lower_is_better=False)
    baseline_summary = ic_summary(composite_ic)
    baseline_summary["rank_ic"] = baseline_summary.get("mean_ic")
    baseline_summary["rank_icir"] = baseline_summary.get("icir")
    baseline_summary["rank_icir_nw"] = baseline_summary.get("icir_nw")
    baseline_summary["hit_rate"] = baseline_summary.get("hit_rate")

    # Single-factor baselines
    log.info("Computing single-factor baseline ICs ...")
    single_factor_summaries = {}
    for factor_name, (col, lower_is_better) in BASELINE_FACTORS.items():
        if col not in df_with_ret.columns:
            continue
        ic_s = compute_factor_ic(df_with_ret, col, TARGET_COL, lower_is_better=lower_is_better)
        s = ic_summary(ic_s)
        single_factor_summaries[factor_name] = {
            "rank_ic": s.get("mean_ic"),
            "rank_icir": s.get("icir"),
            "rank_icir_nw": s.get("icir_nw"),
            "hit_rate": s.get("hit_rate"),
        }

    # Print summary
    agg = wf["aggregate"]
    print(f"\n{'=' * 70}")
    print("Walk-Forward Validation — Fundamentals Alpha XGBoost")
    print(f"{'=' * 70}")
    print(f"Folds: {agg.get('n_folds', 0)}  |  Train: {args.train_years}y rolling  |  Test: {args.test_years}y per fold")
    print()
    print(f"{'Metric':<22} {'XGBoost (OOS)':>14} {'Composite (full)':>17}")
    print("-" * 56)
    rows = [
        ("Mean Rank IC",    agg.get("mean_rank_ic"),    baseline_summary.get("rank_ic")),
        ("ICIR",            agg.get("mean_rank_icir"),  baseline_summary.get("rank_icir")),
        ("NW-ICIR",         agg.get("mean_rank_icir_nw"), baseline_summary.get("rank_icir_nw")),
        ("Hit Rate",        agg.get("mean_hit_rate"),   baseline_summary.get("hit_rate")),
        ("Mean OOS R²",     agg.get("mean_oos_r2"),     None),
        ("Q5-Q1 Spread",    agg.get("mean_quintile_spread"), None),
    ]
    for label, xv, bv in rows:
        print(f"{label:<22} {_fmt(xv):>14} {_fmt(bv) if bv is not None else '':>17}")

    print()
    print("Yearly OOS rank IC:")
    yearly = wf.get("yearly", pd.DataFrame())
    if not yearly.empty:
        for yr, row in yearly.iterrows():
            ic_val = _fmt(row.get("mean_rank_ic"))
            hr_val = _fmt(row.get("mean_hit_rate"))
            print(f"  {int(yr)}  IC={ic_val}  HitRate={hr_val}")

    print()
    print("Top features by mean importance:")
    fi = wf.get("feature_importance", pd.DataFrame())
    if not fi.empty and "mean_importance" in fi.columns:
        for feat, row in fi.head(10).iterrows():
            print(f"  {feat:<40} {row['mean_importance']:.4f}")

    # SHAP stability
    shap_df = pd.DataFrame()
    if args.shap:
        log.info("Running SHAP stability analysis ...")
        try:
            shap_df = shap_stability(
                df=df,
                feature_cols=feature_cols,
                target_col=TARGET_COL,
                train_years=args.train_years,
                test_years=args.test_years,
                model_params=DEFAULT_MODEL_PARAMS,
                sector_col=sector_col,
                embargo_months=12,
            )
            if not shap_df.empty:
                print("\nTop features by mean |SHAP| across folds:")
                for feat, row in shap_df.head(10).iterrows():
                    print(f"  {feat:<40} {row['mean_abs_shap']:.4f}")
        except Exception as exc:
            log.warning("SHAP analysis failed: %s", exc)

    # Write markdown report
    docs_dir = ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)
    out_path = docs_dir / "validation_report.md"
    md = _build_report(
        wf=wf,
        baseline_summary=baseline_summary,
        single_factor_summaries=single_factor_summaries,
        feature_cols=feature_cols,
        universe_kwargs=universe_kwargs,
        train_years=args.train_years,
        test_years=args.test_years,
    )

    if not shap_df.empty:
        md += "\n## SHAP Feature Stability\n\n```\n"
        md += f"{'Feature':<40} {'Mean |SHAP|':>12}\n"
        md += "-" * 54 + "\n"
        for feat, row in shap_df.head(20).iterrows():
            md += f"{feat:<40} {row['mean_abs_shap']:>12.4f}\n"
        md += "```\n"

    out_path.write_text(md)
    log.info("Wrote validation report to %s", out_path)
    print(f"\nReport written to {out_path}")


if __name__ == "__main__":
    main()
