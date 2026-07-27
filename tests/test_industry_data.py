"""
Industry AI Researcher — data-layer unit tests (no LLM, no network).

Covers api/industry_data.py per features/industry_research/PLAN.md Phase 1. The grain-guarantee
tests are the most important in this file (SPEC.md 2.1): this is an INDUSTRY researcher, and must
never silently widen to sector scope anywhere — selection, aggregation, or otherwise.
"""
from __future__ import annotations

from datetime import date, datetime

import duckdb
import pytest

import api.industry_data as ind


# ---------------------------------------------------------------------------
# resolve_members
# ---------------------------------------------------------------------------

def _write_company_overview(db_path, rows):
    """rows: list of (ticker, industry, market_cap) — single fetch_date snapshot."""
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE company_overview (
            ticker VARCHAR, fetch_date DATE, industry VARCHAR, sector VARCHAR, market_cap DOUBLE
        )
    """)
    for ticker, industry, market_cap in rows:
        conn.execute(
            "INSERT INTO company_overview VALUES (?, ?, ?, ?, ?)",
            [ticker, date(2026, 7, 1), industry, "TECHNOLOGY", market_cap],
        )
    conn.close()


def _write_pe_stats(db_path, rows):
    """rows: list of (ticker, market_cap_b) — pass None for a null market_cap_b."""
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE TABLE pe_stats (ticker VARCHAR, market_cap_b DOUBLE)")
    for ticker, mcap_b in rows:
        conn.execute("INSERT INTO pe_stats VALUES (?, ?)", [ticker, mcap_b])
    conn.close()


def test_resolve_members_orders_by_market_cap_and_caps(tmp_path, monkeypatch):
    av_path = tmp_path / "av.duckdb"
    hf_path = tmp_path / "hf.duckdb"
    _write_company_overview(av_path, [
        ("A", "WIDGETS", 10e9), ("B", "WIDGETS", 50e9), ("C", "WIDGETS", 30e9),
        ("D", "WIDGETS", 5e9),
    ])
    _write_pe_stats(hf_path, [("A", None), ("B", None), ("C", None), ("D", None)])
    monkeypatch.setattr(ind, "_AV_FIN_DB", av_path)
    monkeypatch.setattr(ind, "_HIST_FUND_DB", hf_path)

    result = ind.resolve_members("Widgets", cap=2)
    assert result == ["B", "C"]


def test_resolve_members_custom_basket_verbatim_deduped(tmp_path, monkeypatch):
    result = ind.resolve_members(None, ["nvda", "amd", "NVDA", " amd "])
    assert result == ["NVDA", "AMD"]


def test_resolve_members_empty_unknown_industry_returns_empty(tmp_path, monkeypatch):
    av_path = tmp_path / "av.duckdb"
    hf_path = tmp_path / "hf.duckdb"
    _write_company_overview(av_path, [("A", "WIDGETS", 10e9)])
    _write_pe_stats(hf_path, [("A", None)])
    monkeypatch.setattr(ind, "_AV_FIN_DB", av_path)
    monkeypatch.setattr(ind, "_HIST_FUND_DB", hf_path)

    assert ind.resolve_members("Nonexistent Industry") == []
    assert ind.resolve_members(None, None) == []
    assert ind.resolve_members("", None) == []


def test_resolve_members_missing_db_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ind, "_AV_FIN_DB", tmp_path / "does_not_exist.duckdb")
    monkeypatch.setattr(ind, "_HIST_FUND_DB", tmp_path / "also_missing.duckdb")
    assert ind.resolve_members("Widgets") == []


# ---------------------------------------------------------------------------
# Grain guarantee (SPEC.md 2.1) — the tests that matter most in this file
# ---------------------------------------------------------------------------

def test_null_industry_member_excluded_not_sector_substituted(tmp_path, monkeypatch):
    """A company with no industry classification must never appear in industry results — and
    critically, must NOT be silently pulled in via a sector-level fallback (the exact behavior
    research_router._peer_df has for single-name peer comparison, which this feature must not
    copy)."""
    av_path = tmp_path / "av.duckdb"
    hf_path = tmp_path / "hf.duckdb"
    _write_company_overview(av_path, [
        ("A", "WIDGETS", 100e9),   # correctly classified — must appear
        ("B", None, 999e9),       # no industry — must NOT appear despite huge market cap
        ("C", "", 500e9),         # blank industry — must NOT appear
    ])
    _write_pe_stats(hf_path, [("A", None), ("B", None), ("C", None)])
    monkeypatch.setattr(ind, "_AV_FIN_DB", av_path)
    monkeypatch.setattr(ind, "_HIST_FUND_DB", hf_path)

    result = ind.resolve_members("Widgets", cap=8)
    assert result == ["A"]
    assert "B" not in result
    assert "C" not in result


def test_get_industry_aggregates_never_reads_sector_rows(tmp_path, monkeypatch):
    """Even if a 'sector' row exists with the same group_name as an 'industry' row (a
    pathological/adversarial fixture), get_industry_aggregates must return the industry row's
    numbers, never the sector row's."""
    hf_path = tmp_path / "hf.duckdb"
    conn = duckdb.connect(str(hf_path))
    conn.execute("""
        CREATE TABLE sector_stats (
            group_type VARCHAR, group_name VARCHAR, month_end_date DATE, ticker_count INTEGER,
            pe_median DOUBLE, pfcf_median DOUBLE, evebitda_median DOUBLE, ps_median DOUBLE,
            rev_growth_1yr_median DOUBLE, earn_growth_1yr_median DOUBLE,
            gross_margin_median DOUBLE, operating_margin_median DOUBLE, fcf_margin_median DOUBLE,
            roic_median DOUBLE, roe_median DOUBLE, debt_to_ebitda_median DOUBLE
        )
    """)
    # Same group_name, different group_type, deliberately different numbers.
    conn.execute("""
        INSERT INTO sector_stats VALUES
        ('sector', 'SAME NAME', '2026-06-30', 999, 1.0, 1.0, 1.0, 1.0, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 1.0)
    """)
    conn.execute("""
        INSERT INTO sector_stats VALUES
        ('industry', 'SAME NAME', '2026-06-30', 12, 42.0, 42.0, 42.0, 42.0, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 4.2)
    """)
    conn.close()
    monkeypatch.setattr(ind, "_HIST_FUND_DB", hf_path)

    result = ind.get_industry_aggregates("SAME NAME")
    assert "42.0" in result
    assert "999" not in result  # the sector row's ticker_count must never leak through
    assert "12 tickers measured" in result


