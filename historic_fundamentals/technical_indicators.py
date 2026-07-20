"""
Technical indicator computation for the AI Researcher's Technical Analyst sub-agent.

Reads daily OHLCV from trade_systems' prices.duckdb (shared cross-repo, same pattern as
scripts/fmp_price_backfill.py). Indicators are hand-rolled pandas (no new dependency) mirroring
the formulas in trade_systems/ta_report/indicators.py, scoped down to what a narrative technical
read needs: trend (SMA20/50/200), momentum (RSI, MACD), volatility (ATR), rate of change, and
52-week range position.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd
import requests

_PRICES_DB = Path(os.environ.get("PRICES_DB_PATH", "/home/pedro/projects/trade_systems/data/prices.duckdb"))
_FMP_BASE_URL = "https://financialmodelingprep.com/stable"
_LOOKBACK_DAYS = 400
_STALE_DAYS = 5


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute trend/momentum/volatility indicators from date-sorted OHLCV rows.

    Expects columns: date, open, high, low, close, volume. Returns df with added columns.
    """
    out = df.copy()
    c, h, l = out["close"], out["high"], out["low"]

    out["sma20"] = c.rolling(20).mean()
    out["sma50"] = c.rolling(50).mean()
    out["sma200"] = c.rolling(200, min_periods=100).mean()

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    out["macd_line"] = ema12 - ema26
    out["macd_signal"] = out["macd_line"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd_line"] - out["macd_signal"]

    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    out["rsi"] = 100 - (100 / (1 + rs))
    out.loc[loss == 0, "rsi"] = 100.0

    prev_close = c.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    out["atr"] = tr.rolling(14).mean()
    out["atr_pct"] = out["atr"] / c * 100

    out["roc_10"] = (c / c.shift(10) - 1) * 100
    out["roc_20"] = (c / c.shift(20) - 1) * 100

    out["high_52w"] = c.rolling(252, min_periods=60).max()
    out["low_52w"] = c.rolling(252, min_periods=60).min()
    out["pct_off_high"] = (c - out["high_52w"]) / out["high_52w"] * 100

    return out


def _trend_label(price: float, sma50: Optional[float], sma200: Optional[float]) -> str:
    if sma50 is None or sma200 is None or pd.isna(sma50) or pd.isna(sma200):
        return "insufficient history"
    if price > sma50 > sma200:
        return "uptrend (price > SMA50 > SMA200)"
    if price < sma50 < sma200:
        return "downtrend (price < SMA50 < SMA200)"
    return "mixed / transitional"


def backfill_recent_prices(ticker: str, days: int = _LOOKBACK_DAYS) -> bool:
    """Fetch recent daily OHLCV for one ticker from FMP and upsert into prices.duckdb.

    Returns False (never raises) on missing key, HTTP error, or DB lock — callers should
    fall back to whatever is cached.
    """
    ticker = ticker.upper()
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        return False

    from_date = (date.today() - timedelta(days=days)).isoformat()
    to_date = date.today().isoformat()

    try:
        resp = requests.get(
            f"{_FMP_BASE_URL}/historical-price-eod/dividend-adjusted",
            params={"symbol": ticker, "from": from_date, "to": to_date, "apikey": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        return False

    if not isinstance(rows, list) or not rows:
        return False

    df = pd.DataFrame(rows)
    if not {"date", "adjOpen", "adjHigh", "adjLow", "adjClose", "volume"}.issubset(df.columns):
        return False
    df["ticker"] = ticker
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["open"] = df["adjOpen"]
    df["high"] = df["adjHigh"]
    df["low"] = df["adjLow"]
    df["close"] = df["adjClose"]
    df["adj_close"] = df["adjClose"]
    df["adj_open"] = None
    df["adj_high"] = None
    df["adj_low"] = None
    df = df[["ticker", "date", "open", "high", "low", "close", "volume",
              "adj_close", "adj_open", "adj_high", "adj_low"]]

    try:
        _PRICES_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(_PRICES_DB))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_prices (
                ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE,
                close DOUBLE, volume BIGINT, adj_close DOUBLE,
                adj_open DOUBLE, adj_high DOUBLE, adj_low DOUBLE
            )
        """)
        conn.register("df_new", df)
        conn.execute("""
            DELETE FROM stock_prices WHERE ticker = ? AND date IN (SELECT date FROM df_new)
        """, [ticker])
        conn.execute("INSERT INTO stock_prices SELECT * FROM df_new")
        conn.commit()
        conn.close()
    except Exception:
        return False

    return True


def get_technical_summary(ticker: str) -> str:
    ticker = ticker.upper()

    def _load() -> Optional[pd.DataFrame]:
        try:
            conn = duckdb.connect(str(_PRICES_DB), read_only=True)
            df = conn.execute(
                "SELECT date, open, high, low, close, volume FROM stock_prices "
                "WHERE ticker = ? ORDER BY date DESC LIMIT ?",
                [ticker, _LOOKBACK_DAYS],
            ).df()
            conn.close()
        except Exception as e:
            return None
        if df.empty:
            return None
        return df.sort_values("date").reset_index(drop=True)

    df = _load()
    last_date = None if df is None else pd.Timestamp(df["date"].iloc[-1]).date()
    stale = last_date is None or (date.today() - last_date) > timedelta(days=_STALE_DAYS)
    if stale:
        if backfill_recent_prices(ticker):
            df = _load()

    if df is None or df.empty or len(df) < 20:
        return f"[ERROR] No usable price history for {ticker}"

    ind = compute_indicators(df)
    last = ind.iloc[-1]

    def f(v, fmt=".2f") -> str:
        return f"{v:{fmt}}" if v is not None and not pd.isna(v) else "n/a"

    lines = [f"TECHNICAL INDICATORS — {ticker} (as of {pd.Timestamp(last['date']).date()})", ""]
    lines.append(f"Current Price: ${f(last['close'])}")
    lines.append(f"SMA20:  ${f(last['sma20'])}")
    lines.append(f"SMA50:  ${f(last['sma50'])}")
    lines.append(f"SMA200: ${f(last['sma200'])}")
    lines.append(f"Trend:  {_trend_label(last['close'], last['sma50'], last['sma200'])}")
    lines.append("")
    lines.append(f"RSI(14): {f(last['rsi'], '.1f')}"
                  + (" [overbought >70]" if pd.notna(last['rsi']) and last['rsi'] > 70
                     else " [oversold <30]" if pd.notna(last['rsi']) and last['rsi'] < 30 else ""))
    lines.append(f"MACD Line: {f(last['macd_line'])}  Signal: {f(last['macd_signal'])}  "
                  f"Hist: {f(last['macd_hist'])} "
                  f"[{'bullish cross' if pd.notna(last['macd_hist']) and last['macd_hist'] > 0 else 'bearish cross'}]")
    lines.append(f"ROC 10d: {f(last['roc_10'], '+.1f')}%   ROC 20d: {f(last['roc_20'], '+.1f')}%")
    lines.append(f"ATR(14): ${f(last['atr'])}  ({f(last['atr_pct'], '.1f')}% of price)")
    lines.append("")
    lines.append(f"52-Week High: ${f(last['high_52w'])}   52-Week Low: ${f(last['low_52w'])}")
    lines.append(f"% Off 52wk High: {f(last['pct_off_high'], '+.1f')}%")

    return "\n".join(lines)
