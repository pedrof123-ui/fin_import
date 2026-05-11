"""
Historic fundamentals database: data/historic_fundamentals.duckdb

Three tables:
    monthly_pe       Monthly PE timeseries per ticker (~20 years, one row per month)
    pe_stats         Pre-computed statistics snapshot per ticker (median, percentiles, etc.)
    earnings_estimates  Time-series snapshots of analyst EPS/revenue estimates

Usage:
    from historic_fundamentals.db import HistoricFundamentalsDB

    db = HistoricFundamentalsDB()

    # Query PE statistics for one or more tickers
    stats_df = db.query_pe_stats(["AAPL", "MSFT"])

    # Query monthly PE timeseries with optional date range
    ts_df = db.query_pe_timeseries(["AAPL"], start_date=date(2020, 1, 1))

    # Query latest analyst estimates
    est_df = db.query_estimates(["AAPL"], horizon="fiscal quarter")

    # List all tickers with computed stats
    tickers = db.list_tickers()

    db.close()

Typical columns returned:
    query_pe_stats:      ticker, current_pe, pe_lt_median, pe_p10, pe_p25, pe_p75, pe_p90,
                         pe_rolling_5yr_median, forward_pe, forward_12m_eps,
                         current_ttm_eps, months_available, updated_at
    query_pe_timeseries: ticker, month_end_date, price, ttm_eps, pe_ratio,
                         pe_rolling_5yr_median, ttm_source, shares, updated_at
    query_estimates:     ticker, fiscal_date, horizon, eps_avg/high/low/count,
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
                ticker                VARCHAR  NOT NULL,
                month_end_date        DATE     NOT NULL,
                price                 DOUBLE,
                ttm_eps               DOUBLE,
                pe_ratio              DOUBLE,
                pe_rolling_5yr_median DOUBLE,
                ttm_source            VARCHAR,
                shares                DOUBLE,
                ttm_dividend          DOUBLE,
                dividend_yield        DOUBLE,
                ttm_revenue           DOUBLE,
                updated_at            TIMESTAMP,
                PRIMARY KEY (ticker, month_end_date)
            )
        """)
        # Migration: add/rename columns introduced after initial schema
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ttm_dividend DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS dividend_yield DOUBLE")
        self.conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS ttm_revenue DOUBLE")
        self._rename_column_if_exists("monthly_pe", "rolling_5yr_median", "pe_rolling_5yr_median")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pe_stats (
                ticker                VARCHAR  PRIMARY KEY,
                updated_at            TIMESTAMP,
                pe_lt_median          DOUBLE,
                pe_p10                DOUBLE,
                pe_p25                DOUBLE,
                pe_p75                DOUBLE,
                pe_p90                DOUBLE,
                months_available      INTEGER,
                pe_rolling_5yr_median DOUBLE,
                current_pe            DOUBLE,
                current_ttm_eps       DOUBLE,
                forward_pe            DOUBLE,
                forward_12m_eps       DOUBLE,
                ttm_dividend          DOUBLE,
                dividend_yield        DOUBLE,
                rev_growth_1yr        DOUBLE,
                rev_cagr_3yr          DOUBLE,
                rev_cagr_5yr          DOUBLE,
                rev_ntm_growth_est    DOUBLE,
                market_cap_b          DOUBLE
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
        for col in ("price", "ttm_eps", "pe_ratio", "pe_rolling_5yr_median", "ttm_source",
                    "shares", "ttm_dividend", "dividend_yield", "ttm_revenue"):
            if col not in data.columns:
                data[col] = None
        cols = ["ticker", "month_end_date", "price", "ttm_eps", "pe_ratio",
                "pe_rolling_5yr_median", "ttm_source", "shares", "ttm_dividend",
                "dividend_yield", "ttm_revenue", "updated_at"]
        self.conn.register("_tmp_pe", data[cols])
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO monthly_pe
                (ticker, month_end_date, price, ttm_eps, pe_ratio,
                 pe_rolling_5yr_median, ttm_source, shares, ttm_dividend,
                 dividend_yield, ttm_revenue, updated_at)
                SELECT ticker, month_end_date, price, ttm_eps, pe_ratio,
                       pe_rolling_5yr_median, ttm_source, shares, ttm_dividend,
                       dividend_yield, ttm_revenue, updated_at
                FROM _tmp_pe
            """)
        finally:
            self.conn.execute("DROP VIEW IF EXISTS _tmp_pe")
        return len(data)

    def upsert_pe_stats(self, stats: dict) -> None:
        # ON CONFLICT preserves estimate-derived fields when the incoming value is NULL
        # so that --skip-estimates runs don't wipe analyst data.
        self.conn.execute("""
            INSERT INTO pe_stats
            (ticker, updated_at, pe_lt_median, pe_p10, pe_p25, pe_p75, pe_p90,
             months_available, pe_rolling_5yr_median, current_pe, current_ttm_eps,
             forward_pe, forward_12m_eps, ttm_dividend, dividend_yield,
             rev_growth_1yr, rev_cagr_3yr, rev_cagr_5yr, rev_ntm_growth_est,
             market_cap_b)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ticker) DO UPDATE SET
                updated_at            = excluded.updated_at,
                pe_lt_median          = excluded.pe_lt_median,
                pe_p10                = excluded.pe_p10,
                pe_p25                = excluded.pe_p25,
                pe_p75                = excluded.pe_p75,
                pe_p90                = excluded.pe_p90,
                months_available      = excluded.months_available,
                pe_rolling_5yr_median = excluded.pe_rolling_5yr_median,
                current_pe            = excluded.current_pe,
                current_ttm_eps       = excluded.current_ttm_eps,
                forward_pe            = COALESCE(excluded.forward_pe,     pe_stats.forward_pe),
                forward_12m_eps       = COALESCE(excluded.forward_12m_eps, pe_stats.forward_12m_eps),
                ttm_dividend          = excluded.ttm_dividend,
                dividend_yield        = excluded.dividend_yield,
                rev_growth_1yr        = excluded.rev_growth_1yr,
                rev_cagr_3yr          = excluded.rev_cagr_3yr,
                rev_cagr_5yr          = excluded.rev_cagr_5yr,
                rev_ntm_growth_est    = COALESCE(excluded.rev_ntm_growth_est, pe_stats.rev_ntm_growth_est),
                market_cap_b          = COALESCE(excluded.market_cap_b, pe_stats.market_cap_b)
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
