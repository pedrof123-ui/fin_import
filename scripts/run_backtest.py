#!/usr/bin/env python3
"""
True monthly portfolio backtest for the fundamentals-alpha model.

This script:
1. Loads monthly_pe from HF_DB_PATH
2. Joins sector from AV_DB_PATH (company_overview)
3. Computes market_cap = shares * price
4. Applies filter_universe() with UNIVERSE_DEFAULTS
5. Computes composite baseline score POINT-IN-TIME (only data with
   feature_available_date <= month_end_date used at each rebalance date)
6. Loads SPY monthly returns via PRICES_DB_PATH
7. Runs run_monthly_backtest() for all 4 portfolio configs
8. Prints summary table and writes docs/backtest_results.md

Usage:
    uv run scripts/run_backtest.py
    uv run scripts/run_backtest.py --tc-bps 20 --min-cap 1e9
    uv run scripts/run_backtest.py --help

Environment variables required:
    HF_DB_PATH      path to historic_fundamentals.duckdb
    AV_DB_PATH      path to av_financials.duckdb (for company_overview sector join)
    PRICES_DB_PATH  path to prices.duckdb (for SPY returns)
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
from historic_fundamentals.baselines import (  # noqa: E402
    composite_score,
    _VALUE_COLS,
    _VALUE_SIGN,
    _QUALITY_COLS,
    _QUALITY_SIGN,
    _MOMENTUM_COL,
    BASELINE_FACTORS,
)
from historic_fundamentals.backtest import (  # noqa: E402
    run_monthly_backtest,
    portfolio_metrics,
    compute_universe_benchmark,
    load_spy_returns,
    PORTFOLIO_CONFIGS,
)
from historic_fundamentals.model import _apply_sector_zscore  # noqa: E402

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
]

log = logging.getLogger(__name__)


def _load_monthly_pe(hf_db_path: str) -> pd.DataFrame:
    import duckdb
    conn = duckdb.connect(hf_db_path, read_only=True)
    df = conn.execute("SELECT * FROM monthly_pe ORDER BY ticker, month_end_date").df()
    conn.close()
    df["month_end_date"] = pd.to_datetime(df["month_end_date"])
    if "feature_available_date" in df.columns:
        df["feature_available_date"] = pd.to_datetime(df["feature_available_date"])
    return df


def _join_sector(df: pd.DataFrame, av_db_path: str) -> pd.DataFrame:
    """Join sector from company_overview if not already present."""
    if "sector" in df.columns and df["sector"].notna().any():
        return df
    try:
        import duckdb
        conn = duckdb.connect(av_db_path, read_only=True)
        overview = conn.execute("SELECT ticker, sector FROM company_overview").df()
        conn.close()
        df = df.merge(overview, on="ticker", how="left")
        log.info("Joined sector: %d rows with sector", df["sector"].notna().sum())
    except Exception as exc:
        log.warning("Could not join sector from AV_DB_PATH: %s", exc)
    return df


def _compute_pit_composite_score(df: pd.DataFrame) -> pd.Series:
    """
    Compute composite baseline score POINT-IN-TIME.

    At each month_end_date, score only uses fundamentals data with
    feature_available_date <= month_end_date. The monthly_pe table already
    enforces this at the row level (each row's fundamentals come from the most
    recent filing available before month_end_date), so composite_score() applied
    per month is inherently PIT.

    The composite uses the value+quality score when quality columns are present,
    falling back to value_composite, then the raw available factors.
    """
    value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
    value_sign = {c: _VALUE_SIGN[c] for c in value_cols}

    quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
    quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}

    has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()

    if value_cols and quality_cols and has_momentum:
        cols = value_cols + quality_cols + [_MOMENTUM_COL]
        sign_map = {**value_sign, **quality_sign, _MOMENTUM_COL: False}
        log.info("Using value+quality+momentum composite (%d factors)", len(cols))
    elif value_cols and quality_cols:
        cols = value_cols + quality_cols
        sign_map = {**value_sign, **quality_sign}
        log.info("Using value+quality composite (%d factors)", len(cols))
    elif value_cols:
        cols = value_cols
        sign_map = value_sign
        log.info("Using value_composite (%d factors)", len(cols))
    else:
        log.warning("No composite factor columns found — using constant score 0.")
        return pd.Series(0.0, index=df.index)

    return composite_score(df, cols, sign_map)


def _score_with_model(universe: pd.DataFrame, model) -> pd.Series:
    """
    Score each monthly cross-section with the XGBoost model.

    Applies sector-relative z-scores per month (using only that month's
    cross-section) before predicting, matching the transformation used
    at training time. PIT-safe: each month's z-scores use only that
    month's stocks.
    """
    feature_names = model.get_booster().feature_names
    sector_col = "sector"
    scores = {}

    for date, month_df in universe.groupby("month_end_date"):
        present = [f for f in feature_names if f in month_df.columns]

        if sector_col in month_df.columns and month_df[sector_col].notna().any():
            scored_df, _ = _apply_sector_zscore(
                month_df, month_df.head(0), present, sector_col
            )
        else:
            scored_df = month_df.copy()

        X = scored_df[present].copy()
        for f in feature_names:
            if f not in X.columns:
                X[f] = np.nan
        X = X[feature_names]
        X = X.fillna(X.median())
        preds = model.predict(X.to_numpy(dtype=float))
        for idx, val in zip(month_df.index, preds):
            scores[idx] = val

    return pd.Series(scores)


def _format_metrics_row(name: str, m: dict) -> str:
    def _f(v, pct=False):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "    N/A"
        if pct:
            return f"{v * 100:+6.2f}%"
        return f"{v:7.4f}"

    return (
        f"{name:<18} "
        f"{_f(m.get('cagr'), pct=True):>8} "
        f"{_f(m.get('ann_vol'), pct=True):>8} "
        f"{_f(m.get('sharpe')):>8} "
        f"{_f(m.get('sortino')):>8} "
        f"{_f(m.get('max_drawdown'), pct=True):>9} "
        f"{_f(m.get('beta')):>7} "
        f"{_f(m.get('alpha'), pct=True):>8} "
        f"{_f(m.get('info_ratio')):>8} "
        f"{m.get('monthly_win_rate', float('nan')) * 100:>7.1f}% "
        f"{m.get('n_months', 0):>7}"
    )


def _build_md_report(
    universe_n: str,
    universe_filters: dict,
    all_metrics: dict[str, dict],
    bt_results: dict,
    tc_bps: float,
    factor_bt_results: dict | None = None,
    rebalance_label: str = "monthly",
    model_bt_results: dict | None = None,
) -> str:
    rebalance_months = 3 if rebalance_label == "quarterly" else 1
    lines = [
        "# Backtest Results\n",
        f"**Universe**: {universe_n}\n",
        f"**Filters**: min_market_cap={universe_filters.get('min_market_cap', 'N/A'):.0f} "
        f"| min_price={universe_filters.get('min_price', 'N/A'):.2f}\n",
        f"**TC**: {tc_bps:.0f} bps one-way per trade\n",
        f"**Signal**: composite baseline (value+quality+momentum where available)\n",
        f"**Rebalancing**: {rebalance_label} equal-weight, non-overlapping {rebalance_months}-month returns\n",
        "\n## Portfolio weighting\n",
        "All portfolios in this backtest are equal-weight (each selected stock receives "
        "an equal allocation at each monthly rebalance).\n",
        "Capped-weight portfolios (e.g., max 5% per position) are deferred to Phase 7 "
        "risk diagnostics, where position concentration limits are configured as guardrails.\n",
        "\n## Performance Summary\n",
        "```",
        f"{'Portfolio':<18} {'CAGR':>8} {'AnnVol':>8} {'Sharpe':>8} {'Sortino':>8} "
        f"{'MaxDD':>9} {'Beta':>7} {'Alpha':>8} {'IR':>8} {'WinRate':>8} {'Months':>7}",
        "-" * 110,
    ]

    for name, m in all_metrics.items():
        if m:
            lines.append(_format_metrics_row(name, m))

    lines.append("```\n")

    # Turnover and TC drag
    lines.append("\n## Turnover and Transaction Cost Drag\n")
    lines.append("```")
    lines.append(f"{'Portfolio':<18} {'Avg Turnover':>14} {'Avg TC/Mo (bps)':>17} {'Ann TC Drag':>13}")
    lines.append("-" * 70)
    for port_name, bt_df in bt_results.items():
        if bt_df.empty:
            continue
        avg_to = bt_df["turnover"].mean()
        avg_tc = bt_df["tc_cost"].mean() * 1e4
        ann_drag = bt_df["tc_cost"].mean() * 12 * 1e4
        lines.append(f"{port_name:<18} {avg_to:>14.1%} {avg_tc:>17.2f} {ann_drag:>13.2f}")
    lines.append("```\n")

    # Single-factor baseline turnover
    if factor_bt_results:
        lines.append("\n## Single-Factor Baseline Turnover\n")
        lines.append("```")
        lines.append(f"{'Factor (top20%)':<18} {'Avg Turnover':>14} {'Avg TC/Mo (bps)':>17} {'Ann TC Drag':>13}")
        lines.append("-" * 70)
        for factor_name, factor_bt_df in factor_bt_results.items():
            if factor_bt_df.empty:
                continue
            avg_to = factor_bt_df["turnover"].mean()
            avg_tc = factor_bt_df["tc_cost"].mean() * 1e4
            ann_drag = factor_bt_df["tc_cost"].mean() * 12 * 1e4
            lines.append(f"{'f_' + factor_name:<18} {avg_to:>14.1%} {avg_tc:>17.2f} {ann_drag:>13.2f}")
        lines.append("```\n")

    # XGBoost model turnover
    if model_bt_results:
        lines.append("\n## XGBoost Model Turnover\n")
        lines.append("```")
        lines.append(f"{'Portfolio':<18} {'Avg Turnover':>14} {'Avg TC/Mo (bps)':>17} {'Ann TC Drag':>13}")
        lines.append("-" * 70)
        for port_name, bt_df in model_bt_results.items():
            if bt_df.empty:
                continue
            avg_to = bt_df["turnover"].mean()
            avg_tc = bt_df["tc_cost"].mean() * 1e4
            ann_drag = bt_df["tc_cost"].mean() * 12 * 1e4
            lines.append(f"{port_name:<18} {avg_to:>14.1%} {avg_tc:>17.2f} {ann_drag:>13.2f}")
        lines.append("```\n")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run true monthly portfolio backtest on the fundamentals-alpha universe."
    )
    parser.add_argument("--tc-bps", type=float, default=10.0,
                        help="One-way transaction cost in basis points (default: 10)")
    parser.add_argument("--min-cap", type=float, default=None,
                        help="Minimum market cap override (default: 1e9)")
    parser.add_argument("--min-price", type=float, default=None,
                        help="Minimum price override (default: 5.0)")
    parser.add_argument("--no-sector-filter", action="store_true",
                        help="Disable sector filter")
    parser.add_argument("--quarterly", action="store_true",
                        help="Rebalance quarterly instead of monthly; saves to backtest_results_quarterly.md")
    parser.add_argument("--model", action="store_true",
                        help="Also run backtest using XGBoost model scores (requires data/model.joblib)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show DEBUG-level logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

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
    log.info("Universe: %d rows, %d tickers after filtering",
             len(universe), universe["ticker"].nunique())

    # Compute composite score POINT-IN-TIME
    log.info("Computing composite score ...")
    universe = universe.copy()
    universe["composite_score"] = _compute_pit_composite_score(universe)

    # Optionally compute XGBoost model scores per month
    model_loaded = None
    if args.model:
        import joblib
        model_path = ROOT / "data" / "model.joblib"
        if model_path.exists():
            log.info("Loading XGBoost model from %s", model_path)
            model_loaded = joblib.load(model_path)
            log.info("Scoring universe with XGBoost model (per-month sector z-scores) ...")
            universe["model_score"] = _score_with_model(universe, model_loaded)
            log.info("Model scores computed for %d rows", universe["model_score"].notna().sum())
        else:
            log.warning("--model requested but %s not found — skipping model backtest", model_path)

    # Load SPY returns
    spy_returns = None
    if Path(prices_db).exists():
        log.info("Loading SPY returns from %s", prices_db)
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
            log.info("SPY returns: %d months (%s to %s)",
                     len(spy_returns), spy_returns.index.min().date(),
                     spy_returns.index.max().date())
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)
    else:
        log.warning("PRICES_DB_PATH not found (%s) — SPY benchmark skipped", prices_db)

    # Run backtest
    rebalance_months = 3 if args.quarterly else 1
    rebalance_label = "quarterly" if args.quarterly else "monthly"
    port_configs = (
        {"top_n_25": 25, "top_n_10": 10, "top_pct_20": 0.20}
        if args.quarterly else PORTFOLIO_CONFIGS
    )
    log.info("Running %s backtest (tc_bps=%.0f) ...", rebalance_label, args.tc_bps)
    bt_results = run_monthly_backtest(
        universe,
        score_col="composite_score",
        tc_bps=args.tc_bps,
        portfolios=port_configs,
        rebalance_months=rebalance_months,
    )

    # XGBoost model backtest (if model loaded)
    model_bt_results: dict[str, pd.DataFrame] = {}
    if model_loaded is not None and "model_score" in universe.columns:
        log.info("Running XGBoost model %s backtest ...", rebalance_label)
        raw_model_results = run_monthly_backtest(
            universe,
            score_col="model_score",
            tc_bps=args.tc_bps,
            portfolios=port_configs,
            rebalance_months=rebalance_months,
        )
        # Prefix names with "xgb_" to distinguish from composite in the table
        model_bt_results = {f"xgb_{k}": v for k, v in raw_model_results.items()}

    # Single-factor baselines: run top_pct_20 for each factor in BASELINE_FACTORS
    log.info("Running single-factor baseline backtests (top 20% only) ...")
    factor_bt_results: dict[str, pd.DataFrame] = {}
    for factor_name, (col, lower_is_better) in BASELINE_FACTORS.items():
        if col not in universe.columns:
            log.info("Factor %s: column '%s' not in universe — skipping", factor_name, col)
            continue
        df_factor = universe.copy()
        score_col_name = f"score_{factor_name}"
        df_factor[score_col_name] = -df_factor[col] if lower_is_better else df_factor[col]
        factor_result = run_monthly_backtest(
            df_factor,
            score_col=score_col_name,
            tc_bps=args.tc_bps,
            portfolios={"top_pct_20": 0.20},
            rebalance_months=rebalance_months,
        )
        factor_bt_results[factor_name] = factor_result.get("top_pct_20", pd.DataFrame())
        log.info("Factor %s: %d months", factor_name,
                 len(factor_bt_results[factor_name]))

    # Universe benchmark
    log.info("Computing universe equal-weight benchmark ...")
    bench_returns = compute_universe_benchmark(universe)

    # Compute metrics
    all_metrics: dict[str, dict] = {}

    for port_name, bt_df in bt_results.items():
        if bt_df.empty:
            log.warning("No returns for portfolio: %s", port_name)
            all_metrics[port_name] = {}
            continue
        net_rets = bt_df["net_return"]
        m = portfolio_metrics(net_rets, spy_returns=spy_returns)
        all_metrics[port_name] = m

    if len(bench_returns) >= 2:
        all_metrics["universe_ew"] = portfolio_metrics(bench_returns, spy_returns=spy_returns)

    if spy_returns is not None and len(spy_returns) >= 2:
        all_metrics["SPY"] = portfolio_metrics(spy_returns)

    for factor_name, factor_bt_df in factor_bt_results.items():
        if factor_bt_df.empty:
            all_metrics[f"f_{factor_name}"] = {}
            continue
        net_rets = factor_bt_df["net_return"]
        all_metrics[f"f_{factor_name}"] = portfolio_metrics(net_rets, spy_returns=spy_returns)

    for port_name, bt_df in model_bt_results.items():
        if bt_df.empty:
            all_metrics[port_name] = {}
            continue
        all_metrics[port_name] = portfolio_metrics(bt_df["net_return"], spy_returns=spy_returns)

    # Print summary table
    header = (
        f"{'Portfolio':<18} {'CAGR':>8} {'AnnVol':>8} {'Sharpe':>8} {'Sortino':>8} "
        f"{'MaxDD':>9} {'Beta':>7} {'Alpha':>8} {'IR':>8} {'WinRate':>8} {'Months':>7}"
    )
    sep = "-" * 110
    print(f"\n{'=' * 110}")
    print(f"True {rebalance_label.capitalize()} Portfolio Backtest — Fundamentals Alpha")
    print(f"{'=' * 110}")
    print(header)
    print(sep)
    for name, m in all_metrics.items():
        if m:
            print(_format_metrics_row(name, m))

    print()
    print("Turnover and TC Drag:")
    print(f"{'Portfolio':<18} {'Avg Turnover':>14} {'Avg TC/Mo (bps)':>17} {'Ann TC Drag (bps)':>18}")
    print("-" * 75)
    for port_name, bt_df in bt_results.items():
        if not isinstance(bt_df, pd.DataFrame) or bt_df.empty:
            continue
        avg_to = bt_df["turnover"].mean()
        avg_tc_bps = bt_df["tc_cost"].mean() * 1e4
        ann_drag_bps = bt_df["tc_cost"].mean() * 12 * 1e4
        print(f"{port_name:<18} {avg_to:>14.1%} {avg_tc_bps:>17.2f} {ann_drag_bps:>18.2f}")

    # Write markdown report
    docs_dir = ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)
    suffix = ("_model" if args.model else "") + ("_quarterly" if args.quarterly else "")
    out_path = docs_dir / f"backtest_results{suffix}.md"
    md = _build_md_report(
        universe_n=f"{universe['ticker'].nunique()} tickers",
        universe_filters=universe_kwargs,
        all_metrics=all_metrics,
        bt_results=bt_results,
        tc_bps=args.tc_bps,
        factor_bt_results=factor_bt_results,
        rebalance_label=rebalance_label,
        model_bt_results=model_bt_results if model_bt_results else None,
    )
    out_path.write_text(md)
    log.info("Wrote results to %s", out_path)


if __name__ == "__main__":
    main()
