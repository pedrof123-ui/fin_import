from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ib_async import LimitOrder, MarketOrder, Order, Trade

_EASTERN = ZoneInfo("America/New_York")
_MOC_CUTOFF_HOUR = 15
_MOC_CUTOFF_MINUTE = 45


def make_order(
    action: str,
    qty: int,
    order_type: str,
    limit_price: float | None = None,
    strategy: str = "fundamentals_alpha",
) -> Order:
    """Create an IB Order. action='BUY'|'SELL', order_type='MKT'|'LMT'|'MOO'|'MOC'."""
    action = action.upper()
    order_type = order_type.upper()

    if order_type == "MOO":
        order = Order()
        order.action = action
        order.totalQuantity = qty
        order.orderType = "MKT"
        order.tif = "OPG"
    elif order_type == "MOC":
        order = Order()
        order.action = action
        order.totalQuantity = qty
        order.orderType = "MOC"
        order.tif = "DAY"
    elif order_type == "LMT":
        if limit_price is None:
            raise ValueError("limit_price required for LMT orders")
        order = LimitOrder(action, qty, round(limit_price, 2))
    elif order_type == "MKT":
        order = MarketOrder(action, qty)
        order.tif = "DAY"
    else:
        raise ValueError(f"Unknown order_type: {order_type!r}. Use MKT, LMT, MOO, or MOC.")

    order.orderRef = strategy
    return order


def _warn_if_past_moc_cutoff() -> None:
    now = datetime.now(_EASTERN)
    past_cutoff = now.hour > _MOC_CUTOFF_HOUR or (
        now.hour == _MOC_CUTOFF_HOUR and now.minute >= _MOC_CUTOFF_MINUTE
    )
    if past_cutoff:
        print(
            f"WARNING: {now.strftime('%H:%M')} ET is past the MOC cutoff "
            f"({_MOC_CUTOFF_HOUR}:{_MOC_CUTOFF_MINUTE:02d} ET). MOC orders may be rejected."
        )


def place_order(
    client,
    ticker: str,
    action: str,
    qty: int,
    order_type: str,
    limit_price: float | None = None,
    strategy: str = "fundamentals_alpha",
) -> Trade:
    """Qualify contract and place order. Returns IB Trade."""
    if order_type.upper() == "MOC":
        _warn_if_past_moc_cutoff()
    contracts = client.qualify_contracts([ticker])
    order = make_order(action, qty, order_type, limit_price, strategy)
    return client.ib.placeOrder(contracts[ticker], order)


def cancel_all_open_orders(client) -> int:
    """Cancel all open orders. Returns count cancelled."""
    trades = client.ib.openTrades()
    for trade in trades:
        client.ib.cancelOrder(trade.order)
    return len(trades)


def get_order_status(client) -> list[dict]:
    """Return summary dicts for all open trades."""
    return [
        {
            "order_id": t.order.orderId,
            "ticker": t.contract.symbol,
            "action": t.order.action,
            "qty": t.order.totalQuantity,
            "order_type": t.order.orderType,
            "status": t.orderStatus.status,
            "filled": t.orderStatus.filled,
            "remaining": t.orderStatus.remaining,
            "avg_fill_price": t.orderStatus.avgFillPrice,
            "strategy": t.order.orderRef,
        }
        for t in client.ib.openTrades()
    ]
