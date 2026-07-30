"""
MD&A (Management Discussion & Analysis) text store, sourced from SEC EDGAR 10-K/10-Q filings
via edgartools.

Used by:
  - scripts/mda_backfill.py   (one-time full-universe backfill)
  - scripts/mda_update.py     (weekly incremental cron update)
  - scripts/manage_tickers.py (per-ticker add/delete)

See PLAN_MDA.md for the full design (schema, extraction key choice, rate limiting).
"""

import os
import signal
from datetime import date
from pathlib import Path
from typing import Literal, Optional

import duckdb

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "mda_filings.duckdb"

Form = Literal["10-K", "10-Q"]

# edgartools section key per form. 10-Q's 'mda' key routes through a deprecated legacy parser
# that frequently returns near-empty text (confirmed by direct sampling) — part_i_item_2 is the
# correct key for the new parser. No fallback retry: a second key attempt roughly doubles the
# cost of an already-failing filing (each attempt runs edgartools' TOC/heading/pattern-matching
# section-detection cascade), which measured ~6s/filing in practice — not worth the marginal
# coverage gain at full-universe scale (see PLAN_MDA.md Decision 6).
_SECTION_KEYS: dict[Form, str] = {
    "10-K": "mda",
    "10-Q": "part_i_item_2",
}
_MIN_OK_CHARS = 500

# Hard per-filing wall-clock bound. Normal filings take 2-90s to parse; a filing that runs long
# is treated as pathological (confirmed in production: one bank 10-Q hung the full-universe
# backfill for 5.5+ hours) rather than let it stall the whole batch. Uses SIGALRM — only safe
# from the main thread, which holds for every caller (mda_backfill.py, mda_update.py,
# manage_tickers.py are all single-threaded).
_FETCH_TIMEOUT_SECONDS = 90


class _FetchTimeout(Exception):
    pass


