"""
Historic fundamentals database: data/historic_fundamentals.duckdb

Three tables:
    monthly_pe       Monthly PE/P/FCF/EV/EBITDA timeseries (~20 years, one row per month)
    pe_stats         Pre-computed statistics snapshot per ticker
    earnings_estimates  Time-series snapshots of analyst EPS/revenue estimates

Usage:
    from historic_fundamentals.db import HistoricFundamentalsDB

    db = HistoricFundamentalsDB()

    stats_df = db.query_pe_stats(["AAPL", "MSFT"])
    ts_df    = db.query_pe_timeseries(["AAPL"], start_date=date(2020, 1, 1))
    est_df   = db.query_estimates(["AAPL"], horizon="fiscal quarter")
    tickers  = db.list_tickers()

    db.close()

Typical columns returned:
    query_pe_stats:
        ticker, current_pe, pe_lt_median, pe_p10, pe_p25, pe_p75, pe_p90,
        pe_rolling_5yr_median, forward_pe, forward_12m_eps,
        current_ttm_eps, months_available, updated_at,
        current_earnings_yield, earnings_yield_3y_avg, earnings_yield_5y_avg,
        forward_earnings_yield, normalized_pe_5y,
        current_pfcf, pfcf_lt_median, pfcf_p25, pfcf_p75, pfcf_rolling_5yr_median,
        current_fcf_yield, forward_pfcf, fcf_margin_5yr_median,
        fcf_growth_1yr, fcf_cagr_3yr, fcf_cagr_5yr,
        current_evebitda, evebitda_lt_median, evebitda_p25, evebitda_p75,
        evebitda_rolling_5yr_median,
        current_ps, ps_lt_median, ps_p25, ps_p75, ps_rolling_5yr_median, forward_ps,
        current_roa, roa_lt_median, roa_p25, roa_p75, roa_rolling_5yr_median,
        current_roe, roe_lt_median, roe_p25, roe_p75, roe_rolling_5yr_median,
        current_roic, roic_lt_median, roic_p25, roic_p75, roic_rolling_5yr_median,
        current_pbv, pbv_lt_median, pbv_p25, pbv_p75, pbv_rolling_5yr_median,
        current_ptbv, ptbv_lt_median, ptbv_p25, ptbv_p75, ptbv_rolling_5yr_median
    query_pe_timeseries:
        ticker, month_end_date, price, ttm_eps, pe_ratio, pe_rolling_5yr_median,
        ttm_source, shares, ttm_dividend, dividend_yield, ttm_revenue,
        ttm_fcf, pfcf_ratio, pfcf_rolling_5yr_median, fcf_yield,
        ttm_ebitda, ev_ebitda, ev_ebitda_rolling_5yr_median,
        earnings_yield, earnings_yield_3y_avg, earnings_yield_5y_avg,
        normalized_pe_5y, updated_at
    query_estimates:
        ticker, fiscal_date, horizon, eps_avg/high/low/count,
        rev_avg/high/low/count, fetched_at
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = str(ROOT / "data" / "historic_fundamentals.duckdb")

log = logging.getLogger(__name__)


class HistoricFundamentalsDB:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.conn = duckdb.connect(db_path)
        self._create_schema()
        log.debug("Connected to %s", db_path)

    def _rename_column_if_exists(self, table: str, old: str, new: str) -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = ? AND column_name = ?",
            [table, old],
        ).fetchone()
        if exists:
            self.conn.execute(f'ALTER TABLE {table} RENAME COLUMN "{old}" TO "{new}"')

    def _create_schema(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS monthly_pe (
                ticker                     VARCHAR  NOT NULL,
                month_end_date             DATE     NOT NULL,
                price                      DOUBLE,
                ttm_eps                    DOUBLE,
                pe_ratio                   DOUBLE,
                pe_rolling_5yr_median      DOUBLE,
                ttm_source                 VARCHAR,
                shares                     DOUBLE,
                ttm_dividend               DOUBLE,
                dividend_yield             DOUBLE,
                ttm_revenue                DOUBLE,
                ttm_fcf                    DOUBLE,
                pfcf_ratio                 DOUBLE,
                pfcf_rolling_5yr_median    DOUBLE,
                fcf_yield                  DOUBLE,
                ttm_ebitda                 DOUBLE,
                ev_ebitda                  DOUBLE,
                ev_ebitda_rolling_5yr_median DOUBLE,
                ps_ratio                   DOUBLE,
                ps_rolling_5yr_median      DOUBLE,
                roa                        DOUBLE,
                roa_rolling_5yr_median     DOUBLE,
                roe                        DOUBLE,
                roe_rolling_5yr_median     DOUBLE,
                roic                       DOUBLE,
                roic_rolling_5yr_median    DOUBLE,
                pbv                        DOUBLE,
                pbv_rolling_5yr_median     DOUBLE,
                ptbv                       DOUBLE,
                ptbv_rolling_5yr_median    DOUBLE,
                updated_at                 TIMESTAMP,
                PRIMARY KEY (ticker, month_end_date)
            )
        """)
        # Migration: add/rename columns introduced after initial schema
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ttm_dividend DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS dividend_yield DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ttm_revenue DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ttm_fcf DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS pfcf_ratio DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS pfcf_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS fcf_yield DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ttm_ebitda DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ev_ebitda DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ev_ebitda_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ps_ratio DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ps_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS roa DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS roa_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS roe DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS roe_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS roic DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS roic_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS pbv DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS pbv_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ptbv DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ptbv_rolling_5yr_median DOUBLE")
        self._rename_column_if_exists("monthly_pe", "rolling_5yr_median", "pe_rolling_5yr_median")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS goal_pe   DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS goal_pcf  DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS goal_peg  DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS goal_bv   DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS goal_2x   DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS goal_low  DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS goal_high DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS earnings_yield        DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS earnings_yield_3y_avg DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS earnings_yield_5y_avg DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS normalized_pe_5y      DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS fcf_yield_3y_avg      DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS fcf_yield_5y_avg      DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS normalized_pfcf_5y    DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ebitda_ev_yield        DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ebitda_ev_yield_3y_avg DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ebitda_ev_yield_5y_avg DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS normalized_evebitda_5y DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS normalized_ps_5y       DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ttm_gross_margin        DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ttm_operating_margin    DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ttm_fcf_margin          DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS debt_to_ebitda          DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS interest_coverage       DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS gross_margin_5y_median  DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS gross_margin_slope_5y   DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS operating_margin_5y_median  DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS operating_margin_slope_5y   DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS operating_margin_change_3y  DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS fcf_margin_5y_median    DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS fcf_margin_change_3y    DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS roa_stability_5y        DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS earnings_yield_norm     DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS fcf_yield_norm          DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ev_ebitda_norm          DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ps_ratio_norm           DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS momentum_12_1           DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS earnings_quality        DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS feature_available_date DATE")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pe_stats (
                ticker                     VARCHAR  PRIMARY KEY,
                updated_at                 TIMESTAMP,
                pe_lt_median               DOUBLE,
                pe_p10                     DOUBLE,
                pe_p25                     DOUBLE,
                pe_p75                     DOUBLE,
                pe_p90                     DOUBLE,
                months_available           INTEGER,
                pe_rolling_5yr_median      DOUBLE,
                current_pe                 DOUBLE,
                current_ttm_eps            DOUBLE,
                forward_pe                 DOUBLE,
                forward_12m_eps            DOUBLE,
                ttm_dividend               DOUBLE,
                dividend_yield             DOUBLE,
                rev_growth_1yr             DOUBLE,
                rev_cagr_3yr               DOUBLE,
                rev_cagr_5yr               DOUBLE,
                rev_ntm_growth_est         DOUBLE,
                market_cap_b               DOUBLE,
                earn_growth_1yr            DOUBLE,
                earn_cagr_3yr              DOUBLE,
                earn_cagr_5yr              DOUBLE,
                earn_ntm_growth_est        DOUBLE,
                current_pfcf               DOUBLE,
                pfcf_lt_median             DOUBLE,
                pfcf_p25                   DOUBLE,
                pfcf_p75                   DOUBLE,
                pfcf_rolling_5yr_median    DOUBLE,
                current_fcf_yield          DOUBLE,
                forward_pfcf               DOUBLE,
                fcf_margin_5yr_median      DOUBLE,
                fcf_growth_1yr             DOUBLE,
                fcf_cagr_3yr               DOUBLE,
                fcf_cagr_5yr               DOUBLE,
                current_evebitda           DOUBLE,
                evebitda_lt_median         DOUBLE,
                evebitda_p25               DOUBLE,
                evebitda_p75               DOUBLE,
                evebitda_rolling_5yr_median DOUBLE,
                ebitda_margin_5yr_median   DOUBLE,
                forward_evebitda           DOUBLE,
                current_ps                 DOUBLE,
                ps_lt_median               DOUBLE,
                ps_p25                     DOUBLE,
                ps_p75                     DOUBLE,
                ps_rolling_5yr_median      DOUBLE,
                forward_ps                 DOUBLE,
                current_roa                DOUBLE,
                roa_lt_median              DOUBLE,
                roa_p25                    DOUBLE,
                roa_p75                    DOUBLE,
                roa_rolling_5yr_median     DOUBLE,
                current_roe                DOUBLE,
                roe_lt_median              DOUBLE,
                roe_p25                    DOUBLE,
                roe_p75                    DOUBLE,
                roe_rolling_5yr_median     DOUBLE,
                current_roic               DOUBLE,
                roic_lt_median             DOUBLE,
                roic_p25                   DOUBLE,
                roic_p75                   DOUBLE,
                roic_rolling_5yr_median    DOUBLE,
                current_pbv                DOUBLE,
                pbv_lt_median              DOUBLE,
                pbv_p25                    DOUBLE,
                pbv_p75                    DOUBLE,
                pbv_rolling_5yr_median     DOUBLE,
                current_ptbv               DOUBLE,
                ptbv_lt_median             DOUBLE,
                ptbv_p25                   DOUBLE,
                ptbv_p75                   DOUBLE,
                ptbv_rolling_5yr_median    DOUBLE
            )
        """)
        # Migration: add/rename columns introduced after initial schema
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS ttm_dividend DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS dividend_yield DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS rev_growth_1yr DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS rev_cagr_3yr DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS rev_cagr_5yr DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS rev_ntm_growth_est DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS market_cap_b DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS earn_growth_1yr DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS earn_cagr_3yr DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS earn_cagr_5yr DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS earn_ntm_growth_est DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_pfcf DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS pfcf_lt_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS pfcf_p25 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS pfcf_p75 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS pfcf_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_fcf_yield DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS forward_pfcf DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS fcf_margin_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS fcf_growth_1yr DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS fcf_cagr_3yr DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS fcf_cagr_5yr DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_evebitda DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS evebitda_lt_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS evebitda_p25 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS evebitda_p75 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS evebitda_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS ebitda_margin_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS forward_evebitda DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_ps DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS ps_lt_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS ps_p25 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS ps_p75 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS ps_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS forward_ps DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_roa DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roa_lt_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roa_p25 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roa_p75 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roa_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_roe DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roe_lt_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roe_p25 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roe_p75 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roe_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_roic DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roic_lt_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roic_p25 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roic_p75 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roic_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_pbv DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS pbv_lt_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS pbv_p25 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS pbv_p75 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS pbv_rolling_5yr_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_ptbv DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS ptbv_lt_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS ptbv_p25 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS ptbv_p75 DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS ptbv_rolling_5yr_median DOUBLE")
        self._rename_column_if_exists("pe_stats", "lt_median",          "pe_lt_median")
        self._rename_column_if_exists("pe_stats", "p10",                "pe_p10")
        self._rename_column_if_exists("pe_stats", "p25",                "pe_p25")
        self._rename_column_if_exists("pe_stats", "p75",                "pe_p75")
        self._rename_column_if_exists("pe_stats", "p90",                "pe_p90")
        self._rename_column_if_exists("pe_stats", "rolling_5yr_median", "pe_rolling_5yr_median")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_price DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_earnings_yield    DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS earnings_yield_3y_avg     DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS earnings_yield_5y_avg     DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS forward_earnings_yield    DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS normalized_pe_5y          DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS fcf_yield_3y_avg          DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS fcf_yield_5y_avg          DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS normalized_pfcf_5y        DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_ebitda_ev_yield   DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS ebitda_ev_yield_3y_avg    DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS ebitda_ev_yield_5y_avg    DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS normalized_evebitda_5y    DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS normalized_ps_5y          DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS goal_pe   DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS goal_pcf  DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS goal_peg  DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS goal_bv   DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS goal_2x   DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS goal_low  DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS goal_high DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_gross_margin       DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS gross_margin_5y_median     DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS gross_margin_slope_5y      DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_operating_margin   DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS operating_margin_5y_median DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS operating_margin_change_3y DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS operating_margin_slope_5y  DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS current_fcf_margin         DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS fcf_margin_5y_median       DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS fcf_margin_change_3y       DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS roa_stability_5y           DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS debt_to_ebitda             DOUBLE")
        self.conn.execute("ALTER TABLE pe_stats ADD COLUMN IF NOT EXISTS interest_coverage          DOUBLE")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS earnings_estimates (
                ticker              VARCHAR   NOT NULL,
                fiscal_date         DATE      NOT NULL,
                horizon             VARCHAR   NOT NULL,
                fetched_at          TIMESTAMP NOT NULL,
                eps_avg             DOUBLE,
                eps_high            DOUBLE,
                eps_low             DOUBLE,
                eps_count           INTEGER,
                eps_avg_7d          DOUBLE,
                eps_avg_30d         DOUBLE,
                eps_avg_60d         DOUBLE,
                eps_avg_90d         DOUBLE,
                eps_rev_up_7d       INTEGER,
                eps_rev_down_7d     INTEGER,
                eps_rev_up_30d      INTEGER,
                eps_rev_down_30d    INTEGER,
                rev_avg             DOUBLE,
                rev_high            DOUBLE,
                rev_low             DOUBLE,
                rev_count           INTEGER,
                PRIMARY KEY (ticker, fiscal_date, horizon, fetched_at)
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sector_stats (
                group_type              VARCHAR NOT NULL,
                group_name              VARCHAR NOT NULL,
                month_end_date          DATE    NOT NULL,
                ticker_count            INTEGER,
                pe_median               DOUBLE,
                pe_p25                  DOUBLE,
                pe_p75                  DOUBLE,
                pfcf_median             DOUBLE,
                pfcf_p25                DOUBLE,
                pfcf_p75                DOUBLE,
                evebitda_median         DOUBLE,
                evebitda_p25            DOUBLE,
                evebitda_p75            DOUBLE,
                ps_median               DOUBLE,
                ps_p25                  DOUBLE,
                ps_p75                  DOUBLE,
                pbv_median              DOUBLE,
                earnings_yield_median   DOUBLE,
                fcf_yield_median        DOUBLE,
                ebitda_ev_yield_median  DOUBLE,
                dividend_yield_median   DOUBLE,
                roa_median              DOUBLE,
                roa_p25                 DOUBLE,
                roa_p75                 DOUBLE,
                roe_median              DOUBLE,
                roe_p25                 DOUBLE,
                roe_p75                 DOUBLE,
                roic_median             DOUBLE,
                roic_p25                DOUBLE,
                roic_p75                DOUBLE,
                rev_growth_1yr_median   DOUBLE,
                earn_growth_1yr_median  DOUBLE,
                PRIMARY KEY (group_type, group_name, month_end_date)
            )
        """)

    # ── Upsert ───────────────────────────────────────────────────────────────

    def upsert_monthly_pe(self, ticker: str, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        now = datetime.now(UTC)
        data = df.copy()
        data.insert(0, "ticker", ticker)
        data["updated_at"] = now
        cols = [
            "ticker", "month_end_date", "price", "ttm_eps", "pe_ratio",
            "pe_rolling_5yr_median", "ttm_source", "shares", "ttm_dividend",
            "dividend_yield", "ttm_revenue",
            "ttm_fcf", "pfcf_ratio", "pfcf_rolling_5yr_median", "fcf_yield",
            "ttm_ebitda", "ev_ebitda", "ev_ebitda_rolling_5yr_median",
            "ps_ratio", "ps_rolling_5yr_median",
            "roa", "roa_rolling_5yr_median",
            "roe", "roe_rolling_5yr_median",
            "roic", "roic_rolling_5yr_median",
            "pbv", "pbv_rolling_5yr_median",
            "ptbv", "ptbv_rolling_5yr_median",
            "goal_pe", "goal_pcf", "goal_peg", "goal_bv", "goal_2x", "goal_low", "goal_high",
            "earnings_yield", "earnings_yield_3y_avg", "earnings_yield_5y_avg", "normalized_pe_5y",
            "fcf_yield_3y_avg", "fcf_yield_5y_avg", "normalized_pfcf_5y",
            "ebitda_ev_yield", "ebitda_ev_yield_3y_avg", "ebitda_ev_yield_5y_avg", "normalized_evebitda_5y",
            "normalized_ps_5y",
            "ttm_gross_margin", "gross_margin_5y_median", "gross_margin_slope_5y",
            "ttm_operating_margin", "operating_margin_5y_median",
            "operating_margin_change_3y", "operating_margin_slope_5y",
            "ttm_fcf_margin", "fcf_margin_5y_median", "fcf_margin_change_3y",
            "roa_stability_5y", "debt_to_ebitda", "interest_coverage",
            "earnings_yield_norm", "fcf_yield_norm", "ev_ebitda_norm", "ps_ratio_norm",
            "momentum_12_1", "earnings_quality",
            "feature_available_date",
            "updated_at",
        ]
        for col in cols:
            if col not in data.columns:
                data[col] = None
        self.conn.register("_tmp_pe", data[cols])
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO monthly_pe
                (ticker, month_end_date, price, ttm_eps, pe_ratio,
                 pe_rolling_5yr_median, ttm_source, shares, ttm_dividend,
                 dividend_yield, ttm_revenue,
                 ttm_fcf, pfcf_ratio, pfcf_rolling_5yr_median, fcf_yield,
                 ttm_ebitda, ev_ebitda, ev_ebitda_rolling_5yr_median,
                 ps_ratio, ps_rolling_5yr_median,
                 roa, roa_rolling_5yr_median,
                 roe, roe_rolling_5yr_median,
                 roic, roic_rolling_5yr_median,
                 pbv, pbv_rolling_5yr_median,
                 ptbv, ptbv_rolling_5yr_median,
                 goal_pe, goal_pcf, goal_peg, goal_bv, goal_2x, goal_low, goal_high,
                 earnings_yield, earnings_yield_3y_avg, earnings_yield_5y_avg, normalized_pe_5y,
                 fcf_yield_3y_avg, fcf_yield_5y_avg, normalized_pfcf_5y,
                 ebitda_ev_yield, ebitda_ev_yield_3y_avg, ebitda_ev_yield_5y_avg, normalized_evebitda_5y,
                 normalized_ps_5y,
                 ttm_gross_margin, gross_margin_5y_median, gross_margin_slope_5y,
                 ttm_operating_margin, operating_margin_5y_median,
                 operating_margin_change_3y, operating_margin_slope_5y,
                 ttm_fcf_margin, fcf_margin_5y_median, fcf_margin_change_3y,
                 roa_stability_5y, debt_to_ebitda, interest_coverage,
                 earnings_yield_norm, fcf_yield_norm, ev_ebitda_norm, ps_ratio_norm,
                 momentum_12_1, earnings_quality,
                 feature_available_date,
                 updated_at)
                SELECT ticker, month_end_date, price, ttm_eps, pe_ratio,
                       pe_rolling_5yr_median, ttm_source, shares, ttm_dividend,
                       dividend_yield, ttm_revenue,
                       ttm_fcf, pfcf_ratio, pfcf_rolling_5yr_median, fcf_yield,
                       ttm_ebitda, ev_ebitda, ev_ebitda_rolling_5yr_median,
                       ps_ratio, ps_rolling_5yr_median,
                       roa, roa_rolling_5yr_median,
                       roe, roe_rolling_5yr_median,
                       roic, roic_rolling_5yr_median,
                       pbv, pbv_rolling_5yr_median,
                       ptbv, ptbv_rolling_5yr_median,
                       goal_pe, goal_pcf, goal_peg, goal_bv, goal_2x, goal_low, goal_high,
                       earnings_yield, earnings_yield_3y_avg, earnings_yield_5y_avg, normalized_pe_5y,
                       fcf_yield_3y_avg, fcf_yield_5y_avg, normalized_pfcf_5y,
                       ebitda_ev_yield, ebitda_ev_yield_3y_avg, ebitda_ev_yield_5y_avg, normalized_evebitda_5y,
                       normalized_ps_5y,
                       ttm_gross_margin, gross_margin_5y_median, gross_margin_slope_5y,
                       ttm_operating_margin, operating_margin_5y_median,
                       operating_margin_change_3y, operating_margin_slope_5y,
                       ttm_fcf_margin, fcf_margin_5y_median, fcf_margin_change_3y,
                       roa_stability_5y, debt_to_ebitda, interest_coverage,
                       earnings_yield_norm, fcf_yield_norm, ev_ebitda_norm, ps_ratio_norm,
                       momentum_12_1, earnings_quality,
                       feature_available_date,
                       updated_at
                FROM _tmp_pe
            """)
        finally:
            self.conn.execute("DROP VIEW IF EXISTS _tmp_pe")
        return len(data)

    def upsert_pe_stats(self, stats: dict) -> None:
        # ON CONFLICT preserves estimate-derived and externally-set fields when
        # the incoming value is NULL (--skip-estimates runs don't wipe analyst data).
        self.conn.execute("""
            INSERT INTO pe_stats
            (ticker, updated_at, current_price, pe_lt_median, pe_p10, pe_p25, pe_p75, pe_p90,
             months_available, pe_rolling_5yr_median, current_pe, current_ttm_eps,
             forward_pe, forward_12m_eps, ttm_dividend, dividend_yield,
             rev_growth_1yr, rev_cagr_3yr, rev_cagr_5yr, rev_ntm_growth_est,
             market_cap_b,
             earn_growth_1yr, earn_cagr_3yr, earn_cagr_5yr, earn_ntm_growth_est,
             current_pfcf, pfcf_lt_median, pfcf_p25, pfcf_p75,
             pfcf_rolling_5yr_median, current_fcf_yield,
             forward_pfcf, fcf_margin_5yr_median,
             fcf_growth_1yr, fcf_cagr_3yr, fcf_cagr_5yr,
             current_evebitda, evebitda_lt_median, evebitda_p25, evebitda_p75,
             evebitda_rolling_5yr_median, ebitda_margin_5yr_median, forward_evebitda,
             current_ps, ps_lt_median, ps_p25, ps_p75, ps_rolling_5yr_median, forward_ps,
             current_roa, roa_lt_median, roa_p25, roa_p75, roa_rolling_5yr_median,
             current_roe, roe_lt_median, roe_p25, roe_p75, roe_rolling_5yr_median,
             current_roic, roic_lt_median, roic_p25, roic_p75, roic_rolling_5yr_median,
             current_pbv, pbv_lt_median, pbv_p25, pbv_p75, pbv_rolling_5yr_median,
             current_ptbv, ptbv_lt_median, ptbv_p25, ptbv_p75, ptbv_rolling_5yr_median,
             goal_pe, goal_pcf, goal_peg, goal_bv, goal_2x, goal_low, goal_high,
             current_earnings_yield, earnings_yield_3y_avg, earnings_yield_5y_avg,
             forward_earnings_yield, normalized_pe_5y,
             fcf_yield_3y_avg, fcf_yield_5y_avg, normalized_pfcf_5y,
             current_ebitda_ev_yield, ebitda_ev_yield_3y_avg, ebitda_ev_yield_5y_avg,
             normalized_evebitda_5y, normalized_ps_5y,
             current_gross_margin, gross_margin_5y_median, gross_margin_slope_5y,
             current_operating_margin, operating_margin_5y_median,
             operating_margin_change_3y, operating_margin_slope_5y,
             current_fcf_margin, fcf_margin_5y_median, fcf_margin_change_3y,
             roa_stability_5y, debt_to_ebitda, interest_coverage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ticker) DO UPDATE SET
                updated_at                 = excluded.updated_at,
                current_price              = excluded.current_price,
                pe_lt_median               = excluded.pe_lt_median,
                pe_p10                     = excluded.pe_p10,
                pe_p25                     = excluded.pe_p25,
                pe_p75                     = excluded.pe_p75,
                pe_p90                     = excluded.pe_p90,
                months_available           = excluded.months_available,
                pe_rolling_5yr_median      = excluded.pe_rolling_5yr_median,
                current_pe                 = excluded.current_pe,
                current_ttm_eps            = excluded.current_ttm_eps,
                forward_pe                 = COALESCE(excluded.forward_pe, pe_stats.forward_pe),
                forward_12m_eps            = COALESCE(excluded.forward_12m_eps, pe_stats.forward_12m_eps),
                ttm_dividend               = excluded.ttm_dividend,
                dividend_yield             = excluded.dividend_yield,
                rev_growth_1yr             = excluded.rev_growth_1yr,
                rev_cagr_3yr               = excluded.rev_cagr_3yr,
                rev_cagr_5yr               = excluded.rev_cagr_5yr,
                rev_ntm_growth_est         = COALESCE(excluded.rev_ntm_growth_est, pe_stats.rev_ntm_growth_est),
                market_cap_b               = COALESCE(excluded.market_cap_b, pe_stats.market_cap_b),
                earn_growth_1yr            = excluded.earn_growth_1yr,
                earn_cagr_3yr              = excluded.earn_cagr_3yr,
                earn_cagr_5yr              = excluded.earn_cagr_5yr,
                earn_ntm_growth_est        = COALESCE(excluded.earn_ntm_growth_est, pe_stats.earn_ntm_growth_est),
                current_pfcf               = excluded.current_pfcf,
                pfcf_lt_median             = excluded.pfcf_lt_median,
                pfcf_p25                   = excluded.pfcf_p25,
                pfcf_p75                   = excluded.pfcf_p75,
                pfcf_rolling_5yr_median    = excluded.pfcf_rolling_5yr_median,
                current_fcf_yield          = excluded.current_fcf_yield,
                forward_pfcf               = COALESCE(excluded.forward_pfcf, pe_stats.forward_pfcf),
                fcf_margin_5yr_median      = excluded.fcf_margin_5yr_median,
                fcf_growth_1yr             = excluded.fcf_growth_1yr,
                fcf_cagr_3yr               = excluded.fcf_cagr_3yr,
                fcf_cagr_5yr               = excluded.fcf_cagr_5yr,
                current_evebitda           = excluded.current_evebitda,
                evebitda_lt_median         = excluded.evebitda_lt_median,
                evebitda_p25               = excluded.evebitda_p25,
                evebitda_p75               = excluded.evebitda_p75,
                evebitda_rolling_5yr_median = excluded.evebitda_rolling_5yr_median,
                ebitda_margin_5yr_median    = excluded.ebitda_margin_5yr_median,
                forward_evebitda           = COALESCE(excluded.forward_evebitda, pe_stats.forward_evebitda),
                current_ps                 = excluded.current_ps,
                ps_lt_median               = excluded.ps_lt_median,
                ps_p25                     = excluded.ps_p25,
                ps_p75                     = excluded.ps_p75,
                ps_rolling_5yr_median      = excluded.ps_rolling_5yr_median,
                forward_ps                 = COALESCE(excluded.forward_ps, pe_stats.forward_ps),
                current_roa                = excluded.current_roa,
                roa_lt_median              = excluded.roa_lt_median,
                roa_p25                    = excluded.roa_p25,
                roa_p75                    = excluded.roa_p75,
                roa_rolling_5yr_median     = excluded.roa_rolling_5yr_median,
                current_roe                = excluded.current_roe,
                roe_lt_median              = excluded.roe_lt_median,
                roe_p25                    = excluded.roe_p25,
                roe_p75                    = excluded.roe_p75,
                roe_rolling_5yr_median     = excluded.roe_rolling_5yr_median,
                current_roic               = excluded.current_roic,
                roic_lt_median             = excluded.roic_lt_median,
                roic_p25                   = excluded.roic_p25,
                roic_p75                   = excluded.roic_p75,
                roic_rolling_5yr_median    = excluded.roic_rolling_5yr_median,
                current_pbv                = excluded.current_pbv,
                pbv_lt_median              = excluded.pbv_lt_median,
                pbv_p25                    = excluded.pbv_p25,
                pbv_p75                    = excluded.pbv_p75,
                pbv_rolling_5yr_median     = excluded.pbv_rolling_5yr_median,
                current_ptbv               = excluded.current_ptbv,
                ptbv_lt_median             = excluded.ptbv_lt_median,
                ptbv_p25                   = excluded.ptbv_p25,
                ptbv_p75                   = excluded.ptbv_p75,
                ptbv_rolling_5yr_median    = excluded.ptbv_rolling_5yr_median,
                goal_pe                    = excluded.goal_pe,
                goal_pcf                   = excluded.goal_pcf,
                goal_peg                   = excluded.goal_peg,
                goal_bv                    = excluded.goal_bv,
                goal_2x                    = excluded.goal_2x,
                goal_low                   = excluded.goal_low,
                goal_high                  = excluded.goal_high,
                current_earnings_yield     = excluded.current_earnings_yield,
                earnings_yield_3y_avg      = excluded.earnings_yield_3y_avg,
                earnings_yield_5y_avg      = excluded.earnings_yield_5y_avg,
                forward_earnings_yield     = COALESCE(excluded.forward_earnings_yield, pe_stats.forward_earnings_yield),
                normalized_pe_5y           = excluded.normalized_pe_5y,
                fcf_yield_3y_avg           = excluded.fcf_yield_3y_avg,
                fcf_yield_5y_avg           = excluded.fcf_yield_5y_avg,
                normalized_pfcf_5y         = excluded.normalized_pfcf_5y,
                current_ebitda_ev_yield    = excluded.current_ebitda_ev_yield,
                ebitda_ev_yield_3y_avg     = excluded.ebitda_ev_yield_3y_avg,
                ebitda_ev_yield_5y_avg     = excluded.ebitda_ev_yield_5y_avg,
                normalized_evebitda_5y     = excluded.normalized_evebitda_5y,
                normalized_ps_5y           = excluded.normalized_ps_5y,
                current_gross_margin       = excluded.current_gross_margin,
                gross_margin_5y_median     = excluded.gross_margin_5y_median,
                gross_margin_slope_5y      = excluded.gross_margin_slope_5y,
                current_operating_margin   = excluded.current_operating_margin,
                operating_margin_5y_median = excluded.operating_margin_5y_median,
                operating_margin_change_3y = excluded.operating_margin_change_3y,
                operating_margin_slope_5y  = excluded.operating_margin_slope_5y,
                current_fcf_margin         = excluded.current_fcf_margin,
                fcf_margin_5y_median       = excluded.fcf_margin_5y_median,
                fcf_margin_change_3y       = excluded.fcf_margin_change_3y,
                roa_stability_5y           = excluded.roa_stability_5y,
                debt_to_ebitda             = excluded.debt_to_ebitda,
                interest_coverage          = excluded.interest_coverage
        """, [
            stats["ticker"],
            stats.get("updated_at", datetime.now(UTC)),
            stats.get("current_price"),
            stats.get("pe_lt_median"),
            stats.get("pe_p10"),
            stats.get("pe_p25"),
            stats.get("pe_p75"),
            stats.get("pe_p90"),
            stats.get("months_available"),
            stats.get("pe_rolling_5yr_median"),
            stats.get("current_pe"),
            stats.get("current_ttm_eps"),
            stats.get("forward_pe"),
            stats.get("forward_12m_eps"),
            stats.get("ttm_dividend"),
            stats.get("dividend_yield"),
            stats.get("rev_growth_1yr"),
            stats.get("rev_cagr_3yr"),
            stats.get("rev_cagr_5yr"),
            stats.get("rev_ntm_growth_est"),
            stats.get("market_cap_b"),
            stats.get("earn_growth_1yr"),
            stats.get("earn_cagr_3yr"),
            stats.get("earn_cagr_5yr"),
            stats.get("earn_ntm_growth_est"),
            stats.get("current_pfcf"),
            stats.get("pfcf_lt_median"),
            stats.get("pfcf_p25"),
            stats.get("pfcf_p75"),
            stats.get("pfcf_rolling_5yr_median"),
            stats.get("current_fcf_yield"),
            stats.get("forward_pfcf"),
            stats.get("fcf_margin_5yr_median"),
            stats.get("fcf_growth_1yr"),
            stats.get("fcf_cagr_3yr"),
            stats.get("fcf_cagr_5yr"),
            stats.get("current_evebitda"),
            stats.get("evebitda_lt_median"),
            stats.get("evebitda_p25"),
            stats.get("evebitda_p75"),
            stats.get("evebitda_rolling_5yr_median"),
            stats.get("ebitda_margin_5yr_median"),
            stats.get("forward_evebitda"),
            stats.get("current_ps"),
            stats.get("ps_lt_median"),
            stats.get("ps_p25"),
            stats.get("ps_p75"),
            stats.get("ps_rolling_5yr_median"),
            stats.get("forward_ps"),
            stats.get("current_roa"),
            stats.get("roa_lt_median"),
            stats.get("roa_p25"),
            stats.get("roa_p75"),
            stats.get("roa_rolling_5yr_median"),
            stats.get("current_roe"),
            stats.get("roe_lt_median"),
            stats.get("roe_p25"),
            stats.get("roe_p75"),
            stats.get("roe_rolling_5yr_median"),
            stats.get("current_roic"),
            stats.get("roic_lt_median"),
            stats.get("roic_p25"),
            stats.get("roic_p75"),
            stats.get("roic_rolling_5yr_median"),
            stats.get("current_pbv"),
            stats.get("pbv_lt_median"),
            stats.get("pbv_p25"),
            stats.get("pbv_p75"),
            stats.get("pbv_rolling_5yr_median"),
            stats.get("current_ptbv"),
            stats.get("ptbv_lt_median"),
            stats.get("ptbv_p25"),
            stats.get("ptbv_p75"),
            stats.get("ptbv_rolling_5yr_median"),
            stats.get("goal_pe"),
            stats.get("goal_pcf"),
            stats.get("goal_peg"),
            stats.get("goal_bv"),
            stats.get("goal_2x"),
            stats.get("goal_low"),
            stats.get("goal_high"),
            stats.get("current_earnings_yield"),
            stats.get("earnings_yield_3y_avg"),
            stats.get("earnings_yield_5y_avg"),
            stats.get("forward_earnings_yield"),
            stats.get("normalized_pe_5y"),
            stats.get("fcf_yield_3y_avg"),
            stats.get("fcf_yield_5y_avg"),
            stats.get("normalized_pfcf_5y"),
            stats.get("current_ebitda_ev_yield"),
            stats.get("ebitda_ev_yield_3y_avg"),
            stats.get("ebitda_ev_yield_5y_avg"),
            stats.get("normalized_evebitda_5y"),
            stats.get("normalized_ps_5y"),
            stats.get("current_gross_margin"),
            stats.get("gross_margin_5y_median"),
            stats.get("gross_margin_slope_5y"),
            stats.get("current_operating_margin"),
            stats.get("operating_margin_5y_median"),
            stats.get("operating_margin_change_3y"),
            stats.get("operating_margin_slope_5y"),
            stats.get("current_fcf_margin"),
            stats.get("fcf_margin_5y_median"),
            stats.get("fcf_margin_change_3y"),
            stats.get("roa_stability_5y"),
            stats.get("debt_to_ebitda"),
            stats.get("interest_coverage"),
        ])

    def upsert_estimates(self, ticker: str, rows: list[dict]) -> int:
        count = 0
        for row in rows:
            self.conn.execute("""
                INSERT OR REPLACE INTO earnings_estimates
                (ticker, fiscal_date, horizon, fetched_at,
                 eps_avg, eps_high, eps_low, eps_count,
                 eps_avg_7d, eps_avg_30d, eps_avg_60d, eps_avg_90d,
                 eps_rev_up_7d, eps_rev_down_7d, eps_rev_up_30d, eps_rev_down_30d,
                 rev_avg, rev_high, rev_low, rev_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                ticker, row["fiscal_date"], row["horizon"], row["fetched_at"],
                row.get("eps_avg"), row.get("eps_high"), row.get("eps_low"), row.get("eps_count"),
                row.get("eps_avg_7d"), row.get("eps_avg_30d"), row.get("eps_avg_60d"), row.get("eps_avg_90d"),
                row.get("eps_rev_up_7d"), row.get("eps_rev_down_7d"), row.get("eps_rev_up_30d"), row.get("eps_rev_down_30d"),
                row.get("rev_avg"), row.get("rev_high"), row.get("rev_low"), row.get("rev_count"),
            ])
            count += 1
        return count

    def upsert_sector_stats(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        cols = [
            "group_type", "group_name", "month_end_date", "ticker_count",
            "pe_median", "pe_p25", "pe_p75",
            "pfcf_median", "pfcf_p25", "pfcf_p75",
            "evebitda_median", "evebitda_p25", "evebitda_p75",
            "ps_median", "ps_p25", "ps_p75",
            "pbv_median",
            "earnings_yield_median", "fcf_yield_median", "ebitda_ev_yield_median", "dividend_yield_median",
            "roa_median", "roa_p25", "roa_p75",
            "roe_median", "roe_p25", "roe_p75",
            "roic_median", "roic_p25", "roic_p75",
            "rev_growth_1yr_median", "earn_growth_1yr_median",
        ]
        data = df.copy()
        for col in cols:
            if col not in data.columns:
                data[col] = None
        self.conn.register("_tmp_sector", data[cols])
        try:
            col_csv = ", ".join(cols)
            self.conn.execute(f"""
                INSERT OR REPLACE INTO sector_stats ({col_csv})
                SELECT {col_csv} FROM _tmp_sector
            """)
        finally:
            self.conn.execute("DROP VIEW IF EXISTS _tmp_sector")
        return len(df)

    def update_forward_pe(self, ticker: str, forward_pe: float | None, forward_12m_eps: float | None) -> None:
        self.conn.execute("""
            UPDATE pe_stats SET forward_pe = ?, forward_12m_eps = ?, updated_at = ?
            WHERE ticker = ?
        """, [forward_pe, forward_12m_eps, datetime.now(UTC), ticker])

    def update_rev_ntm_growth_est(self, ticker: str, rev_ntm_growth_est: float | None) -> None:
        self.conn.execute("""
            UPDATE pe_stats SET rev_ntm_growth_est = ?, updated_at = ?
            WHERE ticker = ?
        """, [rev_ntm_growth_est, datetime.now(UTC), ticker])

    def update_earn_ntm_growth_est(self, ticker: str, earn_ntm_growth_est: float | None) -> None:
        self.conn.execute("""
            UPDATE pe_stats SET earn_ntm_growth_est = ?, updated_at = ?
            WHERE ticker = ?
        """, [earn_ntm_growth_est, datetime.now(UTC), ticker])

    def update_forward_pfcf(self, ticker: str, forward_pfcf: float | None) -> None:
        self.conn.execute("""
            UPDATE pe_stats SET forward_pfcf = ?, updated_at = ?
            WHERE ticker = ?
        """, [forward_pfcf, datetime.now(UTC), ticker])

    def update_forward_ps(self, ticker: str, forward_ps: float | None) -> None:
        self.conn.execute("""
            UPDATE pe_stats SET forward_ps = ?, updated_at = ?
            WHERE ticker = ?
        """, [forward_ps, datetime.now(UTC), ticker])

    def update_forward_evebitda(self, ticker: str, forward_evebitda: float | None) -> None:
        self.conn.execute("""
            UPDATE pe_stats SET forward_evebitda = ?, updated_at = ?
            WHERE ticker = ?
        """, [forward_evebitda, datetime.now(UTC), ticker])

    def update_market_cap(self, ticker: str, market_cap_b: float | None) -> None:
        self.conn.execute("""
            UPDATE pe_stats SET market_cap_b = ?, updated_at = ?
            WHERE ticker = ?
        """, [market_cap_b, datetime.now(UTC), ticker])

    # ── Query ─────────────────────────────────────────────────────────────────

    def query_pe_timeseries(
        self,
        tickers: list[str],
        start_date=None,
        end_date=None,
    ) -> pd.DataFrame:
        placeholders = ", ".join(["?"] * len(tickers))
        params: list = list(tickers)
        where = f"WHERE ticker IN ({placeholders})"
        if start_date:
            where += " AND month_end_date >= ?"
            params.append(start_date)
        if end_date:
            where += " AND month_end_date <= ?"
            params.append(end_date)
        return self.conn.execute(
            f"SELECT * FROM monthly_pe {where} ORDER BY ticker, month_end_date",
            params,
        ).df()

    def query_pe_stats(self, tickers: list[str] | None = None) -> pd.DataFrame:
        if tickers:
            placeholders = ", ".join(["?"] * len(tickers))
            return self.conn.execute(
                f"SELECT * FROM pe_stats WHERE ticker IN ({placeholders}) ORDER BY ticker",
                tickers,
            ).df()
        return self.conn.execute("SELECT * FROM pe_stats ORDER BY ticker").df()

    def query_estimates(
        self,
        tickers: list[str],
        horizon: str | None = None,
    ) -> pd.DataFrame:
        placeholders = ", ".join(["?"] * len(tickers))
        params: list = list(tickers)
        where = f"WHERE ticker IN ({placeholders})"
        if horizon:
            where += " AND horizon = ?"
            params.append(horizon)
        return self.conn.execute(
            f"SELECT * FROM earnings_estimates {where} ORDER BY ticker, fiscal_date, fetched_at DESC",
            params,
        ).df()

    def query_sector_stats(
        self,
        group_type: str | None = None,
        names: list[str] | None = None,
        start_date=None,
        end_date=None,
        latest_only: bool = False,
    ) -> pd.DataFrame:
        conditions = []
        params: list = []
        if group_type:
            conditions.append("group_type = ?")
            params.append(group_type)
        if names:
            placeholders = ", ".join(["?"] * len(names))
            conditions.append(f"group_name IN ({placeholders})")
            params.extend(names)
        if start_date:
            conditions.append("month_end_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("month_end_date <= ?")
            params.append(end_date)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        qualify = (
            "QUALIFY month_end_date = MAX(month_end_date) OVER (PARTITION BY group_type, group_name)"
            if latest_only else ""
        )
        return self.conn.execute(
            f"SELECT * FROM sector_stats {where} {qualify} ORDER BY group_type, group_name, month_end_date",
            params,
        ).df()

    def list_tickers(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT ticker FROM pe_stats ORDER BY ticker"
        ).fetchall()]

    def close(self) -> None:
        self.conn.close()
        log.debug("Connection closed")