def test_disjoint_industries_resolve_to_disjoint_members_and_aggregates(tmp_path, monkeypatch):
    """Two industries sharing a sector (mirrors Semiconductors vs Software - Infrastructure,
    both under Technology in the real DB) must resolve to disjoint member sets and distinct
    aggregate figures — a sector-wide blend would merge them."""
    av_path = tmp_path / "av.duckdb"
    hf_path = tmp_path / "hf.duckdb"
    _write_company_overview(av_path, [
        ("SEMI1", "SEMICONDUCTORS", 100e9), ("SEMI2", "SEMICONDUCTORS", 50e9),
        ("SW1", "SOFTWARE - INFRASTRUCTURE", 80e9), ("SW2", "SOFTWARE - INFRASTRUCTURE", 40e9),
    ])
    _write_pe_stats(hf_path, [("SEMI1", None), ("SEMI2", None), ("SW1", None), ("SW2", None)])
    conn = duckdb.connect(str(hf_path))
    conn.execute("""
        CREATE TABLE sector_stats (
            group_type VARCHAR, group_name VARCHAR, month_end_date DATE, ticker_count INTEGER,
            pe_median DOUBLE, pfcf_median DOUBLE, evebitda_median DOUBLE, ps_median DOUBLE,
            rev_growth_1yr_median DOUBLE, earn_growth_1yr_median DOUBLE,
            gross_margin_median DOUBLE, operating_margin_median DOUBLE, fcf_margin_median DOUBLE,
            roic_median DOUBLE, roe_median DOUBLE, debt_to_ebitda_median DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO sector_stats VALUES
        ('industry', 'SEMICONDUCTORS', '2026-06-30', 2, 90.0, 70.0, 55.0, 14.0, 0.15, 0.14, 0.5, 0.06, 0.16, 0.07, 0.04, 0.1)
    """)
    conn.execute("""
        INSERT INTO sector_stats VALUES
        ('industry', 'SOFTWARE - INFRASTRUCTURE', '2026-06-30', 2, 31.0, 16.0, 19.0, 4.0, 0.13, 0.14, 0.65, 0.06, 0.17, 0.09, 0.07, 0.1)
    """)
    conn.close()
    monkeypatch.setattr(ind, "_AV_FIN_DB", av_path)
    monkeypatch.setattr(ind, "_HIST_FUND_DB", hf_path)

    semis = set(ind.resolve_members("Semiconductors"))
    sw = set(ind.resolve_members("Software - Infrastructure"))
    assert semis == {"SEMI1", "SEMI2"}
    assert sw == {"SW1", "SW2"}
    assert semis.isdisjoint(sw)

    semis_agg = ind.get_industry_aggregates("Semiconductors")
    sw_agg = ind.get_industry_aggregates("Software - Infrastructure")
    assert semis_agg != sw_agg
    assert "90.0" in semis_agg
    assert "31.0" in sw_agg


