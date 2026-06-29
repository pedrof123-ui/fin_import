"""
Sector and industry dashboard endpoints.

GET /sector/snapshot?group_type=sector
    Current (latest month) fundamentals for all sectors or industries,
    with VMQ composite score and period-over-period changes.

GET /sector/history?group_type=sector&name=Technology&months=60
    Monthly timeseries for a single sector/industry (for charts).

GET /sector/companies?group_type=sector&name=Technology
    Companies in a sector/industry with current fundamentals.
"""

import math
import os
from pathlib import Path

import duckdb
import numpy as np
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/sector", tags=["sector"])

_HF_DB = Path(os.environ.get("HF_DB_PATH", str(Path(__file__).parent.parent / "data" / "historic_fundamentals.duckdb")))
_AV_DB = Path(os.environ.get("AV_FINANCIALS_DB_PATH", str(Path(__file__).parent.parent / "data" / "av_financials.duckdb")))


def _clean(records: list[dict]) -> list[dict]:
    return [
        {k: (None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v)
         for k, v in row.items()}
        for row in records
    ]


def _zscore(series: np.ndarray, cap: float = 2.5) -> np.ndarray:
    """Cross-sectional z-score, capped at ±cap. NaN-safe."""
    valid = series[~np.isnan(series)]
    if len(valid) < 2:
        return np.full_like(series, np.nan)
    mu = np.nanmean(series)
    sd = np.nanstd(series)
    if sd == 0:
        return np.zeros_like(series)
    z = (series - mu) / sd
    return np.clip(z, -cap, cap)


def _add_composite(rows: list[dict]) -> list[dict]:
    """
    VMQ composite score:
      0.35 × z(5yr_evebitda_hist_median / current_evebitda)  — value vs own history
      0.35 × z(rev_growth_1yr_median)                         — momentum
      0.30 × z(roic_median)                                   — quality
    """
    n = len(rows)
    if n == 0:
        return rows

    val_arr  = np.array([r.get("evebitda_hist_ratio") for r in rows], dtype=float)
    mom_arr  = np.array([r.get("rev_growth_1yr_median") for r in rows], dtype=float)
    qual_arr = np.array([r.get("roic_median") for r in rows], dtype=float)

    z_val  = _zscore(val_arr)
    z_mom  = _zscore(mom_arr)
    z_qual = _zscore(qual_arr)

    for i, row in enumerate(rows):
        parts = []
        if not math.isnan(z_val[i]):
            parts.append(0.35 * z_val[i])
        if not math.isnan(z_mom[i]):
            parts.append(0.35 * z_mom[i])
        if not math.isnan(z_qual[i]):
            parts.append(0.30 * z_qual[i])
        row["composite_score"] = round(sum(parts) / (len(parts) / (0.35 + 0.35 + 0.30)), 4) if parts else None

    return rows


@router.get("/snapshot")
async def sector_snapshot(group_type: str = "sector"):
    if group_type not in ("sector", "industry"):
        raise HTTPException(status_code=400, detail="group_type must be sector or industry")
    try:
        conn = duckdb.connect(":memory:")
        conn.execute(f"ATTACH '{_HF_DB}' AS hf (READ_ONLY)")

        # Latest month per group
        current = conn.execute("""
            SELECT *
            FROM hf.sector_stats
            WHERE group_type = ?
            QUALIFY month_end_date = MAX(month_end_date) OVER (PARTITION BY group_name)
        """, [group_type]).df()

        if current.empty:
            return {"count": 0, "results": []}

        latest_date = current["month_end_date"].max()

        # Historical evebitda medians (up to 60 months) for VMQ value score
        hist = conn.execute("""
            SELECT group_name,
                   MEDIAN(evebitda_median) AS evebitda_hist_median
            FROM hf.sector_stats
            WHERE group_type = ?
              AND month_end_date >= ? - INTERVAL '60 months'
              AND month_end_date < ?
              AND evebitda_median IS NOT NULL
            GROUP BY group_name
        """, [group_type, latest_date, latest_date]).df()

        # Period snapshots for change columns (months must be literal in INTERVAL)
        def _period_snap(months: int) -> dict:
            df = conn.execute(f"""
                SELECT group_name, pe_median, evebitda_median, rev_growth_1yr_median
                FROM hf.sector_stats
                WHERE group_type = ?
                  AND month_end_date >= ? - INTERVAL '{months} months'
                  AND month_end_date <= ? - INTERVAL '{months} months' + INTERVAL '1 month'
                QUALIFY month_end_date = MAX(month_end_date) OVER (PARTITION BY group_name)
            """, [group_type, latest_date, latest_date]).df()
            return {row["group_name"]: row for _, row in df.iterrows()}

        snap3  = _period_snap(3)
        snap6  = _period_snap(6)
        snap12 = _period_snap(12)

        conn.close()

        hist_map = {row["group_name"]: row["evebitda_hist_median"]
                    for _, row in hist.iterrows()}

        rows = current.replace([np.inf, -np.inf], np.nan).to_dict(orient="records")

        for row in rows:
            name = row["group_name"]
            hist_ev = hist_map.get(name)
            cur_ev  = row.get("evebitda_median")
            # ratio > 1 means currently cheaper than history (history was more expensive)
            row["evebitda_hist_median"] = hist_ev
            row["evebitda_hist_ratio"]  = (
                float(hist_ev) / float(cur_ev)
                if hist_ev and cur_ev and float(cur_ev) > 0
                else None
            )
            for lag_name, snap in [("3m", snap3), ("6m", snap6), ("12m", snap12)]:
                prior = snap.get(name, {})
                prior_pe = prior.get("pe_median")
                prior_ev = prior.get("evebitda_median")
                prior_gr = prior.get("rev_growth_1yr_median")
                row[f"pe_change_{lag_name}"] = (
                    (float(row["pe_median"]) - float(prior_pe)) / float(prior_pe)
                    if row.get("pe_median") and prior_pe and float(prior_pe) > 0
                    else None
                )
                row[f"evebitda_change_{lag_name}"] = (
                    (float(row["evebitda_median"]) - float(prior_ev)) / float(prior_ev)
                    if row.get("evebitda_median") and prior_ev and float(prior_ev) > 0
                    else None
                )
                row[f"rev_growth_change_{lag_name}"] = (
                    float(row["rev_growth_1yr_median"]) - float(prior_gr)
                    if row.get("rev_growth_1yr_median") is not None and prior_gr is not None
                    else None
                )

        rows = _add_composite(rows)
        return {"count": len(rows), "snapshot_date": str(latest_date), "results": _clean(rows)}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history")
