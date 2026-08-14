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

# (field_prefix, SQL expression using table aliases ps / co / mp / dr)
# ps  = hf.pe_stats
# co  = latest row from av.company_overview
# mp  = latest row from hf.monthly_pe
# dr  = hf.dcf_results (status='ok' rows only), refreshed monthly by
#       scripts/compute_dcf_batch.py — see DCF_SCREENER_PLAN.md
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
    ("ncav_per_share",    "bs.ncav_per_share"),
    ("price_to_ncav",     "CASE WHEN bs.ncav_per_share > 0 THEN ps.current_price / bs.ncav_per_share ELSE NULL END"),
    ("goal_low_upside",   "CASE WHEN ps.current_price > 0 AND ps.goal_low  IS NOT NULL THEN (ps.goal_low  / ps.current_price - 1) ELSE NULL END"),
    ("goal_high_upside",  "CASE WHEN ps.current_price > 0 AND ps.goal_high IS NOT NULL THEN (ps.goal_high / ps.current_price - 1) ELSE NULL END"),
    ("goal_pe_upside",    "CASE WHEN ps.current_price > 0 AND ps.goal_pe   IS NOT NULL THEN (ps.goal_pe   / ps.current_price - 1) ELSE NULL END"),
    ("goal_pcf_upside",   "CASE WHEN ps.current_price > 0 AND ps.goal_pcf  IS NOT NULL THEN (ps.goal_pcf  / ps.current_price - 1) ELSE NULL END"),
    ("goal_peg_upside",   "CASE WHEN ps.current_price > 0 AND ps.goal_peg  IS NOT NULL THEN (ps.goal_peg  / ps.current_price - 1) ELSE NULL END"),
    ("goal_bv_upside",    "CASE WHEN ps.current_price > 0 AND ps.goal_bv   IS NOT NULL THEN (ps.goal_bv   / ps.current_price - 1) ELSE NULL END"),
    ("dcf_upside",        "CASE WHEN ps.current_price > 0 AND dr.intrinsic_value_per_share IS NOT NULL THEN (dr.intrinsic_value_per_share / ps.current_price - 1) ELSE NULL END"),
    ("q1_rev_yoy",        "qy.q1_rev_yoy"),
    ("q1_earn_yoy",       "qy.q1_earn_yoy"),
    ("q1_ebit_yoy",       "qy.q1_ebit_yoy"),
    ("q2_rev_yoy",        "qy.q2_rev_yoy"),
    ("q2_earn_yoy",       "qy.q2_earn_yoy"),
    ("q2_ebit_yoy",       "qy.q2_ebit_yoy"),
    ("accel_rev_yoy",     "qy.q1_rev_yoy - qy.q2_rev_yoy"),
    ("accel_earn_yoy",    "qy.q1_earn_yoy - qy.q2_earn_yoy"),
    ("accel_ebit_yoy",    "qy.q1_ebit_yoy - qy.q2_ebit_yoy"),
    ("op_leverage_q1",    "qy.q1_ebit_yoy - qy.q1_rev_yoy"),
    # Greenblatt "Magic Formula" (The Little Book That Still Beats the Market, Appendix):
    # ebit_ev_yield = EBIT/EV, greenblatt_roc = EBIT/(Net Working Capital + Net Fixed Assets).
    # Backfilled into monthly_pe by scripts/backfill_greenblatt_factors.py — see
    # docs/greenblatt_factors_test.md (tested for the live composite, not promoted;
    # kept here as an explainable manual screen only).
    ("ebit_ev_yield",     "mp.ebit_ev_yield"),
    ("greenblatt_roc",    "mp.greenblatt_roc"),
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
    ncav_per_share_min: float | None = None
    ncav_per_share_max: float | None = None
    price_to_ncav_min: float | None = None
    price_to_ncav_max: float | None = None
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
    dcf_upside_min: float | None = None
    dcf_upside_max: float | None = None
    q1_rev_yoy_min: float | None = None
    q1_rev_yoy_max: float | None = None
    q1_earn_yoy_min: float | None = None
    q1_earn_yoy_max: float | None = None
    q1_ebit_yoy_min: float | None = None
    q1_ebit_yoy_max: float | None = None
    q2_rev_yoy_min: float | None = None
    q2_rev_yoy_max: float | None = None
    q2_earn_yoy_min: float | None = None
    q2_earn_yoy_max: float | None = None
    q2_ebit_yoy_min: float | None = None
    q2_ebit_yoy_max: float | None = None
    accel_rev_yoy_min: float | None = None
    accel_rev_yoy_max: float | None = None
    accel_earn_yoy_min: float | None = None
    accel_earn_yoy_max: float | None = None
    accel_ebit_yoy_min: float | None = None
    accel_ebit_yoy_max: float | None = None
    op_leverage_q1_min: float | None = None
    op_leverage_q1_max: float | None = None
    ebit_ev_yield_min: float | None = None
    ebit_ev_yield_max: float | None = None
    greenblatt_roc_min: float | None = None
    greenblatt_roc_max: float | None = None


