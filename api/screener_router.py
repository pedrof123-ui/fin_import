"""
Stock screener endpoint — queries pe_stats (historic_fundamentals.duckdb) joined
with company_overview (av_financials.duckdb) via DuckDB ATTACH.

Adding a new metric:
  1. Add two fields to ScreenRequest (field_min / field_max)
  2. Add one entry to RANGE_FIELDS mapping the field prefix to its SQL expression
  3. Add the column to the SELECT in _build_query()
"""

import math
import os
from pathlib import Path

import duckdb
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/screen", tags=["screener"])

_HF_DB = Path(os.environ.get("HF_DB_PATH", str(Path(__file__).parent.parent / "data" / "historic_fundamentals.duckdb")))
_AV_DB = Path(os.environ.get("AV_FINANCIALS_DB_PATH", str(Path(__file__).parent.parent / "data" / "av_financials.duckdb")))

# (field_prefix, SQL expression using table aliases ps / co / mp)
# ps  = hf.pe_stats
# co  = latest row from av.company_overview
# mp  = latest row from hf.monthly_pe
RANGE_FIELDS: list[tuple[str, str]] = [
    ("market_cap_b",      "COALESCE(ps.market_cap_b, co.market_cap / 1e9)"),
    ("pe",                "ps.current_pe"),
    ("fwd_pe",            "ps.forward_pe"),
    ("ev_ebitda",         "ps.current_evebitda"),
    ("pfcf",              "ps.current_pfcf"),
    ("ps_ratio",          "ps.current_ps"),
    ("pbv",               "ps.current_pbv"),
    ("rev_growth_1yr",    "ps.rev_growth_1yr"),
    ("rev_cagr_3yr",      "ps.rev_cagr_3yr"),
    ("earn_growth_1yr",   "ps.earn_growth_1yr"),
    ("gross_margin",      "ps.current_gross_margin"),
    ("ebit_margin",       "ps.current_operating_margin"),
    ("fcf_margin",        "ps.current_fcf_margin"),
    ("roe",               "ps.current_roe"),
    ("roic",              "ps.current_roic"),
    ("debt_to_ebitda",    "ps.debt_to_ebitda"),
    ("interest_coverage", "ps.interest_coverage"),
    ("dividend_yield",    "ps.dividend_yield"),
    ("momentum_12_1",     "mp.momentum_12_1"),
    ("goal_low_upside",   "CASE WHEN ps.current_price > 0 AND ps.goal_low  IS NOT NULL THEN (ps.goal_low  / ps.current_price - 1) ELSE NULL END"),
    ("goal_high_upside",  "CASE WHEN ps.current_price > 0 AND ps.goal_high IS NOT NULL THEN (ps.goal_high / ps.current_price - 1) ELSE NULL END"),
    ("goal_pe_upside",    "CASE WHEN ps.current_price > 0 AND ps.goal_pe   IS NOT NULL THEN (ps.goal_pe   / ps.current_price - 1) ELSE NULL END"),
    ("goal_pcf_upside",   "CASE WHEN ps.current_price > 0 AND ps.goal_pcf  IS NOT NULL THEN (ps.goal_pcf  / ps.current_price - 1) ELSE NULL END"),
    ("goal_peg_upside",   "CASE WHEN ps.current_price > 0 AND ps.goal_peg  IS NOT NULL THEN (ps.goal_peg  / ps.current_price - 1) ELSE NULL END"),
    ("goal_bv_upside",    "CASE WHEN ps.current_price > 0 AND ps.goal_bv   IS NOT NULL THEN (ps.goal_bv   / ps.current_price - 1) ELSE NULL END"),
]


class ScreenRequest(BaseModel):
    sectors: list[str] = []
    industries: list[str] = []
    market_cap_b_min: float | None = None
    market_cap_b_max: float | None = None
    pe_min: float | None = None
    pe_max: float | None = None
    fwd_pe_min: float | None = None
    fwd_pe_max: float | None = None
    ev_ebitda_min: float | None = None
    ev_ebitda_max: float | None = None
    pfcf_min: float | None = None
    pfcf_max: float | None = None
    ps_ratio_min: float | None = None
    ps_ratio_max: float | None = None
    pbv_min: float | None = None
    pbv_max: float | None = None
    rev_growth_1yr_min: float | None = None
    rev_growth_1yr_max: float | None = None
    rev_cagr_3yr_min: float | None = None
    rev_cagr_3yr_max: float | None = None
    earn_growth_1yr_min: float | None = None
    earn_growth_1yr_max: float | None = None
    gross_margin_min: float | None = None
    gross_margin_max: float | None = None
    ebit_margin_min: float | None = None
    ebit_margin_max: float | None = None
    fcf_margin_min: float | None = None
    fcf_margin_max: float | None = None
    roe_min: float | None = None
    roe_max: float | None = None
    roic_min: float | None = None
    roic_max: float | None = None
    debt_to_ebitda_min: float | None = None
    debt_to_ebitda_max: float | None = None
    interest_coverage_min: float | None = None
    interest_coverage_max: float | None = None
    dividend_yield_min: float | None = None
    dividend_yield_max: float | None = None
    momentum_12_1_min: float | None = None
    momentum_12_1_max: float | None = None
    goal_low_upside_min: float | None = None
    goal_low_upside_max: float | None = None
    goal_high_upside_min: float | None = None
    goal_high_upside_max: float | None = None
    goal_pe_upside_min: float | None = None
    goal_pe_upside_max: float | None = None
    goal_pcf_upside_min: float | None = None
    goal_pcf_upside_max: float | None = None
    goal_peg_upside_min: float | None = None
    goal_peg_upside_max: float | None = None
    goal_bv_upside_min: float | None = None
    goal_bv_upside_max: float | None = None


