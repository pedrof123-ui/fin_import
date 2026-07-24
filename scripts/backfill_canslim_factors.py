#!/usr/bin/env python3
"""
Backfill CANSLIM factor columns into monthly_pe.

Phase 1 (this pass): C -- current-quarter earnings acceleration.
    q_earn_yoy   = latest reported quarter's EPS YoY growth, as of month_end
    q_earn_accel = q_earn_yoy(latest quarter) - q_earn_yoy(quarter before that)
                   positive = earnings growth is accelerating, the O'Neil-specific
                   signal beyond plain single-quarter growth.

EPS per quarter = net_income / diluted shares outstanding as of that quarter's
fiscal_date_ending (via historic_fundamentals.pe._get_shares), not a single
current share count -- this lets buyback-driven EPS growth show up distinctly
from net-income growth, same distinction O'Neil's "C" criterion cares about.

Point-in-time safe: mirrors build_monthly_pe's reporting-lag policy exactly
(quarterly fiscal_date_ending + 60 days <= month_end) rather than the shallower
"fiscal_date_ending <= month_end" filter used by backfill_greenblatt_factors.py.

This is an EXPERIMENTAL feature test -- see CANSLIM_FACTOR_TEST_PLAN.md and
(once written) docs/canslim_factors_test.md for the IC/backtest results. These
columns are not wired into the live composite score
(historic_fundamentals/baselines.py _VALUE_COLS/_QUALITY_COLS) until validated.

Usage:
    uv run scripts/backfill_canslim_factors.py
    uv run scripts/backfill_canslim_factors.py --dry-run
    uv run scripts/backfill_canslim_factors.py --limit 50 --verbose
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from historic_fundamentals.pe import _load_av_data, _load_shares_ts, _get_shares  # noqa: E402

log = logging.getLogger(__name__)

_LAG_QUARTERLY = timedelta(days=60)


def _quarter_eps(fde, quarterly: pd.DataFrame, annual: pd.DataFrame, shares_ts: pd.DataFrame) -> float | None:
    """Single-quarter EPS = net_income for that fiscal_date_ending / diluted shares as of that date."""
    row = quarterly[quarterly["fiscal_date_ending"] == fde]
    if row.empty:
        return None
    ni = row.iloc[0].get("net_income")
    if pd.isna(ni):
        return None
    sh = _get_shares(fde, shares_ts, quarterly, annual)
    if sh is None or sh <= 0:
        return None
    return float(ni) / sh


def _yoy(eps_latest: float | None, eps_prior_year: float | None) -> float | None:
    """YoY growth, defined only when the prior-year base is positive (matches earn_growth_1yr convention)."""
    if eps_latest is None or eps_prior_year is None or eps_prior_year <= 0:
        return None
    return eps_latest / eps_prior_year - 1


def _compute_for_ticker(ticker: str, month_ends: list, av_conn) -> pd.DataFrame:
    quarterly, annual = _load_av_data(av_conn, ticker)
    if quarterly.empty:
        return pd.DataFrame(columns=["ticker", "month_end_date", "q_earn_yoy", "q_earn_accel"])

    quarterly["fiscal_date_ending"] = pd.to_datetime(quarterly["fiscal_date_ending"]).dt.date
    if not annual.empty:
        annual["fiscal_date_ending"] = pd.to_datetime(annual["fiscal_date_ending"]).dt.date
    quarterly = quarterly.sort_values("fiscal_date_ending").reset_index(drop=True)

    shares_ts = _load_shares_ts(av_conn, ticker)
    if not shares_ts.empty:
        shares_ts["date"] = pd.to_datetime(shares_ts["date"]).dt.date

    rows = []
    for month_end in month_ends:
        q_pit = quarterly[quarterly["fiscal_date_ending"] + _LAG_QUARTERLY <= month_end]
        if len(q_pit) < 5:
            rows.append({"ticker": ticker, "month_end_date": month_end, "q_earn_yoy": None, "q_earn_accel": None})
            continue

        fdes = q_pit["fiscal_date_ending"].tolist()
        # indices: n (latest), n-1, n-4, n-5 (0-indexed from the end)
        fde_n, fde_n1, fde_n4, fde_n5 = fdes[-1], fdes[-2], fdes[-5], fdes[-6] if len(fdes) >= 6 else None

        eps_n = _quarter_eps(fde_n, q_pit, annual, shares_ts)
        eps_n4 = _quarter_eps(fde_n4, q_pit, annual, shares_ts)
        q_earn_yoy = _yoy(eps_n, eps_n4)

        q_earn_accel = None
        if fde_n5 is not None:
            eps_n1 = _quarter_eps(fde_n1, q_pit, annual, shares_ts)
            eps_n5 = _quarter_eps(fde_n5, q_pit, annual, shares_ts)
            q_earn_yoy_prior = _yoy(eps_n1, eps_n5)
            if q_earn_yoy is not None and q_earn_yoy_prior is not None:
                q_earn_accel = q_earn_yoy - q_earn_yoy_prior

        rows.append({
            "ticker": ticker,
            "month_end_date": month_end,
            "q_earn_yoy": q_earn_yoy,
            "q_earn_accel": q_earn_accel,
        })

    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill CANSLIM 'C' factors into monthly_pe.")
    parser.add_argument("--db", default=None, help="Path to historic_fundamentals.duckdb")
    parser.add_argument("--av-db", default=None, help="Path to av_financials.duckdb")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N tickers (testing)")
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not write")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    hf_db = args.db or os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = args.av_db or os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    log.info("HF_DB: %s", hf_db)
    log.info("AV_DB: %s", av_db)

    hf_conn = duckdb.connect(hf_db)
    for col in ("q_earn_yoy", "q_earn_accel"):
        hf_conn.execute(f"ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS {col} DOUBLE")

    log.info("Loading monthly_pe (ticker, month_end_date) ...")
    base = hf_conn.execute(
        "SELECT ticker, month_end_date FROM monthly_pe ORDER BY ticker, month_end_date"
    ).df()
    base["month_end_date"] = pd.to_datetime(base["month_end_date"]).dt.date
    log.info("Loaded %d rows, %d tickers", len(base), base["ticker"].nunique())

    tickers = base["ticker"].unique().tolist()
    if args.limit:
        tickers = tickers[: args.limit]
        log.info("Limiting to first %d tickers", len(tickers))

    av_conn = duckdb.connect(av_db, read_only=True)

    results = []
    t0 = time.time()
    for i, ticker in enumerate(tickers, 1):
        month_ends = base.loc[base["ticker"] == ticker, "month_end_date"].tolist()
        try:
            res = _compute_for_ticker(ticker, month_ends, av_conn)
        except Exception as exc:
            log.warning("Ticker %s failed: %s", ticker, exc)
            continue
        results.append(res)
        if i % 200 == 0 or i == len(tickers):
            elapsed = time.time() - t0
            log.info("Processed %d / %d tickers (%.0fs elapsed)", i, len(tickers), elapsed)

    av_conn.close()

    out = pd.concat(results, ignore_index=True) if results else pd.DataFrame()
    if out.empty:
        log.error("No rows computed -- aborting.")
        hf_conn.close()
        sys.exit(1)

    total = len(out)
    for col in ("q_earn_yoy", "q_earn_accel"):
        n = out[col].notna().sum()
        log.info("  %-16s %d / %d  (%.1f%%)", col, n, total, 100 * n / total)

    if args.dry_run:
        log.info("Dry run -- no changes written.")
        hf_conn.close()
        return

    log.info("Writing columns back to monthly_pe ...")
    hf_conn.register("_tmp_canslim_c", out)
    hf_conn.execute("""
        UPDATE monthly_pe
        SET
            q_earn_yoy   = c.q_earn_yoy,
            q_earn_accel = c.q_earn_accel
        FROM _tmp_canslim_c c
        WHERE monthly_pe.ticker         = c.ticker
          AND monthly_pe.month_end_date = c.month_end_date
    """)
    hf_conn.execute("DROP VIEW IF EXISTS _tmp_canslim_c")

    updated = hf_conn.execute(
        "SELECT COUNT(*) FROM monthly_pe WHERE q_earn_yoy IS NOT NULL OR q_earn_accel IS NOT NULL"
    ).fetchone()[0]
    log.info("Rows with at least one factor populated: %d", updated)

    hf_conn.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
