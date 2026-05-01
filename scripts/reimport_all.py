"""
Re-import all tickers currently in the database.

For each ticker: imports 10 annual (10-K) + 20 quarterly (10-Q) filings,
forcing re-extraction even for periods that already exist.

Usage:
    uv run scripts/reimport_all.py
    uv run scripts/reimport_all.py --annual-only
    uv run scripts/reimport_all.py --tickers MSFT AAPL
"""

import asyncio
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
from financial_statements_db import FinancialStatementsDB
from api.importer import import_ticker


def get_all_tickers(db_path: str = "data/financial_statements.duckdb") -> list[str]:
    conn = duckdb.connect(db_path, read_only=True)
    rows = conn.execute("SELECT DISTINCT ticker FROM companies ORDER BY ticker").fetchall()
    conn.close()
    return [r[0] for r in rows]


async def reimport_ticker(ticker: str, db: FinancialStatementsDB, annual_only: bool) -> dict:
    results = {}

    try:
        results["annual"] = await import_ticker(ticker, periods=10, period_type="FY", db=db, force=True)
    except Exception as e:
        results["annual"] = {"status": "error", "error": str(e)}

    if not annual_only:
        try:
            results["quarterly"] = await import_ticker(ticker, periods=20, period_type="Q", db=db, force=True)
        except Exception as e:
            results["quarterly"] = {"status": "error", "error": str(e)}

    return results


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--annual-only", action="store_true", help="Skip quarterly re-import")
    parser.add_argument("--tickers", nargs="+", metavar="TICKER", help="Re-import specific tickers only")
    args = parser.parse_args()

    tickers = args.tickers if args.tickers else get_all_tickers()
    if not tickers:
        print("No tickers found in database.")
        return

    print(f"Re-importing {len(tickers)} ticker(s): {', '.join(tickers)}")
    print(f"Mode: {'annual only' if args.annual_only else '10 annual + 20 quarterly'}\n")

    db = FinancialStatementsDB()
    success, failed = 0, 0
    t0 = time.time()

    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {ticker}")
        try:
            result = await reimport_ticker(ticker, db, args.annual_only)
            annual = result.get("annual", {})
            quarterly = result.get("quarterly", {})
            ann_ok = annual.get("filings_processed", 0)
            ann_fail = annual.get("filings_failed", 0)
            q_ok = quarterly.get("filings_processed", 0) if quarterly else 0
            q_fail = quarterly.get("filings_failed", 0) if quarterly else 0
            print(f"  annual: {ann_ok} ok / {ann_fail} failed  |  quarterly: {q_ok} ok / {q_fail} failed")
            success += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s — {success} tickers ok, {failed} failed.")


if __name__ == "__main__":
    asyncio.run(main())
