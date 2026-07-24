#!/usr/bin/env python3
"""
Regime-conditioned follow-up to scripts/test_canslim_rs_updown_ab.py: adding
rs_rating + up_down_vol_ratio unconditionally improved CAGR/Sharpe but made
MaxDD 5.2pp worse and won only 37% of walk-forward folds -- a momentum/
volatility-timing effect that pays off in sharp recoveries and costs you the
rest of the time (docs/canslim_factors_test.md section 6).

This tests whether gating the two factors on a confirmed market uptrend fixes
that: only use composite_augmented (baseline + rs_rating + up_down_vol_ratio)
in months where SPY's close is at/above its 50-day moving average; fall back
to composite_baseline (unconditional, no CANSLIM factors) otherwise. This is
the literal historical version of IBD50's live regime gate
(trade_systems/traderbot/ibd50/regime.py::spy_regime(), SPY >= 50dMA),
generalized across the full backtest period instead of evaluated once at
"now" -- NOT scripts/run_backtest.py::_compute_regime_exposure, which is a
different, symmetric de-risk-on-either-extreme gate, not a trend-confirmation
signal, and doesn't match O'Neil's own "M" semantics as directly.

Three variants compared: baseline (unconditional, no CANSLIM factors),
augmented (unconditional, both factors always on -- from
test_canslim_rs_updown_ab.py), and regime_conditional (factors on only when
SPY confirms an uptrend).

Usage:
    uv run scripts/test_canslim_rs_updown_regime.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import duckdb
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

EXTRA_COLS = ["rs_rating", "up_down_vol_ratio"]


def _compute_monthly_uptrend_regime(prices_db_path: str, ma_window: int) -> pd.Series:
    """SPY close >= its trailing SMA(ma_window), evaluated at each month end.

    Literal historical generalization of
    trade_systems/traderbot/ibd50/regime.py::spy_regime() (SPY >= 50dMA "now"),
    computed for every month end instead of just the latest one. PIT safe:
    only uses SPY data up to and including each month end.
    """
    conn = duckdb.connect(prices_db_path, read_only=True)
    spy = conn.execute(
        "SELECT date, adj_close FROM etf_prices WHERE ticker = 'SPY' ORDER BY date"
    ).df()
    conn.close()

    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.set_index("date").sort_index()
    spy["sma"] = spy["adj_close"].rolling(ma_window, min_periods=ma_window).mean()
    spy["uptrend"] = spy["adj_close"] >= spy["sma"]

    monthly = spy["uptrend"].resample("ME").last().dropna()
    monthly.index.name = "month_end_date"
    return monthly


def _composite(df: pd.DataFrame, extra_cols: list = None) -> pd.Series:
    value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
    value_sign = {c: _VALUE_SIGN[c] for c in value_cols}
    quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
    quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}
    if extra_cols:
        for c in extra_cols:
            if c in df.columns and df[c].notna().any() and c not in quality_cols:
                quality_cols.append(c)
                quality_sign[c] = False
    has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()
    cols = value_cols + quality_cols + ([_MOMENTUM_COL] if has_momentum else [])
    sign_map = {**value_sign, **quality_sign, **({_MOMENTUM_COL: False} if has_momentum else {})}
    log.info("Composite factors (%d): %s", len(cols), cols)
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
    parser = argparse.ArgumentParser(description="Regime-conditioned rs_rating + up_down_vol_ratio test.")
    parser.add_argument("--ma-window", type=int, default=50,
                         help="SPY trailing moving-average window defining the uptrend gate (default 50)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    raw = _load_monthly_pe(hf_db)
    missing = [c for c in EXTRA_COLS if c not in raw.columns]
    if missing:
        log.error("Missing columns %s — run the backfill_canslim_* scripts first.", missing)
        sys.exit(1)
    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]

    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe: %d rows, %d tickers", len(universe), universe["ticker"].nunique())

    universe["composite_baseline"] = _composite(universe)
    universe["composite_augmented"] = _composite(universe, extra_cols=EXTRA_COLS)

    log.info("Computing SPY >= %ddMA monthly uptrend regime ...", args.ma_window)
    regime = _compute_monthly_uptrend_regime(prices_db, args.ma_window)
    log.info("Regime: %d months, %.1f%% uptrend", len(regime), 100 * regime.mean())

    med = pd.to_datetime(universe["month_end_date"])
    regime_lookup = regime.reindex(med.dt.to_period("M").dt.to_timestamp("M")).to_numpy()
    uptrend_mask = pd.Series(regime_lookup, index=universe.index).fillna(False).astype(bool)
    universe["composite_regime_conditional"] = universe["composite_baseline"].where(
        ~uptrend_mask, universe["composite_augmented"]
    )
    log.info("Regime-conditional: %d/%d rows use augmented score (uptrend months)",
              int(uptrend_mask.sum()), len(uptrend_mask))

    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)

    net_returns = {}
    for score_col in ("composite_baseline", "composite_augmented", "composite_regime_conditional"):
        gr = _apply_guardrails(universe, score_col)
        bt = run_monthly_backtest(
            gr, score_col=score_col, tc_bps=10.0, portfolios={"top_n_25": 25},
            sector_col="sector", max_sector_pct=0.25,
        )
        net_returns[score_col] = bt["top_n_25"]["net_return"]

    print("\n" + "=" * 90)
    print(f"REGIME-CONDITIONED rs_rating + up_down_vol_ratio (SPY >= {args.ma_window}dMA gate)")
    print("=" * 90)
    for score_col, label in [
        ("composite_baseline", "baseline (no CANSLIM factors)"),
        ("composite_augmented", "augmented (unconditional)"),
        ("composite_regime_conditional", "regime_conditional (uptrend-only)"),
    ]:
        m = portfolio_metrics(net_returns[score_col], spy_returns=spy_returns)
        print(f"  {label:<38} CAGR {_fmt(m.get('cagr')):>9}  Sharpe {m.get('sharpe', float('nan')):6.3f}  "
              f"MaxDD {_fmt(m.get('max_drawdown')):>9}  WinRate {_fmt(m.get('monthly_win_rate')):>8}  "
              f"Months {m.get('n_months', 0)}")

    all_months = sorted(universe["month_end_date"].unique())
    windows = _fold_windows(all_months, TRAIN_YEARS, TEST_YEARS)
    log.info("%d walk-forward test folds, %s to %s", len(windows), str(windows[0][0])[:10], str(windows[-1][1])[:10])

    print(f"\n{'Fold':<6} {'Test window':<27} {'baseline':>10} {'regime_cond':>12} {'Winner':>10}")
    print("-" * 76)
    fold_results = []
    for i, (start, end) in enumerate(windows, 1):
        base_r = net_returns["composite_baseline"]
        rc_r = net_returns["composite_regime_conditional"]
        base_mask = (base_r.index >= start) & (base_r.index <= end)
        rc_mask = (rc_r.index >= start) & (rc_r.index <= end)
        base_total = float((1 + base_r[base_mask]).prod() - 1) if base_mask.any() else float("nan")
        rc_total = float((1 + rc_r[rc_mask]).prod() - 1) if rc_mask.any() else float("nan")
        winner = ""
        valid = pd.notna(base_total) and pd.notna(rc_total)
        if valid:
            winner = "regime_cond" if rc_total > base_total else "baseline"
        fold_results.append({"fold": i, "start": start, "end": end, "valid": valid,
                              "win": valid and rc_total > base_total})
        print(f"{i:<6} {str(start)[:10]} to {str(end)[:10]}  {_fmt(base_total):>10} {_fmt(rc_total):>12} {winner:>10}")
    print("-" * 76)
    valid_folds = [f for f in fold_results if f["valid"]]
    n_valid = len(valid_folds)
    wins = sum(1 for f in valid_folds if f["win"])
    if n_valid:
        print(f"regime_conditional beats baseline in {wins} / {n_valid} valid folds ({wins / n_valid:.0%})")

    # ── Temporal stability split ────────────────────────────────────────────
    # A true blind holdout isn't possible after already inspecting the full
    # fold table above -- this instead checks whether the fold win rate is
    # spread across the full history or concentrated in a handful of recent
    # standout folds (e.g. 2020-21, 2025-26), which would be a red flag for
    # a regime-specific artifact rather than a durable effect.
    mid = n_valid // 2
    first_half, second_half = valid_folds[:mid], valid_folds[mid:]
    print(f"\nTemporal stability split ({n_valid} valid folds, split at fold #{first_half[-1]['fold']}):")
    for label, half in [("first half ", first_half), ("second half", second_half)]:
        h_wins = sum(1 for f in half if f["win"])
        h_n = len(half)
        span = f"{str(half[0]['start'])[:10]} to {str(half[-1]['end'])[:10]}"
        print(f"  {label}  {span:<25}  {h_wins}/{h_n} folds ({h_wins / h_n:.0%})" if h_n else f"  {label}  no folds")

    print("\nDone.")


if __name__ == "__main__":
    main()
