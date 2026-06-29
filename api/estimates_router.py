"""
Analyst estimates endpoint — reads earnings_estimates from historic_fundamentals.duckdb.

GET /estimates/{ticker}
  Returns current estimate snapshots (latest fetched_at per period) with revision
  deltas, plus the full time-series history for trend charts.

EPS revision deltas (7d/30d/60d/90d) come directly from AV fields.
Revenue revision deltas (7d/30d) are derived from prior fetched_at snapshots in the DB.
"""

import os
from pathlib import Path
from typing import Any

import duckdb
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/estimates", tags=["estimates"])

_HF_DB = Path(os.environ.get("HF_DB_PATH", str(Path(__file__).parent.parent / "data" / "historic_fundamentals.duckdb")))


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        r = float(v)
        return None if r != r else r
    except (TypeError, ValueError):
        return None


def _pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / abs(b) * 100, 2)


def _get_periods(conn: duckdb.DuckDBPyConnection, ticker: str) -> list[dict]:
    rows = conn.execute("""
        WITH latest AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY fiscal_date, horizon ORDER BY fetched_at DESC) AS rn
            FROM earnings_estimates
            WHERE ticker = ?
        ),
        prior_7d AS (
            SELECT ee.fiscal_date, ee.horizon, ee.rev_avg AS rev_avg_p7,
                ROW_NUMBER() OVER (PARTITION BY ee.fiscal_date, ee.horizon ORDER BY ee.fetched_at DESC) AS rn
            FROM earnings_estimates ee
            INNER JOIN (SELECT fiscal_date, horizon, fetched_at FROM latest WHERE rn = 1) AS l
                ON l.fiscal_date = ee.fiscal_date AND l.horizon = ee.horizon
            WHERE ee.ticker = ? AND ee.fetched_at <= l.fetched_at - INTERVAL '7 days'
        ),
        prior_30d AS (
            SELECT ee.fiscal_date, ee.horizon, ee.rev_avg AS rev_avg_p30,
                ROW_NUMBER() OVER (PARTITION BY ee.fiscal_date, ee.horizon ORDER BY ee.fetched_at DESC) AS rn
            FROM earnings_estimates ee
            INNER JOIN (SELECT fiscal_date, horizon, fetched_at FROM latest WHERE rn = 1) AS l
                ON l.fiscal_date = ee.fiscal_date AND l.horizon = ee.horizon
            WHERE ee.ticker = ? AND ee.fetched_at <= l.fetched_at - INTERVAL '30 days'
        )
        SELECT
            l.fiscal_date::VARCHAR, l.horizon,
            strftime(l.fetched_at, '%Y-%m-%d') AS fetched_at,
            l.eps_avg, l.eps_high, l.eps_low, l.eps_count,
            l.eps_avg_7d, l.eps_avg_30d, l.eps_avg_60d, l.eps_avg_90d,
            l.eps_rev_up_7d, l.eps_rev_down_7d, l.eps_rev_up_30d, l.eps_rev_down_30d,
            l.rev_avg, l.rev_high, l.rev_low, l.rev_count,
            p7.rev_avg_p7,
            p30.rev_avg_p30
        FROM latest l
        LEFT JOIN prior_7d p7
            ON p7.fiscal_date = l.fiscal_date AND p7.horizon = l.horizon AND p7.rn = 1
        LEFT JOIN prior_30d p30
            ON p30.fiscal_date = l.fiscal_date AND p30.horizon = l.horizon AND p30.rn = 1
        WHERE l.rn = 1 AND l.fiscal_date >= today() - INTERVAL '60 days'
        ORDER BY l.horizon DESC, l.fiscal_date
    """, [ticker, ticker, ticker]).fetchall()

    result = []
    for r in rows:
        (fiscal_date, horizon, fetched_at,
         eps_avg, eps_high, eps_low, eps_count,
         eps_avg_7d, eps_avg_30d, eps_avg_60d, eps_avg_90d,
         eps_rev_up_7d, eps_rev_down_7d, eps_rev_up_30d, eps_rev_down_30d,
         rev_avg, rev_high, rev_low, rev_count,
         rev_avg_p7, rev_avg_p30) = r

        eps_avg = _f(eps_avg)
        eps_avg_7d = _f(eps_avg_7d)
        eps_avg_30d = _f(eps_avg_30d)
        rev_avg = _f(rev_avg)
        rev_avg_p7 = _f(rev_avg_p7)
        rev_avg_p30 = _f(rev_avg_p30)

        result.append({
            "fiscal_date": fiscal_date,
            "horizon": horizon,
            "fetched_at": fetched_at,
            "eps_avg": eps_avg,
            "eps_high": _f(eps_high),
            "eps_low": _f(eps_low),
            "eps_count": eps_count,
            "eps_avg_7d": eps_avg_7d,
            "eps_avg_30d": eps_avg_30d,
            "eps_chg_7d": round(eps_avg - eps_avg_7d, 4) if eps_avg is not None and eps_avg_7d is not None else None,
            "eps_chg_30d": round(eps_avg - eps_avg_30d, 4) if eps_avg is not None and eps_avg_30d is not None else None,
            "eps_chg_pct_7d": _pct(eps_avg, eps_avg_7d),
            "eps_chg_pct_30d": _pct(eps_avg, eps_avg_30d),
            "eps_rev_up_7d": eps_rev_up_7d,
            "eps_rev_down_7d": eps_rev_down_7d,
            "eps_rev_up_30d": eps_rev_up_30d,
            "eps_rev_down_30d": eps_rev_down_30d,
            "rev_avg": rev_avg,
            "rev_high": _f(rev_high),
            "rev_low": _f(rev_low),
            "rev_count": rev_count,
            "rev_chg_7d": round(rev_avg - rev_avg_p7, 0) if rev_avg is not None and rev_avg_p7 is not None else None,
            "rev_chg_pct_7d": _pct(rev_avg, rev_avg_p7),
            "rev_chg_30d": round(rev_avg - rev_avg_p30, 0) if rev_avg is not None and rev_avg_p30 is not None else None,
            "rev_chg_pct_30d": _pct(rev_avg, rev_avg_p30),
        })
    return result


def _get_history(conn: duckdb.DuckDBPyConnection, ticker: str) -> list[dict]:
    rows = conn.execute("""
        SELECT
            strftime(fetched_at, '%Y-%m-%d') AS fetched_at,
            fiscal_date::VARCHAR AS fiscal_date,
            horizon,
            eps_avg,
            rev_avg
        FROM earnings_estimates
        WHERE ticker = ? AND fiscal_date >= today() - INTERVAL '60 days'
        ORDER BY fiscal_date, fetched_at
    """, [ticker]).fetchall()
    return [
        {
            "fetched_at": r[0],
            "fiscal_date": r[1],
            "horizon": r[2],
            "eps_avg": _f(r[3]),
            "rev_avg": _f(r[4]),
        }
        for r in rows
    ]


@router.get("/{ticker}")
async def get_estimates(ticker: str):
    ticker = ticker.upper()
    if not _HF_DB.exists():
        raise HTTPException(status_code=503, detail="historic_fundamentals.duckdb not found")
    try:
        conn = duckdb.connect(str(_HF_DB), read_only=True)
        try:
            periods = _get_periods(conn, ticker)
            history = _get_history(conn, ticker)
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not periods and not history:
        raise HTTPException(status_code=404, detail=f"No estimates found for {ticker}")

    return {"ticker": ticker, "periods": periods, "history": history}
