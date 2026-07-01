from __future__ import annotations

import logging
import math
import os
from pathlib import Path

import nest_asyncio
from dotenv import load_dotenv
from ib_async import IB, Contract, Stock

nest_asyncio.apply()
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

log = logging.getLogger(__name__)


def _log_ib_error(reqId: int, errorCode: int, errorString: str, contract: Contract | None) -> None:
    symbol = f" [{contract.symbol}]" if contract is not None else ""
    log.warning("IB error %s (reqId=%s)%s: %s", errorCode, reqId, symbol, errorString)


class IBClient:
    """Thin wrapper around ib_async.IB: connection, account info, and market data."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        client_id: int | None = None,
        account: str | None = None,
    ) -> None:
        self.host = host or os.getenv("IB_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("IB_PORT", "7497"))
        self.client_id = int(client_id or os.getenv("IB_CLIENT_ID", "1"))
        self.account = account or os.getenv("IB_ACCOUNT", "")
        self.ib = IB()
        self.ib.errorEvent += _log_ib_error

    def connect(self) -> "IBClient":
        self.ib.connect(self.host, self.port, clientId=self.client_id)
        if not self.account:
            accounts = self.ib.managedAccounts()
            if accounts:
                self.account = accounts[0]
        # Paper accounts have no live-data subscriptions; delayed data (type 3) is free
        # and returns under the same attribute names as live data.
        # Live accounts default to type 1; override with IB_MARKET_DATA_TYPE=3 if needed.
        mdt = int(os.getenv("IB_MARKET_DATA_TYPE", "1" if self.is_live() else "3"))
        self.ib.reqMarketDataType(mdt)
        return self

    def disconnect(self) -> None:
        self.ib.disconnect()

    def __enter__(self) -> "IBClient":
        return self.connect()

    def __exit__(self, *_) -> None:
        self.disconnect()

    def is_live(self) -> bool:
        return self.port == 7496

    def get_nav(self) -> float:
        """Return NetLiquidation (USD) from accountSummary."""
        for v in self.ib.accountSummary(self.account):
            if v.tag == "NetLiquidation" and v.currency == "USD":
                return float(v.value)
        raise RuntimeError("NetLiquidation not found in accountSummary")

    def get_available_funds(self) -> float:
        """Return AvailableFunds (USD) — cash available to place new orders."""
        for v in self.ib.accountSummary(self.account):
            if v.tag == "AvailableFunds" and v.currency == "USD":
                return float(v.value)
        raise RuntimeError("AvailableFunds not found in accountSummary")

    def get_positions(self) -> dict[str, float]:
        """Return {ticker: shares} for all current positions."""
        return {
            pos.contract.symbol: float(pos.position)
            for pos in self.ib.positions(self.account)
        }

    def qualify_contracts(self, tickers: list[str]) -> dict[str, Contract]:
        """Batch-qualify US stock contracts. Returns {ticker: Contract}."""
        if not tickers:
            return {}
        contracts = [Stock(t, "SMART", "USD") for t in tickers]
        self.ib.qualifyContracts(*contracts)
        return dict(zip(tickers, contracts))

    def get_live_prices(self, tickers: list[str], timeout: float = 5.0) -> dict[str, float]:
        """Batch snapshot prices. Falls back through last → close → ask → bid."""
        if not tickers:
            return {}
        contracts = self.qualify_contracts(tickers)
        ticker_data = {
            sym: self.ib.reqMktData(c, "", True, False)
            for sym, c in contracts.items()
        }
        self.ib.sleep(timeout)
        result = {}
        for sym, td in ticker_data.items():
            for attr in ("last", "close", "ask", "bid"):
                val = getattr(td, attr, None)
                if val is not None and math.isfinite(val) and val > 0:
                    result[sym] = float(val)
                    break
        return result

    def get_live_midprices(self, tickers: list[str], timeout: float = 5.0) -> dict[str, float]:
        """Batch snapshot mid-prices (bid+ask)/2, falling back to last/close."""
        if not tickers:
            return {}
        contracts = self.qualify_contracts(tickers)
        ticker_data = {
            sym: self.ib.reqMktData(c, "", True, False)
            for sym, c in contracts.items()
        }
        self.ib.sleep(timeout)
        result = {}
        for sym, td in ticker_data.items():
            bid = getattr(td, "bid", None)
            ask = getattr(td, "ask", None)
            if (bid and ask and math.isfinite(bid) and math.isfinite(ask)
                    and bid > 0 and ask > 0):
                result[sym] = (bid + ask) / 2.0
            else:
                for attr in ("last", "close"):
                    val = getattr(td, attr, None)
                    if val is not None and math.isfinite(val) and val > 0:
                        result[sym] = float(val)
                        break
        return result
