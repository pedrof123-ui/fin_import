#!/usr/bin/env python3
"""
Phase 9 robustness/sensitivity check for the composite factor score (the model
now retained after scripts/walk_forward_portfolio_backtest.py showed XGBoost
has no walk-forward edge over it — see
features/historic_fundamentals/fundamentals_alpha_action_plan.md Phase 9 for
the original checklist this adapts).

Tests whether the composite score's backtested edge survives reasonable
variation in:
  1. Universe definition (min market cap: 300M / 1B baseline / 5B)
  2. Transaction costs (0 / 10 baseline / 25 / 50 / 100 bps)
  3. Sector-neutral vs. raw cross-sectional scoring

Portfolio-size sensitivity is NOT re-tested here — it's already covered by
docs/walk_forward_portfolio_backtest.md (top_pct_20/10, top_n_50/25/10 all
computed in that run). This script holds portfolio size fixed at top_n_25
(the size cited throughout prior reports) and varies the other three axes
instead, since composite scoring requires no model fitting (no walk-forward
retrain needed -- point-in-time cross-sectional rank each month), so this
runs in a fraction of the time the XGBoost walk-forward did.

Usage:
    uv run scripts/composite_robustness_check.py
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
from scripts.run_backtest import _load_monthly_pe, _join_sector, _load_historical_adv, _compute_pit_composite_score  # noqa: E402

log = logging.getLogger(__name__)


def _fmt(v, pct=True):
    if v is None or pd.isna(v):
        return "   N/A"
    return f"{v * 100:+.2f}%" if pct else f"{v:.4f}"


def _run_one(raw: pd.DataFrame, min_market_cap: float, tc_bps: float, sector_neutral: bool, spy_returns) -> dict:
    uk = {**UNIVERSE_DEFAULTS, "min_market_cap": min_market_cap}
    universe = filter_universe(raw, **uk)
    universe = universe.copy()
    universe["composite_score"] = _compute_pit_composite_score(universe, sector_neutral=sector_neutral)

    bt = run_monthly_backtest(
        universe, score_col="composite_score", tc_bps=tc_bps,
        portfolios={"top_n_25": 25}, sector_col="sector", max_sector_pct=0.25,
    )
    port = bt.get("top_n_25", pd.DataFrame())
    if port.empty:
        return {"n_tickers": universe["ticker"].nunique(), "n_months": 0}
    m = portfolio_metrics(port["net_return"], spy_returns=spy_returns)
    m["n_tickers"] = universe["ticker"].nunique()
    return m


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    log.info("Loading monthly_pe ...")
    raw = _load_monthly_pe(hf_db)
    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]

    if Path(prices_db).exists():
        adv_df = _load_historical_adv(prices_db, raw["ticker"].unique().tolist())
        if not adv_df.empty:
            raw["_month"] = pd.to_datetime(raw["month_end_date"]).dt.to_period("M")
            raw = raw.merge(adv_df.rename(columns={"year_month": "_month"}), on=["ticker", "_month"], how="left")
            raw = raw.drop(columns=["_month"])

    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)

    rows = []

    log.info("Axis 1: universe (min market cap), tc=10bps, sector_neutral=False ...")
    for label, mc in [("300M", 300e6), ("1B (baseline)", 1e9), ("5B", 5e9)]:
        m = _run_one(raw, mc, 10.0, False, spy_returns)
        rows.append({"variant": f"universe_min_cap_{label}", **m})

    log.info("Axis 2: transaction costs, universe=1B baseline, sector_neutral=False ...")
    for tc in [0.0, 10.0, 25.0, 50.0, 100.0]:
        label = f"{tc:.0f}bps" + (" (baseline)" if tc == 10.0 else "")
        m = _run_one(raw, 1e9, tc, False, spy_returns)
        rows.append({"variant": f"tc_{label}", **m})

    log.info("Axis 3: sector-neutral scoring, universe=1B baseline, tc=10bps ...")
    for label, sn in [("raw (baseline)", False), ("sector_neutral", True)]:
        m = _run_one(raw, 1e9, 10.0, sn, spy_returns)
        rows.append({"variant": f"scoring_{label}", **m})

    result_df = pd.DataFrame(rows)

    lines = [
        "# Composite Score — Robustness / Sensitivity Check (Phase 9)\n",
        "Portfolio fixed at top_n_25 (25 stocks, equal-weight, monthly rebalance, 25% sector cap).",
        "Portfolio-SIZE sensitivity already covered by docs/walk_forward_portfolio_backtest.md",
        "(top_pct_20/10, top_n_50/25/10 all computed there) — not repeated here.\n",
        "```",
        f"{'Variant':<28} {'CAGR':>9} {'Sharpe':>8} {'MaxDD':>9} {'AnnVol':>9} {'Tickers':>8}",
        "-" * 76,
    ]
    for _, row in result_df.iterrows():
        lines.append(
            f"{row['variant']:<28} {_fmt(row.get('cagr')):>9} {row.get('sharpe', float('nan')):>8.3f}"
            f" {_fmt(row.get('max_drawdown')):>9} {_fmt(row.get('ann_vol')):>9} {int(row.get('n_tickers', 0)):>8}"
        )
    lines.append("```\n")

    report = "\n".join(lines)
    print(report)
    out_path = ROOT / "docs" / "composite_robustness_report.md"
    out_path.write_text(report)
    log.info("Report written to %s", out_path)


if __name__ == "__main__":
    main()
