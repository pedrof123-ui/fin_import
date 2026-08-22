#!/usr/bin/env python3
"""
Monthly batch: run the DCF model for every ticker and cache the result in
historic_fundamentals.duckdb::dcf_results, for the Screener's DCF-upside filter.

Intended to run once per month, right after hf_update.py in run_pipeline.py, so the
cache refreshes whenever fundamentals refresh.

Usage:
    uv run scripts/compute_dcf_batch.py                    # all tickers in company_overview
    uv run scripts/compute_dcf_batch.py --tickers AAPL,JPM,WMT
    uv run scripts/compute_dcf_batch.py --verbose

Writes one row per ticker to dcf_results (status='ok' or 'error'), full rebuild each
run — a ticker that fails this run overwrites any previous 'ok' row for it, matching
hf_update.py's rebuild style rather than an incremental merge.

The same rows are also appended to dcf_results_history keyed by snapshot date, so the
output of each rebuild survives the next one. dcf_results alone cannot be backtested:
every rebuild overwrites it, and it does not record the price the valuation was made
against. See archive/PLAN_DCF_ACCURACY.md.
"""

import argparse
import logging
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH as AV_DB_PATH  # noqa: E402
from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH, HistoricFundamentalsDB  # noqa: E402
from dcf.model import run_dcf_av  # noqa: E402

log = logging.getLogger(__name__)


def _list_tickers(av_db_path: str) -> list[str]:
    conn = duckdb.connect(av_db_path, read_only=True)
    try:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT ticker FROM company_overview ORDER BY ticker"
        ).fetchall()]
    finally:
        conn.close()


_PROGRESS_EVERY = 200


def compute_dcf_batch(tickers: list[str], estimates_conn) -> pd.DataFrame:
    rows = []
    # Progress at INFO every _PROGRESS_EVERY tickers. The per-ticker line below is DEBUG, so a
    # ~2,600-ticker run otherwise emits nothing between start and finish across many minutes, and
    # a working job cannot be told apart from a hung one. Same reason the walk-forward gained
    # fold-level logging.
    for i, ticker in enumerate(tickers, 1):
        if i % _PROGRESS_EVERY == 0 or i == len(tickers):
            n_err = sum(1 for r in rows if r["status"] == "error")
            log.info("  %d/%d done (%d error so far)", i, len(tickers), n_err)
        log.debug("[%d/%d] %s", i, len(tickers), ticker)
        now = datetime.now(UTC)
        try:
            result = run_dcf_av(ticker, estimates_conn=estimates_conn)
            rows.append({
                "ticker": ticker,
                "intrinsic_value_per_share": result.intrinsic_value_per_share,
                "price_at_computation": result.current_price,
                "wacc": result.wacc_detail.wacc,
                "beta_raw": result.wacc_detail.beta_raw,
                "terminal_growth_rate": result.terminal_growth_rate,
                "tv_pct_enterprise_value": result.tv_pct_enterprise_value,
                "enterprise_value": result.enterprise_value,
                "net_debt": result.net_debt,
                "diluted_shares": result.diluted_shares,
                "analyst_years_applied": result.analyst_years_applied,
                "status": "ok",
                "error_message": None,
                "computed_at": now,
            })
        except Exception as e:
            log.debug("  %s failed: %s", ticker, e)
            rows.append({
                "ticker": ticker,
                "intrinsic_value_per_share": None,
                "price_at_computation": None,
                "wacc": None,
                "beta_raw": None,
                "terminal_growth_rate": None,
                "tv_pct_enterprise_value": None,
                "enterprise_value": None,
                "net_debt": None,
                "diluted_shares": None,
                "analyst_years_applied": None,
                "status": "error",
                "error_message": str(e)[:500],
                "computed_at": now,
            })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch DCF computation for the Screener's dcf_upside filter.")
    parser.add_argument("--tickers", help="Comma-separated tickers (default: all in company_overview)")
    parser.add_argument("--av-db", default=AV_DB_PATH, help="Override av_financials.duckdb path")
    parser.add_argument("--hf-db", default=HF_DB_PATH, help="Override historic_fundamentals.duckdb path")
    parser.add_argument("--verbose", action="store_true", help="Show DEBUG-level output")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(message)s")

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else _list_tickers(args.av_db)
    if not tickers:
        print("No tickers found.", file=sys.stderr)
        sys.exit(1)

    print(f"Running DCF for {len(tickers)} ticker(s)...", flush=True)
    t0 = time.time()

    hf_db = HistoricFundamentalsDB(args.hf_db)
    df = compute_dcf_batch(tickers, hf_db.conn)

    n_written = hf_db.upsert_dcf_results(df)
    df["snapshot_date"] = date.today()
    n_hist = hf_db.upsert_dcf_results_history(df)
    hf_db.close()

    elapsed = time.time() - t0
    n_ok = int((df["status"] == "ok").sum())
    n_error = int((df["status"] == "error").sum())
    print(f"\nDone: {n_ok} ok, {n_error} error, {n_written} rows written to dcf_results, "
          f"{n_hist} to dcf_results_history ({elapsed:.1f}s)")
    if n_error:
        print("\nErrors:")
        for _, row in df[df["status"] == "error"].iterrows():
            print(f"  {row['ticker']}: {row['error_message']}")


if __name__ == "__main__":
    main()
