#!/usr/bin/env python3
"""
Is 12 months the wrong clock for a DCF?  (features/dcf/PLAN_DCF_FOLLOWUP.md Phase 1)

The predecessor rejected dcf_upside as a ranking factor on 1-year forward returns. But a DCF is a
claim about decades of cash flows, and the standard premise is that price converges to intrinsic
value over three to five years. This re-runs the factor at 1y / 2y / 3y / 5y.

Four horizons, not two: with three points you cannot tell slow convergence (monotonic rise) from a
peak-and-fade.

THREE CONSTRAINTS, fixed before running (see the plan):

  1. Newey-West lags must be H-1 for overlapping H-month returns (11/23/35/59). ic_summary
     defaults to 11; using the default at 3y or 5y produces inflated t-stats that look like a
     strong result.
  2. DO NOT lead on t-stats at long horizons. At 5y the estimator uses 59 lags from ~140 months --
     42% of the sample length. Lead on the TREND SHAPE across horizons and on fold win rate, both
     of which survive overlap in a way t-stats do not.
  3. Measure INCREMENTAL IC at every horizon, not just standalone. Value factors generally
     strengthen at longer horizons, so a rise in standalone DCF IC could just mean "all value
     works better at 3y" -- which says nothing about the DCF.

PREDICTION COMMITTED BEFORE RUNNING: standalone IC rises with horizon; INCREMENTAL IC stays near
zero or negative, because the reference factors rise too. If incremental IC turns clearly positive
at 3y or 5y, the predecessor's verdict was measured on the wrong clock and the 2.5x guard -- which
was fitted at 1y -- needs re-deriving at the horizon where the signal lives.

Usage:
    uv run scripts/test_dcf_horizon.py
"""

from __future__ import annotations

import argparse
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
from scripts.test_dcf_upside_factor import load_panel, attach_dcf_upside, residualise  # noqa: E402

log = logging.getLogger(__name__)

HORIZONS = {"ret_1y": 12, "ret_2y": 24, "ret_3y": 36, "ret_5y": 60}
REFERENCE = ["earnings_yield", "ebitda_ev_yield", "fcf_yield", "roic"]
RESIDUALISE_ON = ["earnings_yield", "ebitda_ev_yield", "fcf_yield"]


def _row(df: pd.DataFrame, col: str, ret: str, lags: int) -> dict:
    ic = compute_factor_ic(df, col, ret)
    s = ic_summary(ic, nw_lags=lags)
    by_year = ic.groupby(ic.index.year).mean() if len(ic) else pd.Series(dtype=float)
    wins = int((by_year > 0).sum())
    return {
        "mean_ic": s["mean_ic"], "icir_nw": s["icir_nw"], "hit": s["hit_rate"],
        "t": s["t_stat"], "n_months": s["n_months"],
        "folds": f"{wins}/{len(by_year)}" if len(by_year) else "-",
        "fold_pct": (wins / len(by_year)) if len(by_year) else np.nan,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="data/dcf_reconstruction_flat_2p5")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")

    hf = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))

    raw = _join_sector(_load_monthly_pe(hf), av)
    raw["market_cap"] = raw["shares"] * raw["price"]
    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)

    # Forward returns on the FULL universe BEFORE trimming to the panel window. compute_forward_returns
    # looks up future prices inside the frame it is given, so filtering first silently truncates the
    # sample -- harmless at 1y (it cost the predecessor 13 of 180 months) and fatal at 5y, where a
    # frame ending 2024-12 would leave only months through 2019.
    universe = compute_forward_returns(universe, HORIZONS)

    df = attach_dcf_upside(universe, load_panel(args.panel))
    df = df[(df["month_end_date"] >= "2010-01-01") & (df["month_end_date"] <= "2024-12-31")]

    print("=" * 96)
    print("DCF-implied upside across horizons — panel:", args.panel)
    print("=" * 96)

    df["dcf_upside_resid"] = residualise(df, "dcf_upside", RESIDUALISE_ON)

    out = []
    for ret, months in HORIZONS.items():
        lags = months - 1
        for label, col in (("dcf_upside", "dcf_upside"), ("dcf_upside RESID", "dcf_upside_resid")):
            r = _row(df, col, ret, lags)
            out.append({"horizon": ret, "nw_lags": lags, "factor": label, **r})
        for col in REFERENCE:
            if col in df.columns and df[col].notna().any():
                out.append({"horizon": ret, "nw_lags": lags, "factor": col, **_row(df, col, ret, lags)})

    t = pd.DataFrame(out)
    for ret in HORIZONS:
        sub = t[t.horizon == ret].drop(columns=["horizon", "fold_pct"])
        print(f"\n--- {ret}  (Newey-West lags {HORIZONS[ret]-1}) ---")
        print(sub.to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

    print("\n" + "=" * 96)
    print("TREND SHAPE — the read that survives overlapping returns")
    print("=" * 96)
    piv = t[t.factor.isin(["dcf_upside", "dcf_upside RESID"] + RESIDUALISE_ON)].pivot(
        index="factor", columns="horizon", values="mean_ic")[list(HORIZONS)]
    print("\nmean IC by horizon:")
    print(piv.to_string(float_format=lambda x: f"{x:8.4f}"))

    fold = t[t.factor.isin(["dcf_upside", "dcf_upside RESID"])].pivot(
        index="factor", columns="horizon", values="folds")[list(HORIZONS)]
    print("\nfold win rate by horizon:")
    print(fold.to_string())

    print("\n" + "=" * 96)
    print("VERDICT vs the committed prediction")
    print("=" * 96)
    s_ic = piv.loc["dcf_upside"]
    r_ic = piv.loc["dcf_upside RESID"]
    print(f"  standalone IC rises with horizon?   {s_ic.iloc[-1] > s_ic.iloc[0]}  "
          f"({s_ic.iloc[0]:+.4f} at 1y -> {s_ic.iloc[-1]:+.4f} at 5y)")
    print(f"  INCREMENTAL IC positive at 3y/5y?   {(r_ic['ret_3y'] > 0.01) or (r_ic['ret_5y'] > 0.01)}  "
          f"({r_ic['ret_3y']:+.4f} at 3y, {r_ic['ret_5y']:+.4f} at 5y)")
    print(f"\n  PREDICTED: standalone rises, incremental stays <= ~0 -> verdict stands.")


if __name__ == "__main__":
    main()
