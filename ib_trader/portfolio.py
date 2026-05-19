from __future__ import annotations

import math
from collections import namedtuple
from pathlib import Path

import pandas as pd

OrderSpec = namedtuple("OrderSpec", ["ticker", "action", "qty"])


def find_latest_scores(root: Path) -> Path | None:
    """Return the most recent live_scores_*.csv in docs/, or None."""
    docs = root / "docs"
    if not docs.exists():
        return None
    csvs = sorted(docs.glob("live_scores_*.csv"), reverse=True)
    return csvs[0] if csvs else None


def load_scores_csv(path: str | Path) -> pd.DataFrame:
    """Load a live_scores CSV (with # comment header).

    Returns only portfolio rows (non-empty alloc_pct) with numeric columns.
    alloc_pct is returned as a float 0-100 (e.g. 2.0 = 2% of NAV).
    """
    df = pd.read_csv(path, comment="#")

    if "alloc_pct" not in df.columns:
        raise ValueError(f"alloc_pct column not found in {path}")

    # Keep only portfolio positions (non-empty alloc_pct)
    mask = df["alloc_pct"].notna() & (df["alloc_pct"].astype(str).str.strip() != "")
    df = df[mask].copy()

    # Parse "2.0%" → 2.0
    df["alloc_pct"] = df["alloc_pct"].astype(str).str.rstrip("%").astype(float)

    if "price" in df.columns:
        df["price"] = pd.to_numeric(df["price"], errors="coerce")

    return df.reset_index(drop=True)


def build_target(
    ranked_df: pd.DataFrame,
    nav: float,
    price_map: dict[str, float] | None = None,
) -> dict[str, int]:
    """Compute whole-share target counts from a portfolio DataFrame.

    ranked_df must have: ticker (str), alloc_pct (float 0-100), price (float).
    price_map: live IB prices; takes precedence over the price column.
    Returns {ticker: target_shares} for alloc_pct > 0 rows only.
    """
    price_map = price_map or {}
    target: dict[str, int] = {}
    for _, row in ranked_df.iterrows():
        ticker = row["ticker"]
        alloc_pct = row.get("alloc_pct")
        if pd.isna(alloc_pct) or alloc_pct <= 0:
            continue
        price = price_map.get(ticker) or row.get("price")
        if price is None or pd.isna(price) or price <= 0:
            continue
        target[ticker] = math.floor(alloc_pct / 100.0 * nav / price)
    return target


def diff_portfolio(
    current: dict[str, float],
    target: dict[str, int],
) -> list[OrderSpec]:
    """Compute orders to move from current positions to target.

    Tickers in current but absent from target → target = 0 (full exit).
    Returns BUY and SELL OrderSpecs sorted by ticker.
    """
    specs = []
    for ticker in sorted(set(current) | set(target)):
        cur = int(current.get(ticker, 0))
        tgt = target.get(ticker, 0)
        delta = tgt - cur
        if delta > 0:
            specs.append(OrderSpec(ticker, "BUY", delta))
        elif delta < 0:
            specs.append(OrderSpec(ticker, "SELL", abs(delta)))
    return specs


def summarise_diff(
    specs: list[OrderSpec],
    price_map: dict[str, float],
) -> pd.DataFrame:
    """Return a human-readable blotter DataFrame."""
    if not specs:
        return pd.DataFrame(columns=["ticker", "action", "qty", "est_price", "est_value"])
    rows = []
    for spec in specs:
        price = price_map.get(spec.ticker)
        rows.append({
            "ticker": spec.ticker,
            "action": spec.action,
            "qty": spec.qty,
            "est_price": f"${price:.2f}" if price else "N/A",
            "est_value": f"${spec.qty * price:>10,.0f}" if price else "N/A",
        })
    return pd.DataFrame(rows)
