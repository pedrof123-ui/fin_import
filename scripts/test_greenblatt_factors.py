#!/usr/bin/env python3
"""
Evaluate the two Greenblatt "Magic Formula" factors (ebit_ev_yield, greenblatt_roc)
backfilled by scripts/backfill_greenblatt_factors.py.

Three tests, mirroring the methodology used for the PEGY-ratio experiment
(docs/project memory: IC test first, then walk-forward-style portfolio backtest
before touching the live composite):

1. IC test — Spearman rank IC of each new factor vs 6m/12m forward returns,
   compared against the existing factors they are meant to improve on
   (earnings_yield, ebitda_ev_yield, roic).

2. "Pure Greenblatt" backtest — literal magic-formula replication: rank-sum
   of ebit_ev_yield + greenblatt_roc, market-wide (NOT sector-neutral, per
   the book), excludes financials/real estate/utilities, top 20-30 names,
   monthly rebalance. No guardrails, no momentum — matches the book exactly.

3. "Augmented composite" backtest — the platform's live sector-neutral
   guardrailed composite (value+quality+momentum, see
   historic_fundamentals/baselines.py _VALUE_COLS/_QUALITY_COLS) with the
   two new factors added to the value/quality column lists, A/B'd against
   the same composite computed in this same run WITHOUT the new factors
   (apples-to-apples on identical data/universe/date range).

Nothing here writes to _VALUE_COLS/_QUALITY_COLS/BASELINE_FACTORS in
historic_fundamentals/baselines.py — those stay untouched (and therefore the
live score_live.py composite stays untouched) until these results are
reviewed and a decision is made to promote the factors.

Usage:
    uv run scripts/test_greenblatt_factors.py
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

NEW_FACTORS = {
    "high_ebit_ev_yield": ("ebit_ev_yield", False),
    "high_greenblatt_roc": ("greenblatt_roc", False),
}
REFERENCE_FACTORS = {
    "high_earnings_yield": ("earnings_yield", False),
    "high_ebitda_ev_yield": ("ebitda_ev_yield", False),
    "high_roic": ("roic", False),
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    log.info("Loading monthly_pe ...")
    raw = _load_monthly_pe(hf_db)
    if "ebit_ev_yield" not in raw.columns or "greenblatt_roc" not in raw.columns:
        log.error("ebit_ev_yield / greenblatt_roc not found — run scripts/backfill_greenblatt_factors.py first.")
        sys.exit(1)
    log.info("Loaded %d rows, %d tickers", len(raw), raw["ticker"].nunique())
    log.info(
        "Coverage: ebit_ev_yield %d/%d (%.1f%%), greenblatt_roc %d/%d (%.1f%%)",
        raw["ebit_ev_yield"].notna().sum(), len(raw), 100 * raw["ebit_ev_yield"].notna().mean(),
        raw["greenblatt_roc"].notna().sum(), len(raw), 100 * raw["greenblatt_roc"].notna().mean(),
    )

    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]

    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe (standard, incl. financials/real-estate excluded): %d rows, %d tickers",
              len(universe), universe["ticker"].nunique())

    log.info("Computing forward returns (ret_6m, ret_1y) ...")
    universe = compute_forward_returns(universe, {"ret_6m": 6, "ret_1y": 12})

    # ── 1. IC test ──────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("1. IC TEST — new factors vs. existing factors they aim to improve on")
    print("=" * 78)
    for return_col in ("ret_1y", "ret_6m"):
        print(f"\n-- forward return: {return_col} --")
        table = pd.concat([
            _ic_table(universe, NEW_FACTORS, return_col),
            _ic_table(universe, REFERENCE_FACTORS, return_col),
        ], ignore_index=True)
        print(table.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # ── 2. Quintile spread (ret_1y, matches the book's 1yr holding period) ──
    print("\n" + "=" * 78)
    print("2. QUINTILE SPREAD (ret_1y) — Q1 (best) minus Q5 (worst), mean monthly")
    print("=" * 78)
    for name, (col, lower_is_better) in {**NEW_FACTORS, **REFERENCE_FACTORS}.items():
        if col not in universe.columns:
            continue
        qr = quintile_returns(universe, col, "ret_1y", lower_is_better=lower_is_better)
        if qr.empty:
            continue
        print(f"  {name:<22} Q1={qr['Q1'].mean():+7.2%}  Q5={qr['Q5'].mean():+7.2%}  "
              f"spread={qr['spread'].mean():+7.2%}  months={len(qr)}")

    # ── 3. Pure Greenblatt replication backtest ──────────────────────────────
    print("\n" + "=" * 78)
    print("3. PURE GREENBLATT REPLICATION — rank-sum(ebit_ev_yield, greenblatt_roc),")
    print("   market-wide (not sector-neutral), financials/real-estate excluded,")
    print("   no guardrails, no momentum — matches the book's literal method")
    print("=" * 78)

    gb = universe.copy()
    gb = gb[gb["ebit_ev_yield"].notna() & gb["greenblatt_roc"].notna()].copy()
    gb["rank_ey"] = gb.groupby("month_end_date")["ebit_ev_yield"].rank(ascending=False)
    gb["rank_roc"] = gb.groupby("month_end_date")["greenblatt_roc"].rank(ascending=False)
    gb["greenblatt_score"] = -(gb["rank_ey"] + gb["rank_roc"])
    log.info("Pure-Greenblatt universe: %d rows, %d tickers (both factors present)",
              len(gb), gb["ticker"].nunique())

    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)

    gb_results = run_monthly_backtest(
        gb, score_col="greenblatt_score", tc_bps=10.0,
        portfolios={"top_n_25": 25, "top_n_30": 30, "top_pct_20": 0.20},
    )
    bench_returns = compute_universe_benchmark(gb)

    print()
    for port_name, bt_df in gb_results.items():
        m = portfolio_metrics(bt_df["net_return"], spy_returns) if not bt_df.empty else {}
        _print_metrics(f"greenblatt_{port_name}", m)
    if not bench_returns.empty:
        m = portfolio_metrics(bench_returns, spy_returns)
        _print_metrics("universe_ew (greenblatt univ.)", m)
    if spy_returns is not None and not spy_returns.empty:
        m = portfolio_metrics(spy_returns, spy_returns)
        _print_metrics("SPY", m)

    # ── 4. Augmented composite A/B ──────────────────────────────────────────
    print("\n" + "=" * 78)
    print("4. AUGMENTED COMPOSITE A/B — live sector-neutral guardrailed composite")
    print("   WITH vs WITHOUT the two new factors added (identical universe/dates)")
    print("=" * 78)

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

    universe_ab = universe.copy()
    universe_ab["composite_baseline"] = _composite(universe_ab)
    universe_ab["composite_augmented"] = _composite(
        universe_ab, extra_value=["ebit_ev_yield"], extra_quality=["greenblatt_roc"]
    )

    for score_col, label in [("composite_baseline", "baseline (current live factors)"),
                              ("composite_augmented", "augmented (+ebit_ev_yield +greenblatt_roc)")]:
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
