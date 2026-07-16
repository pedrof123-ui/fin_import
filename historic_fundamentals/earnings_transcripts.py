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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS earnings_surprises (
            symbol           VARCHAR NOT NULL,
            fiscal_date_ending VARCHAR NOT NULL,
            reported_date    VARCHAR,
            reported_eps     DOUBLE,
            estimated_eps    DOUBLE,
            surprise_pct     DOUBLE,
            fetched_at       TIMESTAMP,
            PRIMARY KEY (symbol, fiscal_date_ending)
        )
    """)
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


def get_last_n_transcripts(
    conn: duckdb.DuckDBPyConnection, symbol: str, n: int = 4
) -> list[tuple[str, str]]:
    """Return up to n cached (quarter, transcript_text) pairs, newest first."""
    rows = conn.execute(
        "SELECT quarter, transcript_text FROM earnings_transcripts "
        "WHERE symbol = ? ORDER BY quarter DESC LIMIT ?",
        [symbol, n],
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


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
# EPS beat/miss history (AV EARNINGS function)
# ---------------------------------------------------------------------------

_SURPRISE_CACHE_DAYS = 30


def get_cached_surprises(
    conn: duckdb.DuckDBPyConnection, symbol: str, max_age_days: int = _SURPRISE_CACHE_DAYS
) -> Optional[list[dict]]:
    """Return up to 8 cached quarterly (reported_eps, estimated_eps, surprise_pct) rows,
    newest first, or None if the cache is stale/empty."""
    from datetime import datetime, timedelta

    row = conn.execute(
        "SELECT MAX(fetched_at) FROM earnings_surprises WHERE symbol = ?", [symbol]
    ).fetchone()
    if not row or row[0] is None or row[0] < datetime.utcnow() - timedelta(days=max_age_days):
        return None
    rows = conn.execute(
        """SELECT fiscal_date_ending, reported_date, reported_eps, estimated_eps, surprise_pct
           FROM earnings_surprises WHERE symbol = ?
           ORDER BY fiscal_date_ending DESC LIMIT 8""",
        [symbol],
    ).fetchall()
    return [
        {"fiscal_date_ending": r[0], "reported_date": r[1], "reported_eps": r[2],
         "estimated_eps": r[3], "surprise_pct": r[4]}
        for r in rows
    ]


def fetch_surprises_from_av(symbol: str, api_key: Optional[str] = None) -> Optional[list[dict]]:
    """Fetch quarterly EPS beat/miss history from Alpha Vantage's EARNINGS function."""
    if api_key is None:
        api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        return None

    resp = requests.get(
        _AV_URL,
        params={"function": "EARNINGS", "symbol": symbol, "apikey": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    quarterly = data.get("quarterlyEarnings")
    if not quarterly:
        return None

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return [
        {
            "fiscal_date_ending": q.get("fiscalDateEnding"),
            "reported_date": q.get("reportedDate"),
            "reported_eps": _f(q.get("reportedEPS")),
            "estimated_eps": _f(q.get("estimatedEPS")),
            "surprise_pct": _f(q.get("surprisePercentage")),
        }
        for q in quarterly[:8]
    ]


def save_surprises(conn: duckdb.DuckDBPyConnection, symbol: str, rows: list[dict]) -> None:
    from datetime import datetime

    fetched_at = datetime.utcnow()
    for r in rows:
        conn.execute(
            """
            INSERT INTO earnings_surprises
                (symbol, fiscal_date_ending, reported_date, reported_eps, estimated_eps,
                 surprise_pct, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (symbol, fiscal_date_ending) DO UPDATE SET
                reported_date = EXCLUDED.reported_date,
                reported_eps  = EXCLUDED.reported_eps,
                estimated_eps = EXCLUDED.estimated_eps,
                surprise_pct  = EXCLUDED.surprise_pct,
                fetched_at    = EXCLUDED.fetched_at
            """,
            [symbol, r["fiscal_date_ending"], r["reported_date"], r["reported_eps"],
             r["estimated_eps"], r["surprise_pct"], fetched_at],
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
    fy_end_month: int = 12,
) -> list[str]:
    """
    Return up to n_quarters fiscal quarter strings (newest first) to probe
    for a ticker whose latest av_financials entry has the given fiscal_date_ending.

    Uses the company's fiscal year end month so that AV's fiscal quarter labels
    are matched correctly for non-December fiscal year companies.

    Applies the 60-day lookahead rule: if more than 60 days have passed since
    latest_fiscal_date, includes the following quarter as a potential new transcript
    not yet reflected in av_financials.
    """
    # Fiscal year = the calendar year in which the fiscal year ends
    if latest_fiscal_date.month <= fy_end_month:
        fy = latest_fiscal_date.year
    else:
        fy = latest_fiscal_date.year + 1

    # Fiscal quarter number 1-4 within that fiscal year
    fq = ((latest_fiscal_date.month - fy_end_month - 1) % 12) // 3 + 1

    base_idx = fy * 4 + (fq - 1)

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
