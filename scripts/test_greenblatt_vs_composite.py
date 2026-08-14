#!/usr/bin/env python3
"""
The decision-relevant comparison: constrained pure-Greenblatt (rank-sum of
ebit_ev_yield + greenblatt_roc, guardrails + 25% sector cap + $5M ADV
liquidity filter — the investable version from
scripts/test_greenblatt_pure_robust.py) vs. the platform's actual live
composite baseline (historic_fundamentals/baselines.py _VALUE_COLS/
_QUALITY_COLS + momentum, sector-neutral, same guardrails/sector cap/
liquidity filter), fold by fold over the same 36-fold walk-forward
structure used throughout this test series.

Both scores are computed on the IDENTICAL universe (same liquidity filter
applied before either score is built) so this is a true apples-to-apples
comparison, not two differently-filtered backtests compared after the fact.

Usage:
    uv run scripts/test_greenblatt_vs_composite.py
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
    compute_universe_benchmark,
    load_spy_returns,
)
from scripts.run_backtest import (  # noqa: E402
    _load_monthly_pe,
    _join_sector,
    _apply_guardrails,
    _load_historical_adv,
)

log = logging.getLogger(__name__)

TRAIN_YEARS = 5
TEST_YEARS = 1


def _composite_baseline(df: pd.DataFrame) -> pd.Series:
    value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
    value_sign = {c: _VALUE_SIGN[c] for c in value_cols}
    quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
    quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}
    has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()
    cols = value_cols + quality_cols + ([_MOMENTUM_COL] if has_momentum else [])
    sign_map = {**value_sign, **quality_sign, **({_MOMENTUM_COL: False} if has_momentum else {})}
    log.info("Composite baseline factors (%d): %s", len(cols), cols)
    return composite_score(df, cols, sign_map, sector_neutral=True)


def _fold_windows(all_months: list, train_years: int, test_years: int) -> list[tuple]:
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

    tickers_all = raw["ticker"].unique().tolist()
    if Path(prices_db).exists():
        adv_df = _load_historical_adv(prices_db, tickers_all)
        if not adv_df.empty:
            raw["_month"] = pd.to_datetime(raw["month_end_date"]).dt.to_period("M")
            raw = raw.merge(adv_df.rename(columns={"year_month": "_month"}), on=["ticker", "_month"], how="left")
            raw = raw.drop(columns=["_month"])

    # Identical universe for both scores (liquidity filter applied here, once)
    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe: %d rows, %d tickers", len(universe), universe["ticker"].nunique())

    universe["composite_baseline"] = _composite_baseline(universe)

    gb_mask = universe["ebit_ev_yield"].notna() & universe["greenblatt_roc"].notna()
    universe["rank_ey"] = universe.groupby("month_end_date")["ebit_ev_yield"].rank(ascending=False)
    universe["rank_roc"] = universe.groupby("month_end_date")["greenblatt_roc"].rank(ascending=False)
    universe["greenblatt_score"] = -(universe["rank_ey"] + universe["rank_roc"])
    universe.loc[~gb_mask, "greenblatt_score"] = float("nan")

    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)

    returns = {}
    for score_col, label in [("composite_baseline", "composite"), ("greenblatt_score", "greenblatt")]:
        gr = _apply_guardrails(universe, score_col)
        bt = run_monthly_backtest(
            gr, score_col=score_col, tc_bps=10.0, portfolios={"top_n_25": 25},
            sector_col="sector", max_sector_pct=0.25,
        )
        returns[label] = bt["top_n_25"]["net_return"]

    print("\n" + "=" * 90)
    print("CONSTRAINED PURE-GREENBLATT vs. LIVE COMPOSITE BASELINE")
    print("Identical universe (incl. $5M ADV liquidity filter), both guardrailed, 25% sector cap, top_n_25")
    print("=" * 90)
    for label, r in returns.items():
        m = portfolio_metrics(r, spy_returns=spy_returns)
        print(f"  {label:<12} CAGR {_fmt(m.get('cagr')):>9}  Sharpe {m.get('sharpe', float('nan')):6.3f}  "
              f"MaxDD {_fmt(m.get('max_drawdown')):>9}  WinRate {_fmt(m.get('monthly_win_rate')):>8}  "
              f"Months {m.get('n_months', 0)}")

    all_months = sorted(universe["month_end_date"].unique())
    windows = _fold_windows(all_months, TRAIN_YEARS, TEST_YEARS)
    log.info("%d walk-forward test folds, %s to %s", len(windows), str(windows[0][0])[:10], str(windows[-1][1])[:10])

    print(f"\n{'Fold':<6} {'Test window':<27} {'composite':>12} {'greenblatt':>12} {'Winner':>10}")
    print("-" * 76)
    wins = 0
    n_valid = 0
    for i, (start, end) in enumerate(windows, 1):
        comp_r = returns["composite"]
        gb_r = returns["greenblatt"]
        comp_mask = (comp_r.index >= start) & (comp_r.index <= end)
        gb_mask2 = (gb_r.index >= start) & (gb_r.index <= end)
        comp_total = float((1 + comp_r[comp_mask]).prod() - 1) if comp_mask.any() else float("nan")
        gb_total = float((1 + gb_r[gb_mask2]).prod() - 1) if gb_mask2.any() else float("nan")
        winner = ""
        if pd.notna(comp_total) and pd.notna(gb_total):
            n_valid += 1
            winner = "greenblatt" if gb_total > comp_total else "composite"
            wins += 1 if gb_total > comp_total else 0
        print(f"{i:<6} {str(start)[:10]} to {str(end)[:10]}  {_fmt(comp_total):>12} {_fmt(gb_total):>12} {winner:>10}")
    print("-" * 76)
    if n_valid:
        print(f"greenblatt beats composite in {wins} / {n_valid} valid folds ({wins / n_valid:.0%})")

    eval_start, eval_end = windows[0][0], windows[-1][1]
    print(f"\nAggregate over walk-forward-evaluable range ({str(eval_start)[:10]} to {str(eval_end)[:10]}):")
    for label, r in returns.items():
        r_eval = r[(r.index >= eval_start) & (r.index <= eval_end)]
        m = portfolio_metrics(r_eval, spy_returns=spy_returns)
        print(f"  {label:<12} CAGR {_fmt(m.get('cagr')):>9}  Sharpe {m.get('sharpe', float('nan')):6.3f}  "
              f"MaxDD {_fmt(m.get('max_drawdown')):>9}  WinRate {_fmt(m.get('monthly_win_rate')):>8}  "
              f"Months {m.get('n_months', 0)}")

    print("\nDone.")


if __name__ == "__main__":
    main()
