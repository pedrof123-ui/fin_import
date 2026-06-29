"""
Compare XBRL pipeline output vs Alpha Vantage financial data.

Joins both databases by ticker + approximate period date (within 7 days),
then computes absolute and relative differences for each matched field.

Usage:
    uv run scripts/compare_xbrl_av.py [--tickers NVDA AAPL MSFT] [--period-type Annual]
"""

import argparse
import os
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).parent.parent

AV_DB   = ROOT / "data" / "av_financials.duckdb"
XBRL_DB = ROOT / "data" / "financial_statements.duckdb"

# (av_col, xbrl_col, label)
INCOME_PAIRS = [
    ("total_revenue",               "revenue",               "Revenue"),
    ("gross_profit",                "gross_profit",          "Gross Profit"),
    ("operating_income",            "operating_income",      "Operating Income"),
    ("net_income",                  "net_income",            "Net Income"),
    ("income_before_tax",           "pretax_income",         "Pretax Income"),
    ("income_tax_expense",          "income_tax_expense",    "Tax Expense"),
    ("research_and_development",    "research_development",  "R&D"),
    ("selling_general_and_administrative", "selling_general_admin", "SG&A"),
    ("interest_expense",            "interest_expense",      "Interest Expense"),
    ("depreciation_and_amortization", "depreciation_amortization", "D&A (income)"),
]

BALANCE_PAIRS = [
    ("total_assets",               "total_assets",                      "Total Assets"),
    ("total_shareholder_equity",   "total_equity",                      "Total Equity"),
    ("long_term_debt",             "long_term_debt",                    "LT Debt"),
    ("short_term_debt",            "short_term_debt",                   "ST Debt (excl CPLTD)"),
    ("current_long_term_debt",     "current_portion_long_term_debt",    "CPLTD"),
    ("cash_and_cash_equivalents",  "cash_and_equivalents",              "Cash"),
    ("total_liabilities",          "total_liabilities",                 "Total Liabilities"),
]

CASHFLOW_PAIRS = [
    ("operating_cashflow",                  "net_cash_operating_activities",  "CFO"),
    ("capital_expenditures",               "capital_expenditures",           "CapEx"),
    ("cashflow_from_investment",           "net_cash_investing_activities",  "CFI"),
    ("cashflow_from_financing",            "net_cash_financing_activities",  "CFF"),
    ("depreciation_depletion_and_amortization", "depreciation_amortization", "D&A (CF)"),
    ("stock_based_compensation",           "stock_based_compensation",       "SBC"),
]

STATEMENT_CONFIG = {
    "income":   ("income_statements",    "income_statements",    INCOME_PAIRS),
    "balance":  ("balance_sheets",       "balance_sheets",       BALANCE_PAIRS),
    "cashflow": ("cash_flow_statements", "cash_flow_statements", CASHFLOW_PAIRS),
}


def load_av(conn_av, ticker: str, table: str, period_type: str) -> pd.DataFrame:
    pt = "annual" if period_type == "Annual" else "quarterly"
    df = conn_av.execute(f"""
        SELECT * FROM {table}
        WHERE ticker = ? AND lower(period_type) = ?
        ORDER BY fiscal_date_ending DESC
    """, [ticker, pt]).df()
    df["fiscal_date_ending"] = pd.to_datetime(df["fiscal_date_ending"])
    return df


def load_xbrl(conn_xbrl, ticker: str, table: str, period_type: str) -> pd.DataFrame:
    df = conn_xbrl.execute(f"""
        SELECT * FROM {table}
        WHERE ticker = ? AND period_type = ?
        ORDER BY period_end_date DESC
    """, [ticker, period_type]).df()
    df["period_end_date"] = pd.to_datetime(df["period_end_date"])
    return df


_NON_FINANCIAL = {"ticker", "period_end_date", "fiscal_year", "fiscal_quarter", "period_type",
                  "filing_date", "extraction_date", "fields_extracted", "total_fields",
                  "coverage_pct", "filing_type", "ytd_cashflow"}


def _decumulate_cashflows(df: pd.DataFrame) -> pd.DataFrame:
    """Convert YTD Q2/Q3 cash flows to standalone quarterly values.
    Only processes rows where ytd_cashflow=True (set at extraction time).
    """
    if df.empty or "fiscal_quarter" not in df.columns or "ytd_cashflow" not in df.columns:
        return df
    financial_cols = [c for c in df.columns if c not in _NON_FINANCIAL]
    df = df.sort_values(["fiscal_year", "fiscal_quarter"]).reset_index(drop=True)
    original = df[financial_cols].copy()
    for i, row in df.iterrows():
        if not row.get("ytd_cashflow", False):
            continue
        q = row.get("fiscal_quarter")
        if q not in (2, 3):
            continue
        prev = df[(df["fiscal_year"] == row["fiscal_year"]) & (df["fiscal_quarter"] == q - 1)]
        if prev.empty:
            continue
        prev_idx = prev.index[0]
        for col in financial_cols:
            curr_val = original.at[i, col]
            prev_val = original.at[prev_idx, col]
            if pd.notna(curr_val) and pd.notna(prev_val):
                df.at[i, col] = curr_val - prev_val
    return df


