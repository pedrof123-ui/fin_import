#!/usr/bin/env python3
"""Interactive REPL for IB trading.

Launch:
    uv run scripts/ib_repl.py

Environment variables (in .env):
    IB_HOST, IB_PORT, IB_CLIENT_ID, IB_ACCOUNT
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from ib_trader.client import IBClient
from ib_trader.interactive import run_repl


def main() -> None:
    with IBClient() as client:
        run_repl(client)


if __name__ == "__main__":
    main()
