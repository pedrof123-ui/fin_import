#!/usr/bin/env python3
"""
Backfill historic fundamentals (PE history + earnings estimates) for all tickers.

Run this once to populate data/historic_fundamentals.duckdb. After the initial
backfill, use hf_update.py for monthly refreshes.

Source (pick one):
    uv run scripts/hf_import.py                    # all tickers in av_financials.duckdb
    uv run scripts/hf_import.py AAPL MSFT          # specific tickers
    uv run scripts/hf_import.py --csv FILE         # first column of a CSV file

Options:
    --force            Recalculate tickers already in the DB (default: skip existing)
    --skip-estimates   Skip EARNINGS_ESTIMATES API calls; PE history only, no AV calls
    --db PATH          Override data/historic_fundamentals.duckdb path
    --verbose          Show DEBUG-level output (individual ticker detail)

What it does per ticker:
    1. Reads net_income + shares from av_financials.duckdb (no AV API calls)
    2. Computes monthly PE back ~20 years (quarterly TTM, annual fallback)
    3. Computes rolling 5yr median PE per month and long-term stats
    4. Fetches EARNINGS_ESTIMATES from Alpha Vantage (1 call/ticker, ~20 min total)
    5. Computes and stores forward 12M PE from analyst estimates

Examples:
    # Full backfill: PE history + estimates for all tickers (~20 min for estimates)
    uv run scripts/hf_import.py

    # PE history only, no AV API calls (fast, a few minutes for all tickers)
    uv run scripts/hf_import.py --skip-estimates

    # Force recalculate specific tickers
    uv run scripts/hf_import.py AAPL MSFT --force

    # Import from CSV, skip estimates
    uv run scripts/hf_import.py --csv data/test_tickers.csv --skip-estimates

    # Use a custom DB path
    uv run scripts/hf_import.py AAPL --db data/my_hf.duckdb
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

from av_financials_db import DEFAULT_DB_PATH as AV_DB_PATH, RateLimiter  # noqa: E402
from historic_fundamentals.db import DEFAULT_DB_PATH as HF_DB_PATH, HistoricFundamentalsDB  # noqa: E402
from historic_fundamentals.pe import process_ticker  # noqa: E402
from historic_fundamentals.estimates import (  # noqa: E402
    fetch_estimates, normalize_estimates, compute_forward_eps,
)

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill historic fundamentals.")
    parser.add_argument("tickers", nargs="*", metavar="TICKER", help="Ticker symbols")
    parser.add_argument("--csv", metavar="FILE", help="CSV file with tickers in first column")
    parser.add_argument("--force", action="store_true", help="Recalculate tickers already in DB")
    parser.add_argument("--skip-estimates", action="store_true", help="Skip AV API calls for estimates")
    parser.add_argument("--db", default=None, metavar="PATH", help="Override DB path")
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

    api_key = None
    if not args.skip_estimates:
        api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        if not api_key:
            log.error("ALPHA_VANTAGE_API_KEY not found in .env (use --skip-estimates to skip)")
            return 2

    av_db_path = os.getenv("AV_DB_PATH") or AV_DB_PATH
    prices_db_path = os.getenv("PRICES_DB_PATH")
    if not prices_db_path:
        log.error("PRICES_DB_PATH not set in .env")
        return 2

    hf_db_path = args.db or os.getenv("HF_DB_PATH") or HF_DB_PATH

    sources = sum([bool(args.tickers), bool(args.csv)])
    if sources > 1:
        log.error("Provide only one of: tickers or --csv")
        return 2

    av_conn = duckdb.connect(av_db_path, read_only=True)
    prices_conn = duckdb.connect(prices_db_path, read_only=True)
    hf_db = HistoricFundamentalsDB(hf_db_path)
    limiter = RateLimiter() if not args.skip_estimates else None

    if args.csv:
        tickers = _tickers_from_csv(args.csv)
        if not tickers:
            log.error("No tickers found in %s", args.csv)
            return 2
        log.info("Loaded %d tickers from %s", len(tickers), args.csv)
    elif args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        rows = av_conn.execute("SELECT ticker FROM companies ORDER BY ticker").fetchall()
        tickers = [r[0] for r in rows]
        log.info("Loaded %d tickers from av_financials", len(tickers))

    if not tickers:
        log.error("No tickers to process")
        return 2

    existing = set(hf_db.list_tickers()) if not args.force else set()

    pe_ok = pe_skip = pe_fail = 0
    est_ok = est_fail = 0

    try:
        for i, ticker in enumerate(tickers, 1):
            prefix = f"[{i}/{len(tickers)}]"

            # PE phase
            if not args.force and ticker in existing:
                log.info("%s %s — skipped (already in DB; use --force to recalculate)", prefix, ticker)
                pe_skip += 1
            else:
                try:
                    monthly_pe, stats = process_ticker(ticker, av_conn, prices_conn)
                    if monthly_pe.empty:
                        log.warning("%s %s — no PE data computed", prefix, ticker)
                        pe_fail += 1
                    else:
                        n = hf_db.upsert_monthly_pe(ticker, monthly_pe)
                        if stats:
                            hf_db.upsert_pe_stats(stats)
                        pe_ok += 1
                        log.info("%s %s — %d PE months", prefix, ticker, n)
                except Exception as exc:
                    log.error("%s %s — PE failed: %s", prefix, ticker, exc)
                    pe_fail += 1
                    continue

            # Estimates phase
            if args.skip_estimates:
                continue
            try:
                raw = fetch_estimates(ticker, api_key, limiter)
                rows = normalize_estimates(ticker, raw)
                hf_db.upsert_estimates(ticker, rows)
                _update_forward_pe(hf_db, prices_conn, ticker)
                est_ok += 1
                log.info("%s %s — %d estimate rows", prefix, ticker, len(rows))
            except Exception as exc:
                log.error("%s %s — estimates failed: %s", prefix, ticker, exc)
                est_fail += 1

    finally:
        av_conn.close()
        prices_conn.close()
        hf_db.close()

    log.info(
        "Done: PE %d ok / %d skipped / %d failed | Estimates %d ok / %d failed",
        pe_ok, pe_skip, pe_fail, est_ok, est_fail,
    )
    return 0 if pe_fail == 0 and est_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
