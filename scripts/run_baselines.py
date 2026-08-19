#!/usr/bin/env python3
"""
Run rank-based baseline factor models on the full investable universe.

This script:
1. Loads monthly_pe from HF_DB_PATH
2. Joins sector from AV_DB_PATH (company_overview)
3. Computes market_cap = shares * price
4. Applies filter_universe() with UNIVERSE_DEFAULTS
5. Computes forward returns (ret_1y, ret_6m) using the same logic as notebook Cell 3
6. Runs run_all_baselines() for ret_1y and ret_6m
7. Prints summary tables and writes docs/baseline_results.md

Usage:
    uv run scripts/run_baselines.py
    uv run scripts/run_baselines.py --min-cap 300e6
    uv run scripts/run_baselines.py --help

Environment variables required:
    HF_DB_PATH     path to historic_fundamentals.duckdb
    AV_DB_PATH     path to av_financials.duckdb (for company_overview sector join)

Optional:
    PRICES_DB_PATH  not used by this script (prices come from monthly_pe)
"""

from __future__ import annotations

import argparse
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
    run_all_baselines,
)

log = logging.getLogger(__name__)

RETURN_HORIZONS = {"ret_6m": 6, "ret_1y": 12}


def _load_monthly_pe(hf_db_path: str) -> pd.DataFrame:
    import duckdb
    conn = duckdb.connect(hf_db_path, read_only=True)
    df = conn.execute("SELECT * FROM monthly_pe ORDER BY ticker, month_end_date").df()
    conn.close()
    df["month_end_date"] = pd.to_datetime(df["month_end_date"])
    return df


def _join_sector(df: pd.DataFrame, av_db_path: str) -> pd.DataFrame:
    """Join sector from company_overview if not already present."""
    if "sector" in df.columns and df["sector"].notna().any():
        return df
    try:
        import duckdb
        conn = duckdb.connect(av_db_path, read_only=True)
        overview = conn.execute(
            "SELECT ticker, sector, fetch_date FROM company_overview ORDER BY fetch_date"
        ).df()
        conn.close()
        # See run_backtest.py: dedupe to the latest snapshot per ticker or the merge fans out.
        overview = overview.drop_duplicates(subset=["ticker"], keep="last").drop(columns=["fetch_date"])
        df = df.merge(overview, on="ticker", how="left")
        log.info("Joined sector from company_overview: %d tickers with sector", df["sector"].notna().sum())
    except Exception as exc:
        log.warning("Could not join sector from AV_DB_PATH: %s", exc)
    return df


def _build_summary_table(label: str, summary: pd.DataFrame) -> str:
    lines = [f"\n## Baseline factor summary — {label}\n"]
    lines.append("```")
    lines.append(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run rank-based baseline factor models on the investable universe."
    )
    parser.add_argument(
        "--min-cap",
        type=float,
        default=None,
        help="Minimum market cap override (default: UNIVERSE_DEFAULTS['min_market_cap'] = 1e9)",
    )
    parser.add_argument(
        "--min-price",
        type=float,
        default=None,
        help="Minimum share price override (default: 5.0)",
    )
    parser.add_argument(
        "--no-sector-filter",
        action="store_true",
        help="Disable the sector filter (allow rows without sector).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show DEBUG-level logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))

    if not Path(hf_db).exists():
        log.error("HF_DB_PATH not found: %s", hf_db)
        sys.exit(1)

    log.info("Loading monthly_pe from %s", hf_db)
    raw = _load_monthly_pe(hf_db)
    log.info("Loaded %d rows, %d tickers", len(raw), raw["ticker"].nunique())

    raw = _join_sector(raw, av_db)

    raw["market_cap"] = raw["shares"] * raw["price"]

    universe_kwargs = {**UNIVERSE_DEFAULTS}
    if args.min_cap is not None:
        universe_kwargs["min_market_cap"] = args.min_cap
    if args.min_price is not None:
        universe_kwargs["min_price"] = args.min_price
    if args.no_sector_filter:
        universe_kwargs["require_sector"] = False

    log.info("Applying universe filters: %s", universe_kwargs)
    universe = filter_universe(raw, **universe_kwargs)
    log.info("Universe: %d rows, %d tickers after filtering", len(universe), universe["ticker"].nunique())

    log.info("Computing forward returns ...")
    df = compute_forward_returns(universe, RETURN_HORIZONS)
    for col in RETURN_HORIZONS:
        valid = df[col].notna().sum()
        log.info("  %s: %d valid rows", col, valid)

    output_sections = ["# Baseline Factor Results\n"]
    output_sections.append(
        f"Universe: {universe['ticker'].nunique()} tickers | "
        f"min_market_cap={universe_kwargs['min_market_cap']:.0f} | "
        f"min_price={universe_kwargs['min_price']:.2f}\n"
    )

    for return_col in ["ret_1y", "ret_6m"]:
        if df[return_col].notna().sum() < 20:
            log.warning("Skipping %s: fewer than 20 valid forward-return rows", return_col)
            continue

        log.info("Running baselines for %s ...", return_col)
        summary = run_all_baselines(df, return_col=return_col)

        print(f"\n{'=' * 70}")
        print(f"Baseline results — {return_col}")
        print("=" * 70)
        print(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

        output_sections.append(_build_summary_table(return_col, summary))

    docs_dir = ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)
    out_path = docs_dir / "baseline_results.md"
    out_path.write_text("\n".join(output_sections))
    log.info("Wrote results to %s", out_path)


if __name__ == "__main__":
    main()
