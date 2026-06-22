"""
Shared utilities for the earnings call transcript database.

Used by:
  - api/earnings_router.py  (on-demand Finview fetch)
  - api/research_router.py  (AI Researcher integration)
  - scripts/earnings_backfill.py
  - scripts/earnings_update.py
"""

import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

import duckdb
import requests

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "earnings_transcripts.duckdb"

_AV_URL = "https://www.alphavantage.co/query"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def open_db(db_path: Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open (or create) the earnings transcript DuckDB and ensure schema is current."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS earnings_transcripts (
            symbol             VARCHAR NOT NULL,
            quarter            VARCHAR NOT NULL,
            transcript_text    TEXT    NOT NULL,
            fetched_date       DATE    NOT NULL,
            api_response_json  TEXT,
            source             VARCHAR DEFAULT 'av',
            earnings_call_date DATE,
            PRIMARY KEY (symbol, quarter)
        )
    """)
    cols = {row[0] for row in conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'earnings_transcripts'"
    ).fetchall()}
    if "source" not in cols:
        conn.execute("ALTER TABLE earnings_transcripts ADD COLUMN source VARCHAR DEFAULT 'av'")
    if "earnings_call_date" not in cols:
        conn.execute("ALTER TABLE earnings_transcripts ADD COLUMN earnings_call_date DATE")
    return conn


def is_cached(conn: duckdb.DuckDBPyConnection, symbol: str, quarter: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM earnings_transcripts WHERE symbol = ? AND quarter = ?",
        [symbol, quarter],
    ).fetchone()
    return row is not None


def get_latest_cached_quarter(conn: duckdb.DuckDBPyConnection, symbol: str) -> Optional[str]:
    row = conn.execute(
        "SELECT quarter FROM earnings_transcripts WHERE symbol = ? ORDER BY quarter DESC LIMIT 1",
        [symbol],
    ).fetchone()
    return row[0] if row else None


def save_transcript(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    quarter: str,
    transcript_text: str,
    api_json: Optional[str],
    source: str = "av",
    earnings_call_date: Optional[date] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO earnings_transcripts
            (symbol, quarter, transcript_text, fetched_date, api_response_json, source, earnings_call_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (symbol, quarter) DO UPDATE SET
            transcript_text    = EXCLUDED.transcript_text,
            fetched_date       = EXCLUDED.fetched_date,
            api_response_json  = EXCLUDED.api_response_json,
            source             = EXCLUDED.source,
            earnings_call_date = EXCLUDED.earnings_call_date
        """,
        [symbol, quarter, transcript_text, date.today(), api_json, source, earnings_call_date],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Alpha Vantage fetch
# ---------------------------------------------------------------------------

def fetch_from_av(
    symbol: str,
    quarter: str,
    api_key: Optional[str] = None,
) -> Optional[tuple[str, str]]:
    """
    Fetch an earnings call transcript from Alpha Vantage.

    Returns (transcript_text, api_response_json) on success, or None if the
    transcript does not exist for this symbol/quarter (404 / empty response).
    Raises requests.HTTPError on network/server errors.
    """
    if api_key is None:
        api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        raise ValueError("ALPHA_VANTAGE_API_KEY not set")

    resp = requests.get(
        _AV_URL,
        params={
            "function": "EARNINGS_CALL_TRANSCRIPT",
            "symbol": symbol,
            "quarter": quarter,
            "apikey": api_key,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if any(k in data for k in ("Error Message", "Note", "Information")):
        return None
    if not data.get("transcript"):
        return None

    parts = []
    for entry in data["transcript"]:
        speaker = entry.get("speaker", "Unknown")
        title   = entry.get("title", "")
        content = entry.get("content", "")
        header  = f"## {speaker}"
        if title:
            header += f"\n**{title}**"
        parts.append(f"{header}\n\n{content}")

    transcript_text = "\n\n---\n\n".join(parts)
    return transcript_text, json.dumps(data)


# ---------------------------------------------------------------------------
# Quarter derivation
# ---------------------------------------------------------------------------

def fiscal_date_to_quarters(
    latest_fiscal_date: date,
    today: date,
    n_quarters: int,
) -> list[str]:
    """
    Return up to n_quarters calendar quarter strings (newest first) to probe
    for a ticker whose latest av_financials entry has the given fiscal_date_ending.

    Applies the 60-day lookahead rule: if more than 60 days have passed since
    latest_fiscal_date, includes the following quarter as a potential new transcript
    not yet reflected in av_financials.
    """
    q = (latest_fiscal_date.month - 1) // 3 + 1
    base_idx = latest_fiscal_date.year * 4 + (q - 1)

    if (today - latest_fiscal_date).days > 60:
        start_idx = base_idx + 1
    else:
        start_idx = base_idx

    result = []
    for i in range(n_quarters):
        total = start_idx - i
        y, rem = divmod(total, 4)
        result.append(f"{y}Q{rem + 1}")
    return result
