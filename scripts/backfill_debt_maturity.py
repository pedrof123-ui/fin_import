"""
PLAN_DEBT_MATURITY.md Phase 2 (single-ticker refresh) / Phase 5 (full-universe batch).

Fetches a ticker's latest 10-K, parses its debt tranches (scripts/fetch_debt_maturity.py),
computes the weighted-average summary (debt_maturity/summary.py), and stores both in
data/debt_maturity.duckdb. A ticker with no coverage (~1/3 of the universe, see
docs/debt_maturity_coverage.md) still gets its stale rows cleared and simply has no
summary row -- that's the expected outcome, not an error.

Usage: uv run scripts/backfill_debt_maturity.py TICKER [TICKER ...]
"""

from typing import Optional

from debt_maturity import db
from debt_maturity.summary import compute_summary
from scripts.fetch_debt_maturity import extract_debt_tranches


def refresh_ticker(ticker: str, conn=None) -> Optional[dict]:
    """Refresh one ticker's debt_tranches + debt_maturity_summary. Returns the summary
    dict, or None if the ticker has no coverage (nothing to summarize)."""
    ticker = ticker.upper()
    owns_conn = conn is None
    conn = conn or db.open_db()
    try:
        tranches = extract_debt_tranches(ticker)
        db.delete_ticker(conn, ticker)
        if not tranches:
            return None
        db.save_tranches(conn, ticker, tranches)

        fiscal_year = max(t["fiscal_year"] for t in tranches if t.get("fiscal_year"))
        summary = compute_summary(tranches, fiscal_year)
        db.save_summary(conn, ticker, summary)
        return summary
    finally:
        if owns_conn:
            conn.close()


if __name__ == "__main__":
    import argparse
    import os

    from dotenv import load_dotenv

    load_dotenv()
    from edgar import set_identity

    set_identity(os.getenv("SEC_ID"))

    p = argparse.ArgumentParser()
    p.add_argument("tickers", nargs="+")
    args = p.parse_args()

    conn = db.open_db()
    try:
        for ticker in args.tickers:
            summary = refresh_ticker(ticker.upper(), conn=conn)
            print(ticker.upper(), summary or "no coverage")
    finally:
        conn.close()
