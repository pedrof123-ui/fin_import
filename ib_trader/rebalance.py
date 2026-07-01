from __future__ import annotations

import os

import pandas as pd

from .orders import place_order
from .portfolio import build_target, diff_portfolio, summarise_diff


def run_rebalance(
    ranked_df: pd.DataFrame,
    client,
    order_type: str = "MOC",
    dry_run: bool = True,
    strategy: str = "fundamentals_alpha",
    tracker_conn=None,
    nav_override: float | None = None,
) -> pd.DataFrame:
    """Execute a full portfolio rebalance.

    ranked_df: output of load_scores_csv() — portfolio rows only, numeric alloc_pct.
    client: connected IBClient.
    dry_run: print blotter but submit no orders.
    tracker_conn: open tracker DB connection — used to scope sells to strategy-owned positions only.
    nav_override: if set, use this value as NAV for position sizing instead of the account NAV.
                  Use when multiple strategies share one account and each has a fixed capital allocation.
    Returns blotter DataFrame.
    """
    # 1. Account state
    if nav_override is None:
        raise ValueError(
            "run_rebalance() requires an explicit nav_override. Falling back to the full "
            "account NAV (client.get_nav()) is unsafe when multiple strategies share one "
            "IB account — it would size the target portfolio against every strategy's "
            "combined capital instead of just this one's."
        )
    nav = nav_override
    ib_positions = client.get_positions()

    # Scope current positions to only what this strategy owns, so we never
    # sell positions belonging to other strategies running on the same account.
    if tracker_conn is not None:
        from .tracker import get_strategy_positions
        strategy_qty = get_strategy_positions(tracker_conn, strategy)
        # Use IB qty capped at tracker qty (tracker is authoritative for strategy ownership)
        current = {
            t: min(ib_positions.get(t, qty), qty)
            for t, qty in strategy_qty.items()
            if qty > 0
        }
    else:
        current = ib_positions

    # 2. Live prices for all relevant tickers (portfolio + current holdings)
    all_tickers = sorted(set(ranked_df["ticker"].tolist()) | set(current.keys()))
    print(f"Fetching live prices for {len(all_tickers)} tickers...")
    live_prices = client.get_live_prices(all_tickers)
    n_live = len(live_prices)
    n_total = len(all_tickers)
    print(f"  Got prices for {n_live}/{n_total} tickers"
          + (f" ({n_total - n_live} will use CSV price)" if n_total > n_live else "") + ".")

    # 3. Build target share counts
    target = build_target(ranked_df, nav, price_map=live_prices)

    # 4. Diff
    specs = diff_portfolio(current, target)

    # 5. Price map for blotter: CSV prices + live prices (live takes precedence)
    csv_prices = {
        row["ticker"]: row.get("price")
        for _, row in ranked_df.iterrows()
        if row.get("price") and row.get("price") > 0
    }
    blotter_prices: dict[str, float] = {**csv_prices, **live_prices}

    blotter = summarise_diff(specs, blotter_prices)

    # 6. Summary
    buys = [s for s in specs if s.action == "BUY"]
    sells = [s for s in specs if s.action == "SELL"]
    account_type = "LIVE" if client.is_live() else "PAPER"
    nav_label = f"${nav:,.0f} (override)" if nav_override else f"${nav:,.0f}"
    print(f"\nAccount: {client.account} [{account_type}]  NAV: {nav_label}")
    print(f"Current positions: {len(current)} tickers")
    print(f"Target positions:  {len(target)} tickers")
    print(f"Orders: {len(buys)} buys, {len(sells)} sells")

    if blotter.empty:
        print("Portfolio is already at target — no orders needed.")
        return blotter

    label = f"order_type={order_type}" + (" [DRY RUN — no orders submitted]" if dry_run else "")
    print(f"\nOrder blotter ({label}):")
    print(blotter.to_string(index=False))

    if dry_run:
        print("\nPass --no-dry-run (CLI) or 'rebalance --confirm' (REPL) to submit orders.")
        return blotter

    # 7. Cancel existing open orders for affected tickers
    affected = {s.ticker for s in specs}
    open_trades = client.ib.openTrades()
    cancelled = sum(
        1 for t in open_trades
        if t.contract.symbol in affected
        and not client.ib.cancelOrder(t.order)
    )
    if cancelled:
        print(f"Cancelled {cancelled} existing open order(s) for affected tickers.")
        client.ib.sleep(1)

    # 8. Submit
    submitted = 0
    for spec in specs:
        limit_price = live_prices.get(spec.ticker) if order_type == "LMT" else None
        try:
            place_order(client, spec.ticker, spec.action, spec.qty,
                        order_type, limit_price, strategy)
            submitted += 1
        except Exception as exc:
            print(f"  ERROR {spec.action} {spec.qty} {spec.ticker}: {exc}")

    print(f"\nSubmitted {submitted}/{len(specs)} orders.")
    blotter = blotter.copy()
    blotter["order_type"] = order_type

    # Auto-log estimated fills to tracker DB if IB_TRACKER_DB is configured
    tracker_db = os.getenv("IB_TRACKER_DB")
    if tracker_db and submitted > 0:
        try:
            from .tracker import init_tracker_db, record_fills_from_blotter
            tracker_conn = init_tracker_db(tracker_db)
            n_logged = record_fills_from_blotter(
                tracker_conn, strategy, blotter, live_prices,
                reference_price_map=csv_prices,
            )
            tracker_conn.close()
            print(f"  Logged {n_logged} estimated fill(s) to tracker DB.")
        except Exception as exc:
            print(f"  Warning: tracker log failed: {exc}")

    return blotter