_BASE_QUERY = """
WITH latest_mp AS (
    SELECT ticker, momentum_12_1, ebit_ev_yield, greenblatt_roc
    FROM hf.monthly_pe
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY month_end_date DESC) = 1
),
latest_co AS (
    SELECT ticker, name, sector, industry, market_cap
    FROM av.company_overview
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fetch_date DESC) = 1
),
latest_bs AS (
    -- Graham net current asset value (Security Analysis, Ch. XLIII): NCAV = current assets - ALL liabilities
    SELECT
        ticker,
        (total_current_assets - total_liabilities) / NULLIF(common_stock_shares_outstanding, 0) AS ncav_per_share
    FROM av.balance_sheets
    WHERE period_type = 'quarterly'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fiscal_date_ending DESC) = 1
),
quarters AS (
    SELECT
        ticker,
        fiscal_date_ending,
        total_revenue,
        ebit,
        net_income,
        LAG(total_revenue, 4) OVER (PARTITION BY ticker ORDER BY fiscal_date_ending) AS total_revenue_py,
        LAG(ebit, 4)          OVER (PARTITION BY ticker ORDER BY fiscal_date_ending) AS ebit_py,
        LAG(net_income, 4)    OVER (PARTITION BY ticker ORDER BY fiscal_date_ending) AS net_income_py,
        ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fiscal_date_ending DESC) AS rn
    FROM av.income_statements
    WHERE period_type = 'quarterly'
),
quarterly_yoy AS (
    SELECT
        ticker,
        MAX(CASE WHEN rn = 1 THEN fiscal_date_ending END) AS q1_date,
        MAX(CASE WHEN rn = 1 AND total_revenue_py > 0 THEN total_revenue / total_revenue_py - 1 END) AS q1_rev_yoy,
        MAX(CASE WHEN rn = 1 AND net_income_py    > 0 THEN net_income / net_income_py - 1 END)       AS q1_earn_yoy,
        MAX(CASE WHEN rn = 1 AND ebit_py          > 0 THEN ebit / ebit_py - 1 END)                    AS q1_ebit_yoy,
        MAX(CASE WHEN rn = 2 THEN fiscal_date_ending END) AS q2_date,
        MAX(CASE WHEN rn = 2 AND total_revenue_py > 0 THEN total_revenue / total_revenue_py - 1 END) AS q2_rev_yoy,
        MAX(CASE WHEN rn = 2 AND net_income_py    > 0 THEN net_income / net_income_py - 1 END)       AS q2_earn_yoy,
        MAX(CASE WHEN rn = 2 AND ebit_py          > 0 THEN ebit / ebit_py - 1 END)                    AS q2_ebit_yoy
    FROM quarters
    WHERE rn <= 2
    GROUP BY ticker
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
    mp.ebit_ev_yield,
    mp.greenblatt_roc,
    CASE WHEN mp.ebit_ev_yield IS NOT NULL AND mp.greenblatt_roc IS NOT NULL
         THEN RANK() OVER (ORDER BY mp.ebit_ev_yield  DESC NULLS LAST)
            + RANK() OVER (ORDER BY mp.greenblatt_roc DESC NULLS LAST)
         ELSE NULL END                                   AS magic_formula_rank,
    bs.ncav_per_share,
    CASE WHEN bs.ncav_per_share > 0 THEN ps.current_price / bs.ncav_per_share ELSE NULL END AS price_to_ncav,
    CASE WHEN ps.current_price > 0 AND ps.goal_low  IS NOT NULL THEN (ps.goal_low  / ps.current_price - 1) ELSE NULL END AS goal_low_upside,
    CASE WHEN ps.current_price > 0 AND ps.goal_high IS NOT NULL THEN (ps.goal_high / ps.current_price - 1) ELSE NULL END AS goal_high_upside,
    CASE WHEN ps.current_price > 0 AND ps.goal_pe   IS NOT NULL THEN (ps.goal_pe   / ps.current_price - 1) ELSE NULL END AS goal_pe_upside,
    CASE WHEN ps.current_price > 0 AND ps.goal_pcf  IS NOT NULL THEN (ps.goal_pcf  / ps.current_price - 1) ELSE NULL END AS goal_pcf_upside,
    CASE WHEN ps.current_price > 0 AND ps.goal_peg  IS NOT NULL THEN (ps.goal_peg  / ps.current_price - 1) ELSE NULL END AS goal_peg_upside,
    CASE WHEN ps.current_price > 0 AND ps.goal_bv   IS NOT NULL THEN (ps.goal_bv   / ps.current_price - 1) ELSE NULL END AS goal_bv_upside,
    dr.intrinsic_value_per_share                         AS dcf_intrinsic_value,
    CASE WHEN ps.current_price > 0 AND dr.intrinsic_value_per_share IS NOT NULL THEN (dr.intrinsic_value_per_share / ps.current_price - 1) ELSE NULL END AS dcf_upside,
    qy.q1_date,
    qy.q1_rev_yoy,
    qy.q1_earn_yoy,
    qy.q1_ebit_yoy,
    qy.q2_date,
    qy.q2_rev_yoy,
    qy.q2_earn_yoy,
    qy.q2_ebit_yoy,
    qy.q1_rev_yoy  - qy.q2_rev_yoy  AS accel_rev_yoy,
    qy.q1_earn_yoy - qy.q2_earn_yoy AS accel_earn_yoy,
    qy.q1_ebit_yoy - qy.q2_ebit_yoy AS accel_ebit_yoy,
    qy.q1_ebit_yoy - qy.q1_rev_yoy  AS op_leverage_q1
FROM hf.pe_stats ps
LEFT JOIN latest_co co ON ps.ticker = co.ticker
LEFT JOIN latest_mp mp ON ps.ticker = mp.ticker
LEFT JOIN latest_bs bs ON ps.ticker = bs.ticker
LEFT JOIN quarterly_yoy qy ON ps.ticker = qy.ticker
LEFT JOIN hf.dcf_results dr ON ps.ticker = dr.ticker AND dr.status = 'ok'
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
