"""Backfill bcd_misp into monthly_pe and compute monthly punder market signal.

Uses earn_growth_1yr from monthly_pe as G(t) and DGS30 from fred.duckdb as R(t).
Rows where ttm_eps <= 0, earn_growth_1yr is NULL, or transversality fails are left NULL.
"""

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

from dcf.data import FRED_DB
from features.bcd.signal import _ERP, _TERMINAL_GROWTH, _MISP_CLIP

HF_DB = Path(__file__).parent.parent / "data" / "historic_fundamentals.duckdb"


def _add_column(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("ALTER TABLE monthly_pe ADD COLUMN IF NOT EXISTS bcd_misp DOUBLE")


def _ensure_market_signals(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_signals (
            month_end_date DATE PRIMARY KEY,
            punder         DOUBLE,
            n_stocks       INTEGER,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def run(dry_run: bool = False) -> None:
    fred_conn = duckdb.connect(str(FRED_DB), read_only=True)
    dgs30_df = fred_conn.execute(
        "SELECT date, value / 100.0 AS dgs30 FROM economic_indicators WHERE series_id = 'DGS30' ORDER BY date"
    ).df()
    fred_conn.close()

    hf_conn = duckdb.connect(str(HF_DB), read_only=dry_run)

    if not dry_run:
        _add_column(hf_conn)

    # Register DGS30 series so we can ASOF JOIN against it
    hf_conn.register("dgs30_series", dgs30_df)

    computed = hf_conn.execute(f"""
        SELECT
            mp.ticker,
            mp.month_end_date,
            CASE
                WHEN mp.ttm_eps > 0
                 AND mp.earn_growth_1yr IS NOT NULL
                 AND mp.price > 0
                 AND d.dgs30 IS NOT NULL
                 AND (d.dgs30 + {_ERP} - {_TERMINAL_GROWTH}) > 0
                 AND mp.ttm_eps * (1.0 + mp.earn_growth_1yr) > 0
                THEN
                    GREATEST(-{_MISP_CLIP}, LEAST({_MISP_CLIP},
                        (mp.price - mp.ttm_eps * (1.0 + mp.earn_growth_1yr)
                            / (d.dgs30 + {_ERP} - {_TERMINAL_GROWTH}))
                        / (mp.ttm_eps * (1.0 + mp.earn_growth_1yr)
                            / (d.dgs30 + {_ERP} - {_TERMINAL_GROWTH}))
                    ))
                ELSE NULL
            END AS bcd_misp
        FROM monthly_pe mp
        ASOF JOIN dgs30_series d ON mp.month_end_date >= d.date
    """).df()

    non_null = computed["bcd_misp"].notna().sum()
    total = len(computed)
    print(f"Computed bcd_misp: {non_null}/{total} rows ({100*non_null/total:.1f}%)")
    print(f"  mean={computed['bcd_misp'].mean():.3f}  "
          f"p25={computed['bcd_misp'].quantile(0.25):.3f}  "
          f"p75={computed['bcd_misp'].quantile(0.75):.3f}")

    if dry_run:
        print("Dry run — no writes.")
        hf_conn.close()
        return

    hf_conn.register("computed", computed)
    hf_conn.execute("""
        UPDATE monthly_pe mp
        SET bcd_misp = c.bcd_misp
        FROM computed c
        WHERE mp.ticker = c.ticker AND mp.month_end_date = c.month_end_date
    """)

    _ensure_market_signals(hf_conn)
    hf_conn.execute("""
        INSERT OR REPLACE INTO market_signals (month_end_date, punder, n_stocks, updated_at)
        SELECT
            month_end_date,
            AVG(CASE WHEN bcd_misp < 0 THEN 1.0 ELSE 0.0 END) AS punder,
            COUNT(*) AS n_stocks,
            CURRENT_TIMESTAMP
        FROM monthly_pe
        WHERE bcd_misp IS NOT NULL
        GROUP BY month_end_date
    """)

    n_signals = hf_conn.execute("SELECT COUNT(*) FROM market_signals").fetchone()[0]
    print(f"market_signals: {n_signals} monthly rows written")

    hf_conn.close()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
