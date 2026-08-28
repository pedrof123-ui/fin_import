"""
Sector and industry aggregate fundamentals computation.
"""

import logging

import duckdb
import pandas as pd

log = logging.getLogger(__name__)

_MIN_PEERS = 5

_SECTOR_SQL = """
WITH prior_year AS (
    SELECT m.ticker, m.month_end_date, MAX(p.month_end_date) AS prior_date
    FROM monthly_pe m
    JOIN monthly_pe p ON (
        p.ticker = m.ticker
        AND p.month_end_date >= m.month_end_date - INTERVAL '14 months'
        AND p.month_end_date <= m.month_end_date - INTERVAL '10 months'
    )
    GROUP BY m.ticker, m.month_end_date
),
base AS (
    SELECT sm.{group_col} AS group_name, m.month_end_date, m.ticker,
           m.pe_ratio, m.pfcf_ratio, m.ev_ebitda, m.ps_ratio, m.pbv,
           m.earnings_yield, m.fcf_yield, m.ebitda_ev_yield, m.dividend_yield,
           m.roa, m.roe, m.roic,
           m.ttm_gross_margin, m.ttm_operating_margin, m.ttm_fcf_margin,
           m.ttm_capex_intensity, m.ttm_rd_intensity, m.ttm_capex_to_da,
           m.debt_to_ebitda, m.interest_coverage,
           CASE WHEN p.ttm_revenue > 0 AND m.ttm_revenue > 0
                THEN m.ttm_revenue / p.ttm_revenue - 1 END AS rev_growth_1yr,
           CASE WHEN p.ttm_eps > 0 AND m.ttm_eps > 0
                THEN m.ttm_eps / p.ttm_eps - 1 END AS earn_growth_1yr
    FROM monthly_pe m
    JOIN _sector_map sm ON m.ticker = sm.ticker
    LEFT JOIN prior_year py ON py.ticker = m.ticker AND py.month_end_date = m.month_end_date
    LEFT JOIN monthly_pe p  ON p.ticker = py.ticker  AND p.month_end_date = py.prior_date
    WHERE sm.{group_col} IS NOT NULL AND sm.{group_col} NOT IN ('None', '')
    {month_filter}
)
SELECT '{group_type}' AS group_type, group_name, month_end_date,
       COUNT(DISTINCT ticker) AS ticker_count,
       QUANTILE_CONT(pe_ratio, 0.50) FILTER (WHERE pe_ratio > 0) AS pe_median,
       QUANTILE_CONT(pe_ratio, 0.25) FILTER (WHERE pe_ratio > 0) AS pe_p25,
       QUANTILE_CONT(pe_ratio, 0.75) FILTER (WHERE pe_ratio > 0) AS pe_p75,
       QUANTILE_CONT(pfcf_ratio, 0.50) FILTER (WHERE pfcf_ratio > 0) AS pfcf_median,
       QUANTILE_CONT(pfcf_ratio, 0.25) FILTER (WHERE pfcf_ratio > 0) AS pfcf_p25,
       QUANTILE_CONT(pfcf_ratio, 0.75) FILTER (WHERE pfcf_ratio > 0) AS pfcf_p75,
       QUANTILE_CONT(ev_ebitda, 0.50) FILTER (WHERE ev_ebitda > 0) AS evebitda_median,
       QUANTILE_CONT(ev_ebitda, 0.25) FILTER (WHERE ev_ebitda > 0) AS evebitda_p25,
       QUANTILE_CONT(ev_ebitda, 0.75) FILTER (WHERE ev_ebitda > 0) AS evebitda_p75,
       QUANTILE_CONT(ps_ratio, 0.50) FILTER (WHERE ps_ratio > 0) AS ps_median,
       QUANTILE_CONT(ps_ratio, 0.25) FILTER (WHERE ps_ratio > 0) AS ps_p25,
       QUANTILE_CONT(ps_ratio, 0.75) FILTER (WHERE ps_ratio > 0) AS ps_p75,
       QUANTILE_CONT(pbv, 0.50) FILTER (WHERE pbv > 0) AS pbv_median,
       QUANTILE_CONT(earnings_yield, 0.50) FILTER (WHERE earnings_yield IS NOT NULL) AS earnings_yield_median,
       QUANTILE_CONT(fcf_yield, 0.50) FILTER (WHERE fcf_yield IS NOT NULL) AS fcf_yield_median,
       QUANTILE_CONT(ebitda_ev_yield, 0.50) FILTER (WHERE ebitda_ev_yield IS NOT NULL) AS ebitda_ev_yield_median,
       QUANTILE_CONT(dividend_yield, 0.50) FILTER (WHERE dividend_yield IS NOT NULL) AS dividend_yield_median,
       QUANTILE_CONT(roa, 0.50) FILTER (WHERE roa IS NOT NULL) AS roa_median,
       QUANTILE_CONT(roa, 0.25) FILTER (WHERE roa IS NOT NULL) AS roa_p25,
       QUANTILE_CONT(roa, 0.75) FILTER (WHERE roa IS NOT NULL) AS roa_p75,
       QUANTILE_CONT(roe, 0.50) FILTER (WHERE roe IS NOT NULL) AS roe_median,
       QUANTILE_CONT(roe, 0.25) FILTER (WHERE roe IS NOT NULL) AS roe_p25,
       QUANTILE_CONT(roe, 0.75) FILTER (WHERE roe IS NOT NULL) AS roe_p75,
       QUANTILE_CONT(roic, 0.50) FILTER (WHERE roic IS NOT NULL) AS roic_median,
       QUANTILE_CONT(roic, 0.25) FILTER (WHERE roic IS NOT NULL) AS roic_p25,
       QUANTILE_CONT(roic, 0.75) FILTER (WHERE roic IS NOT NULL) AS roic_p75,
       QUANTILE_CONT(rev_growth_1yr, 0.50) FILTER (WHERE rev_growth_1yr IS NOT NULL) AS rev_growth_1yr_median,
       QUANTILE_CONT(earn_growth_1yr, 0.50) FILTER (WHERE earn_growth_1yr IS NOT NULL) AS earn_growth_1yr_median,
       QUANTILE_CONT(ttm_gross_margin, 0.50) FILTER (WHERE ttm_gross_margin IS NOT NULL) AS gross_margin_median,
       QUANTILE_CONT(ttm_operating_margin, 0.50) FILTER (WHERE ttm_operating_margin IS NOT NULL) AS operating_margin_median,
       QUANTILE_CONT(ttm_fcf_margin, 0.50) FILTER (WHERE ttm_fcf_margin IS NOT NULL) AS fcf_margin_median,
       QUANTILE_CONT(ttm_capex_intensity, 0.50) FILTER (WHERE ttm_capex_intensity IS NOT NULL) AS capex_intensity_median,
       QUANTILE_CONT(ttm_rd_intensity, 0.50) FILTER (WHERE ttm_rd_intensity IS NOT NULL) AS rd_intensity_median,
       QUANTILE_CONT(ttm_capex_to_da, 0.50) FILTER (WHERE ttm_capex_to_da IS NOT NULL) AS capex_to_da_median,
       QUANTILE_CONT(debt_to_ebitda, 0.50) FILTER (WHERE debt_to_ebitda IS NOT NULL AND debt_to_ebitda >= 0) AS debt_to_ebitda_median,
       QUANTILE_CONT(interest_coverage, 0.50) FILTER (WHERE interest_coverage IS NOT NULL) AS interest_coverage_median
FROM base
GROUP BY group_name, month_end_date
HAVING COUNT(DISTINCT ticker) >= {min_peers}
ORDER BY group_name, month_end_date
"""


