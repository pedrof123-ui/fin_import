#!/usr/bin/env python3
"""Interactive REPL for IB trading.

Launch:
    uv run scripts/ib_repl.py
    uv run scripts/ib_repl.py --strategy vw_gr_top_n_25 --tracker-db data/ib_tracker_paper.duckdb

Environment variables (in .env):
    IB_HOST, IB_PORT, IB_CLIENT_ID, IB_ACCOUNT

Pass --tracker-db so 'rebalance'/'preview' can scope NAV and positions to this
strategy instead of the whole shared account. Without it, those commands refuse
to run rather than silently sizing against the full account NAV.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from ib_trader.client import IBClient
from ib_trader.interactive import run_repl
from ib_trader.tracker import init_tracker_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive REPL for IB trading.")
    parser.add_argument("--strategy", default="fundamentals_alpha",
                        help="Strategy tag for buy/sell/rebalance commands (default: fundamentals_alpha)")
    parser.add_argument("--tracker-db", default=None,
                        help="Path to tracker DuckDB, needed for 'rebalance'/'preview' commands")
    args = parser.parse_args()

    tracker_conn = init_tracker_db(args.tracker_db) if args.tracker_db else None

    with IBClient() as client:
        run_repl(client, strategy=args.strategy, tracker_conn=tracker_conn)

    if tracker_conn:
        tracker_conn.close()


if __name__ == "__main__":
    main()
