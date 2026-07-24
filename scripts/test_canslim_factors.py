#!/usr/bin/env python3
"""
IC / ICIR test for the CANSLIM factors backfilled by:
    scripts/backfill_canslim_factors.py      (C: q_earn_yoy, q_earn_accel)
    scripts/backfill_canslim_technicals.py   (N/S: pct_off_52wk_high,
                                               vol_surge_ratio, up_down_vol_ratio)
    scripts/backfill_canslim_rs.py           (L: rs_rating)

A (earn_cagr_3yr, roe) already existed in monthly_pe before this plan, not
currently part of the live composite (_VALUE_COLS/_QUALITY_COLS) -- tested
here alongside the new factors for the same reason.

M (market direction) is not a per-stock factor and is not tested here -- it's
a portfolio-level regime gate, reused from
scripts/run_backtest.py::_compute_regime_exposure in the backtest phases.

I (institutional sponsorship) is cut from this plan entirely (see
CANSLIM_FACTOR_TEST_PLAN.md Phase 0/4) -- no historical data to test against.

Same two tests as scripts/test_greenblatt_factors.py's sections 1-2:
    1. IC test — Spearman rank IC vs ret_6m/ret_1y forward returns.
    2. Quintile spread (ret_1y) — Q1 (best) minus Q5 (worst).

Nothing here writes to historic_fundamentals/baselines.py -- those stay
untouched until these results are reviewed.

Usage:
    uv run scripts/test_canslim_factors.py
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
)
from scripts.run_backtest import _load_monthly_pe, _join_sector  # noqa: E402

log = logging.getLogger(__name__)

# name -> (column, lower_is_better)
CANSLIM_FACTORS = {
    "C_earn_accel":        ("q_earn_accel",       False),
    "A_earn_cagr_3yr":     ("earn_cagr_3yr",       False),
    "A_roe":               ("roe",                 False),
    "N_pct_off_52wk_high": ("pct_off_52wk_high",   False),  # closer to 0 (near high) is better
    "S_vol_surge_ratio":   ("vol_surge_ratio",     False),
    "S_up_down_vol_ratio": ("up_down_vol_ratio",   False),
    "L_rs_rating":         ("rs_rating",           False),
}

REQUIRED_COLS = [col for col, _ in CANSLIM_FACTORS.values()]


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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))

    log.info("Loading monthly_pe ...")
    raw = _load_monthly_pe(hf_db)
    missing = [c for c in REQUIRED_COLS if c not in raw.columns]
    if missing:
        log.error("Missing columns %s — run the backfill_canslim_* scripts first.", missing)
        sys.exit(1)
    log.info("Loaded %d rows, %d tickers", len(raw), raw["ticker"].nunique())
    for name, (col, _) in CANSLIM_FACTORS.items():
        n = raw[col].notna().sum()
        log.info("  %-22s (%-18s) coverage %d/%d (%.1f%%)", name, col, n, len(raw), 100 * n / len(raw))

    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]

    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe (standard, financials/real-estate excluded): %d rows, %d tickers",
              len(universe), universe["ticker"].nunique())

    log.info("Computing forward returns (ret_6m, ret_1y) ...")
    universe = compute_forward_returns(universe, {"ret_6m": 6, "ret_1y": 12})

    # ── 1. IC test ──────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("1. IC TEST — CANSLIM factors (C, A, N, S, L)")
    print("=" * 78)
    for return_col in ("ret_1y", "ret_6m"):
        print(f"\n-- forward return: {return_col} --")
        table = _ic_table(universe, CANSLIM_FACTORS, return_col)
        print(table.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # ── 2. Quintile spread (ret_1y) ──────────────────────────────────────────
    print("\n" + "=" * 78)
    print("2. QUINTILE SPREAD (ret_1y) — Q1 (best) minus Q5 (worst), mean monthly")
    print("=" * 78)
    for name, (col, lower_is_better) in CANSLIM_FACTORS.items():
        if col not in universe.columns:
            continue
        qr = quintile_returns(universe, col, "ret_1y", lower_is_better=lower_is_better)
        if qr.empty:
            continue
        print(f"  {name:<22} Q1={qr['Q1'].mean():+7.2%}  Q5={qr['Q5'].mean():+7.2%}  "
              f"spread={qr['spread'].mean():+7.2%}  months={len(qr)}")

    print("\nDone.")


if __name__ == "__main__":
    main()
