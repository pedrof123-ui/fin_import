#!/usr/bin/env python3
"""
Stress-test the "pure Greenblatt" magic-formula replication
(scripts/test_greenblatt_factors.py section 3: rank-sum of ebit_ev_yield +
greenblatt_roc, no other machinery) two ways, before trusting its raw
19.79% CAGR / 1.127 Sharpe headline number:

1. Walk-forward fold stability — same 36-fold structure (train=5y, test=1y)
   used to catch the augmented composite's coin-flip fold win rate. Does the
   pure replication's full-period average hide the same instability, or is
   it a genuinely more consistent edge?

2. Apply it to the same rules the live process actually plays by: guardrails
   (excludes value traps / poor data quality), 25% sector cap, and a
   liquidity filter (min $5M avg dollar volume) — none of which the raw
   19.79% number had. What's left once it can't concentrate in one sector,
   pick illiquid names, or hold deteriorating "value trap" stocks?

Usage:
    uv run scripts/test_greenblatt_pure_robust.py
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


def _print_fold_table(label: str, base_r: pd.Series, alt_r: pd.Series, base_label: str, alt_label: str, windows: list) -> None:
    print(f"\n{label}")
    print(f"{'Fold':<6} {'Test window':<27} {base_label:>14} {alt_label:>14} {'Winner':>10}")
    print("-" * 76)
    wins = 0
    n_valid = 0
    for i, (start, end) in enumerate(windows, 1):
        base_mask = (base_r.index >= start) & (base_r.index <= end)
        alt_mask = (alt_r.index >= start) & (alt_r.index <= end)
        base_total = float((1 + base_r[base_mask]).prod() - 1) if base_mask.any() else float("nan")
        alt_total = float((1 + alt_r[alt_mask]).prod() - 1) if alt_mask.any() else float("nan")
        winner = ""
        if pd.notna(base_total) and pd.notna(alt_total):
            n_valid += 1
            winner = alt_label if alt_total > base_total else base_label
            wins += 1 if alt_total > base_total else 0
        print(f"{i:<6} {str(start)[:10]} to {str(end)[:10]}  {_fmt(base_total):>14} {_fmt(alt_total):>14} {winner:>10}")
    print("-" * 76)
    if n_valid:
        print(f"{alt_label} beats {base_label} in {wins} / {n_valid} valid folds ({wins / n_valid:.0%})")
    else:
        print("No valid folds")


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

    # Liquidity: load ADV before filter_universe so the constrained run can apply it
    tickers_all = raw["ticker"].unique().tolist()
    if Path(prices_db).exists():
        log.info("Loading historical ADV for %d tickers ...", len(tickers_all))
        adv_df = _load_historical_adv(prices_db, tickers_all)
        if not adv_df.empty:
            raw["_month"] = pd.to_datetime(raw["month_end_date"]).dt.to_period("M")
            raw = raw.merge(adv_df.rename(columns={"year_month": "_month"}), on=["ticker", "_month"], how="left")
            raw = raw.drop(columns=["_month"])
            log.info("ADV joined: %d/%d rows have avg_dollar_volume", raw["avg_dollar_volume"].notna().sum(), len(raw))
    else:
        log.warning("PRICES_DB_PATH not found — liquidity filter will be skipped in the 'constrained' run.")

    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe: %d rows, %d tickers", len(universe), universe["ticker"].nunique())

    gb = universe[universe["ebit_ev_yield"].notna() & universe["greenblatt_roc"].notna()].copy()
    gb["rank_ey"] = gb.groupby("month_end_date")["ebit_ev_yield"].rank(ascending=False)
    gb["rank_roc"] = gb.groupby("month_end_date")["greenblatt_roc"].rank(ascending=False)
    gb["greenblatt_score"] = -(gb["rank_ey"] + gb["rank_roc"])
    log.info("Pure-Greenblatt universe: %d rows, %d tickers (both factors present)", len(gb), gb["ticker"].nunique())

    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)

    # ── Run 1: unconstrained (as originally tested) ─────────────────────────
    unconstrained_bt = run_monthly_backtest(
        gb, score_col="greenblatt_score", tc_bps=10.0, portfolios={"top_n_25": 25},
    )
    unconstrained_returns = unconstrained_bt["top_n_25"]["net_return"]

    # ── Run 2: constrained — guardrails + 25% sector cap + liquidity filter ─
    gb_constrained = gb.copy()
    if "avg_dollar_volume" in gb_constrained.columns:
        n_before = len(gb_constrained)
        gb_constrained = gb_constrained[
            gb_constrained["avg_dollar_volume"].isna() | (gb_constrained["avg_dollar_volume"] >= 5_000_000)
        ].copy()
        log.info("Liquidity filter (>= $5M ADV): %d -> %d rows", n_before, len(gb_constrained))
    gb_constrained = _apply_guardrails(gb_constrained, "greenblatt_score")
    constrained_bt = run_monthly_backtest(
        gb_constrained, score_col="greenblatt_score", tc_bps=10.0, portfolios={"top_n_25": 25},
        sector_col="sector", max_sector_pct=0.25,
    )
    constrained_returns = constrained_bt["top_n_25"]["net_return"]

    print("\n" + "=" * 90)
    print("PURE GREENBLATT — unconstrained vs. constrained (guardrails + 25% sector cap + $5M ADV liquidity)")
    print("=" * 90)
    for label, r in [("unconstrained", unconstrained_returns), ("constrained", constrained_returns)]:
        m = portfolio_metrics(r, spy_returns=spy_returns)
        print(f"  {label:<14} CAGR {_fmt(m.get('cagr')):>9}  Sharpe {m.get('sharpe', float('nan')):6.3f}  "
              f"MaxDD {_fmt(m.get('max_drawdown')):>9}  WinRate {_fmt(m.get('monthly_win_rate')):>8}  "
              f"Months {m.get('n_months', 0)}")

    # ── Walk-forward fold stability, both versions vs. universe benchmark ──
    all_months = sorted(gb["month_end_date"].unique())
    windows = _fold_windows(all_months, TRAIN_YEARS, TEST_YEARS)
    log.info("%d walk-forward test folds (train=%dy, test=%dy), %s to %s",
              len(windows), TRAIN_YEARS, TEST_YEARS, str(windows[0][0])[:10], str(windows[-1][1])[:10])

    bench_returns = compute_universe_benchmark(gb)

    print("\n" + "=" * 90)
    print("WALK-FORWARD FOLD STABILITY — 36 non-overlapping annual test folds")
    print("=" * 90)
    _print_fold_table(
        "-- unconstrained pure-Greenblatt vs. universe equal-weight benchmark --",
        bench_returns, unconstrained_returns, "universe_ew", "greenblatt", windows,
    )
    _print_fold_table(
        "-- constrained pure-Greenblatt vs. universe equal-weight benchmark --",
        bench_returns, constrained_returns, "universe_ew", "greenblatt", windows,
    )
    _print_fold_table(
        "-- unconstrained vs. constrained (does adding real-world rules help or hurt, fold by fold) --",
        unconstrained_returns, constrained_returns, "unconstrained", "constrained", windows,
    )

    # Aggregate over the walk-forward-evaluable range only
    eval_start, eval_end = windows[0][0], windows[-1][1]
    print(f"\nAggregate over walk-forward-evaluable range ({str(eval_start)[:10]} to {str(eval_end)[:10]}):")
    for label, r in [("unconstrained", unconstrained_returns), ("constrained", constrained_returns),
                      ("universe_ew", bench_returns)]:
        r_eval = r[(r.index >= eval_start) & (r.index <= eval_end)]
        m = portfolio_metrics(r_eval, spy_returns=spy_returns)
        print(f"  {label:<14} CAGR {_fmt(m.get('cagr')):>9}  Sharpe {m.get('sharpe', float('nan')):6.3f}  "
              f"MaxDD {_fmt(m.get('max_drawdown')):>9}  WinRate {_fmt(m.get('monthly_win_rate')):>8}  "
              f"Months {m.get('n_months', 0)}")

    print("\nDone.")


if __name__ == "__main__":
    main()
