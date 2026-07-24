#!/usr/bin/env python3
"""
"Pure CANSLIM" backtest -- literal rank-sum of all 7 CANSLIM sub-factor
columns (C, A x2, N, S x2, L), market-wide (not sector-neutral), no
guardrails, no liquidity filter, financials/real-estate excluded -- same
book-faithful treatment scripts/test_greenblatt_factors.py's section 3 gives
the Magic Formula.

Requires all 7 sub-factors present for a ticker/month (same strict
all-present requirement Greenblatt's pure replication used), so the eligible
universe is smaller than any single factor's coverage -- reported explicitly.

M (market direction) is not included in the per-stock rank-sum -- it's a
portfolio-level regime gate, tested separately if/when a regime-filtered
variant is run (see scripts/run_backtest.py::_compute_regime_exposure).

Usage:
    uv run scripts/test_canslim_pure.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from historic_fundamentals.universe import UNIVERSE_DEFAULTS, filter_universe  # noqa: E402
from historic_fundamentals.backtest import (  # noqa: E402
    run_monthly_backtest,
    portfolio_metrics,
    compute_universe_benchmark,
    load_spy_returns,
)
from scripts.run_backtest import _load_monthly_pe, _join_sector  # noqa: E402

log = logging.getLogger(__name__)

CANSLIM_COLS = [
    "q_earn_accel",        # C
    "earn_cagr_3yr",       # A
    "roe",                 # A
    "pct_off_52wk_high",   # N
    "vol_surge_ratio",     # S
    "up_down_vol_ratio",   # S
    "rs_rating",           # L
]


def _print_metrics(label: str, m: dict) -> None:
    if not m or not m.get("n_months"):
        print(f"  {label}: no data")
        return
    print(
        f"  {label:<28} CAGR {m.get('cagr', float('nan')):+7.2%}  "
        f"Sharpe {m.get('sharpe', float('nan')):6.3f}  "
        f"MaxDD {m.get('max_drawdown', float('nan')):+7.2%}  "
        f"WinRate {m.get('monthly_win_rate', float('nan')):6.1%}  "
        f"Months {m.get('n_months', 0)}"
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    log.info("Loading monthly_pe ...")
    raw = _load_monthly_pe(hf_db)
    missing = [c for c in CANSLIM_COLS if c not in raw.columns]
    if missing:
        log.error("Missing columns %s — run the backfill_canslim_* scripts first.", missing)
        sys.exit(1)

    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]
    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe (standard, financials/real-estate excluded): %d rows, %d tickers",
              len(universe), universe["ticker"].nunique())

    print("\n" + "=" * 78)
    print("PURE CANSLIM REPLICATION — rank-sum(C, A x2, N, S x2, L), market-wide,")
    print("not sector-neutral, financials/real-estate excluded, no guardrails")
    print("=" * 78)

    cs = universe.copy()
    cs = cs[cs[CANSLIM_COLS].notna().all(axis=1)].copy()
    log.info("Pure-CANSLIM universe (all 7 sub-factors present): %d rows, %d tickers",
              len(cs), cs["ticker"].nunique())

    for col in CANSLIM_COLS:
        cs[f"rank_{col}"] = cs.groupby("month_end_date")[col].rank(ascending=False)
    cs["canslim_score"] = -sum(cs[f"rank_{col}"] for col in CANSLIM_COLS)

    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)

    results = run_monthly_backtest(
        cs, score_col="canslim_score", tc_bps=10.0,
        portfolios={"top_n_25": 25, "top_n_30": 30, "top_pct_20": 0.20},
    )
    bench_returns = compute_universe_benchmark(cs)

    print()
    for port_name, bt_df in results.items():
        m = portfolio_metrics(bt_df["net_return"], spy_returns) if not bt_df.empty else {}
        _print_metrics(f"canslim_{port_name}", m)
    if not bench_returns.empty:
        m = portfolio_metrics(bench_returns, spy_returns)
        _print_metrics("universe_ew (canslim univ.)", m)
    if spy_returns is not None and not spy_returns.empty:
        m = portfolio_metrics(spy_returns, spy_returns)
        _print_metrics("SPY", m)

    print("\nDone.")


if __name__ == "__main__":
    main()