def compute_sector_stats(hf_conn, av_db_path: str, full_rebuild: bool = False) -> pd.DataFrame:
    """
    Compute sector and industry aggregate fundamentals from monthly_pe.

    Loads sector/industry assignments from the latest company_overview snapshot in
    av_financials.duckdb, then aggregates monthly_pe for both group types.

    Args:
        hf_conn:      Open DuckDB connection to historic_fundamentals.duckdb
        av_db_path:   Path to av_financials.duckdb
        full_rebuild: If True, recompute all months; otherwise only new months not yet in sector_stats

    Returns combined DataFrame with sector_stats schema, or empty DataFrame if no overview data.
    """
    av_conn = duckdb.connect(av_db_path, read_only=True)
    try:
        sector_map = av_conn.execute("""
            SELECT ticker, sector, industry
            FROM company_overview
            QUALIFY fetch_date = MAX(fetch_date) OVER (PARTITION BY ticker)
        """).df()
    except Exception as exc:
        log.warning("company_overview unavailable in %s: %s", av_db_path, exc)
        return pd.DataFrame()
    finally:
        av_conn.close()

    if sector_map.empty:
        log.warning("No company_overview data; skipping sector stats")
        return pd.DataFrame()

    hf_conn.register("_sector_map", sector_map)
    try:
        month_filter = (
            "" if full_rebuild else
            "AND m.month_end_date NOT IN (SELECT DISTINCT month_end_date FROM sector_stats)"
        )
        frames = []
        for group_type, group_col in [("sector", "sector"), ("industry", "industry")]:
            sql = _SECTOR_SQL.format(
                group_type=group_type,
                group_col=group_col,
                month_filter=month_filter,
                min_peers=_MIN_PEERS,
            )
            df = hf_conn.execute(sql).df()
            log.debug("%s: %d rows computed", group_type, len(df))
            frames.append(df)
    finally:
        hf_conn.execute("DROP VIEW IF EXISTS _sector_map")

    non_empty = [f for f in frames if not f.empty]
    if not non_empty:
        return pd.DataFrame()
    return pd.concat(non_empty, ignore_index=True)