_BASE_QUERY = """
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
    co.name                                              AS company_name,
    co.sector,
    co.industry,
    COALESCE(ps.market_cap_b, co.market_cap / 1e9)      AS market_cap_b,
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
    mp.momentum_12_1,
    CASE WHEN ps.current_price > 0 AND ps.goal_low  IS NOT NULL THEN (ps.goal_low  / ps.current_price - 1) ELSE NULL END AS goal_low_upside,
    CASE WHEN ps.current_price > 0 AND ps.goal_high IS NOT NULL THEN (ps.goal_high / ps.current_price - 1) ELSE NULL END AS goal_high_upside,
    CASE WHEN ps.current_price > 0 AND ps.goal_pe   IS NOT NULL THEN (ps.goal_pe   / ps.current_price - 1) ELSE NULL END AS goal_pe_upside,
    CASE WHEN ps.current_price > 0 AND ps.goal_pcf  IS NOT NULL THEN (ps.goal_pcf  / ps.current_price - 1) ELSE NULL END AS goal_pcf_upside,
    CASE WHEN ps.current_price > 0 AND ps.goal_peg  IS NOT NULL THEN (ps.goal_peg  / ps.current_price - 1) ELSE NULL END AS goal_peg_upside,
    CASE WHEN ps.current_price > 0 AND ps.goal_bv   IS NOT NULL THEN (ps.goal_bv   / ps.current_price - 1) ELSE NULL END AS goal_bv_upside
FROM hf.pe_stats ps
LEFT JOIN latest_co co ON ps.ticker = co.ticker
LEFT JOIN latest_mp mp ON ps.ticker = mp.ticker
"""


def _run_screen(req: ScreenRequest) -> list[dict]:
    conditions: list[str] = []
    params: list = []

    if req.sectors:
        placeholders = ", ".join(["?" for _ in req.sectors])
        conditions.append(f"UPPER(co.sector) IN ({placeholders})")
        params.extend([s.upper() for s in req.sectors])
    if req.industries:
        placeholders = ", ".join(["?" for _ in req.industries])
        conditions.append(f"UPPER(co.industry) IN ({placeholders})")
        params.extend([i.upper() for i in req.industries])

    for field, sql_expr in RANGE_FIELDS:
        val_min = getattr(req, f"{field}_min", None)
        val_max = getattr(req, f"{field}_max", None)
        if val_min is not None:
            conditions.append(f"{sql_expr} >= ?")
            params.append(val_min)
        if val_max is not None:
            conditions.append(f"{sql_expr} <= ?")
            params.append(val_max)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order = "ORDER BY COALESCE(ps.market_cap_b, co.market_cap / 1e9) DESC NULLS LAST"
    sql = f"{_BASE_QUERY} {where} {order}"

    conn = duckdb.connect(":memory:")
    conn.execute(f"ATTACH '{_HF_DB}' AS hf (READ_ONLY)")
    conn.execute(f"ATTACH '{_AV_DB}' AS av (READ_ONLY)")
    df = conn.execute(sql, params).df()
    conn.close()

    df = df.replace([np.inf, -np.inf], np.nan)
    records = df.to_dict(orient="records")
    return [
        {k: (None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v)
         for k, v in row.items()}
        for row in records
    ]


@router.get("/metadata")
async def screen_metadata():
    """Return sectors and a sector→industries mapping for filter dropdowns."""
    try:
        conn = duckdb.connect(":memory:")
        conn.execute(f"ATTACH '{_AV_DB}' AS av (READ_ONLY)")
        pairs = conn.execute(
            "SELECT DISTINCT sector, industry FROM av.company_overview "
            "WHERE sector IS NOT NULL AND sector != 'NONE' "
            "  AND industry IS NOT NULL AND industry != 'NONE' "
            "ORDER BY sector, industry"
        ).df()
        conn.close()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    sectors = sorted(pairs["sector"].unique().tolist())
    sector_industries: dict[str, list[str]] = {
        sector: sorted(group["industry"].tolist())
        for sector, group in pairs.groupby("sector")
    }
    return {"sectors": sectors, "sector_industries": sector_industries}


@router.post("")
async def run_screen(req: ScreenRequest):
    """Run the stock screen and return matching tickers."""
    try:
        results = _run_screen(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"count": len(results), "results": results}