# ---------------------------------------------------------------------------
# scope_key
# ---------------------------------------------------------------------------

def test_scope_key_stable_and_order_independent_for_custom_baskets():
    a = ind.scope_key(None, ["NVDA", "AMD"])
    b = ind.scope_key(None, ["AMD", "NVDA"])
    c = ind.scope_key(None, ["amd", "nvda"])
    assert a == b == c
    assert a.startswith("custom:")


def test_scope_key_distinct_for_distinct_sets():
    a = ind.scope_key(None, ["NVDA", "AMD"])
    b = ind.scope_key(None, ["NVDA", "INTC"])
    assert a != b


def test_scope_key_industry_path_is_uppercased_name():
    assert ind.scope_key("Semiconductors") == "SEMICONDUCTORS"
    assert ind.scope_key("semiconductors") == ind.scope_key("SEMICONDUCTORS")


# ---------------------------------------------------------------------------
# get_member_financials_df / get_member_financials — missing-member degrade
# ---------------------------------------------------------------------------

def test_member_financials_every_requested_ticker_appears_even_if_absent(tmp_path, monkeypatch):
    """A member with zero data in either DB (e.g. TSM's null market_cap_b in pe_stats, or a
    ticker entirely absent from company_overview) must still appear as a row, not be silently
    dropped — a peer table that drops members is misleading, not just incomplete."""
    av_path = tmp_path / "av.duckdb"
    hf_path = tmp_path / "hf.duckdb"
    conn = duckdb.connect(str(av_path))
    conn.execute("""
        CREATE TABLE company_overview (ticker VARCHAR, fetch_date DATE, name VARCHAR, market_cap DOUBLE)
    """)
    conn.execute("INSERT INTO company_overview VALUES ('A', '2026-07-01', 'Alpha Corp', 100e9)")
    conn.close()

    conn = duckdb.connect(str(hf_path))
    conn.execute("""
        CREATE TABLE pe_stats (
            ticker VARCHAR, market_cap_b DOUBLE, current_pe DOUBLE, forward_pe DOUBLE,
            current_pfcf DOUBLE, rev_growth_1yr DOUBLE, earn_growth_1yr DOUBLE,
            current_roic DOUBLE, current_gross_margin DOUBLE
        )
    """)
    conn.execute("INSERT INTO pe_stats VALUES ('A', NULL, 20.0, 18.0, 15.0, 0.1, 0.1, 0.2, 0.5)")
    conn.close()
    monkeypatch.setattr(ind, "_AV_FIN_DB", av_path)
    monkeypatch.setattr(ind, "_HIST_FUND_DB", hf_path)

    df = ind.get_member_financials_df(["A", "ZZZZ_NOT_IN_ANY_DB"])
    assert set(df["ticker"]) == {"A", "ZZZZ_NOT_IN_ANY_DB"}

    text = ind.get_member_financials(["A", "ZZZZ_NOT_IN_ANY_DB"])
    assert "ZZZZ_NOT_IN_ANY_DB" in text
    assert "n/a" in text  # the missing ticker's numeric fields render as n/a, not a crash


def test_member_financials_empty_input_degrades_gracefully():
    assert ind.get_member_financials([]) == "[INFO] No member financials available"
    df = ind.get_member_financials_df([])
    assert df.empty


# ---------------------------------------------------------------------------
# get_industry_beat_miss — dispersion math
# ---------------------------------------------------------------------------

def test_beat_miss_dispersion_math(tmp_path, monkeypatch):
    et_path = tmp_path / "earnings_transcripts.duckdb"
    conn = duckdb.connect(str(et_path))
    conn.execute("""
        CREATE TABLE earnings_surprises (
            symbol VARCHAR, fiscal_date_ending VARCHAR, reported_date VARCHAR,
            reported_eps DOUBLE, estimated_eps DOUBLE, surprise_pct DOUBLE, fetched_at TIMESTAMP
        )
    """)
    now = datetime.utcnow()
    # 3 members, most recent quarter each: two beats (+5%, +20%), one miss (-10%)
    rows = [
        ("A", "2026-06-30", "2026-07-15", 1.05, 1.00, 5.0, now),
        ("B", "2026-06-30", "2026-07-16", 1.20, 1.00, 20.0, now),
        ("C", "2026-06-30", "2026-07-17", 0.90, 1.00, -10.0, now),
    ]
    for r in rows:
        conn.execute("INSERT INTO earnings_surprises VALUES (?, ?, ?, ?, ?, ?, ?)", list(r))
    conn.close()
    monkeypatch.setattr(ind, "_EARNINGS_DB", et_path)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    result = ind.get_industry_beat_miss(["A", "B", "C"])
    assert "2/3 members beat" in result
    assert "median surprise +5.0%" in result  # median of [5, 20, -10] is 5


