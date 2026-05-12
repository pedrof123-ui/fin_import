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
        current_pfcf, pfcf_lt_median, pfcf_p25, pfcf_p75, pfcf_rolling_5yr_median,
        current_fcf_yield, forward_pfcf, fcf_margin_5yr_median,
        fcf_growth_1yr, fcf_cagr_3yr, fcf_cagr_5yr,
        current_evebitda, evebitda_lt_median, evebitda_p25, evebitda_p75,
        evebitda_rolling_5yr_median
    query_pe_timeseries:
        ticker, month_end_date, price, ttm_eps, pe_ratio, pe_rolling_5yr_median,
        ttm_source, shares, ttm_dividend, dividend_yield, ttm_revenue,
        ttm_fcf, pfcf_ratio, pfcf_rolling_5yr_median, fcf_yield,
        ttm_ebitda, ev_ebitda, ev_ebitda_rolling_5yr_median, updated_at
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
        self._rename_column_if_exists("monthly_pe", "rolling_5yr_median", "pe_rolling_5yr_median")

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
                forward_evebitda           DOUBLE
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
        self._rename_column_if_exists("pe_stats", "lt_median",          "pe_lt_median")
        self._rename_column_if_exists("pe_stats", "p10",                "pe_p10")
        self._rename_column_if_exists("pe_stats", "p25",                "pe_p25")
        self._rename_column_if_exists("pe_stats", "p75",                "pe_p75")
        self._rename_column_if_exists("pe_stats", "p90",                "pe_p90")
        self._rename_column_if_exists("pe_stats", "rolling_5yr_median", "pe_rolling_5yr_median")

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
                 updated_at)
                SELECT ticker, month_end_date, price, ttm_eps, pe_ratio,
                       pe_rolling_5yr_median, ttm_source, shares, ttm_dividend,
                       dividend_yield, ttm_revenue,
                       ttm_fcf, pfcf_ratio, pfcf_rolling_5yr_median, fcf_yield,
                       ttm_ebitda, ev_ebitda, ev_ebitda_rolling_5yr_median,
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
            (ticker, updated_at, pe_lt_median, pe_p10, pe_p25, pe_p75, pe_p90,
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
             evebitda_rolling_5yr_median, ebitda_margin_5yr_median, forward_evebitda)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ticker) DO UPDATE SET
                updated_at                 = excluded.updated_at,
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
                forward_evebitda           = COALESCE(excluded.forward_evebitda, pe_stats.forward_evebitda)
        """, [
            stats["ticker"],
            stats.get("updated_at", datetime.now(UTC)),
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

    def list_tickers(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT ticker FROM pe_stats ORDER BY ticker"
        ).fetchall()]

    def close(self) -> None:
        self.conn.close()
        log.debug("Connection closed")
