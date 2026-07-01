from __future__ import annotations

from pathlib import Path

from .orders import cancel_all_open_orders, get_order_status, place_order
from .portfolio import find_latest_scores, load_scores_csv
from .rebalance import run_rebalance

_HELP = """
Commands:
  status                         Show NAV, positions, and open orders
  buy  TICKER QTY [TYPE [PRICE]] Buy shares  (default: MOC)
  sell TICKER QTY [TYPE [PRICE]] Sell shares (default: MOC)
  quote TICKER                   Show live bid / ask / last
  cancel ORDER_ID                Cancel a specific open order
  cancel all                     Cancel all open orders
  preview [PATH]                 Show rebalance diff without submitting
  rebalance [PATH]               Dry-run rebalance (latest CSV if no PATH)
  rebalance [PATH] --confirm     Submit rebalance orders
  help                           Show this help
  quit / exit                    Disconnect and exit

Order types: MOC (default), MKT, LMT
LMT example:  sell MSFT 30 LMT 450.00
"""


def _print_status(client) -> None:
    nav = client.get_nav()
    positions = client.get_positions()
    orders = get_order_status(client)
    account_type = "LIVE" if client.is_live() else "PAPER"
    print(f"\nAccount: {client.account} [{account_type}]  NAV: ${nav:,.0f}")
    if positions:
        print(f"\nPositions ({len(positions)}):")
        for ticker, shares in sorted(positions.items()):
            print(f"  {ticker:10s}  {shares:>8.0f} shares")
    else:
        print("\nNo positions.")
    if orders:
        print(f"\nOpen orders ({len(orders)}):")
        for o in orders:
            fill = f"  filled={o['filled']:.0f}" if o["filled"] else ""
            print(f"  #{o['order_id']}  {o['action']:4s} {o['qty']:>6.0f} {o['ticker']:10s}"
                  f"  {o['order_type']:3s}  {o['status']}{fill}")
    else:
        print("No open orders.")


def _print_quote(client, ticker: str) -> None:
    contracts = client.qualify_contracts([ticker])
    if not contracts:
        print(f"  {ticker}: could not qualify contract")
        return
    td = client.ib.reqMktData(contracts[ticker], "", True, False)
    client.ib.sleep(3.0)
    bid = getattr(td, "bid", None)
    ask = getattr(td, "ask", None)
    last = getattr(td, "last", None)
    close = getattr(td, "close", None)

    def fmt(v):
        return f"${v:.2f}" if v and v > 0 else "N/A"

    mid = (bid + ask) / 2 if bid and ask and bid > 0 and ask > 0 else None
    print(f"  {ticker}  bid={fmt(bid)}  ask={fmt(ask)}  last={fmt(last)}"
          + (f"  mid={fmt(mid)}" if mid else "")
          + (f"  prev_close={fmt(close)}" if close and close > 0 else ""))


def _handle_buy_sell(client, cmd: str, args: list[str], strategy: str) -> None:
    if len(args) < 2:
        print(f"Usage: {cmd} TICKER QTY [MKT|LMT price|MOC]")
        return
    ticker = args[0].upper()
    try:
        qty = int(args[1])
    except ValueError:
        print("QTY must be an integer.")
        return
    order_type = args[2].upper() if len(args) > 2 else "MOC"
    limit_price = None
    if order_type == "LMT":
        if len(args) < 4:
            print("LMT requires a price: sell TICKER QTY LMT 450.00")
            return
        try:
            limit_price = float(args[3])
        except ValueError:
            print("PRICE must be a number.")
            return

    trade = place_order(client, ticker, cmd.upper(), qty, order_type, limit_price, strategy)
    suffix = f" @ ${limit_price:.2f}" if limit_price else ""
    print(f"  Placed: {cmd.upper()} {qty} {ticker} {order_type}{suffix}"
          f"  order_id={trade.order.orderId}")


def _handle_cancel(client, args: list[str]) -> None:
    if not args:
        print("Usage: cancel ORDER_ID | cancel all")
        return
    if args[0].lower() == "all":
        n = cancel_all_open_orders(client)
        print(f"  Cancelled {n} order(s).")
        return
    try:
        order_id = int(args[0])
    except ValueError:
        print("ORDER_ID must be an integer, or 'all'.")
        return
    found = [t for t in client.ib.openTrades() if t.order.orderId == order_id]
    if not found:
        print(f"  Order {order_id} not found.")
    else:
        client.ib.cancelOrder(found[0].order)
        print(f"  Cancelled order {order_id}.")


def _handle_rebalance(client, args: list[str], dry_run: bool, strategy: str, tracker_conn) -> None:
    if tracker_conn is None:
        print("  No tracker DB connected — refusing to rebalance. Relaunch with "
              "'uv run scripts/ib_repl.py --tracker-db PATH' so NAV and positions "
              "can be scoped to this strategy instead of the whole shared account.")
        return

    from .tracker import get_latest_strategy_nav
    nav_override = get_latest_strategy_nav(tracker_conn, strategy)
    if nav_override is None:
        print(f"  No NAV recorded yet for strategy '{strategy}'. Run sync_fills.py once "
              f"first, or use scripts/rebalance.py --nav-override for the initial run.")
        return

    path_args = [a for a in args if not a.startswith("--")]
    if path_args:
        scores_path = path_args[0]
    else:
        root = Path(__file__).resolve().parents[1]
        latest = find_latest_scores(root)
        if not latest:
            print("No live_scores CSV found. Run 'uv run scripts/score_live.py' first.")
            return
        scores_path = str(latest)
        print(f"Using: {scores_path}")

    ranked_df = load_scores_csv(scores_path)
    print(f"Loaded {len(ranked_df)} portfolio positions.")
    run_rebalance(ranked_df, client, order_type="MOC", dry_run=dry_run, strategy=strategy,
                  tracker_conn=tracker_conn, nav_override=nav_override)


def run_repl(client, strategy: str = "fundamentals_alpha", tracker_conn=None) -> None:
    account_type = "LIVE" if client.is_live() else "PAPER"
    print(f"\nIB Trader REPL — {client.account} [{account_type}]")
    if client.is_live():
        print("*** WARNING: Connected to LIVE account. Real money. ***")
    print('Type "help" for commands, "quit" to exit.\n')

    while True:
        try:
            line = input("ib> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nDisconnecting...")
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("quit", "exit"):
            print("Disconnecting...")
            break
        elif cmd == "help":
            print(_HELP)
        elif cmd == "status":
            _print_status(client)
        elif cmd == "quote":
            if not args:
                print("Usage: quote TICKER")
            else:
                _print_quote(client, args[0].upper())
        elif cmd in ("buy", "sell"):
            _handle_buy_sell(client, cmd, args, strategy)
        elif cmd == "cancel":
            _handle_cancel(client, args)
        elif cmd == "preview":
            _handle_rebalance(client, args, dry_run=True, strategy=strategy, tracker_conn=tracker_conn)
        elif cmd == "rebalance":
            confirm = "--confirm" in args
            _handle_rebalance(client, args, dry_run=not confirm, strategy=strategy, tracker_conn=tracker_conn)
        else:
            print(f"Unknown command: {cmd!r}. Type 'help' for commands.")
