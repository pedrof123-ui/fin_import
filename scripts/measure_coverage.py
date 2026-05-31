"""
Phase 0 baseline measurement (PLAN.md — edgartools gaap_mappings integration).

Produces up to three JSON files in docs/:
  coverage_baseline.json  — per-ticker, per-statement field hit rates
  ai_baseline.json        — AI discovery queue stats
  dcf_baseline.json       — DCF intrinsic value snapshot

DCF baseline requires the API server to be stopped (financial_statements.duckdb
must not be write-locked). Coverage and AI baseline work alongside a running server.

Usage:
    uv run scripts/measure_coverage.py
    uv run scripts/measure_coverage.py --skip-dcf
    uv run scripts/measure_coverage.py --tickers AAPL,MSFT,WMT
    uv run scripts/measure_coverage.py --out-prefix docs/coverage_phase2
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

MAPPING_DB = ROOT / "data" / "xbrl_mappings_multi.duckdb"
STATEMENTS_DB = ROOT / "data" / "financial_statements.duckdb"
DOCS = ROOT / "docs"

# Fields the DCF model depends on — coverage gaps here break intrinsic value output
DCF_CRITICAL = {
    "income": [
        "revenue", "operating_income", "gross_profit", "cost_of_revenue",
        "pretax_income", "income_tax_expense", "diluted_shares", "diluted_eps",
        "interest_expense", "depreciation_amortization",
    ],
    "balance": [
        "long_term_debt", "short_term_debt", "current_portion_long_term_debt",
        "cash_and_equivalents", "accounts_receivable", "accounts_payable", "inventory",
        "total_assets",
    ],
    "cashflow": [
        "depreciation_amortization", "capital_expenditures",
        "net_cash_operating_activities",
    ],
}


def _load_mapping_field_counts() -> dict[str, int]:
    from xbrl_mappings import INCOME_STATEMENT_MAPPING, BALANCE_SHEET_MAPPING, CASH_FLOW_MAPPING
    return {
        "income":   len(INCOME_STATEMENT_MAPPING),
        "balance":  len(BALANCE_SHEET_MAPPING),
        "cashflow": len(CASH_FLOW_MAPPING),
    }


def _load_mapping_dicts() -> dict[str, dict]:
    from xbrl_mappings import INCOME_STATEMENT_MAPPING, BALANCE_SHEET_MAPPING, CASH_FLOW_MAPPING
    return {
        "income":   INCOME_STATEMENT_MAPPING,
        "balance":  BALANCE_SHEET_MAPPING,
        "cashflow": CASH_FLOW_MAPPING,
    }


def measure_coverage(tickers: list[str] | None = None) -> dict:
    """
    Read missed_concepts from xbrl_mappings_multi.duckdb.

    Returns a dict keyed by ticker, with per-statement coverage stats for the
    most recent period of each statement type.
    """
    if not MAPPING_DB.exists():
        print(f"Mapping DB not found: {MAPPING_DB}", file=sys.stderr)
        return {}

    conn = duckdb.connect(str(MAPPING_DB), read_only=True)
    field_counts = _load_mapping_field_counts()
    mapping_dicts = _load_mapping_dicts()

    ticker_filter = ""
    params = []
    if tickers:
        placeholders = ",".join("?" * len(tickers))
        ticker_filter = f"WHERE ticker IN ({placeholders})"
        params = list(tickers)

    # Most recent period per (ticker, statement_type)
    most_recent = conn.execute(f"""
        SELECT ticker, statement_type, max(period_end_date) as latest_period
        FROM missed_concepts
        {ticker_filter}
        GROUP BY ticker, statement_type
    """, params).fetchall()

    # All tickers present in the DB
    all_tickers = sorted(set(r[0] for r in most_recent))
    if not all_tickers:
        print("No tickers found in missed_concepts table.", file=sys.stderr)
        conn.close()
        return {}

    results = {}
    for ticker in all_tickers:
        results[ticker] = {}
        for stmt in ("income", "balance", "cashflow"):
            # Find latest period for this ticker+statement
            period_rows = [r for r in most_recent if r[0] == ticker and r[1] == stmt]
            if not period_rows:
                continue
            latest_period = period_rows[0][2]
            total_fields = field_counts[stmt]

            # Count distinct missed fields at the most recent period
            missed = conn.execute("""
                SELECT count(distinct field_name)
                FROM missed_concepts
                WHERE ticker = ? AND statement_type = ? AND period_end_date = ?
                  AND field_name IS NOT NULL
            """, [ticker, stmt, latest_period]).fetchone()[0]

            found = total_fields - missed
            hit_rate = found / total_fields if total_fields > 0 else 0.0

            # DCF-critical field breakdown
            critical_fields = DCF_CRITICAL.get(stmt, [])
            critical_missed = conn.execute(f"""
                SELECT count(distinct field_name)
                FROM missed_concepts
                WHERE ticker = ? AND statement_type = ? AND period_end_date = ?
                  AND field_name IN ({','.join('?' * len(critical_fields))})
            """, [ticker, stmt, latest_period] + critical_fields).fetchone()[0] if critical_fields else 0

            results[ticker][stmt] = {
                "latest_period":    str(latest_period),
                "total_fields":     total_fields,
                "fields_found":     found,
                "fields_missed":    missed,
                "hit_rate":         round(hit_rate, 4),
                "dcf_critical_total":  len(critical_fields),
                "dcf_critical_missed": critical_missed,
                "dcf_critical_found":  len(critical_fields) - critical_missed,
                "missed_field_names":  _get_missed_field_names(conn, ticker, stmt, latest_period),
            }

    conn.close()
    return results


def _get_missed_field_names(conn, ticker: str, stmt: str, period) -> list[str]:
    rows = conn.execute("""
        SELECT distinct field_name FROM missed_concepts
        WHERE ticker = ? AND statement_type = ? AND period_end_date = ?
          AND field_name IS NOT NULL
        ORDER BY field_name
    """, [ticker, stmt, period]).fetchall()
    return [r[0] for r in rows]


def measure_ai_baseline(tickers: list[str] | None = None) -> dict:
    """Summary of AI discovery queue and missed concepts."""
    if not MAPPING_DB.exists():
        return {}

    conn = duckdb.connect(str(MAPPING_DB), read_only=True)

    ticker_filter = ""
    params = []
    if tickers:
        placeholders = ",".join("?" * len(tickers))
        ticker_filter = f"AND ticker IN ({placeholders})"
        params = list(tickers)

    # AI discovery queue totals
    total_ai = conn.execute(
        f"SELECT count(*) FROM ai_discovery_queue WHERE 1=1 {ticker_filter}", params
    ).fetchone()[0]

    by_stmt = conn.execute(f"""
        SELECT statement_type, count(*) as n, count(distinct ticker) as tickers
        FROM ai_discovery_queue
        WHERE 1=1 {ticker_filter}
        GROUP BY statement_type ORDER BY statement_type
    """, params).fetchall()

    by_field = conn.execute(f"""
        SELECT statement_type, field_name, count(*) as n
        FROM ai_discovery_queue
        WHERE 1=1 {ticker_filter}
        GROUP BY statement_type, field_name
        ORDER BY n DESC LIMIT 20
    """, params).fetchall()

    # Missed concepts totals (permanent misses after all passes)
    total_missed = conn.execute(
        f"SELECT count(distinct ticker || '|' || statement_type || '|' || field_name || '|' || cast(period_end_date as varchar)) FROM missed_concepts WHERE 1=1 {ticker_filter}", params
    ).fetchone()[0]

    top_missed = conn.execute(f"""
        SELECT statement_type, field_name, count(distinct ticker) as tickers,
               count(distinct period_end_date) as periods
        FROM missed_concepts
        WHERE field_name IS NOT NULL {ticker_filter}
        GROUP BY statement_type, field_name
        ORDER BY tickers DESC, periods DESC
        LIMIT 30
    """, params).fetchall()

    conn.close()

    return {
        "generated": datetime.now().isoformat(),
        "ai_discovery_queue": {
            "total_entries": total_ai,
            "by_statement": [
                {"statement": r[0], "entries": r[1], "tickers": r[2]} for r in by_stmt
            ],
            "top_discovered_fields": [
                {"statement": r[0], "field": r[1], "count": r[2]} for r in by_field
            ],
        },
        "permanent_misses": {
            "total_unique_field_period_combinations": total_missed,
            "top_missed_fields": [
                {"statement": r[0], "field": r[1], "distinct_tickers": r[2], "distinct_periods": r[3]}
                for r in top_missed
            ],
        },
    }


def _try_connect_statements_db():
    """Connect to financial_statements.duckdb. Returns (conn, error_msg)."""
    if not STATEMENTS_DB.exists():
        return None, f"DB not found: {STATEMENTS_DB}"
    try:
        conn = duckdb.connect(str(STATEMENTS_DB), read_only=True)
        return conn, None
    except duckdb.IOException as e:
        return None, (
            f"Cannot open {STATEMENTS_DB} — likely locked by the API server (uvicorn).\n"
            "  Stop the server first:  kill $(lsof -t data/financial_statements.duckdb)\n"
            f"  Original error: {e}"
        )


def _dcf_via_api(ticker: str, api_url: str) -> dict:
    """Fetch DCF result from a running API server."""
    import urllib.request
    url = f"{api_url.rstrip('/')}/dcf/{ticker}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        d = json.loads(resp.read())
    return {
        "intrinsic_value_per_share": d.get("intrinsic_value_per_share"),
        "current_price":             d.get("current_price"),
        "upside_pct":                d.get("upside_pct"),
        "wacc":                      round(d.get("wacc_detail", {}).get("wacc", 0), 6),
        "net_debt":                  d.get("net_debt"),
        "diluted_shares":            d.get("diluted_shares"),
        "enterprise_value":          d.get("enterprise_value"),
        "terminal_value":            d.get("terminal_value"),
        "tv_pct_ev":                 round(d.get("tv_pct_enterprise_value", 0), 4),
        "warnings":                  d.get("warnings", []),
    }


def measure_dcf_baseline(tickers: list[str] | None = None, api_url: str | None = None) -> dict:
    """
    Snapshot DCF outputs for all available tickers.

    Two modes:
    1. api_url provided (--api flag): calls the running API server's /dcf/{ticker} endpoint.
       Use this when uvicorn is running and the DB is locked.
    2. Direct DB access: connects to financial_statements.duckdb directly.
       Requires the API server to be stopped first.
    """
    results = {}

    if api_url:
        # Discover tickers from the API
        import urllib.request
        try:
            with urllib.request.urlopen(f"{api_url.rstrip('/')}/tickers", timeout=10) as resp:
                available = json.loads(resp.read())
        except Exception as e:
            return {"error": f"Cannot reach API at {api_url}: {e}", "generated": datetime.now().isoformat(), "tickers": {}}
        if tickers:
            available = [t for t in tickers if t in available]
        for ticker in sorted(available):
            print(f"  DCF via API: {ticker} ...", end=" ", flush=True)
            try:
                results[ticker] = _dcf_via_api(ticker, api_url)
                print("ok")
            except Exception as e:
                results[ticker] = {"error": str(e)}
                print(f"error: {e}")
        return {"generated": datetime.now().isoformat(), "source": "api", "api_url": api_url, "tickers": results}

    # Direct DB mode
    conn, err = _try_connect_statements_db()
    if err:
        print(f"\nDCF baseline skipped: {err}\n", file=sys.stderr)
        print("Tip: use --api http://localhost:8000 to fetch DCF data from the running server.", file=sys.stderr)
        return {"error": err, "generated": datetime.now().isoformat(), "tickers": {}}

    available = [r[0] for r in conn.execute(
        "SELECT DISTINCT ticker FROM income_statements ORDER BY ticker"
    ).fetchall()]
    conn.close()

    if tickers:
        available = [t for t in tickers if t in available]
    if not available:
        return {"error": "No tickers in financial_statements.duckdb", "tickers": {}}

    from financial_statements_db import FinancialStatementsDB
    from dcf.model import run_dcf

    db = FinancialStatementsDB(str(STATEMENTS_DB))
    for ticker in available:
        print(f"  DCF: {ticker} ...", end=" ", flush=True)
        try:
            r = run_dcf(ticker, db)
            results[ticker] = {
                "intrinsic_value_per_share": r.intrinsic_value_per_share,
                "current_price":             r.current_price,
                "upside_pct":                r.upside_pct,
                "wacc":                      round(r.wacc_detail.wacc, 6),
                "net_debt":                  r.net_debt,
                "diluted_shares":            r.diluted_shares,
                "enterprise_value":          r.enterprise_value,
                "terminal_value":            r.terminal_value,
                "tv_pct_ev":                 round(r.tv_pct_enterprise_value, 4),
                "warnings":                  r.warnings,
            }
            print("ok")
        except Exception as e:
            results[ticker] = {"error": str(e)}
            print(f"error: {e}")

    db.close()
    return {"generated": datetime.now().isoformat(), "source": "direct_db", "tickers": results}


def _print_coverage_summary(coverage: dict) -> None:
    print(f"\n{'='*72}")
    print(f"{'COVERAGE SUMMARY':^72}")
    print(f"{'='*72}")
    print(f"{'Ticker':<10} {'Statement':<12} {'Found':>6} {'Total':>6} {'Hit%':>6}  {'DCF crit':>8}  {'Period'}")
    print(f"{'-'*72}")
    for ticker, stmts in sorted(coverage.items()):
        for stmt, stats in sorted(stmts.items()):
            dcf_ok = stats["dcf_critical_found"]
            dcf_tot = stats["dcf_critical_total"]
            dcf_flag = "  " if dcf_ok == dcf_tot else " !"
            print(
                f"{ticker:<10} {stmt:<12} {stats['fields_found']:>6} {stats['total_fields']:>6} "
                f"{stats['hit_rate']*100:>5.1f}%  {dcf_ok}/{dcf_tot}{dcf_flag}      {stats['latest_period']}"
            )
    print()
    # DCF-critical misses
    critical_misses = []
    for ticker, stmts in coverage.items():
        for stmt, stats in stmts.items():
            if stats["dcf_critical_missed"] > 0:
                for f in stats["missed_field_names"]:
                    if f in DCF_CRITICAL.get(stmt, []):
                        critical_misses.append((ticker, stmt, f))
    if critical_misses:
        print("DCF-critical fields with misses (!):")
        for ticker, stmt, field in sorted(critical_misses):
            print(f"  {ticker:<10} {stmt:<12} {field}")
    else:
        print("All DCF-critical fields found for all tickers.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 0 baseline measurement")
    parser.add_argument("--tickers", help="Comma-separated tickers (default: all in DB)")
    parser.add_argument("--skip-dcf", action="store_true", help="Skip DCF baseline entirely")
    parser.add_argument("--api", default="http://localhost:8000",
                        help="API base URL for DCF (default: http://localhost:8000). "
                             "Used when the DB is locked by uvicorn. Pass --skip-dcf to skip entirely.")
    parser.add_argument("--out-prefix", default=str(DOCS / "coverage_baseline"),
                        help="Output file prefix (default: docs/coverage_baseline)")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None

    DOCS.mkdir(exist_ok=True)

    # --- 0.1 Coverage ---
    print("Measuring field coverage from xbrl_mappings_multi.duckdb ...")
    coverage = measure_coverage(tickers)
    if coverage:
        _print_coverage_summary(coverage)
        # Determine output path from prefix
        prefix = args.out_prefix.replace("coverage_baseline", "")
        cov_path = Path(args.out_prefix).with_suffix(".json")
        cov_path.write_text(json.dumps({
            "generated": datetime.now().isoformat(),
            "mapping_db": str(MAPPING_DB),
            "tickers": coverage,
        }, indent=2, default=str))
        print(f"Coverage baseline written to: {cov_path}")
    else:
        print("No coverage data found.")

    # --- 0.3 AI baseline ---
    print("Measuring AI baseline from xbrl_mappings_multi.duckdb ...")
    ai_data = measure_ai_baseline(tickers)
    ai_path = Path(str(args.out_prefix).replace("coverage_baseline", "ai_baseline")).with_suffix(".json")
    ai_path.write_text(json.dumps(ai_data, indent=2, default=str))
    print(f"AI baseline written to: {ai_path}")

    # --- 0.2 DCF baseline ---
    if args.skip_dcf:
        print("\nDCF baseline skipped (--skip-dcf).")
    else:
        print(f"\nAttempting DCF baseline via API ({args.api}) ...")
        dcf_data = measure_dcf_baseline(tickers, api_url=args.api)
        dcf_path = Path(str(args.out_prefix).replace("coverage_baseline", "dcf_baseline")).with_suffix(".json")
        dcf_path.write_text(json.dumps(dcf_data, indent=2, default=str))
        if "error" not in dcf_data:
            n_ok = sum(1 for v in dcf_data["tickers"].values() if "error" not in v)
            print(f"DCF baseline written ({n_ok}/{len(dcf_data['tickers'])} tickers ok): {dcf_path}")
        else:
            print(f"DCF baseline written with error note to: {dcf_path}")


if __name__ == "__main__":
    main()