def test_beat_miss_empty_input():
    assert ind.get_industry_beat_miss([]) == "[INFO] No members to compare"


def test_beat_miss_no_data_member_shown_not_dropped(tmp_path, monkeypatch):
    et_path = tmp_path / "earnings_transcripts.duckdb"
    duckdb.connect(str(et_path)).execute("""
        CREATE TABLE earnings_surprises (
            symbol VARCHAR, fiscal_date_ending VARCHAR, reported_date VARCHAR,
            reported_eps DOUBLE, estimated_eps DOUBLE, surprise_pct DOUBLE, fetched_at TIMESTAMP
        )
    """).close()
    monkeypatch.setattr(ind, "_EARNINGS_DB", et_path)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    result = ind.get_industry_beat_miss(["NODATA"])
    assert "NODATA: no data" in result


# ---------------------------------------------------------------------------
# get_industry_estimates — nullable-Int64 (pd.NA) safety regression
# ---------------------------------------------------------------------------

def test_estimates_handles_null_revision_counts_without_crashing(tmp_path, monkeypatch):
    """Regression test: eps_rev_up_7d/eps_rev_down_7d are INTEGER columns. DuckDB -> pandas
    surfaces nulls in integer columns as pd.NA (nullable Int64), not None or float NaN. A naive
    `is not None` check lets pd.NA through and int(pd.NA) raises TypeError — found live while
    smoke-testing this function against the real DB."""
    hf_path = tmp_path / "hf.duckdb"
    conn = duckdb.connect(str(hf_path))
    conn.execute("""
        CREATE TABLE earnings_estimates (
            ticker VARCHAR, fiscal_date DATE, horizon VARCHAR, fetched_at TIMESTAMP,
            eps_avg DOUBLE, eps_avg_7d DOUBLE, eps_avg_30d DOUBLE,
            eps_rev_up_7d INTEGER, eps_rev_down_7d INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO earnings_estimates VALUES
        ('A', '2026-12-31', 'fiscal quarter', '2026-07-01', 1.0, 1.0, 1.0, NULL, NULL)
    """)
    conn.close()
    monkeypatch.setattr(ind, "_HIST_FUND_DB", hf_path)

    result = ind.get_industry_estimates(["A"])
    assert "0up/0dn" in result


def test_estimates_empty_input():
    assert ind.get_industry_estimates([]) == "[INFO] No members to compare"


def test_estimates_missing_member_shown_not_crashed(tmp_path, monkeypatch):
    hf_path = tmp_path / "hf.duckdb"
    conn = duckdb.connect(str(hf_path))
    conn.execute("""
        CREATE TABLE earnings_estimates (
            ticker VARCHAR, fiscal_date DATE, horizon VARCHAR, fetched_at TIMESTAMP,
            eps_avg DOUBLE, eps_avg_7d DOUBLE, eps_avg_30d DOUBLE,
            eps_rev_up_7d INTEGER, eps_rev_down_7d INTEGER
        )
    """)
    conn.close()
    monkeypatch.setattr(ind, "_HIST_FUND_DB", hf_path)

    result = ind.get_industry_estimates(["NODATA"])
    assert "NODATA: no estimate data" in result


# ---------------------------------------------------------------------------
# list_industries
# ---------------------------------------------------------------------------

def test_list_industries_excludes_null_and_blank(tmp_path, monkeypatch):
    av_path = tmp_path / "av.duckdb"
    _write_company_overview(av_path, [
        ("A", "WIDGETS", 10e9), ("B", "WIDGETS", 20e9), ("C", None, 5e9), ("D", "", 5e9),
        ("E", "GADGETS", 15e9),
    ])
    monkeypatch.setattr(ind, "_AV_FIN_DB", av_path)

    result = ind.list_industries()
    by_name = {r["industry"]: r["member_count"] for r in result}
    assert by_name == {"WIDGETS": 2, "GADGETS": 1}


def test_list_industries_excludes_literal_none_string(tmp_path, monkeypatch):
    """Regression test: BBBY (a known contaminated ticker, see memory
    project_survivorship_bias_result.md) has industry literally set to the string "None" rather
    than a real NULL — found live via Playwright UI testing, where it appeared as a selectable
    one-member "NONE" entry in the industry picker."""
    av_path = tmp_path / "av.duckdb"
    _write_company_overview(av_path, [
        ("A", "WIDGETS", 10e9), ("BBBY", "None", 1e9), ("F", "NONE", 1e9),
    ])
    monkeypatch.setattr(ind, "_AV_FIN_DB", av_path)

    result = ind.list_industries()
    by_name = {r["industry"]: r["member_count"] for r in result}
    assert by_name == {"WIDGETS": 1}
