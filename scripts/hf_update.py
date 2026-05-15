#!/usr/bin/env python3
"""
Monthly update: refresh PE timeseries and analyst estimates for all tickers
already in historic_fundamentals.duckdb.

Intended to run once per month (e.g. first business day of each month).
Only processes tickers already imported by hf_import.py. To add new tickers,
run hf_import.py first, then resume monthly updates with this script.

Usage:
    uv run scripts/hf_update.py                          # update all tickers
    uv run scripts/hf_update.py --ticker AAPL            # update one ticker
    uv run scripts/hf_update.py --skip-estimates         # PE only, no AV calls
    uv run scripts/hf_update.py --db PATH --verbose

Options:
    --ticker TICKER    Update a single ticker instead of all
    --skip-estimates   Skip EARNINGS_ESTIMATES API calls (PE recalculation only)
    --db PATH          Override data/historic_fundamentals.duckdb path
    --verbose          Show DEBUG-level output

What it does per ticker:
    1. Recomputes full PE timeseries from av_financials.duckdb (idempotent upsert)
    2. Recalculates pe_stats (long-term median, percentiles, rolling 5yr)
    3. Fetches fresh EARNINGS_ESTIMATES from Alpha Vantage (1 call/ticker)
    4. Updates forward_pe and forward_12m_eps in pe_stats

Examples:
    # Standard monthly run (PE + estimates, ~20 min for all tickers)
    uv run scripts/hf_update.py

    # Quick PE-only refresh after new av_financials data, no AV calls
    uv run scripts/hf_update.py --skip-estimates

    # Refresh a single ticker after manual av_financials update
    uv run scripts/hf_update.py --ticker TSLA
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
from historic_fundamentals.pe import process_ticker, enrich_goals, extract_goal_stats  # noqa: E402
from historic_fundamentals.estimates import (  # noqa: E402
    fetch_estimates, normalize_estimates, compute_forward_eps, compute_ntm_revenue,
)
from historic_fundamentals.sector import compute_sector_stats  # noqa: E402

log = logging.getLogger(__name__)


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


def _update_market_cap(hf_db: HistoricFundamentalsDB, av_conn, prices_conn, ticker: str) -> None:
    row = prices_conn.execute(
        "SELECT adj_close FROM stock_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    price = row[0] if row else None
    if not price:
        hf_db.update_market_cap(ticker, None)
        return
    row = av_conn.execute("""
        SELECT shares_outstanding_diluted FROM shares_outstanding
        WHERE ticker = ? AND shares_outstanding_diluted IS NOT NULL
        ORDER BY date DESC LIMIT 1
    """, [ticker]).fetchone()
    if not row:
        row = av_conn.execute("""
            SELECT common_stock_shares_outstanding FROM balance_sheets
            WHERE ticker = ? AND period_type = 'quarterly'
                AND common_stock_shares_outstanding IS NOT NULL
            ORDER BY fiscal_date_ending DESC LIMIT 1
        """, [ticker]).fetchone()
    shares = row[0] if row else None
    market_cap_b = (price * shares / 1e9) if shares and shares > 0 else None
    hf_db.update_market_cap(ticker, market_cap_b)


def _update_rev_ntm_growth_est(hf_db: HistoricFundamentalsDB, av_conn, ticker: str) -> None:
    ntm_rev = compute_ntm_revenue(hf_db.conn, ticker)
    if ntm_rev is None:
        hf_db.update_rev_ntm_growth_est(ticker, None)
        return
    row = av_conn.execute("""
        SELECT SUM(total_revenue) FROM (
            SELECT total_revenue FROM income_statements
            WHERE ticker = ? AND period_type = 'quarterly' AND total_revenue IS NOT NULL
            ORDER BY fiscal_date_ending DESC LIMIT 4
        )
    """, [ticker]).fetchone()
    ttm_rev = row[0] if row and row[0] else None
    growth = (ntm_rev / ttm_rev - 1.0) if ttm_rev and ttm_rev > 0 else None
    hf_db.update_rev_ntm_growth_est(ticker, growth)


def _update_earn_ntm_growth_est(hf_db: HistoricFundamentalsDB, ticker: str) -> None:
    row = hf_db.conn.execute(
        "SELECT forward_12m_eps, current_ttm_eps FROM pe_stats WHERE ticker = ?", [ticker]
    ).fetchone()
    if not row or row[0] is None:
        hf_db.update_earn_ntm_growth_est(ticker, None)
        return
    forward_eps, current_ttm_eps = row
    growth = (forward_eps / current_ttm_eps - 1.0) if current_ttm_eps and current_ttm_eps > 0 else None
    hf_db.update_earn_ntm_growth_est(ticker, growth)


def _update_forward_evebitda(
    hf_db: HistoricFundamentalsDB,
    av_conn,
    prices_conn,
    ticker: str,
) -> None:
    """
    Compute forward EV/EBITDA using the 5yr median EBITDA margin applied to NTM revenue.
    forward_EBITDA = NTM_revenue * ebitda_margin_5yr_median
    forward_EV/EBITDA = current_EV / forward_EBITDA
    current_EV = price * shares + total_debt - cash
    """
    row = hf_db.conn.execute(
        "SELECT ebitda_margin_5yr_median FROM pe_stats WHERE ticker = ?", [ticker]
    ).fetchone()
    if not row or row[0] is None:
        hf_db.update_forward_evebitda(ticker, None)
        return
    ebitda_margin = row[0]

    ntm_rev = compute_ntm_revenue(hf_db.conn, ticker)
    if not ntm_rev or ntm_rev <= 0:
        hf_db.update_forward_evebitda(ticker, None)
        return

    forward_ebitda = ntm_rev * ebitda_margin
    if forward_ebitda <= 0:
        hf_db.update_forward_evebitda(ticker, None)
        return

    price_row = prices_conn.execute(
        "SELECT adj_close FROM stock_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    if not price_row:
        hf_db.update_forward_evebitda(ticker, None)
        return
    price = price_row[0]

    shares_row = av_conn.execute("""
        SELECT shares_outstanding_diluted FROM shares_outstanding
        WHERE ticker = ? AND shares_outstanding_diluted IS NOT NULL
        ORDER BY date DESC LIMIT 1
    """, [ticker]).fetchone()
    if not shares_row:
        shares_row = av_conn.execute("""
            SELECT common_stock_shares_outstanding FROM balance_sheets
            WHERE ticker = ? AND period_type = 'quarterly'
                AND common_stock_shares_outstanding IS NOT NULL
            ORDER BY fiscal_date_ending DESC LIMIT 1
        """, [ticker]).fetchone()
    shares = shares_row[0] if shares_row else None

    if not shares or shares <= 0:
        hf_db.update_forward_evebitda(ticker, None)
        return

    # total_debt = long_term_debt_noncurrent + short_term_debt + current_long_term_debt
    debt_row = av_conn.execute("""
        SELECT
            COALESCE(long_term_debt_noncurrent, 0) +
            COALESCE(short_term_debt, 0) +
            COALESCE(current_long_term_debt, 0) AS total_debt,
            cash_and_short_term_investments
        FROM balance_sheets
        WHERE ticker = ? AND period_type = 'quarterly'
            AND (long_term_debt_noncurrent IS NOT NULL
                 OR short_term_debt IS NOT NULL
                 OR current_long_term_debt IS NOT NULL)
        ORDER BY fiscal_date_ending DESC LIMIT 1
    """, [ticker]).fetchone()
    if not debt_row:
        hf_db.update_forward_evebitda(ticker, None)
        return
    total_debt = debt_row[0] or 0.0
    cash = debt_row[1] or 0.0

    ev = price * shares + total_debt - cash
    if ev <= 0:
        hf_db.update_forward_evebitda(ticker, None)
        return

    forward_evebitda = ev / forward_ebitda
    hf_db.update_forward_evebitda(ticker, forward_evebitda)


def _update_forward_ps(
    hf_db: HistoricFundamentalsDB,
    av_conn,
    prices_conn,
    ticker: str,
) -> None:
    """Compute forward P/S = current market cap / NTM revenue."""
    ntm_rev = compute_ntm_revenue(hf_db.conn, ticker)
    if not ntm_rev or ntm_rev <= 0:
        hf_db.update_forward_ps(ticker, None)
        return

    price_row = prices_conn.execute(
        "SELECT adj_close FROM stock_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    if not price_row:
        hf_db.update_forward_ps(ticker, None)
        return
    price = price_row[0]

    shares_row = av_conn.execute("""
        SELECT shares_outstanding_diluted FROM shares_outstanding
        WHERE ticker = ? AND shares_outstanding_diluted IS NOT NULL
        ORDER BY date DESC LIMIT 1
    """, [ticker]).fetchone()
    if not shares_row:
        shares_row = av_conn.execute("""
            SELECT common_stock_shares_outstanding FROM balance_sheets
            WHERE ticker = ? AND period_type = 'quarterly'
                AND common_stock_shares_outstanding IS NOT NULL
            ORDER BY fiscal_date_ending DESC LIMIT 1
        """, [ticker]).fetchone()
    shares = shares_row[0] if shares_row else None

    if not shares or shares <= 0:
        hf_db.update_forward_ps(ticker, None)
        return

    hf_db.update_forward_ps(ticker, price * shares / ntm_rev)


def _update_forward_pfcf(
    hf_db: HistoricFundamentalsDB,
    av_conn,
    prices_conn,
    ticker: str,
) -> None:
    """
    Compute forward P/FCF using the 5yr median FCF margin applied to NTM revenue.
    forward_FCF = NTM_revenue * fcf_margin_5yr_median
    forward_P/FCF = current_price / (forward_FCF / shares)
    """
    row = hf_db.conn.execute(
        "SELECT fcf_margin_5yr_median FROM pe_stats WHERE ticker = ?", [ticker]
    ).fetchone()
    if not row or row[0] is None:
        hf_db.update_forward_pfcf(ticker, None)
        return
    fcf_margin = row[0]

    ntm_rev = compute_ntm_revenue(hf_db.conn, ticker)
    if not ntm_rev or ntm_rev <= 0:
        hf_db.update_forward_pfcf(ticker, None)
        return

    forward_fcf = ntm_rev * fcf_margin
    if forward_fcf <= 0:
        hf_db.update_forward_pfcf(ticker, None)
        return

    price_row = prices_conn.execute(
        "SELECT adj_close FROM stock_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    if not price_row:
        hf_db.update_forward_pfcf(ticker, None)
        return
    price = price_row[0]

    shares_row = av_conn.execute("""
        SELECT shares_outstanding_diluted FROM shares_outstanding
        WHERE ticker = ? AND shares_outstanding_diluted IS NOT NULL
        ORDER BY date DESC LIMIT 1
    """, [ticker]).fetchone()
    if not shares_row:
        shares_row = av_conn.execute("""
            SELECT common_stock_shares_outstanding FROM balance_sheets
            WHERE ticker = ? AND period_type = 'quarterly'
                AND common_stock_shares_outstanding IS NOT NULL
            ORDER BY fiscal_date_ending DESC LIMIT 1
        """, [ticker]).fetchone()
    shares = shares_row[0] if shares_row else None

    if not shares or shares <= 0:
        hf_db.update_forward_pfcf(ticker, None)
        return

    forward_fcf_per_share = forward_fcf / shares
    forward_pfcf = price / forward_fcf_per_share if forward_fcf_per_share > 0 else None
    hf_db.update_forward_pfcf(ticker, forward_pfcf)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monthly update of historic fundamentals.")
    parser.add_argument("--ticker", metavar="TICKER", help="Update a single ticker")
    parser.add_argument("--skip-estimates", action="store_true", help="Skip AV API calls for estimates")
    parser.add_argument("--skip-sector", action="store_true", help="Skip sector stats computation")
    parser.add_argument("--full-sector-rebuild", action="store_true", help="Recompute all historical sector stats")
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

    av_conn = duckdb.connect(av_db_path, read_only=True)
    prices_conn = duckdb.connect(prices_db_path, read_only=True)
    hf_db = HistoricFundamentalsDB(hf_db_path)
    limiter = RateLimiter() if not args.skip_estimates else None

    tickers = [args.ticker.upper()] if args.ticker else hf_db.list_tickers()
    if not tickers:
        log.warning("No tickers in DB. Run hf_import.py first.")
        av_conn.close()
        prices_conn.close()
        hf_db.close()
        return 1

    log.info("Updating %d ticker(s)", len(tickers))

    ok = failed = 0
    try:
        for i, ticker in enumerate(tickers, 1):
            prefix = f"[{i}/{len(tickers)}]"
            try:
                monthly_pe, stats = process_ticker(ticker, av_conn, prices_conn)

                # Fetch estimates before goal enrichment so PEG goal uses fresh data.
                if not args.skip_estimates:
                    raw = fetch_estimates(ticker, api_key, limiter)
                    rows = normalize_estimates(ticker, raw)
                    hf_db.upsert_estimates(ticker, rows)

                if not monthly_pe.empty:
                    if stats:
                        monthly_pe = enrich_goals(monthly_pe, stats, hf_db.conn, ticker)
                        stats.update(extract_goal_stats(monthly_pe))
                    hf_db.upsert_monthly_pe(ticker, monthly_pe)
                    if stats:
                        hf_db.upsert_pe_stats(stats)

                _update_forward_pe(hf_db, prices_conn, ticker)
                _update_rev_ntm_growth_est(hf_db, av_conn, ticker)
                _update_earn_ntm_growth_est(hf_db, ticker)
                _update_forward_pfcf(hf_db, av_conn, prices_conn, ticker)
                _update_forward_evebitda(hf_db, av_conn, prices_conn, ticker)
                _update_forward_ps(hf_db, av_conn, prices_conn, ticker)
                _update_market_cap(hf_db, av_conn, prices_conn, ticker)

                ok += 1
                log.info("%s %s — updated", prefix, ticker)
            except Exception as exc:
                log.error("%s %s — failed: %s", prefix, ticker, exc)
                failed += 1
        if not args.skip_sector and not args.ticker:
            try:
                log.info("Computing sector stats (full_rebuild=%s)...", args.full_sector_rebuild)
                sector_df = compute_sector_stats(hf_db.conn, av_db_path, full_rebuild=args.full_sector_rebuild)
                if not sector_df.empty:
                    n = hf_db.upsert_sector_stats(sector_df)
                    log.info("Sector stats: %d rows upserted", n)
                else:
                    log.info("Sector stats: no data (run av_import_overview.py first, or all months already computed)")
            except Exception as exc:
                log.error("Sector stats failed: %s", exc)
    finally:
        av_conn.close()
        prices_conn.close()
        hf_db.close()

    log.info("Update complete: %d ok, %d failed", ok, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
