"""
Storage for SEC-sourced debt tranche/maturity data (PLAN_DEBT_MATURITY.md Phase 2).

Two tables:
  - debt_tranches: one row per disclosed tranche/year-bucket, as parsed by
    scripts/fetch_debt_maturity.py. No primary key -- a filer can legitimately reuse the
    same raw_label (e.g. Southern Company's subsidiaries each have their own "Senior
    notes" tranche), so a ticker's rows are refreshed by delete-then-reinsert rather than
    upserted, same pattern as historic_fundamentals/mda.py.
  - debt_maturity_summary: one row per ticker/fiscal_year -- the weighted-average numbers
    dcf/wacc.py's Phase 3 terminal-value split actually consumes, computed by
    debt_maturity/summary.py from debt_tranches.
"""

from pathlib import Path
from typing import Optional

import duckdb

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "debt_maturity.duckdb"


def open_db(db_path: Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open (or create) the debt maturity DuckDB and ensure schema is current."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS debt_tranches (
            ticker          VARCHAR NOT NULL,
            cik             VARCHAR,
            fiscal_year     INTEGER,
            filed_date      DATE,
            currency        VARCHAR,
            coupon_rate     DOUBLE,
            maturity_year   INTEGER,
            amount          DOUBLE,
            source_concept  VARCHAR,
            raw_label       VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS debt_maturity_summary (
            ticker                          VARCHAR NOT NULL,
            fiscal_year                     INTEGER NOT NULL,
            weighted_avg_years_to_maturity  DOUBLE,
            pct_maturity_dated              DOUBLE,
            weighted_avg_coupon_near_term   DOUBLE,
            weighted_avg_coupon_long_dated  DOUBLE,
            total_debt_covered              DOUBLE,
            total_debt_reported             DOUBLE,
            computed_at                     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (ticker, fiscal_year)
        )
    """)
    return conn


def delete_ticker(conn: duckdb.DuckDBPyConnection, ticker: str) -> None:
    ticker = ticker.upper()
    conn.execute("DELETE FROM debt_tranches WHERE ticker = ?", [ticker])
    conn.execute("DELETE FROM debt_maturity_summary WHERE ticker = ?", [ticker])
    conn.commit()


def save_tranches(conn: duckdb.DuckDBPyConnection, ticker: str, rows: list[dict]) -> None:
    """Replace all debt_tranches rows for `ticker` (delete_ticker first, then this) --
    call site owns the delete so a caller doing both tranches and summary in one refresh
    doesn't delete twice."""
    if not rows:
        return
    conn.executemany(
        """
        INSERT INTO debt_tranches
            (ticker, cik, fiscal_year, filed_date, currency, coupon_rate, maturity_year,
             amount, source_concept, raw_label)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            [
                ticker.upper(), r.get("cik"), r.get("fiscal_year"), r.get("filed_date"),
                r.get("currency"), r.get("coupon_rate"), r.get("maturity_year"),
                r.get("amount"), r.get("source_concept"), r.get("raw_label"),
            ]
            for r in rows
        ],
    )
    conn.commit()


def save_summary(conn: duckdb.DuckDBPyConnection, ticker: str, summary: dict) -> None:
    conn.execute(
        """
        INSERT INTO debt_maturity_summary
            (ticker, fiscal_year, weighted_avg_years_to_maturity, pct_maturity_dated,
             weighted_avg_coupon_near_term, weighted_avg_coupon_long_dated,
             total_debt_covered, total_debt_reported, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, now())
        ON CONFLICT (ticker, fiscal_year) DO UPDATE SET
            weighted_avg_years_to_maturity = EXCLUDED.weighted_avg_years_to_maturity,
            pct_maturity_dated             = EXCLUDED.pct_maturity_dated,
            weighted_avg_coupon_near_term  = EXCLUDED.weighted_avg_coupon_near_term,
            weighted_avg_coupon_long_dated = EXCLUDED.weighted_avg_coupon_long_dated,
            total_debt_covered             = EXCLUDED.total_debt_covered,
            total_debt_reported            = EXCLUDED.total_debt_reported,
            computed_at                    = EXCLUDED.computed_at
        """,
        [
            ticker.upper(), summary["fiscal_year"], summary["weighted_avg_years_to_maturity"],
            summary["pct_maturity_dated"], summary["weighted_avg_coupon_near_term"],
            summary["weighted_avg_coupon_long_dated"], summary["total_debt_covered"],
            summary.get("total_debt_reported"),
        ],
    )
    conn.commit()


def get_summary(ticker: str, db_path: Path = DEFAULT_DB_PATH) -> Optional[dict]:
    """Latest debt_maturity_summary row for `ticker`, or None if it has no coverage.
    Null-safe entry point for downstream consumers (dcf/wacc.py Phase 3, api/ai_dcf_data.py
    Phase 4) -- a missing file or missing ticker both just return None."""
    if not db_path.exists():
        return None
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        row = conn.execute(
            """
            SELECT ticker, fiscal_year, weighted_avg_years_to_maturity, pct_maturity_dated,
                   weighted_avg_coupon_near_term, weighted_avg_coupon_long_dated,
                   total_debt_covered, total_debt_reported
            FROM debt_maturity_summary
            WHERE ticker = ?
            ORDER BY fiscal_year DESC
            LIMIT 1
            """,
            [ticker.upper()],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    cols = ["ticker", "fiscal_year", "weighted_avg_years_to_maturity", "pct_maturity_dated",
            "weighted_avg_coupon_near_term", "weighted_avg_coupon_long_dated",
            "total_debt_covered", "total_debt_reported"]
    return dict(zip(cols, row))
