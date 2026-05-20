#!/usr/bin/env python3
"""CLI for portfolio rebalancing via Interactive Brokers.

Usage:
    uv run scripts/rebalance.py                                      # dry run, auto-find latest scores CSV
    uv run scripts/rebalance.py --scores PATH                        # dry run, explicit scores CSV
    uv run scripts/rebalance.py --no-dry-run                         # submit orders
    uv run scripts/rebalance.py --status                             # show account status and exit
    uv run scripts/rebalance.py --cancel-all                         # cancel all open orders and exit
    uv run scripts/rebalance.py --tracker-db data/ib_tracker_paper.duckdb  # override tracker DB

Environment variables (in .env):
    IB_HOST, IB_PORT, IB_CLIENT_ID, IB_ACCOUNT, IB_TRACKER_DB
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from ib_trader.client import IBClient
from ib_trader.interactive import _print_status
from ib_trader.orders import cancel_all_open_orders
from ib_trader.portfolio import find_latest_scores, load_scores_csv
from ib_trader.rebalance import run_rebalance

log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="IB portfolio rebalancer")
    parser.add_argument("--scores", default=None,
                        help="Path to live_scores CSV (default: auto-find latest in docs/)")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True,
                        help="Preview orders without submitting (default: on)")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                        help="Submit orders to IB")
    parser.add_argument("--order-type", default="MOC", choices=["MOC", "MKT", "LMT"],
                        help="Order type (default: MOC)")
    parser.add_argument("--strategy", default="fundamentals_alpha",
                        help="Strategy tag written to IB orderRef (default: fundamentals_alpha)")
    parser.add_argument("--tracker-db", default=None,
                        help="Path to tracker DuckDB (overrides IB_TRACKER_DB env var)")
    parser.add_argument("--cancel-all", action="store_true",
                        help="Cancel all open orders and exit")
    parser.add_argument("--status", action="store_true",
                        help="Show account status and exit")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    with IBClient() as client:
        if args.status:
            _print_status(client)
            return

        if args.cancel_all:
            n = cancel_all_open_orders(client)
            print(f"Cancelled {n} open order(s).")
            return

        # Resolve scores path
        if args.scores:
            scores_path = args.scores
        else:
            latest = find_latest_scores(ROOT)
            if not latest:
                log.error(
                    "No live_scores CSV found in docs/. "
                    "Run 'uv run scripts/score_live.py' first, or pass --scores PATH."
                )
                sys.exit(1)
            scores_path = str(latest)
            log.info("Using latest scores: %s", scores_path)

        ranked_df = load_scores_csv(scores_path)
        if ranked_df.empty:
            log.error("No portfolio positions found in %s.", scores_path)
            sys.exit(1)

        log.info("Loaded %d portfolio positions from %s", len(ranked_df), scores_path)
        run_rebalance(ranked_df, client, order_type=args.order_type,
                      dry_run=args.dry_run, strategy=args.strategy)

        # Record end-of-rebalance NAV to tracker (live runs only)
        tracker_db = args.tracker_db or os.getenv("IB_TRACKER_DB")
        if not args.dry_run and tracker_db:
            try:
                from ib_trader.tracker import init_tracker_db, record_nav
                nav = client.get_nav()
                tracker_conn = init_tracker_db(tracker_db)
                record_nav(tracker_conn, args.strategy, nav)
                tracker_conn.close()
                log.info("Recorded NAV $%,.0f to tracker DB.", nav)
            except Exception as exc:
                log.warning("Could not record NAV to tracker: %s", exc)


if __name__ == "__main__":
    main()
