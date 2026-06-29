"""
Backfill prices.duckdb/stock_prices with FMP dividend-adjusted EOD prices.

Two operations combined in one pass per ticker:
  Phase 1 - new rows:      Insert pre-1996 history back to 1983-01-01.
  Phase 2 - adj_close fix: Update adj_close=NULL on existing 1996-1998 rows.

Both use FMP historical-price-eod/dividend-adjusted, which returns fully
split- and dividend-adjusted prices directly usable as adj_close by pe.py.

Universe: all tickers in av_financials.duckdb.
Fetch range per ticker: 1983-01-01 to 1998-12-31.

Skip a ticker if: MIN(date) <= 1983-01-01 AND no NULL adj_close in 1996-1998.

Usage:
    uv run scripts/fmp_price_backfill.py [--dry-run] [--ticker AAPL]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date as date_cls, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

_AV_DB      = Path(os.environ.get("AV_DB_PATH",      str(ROOT / "data" / "av_financials.duckdb")))
_PRICES_DB  = Path(os.environ.get("PRICES_DB_PATH",  "/home/pedro/projects/trade_systems/data/prices.duckdb"))
_BASE_URL   = "https://financialmodelingprep.com/stable"
_DEFAULT_FROM = "1983-01-01"
_DEFAULT_TO   = "1999-12-31"
_CALLS_PER_MINUTE = 750
_BATCH_ROWS = 50_000

log = logging.getLogger(__name__)


class _RateLimiter:
    def __init__(self, calls_per_minute: int = _CALLS_PER_MINUTE) -> None:
        self._interval = 60.0 / calls_per_minute
        self._last = 0.0

    def wait(self) -> None:
        gap = self._interval - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()


def _get_api_key() -> str:
    key = os.getenv("FMP_API_KEY")
    if not key:
        raise RuntimeError("FMP_API_KEY not set in environment or .env")
    return key


def _fetch_adj(symbol: str, from_date: str, to_date: str, api_key: str) -> list[dict]:
    resp = requests.get(
        f"{_BASE_URL}/historical-price-eod/dividend-adjusted",
        params={"symbol": symbol, "from": from_date, "to": to_date, "apikey": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def _av_tickers() -> list[str]:
    conn = duckdb.connect(str(_AV_DB), read_only=True)
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM income_statements ORDER BY ticker").fetchall()]
    finally:
        conn.close()


def _coverage(tickers: list[str]) -> dict[str, tuple[date_cls | None, int]]:
    """Return {ticker: (min_date, null_adj_count_in_1996_1998)} for all tickers."""
    conn = duckdb.connect(str(_PRICES_DB), read_only=True)
    try:
        existing = set(
            r[0] for r in conn.execute("SELECT DISTINCT ticker FROM stock_prices").fetchall()
        )
        if not existing:
            return {t: (None, None) for t in tickers}

        df = conn.execute("""
            SELECT
                ticker,
                MIN(date) AS min_date,
                MIN(CASE WHEN date >= '1996-01-01' AND date <= '1999-12-31'
                              AND adj_close IS NULL THEN date END) AS earliest_null_adj
            FROM stock_prices
            GROUP BY ticker
        """).df()
    finally:
        conn.close()

    result: dict[str, tuple[date_cls | None, date_cls | None]] = {}
    row_map = {r["ticker"]: r for _, r in df.iterrows()}
    for t in tickers:
        if t in row_map:
            r = row_map[t]
            min_d  = pd.Timestamp(r["min_date"]).date()          if pd.notna(r["min_date"])          else None
            null_d = pd.Timestamp(r["earliest_null_adj"]).date() if pd.notna(r["earliest_null_adj"]) else None
            result[t] = (min_d, null_d)
        else:
            result[t] = (None, None)
    return result


def _ticker_range(
    min_date: date_cls | None,
    earliest_null: date_cls | None,
    fetch_from: date_cls,
    fetch_to: date_cls,
) -> tuple[str, str] | None:
    """
    Return (dl_from, dl_to) to fetch, or None to skip.

    - No data at all:            fetch [fetch_from, fetch_to]
    - Fully covered:             skip
    - Needs pre-history only:    fetch [fetch_from, min_date-1]
    - Needs adj_close fix only:  fetch [earliest_null, fetch_to]
    - Needs both:                fetch [fetch_from, fetch_to]
    """
    need_history = min_date is None or min_date > fetch_from + timedelta(days=3)
    need_adj     = earliest_null is not None

    if not need_history and not need_adj:
        return None
    if need_history and not need_adj:
        dl_to = min(min_date - timedelta(days=1), fetch_to) if min_date else fetch_to
        return fetch_from.isoformat(), dl_to.isoformat()
    if not need_history and need_adj:
        return earliest_null.isoformat(), fetch_to.isoformat()
    # need both
    return fetch_from.isoformat(), fetch_to.isoformat()


def _upsert_batch(rows: list[dict]) -> tuple[int, int]:
    """Insert new rows and update NULL adj_close on conflicts. Returns (inserted, updated)."""
    if not rows:
        return 0, 0

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date

    conn = duckdb.connect(str(_PRICES_DB))
    try:
        before = conn.execute("SELECT COUNT(*) FROM stock_prices").fetchone()[0]
        conn.register("_batch", df)
        conn.execute("""
            INSERT INTO stock_prices (ticker, date, open, high, low, close, volume, adj_close)
            SELECT ticker, date, open, high, low, close, volume, adj_close FROM _batch
            ON CONFLICT (ticker, date) DO UPDATE
                SET adj_close = EXCLUDED.adj_close
            WHERE stock_prices.adj_close IS NULL
        """)
        after = conn.execute("SELECT COUNT(*) FROM stock_prices").fetchone()[0]
        conn.unregister("_batch")
    finally:
        conn.close()

    inserted = after - before
    updated = len(rows) - inserted  # approximate: conflicts that updated adj_close
    return inserted, updated


def run(
    dry_run: bool,
    single_ticker: str | None = None,
    fetch_from: str = _DEFAULT_FROM,
    fetch_to: str = _DEFAULT_TO,
) -> None:
    api_key = _get_api_key()
    rl = _RateLimiter()
    from_dt = date_cls.fromisoformat(fetch_from)
    to_dt   = date_cls.fromisoformat(fetch_to)

    tickers = _av_tickers()
    if single_ticker:
        tickers = [single_ticker.upper()]
    log.info("Universe: %d tickers from av_financials", len(tickers))

    log.info("Checking existing coverage in prices.duckdb ...")
    coverage = _coverage(tickers)
    plan = []
    for t in tickers:
        min_date, earliest_null = coverage[t]
        rng = _ticker_range(min_date, earliest_null, from_dt, to_dt)
        if rng is not None:
            plan.append((t, rng[0], rng[1]))
    log.info(
        "Need fetch: %d tickers  (skip: %d already fully covered)",
        len(plan), len(tickers) - len(plan),
    )

    if dry_run:
        # Show breakdown of fetch ranges
        full = sum(1 for _, f, _ in plan if f == fetch_from)
        partial = len(plan) - full
        log.info("DRY RUN — %d tickers: %d full range, %d partial (adj_close fix only)",
                 len(plan), full, partial)
        return

    total_inserted = total_updated = empty = errors = 0
    batch: list[dict] = []
    n = len(plan)

    for i, (ticker, dl_from, dl_to) in enumerate(plan, 1):
        rl.wait()
        try:
            records = _fetch_adj(ticker, dl_from, dl_to, api_key)
        except Exception as exc:
            log.warning("[%d/%d] %s — fetch error: %s", i, n, ticker, exc)
            errors += 1
            continue

        if not records:
            log.debug("[%d/%d] %s — no data returned (likely pre-IPO or delisted)", i, n, ticker)
            empty += 1
            continue

        for r in records:
            batch.append({
                "ticker":    ticker,
                "date":      r["date"],
                "open":      r.get("adjOpen"),
                "high":      r.get("adjHigh"),
                "low":       r.get("adjLow"),
                "close":     r.get("adjClose"),
                "volume":    r.get("volume"),
                "adj_close": r.get("adjClose"),
            })

        if len(batch) >= _BATCH_ROWS:
            ins, upd = _upsert_batch(batch)
            total_inserted += ins
            total_updated += upd
            log.info(
                "[%d/%d] Flushed %d rows — +%d inserted, ~%d adj_close updated (running: +%d / ~%d)",
                i, n, len(batch), ins, upd, total_inserted, total_updated,
            )
            batch = []

        if i % 200 == 0:
            log.info("[%d/%d] Progress — empty: %d, errors: %d", i, n, empty, errors)

    del plan  # free memory before final flush

    if batch:
        ins, upd = _upsert_batch(batch)
        total_inserted += ins
        total_updated += upd

    log.info(
        "Done. Inserted: %d new rows. adj_close updated: ~%d rows. "
        "Empty (no FMP data): %d. Errors: %d.",
        total_inserted, total_updated, empty, errors,
    )


def main() -> int:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    from datetime import datetime
    log_path = log_dir / f"fmp_price_backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path)],
    )
    log.info("Log: %s", log_path)

    parser = argparse.ArgumentParser(description="Backfill prices.duckdb from FMP (1983-1999)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ticker", metavar="TICKER", help="Fetch a single ticker only")
    parser.add_argument("--from", dest="from_date", default=_DEFAULT_FROM, metavar="YYYY-MM-DD")
    parser.add_argument("--to",   dest="to_date",   default=_DEFAULT_TO,   metavar="YYYY-MM-DD")
    args = parser.parse_args()

    run(dry_run=args.dry_run, single_ticker=args.ticker,
        fetch_from=args.from_date, fetch_to=args.to_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
