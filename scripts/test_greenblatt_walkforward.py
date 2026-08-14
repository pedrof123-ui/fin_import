#!/usr/bin/env python3
"""
Out-of-sample stability check for the Greenblatt-augmented composite
(scripts/test_greenblatt_factors.py section 4 showed a full-period Sharpe
gain of 0.952 -> 0.996 from adding ebit_ev_yield + greenblatt_roc; this
checks whether that gain is fold-consistent or an artifact of one lucky
sub-period, the way the PEGY-ratio experiment's promising in-sample IC
failed to hold up walk-forward).

The composite score has no fitted parameters (pure cross-sectional rank/
z-score each month), so there is no train/test leakage risk to guard
against the way there is for the XGBoost model — "out-of-sample" here
means period-consistency: using the SAME fold boundaries as
scripts/walk_forward_portfolio_backtest.py (train_years=5, test_years=1,
non-overlapping annual test windows walking across the full history),
does composite_augmented beat composite_baseline in most folds, or does
the full-period average hide a few outsized wins?

Usage:
    uv run scripts/test_greenblatt_walkforward.py
"""

from __future__ import annotations

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
from historic_fundamentals.baselines import (  # noqa: E402
    composite_score,
    _VALUE_COLS,
    _VALUE_SIGN,
    _QUALITY_COLS,
    _QUALITY_SIGN,
    _MOMENTUM_COL,
)
from historic_fundamentals.backtest import (  # noqa: E402
    run_monthly_backtest,
    portfolio_metrics,
    load_spy_returns,
)
from scripts.run_backtest import _load_monthly_pe, _join_sector, _apply_guardrails  # noqa: E402

log = logging.getLogger(__name__)

TRAIN_YEARS = 5
TEST_YEARS = 1


def _composite(df: pd.DataFrame, extra_value: list = None, extra_quality: list = None) -> pd.Series:
    value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
    value_sign = {c: _VALUE_SIGN[c] for c in value_cols}
    quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
    quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}
    if extra_value:
        for c in extra_value:
            if c in df.columns and df[c].notna().any() and c not in value_cols:
                value_cols.append(c)
                value_sign[c] = False
    if extra_quality:
        for c in extra_quality:
            if c in df.columns and df[c].notna().any() and c not in quality_cols:
                quality_cols.append(c)
                quality_sign[c] = False
    has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()
    cols = value_cols + quality_cols + ([_MOMENTUM_COL] if has_momentum else [])
    sign_map = {**value_sign, **quality_sign, **({_MOMENTUM_COL: False} if has_momentum else {})}
    log.info("Composite factors (%d): %s", len(cols), cols)
    return composite_score(df, cols, sign_map, sector_neutral=True)


def _fold_windows(all_months: list, train_years: int, test_years: int) -> list[tuple]:
    """Same walk-forward fold structure as generate_walk_forward_oos_scores(),
    without any model fitting: just the (test_start, test_end) date boundaries."""
    train_months = train_years * 12
    test_months = test_years * 12
    windows = []
    t = train_months
    while t < len(all_months):
        test_end_idx = min(t + test_months, len(all_months))
        test_window = all_months[t:test_end_idx]
        if test_window:
            windows.append((test_window[0], test_window[-1]))
        t += test_months
    return windows


def _fmt(v, pct=True):
    if v is None or pd.isna(v):
        return "  N/A"
    return f"{v * 100:+.2f}%" if pct else f"{v:.4f}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    raw = _load_monthly_pe(hf_db)
    if "ebit_ev_yield" not in raw.columns or "greenblatt_roc" not in raw.columns:
        log.error("Run scripts/backfill_greenblatt_factors.py first.")
        sys.exit(1)
    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]

    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe: %d rows, %d tickers", len(universe), universe["ticker"].nunique())

    universe["composite_baseline"] = _composite(universe)
    universe["composite_augmented"] = _composite(
        universe, extra_value=["ebit_ev_yield"], extra_quality=["greenblatt_roc"]
    )

    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)

    net_returns = {}
    for score_col in ("composite_baseline", "composite_augmented"):
        gr = _apply_guardrails(universe, score_col)
        bt = run_monthly_backtest(
            gr, score_col=score_col, tc_bps=10.0, portfolios={"top_n_25": 25},
            sector_col="sector", max_sector_pct=0.25,
        )
        net_returns[score_col] = bt["top_n_25"]["net_return"]

    all_months = sorted(universe["month_end_date"].unique())
    windows = _fold_windows(all_months, TRAIN_YEARS, TEST_YEARS)
    log.info("%d walk-forward test folds (train=%dy, test=%dy), %s to %s",
              len(windows), TRAIN_YEARS, TEST_YEARS, str(windows[0][0])[:10], str(windows[-1][1])[:10])

    print("\n" + "=" * 90)
    print(f"5. WALK-FORWARD FOLD STABILITY — composite_baseline vs composite_augmented")
    print(f"   {len(windows)} non-overlapping annual test folds, same structure as walk_forward_portfolio_backtest.py")
    print("=" * 90)
    print(f"\n{'Fold':<6} {'Test window':<25} {'Baseline ret':>13} {'Augmented ret':>14} {'Winner':>10}")
    print("-" * 76)

    fold_rows = []
    wins = 0
    for i, (start, end) in enumerate(windows, 1):
        base_r = net_returns["composite_baseline"]
        aug_r = net_returns["composite_augmented"]
        base_mask = (base_r.index >= start) & (base_r.index <= end)
        aug_mask = (aug_r.index >= start) & (aug_r.index <= end)
        base_total = float((1 + base_r[base_mask]).prod() - 1) if base_mask.any() else float("nan")
        aug_total = float((1 + aug_r[aug_mask]).prod() - 1) if aug_mask.any() else float("nan")
        winner = ""
        if pd.notna(base_total) and pd.notna(aug_total):
            winner = "augmented" if aug_total > base_total else "baseline"
            wins += 1 if aug_total > base_total else 0
        fold_rows.append({"fold": i, "start": start, "end": end, "base": base_total, "aug": aug_total})
        print(f"{i:<6} {str(start)[:10]} to {str(end)[:10]}  {_fmt(base_total):>13} {_fmt(aug_total):>14} {winner:>10}")

    n_valid = sum(1 for r in fold_rows if pd.notna(r["base"]) and pd.notna(r["aug"]))
    print("-" * 76)
    print(f"Augmented beats baseline in {wins} / {n_valid} folds ({wins / n_valid:.0%})" if n_valid else "No valid folds")

    # Aggregate over the walk-forward-evaluable date range only (first fold start to last fold end)
    eval_start, eval_end = windows[0][0], windows[-1][1]
    print(f"\nAggregate over walk-forward-evaluable range ({str(eval_start)[:10]} to {str(eval_end)[:10]}):")
    for score_col, label in [("composite_baseline", "baseline"), ("composite_augmented", "augmented")]:
        r = net_returns[score_col]
        r_eval = r[(r.index >= eval_start) & (r.index <= eval_end)]
        m = portfolio_metrics(r_eval, spy_returns=spy_returns)
        print(f"  {label:<12} CAGR {_fmt(m.get('cagr')):>9}  Sharpe {m.get('sharpe', float('nan')):6.3f}  "
              f"MaxDD {_fmt(m.get('max_drawdown')):>9}  WinRate {_fmt(m.get('monthly_win_rate')):>8}  "
              f"Months {m.get('n_months', 0)}")

    print("\nDone.")


if __name__ == "__main__":
    main()
