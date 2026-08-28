#!/usr/bin/env python3
"""
Phase 3 factor gauntlet for the capex/R&D intensity ratios (PLAN_CAPEX_RD_RATIOS.md).

Tests four candidate factors, all already point-in-time by construction (Phase 1's
feature_available_date/reporting-lag discipline) — no external join needed, unlike the
MD&A gauntlet:
    capex_intensity            ttm_capex_intensity (level)
    capex_intensity_change_3y  ttm_capex_intensity - value 36 months prior, per ticker
    rd_intensity                ttm_rd_intensity (level)
    rd_intensity_change_3y      ttm_rd_intensity - value 36 months prior, per ticker

Direction is NOT assumed a priori — historic_fundamentals/pe.py's feature-direction
reference block explicitly flags these as "not unambiguously directional" (high capex/R&D
can mean wasteful overinvestment or a genuine growth advantage depending on company/sector),
unlike the margin factors it documents as safely "higher is better". lower_is_better=False
throughout; a negative mean IC is exactly as valid a result as a positive one here — it just
means the empirical relationship runs the other way.

Same two-part gauntlet as scripts/test_canslim_factors.py (IC test, quintile spread) plus a
simple in-sample/out-of-sample sign-stability check in the spirit of the MD&A gauntlet
(scripts/test_mda_features.py) — split the sample at its midpoint by month_end_date and
compare each factor's mean IC sign/magnitude between halves. A factor whose sign flips or
collapses OOS is not a real, stable effect (this is exactly how the MD&A composite was
rejected — see [[project_mda_factors_result]]).

Nothing here writes to historic_fundamentals/baselines.py or scripts/score_live.py — those
stay untouched until this result is reviewed and logged in docs/.

Usage:
    uv run scripts/test_capex_rd_factors.py
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
CAPEX_RD_FACTORS = {
    "capex_intensity":           ("ttm_capex_intensity",       False),
    "capex_intensity_change_3y": ("capex_intensity_change_3y", False),
    "rd_intensity":               ("ttm_rd_intensity",          False),
    "rd_intensity_change_3y":     ("rd_intensity_change_3y",    False),
}

BASE_COLS = ["ttm_capex_intensity", "ttm_rd_intensity"]


def _add_change_3y(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["ticker", "month_end_date"])
    df["capex_intensity_change_3y"] = df.groupby("ticker")["ttm_capex_intensity"].transform(
        lambda s: s - s.shift(36)
    )
    df["rd_intensity_change_3y"] = df.groupby("ticker")["ttm_rd_intensity"].transform(
        lambda s: s - s.shift(36)
    )
    return df


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
    missing = [c for c in BASE_COLS if c not in raw.columns]
    if missing:
        log.error("Missing columns %s — run PLAN_CAPEX_RD_RATIOS.md Phase 1 first.", missing)
        sys.exit(1)
    log.info("Loaded %d rows, %d tickers", len(raw), raw["ticker"].nunique())

    raw = _add_change_3y(raw)
    for name, (col, _) in CAPEX_RD_FACTORS.items():
        n = raw[col].notna().sum()
        log.info("  %-28s (%-26s) coverage %d/%d (%.1f%%)", name, col, n, len(raw), 100 * n / len(raw))

    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]

    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe (standard, financials/real-estate excluded): %d rows, %d tickers",
              len(universe), universe["ticker"].nunique())

    log.info("Computing forward returns (ret_6m, ret_1y) ...")
    universe = compute_forward_returns(universe, {"ret_6m": 6, "ret_1y": 12})

    # ── 1. IC test ──────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("1. IC TEST — capex/R&D intensity factors")
    print("=" * 78)
    for return_col in ("ret_1y", "ret_6m"):
        print(f"\n-- forward return: {return_col} --")
        table = _ic_table(universe, CAPEX_RD_FACTORS, return_col)
        print(table.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # ── 2. Quintile spread (ret_1y) ──────────────────────────────────────────
    print("\n" + "=" * 78)
    print("2. QUINTILE SPREAD (ret_1y) — Q1 (best) minus Q5 (worst), mean monthly")
    print("=" * 78)
    for name, (col, lower_is_better) in CAPEX_RD_FACTORS.items():
        if col not in universe.columns:
            continue
        qr = quintile_returns(universe, col, "ret_1y", lower_is_better=lower_is_better)
        if qr.empty:
            continue
        print(f"  {name:<28} Q1={qr['Q1'].mean():+7.2%}  Q5={qr['Q5'].mean():+7.2%}  "
              f"spread={qr['spread'].mean():+7.2%}  months={len(qr)}")

    # ── 3. In-sample / out-of-sample sign stability ──────────────────────────
    # Simple midpoint time split — same spirit as the MD&A gauntlet's IS/OOS check
    # (scripts/test_mda_features.py): a factor whose IC sign flips or collapses out of
    # sample is not a stable effect, regardless of how it looks on the full period.
    print("\n" + "=" * 78)
    print("3. IN-SAMPLE / OUT-OF-SAMPLE IC STABILITY (ret_1y, split at sample midpoint)")
    print("=" * 78)
    months = sorted(universe["month_end_date"].unique())
    split_date = months[len(months) // 2]
    is_df = universe[universe["month_end_date"] < split_date]
    oos_df = universe[universe["month_end_date"] >= split_date]
    print(f"Split date: {pd.Timestamp(split_date).date()}  "
          f"IS months={is_df['month_end_date'].nunique()}  OOS months={oos_df['month_end_date'].nunique()}")

    for name, (col, lower_is_better) in CAPEX_RD_FACTORS.items():
        if col not in universe.columns:
            continue
        is_ic = ic_summary(compute_factor_ic(is_df, col, "ret_1y", lower_is_better=lower_is_better))
        oos_ic = ic_summary(compute_factor_ic(oos_df, col, "ret_1y", lower_is_better=lower_is_better))
        same_sign = (
            is_ic["mean_ic"] == is_ic["mean_ic"] and oos_ic["mean_ic"] == oos_ic["mean_ic"]
            and (is_ic["mean_ic"] > 0) == (oos_ic["mean_ic"] > 0)
        )
        flag = "STABLE" if same_sign else "SIGN FLIP / UNSTABLE"
        print(f"  {name:<28} IS mean_ic={is_ic['mean_ic']:+.4f} (t={is_ic['t_stat']:+.2f})   "
              f"OOS mean_ic={oos_ic['mean_ic']:+.4f} (t={oos_ic['t_stat']:+.2f})   [{flag}]")

    print("\nDone.")


if __name__ == "__main__":
    main()
