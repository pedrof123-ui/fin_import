#!/usr/bin/env python3
"""
Walk-forward model validation for the fundamentals-alpha stock-selection model.

This script:
1. Loads monthly_pe from HF_DB_PATH
2. Joins sector from AV_DB_PATH (company_overview)
3. Computes market_cap = shares * price
4. Applies filter_universe() with UNIVERSE_DEFAULTS
5. Computes 12-month forward returns per ticker (price_{t+12} / price_{t} - 1)
6. Runs walk_forward_validate() and shap_stability()
7. Prints results and writes docs/walkforward_results.md

Usage:
    uv run scripts/run_walkforward.py
    uv run scripts/run_walkforward.py --train-years 5 --test-years 1 --min-cap 1e9
    uv run scripts/run_walkforward.py --verbose

Environment variables required:
    HF_DB_PATH    path to historic_fundamentals.duckdb
    AV_DB_PATH    path to av_financials.duckdb (for company_overview sector join)

Optional:
    TARGET_COL    forward return column to use as primary target (default: ret_1y)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from historic_fundamentals.universe import UNIVERSE_DEFAULTS, filter_universe  # noqa: E402
from historic_fundamentals.baselines import compute_forward_returns  # noqa: E402
from historic_fundamentals.model import walk_forward_validate, shap_stability  # noqa: E402

log = logging.getLogger(__name__)

# Feature columns expected in monthly_pe (extend as new features are added)
FEATURE_COLS = [
    "pe_ratio",
    "ps_ratio",
    "fcf_yield",
    "ev_ebitda",
    "dividend_yield",
    "earnings_yield",
    "roa",
    "roe",
    "roic",
    "pbv",
    "ptbv",
    "pe_rolling_5yr_median",
    "pfcf_ratio",
    "pfcf_rolling_5yr_median",
    "ps_rolling_5yr_median",
    "ev_ebitda_rolling_5yr_median",
    "roa_rolling_5yr_median",
    "roic_rolling_5yr_median",
    # Phase 3 features (present if pe.py has been updated)
    "gross_margin_5y_median",
    "gross_margin_slope_5y",
    "operating_margin_5y_median",
    "operating_margin_change_3y",
    "operating_margin_slope_5y",
    "fcf_margin_5y_median",
    "fcf_margin_change_3y",
    "roa_stability_5y",
    "debt_to_ebitda",
    "interest_coverage",
    "momentum_12_1",
    "earnings_yield_norm",
    "fcf_yield_norm",
    "ev_ebitda_norm",
    "ps_ratio_norm",
]

RETURN_HORIZONS = {"ret_1y": 12}


def _load_monthly_pe(hf_db_path: str) -> pd.DataFrame:
    import duckdb
    conn = duckdb.connect(hf_db_path, read_only=True)
    df = conn.execute("SELECT * FROM monthly_pe ORDER BY ticker, month_end_date").df()
    conn.close()
    df["month_end_date"] = pd.to_datetime(df["month_end_date"])
    return df


def _join_sector(df: pd.DataFrame, av_db_path: str) -> pd.DataFrame:
    """Join sector from company_overview if not already present."""
    if "sector" in df.columns and df["sector"].notna().any():
        return df
    try:
        import duckdb
        conn = duckdb.connect(av_db_path, read_only=True)
        overview = conn.execute("SELECT symbol AS ticker, sector FROM company_overview").df()
        conn.close()
        df = df.merge(overview, on="ticker", how="left")
        log.info("Joined sector: %d rows with sector", df["sector"].notna().sum())
    except Exception as exc:
        log.warning("Could not join sector from AV_DB_PATH: %s", exc)
    return df


def _select_present_features(df: pd.DataFrame, candidates: list[str]) -> list[str]:
    """Return only feature columns that exist and have some non-NaN values."""
    present = []
    for col in candidates:
        if col in df.columns and df[col].notna().any():
            present.append(col)
    return present


def _format_fold_table(fold_results: list[dict]) -> str:
    rows = []
    header = (
        f"{'Fold':<8} {'Train end':<12} {'Test start':<12} {'Test end':<12} "
        f"{'OOS R2':>8} {'IC':>7} {'ICIR':>7} {'ICIR_NW':>8} {'Hit%':>6} {'N_OBS':>7}"
    )
    rows.append(header)
    rows.append("-" * len(header))
    for f in fold_results:
        def _fmt(v):
            return f"{v:.4f}" if v is not None and v == v else "   nan"
        rows.append(
            f"{f['fold']:<8} {f['train_end']:<12} {f['test_start']:<12} {f['test_end']:<12} "
            f"{_fmt(f['oos_r2']):>8} {_fmt(f['rank_ic']):>7} {_fmt(f['rank_icir']):>7} "
            f"{_fmt(f['rank_icir_nw']):>8} {_fmt(f['hit_rate']):>6} {f['n_test_obs']:>7}"
        )
    return "\n".join(rows)


def _format_yearly_table(yearly: pd.DataFrame) -> str:
    if yearly.empty:
        return "(no yearly data)"
    lines = [f"{'Year':<6} {'Mean IC':>9} {'N Folds':>8}"]
    lines.append("-" * 28)
    for yr, row in yearly.iterrows():
        ic = row.get("mean_rank_ic", float("nan"))
        n = int(row.get("n_folds", 0))
        ic_str = f"{ic:.4f}" if ic == ic else "   nan"
        lines.append(f"{int(yr):<6} {ic_str:>9} {n:>8}")
    return "\n".join(lines)


def _format_feature_importance(fi: pd.DataFrame, top_n: int = 20) -> str:
    if fi.empty:
        return "(no feature importance data)"
    lines = [f"{'Feature':<40} {'Mean Importance':>16}"]
    lines.append("-" * 60)
    shown = fi.head(top_n)
    for feat, row in shown.iterrows():
        imp = row.get("mean_importance", float("nan"))
        imp_str = f"{imp:.6f}" if imp == imp else "     nan"
        lines.append(f"{str(feat):<40} {imp_str:>16}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Walk-forward XGBoost validation on the fundamentals-alpha universe."
    )
    parser.add_argument("--train-years", type=int, default=5, help="Training years per fold (default: 5)")
    parser.add_argument("--test-years", type=int, default=1, help="Test years per fold (default: 1)")
    parser.add_argument("--min-train-months", type=int, default=36, help="Min training months to include fold (default: 36)")
    parser.add_argument("--min-cap", type=float, default=None, help="Minimum market cap override")
    parser.add_argument("--min-price", type=float, default=None, help="Minimum price override")
    parser.add_argument("--target", type=str, default="ret_1y", help="Target column (default: ret_1y)")
    parser.add_argument("--no-sector-filter", action="store_true", help="Disable sector filter")
    parser.add_argument("--no-shap", action="store_true", help="Skip SHAP stability computation (faster)")
    parser.add_argument("--verbose", action="store_true", help="Show DEBUG-level logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    target_col = os.getenv("TARGET_COL", args.target)

    if not Path(hf_db).exists():
        log.error("HF_DB_PATH not found: %s", hf_db)
        sys.exit(1)

    log.info("Loading monthly_pe from %s", hf_db)
    raw = _load_monthly_pe(hf_db)
    log.info("Loaded %d rows, %d tickers", len(raw), raw["ticker"].nunique())

    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]

    universe_kwargs = {**UNIVERSE_DEFAULTS}
    if args.min_cap is not None:
        universe_kwargs["min_market_cap"] = args.min_cap
    if args.min_price is not None:
        universe_kwargs["min_price"] = args.min_price
    if args.no_sector_filter:
        universe_kwargs["require_sector"] = False

    log.info("Applying universe filters: %s", universe_kwargs)
    universe = filter_universe(raw, **universe_kwargs)
    log.info("Universe: %d rows, %d tickers", len(universe), universe["ticker"].nunique())

    log.info("Computing forward returns ...")
    df = compute_forward_returns(universe, RETURN_HORIZONS)
    valid_ret = df[target_col].notna().sum() if target_col in df.columns else 0
    log.info("  %s: %d valid rows", target_col, valid_ret)

    if valid_ret < 100:
        log.error("Too few valid forward-return rows (%d) for %s. Aborting.", valid_ret, target_col)
        sys.exit(1)

    feature_cols = _select_present_features(df, FEATURE_COLS)
    log.info("Using %d features: %s", len(feature_cols), feature_cols)

    sector_col = "sector" if ("sector" in df.columns and df["sector"].notna().any()) else None

    log.info(
        "Running walk-forward validation: train_years=%d test_years=%d min_train_months=%d",
        args.train_years, args.test_years, args.min_train_months,
    )
    result = walk_forward_validate(
        df,
        feature_cols=feature_cols,
        target_col=target_col,
        train_years=args.train_years,
        test_years=args.test_years,
        min_train_months=args.min_train_months,
        sector_col=sector_col,
    )

    n_folds = len(result["fold_results"])
    log.info("Walk-forward complete: %d folds", n_folds)

    shap_df = pd.DataFrame()
    if not args.no_shap and n_folds > 0:
        log.info("Computing SHAP stability ...")
        shap_df = shap_stability(
            df,
            feature_cols=feature_cols,
            target_col=target_col,
            train_years=args.train_years,
            test_years=args.test_years,
            sector_col=sector_col,
        )
        log.info("SHAP stability complete")

    # ── Print to console ──────────────────────────────────────────────────────
    print(f"\n{'=' * 72}")
    print(f"Walk-Forward Validation — {target_col} (primary target)")
    print(f"{'=' * 72}")
    print(f"Universe: {universe['ticker'].nunique()} tickers | {n_folds} folds")
    print(f"Filters: min_market_cap={universe_kwargs['min_market_cap']:.0f}  min_price={universe_kwargs['min_price']:.2f}")
    print(f"Train: {args.train_years}yr  Test: {args.test_years}yr  Min train months: {args.min_train_months}")
    print()

    print("Per-fold OOS results (these are out-of-sample only):")
    print(_format_fold_table(result["fold_results"]))
    print()

    agg = result["aggregate"]
    if agg:
        print("Aggregate OOS metrics:")
        for k, v in agg.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.4f}")
            else:
                print(f"  {k}: {v}")
    print()

    print("Yearly mean IC:")
    print(_format_yearly_table(result["yearly"]))
    print()

    print(f"Top-20 feature importance (mean across folds):")
    print(_format_feature_importance(result["feature_importance"]))
    print()

    if not shap_df.empty:
        print("SHAP stability (mean |SHAP| per feature):")
        shap_top = shap_df[["mean_abs_shap"]].head(20)
        for feat, row in shap_top.iterrows():
            print(f"  {str(feat):<40} {row['mean_abs_shap']:.6f}")
        print()

    # ── Write markdown report ─────────────────────────────────────────────────
    docs_dir = ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)
    out_path = docs_dir / "walkforward_results.md"

    lines = [
        "# Walk-Forward Validation Results\n",
        f"**Target**: `{target_col}` (primary — `ret_1y` per ACTION_PLAN.md Phase 5)\n",
        f"**Universe**: {universe['ticker'].nunique()} tickers | "
        f"min_market_cap={universe_kwargs['min_market_cap']:.0f} | "
        f"min_price={universe_kwargs['min_price']:.2f}\n",
        f"**Folds**: {n_folds} | Train {args.train_years}yr | Test {args.test_years}yr\n",
        "\n> In-sample R² (`ins_r2_diagnostic`) is shown for diagnostic purposes only."
        " It is NOT final evidence. OOS metrics are the valid results.\n",
        "\n## Per-Fold OOS Results\n",
        "```",
        _format_fold_table(result["fold_results"]),
        "```\n",
        "\n## Aggregate OOS Metrics\n",
        "```",
    ]
    for k, v in agg.items():
        if isinstance(v, float):
            lines.append(f"{k}: {v:.4f}")
        else:
            lines.append(f"{k}: {v}")
    lines += [
        "```\n",
        "\n## Yearly Mean IC\n",
        "```",
        _format_yearly_table(result["yearly"]),
        "```\n",
        "\n## Feature Importance (Top 20)\n",
        "```",
        _format_feature_importance(result["feature_importance"]),
        "```\n",
    ]

    if not shap_df.empty:
        lines += [
            "\n## SHAP Stability (Top 20)\n",
            "```",
        ]
        for feat, row in shap_df[["mean_abs_shap"]].head(20).iterrows():
            lines.append(f"{str(feat):<40} {row['mean_abs_shap']:.6f}")
        lines += ["```\n"]

    out_path.write_text("\n".join(lines))
    log.info("Wrote results to %s", out_path)


if __name__ == "__main__":
    main()
