#!/usr/bin/env python3
"""
Does price converge toward the DCF's intrinsic value?  (PLAN_DCF_FOLLOWUP Phase 2)

The predecessor measured CROSS-SECTIONAL ranking. That is not how the AI Researcher uses the DCF
-- it presents a mechanical fair value for ONE company as a valuation anchor. A factor can be
useless for ranking and still informative per name; the two questions are different and neither
implies the other.

Design chosen 2026-08-22 over directional hit rate and calibration-in-the-large, for a
survivorship reason: convergence is a RATIO question a delisted company cannot answer, so its
absence is a missing observation. A directional test silently counts that same absence as evidence
IN THE DCF'S FAVOUR, and Phase 3 established the survivorship gap cannot be quantified locally.

For each (ticker, as_of):
    r_t     = price_t     / intrinsic_t
    r_{t+H} = price_{t+H} / intrinsic_t      <- SAME intrinsic value
converged when |r_{t+H} - 1| < |r_t - 1|.

TWO CONFOUNDS would fake a positive result, so the raw rate is never reported alone:

  A. Market drift. Equities drift up, so anything priced below intrinsic "converges" for free.
  B. Mechanical mean reversion. When |r_t - 1| is large, almost any change shrinks it.

Handled by:
  NULL A -- shuffle the RETURN, not the intrinsic value. r_t is held exactly as observed and the
            company's own forward return is replaced by another company's return from the SAME
            as-of date:  r_fut_null = r_t * (1 + ret_other).

            An earlier version shuffled intrinsic values instead and was WRONG: it widened the
            r_t distribution badly (median |r_t-1| 0.461 actual vs 0.779 shuffled, p90 4.31 vs
            10.68), and wide ratios converge mechanically -- confound B, the very thing the null
            was supposed to control. The null was easier than reality, so the real pairing looked
            anti-informative. Shuffling the return instead preserves r_t EXACTLY (killing
            confound B) while the substitute return still carries the same period's market drift
            (killing confound A). The question becomes precisely: does THIS company's own price
            movement carry it toward ITS OWN intrinsic value more often than a random
            contemporaneous return would?
  NULL B -- split by direction. Genuine information requires BOTH undervalued and overvalued
            names to converge. Drift converges only the undervalued side, and works AGAINST the
            overvalued side, which makes it the discriminating test.

Usage:
    uv run scripts/test_dcf_convergence.py
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
from scripts.run_backtest import _load_monthly_pe, _join_sector  # noqa: E402

log = logging.getLogger(__name__)

HORIZONS = {"1y": 12, "3y": 36, "5y": 60}
N_SHUFFLES = 20
RNG = np.random.default_rng(20260823)


def load_panel(panel_dir: str) -> pd.DataFrame:
    conn = duckdb.connect()
    df = conn.execute(
        f"""SELECT ticker, as_of, intrinsic_value_per_share AS iv, price_at_computation AS px
            FROM '{panel_dir}/*.parquet'
            WHERE status = 'ok' AND intrinsic_value_per_share > 0 AND price_at_computation > 0"""
    ).df()
    conn.close()
    df["as_of"] = pd.to_datetime(df["as_of"])
    return df


def future_prices(universe: pd.DataFrame, months: int) -> pd.DataFrame:
    """Price `months` after each month_end, within a 45-day tolerance (same rule as baselines)."""
    u = universe[["ticker", "month_end_date", "price"]].copy()
    u["month_end_date"] = pd.to_datetime(u["month_end_date"])
    left = u.copy()
    left["_target"] = left["month_end_date"] + pd.DateOffset(months=months)
    right = u.rename(columns={"month_end_date": "future_date", "price": "future_price"})
    m = left.merge(right, on="ticker", how="left")
    m["dd"] = (m["future_date"] - m["_target"]).abs().dt.days
    m = m[m["dd"] <= 45]
    m = (m.sort_values("dd").groupby(["ticker", "month_end_date"], sort=False).first()
           .reset_index()[["ticker", "month_end_date", "future_price"]])
    return m


def _conv_rate(r_t: np.ndarray, r_fut: np.ndarray) -> float:
    return float(np.mean(np.abs(r_fut - 1.0) < np.abs(r_t - 1.0)))


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

    panel = load_panel(args.panel)
    print(f"panel: {len(panel):,} ok valuations, {panel.ticker.nunique():,} tickers, "
          f"{panel.as_of.nunique()} as-of dates\n")

    rows, asym, frames = [], [], {}
    for label, months in HORIZONS.items():
        fut = future_prices(universe, months)
        d = panel.merge(fut, left_on=["ticker", "as_of"],
                        right_on=["ticker", "month_end_date"], how="inner").dropna(subset=["future_price"])
        _cols = ["ticker", "month_end_date", "sector"]
        if "earnings_yield" in universe.columns:
            _cols.append("earnings_yield")
        d = d.merge(universe[_cols].drop_duplicates(subset=["ticker", "month_end_date"]),
                    on=["ticker", "month_end_date"], how="left")
        if d.empty:
            continue
        d = d.assign(r_t=d.px / d.iv, r_fut=d.future_price / d.iv)

        actual = _conv_rate(d.r_t.values, d.r_fut.values)
        d = d.assign(ret=d.future_price / d.px - 1.0)
        frames[label] = d

        # NULL A: shuffle the RETURN within each as-of cross-section; r_t is untouched.
        nulls = []
        for _ in range(N_SHUFFLES):
            ret_s = d.groupby("as_of")["ret"].transform(lambda x: RNG.permutation(x.values))
            nulls.append(_conv_rate(d.r_t.values, (d.r_t * (1.0 + ret_s)).values))
        null_mu, null_sd = float(np.mean(nulls)), float(np.std(nulls))

        # NULL A2: substitute return drawn from the same SECTOR and as-of date. The obvious
        # objection to a positive edge is that the DCF is only carrying sector information (it
        # values some sectors low, and those sectors mean-revert). If the edge is really sector
        # tilt, matching on sector removes it.
        sec_nulls = []
        if "sector" in d.columns and d["sector"].notna().any():
            g = d.dropna(subset=["sector"])
            for _ in range(N_SHUFFLES):
                ret_s = g.groupby(["as_of", "sector"])["ret"].transform(
                    lambda x: RNG.permutation(x.values))
                sec_nulls.append(_conv_rate(g.r_t.values, (g.r_t * (1.0 + ret_s)).values))
        sec_mu = float(np.mean(sec_nulls)) if sec_nulls else np.nan
        sec_actual = _conv_rate(
            d.dropna(subset=["sector"]).r_t.values,
            d.dropna(subset=["sector"]).r_fut.values) if sec_nulls else np.nan

        rows.append({"horizon": label, "n": len(d), "actual": actual, "null": null_mu,
                     "null_sd": null_sd, "edge_pp": 100 * (actual - null_mu),
                     "z": (actual - null_mu) / null_sd if null_sd > 0 else np.nan,
                     "sector_edge_pp": 100 * (sec_actual - sec_mu) if sec_nulls else np.nan})

        # NULL B: directional split. Genuine information needs BOTH sides to converge.
        for side, mask in (("undervalued (px<iv)", d.r_t < 1), ("overvalued  (px>iv)", d.r_t > 1)):
            sub = d[mask]
            if len(sub) < 100:
                continue
            a = _conv_rate(sub.r_t.values, sub.r_fut.values)
            sn = []
            for _ in range(N_SHUFFLES):
                # Draw the substitute return from the FULL cross-section, not just this side --
                # sampling within "undervalued" would import that side's return distribution and
                # re-contaminate the null.
                ret_s = d.groupby("as_of")["ret"].transform(lambda x: RNG.permutation(x.values))
                ret_s = ret_s.loc[sub.index]
                sn.append(_conv_rate(sub.r_t.values, (sub.r_t * (1.0 + ret_s)).values))
            asym.append({"horizon": label, "side": side, "n": len(sub), "actual": a,
                         "null": float(np.mean(sn)), "edge_pp": 100 * (a - float(np.mean(sn)))})

    print("=" * 88)
    print("1. CONVERGENCE vs SHUFFLED-INTRINSIC NULL  (edge_pp is the number that matters)")
    print("=" * 88)
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

    print("\n" + "=" * 88)
    print("2. DIRECTIONAL SPLIT — the discriminating test")
    print("   Genuine information requires BOTH sides to beat their null.")
    print("   Drift converges only the undervalued side and works AGAINST the overvalued side.")
    print("=" * 88)
    print(pd.DataFrame(asym).to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

    print("\n" + "=" * 88)
    print("3. VERDICT vs the committed prediction")
    print("=" * 88)
    # Two questions, deliberately not collapsed into one threshold. An earlier version used a
    # single 5pp cutoff and printed "no real convergence" for a +4.1pp edge with z ~ 14 that
    # survived sector matching -- which is real information, just weak. Report both readings.
    a = pd.DataFrame(asym)
    print("\n  Q1: does the DCF carry per-name information? (edge over null on BOTH sides)")
    for h in HORIZONS:
        u = a[(a.horizon == h) & (a.side.str.startswith("undervalued"))]
        o = a[(a.horizon == h) & (a.side.str.startswith("overvalued"))]
        if u.empty or o.empty:
            continue
        ue, oe = float(u.edge_pp.iloc[0]), float(o.edge_pp.iloc[0])
        both = ue > 0 and oe > 0
        print(f"    {h}: undervalued {ue:+.2f}pp, overvalued {oe:+.2f}pp -> "
              f"{'YES, both sides beat null' if both else 'no — one side fails'}")

    print("\n  Q2: is it strong enough to anchor on? (ABSOLUTE convergence rate)")
    for r in rows:
        print(f"    {r['horizon']}: prices converge toward intrinsic {r['actual']:.1%} of the time "
              f"-> diverge {1 - r['actual']:.1%}")
    print("\n  Those are different questions and can both be answered honestly at once:")
    print("  a real but weak tilt is not the same as a reliable valuation anchor.")

    # ---- Phase 4: calibration-in-the-large -------------------------------------------------
    # Does the edge concentrate where the DCF's claim is STRONG? Same null, bucketed by the size
    # of the predicted gap. Deliberately still a ratio question: bucketing by upside and comparing
    # realised RETURNS would reintroduce the survivorship exposure the Phase 2 design avoided.
    print("\n" + "=" * 88)
    print("4. CALIBRATION-IN-THE-LARGE — does the edge grow where the predicted gap is bigger?")
    print("   Bucketed WITHIN direction. Pooled gap buckets are confounded: MAX_INTRINSIC_TO_PRICE")
    print("   = 2.5 caps intrinsic/price, so px/iv >= 0.4 and the UNDERVALUED gap cannot exceed")
    print("   60%. Every pooled bucket above 60% is therefore 100% overvalued -- the side with the")
    print("   stronger edge -- so a pooled 'large gap' spike is a direction effect in disguise.")
    print("=" * 88)

    BUCKETS = {
        "undervalued (px<iv)": ([0, 0.10, 0.25, 0.40, 0.60], ["<10%", "10-25%", "25-40%", "40-60%"]),
        "overvalued  (px>iv)": ([0, 0.25, 0.60, 1.50, np.inf], ["<25%", "25-60%", "60-150%", ">150%"]),
    }
    cal = []
    for label, months in HORIZONS.items():
        d = frames.get(label)
        if d is None or d.empty:
            continue
        for side, (edges, names) in BUCKETS.items():
            sub_all = d[d.r_t < 1] if side.startswith("undervalued") else d[d.r_t > 1]
            if sub_all.empty:
                continue
            gap = (sub_all.r_t - 1.0).abs()
            sub_all = sub_all.assign(gb=pd.cut(gap, edges, labels=names))
            for b, sub in sub_all.groupby("gb", observed=True):
                if len(sub) < 200:
                    continue
                a = _conv_rate(sub.r_t.values, sub.r_fut.values)
                sn = []
                for _ in range(N_SHUFFLES):
                    ret_s = d.groupby("as_of")["ret"].transform(lambda x: RNG.permutation(x.values))
                    sn.append(_conv_rate(sub.r_t.values,
                                         (sub.r_t * (1.0 + ret_s.loc[sub.index])).values))
                cal.append({"horizon": label, "side": side, "gap": str(b), "n": len(sub),
                            "actual": a, "null": float(np.mean(sn)),
                            "edge_pp": 100 * (a - float(np.mean(sn)))})
    # The crux. The >150% overvalued bucket is full of high-multiple names, and the VALUE EFFECT
    # already punishes those -- Phase 1 found near-zero incremental IC over earnings_yield. So the
    # edge there may be the DCF re-deriving the value premium rather than adding anything. Test it
    # the same way sector was tested: draw the substitute return from companies in the same
    # earnings_yield quintile at the same as-of date. If the edge survives, it is DCF-specific.
    print("\n  --- CRUX: does the big-gap edge survive an EARNINGS-YIELD-matched null? ---")
    print("  (if it vanishes, the DCF is re-deriving the value effect, not adding information)")
    ey_rows = []
    for label in HORIZONS:
        d = frames.get(label)
        if d is None or d.empty or "earnings_yield" not in d.columns:
            continue
        g = d.dropna(subset=["earnings_yield"]).copy()
        if g.empty:
            continue
        g["ey_q"] = g.groupby("as_of")["earnings_yield"].transform(
            lambda x: pd.qcut(x.rank(method="first"), 5, labels=False, duplicates="drop"))
        g = g.dropna(subset=["ey_q"])
        big = g[(g.r_t > 2.5)]          # the >150% overvalued bucket
        if len(big) < 200:
            continue
        a = _conv_rate(big.r_t.values, big.r_fut.values)
        plain, matched = [], []
        for _ in range(N_SHUFFLES):
            r_plain = g.groupby("as_of")["ret"].transform(lambda x: RNG.permutation(x.values))
            r_match = g.groupby(["as_of", "ey_q"])["ret"].transform(lambda x: RNG.permutation(x.values))
            plain.append(_conv_rate(big.r_t.values, (big.r_t * (1 + r_plain.loc[big.index])).values))
            matched.append(_conv_rate(big.r_t.values, (big.r_t * (1 + r_match.loc[big.index])).values))
        ey_rows.append({"horizon": label, "n": len(big), "actual": a,
                        "null_plain": float(np.mean(plain)), "null_ey_matched": float(np.mean(matched)),
                        "edge_plain_pp": 100 * (a - float(np.mean(plain))),
                        "edge_ey_matched_pp": 100 * (a - float(np.mean(matched)))})
    if ey_rows:
        print(pd.DataFrame(ey_rows).to_string(index=False, float_format=lambda x: f"{x:8.4f}"))

    c = pd.DataFrame(cal)
    for side, (_, names) in BUCKETS.items():
        cs = c[c.side == side]
        if cs.empty:
            continue
        print(f"\n  --- {side} ---")
        print("  edge over null (pp):")
        print(cs.pivot(index="horizon", columns="gap", values="edge_pp")
                .reindex(index=list(HORIZONS), columns=[n for n in names if n in set(cs.gap)])
                .to_string(float_format=lambda x: f"{x:8.2f}"))
        print("  absolute convergence rate:")
        print(cs.pivot(index="horizon", columns="gap", values="actual")
                .reindex(index=list(HORIZONS), columns=[n for n in names if n in set(cs.gap)])
                .to_string(float_format=lambda x: f"{x:8.3f}"))
        print("  n:")
        print(cs.pivot(index="horizon", columns="gap", values="n")
                .reindex(index=list(HORIZONS), columns=[n for n in names if n in set(cs.gap)])
                .to_string())


if __name__ == "__main__":
    main()
