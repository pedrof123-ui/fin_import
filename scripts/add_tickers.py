#!/usr/bin/env python3
"""
Add new tickers: fetch all AV data and compute all derived metrics in one pass.

For each ticker this script:
    1. Fetches income / balance / cashflow statements  -> av_financials.duckdb
    2. Fetches shares outstanding                      -> av_financials.duckdb
    3. Fetches dividend history                        -> av_financials.duckdb
    4. Computes monthly PE timeseries                  -> historic_fundamentals.duckdb
    5. Fetches analyst earnings estimates              -> historic_fundamentals.duckdb
    6. Computes forward PE from estimates              -> pe_stats

Use this script when adding new tickers.  For monthly refreshes of existing
tickers use av_update.py + hf_update.py instead.

Source (pick one):
    uv run scripts/add_tickers.py AAPL MSFT GOOGL
    uv run scripts/add_tickers.py --csv data/new_tickers.csv

Options:
    --force            Re-import tickers already in the DB (AV side) and
                       recompute all derived metrics.
    --skip-estimates   Skip EARNINGS_ESTIMATES API calls.
    --verbose          Show DEBUG-level output.

Rate: 5-6 AV API calls per ticker (3 statements + shares + dividends + estimates).
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH as AV_DB_PATH, AVFinancialsDB, RateLimiter  # noqa: E402
from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH, HistoricFundamentalsDB  # noqa: E402
from historic_fundamentals.pe import process_ticker  # noqa: E402
from historic_fundamentals.estimates import fetch_estimates, normalize_estimates, compute_forward_eps, compute_ntm_revenue  # noqa: E402

log = logging.getLogger(__name__)


def _tickers_from_csv(path: str) -> list[str]:
    tickers: list[str] = []
    with open(path) as f:
        for line in f:
            val = line.split(",")[0].strip().strip('"').upper()
            if val and not val.startswith("#"):
                tickers.append(val)
    if tickers and not tickers[0].isalpha():
        tickers = tickers[1:]
    return tickers


def _update_forward_pe(hf_db: HistoricFundamentalsDB, prices_conn, ticker: str) -> None:
    forward_eps = compute_forward_eps(hf_db.conn, ticker)
    if forward_eps and forward_eps > 0:
        row = prices_conn.execute(
            "SELECT adj_close FROM stock_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            [ticker],
        ).fetchone()
        price = row[0] if row else None
        forward_pe = price / forward_eps if price else None
    else:
        forward_pe = None
    hf_db.update_forward_pe(ticker, forward_pe, forward_eps)


def _update_rev_ntm_growth_est(hf_db: HistoricFundamentalsDB, av_db, ticker: str) -> None:
    ntm_rev = compute_ntm_revenue(hf_db.conn, ticker)
    if ntm_rev is None:
        hf_db.update_rev_ntm_growth_est(ticker, None)
        return
    row = av_db.conn.execute("""
        SELECT SUM(total_revenue) FROM (
            SELECT total_revenue FROM income_statements
            WHERE ticker = ? AND period_type = 'quarterly' AND total_revenue IS NOT NULL
            ORDER BY fiscal_date_ending DESC LIMIT 4
        )
    """, [ticker]).fetchone()
    ttm_rev = row[0] if row and row[0] else None
    growth = (ntm_rev / ttm_rev - 1.0) if ttm_rev and ttm_rev > 0 else None
    hf_db.update_rev_ntm_growth_est(ticker, growth)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add new tickers: fetch all AV data and compute all derived metrics."
    )
    parser.add_argument("tickers", nargs="*", metavar="TICKER")
    parser.add_argument("--csv", metavar="FILE", help="CSV file with tickers in first column")
    parser.add_argument("--force", action="store_true", help="Re-import even if already in DB")
    parser.add_argument("--skip-estimates", action="store_true", help="Skip EARNINGS_ESTIMATES calls")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        log.error("ALPHA_VANTAGE_API_KEY not found in .env")
        return 2

    prices_db_path = os.getenv("PRICES_DB_PATH")
    if not prices_db_path:
        log.error("PRICES_DB_PATH not set in .env")
        return 2

    av_db_path = os.getenv("AV_DB_PATH") or AV_DB_PATH
    hf_db_path = os.getenv("HF_DB_PATH") or HF_DB_PATH

    if args.csv:
        tickers = _tickers_from_csv(args.csv)
        if not tickers:
            log.error("No tickers found in %s", args.csv)
            return 2
        log.info("Loaded %d tickers from %s", len(tickers), args.csv)
    elif args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        log.error("Provide tickers or --csv")
        return 2

    av_db = AVFinancialsDB(av_db_path)
    prices_conn = duckdb.connect(prices_db_path, read_only=True)
    hf_db = HistoricFundamentalsDB(hf_db_path)
    limiter = RateLimiter()

    ok = failed = skipped = 0

    try:
        for i, ticker in enumerate(tickers, 1):
            prefix = f"[{i}/{len(tickers)}]"

            # ── Step 1-3: AV raw data ──────────────────────────────────────────
            if not args.force and av_db.has_ticker(ticker):
                log.info("%s %s — AV data already present (use --force to re-fetch)", prefix, ticker)
                skipped += 1
            else:
                ticker_ok = True
                try:
                    rows = av_db.import_ticker(ticker, api_key, limiter)
                    log.debug("%s %s — statements: %d rows", prefix, ticker, rows)
                except Exception as exc:
                    log.error("%s %s — statements failed: %s", prefix, ticker, exc)
                    ticker_ok = False

                try:
                    n = av_db.import_shares_outstanding(ticker, api_key, limiter)
                    log.debug("%s %s — shares: %d rows", prefix, ticker, n)
                except Exception as exc:
                    log.error("%s %s — shares failed: %s", prefix, ticker, exc)
                    ticker_ok = False

                try:
                    n = av_db.import_dividends(ticker, api_key, limiter)
                    log.debug("%s %s — dividends: %d rows", prefix, ticker, n)
                except Exception as exc:
                    log.error("%s %s — dividends failed: %s", prefix, ticker, exc)
                    ticker_ok = False

                if not ticker_ok:
                    log.error("%s %s — AV import failed; skipping derived metrics", prefix, ticker)
                    failed += 1
                    continue

            # ── Step 4: PE timeseries ──────────────────────────────────────────
            try:
                monthly_pe, stats = process_ticker(ticker, av_db.conn, prices_conn)
                if monthly_pe.empty:
                    log.warning("%s %s — no PE data computed (missing financials or prices?)", prefix, ticker)
                else:
                    hf_db.upsert_monthly_pe(ticker, monthly_pe)
                    if stats:
                        hf_db.upsert_pe_stats(stats)
                    log.debug("%s %s — PE: %d months", prefix, ticker, len(monthly_pe))
            except Exception as exc:
                log.error("%s %s — PE computation failed: %s", prefix, ticker, exc)
                failed += 1
                continue

            # ── Step 5-6: Estimates + forward PE ──────────────────────────────
            if not args.skip_estimates:
                try:
                    raw = fetch_estimates(ticker, api_key, limiter)
                    est_rows = normalize_estimates(ticker, raw)
                    hf_db.upsert_estimates(ticker, est_rows)
                    _update_forward_pe(hf_db, prices_conn, ticker)
                    _update_rev_ntm_growth_est(hf_db, av_db, ticker)
                    log.debug("%s %s — estimates: %d rows", prefix, ticker, len(est_rows))
                except Exception as exc:
                    log.error("%s %s — estimates failed: %s", prefix, ticker, exc)
                    failed += 1
                    continue

            ok += 1
            log.info("%s %s — done", prefix, ticker)

    finally:
        av_db.close()
        prices_conn.close()
        hf_db.close()

    log.info("Done: %d ok, %d skipped (already in DB), %d failed", ok, skipped, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
