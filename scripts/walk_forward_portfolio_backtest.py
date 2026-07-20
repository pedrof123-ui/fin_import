#!/usr/bin/env python3
"""
True walk-forward portfolio backtest for the fundamentals-alpha model:
periodic retrain (same fold structure as validate_model.py's walk-forward IC
test), fold-safe sector z-scoring, genuinely out-of-sample scores fed into a
real monthly portfolio simulation.

Answers a question neither existing backtest tool answers on its own:
- validate_model.py / walk_forward_validate() gives fold-safe IC/R² but no
  portfolio construction (no CAGR, Sharpe, drawdown).
- run_backtest.py --model gives portfolio CAGR/Sharpe but from ONE static
  model (trained on a recent ~5yr window) scored across up to ~40 years of
  history — a different, less rigorous question, and one where normalization
  choice matters enormously (see historic_fundamentals/model.py's
  fit_sector_zscore_stats() docstring and
  features/historic_fundamentals/fundamentals_alpha_action_plan.md for the
  investigation that led here).

This script retrains per fold and only ever scores test-period rows with a
model that never saw them (or anything after them), using z-score stats fit
on that fold's own training data — no static single model, no era-mismatched
normalization. Output is comparable in spirit to run_backtest.py's report but
restricted to the walk-forward-evaluable date range, with a composite-score
control run over the identical window for a fair comparison.

Usage:
    uv run scripts/walk_forward_portfolio_backtest.py
    uv run scripts/walk_forward_portfolio_backtest.py --train-years 5 --test-years 1

Environment variables:
    HF_DB_PATH      path to historic_fundamentals.duckdb
    AV_DB_PATH      path to av_financials.duckdb
    PRICES_DB_PATH  path to prices.duckdb (for SPY returns)
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
from historic_fundamentals.model import DEFAULT_MODEL_PARAMS, generate_walk_forward_oos_scores  # noqa: E402
from historic_fundamentals.backtest import (  # noqa: E402
    run_monthly_backtest,
    portfolio_metrics,
    compute_universe_benchmark,
    load_spy_returns,
    PORTFOLIO_CONFIGS,
)
from scripts.run_backtest import _load_monthly_pe, _join_sector, _load_historical_adv, _compute_pit_composite_score  # noqa: E402
from scripts.train_model import FEATURE_COLS, TARGET_COL  # noqa: E402

log = logging.getLogger(__name__)


def _fmt(v, pct=True):
    if v is None or pd.isna(v):
        return "   N/A"
    return f"{v * 100:+.2f}%" if pct else f"{v:.4f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="True walk-forward portfolio backtest.")
    parser.add_argument("--train-years", type=int, default=5)
    parser.add_argument("--test-years", type=int, default=1)
    parser.add_argument("--tc-bps", type=float, default=10.0)
    parser.add_argument("--max-sector-pct", type=float, default=0.25)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    log.info("Loading monthly_pe from %s", hf_db)
    raw = _load_monthly_pe(hf_db)
    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]
    log.info("Loaded %d rows, %d tickers", len(raw), raw["ticker"].nunique())

    if Path(prices_db).exists():
        adv_df = _load_historical_adv(prices_db, raw["ticker"].unique().tolist())
        if not adv_df.empty:
            raw["_month"] = pd.to_datetime(raw["month_end_date"]).dt.to_period("M")
            raw = raw.merge(adv_df.rename(columns={"year_month": "_month"}), on=["ticker", "_month"], how="left")
            raw = raw.drop(columns=["_month"])

    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe after filter_universe: %d rows, %d tickers", len(universe), universe["ticker"].nunique())

    universe = universe.sort_values(["ticker", "month_end_date"]).reset_index(drop=True)
    universe[TARGET_COL] = universe.groupby("ticker")["price"].transform(lambda s: s.shift(-12) / s - 1)

    feature_cols = [c for c in FEATURE_COLS if c in universe.columns and universe[c].notna().any()]
    sector_col = "sector" if ("sector" in universe.columns and universe["sector"].notna().any()) else None
    log.info("Training on %d features, sector_col=%s", len(feature_cols), sector_col)

    log.info(
        "Generating walk-forward OOS scores (train=%dy, test=%dy, embargo=12mo) — "
        "this retrains one model per fold, ~35-40 fits ...",
        args.train_years, args.test_years,
    )
    oos = generate_walk_forward_oos_scores(
        universe, feature_cols, TARGET_COL,
        train_years=args.train_years, test_years=args.test_years,
        model_params=DEFAULT_MODEL_PARAMS, sector_col=sector_col, embargo_months=12,
    )
    log.info("OOS scores: %d rows across %d folds, %s to %s",
              len(oos), oos["fold"].nunique() if not oos.empty else 0,
              str(oos["month_end_date"].min())[:10] if not oos.empty else "N/A",
              str(oos["month_end_date"].max())[:10] if not oos.empty else "N/A")

    if oos.empty:
        log.error("No OOS scores generated — insufficient history for a single fold. Aborting.")
        sys.exit(1)

    scored = universe.merge(oos[["ticker", "month_end_date", "oos_score"]], on=["ticker", "month_end_date"], how="inner")
    log.info("Merged scored universe: %d rows (restricted to walk-forward-evaluable date range)", len(scored))

    # Composite-score control run over the IDENTICAL date range for a fair comparison.
    scored["composite_score"] = _compute_pit_composite_score(scored, sector_neutral=False)

    port_configs = PORTFOLIO_CONFIGS
    log.info("Running walk-forward OOS model backtest ...")
    model_bt = run_monthly_backtest(
        scored, score_col="oos_score", tc_bps=args.tc_bps, portfolios=port_configs,
        sector_col=sector_col, max_sector_pct=args.max_sector_pct if args.max_sector_pct < 1.0 else None,
    )
    log.info("Running composite-score control backtest (same date range) ...")
    composite_bt = run_monthly_backtest(
        scored, score_col="composite_score", tc_bps=args.tc_bps, portfolios=port_configs,
        sector_col=sector_col, max_sector_pct=args.max_sector_pct if args.max_sector_pct < 1.0 else None,
    )

    universe_bench = compute_universe_benchmark(scored)
    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)

    rows = []
    for name, bt in {**{f"wf_{k}": v for k, v in model_bt.items()},
                      **{f"composite_{k}": v for k, v in composite_bt.items()}}.items():
        if bt.empty:
            continue
        m = portfolio_metrics(bt["net_return"], spy_returns=spy_returns)
        rows.append({"portfolio": name, **m})
    m = portfolio_metrics(universe_bench, spy_returns=spy_returns)
    rows.append({"portfolio": "universe_ew", **m})
    if spy_returns is not None:
        common = spy_returns.reindex(universe_bench.index).dropna()
        if len(common) > 0:
            m = portfolio_metrics(common)
            rows.append({"portfolio": "SPY", **m})

    result_df = pd.DataFrame(rows).set_index("portfolio")

    lines = [
        "# Walk-Forward Portfolio Backtest — Fundamentals Alpha\n",
        "Periodic retrain (one XGBoost model per fold, never scoring data it was trained on or after),",
        "fold-safe sector z-scoring. Contrast with `docs/backtest_results_model*.md`, which score ONE",
        "static model across up to ~40 years using per-month self-referential normalization — a",
        "different, less rigorous methodology (see historic_fundamentals/model.py's",
        "`generate_walk_forward_oos_scores()` docstring).\n",
        f"**Date range (walk-forward-evaluable)**: {str(oos['month_end_date'].min())[:10]} to {str(oos['month_end_date'].max())[:10]}",
        f" ({oos['fold'].nunique()} folds, train={args.train_years}y / test={args.test_years}y / embargo=12mo)\n",
        f"**TC**: {args.tc_bps:.0f} bps one-way | **Sector cap**: {args.max_sector_pct:.0%}\n",
        "\n## Results (wf_ = walk-forward OOS model, composite_ = same-window composite-score control)\n",
        "```",
        f"{'Portfolio':<20} {'CAGR':>9} {'AnnVol':>9} {'Sharpe':>8} {'MaxDD':>9} {'WinRate':>8} {'Months':>7}",
        "-" * 76,
    ]
    for name, row in result_df.iterrows():
        lines.append(
            f"{name:<20} {_fmt(row.get('cagr')):>9} {_fmt(row.get('ann_vol')):>9}"
            f" {row.get('sharpe', float('nan')):>8.3f} {_fmt(row.get('max_drawdown')):>9}"
            f" {_fmt(row.get('monthly_win_rate')):>8} {int(row.get('n_months', 0)):>7}"
        )
    lines.append("```\n")

    report = "\n".join(lines)
    print(report)
    out_path = ROOT / "docs" / "walk_forward_portfolio_backtest.md"
    out_path.write_text(report)
    log.info("Report written to %s", out_path)


if __name__ == "__main__":
    main()
