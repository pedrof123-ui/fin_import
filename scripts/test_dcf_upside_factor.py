#!/usr/bin/env python3
"""
Phase 3 of features/dcf/PLAN_DCF_ACCURACY.md — put DCF-implied upside through the same
gauntlet every other factor candidate faces.

The panel comes from scripts/reconstruct_dcf_panel.py: intrinsic value recomputed quarterly
point-in-time, carried forward against each month's price to give a monthly factor. Using the
established bar (compute_factor_ic / ic_summary / quintile_returns) matters more than the
specific metric -- it makes the answer directly comparable to CANSLIM, Greenblatt, Fibonacci
and MD&A, all of which this bar rejected.

PREDICTIONS COMMITTED BEFORE RUNNING (plan, 2026-08-21):
  1. Weak positive rank IC (~0.01-0.03) that fails the fold win rate.
  2. Largely REDUNDANT with existing value factors -- a DCF at fixed WACC is mostly a levered
     function of current margins and growth, which earnings_yield/ebitda_ev_yield capture.

Prediction 2 dictates the design: the headline test is INCREMENTAL IC after residualising
dcf_upside on the existing value factors, not standalone IC. A factor 0.8-correlated with one
already in the composite can post a respectable standalone IC and add nothing.

Dispersion is reported alongside every median: the Step 0.2 beta fix moved 40% of its group by
>25% while showing a median change of +0.02%, so a symmetric re-dispersion and a no-op are
indistinguishable at the median.

Usage:
    uv run scripts/test_dcf_upside_factor.py
    uv run scripts/test_dcf_upside_factor.py --panel data/dcf_reconstruction_smallcap
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from historic_fundamentals.universe import UNIVERSE_DEFAULTS, filter_universe  # noqa: E402
from historic_fundamentals.baselines import (  # noqa: E402
    compute_forward_returns, compute_factor_ic, ic_summary, quintile_returns,
)
from scripts.run_backtest import _load_monthly_pe, _join_sector  # noqa: E402

log = logging.getLogger(__name__)

REFERENCE_FACTORS = {
    "earnings_yield": False,
    "ebitda_ev_yield": False,
    "fcf_yield": False,
    "roic": False,
}
RESIDUALISE_ON = ["earnings_yield", "ebitda_ev_yield", "fcf_yield"]


def load_panel(panel_dir: str) -> pd.DataFrame:
    """Quarterly as-of intrinsic values, ok rows only."""
    conn = duckdb.connect()
    df = conn.execute(
        f"""
        SELECT ticker, as_of, intrinsic_value_per_share, price_at_computation,
               wacc, tv_pct_enterprise_value
        FROM '{panel_dir}/*.parquet'
        WHERE status = 'ok' AND intrinsic_value_per_share > 0
        """
    ).df()
    conn.close()
    df["as_of"] = pd.to_datetime(df["as_of"])
    return df


def attach_dcf_upside(universe: pd.DataFrame, panel: pd.DataFrame, max_stale_days: int = 200) -> pd.DataFrame:
    """Carry each quarterly intrinsic value forward onto monthly rows.

    as_of <= month_end_date strictly, so the valuation only ever uses information that predates
    the month it is scored in. Upside is recomputed against THAT month's price, which is what
    makes a quarterly recompute yield a monthly factor.
    """
    u = universe.sort_values("month_end_date").copy()
    p = panel.sort_values("as_of").copy()
    u["month_end_date"] = pd.to_datetime(u["month_end_date"])

    merged = pd.merge_asof(
        u, p[["ticker", "as_of", "intrinsic_value_per_share", "wacc", "tv_pct_enterprise_value"]],
        left_on="month_end_date", right_on="as_of", by="ticker", direction="backward",
    )
    # Drop valuations too stale to be meaningful (a ticker that dropped out of the panel for
    # years should not carry a decade-old intrinsic value forward).
    stale = (merged["month_end_date"] - merged["as_of"]).dt.days
    merged.loc[stale > max_stale_days, "intrinsic_value_per_share"] = np.nan

    merged["dcf_upside"] = merged["intrinsic_value_per_share"] / merged["price"] - 1.0
    return merged


def residualise(df: pd.DataFrame, target: str, on: list[str]) -> pd.Series:
    """Cross-sectional residual of `target` on `on`, per month, rank-standardised.

    This is the incremental-information test: what does dcf_upside know that the value factors
    already in the composite do not?
    """
    cols = [c for c in on if c in df.columns]
    out = pd.Series(np.nan, index=df.index)
    for month, grp in df.groupby("month_end_date"):
        sub = grp[[target] + cols].apply(lambda s: s.rank(pct=True))
        sub = sub.dropna()
        if len(sub) < 30:
            continue
        y = sub[target].values
        X = np.column_stack([np.ones(len(sub))] + [sub[c].values for c in cols])
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        out.loc[sub.index] = y - X @ beta
    return out


def ic_row(df: pd.DataFrame, col: str, ret: str, lower_is_better: bool = False) -> dict:
    ic = compute_factor_ic(df, col, ret, lower_is_better=lower_is_better)
    s = ic_summary(ic)
    return {
        "factor": col, "mean_ic": s["mean_ic"], "icir": s["icir"], "icir_nw": s["icir_nw"],
        "hit_rate": s["hit_rate"], "t_stat": s["t_stat"], "n_months": s["n_months"],
    }


def fold_win_rate(df: pd.DataFrame, col: str, ret: str) -> tuple[int, int, list]:
    """Annual walk-forward folds: does the factor's mean IC stay positive year by year?

    A factor that only works in a few standout years is what this repo has repeatedly rejected.
    """
    ic = compute_factor_ic(df, col, ret)
    if ic.empty:
        return 0, 0, []
    by_year = ic.groupby(ic.index.year).mean()
    wins = int((by_year > 0).sum())
    return wins, len(by_year), [(int(y), float(v)) for y, v in by_year.items()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="data/dcf_reconstruction")
    ap.add_argument("--return-col", default="ret_1y")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))

    log.info("Loading monthly_pe ...")
    raw = _load_monthly_pe(hf_db)
    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]
    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe: %d rows, %d tickers", len(universe), universe["ticker"].nunique())

    log.info("Loading DCF panel from %s ...", args.panel)
    panel = load_panel(args.panel)
    log.info("Panel: %d ok valuations, %d tickers, %d as-of dates",
             len(panel), panel["ticker"].nunique(), panel["as_of"].nunique())

    df = attach_dcf_upside(universe, panel)
    df = df[(df["month_end_date"] >= "2010-01-01") & (df["month_end_date"] <= "2024-12-31")]
    df = compute_forward_returns(df, {"ret_6m": 6, "ret_1y": 12})

    cov = df["dcf_upside"].notna().mean()
    log.info("dcf_upside coverage on the filtered universe: %d/%d (%.1f%%)",
             df["dcf_upside"].notna().sum(), len(df), 100 * cov)

    ret = args.return_col
    print("\n" + "=" * 78)
    print(f"1. STANDALONE RANK IC vs {ret}")
    print("=" * 78)
    rows = [ic_row(df, "dcf_upside", ret)]
    for col, lower in REFERENCE_FACTORS.items():
        if col in df.columns and df[col].notna().any():
            rows.append(ic_row(df, col, ret, lower_is_better=lower))
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

    print("\n" + "=" * 78)
    print("2. REDUNDANCY — cross-sectional rank correlation with existing value factors")
    print("=" * 78)
    corr_rows = []
    for col in RESIDUALISE_ON + ["roic"]:
        if col not in df.columns:
            continue
        c = df.groupby("month_end_date").apply(
            lambda g: g["dcf_upside"].corr(g[col], method="spearman"), include_groups=False
        )
        corr_rows.append({"vs": col, "mean_rank_corr": c.mean(), "median": c.median(),
                          "p10": c.quantile(0.10), "p90": c.quantile(0.90)})
    print(pd.DataFrame(corr_rows).to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

    print("\n" + "=" * 78)
    print(f"3. INCREMENTAL IC — dcf_upside residualised on {RESIDUALISE_ON}")
    print("=" * 78)
    df["dcf_upside_resid"] = residualise(df, "dcf_upside", RESIDUALISE_ON)
    print(pd.DataFrame([
        ic_row(df, "dcf_upside", ret),
        ic_row(df, "dcf_upside_resid", ret),
    ]).to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

    print("\n" + "=" * 78)
    print(f"4. QUINTILE SPREAD (dispersion, not just the median) vs {ret}")
    print("=" * 78)
    # Aggregate, not the per-month dump: Q1 is the BEST bucket (highest dcf_upside) and
    # spread is Q1 - Q5, so a positive spread is the factor working. p10/p90 are reported
    # because a wide two-sided spread and a real edge look identical at the mean.
    qrows = []
    for col in ("dcf_upside", "dcf_upside_resid"):
        q = quintile_returns(df, col, ret)
        if q.empty:
            continue
        qrows.append({
            "factor": col, "n_months": len(q),
            **{b: q[b].mean() for b in ("Q1", "Q2", "Q3", "Q4", "Q5")},
            "mean_spread": q["spread"].mean(), "median_spread": q["spread"].median(),
            "p10": q["spread"].quantile(0.10), "p90": q["spread"].quantile(0.90),
            "pct_months_pos": 100 * (q["spread"] > 0).mean(),
        })
    print("  Q1 = highest dcf_upside (best bucket); spread = Q1 - Q5, positive = factor works")
    print(pd.DataFrame(qrows).to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

    print("\n" + "=" * 78)
    print(f"5. WALK-FORWARD FOLD WIN RATE (annual folds) vs {ret}")
    print("=" * 78)
    for col in ("dcf_upside", "dcf_upside_resid"):
        wins, n, by_year = fold_win_rate(df, col, ret)
        if not n:
            print(f"  {col}: no folds")
            continue
        print(f"\n  {col}: {wins}/{n} folds positive ({wins / n:.0%})")
        print("   " + "  ".join(f"{y}:{v:+.3f}" for y, v in by_year))


if __name__ == "__main__":
    main()
