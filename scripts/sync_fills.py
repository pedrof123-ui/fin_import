"""Sync IB execution history to the portfolio tracker database.

Usage:
    uv run scripts/sync_fills.py --strategy fundamentals_alpha
    uv run scripts/sync_fills.py --strategy fundamentals_alpha --since 2026-01-01
    uv run scripts/sync_fills.py --strategy ibd_50 --since 2026-04-01
    uv run scripts/sync_fills.py --strategy fundamentals_alpha --update-forward-returns
    uv run scripts/sync_fills.py --strategy fundamentals_alpha --dry-run
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from ib_trader.client import IBClient
from ib_trader.tracker import init_tracker_db, record_nav, sync_ib_fills, update_forward_returns


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync IB fills to portfolio tracker DB")
    parser.add_argument("--strategy", required=True, help="Strategy name (e.g. fundamentals_alpha)")
    parser.add_argument(
        "--since",
        default=None,
        help="Only sync fills on or after this date (YYYY-MM-DD). Default: 90 days ago",
    )
    parser.add_argument(
        "--update-forward-returns",
        action="store_true",
        help="Fill in 30-day forward returns for score snapshots older than 30 days",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Connect to IB and print fills that would be inserted; do not write to DB",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    since_date: date | None = None
    if args.since:
        since_date = datetime.strptime(args.since, "%Y-%m-%d").date()
    else:
        from datetime import timedelta
        since_date = date.today() - timedelta(days=90)

    print(f"Strategy:   {args.strategy}")
    print(f"Since date: {since_date}")
    print(f"Dry run:    {args.dry_run}")

    conn = init_tracker_db()

    if args.dry_run:
        print("\nDry-run mode: connecting to IB to preview fills (no DB writes).")
        with IBClient() as client:
            fills = client.ib.reqExecutions()
            new_fills = []
            for fill in fills:
                fill_time = datetime.strptime(fill.execution.time, "%Y%m%d %H:%M:%S")
                if fill_time.date() < since_date:
                    continue
                exec_id = fill.execution.execId
                exists = conn.execute(
                    "SELECT 1 FROM fills WHERE exec_id = ?", [exec_id]
                ).fetchone()
                if not exists:
                    new_fills.append({
                        "exec_id": exec_id,
                        "ticker": fill.contract.symbol,
                        "action": "BUY" if fill.execution.side == "BOT" else "SELL",
                        "qty": fill.execution.shares,
                        "price": fill.execution.price,
                        "time": fill_time,
                    })

        if new_fills:
            import pandas as pd
            print(f"\n{len(new_fills)} new fill(s) would be inserted:")
            print(pd.DataFrame(new_fills).to_string(index=False))
        else:
            print("\nNo new fills to insert.")
        conn.close()
        return

    # Live sync
    print("\nConnecting to IB...")
    with IBClient() as client:
        count = sync_ib_fills(client, conn, args.strategy, since_date=since_date)
        try:
            nav = client.get_nav()
            record_nav(conn, args.strategy, nav)
            print(f"Recorded NAV ${nav:,.0f} to tracker DB.")
        except Exception as exc:
            print(f"Warning: could not record NAV: {exc}")

    if count > 0:
        print(f"Inserted {count} new fill(s) for strategy '{args.strategy}'.")
    else:
        print("No new fills found.")

    if args.update_forward_returns:
        print("\nUpdating forward returns for score snapshots...")
        updated = update_forward_returns(conn, args.strategy)
        if updated > 0:
            print(f"Updated forward_return for {updated} score snapshot row(s).")
        else:
            print("No score snapshots ready for forward return update yet.")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
