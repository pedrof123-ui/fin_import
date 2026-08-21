#!/usr/bin/env python3
"""
Walk-forward validation of a tighter MAX_INTRINSIC_TO_PRICE guard.

The in-sample sweep (features/dcf/PLAN_DCF_ACCURACY.md Phase 3) showed dcf_upside's mean IC
rising from 0.016 at the current 10.0x bound to 0.045 at 2.0x -- earnings_yield territory.
That sweep tried six thresholds on one dataset and kept the winner, which is exactly the
in-sample selection that killed the MD&A contrarian composite. This script tests whether the
improvement survives out of sample.

Two tests, because they answer different questions:

  A. ADAPTIVE -- pick the best threshold on each fold's TRAIN window, score it on the unseen
     TEST year, against the current 10.0x baseline on that same year. The selection step is
     inside the fold, so a threshold that only works in-sample is penalised here. This asks:
     does the PROCEDURE generalise?

  B. FIXED -- hold one threshold (2.0x) constant and compare per-year against 10.0x, with a
     temporal stability split. This asks: does TIGHTENING help even if the exact value is
     arbitrary? A factor whose edge is concentrated in a few standout years is what this repo
     has repeatedly rejected.

Convention matches scripts/test_canslim_rs_updown_regime.py: 5 train years, 1 test year, rolling.

Usage:
    uv run scripts/test_dcf_guard_walkforward.py
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
    compute_forward_returns, compute_factor_ic, ic_summary,
)
from scripts.run_backtest import _load_monthly_pe, _join_sector  # noqa: E402
from scripts.test_dcf_upside_factor import load_panel, attach_dcf_upside  # noqa: E402

log = logging.getLogger(__name__)

TRAIN_YEARS = 5
TEST_YEARS = 1
BASELINE_CAP = 10.0                                  # current MAX_INTRINSIC_TO_PRICE
CANDIDATE_CAPS = [5.0, 3.0, 2.5, 2.0, 1.5]
FIXED_CAP = 2.0
RET = "ret_1y"


def _ic_for_cap(df: pd.DataFrame, cap: float) -> float:
    """Mean IC with valuations above `cap` x price treated as failures (dropped)."""
    d = df[df["iv_to_price"].isna() | (df["iv_to_price"] <= cap)]
    ic = compute_factor_ic(d, "dcf_upside", RET)
    return float(ic.mean()) if len(ic) else np.nan


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")

    hf = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))

    raw = _join_sector(_load_monthly_pe(hf), av)
    raw["market_cap"] = raw["shares"] * raw["price"]
    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)

    df = attach_dcf_upside(universe, load_panel("data/dcf_reconstruction"))
    df = df[(df["month_end_date"] >= "2010-01-01") & (df["month_end_date"] <= "2024-12-31")]
    df = compute_forward_returns(df, {RET: 12})
    df["iv_to_price"] = df["dcf_upside"] + 1.0
    df["year"] = pd.to_datetime(df["month_end_date"]).dt.year

    years = sorted(df["year"].unique())
    folds = [(years[i - TRAIN_YEARS:i], years[i]) for i in range(TRAIN_YEARS, len(years))]

    print("=" * 84)
    print(f"A. ADAPTIVE — threshold chosen on 5 train years, scored on the unseen next year")
    print("=" * 84)
    print(f"{'Fold':<5} {'Train':<12} {'Test':<6} {'Picked':>7} {'Test IC (picked)':>17} "
          f"{'Test IC (10x)':>14} {'Winner':>9}")
    print("-" * 84)

    wins, valid, picks = 0, 0, []
    for i, (train_years, test_year) in enumerate(folds, 1):
        tr = df[df["year"].isin(train_years)]
        te = df[df["year"] == test_year]
        if te["dcf_upside"].notna().sum() < 100:
            continue
        train_ics = {c: _ic_for_cap(tr, c) for c in CANDIDATE_CAPS + [BASELINE_CAP]}
        best = max(train_ics, key=lambda c: (train_ics[c] if not np.isnan(train_ics[c]) else -9))
        ic_pick = _ic_for_cap(te, best)
        ic_base = _ic_for_cap(te, BASELINE_CAP)
        if np.isnan(ic_pick) or np.isnan(ic_base):
            continue
        valid += 1
        win = ic_pick > ic_base
        wins += win
        picks.append(best)
        print(f"{i:<5} {train_years[0]}-{train_years[-1]:<7} {test_year:<6} {best:>7.1f} "
              f"{ic_pick:>17.4f} {ic_base:>14.4f} {'tighter' if win else '10x':>9}")

    print("-" * 84)
    if valid:
        print(f"Tighter guard beats the current 10x in {wins}/{valid} out-of-sample folds "
              f"({wins / valid:.0%})")
        print(f"Thresholds chosen: {picks}")
        print(f"  -> selection {'is STABLE' if len(set(picks)) <= 2 else 'is UNSTABLE'} "
              f"({len(set(picks))} distinct values across {valid} folds)")

    print("\n" + "=" * 84)
    print(f"B. FIXED {FIXED_CAP}x vs {BASELINE_CAP}x — per-year, plus temporal stability")
    print("=" * 84)
    rows = []
    for y in years:
        te = df[df["year"] == y]
        if te["dcf_upside"].notna().sum() < 100:
            continue
        a, b = _ic_for_cap(te, FIXED_CAP), _ic_for_cap(te, BASELINE_CAP)
        rows.append({"year": y, f"ic_{FIXED_CAP}x": a, f"ic_{BASELINE_CAP}x": b,
                     "delta": a - b, "tighter_wins": a > b})
    t = pd.DataFrame(rows)
    print(t.to_string(index=False, float_format=lambda x: f"{x:8.4f}"))
    n = len(t)
    print(f"\nFixed {FIXED_CAP}x beats {BASELINE_CAP}x in {int(t['tighter_wins'].sum())}/{n} years "
          f"({t['tighter_wins'].mean():.0%}); mean IC delta {t['delta'].mean():+.4f}")

    mid = n // 2
    for label, half in (("first half ", t.iloc[:mid]), ("second half", t.iloc[mid:])):
        print(f"  {label} {half['year'].iloc[0]}-{half['year'].iloc[-1]}: "
              f"{int(half['tighter_wins'].sum())}/{len(half)} years "
              f"({half['tighter_wins'].mean():.0%}), mean delta {half['delta'].mean():+.4f}")

    print("\n" + "=" * 84)
    print(f"C. FULL-SAMPLE IC of the fixed {FIXED_CAP}x rule (context, in-sample)")
    print("=" * 84)
    for cap in (BASELINE_CAP, FIXED_CAP):
        d = df[df["iv_to_price"].isna() | (df["iv_to_price"] <= cap)]
        s = ic_summary(compute_factor_ic(d, "dcf_upside", RET))
        kept = 100 * d["dcf_upside"].notna().sum() / df["dcf_upside"].notna().sum()
        print(f"  {cap:>5.1f}x  mean_ic {s['mean_ic']:+.4f}  icir_nw {s['icir_nw']:+.3f}  "
              f"hit {s['hit_rate']:.3f}  t {s['t_stat']:+.2f}  rows kept {kept:.1f}%")


if __name__ == "__main__":
    main()