def _alarm_handler(signum, frame):
    raise _FetchTimeout()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def open_db(db_path: Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open (or create) the MD&A DuckDB and ensure schema is current."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mda_filings (
            ticker             VARCHAR NOT NULL,
            cik                VARCHAR,
            form               VARCHAR NOT NULL,
            fiscal_period_end  DATE    NOT NULL,
            filing_date        DATE,
            accession_no       VARCHAR,
            section_key        VARCHAR,
            mda_text           VARCHAR,
            char_count         INTEGER,
            status             VARCHAR NOT NULL,
            downloaded_at      TIMESTAMP,
            PRIMARY KEY (ticker, form, fiscal_period_end)
        )
    """)
    return conn


def delete_ticker(conn: duckdb.DuckDBPyConnection, ticker: str) -> int:
    """Delete all MD&A rows for ticker. Returns rows deleted."""
    ticker = ticker.upper()
    before = conn.execute("SELECT COUNT(*) FROM mda_filings WHERE ticker = ?", [ticker]).fetchone()[0]
    conn.execute("DELETE FROM mda_filings WHERE ticker = ?", [ticker])
    conn.commit()
    return before


def is_cached(conn: duckdb.DuckDBPyConnection, ticker: str, form: str, fiscal_period_end: date) -> bool:
    row = conn.execute(
        "SELECT 1 FROM mda_filings WHERE ticker = ? AND form = ? AND fiscal_period_end = ?",
        [ticker, form, fiscal_period_end],
    ).fetchone()
    return row is not None


def get_cached_mda(
    conn: duckdb.DuckDBPyConnection,
    ticker: str,
    form: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """Return cached MD&A rows for a ticker, newest fiscal_period_end first."""
    where = "WHERE ticker = ?" + (" AND form = ?" if form else "")
    params = [ticker] + ([form] if form else [])
    sql = f"""
        SELECT ticker, cik, form, fiscal_period_end, filing_date, accession_no,
               section_key, mda_text, char_count, status, downloaded_at
        FROM mda_filings {where}
        ORDER BY fiscal_period_end DESC
    """
    if limit is not None:
        sql += " LIMIT ?"
        params = params + [limit]
    cols = ["ticker", "cik", "form", "fiscal_period_end", "filing_date", "accession_no",
            "section_key", "mda_text", "char_count", "status", "downloaded_at"]
    rows = conn.execute(sql, params).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def save_mda_row(conn: duckdb.DuckDBPyConnection, row: dict) -> None:
    conn.execute(
        """
        INSERT INTO mda_filings
            (ticker, cik, form, fiscal_period_end, filing_date, accession_no,
             section_key, mda_text, char_count, status, downloaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (ticker, form, fiscal_period_end) DO UPDATE SET
            cik           = EXCLUDED.cik,
            filing_date   = EXCLUDED.filing_date,
            accession_no  = EXCLUDED.accession_no,
            section_key   = EXCLUDED.section_key,
            mda_text      = EXCLUDED.mda_text,
            char_count    = EXCLUDED.char_count,
            status        = EXCLUDED.status,
            downloaded_at = EXCLUDED.downloaded_at
        """,
        [row["ticker"], row["cik"], row["form"], row["fiscal_period_end"], row["filing_date"],
         row["accession_no"], row["section_key"], row["mda_text"], row["char_count"],
         row["status"], row["downloaded_at"]],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# EDGAR fetch
# ---------------------------------------------------------------------------

_identity_set = False


def _ensure_identity() -> Optional[str]:
    """Set the edgartools SEC identity once per process. Returns an error string if SEC_ID
    is not configured, else None."""
    global _identity_set
    identity = os.getenv("SEC_ID", "")
    if not identity:
        return "SEC_ID not set in environment"
    if not _identity_set:
        from edgar import set_identity
        set_identity(identity)
        # edgartools' HTTP cache caches every filing's raw SGML (all exhibits included, often
        # 100MB+) forever with no eviction, which filled the disk during the full-universe
        # backfill (~79GB in a few hours). We never re-request the same filing URL within a
        # run, so the cache buys nothing here — disable it. Rate limiting (9 req/sec) is a
        # separate mechanism and is unaffected.
        import edgar.httpclient as _edgar_http
        _edgar_http.HTTP_MGR = _edgar_http.get_http_mgr(
            cache_enabled=False, request_per_sec_limit=_edgar_http.get_edgar_rate_limit_per_sec()
        )
        _identity_set = True
    return None


def _extract_section(obj, form: Form) -> tuple[str, str, str]:
    """Extract the MD&A section for this form's key. Returns (text, section_key, status)."""
    key = _SECTION_KEYS[form]
    try:
        text = str(obj[key] or "")
    except Exception:
        text = ""
    status = "ok" if len(text) >= _MIN_OK_CHARS else "empty"
    return text, key, status


def fetch_mda(ticker: str, form: Form, filing, fiscal_period_end: date) -> dict:
    """Extract MD&A from an already-resolved edgartools filing object. Never raises —
    EDGAR/parse failures come back as status='error' rows."""
    from datetime import datetime

    ticker = ticker.upper()
    row = {
        "ticker": ticker,
        "cik": None,
        "form": form,
        "fiscal_period_end": fiscal_period_end,
        "filing_date": getattr(filing, "filing_date", None),
        "accession_no": getattr(filing, "accession_no", None),
        "section_key": None,
        "mda_text": None,
        "char_count": 0,
        "status": "error",
        "downloaded_at": datetime.utcnow(),
    }
    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(_FETCH_TIMEOUT_SECONDS)
    try:
        obj = filing.obj()
        if obj is None:
            raise ValueError(f"Could not parse {form} filing for {ticker}")
        text, section_key, status = _extract_section(obj, form)
        row.update(cik=str(filing.cik), section_key=section_key, mda_text=text,
                    char_count=len(text), status=status)
    except _FetchTimeout:
        row["status"] = "error"
    except Exception:
        pass
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
    return row


def fetch_all_mda_for_ticker(
    ticker: str,
    n_annual: int = 20,
    n_quarterly: int = 20,
    force: bool = False,
    conn: Optional[duckdb.DuckDBPyConnection] = None,
    dry_run: bool = False,
) -> dict:
    """Backfill up to n_annual 10-K + n_quarterly 10-Q MD&A filings for one ticker.
    Skips filings already cached unless force=True. Returns a status-count summary.

    With dry_run=True, resolves filing metadata (cheap) and counts what would be fetched
    under the "new"/"skipped" keys, without parsing filing content (the expensive step) or
    writing anything."""
    ticker = ticker.upper()
    own_conn = conn is None
    if own_conn:
        conn = open_db()

    summary: dict = {"10-K": {"ok": 0, "empty": 0, "error": 0, "skipped": 0, "new": 0},
                      "10-Q": {"ok": 0, "empty": 0, "error": 0, "skipped": 0, "new": 0}}

    id_error = _ensure_identity()
    if id_error:
        if own_conn:
            conn.close()
        raise RuntimeError(id_error)

    try:
        from edgar import Company
        company = Company(ticker)
    except Exception:
        if own_conn:
            conn.close()
        return summary

    for form, n in (("10-K", n_annual), ("10-Q", n_quarterly)):
        try:
            filings = company.get_filings(form=form).latest(n)
        except Exception:
            continue
        if filings is None:
            continue
        filings = filings if hasattr(filings, "__iter__") else [filings]
        for filing in filings:
            try:
                fiscal_period_end = date.fromisoformat(filing.period_of_report)
            except Exception:
                continue
            if not force and is_cached(conn, ticker, form, fiscal_period_end):
                summary[form]["skipped"] += 1
                continue
            if dry_run:
                summary[form]["new"] += 1
                continue
            row = fetch_mda(ticker, form, filing, fiscal_period_end)
            save_mda_row(conn, row)
            summary[form][row["status"]] = summary[form].get(row["status"], 0) + 1

    if own_conn:
        conn.close()
    return summary
