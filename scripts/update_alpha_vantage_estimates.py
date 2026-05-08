#!/usr/bin/env python3
"""
Download latest Alpha Vantage analyst estimates for one ticker and store them.

Usage:
    uv run python scripts/update_alpha_vantage_estimates.py AAPL
    uv run python scripts/update_alpha_vantage_estimates.py
"""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from financial_statements_db import FinancialStatementsDB  # noqa: E402

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
DEFAULT_DB_PATH = ROOT / "data" / "financial_statements.duckdb"


def _f(value: Any) -> float | None:
    if value in (None, "", "None", "nan"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result


def _i(value: Any) -> int | None:
    result = _f(value)
    return int(result) if result is not None else None


def fetch_estimates(ticker: str, api_key: str) -> list[dict[str, Any]]:
    response = requests.get(
        ALPHA_VANTAGE_URL,
        params={
            "function": "EARNINGS_ESTIMATES",
            "symbol": ticker,
            "apikey": api_key,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    for key in ("Error Message", "Information", "Note"):
        if payload.get(key):
            raise RuntimeError(str(payload[key]))

    estimates = payload.get("estimates")
    if not isinstance(estimates, list):
        raise RuntimeError("Alpha Vantage response did not include an estimates list")
    return estimates


def store_estimates(db: FinancialStatementsDB, ticker: str, estimates: list[dict[str, Any]]) -> int:
    rows = [row for row in estimates if row.get("date") and row.get("horizon")]
    if not rows:
        return 0

    fetched_at = datetime.now(UTC)

    db.conn.execute("DELETE FROM earnings_estimates WHERE ticker = ?", [ticker])
    for row in rows:
        db.conn.execute(
            """
            INSERT INTO earnings_estimates (
                ticker, date, horizon, fetched_at,
                eps_avg, eps_high, eps_low, eps_count,
                eps_avg_7d, eps_avg_30d, eps_avg_60d, eps_avg_90d,
                eps_rev_up_7d, eps_rev_down_7d, eps_rev_up_30d, eps_rev_down_30d,
                rev_avg, rev_high, rev_low, rev_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ticker,
                row.get("date"),
                row.get("horizon"),
                fetched_at,
                _f(row.get("eps_estimate_average")),
                _f(row.get("eps_estimate_high")),
                _f(row.get("eps_estimate_low")),
                _i(row.get("eps_estimate_analyst_count")),
                _f(row.get("eps_estimate_average_7_days_ago")),
                _f(row.get("eps_estimate_average_30_days_ago")),
                _f(row.get("eps_estimate_average_60_days_ago")),
                _f(row.get("eps_estimate_average_90_days_ago")),
                _i(row.get("eps_estimate_revision_up_trailing_7_days")),
                _i(row.get("eps_estimate_revision_down_trailing_7_days")),
                _i(row.get("eps_estimate_revision_up_trailing_30_days")),
                _i(row.get("eps_estimate_revision_down_trailing_30_days")),
                _f(row.get("revenue_estimate_average")),
                _f(row.get("revenue_estimate_high")),
                _f(row.get("revenue_estimate_low")),
                _i(row.get("revenue_estimate_analyst_count")),
            ],
        )

    return len(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Alpha Vantage analyst estimates for one ticker into DuckDB."
    )
    parser.add_argument("ticker", nargs="?", help="Ticker symbol, e.g. AAPL")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="DuckDB path (default: data/financial_statements.duckdb)",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    args = parse_args()

    ticker = (args.ticker or input("Ticker: ")).strip().upper()
    if not ticker:
        print("Ticker is required", file=sys.stderr)
        return 2

    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("ALPHA_VANTAGE_API_KEY was not found in .env", file=sys.stderr)
        return 2

    try:
        estimates = fetch_estimates(ticker, api_key)
        if not estimates:
            print(f"No analyst estimates returned for {ticker}")
            return 1

        db = FinancialStatementsDB(args.db)
        try:
            inserted = store_estimates(db, ticker, estimates)
        finally:
            db.close()
    except Exception as exc:
        print(f"Failed to update analyst estimates for {ticker}: {exc}", file=sys.stderr)
        return 1

    print(f"Updated {inserted} analyst estimate rows for {ticker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
