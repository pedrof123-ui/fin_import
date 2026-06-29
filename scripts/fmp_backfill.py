"""
Backfill av_financials.duckdb with pre-existing history from fmp_financials.duckdb.

Only inserts FMP rows whose fiscal_date_ending falls at least BOUNDARY_DAYS before
the earliest date already stored in AV for that ticker+period_type combination.
Existing AV rows are never modified or deleted.

Adds a data_source column ('av' for existing rows, 'fmp' for backfilled rows).

Usage:
    uv run scripts/fmp_backfill.py [--dry-run]
"""

import argparse
import logging
from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
AV_DB = ROOT / "data" / "av_financials.duckdb"
FMP_DB = Path("/home/pedro/projects/trade_systems/data/fmp_financials.duckdb")

BOUNDARY_DAYS = 45  # buffer to avoid duplicating a boundary-year period

# ── Column mappings: FMP name → AV name ──────────────────────────────────────

_IS_MAP = {
    "revenue":                                    "total_revenue",
    "research_and_development_expenses":          "research_and_development",
    "selling_general_and_administrative_expenses":"selling_general_and_administrative",
    "net_income_from_continuing_operations":      "net_income_from_continuing_ops",
    "non_operating_income_excluding_interest":    "other_non_operating_income",
    # direct matches (same name in both)
    "gross_profit":               "gross_profit",
    "cost_of_revenue":            "cost_of_revenue",
    "operating_income":           "operating_income",
    "operating_expenses":         "operating_expenses",
    "interest_income":            "interest_income",
    "interest_expense":           "interest_expense",
    "net_interest_income":        "net_interest_income",
    "depreciation_and_amortization": "depreciation_and_amortization",
    "income_before_tax":          "income_before_tax",
    "income_tax_expense":         "income_tax_expense",
    "ebit":                       "ebit",
    "ebitda":                     "ebitda",
    "net_income":                 "net_income",
}

_BS_MAP = {
    "total_stockholders_equity":   "total_shareholder_equity",
    "property_plant_equipment_net":"property_plant_equipment",
    "account_payables":            "current_accounts_payable",
    "net_receivables":             "current_net_receivables",
    "total_debt":                  "short_long_term_debt_total",
    # direct matches
    "total_assets":                "total_assets",
    "total_current_assets":        "total_current_assets",
    "cash_and_cash_equivalents":   "cash_and_cash_equivalents",
    "cash_and_short_term_investments": "cash_and_short_term_investments",
    "inventory":                   "inventory",
    "total_non_current_assets":    "total_non_current_assets",
    "intangible_assets":           "intangible_assets",
    "goodwill":                    "goodwill",
    "long_term_investments":       "long_term_investments",
    "short_term_investments":      "short_term_investments",
    "other_current_assets":        "other_current_assets",
    "other_non_current_assets":    "other_non_current_assets",
    "total_liabilities":           "total_liabilities",
    "total_current_liabilities":   "total_current_liabilities",
    "deferred_revenue":            "deferred_revenue",
    "short_term_debt":             "short_term_debt",
    "long_term_debt":              "long_term_debt",
    "total_non_current_liabilities":"total_non_current_liabilities",
    "capital_lease_obligations":   "capital_lease_obligations",
    "other_current_liabilities":   "other_current_liabilities",
    "other_non_current_liabilities":"other_non_current_liabilities",
    "treasury_stock":              "treasury_stock",
    "retained_earnings":           "retained_earnings",
    "common_stock":                "common_stock",
}

_CF_MAP = {
    "operating_cash_flow":                      "operating_cashflow",
    "net_cash_provided_by_operating_activities":"operating_cashflow",  # FMP has both; use net_cash_ preferentially below
    "capital_expenditure":                      "capital_expenditures",
    "depreciation_and_amortization":            "depreciation_depletion_and_amortization",
    "net_cash_provided_by_investing_activities":"cashflow_from_investment",
    "net_cash_provided_by_financing_activities":"cashflow_from_financing",
    "net_dividends_paid":                       "dividend_payout",
    "common_dividends_paid":                    "dividend_payout_common_stock",
    "preferred_dividends_paid":                 "dividend_payout_preferred_stock",
    "common_stock_issuance":                    "proceeds_from_issuance_common_stock",
    "common_stock_repurchased":                 "payments_for_repurchase_common_stock",
    "net_preferred_stock_issuance":             "proceeds_from_issuance_preferred_stock",
    "long_term_net_debt_issuance":              "proceeds_from_issuance_long_term_debt",
    "short_term_net_debt_issuance":             "proceeds_from_repayments_short_term_debt",
    "effect_of_forex_changes_on_cash":          "change_in_exchange_rate",
    "net_change_in_cash":                       "change_in_cash_and_cash_equivalents",
    "accounts_receivables":                     "change_in_receivables",
    "inventory":                                "change_in_inventory",
    "stock_based_compensation":                 "stock_based_compensation",
    "net_income":                               "net_income",
}

