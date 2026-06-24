"""
Earnings calendar endpoint — reads earnings_calendar from av_financials.duckdb,
joined with company_overview for name/sector enrichment.

GET /earnings-calendar
  Returns earnings events sorted by report_date ASC, with a 30-day lookback
  so recently reported events remain visible. Status is derived at query time.
"""

import os
from datetime import date, timedelta
from pathlib import Path

import duckdb
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/earnings-calendar", tags=["earnings-calendar"])

_AV_DB = Path(os.environ.get(
    "AV_FINANCIALS_DB_PATH",
    str(Path(__file__).parent.parent / "data" / "av_financials.duckdb"),
))


@router.get("")
async def get_earnings_calendar():
    if not _AV_DB.exists():
        raise HTTPException(status_code=503, detail="av_financials.duckdb not found")
    try:
        conn = duckdb.connect(str(_AV_DB), read_only=True)
        try:
            cutoff = date.today() - timedelta(days=30)
            rows = conn.execute("""
                WITH latest_overview AS (
                    SELECT ticker, name, sector,
                        ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fetch_date DESC) AS rn
                    FROM company_overview
                )
                SELECT
                    ec.symbol,
                    COALESCE(lo.name, ec.name)     AS name,
                    lo.sector,
                    ec.report_date::VARCHAR         AS report_date,
                    ec.fiscal_date_ending::VARCHAR  AS fiscal_date_ending,
                    ec.estimate,
                    ec.currency,
                    ec.time_of_day
                FROM earnings_calendar ec
                LEFT JOIN latest_overview lo ON lo.ticker = ec.symbol AND lo.rn = 1
                WHERE ec.report_date >= ?
                ORDER BY ec.report_date ASC
            """, [cutoff]).fetchall()
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    today = date.today().isoformat()
    return [
        {
            "symbol": r[0],
            "name": r[1],
            "sector": r[2],
            "report_date": r[3],
            "fiscal_date_ending": r[4],
            "estimate": r[5],
            "currency": r[6],
            "time_of_day": r[7],
            "status": "reported" if r[3] < today else "upcoming",
        }
        for r in rows
    ]