def match_periods(av_df: pd.DataFrame, xbrl_df: pd.DataFrame, tol_days: int = 7) -> pd.DataFrame:
    """Join on nearest date within tol_days using a cross-join filter.

    All AV columns are prefixed av_, all XBRL columns prefixed xbrl_, so
    identically-named fields (e.g. gross_profit) don't collide after the merge.
    The two join keys are kept unprefixed for easy access.
    """
    av = av_df.copy().rename(columns={"fiscal_date_ending": "_av_date"})
    av = av.rename(columns={c: f"av_{c}" for c in av.columns if c != "_av_date"})

    xbrl = xbrl_df.copy().rename(columns={"period_end_date": "_xbrl_date"})
    xbrl = xbrl.rename(columns={c: f"xbrl_{c}" for c in xbrl.columns if c != "_xbrl_date"})

    av["_key"] = 1
    xbrl["_key"] = 1
    merged = av.merge(xbrl, on="_key").drop(columns="_key")
    delta = (merged["_av_date"] - merged["_xbrl_date"]).abs()
    merged = merged[delta <= pd.Timedelta(days=tol_days)].copy()
    merged["date_diff"] = delta[merged.index]
    merged = (
        merged.sort_values("date_diff")
        .drop_duplicates(subset="_av_date", keep="first")
        .sort_values("_av_date", ascending=False)
        .reset_index(drop=True)
    )
    return merged


def compare_statement(
    conn_av, conn_xbrl,
    ticker: str,
    stmt: str,
    period_type: str,
    pairs: list,
) -> pd.DataFrame:
    av_table, xbrl_table, _ = STATEMENT_CONFIG[stmt]
    av_df   = load_av(conn_av,   ticker, av_table,   period_type)
    xbrl_df = load_xbrl(conn_xbrl, ticker, xbrl_table, period_type)

    if av_df.empty or xbrl_df.empty:
        return pd.DataFrame()

    if stmt == "cashflow" and period_type == "Quarterly" and "ytd_cashflow" in xbrl_df.columns:
        xbrl_df = _decumulate_cashflows(xbrl_df).sort_values("period_end_date", ascending=False).reset_index(drop=True)

    matched = match_periods(av_df, xbrl_df)
    if matched.empty:
        return pd.DataFrame()

    records = []
    for av_col, xbrl_col, label in pairs:
        av_key   = f"av_{av_col}"
        xbrl_key = f"xbrl_{xbrl_col}"
        av_vals   = matched[av_key].values   if av_key   in matched.columns else np.full(len(matched), np.nan)
        xbrl_vals = matched[xbrl_key].values if xbrl_key in matched.columns else np.full(len(matched), np.nan)

        diffs     = []
        rel_diffs = []
        for av_v, xbrl_v in zip(av_vals, xbrl_vals):
            if pd.isna(av_v) or pd.isna(xbrl_v):
                continue
            d = xbrl_v - av_v
            diffs.append(d)
            if av_v != 0:
                rel_diffs.append(abs(d) / abs(av_v))

        n_matched  = len(diffs)
        n_periods  = len(matched)
        mean_abs_pct = np.mean(rel_diffs) * 100 if rel_diffs else np.nan
        max_abs_pct  = np.max(rel_diffs)  * 100 if rel_diffs else np.nan
        exact        = sum(1 for r in rel_diffs if r < 0.001)

        records.append({
            "Field":          label,
            "Periods":        n_periods,
            "Matched":        n_matched,
            "Exact (< 0.1%)": exact,
            "Mean |Δ%|":      round(mean_abs_pct, 2) if not np.isnan(mean_abs_pct) else None,
            "Max |Δ%|":       round(max_abs_pct,  2) if not np.isnan(max_abs_pct)  else None,
        })

    return pd.DataFrame(records)


def run(tickers: list, period_type: str, xbrl_db: str = None, av_db: str = None):
    conn_av   = duckdb.connect(av_db   or str(AV_DB),   read_only=True)
    conn_xbrl = duckdb.connect(xbrl_db or str(XBRL_DB), read_only=True)

    try:
        for ticker in tickers:
            print(f"\n{'='*70}")
            print(f"  {ticker}  |  {period_type}")
            print(f"{'='*70}")

            for stmt, (_, _, pairs) in STATEMENT_CONFIG.items():
                df = compare_statement(conn_av, conn_xbrl, ticker, stmt, period_type, pairs)
                if df.empty:
                    print(f"\n  [{stmt}] No matched periods found.")
                    continue
                print(f"\n  {stmt.upper()}")
                print(df.to_string(index=False))
    finally:
        conn_av.close()
        conn_xbrl.close()


def main():
    parser = argparse.ArgumentParser(description="Compare XBRL vs AV financial data")
    parser.add_argument("--tickers",     nargs="+", default=["NVDA", "AAPL", "MSFT"])
    parser.add_argument("--period-type", choices=["Annual", "Quarterly"], default="Annual")
    parser.add_argument("--xbrl-db",     default=str(XBRL_DB), help="Path to XBRL DuckDB (default: data/financial_statements.duckdb)")
    parser.add_argument("--av-db",       default=str(AV_DB),   help="Path to AV DuckDB (default: data/av_financials.duckdb)")
    args = parser.parse_args()
    run(args.tickers, args.period_type, xbrl_db=args.xbrl_db, av_db=args.av_db)


if __name__ == "__main__":
    main()