# AV tables and their FMP→AV column maps
_TABLES = [
    ("income_statements",    _IS_MAP),
    ("balance_sheets",       _BS_MAP),
    ("cash_flow_statements", _CF_MAP),
]


def _add_data_source_column(av: duckdb.DuckDBPyConnection) -> None:
    for table, _ in _TABLES:
        existing = {
            r[0] for r in av.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                [table]
            ).fetchall()
        }
        if "data_source" not in existing:
            av.execute(f"ALTER TABLE {table} ADD COLUMN data_source VARCHAR")
            av.execute(f"UPDATE {table} SET data_source = 'av' WHERE data_source IS NULL")
            log.info("added data_source column to %s", table)


def _earliest_av_dates(av: duckdb.DuckDBPyConnection, table: str) -> pd.DataFrame:
    return av.execute(f"""
        SELECT ticker, period_type, MIN(fiscal_date_ending) AS av_earliest
        FROM {table}
        GROUP BY ticker, period_type
    """).df()


def _build_backfill(
    fmp: duckdb.DuckDBPyConnection,
    table: str,
    col_map: dict[str, str],
    av_earliest: pd.DataFrame,
    dry_run: bool,
) -> pd.DataFrame:
    fmp_df = fmp.execute(f"SELECT * FROM {table}").df()

    merged = fmp_df.merge(av_earliest, on=["ticker", "period_type"], how="inner")
    cutoff = merged["av_earliest"] - timedelta(days=BOUNDARY_DAYS)
    backfill_src = merged[merged["fiscal_date_ending"] < cutoff].copy()

    if backfill_src.empty:
        return pd.DataFrame()

    # Build target DataFrame with AV column names
    out = pd.DataFrame()
    out["ticker"] = backfill_src["ticker"]
    out["fiscal_date_ending"] = backfill_src["fiscal_date_ending"]
    out["period_type"] = backfill_src["period_type"]
    out["reported_currency"] = backfill_src.get("reported_currency", pd.Series(dtype=str))
    out["fetched_at"] = backfill_src.get("fetched_at", pd.Series(dtype="datetime64[ns]"))
    out["data_source"] = "fmp"

    # For CF table, prefer net_cash_provided_by_operating_activities over operating_cash_flow
    # to avoid double-mapping; process net_cash_ first so it wins
    if table == "cash_flow_statements":
        priority_first = ["net_cash_provided_by_operating_activities"]
        remaining = [k for k in col_map if k not in priority_first]
        ordered_map = {k: col_map[k] for k in priority_first + remaining}
    else:
        ordered_map = col_map

    mapped_av_cols: set[str] = set()
    for fmp_col, av_col in ordered_map.items():
        if av_col in mapped_av_cols:
            continue  # already written by a higher-priority FMP column
        if fmp_col in backfill_src.columns:
            out[av_col] = backfill_src[fmp_col].values
            mapped_av_cols.add(av_col)

    return out


def _insert_backfill(
    av: duckdb.DuckDBPyConnection,
    table: str,
    df: pd.DataFrame,
    dry_run: bool,
) -> int:
    if df.empty:
        return 0
    if dry_run:
        log.info("  DRY RUN: would insert %d rows into %s", len(df), table)
        return len(df)

    # Register df and insert only columns that exist in the AV table
    av_cols = {
        r[0] for r in av.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [table]
        ).fetchall()
    }
    df_cols = [c for c in df.columns if c in av_cols]
    df_insert = df[df_cols].copy()

    av.register("_backfill_tmp", df_insert)
    col_csv = ", ".join(df_cols)
    av.execute(f"INSERT OR IGNORE INTO {table} ({col_csv}) SELECT {col_csv} FROM _backfill_tmp")
    av.unregister("_backfill_tmp")
    return len(df_insert)


def run(dry_run: bool = False) -> None:
    av = duckdb.connect(str(AV_DB), read_only=dry_run)
    fmp = duckdb.connect(str(FMP_DB), read_only=True)

    try:
        if not dry_run:
            _add_data_source_column(av)

        total_inserted = 0
        for table, col_map in _TABLES:
            log.info("processing %s ...", table)
            av_earliest = _earliest_av_dates(av, table)
            df = _build_backfill(fmp, table, col_map, av_earliest, dry_run)
            n = _insert_backfill(av, table, df, dry_run)
            annual = len(df[df["period_type"] == "annual"]) if not df.empty else 0
            quarterly = len(df[df["period_type"] == "quarterly"]) if not df.empty else 0
            log.info(
                "  %s: %d rows (%d annual, %d quarterly) from %d tickers",
                table, n, annual, quarterly,
                df["ticker"].nunique() if not df.empty else 0,
            )
            total_inserted += n

        log.info("done — %d total rows %s", total_inserted, "would be inserted" if dry_run else "inserted")
    finally:
        av.close()
        fmp.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill av_financials from fmp_financials")
    parser.add_argument("--dry-run", action="store_true", help="report counts without writing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
