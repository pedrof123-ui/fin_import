#!/usr/bin/env python3
"""
Quantifies the live formation-to-execution lag for the fundamentals-alpha
rebalance (vw_gr_top_n_25 and gr_top_n_25).

Background: docs/live_scores_*.csv is produced once a month (the pipeline
cron on the 1st), using each ticker's most recently *completed* monthly_pe
row (month-end price of the prior month). rebalance.py then executes on the
last trading day of that same month, up to ~30 calendar days later, still
reading that same CSV. run_backtest.py's zero-lag assumption (score and buy
both use month t's own month-end price) does not match this — live trades
are effectively formed on month t-1 data and executed at month t's close.

This script re-runs the walk-forward-style monthly backtest twice per
portfolio: score_lag_months=0 (current backtest assumption) vs. =1 (matches
the live cron timing), holding everything else identical, to isolate the
CAGR/Sharpe/MaxDD/Profit-Factor/R-Expectancy drag from that one-month lag.

Usage:
    uv run scripts/analyze_score_lag.py
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
from historic_fundamentals.backtest import (  # noqa: E402
    run_monthly_backtest,
    portfolio_metrics,
    load_spy_returns,
)
from scripts.run_backtest import (  # noqa: E402
    _load_monthly_pe,
    _join_sector,
    _load_historical_adv,
    _compute_pit_composite_score,
    _apply_guardrails,
)

log = logging.getLogger(__name__)

TC_BPS = 10.0
MAX_SECTOR_PCT = 0.25
SCORE_BUFFER = 0.10


def _profit_factor_and_expectancy(returns: pd.Series) -> tuple[float, float]:
    r = returns.dropna()
    wins = r[r > 0]
    losses = r[r <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else np.nan
    win_rate = len(wins) / len(r) if len(r) > 0 else np.nan
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.0
    r_exp = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if not np.isnan(win_rate) else np.nan
    return pf, r_exp


def _fmt(v, pct=False):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "    N/A"
    return f"{v * 100:+7.2f}%" if pct else f"{v:8.4f}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    log.info("Loading monthly_pe ...")
    raw = _load_monthly_pe(hf_db)
    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]

    if Path(prices_db).exists() and UNIVERSE_DEFAULTS.get("min_avg_dollar_volume"):
        tickers_all = raw["ticker"].unique().tolist()
        adv_df = _load_historical_adv(prices_db, tickers_all)
        if not adv_df.empty:
            raw["_month"] = pd.to_datetime(raw["month_end_date"]).dt.to_period("M")
            raw = raw.merge(
                adv_df.rename(columns={"year_month": "_month"}), on=["ticker", "_month"], how="left"
            )
            raw = raw.drop(columns=["_month"])

    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe: %d rows, %d tickers", len(universe), universe["ticker"].nunique())

    universe = universe.copy()
    universe["composite_score"] = _compute_pit_composite_score(universe, sector_neutral=True)
    universe_gr = _apply_guardrails(universe, "composite_score")

    spy_returns = load_spy_returns(prices_db_path=prices_db) if Path(prices_db).exists() else None
    sector_col = "sector" if "sector" in universe.columns else None

    variants = [
        ("gr_top_n_25",    "gr_top_n_25",    False),
        ("vw_gr_top_n_25", "vw_gr_top_n_25", True),
    ]
    lags = [0, 1]

    results: dict[str, dict] = {}
    for label, port_key, vol_weight in variants:
        for lag in lags:
            key = f"{label}_lag{lag}"
            log.info("Running %s (score_lag_months=%d) ...", label, lag)
            bt = run_monthly_backtest(
                universe_gr,
                score_col="composite_score",
                tc_bps=TC_BPS,
                portfolios={"top_n_25": 25},
                sector_col=sector_col,
                max_sector_pct=MAX_SECTOR_PCT,
                score_buffer=SCORE_BUFFER,
                use_vol_weighting=vol_weight,
                score_lag_months=lag,
            )
            bt_df = bt.get("top_n_25", pd.DataFrame())
            if bt_df.empty:
                results[key] = {}
                continue
            ret_series = bt_df["net_return"]
            m = portfolio_metrics(ret_series, spy_returns=spy_returns)
            pf, r_exp = _profit_factor_and_expectancy(ret_series)
            m["profit_factor"] = pf
            m["r_expectancy"] = r_exp
            m["avg_turnover"] = bt_df["turnover"].mean()
            results[key] = m

    cols = ["cagr", "ann_vol", "sharpe", "max_drawdown", "profit_factor",
            "r_expectancy", "avg_turnover", "n_months"]
    header = (
        f"{'Variant':<24} {'CAGR':>8} {'Vol':>8} {'Sharpe':>8} "
        f"{'MaxDD':>9} {'ProfFact':>9} {'R-Exp':>8} {'Turnover':>9} {'Months':>7}"
    )
    print()
    print("=" * len(header))
    print("Score-Formation-Lag Backtest — lag0 (current backtest assumption) vs. lag1 (matches live cron)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for key, m in results.items():
        if not m:
            print(f"{key:<24}  (no results)")
            continue
        print(
            f"{key:<24} "
            f"{_fmt(m.get('cagr'), pct=True):>8} "
            f"{_fmt(m.get('ann_vol'), pct=True):>8} "
            f"{_fmt(m.get('sharpe')):>8} "
            f"{_fmt(m.get('max_drawdown'), pct=True):>9} "
            f"{_fmt(m.get('profit_factor')):>9} "
            f"{_fmt(m.get('r_expectancy'), pct=True):>8} "
            f"{_fmt(m.get('avg_turnover'), pct=True):>9} "
            f"{m.get('n_months', 0):>7}"
        )
    print()

    for label, _, _ in variants:
        m0 = results.get(f"{label}_lag0", {})
        m1 = results.get(f"{label}_lag1", {})
        if m0 and m1:
            print(
                f"{label}: 1-month lag drag — "
                f"CAGR {(m1['cagr'] - m0['cagr']) * 100:+.2f}pp, "
                f"Sharpe {m1['sharpe'] - m0['sharpe']:+.3f}, "
                f"MaxDD {(m1['max_drawdown'] - m0['max_drawdown']) * 100:+.2f}pp, "
                f"ProfitFactor {m1['profit_factor'] - m0['profit_factor']:+.3f}"
            )


if __name__ == "__main__":
    main()
