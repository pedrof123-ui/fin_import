"""
Live current-price quotes from Alpha Vantage GLOBAL_QUOTE, shared across routers
(Finview header banner, AV DCF, Fundamentals, AI Researcher).

Short in-memory cache so multiple components reading the same ticker within a few
seconds of each other don't each burn a separate AV call.
"""

import os
import time
from typing import Optional

import requests

_CACHE_TTL_SECONDS = 30
_cache: dict[str, tuple[float, Optional[dict]]] = {}


def fetch_live_quote(ticker: str) -> Optional[dict]:
    """Returns {price, change, change_percent, latest_trading_day} or None if unavailable."""
    ticker = ticker.upper()
    cached = _cache.get(ticker)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    result = _fetch_from_av(ticker)
    _cache[ticker] = (time.monotonic(), result)
    return result


def fetch_live_price(ticker: str) -> Optional[float]:
    quote = fetch_live_quote(ticker)
    return quote["price"] if quote else None


def _fetch_from_av(ticker: str) -> Optional[dict]:
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.get(
            "https://www.alphavantage.co/query",
            params={"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        quote = resp.json().get("Global Quote", {})
        price_str = quote.get("05. price")
        if not price_str:
            return None

        change_pct_str = (quote.get("10. change percent") or "").rstrip("%")
        return {
            "price": float(price_str),
            "change": float(quote["09. change"]) if quote.get("09. change") else None,
            "change_percent": float(change_pct_str) if change_pct_str else None,
            "latest_trading_day": quote.get("07. latest trading day"),
        }
    except Exception:
        return None