async def sector_history(group_type: str = "sector", name: str = "", months: int = 60):
    if group_type not in ("sector", "industry"):
        raise HTTPException(status_code=400, detail="group_type must be sector or industry")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        conn = duckdb.connect(":memory:")
        conn.execute(f"ATTACH '{_HF_DB}' AS hf (READ_ONLY)")
        df = conn.execute(f"""
            SELECT *
            FROM hf.sector_stats
            WHERE group_type = ?
              AND group_name = ?
              AND month_end_date >= (
                  SELECT MAX(month_end_date) - INTERVAL '{months} months' FROM hf.sector_stats
                  WHERE group_type = ? AND group_name = ?
              )
            ORDER BY month_end_date
        """, [group_type, name, group_type, name]).df()
        conn.close()

        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data for {group_type} '{name}'")

        df = df.replace([np.inf, -np.inf], np.nan)
        return {"count": len(df), "results": _clean(df.to_dict(orient="records"))}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/companies")
async def sector_companies(group_type: str = "sector", name: str = ""):
    if group_type not in ("sector", "industry"):
        raise HTTPException(status_code=400, detail="group_type must be sector or industry")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    col = "sector" if group_type == "sector" else "industry"
    try:
        conn = duckdb.connect(":memory:")
        conn.execute(f"ATTACH '{_HF_DB}' AS hf (READ_ONLY)")
        conn.execute(f"ATTACH '{_AV_DB}' AS av (READ_ONLY)")
        df = conn.execute(f"""
            WITH latest_mp AS (
                SELECT ticker, momentum_12_1
                FROM hf.monthly_pe
                QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY month_end_date DESC) = 1
            ),
            latest_co AS (
                SELECT ticker, name, sector, industry, market_cap
                FROM av.company_overview
                QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fetch_date DESC) = 1
            )
            SELECT
                ps.ticker,
                co.name                                         AS company_name,
                co.sector,
                co.industry,
                COALESCE(ps.market_cap_b, co.market_cap / 1e9) AS market_cap_b,
                ps.current_price,
                ps.current_pe,
                ps.forward_pe,
                ps.current_evebitda,
                ps.current_pfcf,
                ps.current_ps,
                ps.current_pbv,
                ps.rev_growth_1yr,
                ps.rev_cagr_3yr,
                ps.earn_growth_1yr,
                ps.current_gross_margin,
                ps.current_operating_margin,
                ps.current_fcf_margin,
                ps.current_roe,
                ps.current_roic,
                ps.debt_to_ebitda,
                ps.interest_coverage,
                ps.dividend_yield,
                mp.momentum_12_1
            FROM hf.pe_stats ps
            LEFT JOIN latest_co co ON ps.ticker = co.ticker
            LEFT JOIN latest_mp mp ON ps.ticker = mp.ticker
            WHERE UPPER(co.{col}) = UPPER(?)
            ORDER BY COALESCE(ps.market_cap_b, co.market_cap / 1e9) DESC NULLS LAST
        """, [name]).df()
        conn.close()

        df = df.replace([np.inf, -np.inf], np.nan)
        return {"count": len(df), "results": _clean(df.to_dict(orient="records"))}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
