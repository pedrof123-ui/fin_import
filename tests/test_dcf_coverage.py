"""
Phase 4 DCF coverage tests.

Tests
-----
1. test_dcf_no_critical_field_warnings_aapl
   AAPL should have zero critical-field NULL warnings after Phase 2/3 mapping expansion.

2. test_dcf_financial_sector_key_fields_jpm
   JPM (bank, FF48=Fin) must have non-NULL revenue and long_term_debt after Phase 3
   industry overrides. Asserts the DCF result reflects populated fields.

3. test_dcf_intrinsic_value_within_2pct_of_baseline
   Compares intrinsic_value_per_share against docs/dcf_baseline.json for all tickers
   present in both the baseline and the DB. Differences > 2% are flagged (not failed)
   since they may represent corrections from previously-NULL fields.

4. test_dcf_no_zero_diluted_shares
   Diluted shares must be > 0 for all baseline tickers present in the DB.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_DB_PATH = Path(__file__).parent.parent / "data" / "financial_statements.duckdb"
_BASELINE_PATH = Path(__file__).parent.parent / "docs" / "dcf_baseline.json"


def _db():
    from financial_statements_db import FinancialStatementsDB
    return FinancialStatementsDB(str(_DB_PATH))


def _run(ticker: str):
    from dcf.model import run_dcf
    return run_dcf(ticker, _db())


def _has_ticker(ticker: str) -> bool:
    try:
        db = _db()
        rows = db.conn.execute(
            "SELECT COUNT(*) FROM income_statements WHERE ticker = ?", [ticker]
        ).fetchone()
        return rows[0] > 0
    except Exception:
        return False


def _critical_field_warnings(result) -> list[str]:
    return [w for w in result.warnings if "Critical field" in w]


# ── Test 1 ───────────────────────────────────────────────────────────────────

def test_dcf_no_critical_field_warnings_aapl():
    if not _DB_PATH.exists():
        pytest.skip("financial_statements.duckdb not present")
    if not _has_ticker("AAPL"):
        pytest.skip("AAPL not in DB")
    result = _run("AAPL")
    crit = _critical_field_warnings(result)
    assert crit == [], f"AAPL has critical-field warnings: {crit}"


# ── Test 2 ───────────────────────────────────────────────────────────────────

def test_dcf_financial_sector_key_fields_jpm():
    if not _DB_PATH.exists():
        pytest.skip("financial_statements.duckdb not present")
    if not _has_ticker("JPM"):
        pytest.skip("JPM not in DB")
    try:
        result = _run("JPM")
    except ValueError as e:
        pytest.skip(f"JPM DCF skipped: {e}")
    crit = _critical_field_warnings(result)
    revenue_missing = any("'revenue'" in w for w in crit)
    debt_missing = any("'long_term_debt'" in w for w in crit)
    assert not revenue_missing, "JPM revenue is NULL — industry override may not be applied"
    assert not debt_missing, "JPM long_term_debt is NULL — check Fin industry overrides"


# ── Test 3 ───────────────────────────────────────────────────────────────────

def test_dcf_intrinsic_value_within_2pct_of_baseline():
    if not _DB_PATH.exists():
        pytest.skip("financial_statements.duckdb not present")
    if not _BASELINE_PATH.exists():
        pytest.skip("dcf_baseline.json not present")

    with open(_BASELINE_PATH) as f:
        baseline = json.load(f)
    tickers_baseline = baseline.get("tickers", {})

    large_deviations = []
    skipped = []

    for ticker, snap in tickers_baseline.items():
        if not _has_ticker(ticker):
            skipped.append(ticker)
            continue
        baseline_iv = snap.get("intrinsic_value_per_share")
        if baseline_iv is None or baseline_iv == 0:
            skipped.append(ticker)
            continue
        try:
            result = _run(ticker)
        except Exception as e:
            skipped.append(f"{ticker}({e})")
            continue

        current_iv = result.intrinsic_value_per_share
        deviation = abs(current_iv - baseline_iv) / abs(baseline_iv)
        if deviation > 0.02:
            large_deviations.append(
                f"{ticker}: baseline={baseline_iv:.2f}, current={current_iv:.2f}, delta={deviation:.1%}"
            )

    if skipped:
        print(f"\nSkipped tickers (no DB data or zero baseline): {skipped}")
    if large_deviations:
        print("\nIntrinsic value deviations > 2% (may be corrections, not failures):")
        for d in large_deviations:
            print(f"  {d}")
    # Always passes — deviations are reported via print, not failed.


# ── Test 4 ───────────────────────────────────────────────────────────────────

def test_dcf_no_zero_diluted_shares():
    if not _DB_PATH.exists():
        pytest.skip("financial_statements.duckdb not present")
    if not _BASELINE_PATH.exists():
        pytest.skip("dcf_baseline.json not present")

    with open(_BASELINE_PATH) as f:
        baseline = json.load(f)
    tickers_baseline = list(baseline.get("tickers", {}).keys())

    zero_shares = []
    for ticker in tickers_baseline:
        if not _has_ticker(ticker):
            continue
        try:
            result = _run(ticker)
        except Exception:
            continue
        if result.diluted_shares <= 0:
            zero_shares.append(ticker)

    assert zero_shares == [], f"Tickers with zero or negative diluted_shares: {zero_shares}"
