#!/usr/bin/env python3
"""
Follow-up gauntlet for rd_intensity_change_3y (docs/capex_rd_factors_test.md), the one
capex/R&D candidate factor that passed the single-split IS/OOS IC-stability check. That
check alone is a lighter bar than any factor this repo has actually promoted or rejected
went through — every one of those (Greenblatt, CANSLIM's regime gate) got a full 30+-fold
walk-forward backtest and a composite-level A/B against the live baseline first
(docs/greenblatt_factors_test.md sections 4-5). This runs the same two tests.

No sign-selection or contrarian-composite step is needed here (unlike
scripts/test_mda_features.py) — Phase 3 already established the direction empirically
(higher rd_intensity_change_3y predicts higher forward returns, stable in both halves of
the sample), so this only tests whether that translates into composite-level, fold-by-fold
value, not whether the sign is right.

1. Augmented composite A/B — the live sector-neutral guardrailed composite, WITH vs WITHOUT
   rd_intensity_change_3y added as an extra quality factor (identical universe/dates).
2. Walk-forward fold stability — same 36 non-overlapping annual test folds as
   walk_forward_portfolio_backtest.py (train=5y/test=1y): does the augmented composite beat
   baseline in most folds, or is the full-period number a few lucky sub-periods?

Metrics include Profit Factor and R-Expectancy alongside Sharpe/MaxDD per the standing rule
(feedback_strategy_metrics).

Nothing here writes to historic_fundamentals/baselines.py or scripts/score_live.py — those
stay untouched until this result is reviewed and logged in docs/.

Usage:
    uv run scripts/test_capex_rd_walkforward.py
"""

from __future__ import annotations

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
TC_BPS = 10.0
EXTRA_QUALITY_COL = "rd_intensity_change_3y"


def _add_change_3y(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["ticker", "month_end_date"])
    df[EXTRA_QUALITY_COL] = df.groupby("ticker")["ttm_rd_intensity"].transform(
        lambda s: s - s.shift(36)
    )
    return df


def _profit_factor_and_expectancy(returns: pd.Series) -> tuple[float, float]:
    """Per the standing metrics rule (feedback_strategy_metrics): always report these
    alongside Sharpe/MaxDD/turnover, not Sharpe alone."""
    r = returns.dropna()
    wins = r[r > 0]
    losses = r[r <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else np.nan
    win_rate = len(wins) / len(r) if len(r) > 0 else np.nan
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.0
    r_exp = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if not np.isnan(win_rate) else np.nan
    return pf, r_exp


def _print_metrics(label: str, m: dict, pf: float = np.nan, r_exp: float = np.nan) -> None:
    if not m or not m.get("n_months"):
        print(f"  {label}: no data")
        return
    print(
        f"  {label:<40} CAGR {m.get('cagr', float('nan')):+7.2%}  "
        f"Sharpe {m.get('sharpe', float('nan')):6.3f}  "
        f"MaxDD {m.get('max_drawdown', float('nan')):+7.2%}  "
        f"PF {pf:6.2f}  R-Exp {r_exp:+7.4f}  "
        f"WinRate {m.get('monthly_win_rate', float('nan')):6.1%}  Months {m.get('n_months', 0)}"
    )


def _composite(df: pd.DataFrame, extra_quality: list = None) -> pd.Series:
    value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
    value_sign = {c: _VALUE_SIGN[c] for c in value_cols}
    quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
    quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}
    if extra_quality:
        for c in extra_quality:
            if c in df.columns and df[c].notna().any() and c not in quality_cols:
                quality_cols.append(c)
                quality_sign[c] = False  # rd_intensity_change_3y: higher is better (Phase 3 result)
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
    if "ttm_rd_intensity" not in raw.columns:
        log.error("ttm_rd_intensity missing — run PLAN_CAPEX_RD_RATIOS.md Phase 1 first.")
        sys.exit(1)
    raw = _add_change_3y(raw)
    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]

    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    universe = universe[universe[EXTRA_QUALITY_COL].notna()].copy()
    log.info("Universe (%s present): %d rows, %d tickers",
              EXTRA_QUALITY_COL, len(universe), universe["ticker"].nunique())

    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)

    universe["composite_baseline"] = _composite(universe)
    universe["composite_augmented"] = _composite(universe, extra_quality=[EXTRA_QUALITY_COL])

    # ── 1. Augmented composite A/B (full period) ─────────────────────────────
    print("\n" + "=" * 92)
    print(f"1. AUGMENTED COMPOSITE A/B — live composite WITH vs WITHOUT {EXTRA_QUALITY_COL}")
    print("   identical universe/dates")
    print("=" * 92)

    net_returns = {}
    for score_col, label in [("composite_baseline", "baseline (current live factors)"),
                              ("composite_augmented", f"augmented (+{EXTRA_QUALITY_COL})")]:
        gr = _apply_guardrails(universe, score_col)
        results = run_monthly_backtest(
            gr, score_col=score_col, tc_bps=TC_BPS, portfolios={"top_n_25": 25},
            sector_col="sector" if "sector" in gr.columns else None, max_sector_pct=0.25,
        )
        bt_df = results.get("top_n_25", pd.DataFrame())
        net_returns[score_col] = bt_df["net_return"] if not bt_df.empty else pd.Series(dtype=float)
        print()
        if bt_df.empty:
            _print_metrics(f"{label} / top_n_25", {})
            continue
        m = portfolio_metrics(bt_df["net_return"], spy_returns)
        pf, r_exp = _profit_factor_and_expectancy(bt_df["net_return"])
        _print_metrics(f"{label} / top_n_25", m, pf, r_exp)
    if spy_returns is not None and not spy_returns.empty:
        m = portfolio_metrics(spy_returns, spy_returns)
        pf, r_exp = _profit_factor_and_expectancy(spy_returns)
        _print_metrics("SPY", m, pf, r_exp)

    # ── 2. Walk-forward fold stability ────────────────────────────────────────
    all_months = sorted(universe["month_end_date"].unique())
    windows = _fold_windows(all_months, TRAIN_YEARS, TEST_YEARS)
    print("\n" + "=" * 92)
    print("2. WALK-FORWARD FOLD STABILITY — composite_baseline vs composite_augmented")
    print(f"   {len(windows)} non-overlapping annual test folds, same structure as walk_forward_portfolio_backtest.py")
    print("=" * 92)
    print(f"\n{'Fold':<6} {'Test window':<25} {'Baseline ret':>13} {'Augmented ret':>14} {'Winner':>10}")
    print("-" * 76)

    fold_rows = []
    wins = 0
    for i, (start, end) in enumerate(windows, 1):
        base_r = net_returns.get("composite_baseline", pd.Series(dtype=float))
        aug_r = net_returns.get("composite_augmented", pd.Series(dtype=float))
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

    eval_start, eval_end = windows[0][0], windows[-1][1]
    print(f"\nAggregate over walk-forward-evaluable range ({str(eval_start)[:10]} to {str(eval_end)[:10]}):")
    for score_col, label in [("composite_baseline", "baseline"), ("composite_augmented", "augmented")]:
        r = net_returns.get(score_col, pd.Series(dtype=float))
        r_eval = r[(r.index >= eval_start) & (r.index <= eval_end)]
        m = portfolio_metrics(r_eval, spy_returns=spy_returns)
        pf, r_exp = _profit_factor_and_expectancy(r_eval)
        _print_metrics(label, m, pf, r_exp)

    print("\nDone.")


if __name__ == "__main__":
    main()
