"""
PLAN_DEBT_MATURITY.md Phase 2 (single-ticker refresh) / Phase 4 (full-universe batch).

Fetches a ticker's latest 10-K, parses its debt tranches (scripts/fetch_debt_maturity.py),
computes the weighted-average summary (debt_maturity/summary.py), and stores both in
data/debt_maturity.duckdb. A ticker with no coverage (~2/3 of the universe, see
docs/debt_maturity_coverage.md) still gets its stale rows cleared and simply has no
summary row -- that's the expected outcome, not an error.

Usage:
    uv run scripts/backfill_debt_maturity.py TICKER [TICKER ...]
    uv run scripts/backfill_debt_maturity.py --universe [--concurrency 5] [--resume] [--limit N]

--universe pulls the same ticker list used for the Phase 0 coverage sample (latest
company_overview row per ticker, market_cap not null and > 0, from av_financials.duckdb).
Progress is appended line-by-line to --progress-log so a Ctrl-C'd run can be picked back up
with --resume (skips tickers already logged, regardless of outcome). edgartools self-throttles
per-request to SEC's fair-access limit (see bulk_import_10k.py), so --concurrency controls
parallel tickers, not raw request rate; Phase 0's coverage check validated 5 concurrent.
"""

import asyncio
import csv
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from debt_maturity import db
from debt_maturity.summary import compute_summary
from scripts.fetch_debt_maturity import extract_debt_tranches

DEFAULT_PROGRESS_LOG = Path("data/debt_maturity_backfill_progress.csv")


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


def get_universe_tickers() -> list[str]:
    """Same universe definition as scripts/debt_maturity_coverage_check.py's Phase 0
    sample, just unfiltered: latest company_overview row per ticker with a market cap."""
    import duckdb

    con = duckdb.connect("data/av_financials.duckdb", read_only=True)
    rows = con.execute(
        """
        select ticker
        from (
            select ticker, market_cap,
                   row_number() over (partition by ticker order by fetch_date desc) as rn
            from company_overview
            where market_cap is not null and market_cap > 0
        )
        where rn = 1
        order by ticker
        """
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


async def backfill_universe(
    tickers: list[str], conn, concurrency: int, progress_log: Path, resume: bool
) -> None:
    done: set[str] = set()
    if resume and progress_log.exists():
        with open(progress_log) as f:
            done = {row["ticker"] for row in csv.DictReader(f)}
        print(f"Resuming: {len(done)} tickers already logged in {progress_log}")

    todo = [t for t in tickers if t not in done]
    print(f"{len(todo)}/{len(tickers)} tickers to process (concurrency={concurrency})")

    is_new_log = not progress_log.exists()
    log_f = open(progress_log, "a", newline="")
    writer = csv.writer(log_f)
    if is_new_log:
        writer.writerow(["ticker", "status", "error"])
        log_f.flush()

    sem = asyncio.Semaphore(concurrency)
    counts = {"coverage": 0, "no_coverage": 0, "error": 0}
    start = time.time()

    async def process(i: int, ticker: str) -> None:
        async with sem:
            t0 = time.time()
            status, error = "no_coverage", ""
            try:
                tranches = await asyncio.to_thread(extract_debt_tranches, ticker)
                db.delete_ticker(conn, ticker)
                if tranches:
                    db.save_tranches(conn, ticker, tranches)
                    fiscal_year = max(t["fiscal_year"] for t in tranches if t.get("fiscal_year"))
                    summary = compute_summary(tranches, fiscal_year)
                    db.save_summary(conn, ticker, summary)
                    status = "coverage"
            except Exception as e:
                status, error = "error", str(e)[:200]
            counts[status if status != "error" else "error"] += 1
            writer.writerow([ticker, status, error])
            log_f.flush()
            elapsed = time.time() - t0
            print(f"[{i}/{len(todo)}] {ticker:8s} {status:12s} {elapsed:.1f}s"
                  + (f"  ({error})" if error else ""))

    await asyncio.gather(*[process(i, t) for i, t in enumerate(todo, 1)])
    log_f.close()

    total_elapsed = time.time() - start
    print(
        f"\nDone in {total_elapsed / 60:.1f}m: {counts['coverage']} with coverage, "
        f"{counts['no_coverage']} without, {counts['error']} errors"
    )


if __name__ == "__main__":
    import argparse
    import os

    from dotenv import load_dotenv

    load_dotenv()
    from edgar import set_identity

    set_identity(os.getenv("SEC_ID"))

    p = argparse.ArgumentParser()
    p.add_argument("tickers", nargs="*")
    p.add_argument("--universe", action="store_true", help="Process the full ticker universe")
    p.add_argument("--concurrency", type=int, default=5)
    p.add_argument("--limit", type=int, help="Cap the universe list (smoke-testing)")
    p.add_argument("--resume", action="store_true", help="Skip tickers already in the progress log")
    p.add_argument("--progress-log", type=Path, default=DEFAULT_PROGRESS_LOG)
    args = p.parse_args()

    conn = db.open_db()
    try:
        if args.universe:
            tickers = get_universe_tickers()
            if args.limit:
                tickers = tickers[: args.limit]
            asyncio.run(
                backfill_universe(tickers, conn, args.concurrency, args.progress_log, args.resume)
            )
        else:
            if not args.tickers:
                p.error("pass TICKER(s), or --universe for a full-universe run")
            for ticker in args.tickers:
                summary = refresh_ticker(ticker.upper(), conn=conn)
                print(ticker.upper(), summary or "no coverage")
    finally:
        conn.close()
