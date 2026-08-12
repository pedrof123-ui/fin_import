"""
Shared utilities for the earnings call transcript database.

Used by:
  - api/earnings_router.py  (on-demand Finview fetch)
  - api/research_router.py  (AI Researcher integration)
  - api/industry_data.py    (Industry AI Researcher integration)
  - scripts/earnings_backfill.py
  - scripts/earnings_update.py
"""

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

import duckdb
import requests

from av_financials_db import RateLimiter

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "earnings_transcripts.duckdb"

_AV_URL = "https://www.alphavantage.co/query"

log = logging.getLogger(__name__)


class AVError(RuntimeError):
    """Alpha Vantage returned an error/throttle response (Error Message/Note/Information),
    as opposed to a normal empty result. Distinguishing this from "no transcript for this
    quarter" matters: an AVError means something is systemically wrong (rate limit, entitlement)
    and probing further quarters would just waste more calls for the same reason."""


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
            PRIMARY KEY (symbol, quarter)
        )
    """)
    # IF NOT EXISTS / IF EXISTS make these migrations atomic, so concurrent open_db()
    # calls (e.g. multiple AI Researcher sub-agents) can't race each other into a
    # "column already exists" catalog error the way a check-then-act pattern would.
    conn.execute("ALTER TABLE earnings_transcripts ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'av'")
    # earnings_call_date is dead weight from an earlier design: nothing ever populated it
    # (AV's transcript response carries no call-date field), and no reader ever selected it.
    conn.execute("ALTER TABLE earnings_transcripts DROP COLUMN IF EXISTS earnings_call_date")
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
) -> None:
    conn.execute(
        """
        INSERT INTO earnings_transcripts
            (symbol, quarter, transcript_text, fetched_date, api_response_json, source)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (symbol, quarter) DO UPDATE SET
            transcript_text    = EXCLUDED.transcript_text,
            fetched_date       = EXCLUDED.fetched_date,
            api_response_json  = EXCLUDED.api_response_json,
            source             = EXCLUDED.source
        """,
        [symbol, quarter, transcript_text, date.today(), api_json, source],
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

    Returns (transcript_text, api_response_json) on success, or None if the transcript
    genuinely does not exist for this symbol/quarter (empty response).
    Raises AVError if AV responds with an error/throttle payload (rate limit, entitlement,
    bad symbol) — a distinct case from "no transcript for this quarter" because it means
    further quarter probes will fail for the same reason, not that this one is empty.
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

    for key in ("Error Message", "Note", "Information"):
        if key in data:
            raise AVError(f"AV API [EARNINGS_CALL_TRANSCRIPT] {symbol} {quarter}: {data[key]}")
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


def probe_quarters(today: date) -> list[str]:
    """
    Quarters to probe for "latest", newest first: 4 quarters ahead of today's calendar
    quarter down through 6 quarters behind it (11 candidates). The lookahead covers
    fiscal years that lead the calendar (e.g. NVDA FY ends Jan, so its Q1 FY2027 call
    lands in a calendar quarter that is nominally "future" relative to today).

    Shared by every live on-demand lookup site (earnings_router, research_router,
    industry_data) so the candidate-quarter logic only needs fixing in one place.
    """
    base = today.year * 4 + (today.month - 1) // 3
    result = []
    for offset in range(4, -7, -1):
        total = base + offset
        y, q = divmod(total, 4)
        result.append(f"{y}Q{q + 1}")
    return result


def refresh_latest_transcript(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    api_key: Optional[str],
    limiter: Optional[RateLimiter] = None,
    today: Optional[date] = None,
) -> Optional[str]:
    """
    Probe AV for a transcript newer than whatever is cached for `symbol`, caching whatever
    is found (write-through). Returns the newly-resolved quarter string, or None if nothing
    new was found (including when api_key is falsy).

    Stops probing as soon as AV returns an AVError or a network error, rather than working
    through the whole candidate list — that error means something is systemically wrong
    (rate limit, entitlement, connectivity), not that this one quarter lacks a transcript,
    so continuing would just burn more of the 75-calls/min budget for the same failure.
    """
    if not api_key:
        return None

    best_quarter = get_latest_cached_quarter(conn, symbol)
    candidates = probe_quarters(today or date.today())
    to_probe = [q for q in candidates if q > best_quarter] if best_quarter else candidates

    for quarter in to_probe:
        if limiter is not None:
            limiter.wait()
        try:
            result = fetch_from_av(symbol, quarter, api_key)
        except (AVError, requests.RequestException) as exc:
            log.warning("Stopped probing %s at %s: %s", symbol, quarter, exc)
            return None
        if result is None:
            continue
        transcript_text, api_json = result
        save_transcript(conn, symbol, quarter, transcript_text, api_json)
        return quarter

    return None
