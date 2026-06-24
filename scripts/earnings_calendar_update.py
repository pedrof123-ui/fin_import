#!/usr/bin/env python3
"""
Weekly update of the earnings calendar for tracked tickers.

Fetches the AV EARNINGS_CALENDAR endpoint (3-month horizon, CSV response),
filters to symbols already in av_financials.duckdb, and upserts into the
earnings_calendar table. Entries older than 30 days are purged each run.

Usage:
    uv run scripts/earnings_calendar_update.py
    uv run scripts/earnings_calendar_update.py --verbose

Cron (weekly, Monday 6 AM):
    0 6 * * 1 cd /home/pedro/projects/fin_import2 && uv run scripts/earnings_calendar_update.py >> logs/earnings_calendar.log 2>&1
"""

import argparse
import csv
import io
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from av_financials_db import DEFAULT_DB_PATH as AV_DB_PATH  # noqa: E402

log = logging.getLogger(__name__)

_AV_URL = "https://www.alphavantage.co/query"
_HORIZON = "3month"


def _ensure_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS earnings_calendar (
            symbol             VARCHAR   NOT NULL,
            name               VARCHAR,
            report_date        DATE      NOT NULL,
            fiscal_date_ending DATE,
            estimate           DOUBLE,
            currency           VARCHAR,
            time_of_day        VARCHAR,
            fetched_at         TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (symbol, report_date)
        )
    """)
    conn.execute(
        "ALTER TABLE earnings_calendar ADD COLUMN IF NOT EXISTS time_of_day VARCHAR"
    )


def _tracked_tickers(conn: duckdb.DuckDBPyConnection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM companies").fetchall()}


def _fetch_csv(api_key: str) -> list[dict]:
    resp = requests.get(
        _AV_URL,
        params={"function": "EARNINGS_CALENDAR", "horizon": _HORIZON, "apikey": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    return list(csv.DictReader(io.StringIO(resp.text)))


def _to_date(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _to_float(s: str) -> float | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly earnings calendar update.")
    parser.add_argument("--db", default=str(AV_DB_PATH), help="Path to av_financials.duckdb")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    load_dotenv(ROOT / ".env", override=True)
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        log.error("ALPHA_VANTAGE_API_KEY not set in .env")
        return 2

    conn = duckdb.connect(args.db)
    _ensure_table(conn)
    tracked = _tracked_tickers(conn)
    log.info("Tracked tickers: %d", len(tracked))

    log.info("Fetching earnings calendar from Alpha Vantage (%s)…", _HORIZON)
    try:
        rows = _fetch_csv(api_key)
    except Exception as exc:
        log.error("Failed to fetch calendar: %s", exc)
        conn.close()
        return 1

    log.info("AV returned %d rows", len(rows))

    inserted = skipped = 0
    for row in rows:
        symbol = (row.get("symbol") or "").strip().upper()
        if symbol not in tracked:
            log.debug("Skip %s — not tracked", symbol)
            skipped += 1
            continue

        report_date = _to_date(row.get("reportDate", ""))
        if report_date is None:
            log.debug("Skip %s — missing reportDate", symbol)
            skipped += 1
            continue

        time_of_day = (row.get("timeOfTheDay") or "").strip() or None

        conn.execute("""
            INSERT OR REPLACE INTO earnings_calendar
                (symbol, name, report_date, fiscal_date_ending, estimate, currency, time_of_day, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)
        """, [
            symbol,
            (row.get("name") or "").strip() or None,
            report_date,
            _to_date(row.get("fiscalDateEnding", "")),
            _to_float(row.get("estimate", "")),
            (row.get("currency") or "").strip() or None,
            time_of_day,
        ])
        inserted += 1
        log.debug("Upserted %s %s", symbol, report_date)

    cutoff = date.today() - timedelta(days=30)
    deleted = conn.execute(
        "DELETE FROM earnings_calendar WHERE report_date < ? RETURNING symbol",
        [cutoff],
    ).fetchall()
    log.info("Purged %d entries older than %s", len(deleted), cutoff)

    conn.close()
    log.info("Done — upserted: %d  skipped: %d", inserted, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
