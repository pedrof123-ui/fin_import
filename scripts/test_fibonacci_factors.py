#!/usr/bin/env python3
"""
Evaluate the Fibonacci-retracement factors (fib_618_proximity, fib_in_golden_zone)
backfilled by scripts/backfill_fibonacci_factors.py.

Same methodology as scripts/test_greenblatt_factors.py / test_canslim_factors.py:

1. IC test — Spearman rank IC of fib_618_proximity / fib_in_golden_zone vs
   forward returns at 1m/3m/6m/1y (a pullback/bounce entry signal is meant to
   play out over weeks-to-months, unlike a fundamentals factor's 6-12m horizon,
   so shorter windows are tested here too), both market-wide and restricted to
   stocks in an established uptrend (above_200dma == 1) -- textbook Fibonacci
   usage says the tool only means something applied within a trend.

2. Quintile spread (ret_3m, ret_1y) — Q1 (best/closest to golden zone) minus
   Q5 (worst), mean monthly.

3. "Pure Fibonacci" backtest — rank stocks purely by fib_618_proximity,
   monthly rebalance, top 25/30/20%, restricted to the uptrend universe (the
   only universe in which a retracement entry is a coherent idea to begin
   with). No guardrails, no fundamentals.

4. Augmented composite A/B — the platform's live sector-neutral guardrailed
   composite with fib_618_proximity added as a quality/timing factor, A/B'd
   against the same composite computed in this same run WITHOUT it
   (apples-to-apples on identical data/universe/date range).

Nothing here writes to _VALUE_COLS/_QUALITY_COLS/BASELINE_FACTORS in
historic_fundamentals/baselines.py -- those stay untouched until these results
are reviewed and a decision is made to promote the factor.

Usage:
    uv run scripts/test_fibonacci_factors.py
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
    compute_forward_returns,
    compute_factor_ic,
    ic_summary,
    quintile_returns,
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
from scripts.run_backtest import _load_monthly_pe, _join_sector, _apply_guardrails  # noqa: E402

log = logging.getLogger(__name__)

FACTORS = {
    "fib_618_proximity": ("fib_618_proximity", False),
    "fib_in_golden_zone": ("fib_in_golden_zone", False),
}


def _ic_table(df: pd.DataFrame, factors: dict, return_col: str) -> pd.DataFrame:
    rows = []
    for name, (col, lower_is_better) in factors.items():
        if col not in df.columns or df[col].notna().sum() == 0:
            continue
        ic_series = compute_factor_ic(df, col, return_col, lower_is_better=lower_is_better)
        summ = ic_summary(ic_series)
        rows.append({
            "factor": name, "column": col,
            "mean_ic": summ["mean_ic"], "icir": summ["icir"], "icir_nw": summ["icir_nw"],
            "hit_rate": summ["hit_rate"], "t_stat": summ["t_stat"], "n_months": summ["n_months"],
        })
    return pd.DataFrame(rows)


def _print_metrics(label: str, m: dict) -> None:
    if not m or not m.get("n_months"):
        print(f"  {label}: no data")
        return
    print(
        f"  {label:<40} CAGR {m.get('cagr', float('nan')):+7.2%}  "
        f"Sharpe {m.get('sharpe', float('nan')):6.3f}  "
        f"MaxDD {m.get('max_drawdown', float('nan')):+7.2%}  "
        f"WinRate {m.get('monthly_win_rate', float('nan')):6.1%}  "
        f"Months {m.get('n_months', 0)}"
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
                quality_sign[c] = False
    has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()
    cols = value_cols + quality_cols + ([_MOMENTUM_COL] if has_momentum else [])
    sign_map = {**value_sign, **quality_sign, **({_MOMENTUM_COL: False} if has_momentum else {})}
    log.info("Composite factors (%d): %s", len(cols), cols)
    return composite_score(df, cols, sign_map, sector_neutral=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    log.info("Loading monthly_pe ...")
    raw = _load_monthly_pe(hf_db)
    missing = [c for c in ("fib_618_proximity", "fib_in_golden_zone", "above_200dma") if c not in raw.columns]
    if missing:
        log.error("%s not found — run scripts/backfill_fibonacci_factors.py first.", missing)
        sys.exit(1)
    log.info("Loaded %d rows, %d tickers", len(raw), raw["ticker"].nunique())

    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]

    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe: %d rows, %d tickers", len(universe), universe["ticker"].nunique())

    log.info("Computing forward returns (ret_1m, ret_3m, ret_6m, ret_1y) ...")
    universe = compute_forward_returns(universe, {"ret_1m": 1, "ret_3m": 3, "ret_6m": 6, "ret_1y": 12})

    uptrend = universe[universe["above_200dma"] == 1.0].copy()
    log.info("Uptrend subset (above_200dma): %d rows, %d tickers", len(uptrend), uptrend["ticker"].nunique())

    # ── 1. IC test ──────────────────────────────────────────────────────────
    print("\n" + "=" * 84)
    print("1. IC TEST — fib_618_proximity / fib_in_golden_zone vs forward returns")
    print("=" * 84)
    for return_col in ("ret_1m", "ret_3m", "ret_6m", "ret_1y"):
        print(f"\n-- forward return: {return_col} -- market-wide")
        print(_ic_table(universe, FACTORS, return_col).to_string(index=False, float_format=lambda x: f"{x:.4f}"))
        print(f"-- forward return: {return_col} -- uptrend only (above_200dma)")
        print(_ic_table(uptrend, FACTORS, return_col).to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # ── 2. Quintile spread ──────────────────────────────────────────────────
    print("\n" + "=" * 84)
    print("2. QUINTILE SPREAD — Q1 (best) minus Q5 (worst), mean monthly")
    print("=" * 84)
    for return_col in ("ret_3m", "ret_1y"):
        print(f"\n-- forward return: {return_col} --")
        for label, df in [("market-wide", universe), ("uptrend-only", uptrend)]:
            for name, (col, lower_is_better) in FACTORS.items():
                qr = quintile_returns(df, col, return_col, lower_is_better=lower_is_better)
                if qr.empty:
                    continue
                print(f"  [{label:<12}] {name:<20} Q1={qr['Q1'].mean():+7.2%}  Q5={qr['Q5'].mean():+7.2%}  "
                      f"spread={qr['spread'].mean():+7.2%}  months={len(qr)}")

    # ── 3. Pure Fibonacci replication backtest (uptrend universe only) ──────
    print("\n" + "=" * 84)
    print("3. PURE FIBONACCI BACKTEST — rank by fib_618_proximity, uptrend universe only,")
    print("   no guardrails, no fundamentals — textbook 'buy the golden-ratio pullback'")
    print("=" * 84)

    fib = uptrend[uptrend["fib_618_proximity"].notna()].copy()
    log.info("Pure-Fibonacci universe: %d rows, %d tickers", len(fib), fib["ticker"].nunique())

    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)

    fib_results = run_monthly_backtest(
        fib, score_col="fib_618_proximity", tc_bps=10.0,
        portfolios={"top_n_25": 25, "top_n_30": 30, "top_pct_20": 0.20},
    )
    bench_returns = compute_universe_benchmark(fib)

    print()
    for port_name, bt_df in fib_results.items():
        m = portfolio_metrics(bt_df["net_return"], spy_returns) if not bt_df.empty else {}
        _print_metrics(f"fibonacci_{port_name}", m)
    if not bench_returns.empty:
        m = portfolio_metrics(bench_returns, spy_returns)
        _print_metrics("universe_ew (uptrend univ.)", m)
    if spy_returns is not None and not spy_returns.empty:
        m = portfolio_metrics(spy_returns, spy_returns)
        _print_metrics("SPY", m)

    # ── 4. Augmented composite A/B ──────────────────────────────────────────
    print("\n" + "=" * 84)
    print("4. AUGMENTED COMPOSITE A/B — live sector-neutral guardrailed composite")
    print("   WITH vs WITHOUT fib_618_proximity added (identical universe/dates)")
    print("=" * 84)

    universe_ab = universe.copy()
    universe_ab["composite_baseline"] = _composite(universe_ab)
    universe_ab["composite_augmented"] = _composite(universe_ab, extra_quality=["fib_618_proximity"])

    for score_col, label in [("composite_baseline", "baseline (current live factors)"),
                              ("composite_augmented", "augmented (+fib_618_proximity)")]:
        gr = _apply_guardrails(universe_ab, score_col)
        results = run_monthly_backtest(
            gr, score_col=score_col, tc_bps=10.0,
            portfolios={"top_n_25": 25},
            sector_col="sector" if "sector" in gr.columns else None,
            max_sector_pct=0.25,
        )
        print()
        for port_name, bt_df in results.items():
            m = portfolio_metrics(bt_df["net_return"], spy_returns) if not bt_df.empty else {}
            _print_metrics(f"{label} / {port_name}", m)

    print("\nDone.")


if __name__ == "__main__":
    main()
