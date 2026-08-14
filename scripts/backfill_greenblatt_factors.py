#!/usr/bin/env python3
"""
Backfill ebit_ev_yield and greenblatt_roc into monthly_pe.

Experimental factors from Greenblatt's "Magic Formula" (The Little Book That
Still Beats the Market, Appendix):

    ebit_ev_yield  = TTM EBIT / Enterprise Value
                      EV = ev_ebitda * ttm_ebitda (both already in monthly_pe,
                      so no new EV computation is needed here).

    greenblatt_roc = TTM EBIT / (Net Working Capital + Net Fixed Assets)
                      NWC   = (total_current_assets - cash) -
                              (total_current_liabilities - short_term_debt - current_long_term_debt)
                      NFA   = property_plant_equipment (net, as reported)
                      Excludes goodwill/intangibles from capital employed, per the
                      book's definition, unlike the existing `roic` column (NOPAT /
                      (equity + debt - cash)), which does not.

Point-in-time safe: uses the same trailing-4Q-with-annual-fallback TTM logic as
the rest of the pipeline (_get_ttm_sum), and the latest balance sheet <= month_end,
for every month_end_date already present in monthly_pe.

This is an EXPERIMENTAL feature test — see docs/greenblatt_factors_test.md for the
IC/backtest results. These columns are not wired into the live composite score
(historic_fundamentals/baselines.py _VALUE_COLS/_QUALITY_COLS) until validated.

Usage:
    uv run scripts/backfill_greenblatt_factors.py
    uv run scripts/backfill_greenblatt_factors.py --dry-run
    uv run scripts/backfill_greenblatt_factors.py --limit 50 --verbose
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from historic_fundamentals.pe import _load_av_data, _get_ttm_sum  # noqa: E402

log = logging.getLogger(__name__)


def _tangible_capital(month_end, quarterly: pd.DataFrame, annual: pd.DataFrame) -> float | None:
    """Net Working Capital + Net Fixed Assets from the latest balance sheet <= month_end.

    NWC excludes cash (not needed to run the business) and short-term
    interest-bearing debt (an obligation, not a working-capital funding source)
    from current liabilities, per Greenblatt's magic formula definition.
    Returns None if current-asset/liability data is unavailable for this date.
    """
    for df in (quarterly, annual):
        if df.empty:
            continue
        avail = df[df["fiscal_date_ending"] <= month_end]
        if avail.empty:
            continue
        row = avail.iloc[-1]
        tca = row.get("total_current_assets")
        tcl = row.get("total_current_liabilities")
        if pd.isna(tca) or pd.isna(tcl):
            continue
        cash = row.get("cash")
        std = row.get("short_term_debt")
        cltd = row.get("current_long_term_debt")
        ppe = row.get("property_plant_equipment")
        nwc = (
            (float(tca) - (float(cash) if pd.notna(cash) else 0.0))
            - (float(tcl) - (float(std) if pd.notna(std) else 0.0) - (float(cltd) if pd.notna(cltd) else 0.0))
        )
        net_fixed = float(ppe) if pd.notna(ppe) else 0.0
        return nwc + net_fixed
    return None


def _compute_for_ticker(ticker: str, month_ends: list, av_conn) -> pd.DataFrame:
    quarterly, annual = _load_av_data(av_conn, ticker)
    if quarterly.empty and annual.empty:
        return pd.DataFrame(columns=["ticker", "month_end_date", "ttm_ebit", "greenblatt_roc"])

    # Match build_monthly_pe's convention: fiscal_date_ending as python date,
    # comparable to the python-date month_ends passed in.
    for df in (quarterly, annual):
        if not df.empty:
            df["fiscal_date_ending"] = pd.to_datetime(df["fiscal_date_ending"]).dt.date

    rows = []
    for month_end in month_ends:
        ttm_ebit = _get_ttm_sum(month_end, "ebit", quarterly, annual)
        tangible_capital = _tangible_capital(month_end, quarterly, annual)
        roc = (
            ttm_ebit / tangible_capital
            if ttm_ebit is not None and tangible_capital is not None and tangible_capital > 0
            else None
        )
        rows.append({
            "ticker": ticker,
            "month_end_date": month_end,
            "ttm_ebit": ttm_ebit,
            "greenblatt_roc": roc,
        })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Greenblatt magic-formula factors into monthly_pe.")
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
    for col in ("ebit_ev_yield", "greenblatt_roc"):
        hf_conn.execute(f"ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS {col} DOUBLE")

    log.info("Loading monthly_pe (ticker, month_end_date, ev_ebitda, ttm_ebitda) ...")
    base = hf_conn.execute(
        "SELECT ticker, month_end_date, ev_ebitda, ttm_ebitda FROM monthly_pe ORDER BY ticker, month_end_date"
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
        log.error("No rows computed — aborting.")
        hf_conn.close()
        sys.exit(1)

    merged = base.merge(out, on=["ticker", "month_end_date"], how="left")
    merged["ebit_ev_yield"] = merged["ttm_ebit"] / (merged["ev_ebitda"] * merged["ttm_ebitda"])
    merged.loc[~((merged["ev_ebitda"].notna()) & (merged["ttm_ebitda"] > 0)), "ebit_ev_yield"] = pd.NA

    total = len(merged)
    for col in ("ebit_ev_yield", "greenblatt_roc"):
        n = merged[col].notna().sum()
        log.info("  %-16s %d / %d  (%.1f%%)", col, n, total, 100 * n / total)

    if args.dry_run:
        log.info("Dry run — no changes written.")
        hf_conn.close()
        return

    log.info("Writing columns back to monthly_pe ...")
    write_cols = ["ticker", "month_end_date", "ebit_ev_yield", "greenblatt_roc"]
    hf_conn.register("_tmp_gb", merged[write_cols])
    hf_conn.execute("""
        UPDATE monthly_pe
        SET
            ebit_ev_yield  = g.ebit_ev_yield,
            greenblatt_roc = g.greenblatt_roc
        FROM _tmp_gb g
        WHERE monthly_pe.ticker         = g.ticker
          AND monthly_pe.month_end_date = g.month_end_date
    """)
    hf_conn.execute("DROP VIEW IF EXISTS _tmp_gb")

    updated = hf_conn.execute(
        "SELECT COUNT(*) FROM monthly_pe WHERE ebit_ev_yield IS NOT NULL OR greenblatt_roc IS NOT NULL"
    ).fetchone()[0]
    log.info("Rows with at least one factor populated: %d", updated)

    hf_conn.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
