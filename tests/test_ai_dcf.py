"""
Agentic AI DCF Valuator — data-layer unit tests (no LLM, no network).

Covers api/ai_dcf_data.py per features/ai_dcf/PLAN.md Phase 1. Fixture-based tests give exact
control over edge cases (industry-report age boundaries, MD&A status filtering, cached-only
transcript guarantee); the sanitization tests run against real tickers, mirroring the existing
price-blindness convention in tests/test_valuation_data.py.
"""
from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timedelta

import duckdb
import pytest

import api.ai_dcf_data as add
import historic_fundamentals.earnings_transcripts as et
import historic_fundamentals.mda as mda

import api.ai_dcf_router as adr
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# get_industry_report
# ---------------------------------------------------------------------------

def _write_company_overview(db_path, ticker, industry):
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE company_overview (
            ticker VARCHAR, fetch_date DATE, industry VARCHAR, sector VARCHAR
        )
    """)
    conn.execute("INSERT INTO company_overview VALUES (?, ?, ?, ?)",
                 [ticker, date(2026, 7, 1), industry, "TECHNOLOGY"])
    conn.close()


def _write_industry_cache(db_path, rows):
    """rows: list of (scope_key, model, report_markdown, generated_at)."""
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE industry_research_cache (
            scope_key VARCHAR, model VARCHAR, report_markdown VARCHAR, generated_at TIMESTAMP
        )
    """)
    for row in rows:
        conn.execute("INSERT INTO industry_research_cache VALUES (?, ?, ?, ?)", list(row))
    conn.close()


def test_get_industry_report_within_window(tmp_path, monkeypatch):
    av = tmp_path / "av.duckdb"
    irc = tmp_path / "irc.duckdb"
    _write_company_overview(av, "TXN", "SEMICONDUCTORS")
    _write_industry_cache(irc, [
        ("SEMICONDUCTORS", "modelA", "report A text", datetime.now() - timedelta(days=3)),
    ])
    monkeypatch.setattr(add, "_AV_FIN_DB", av)
    monkeypatch.setattr(add, "_INDUSTRY_CACHE_DB", irc)

    result = add.get_industry_report("TXN")
    assert result is not None
    markdown, age_days = result
    assert markdown == "report A text"
    assert age_days == 3


def test_get_industry_report_past_window_returns_none(tmp_path, monkeypatch):
    av = tmp_path / "av.duckdb"
    irc = tmp_path / "irc.duckdb"
    _write_company_overview(av, "TXN", "SEMICONDUCTORS")
    _write_industry_cache(irc, [
        ("SEMICONDUCTORS", "modelA", "stale report", datetime.now() - timedelta(days=15)),
    ])
    monkeypatch.setattr(add, "_AV_FIN_DB", av)
    monkeypatch.setattr(add, "_INDUSTRY_CACHE_DB", irc)

    assert add.get_industry_report("TXN", max_age_days=14) is None


def test_get_industry_report_freshest_across_models(tmp_path, monkeypatch):
    av = tmp_path / "av.duckdb"
    irc = tmp_path / "irc.duckdb"
    _write_company_overview(av, "TXN", "SEMICONDUCTORS")
    _write_industry_cache(irc, [
        ("SEMICONDUCTORS", "old-model", "older report", datetime.now() - timedelta(days=10)),
        ("SEMICONDUCTORS", "new-model", "newer report", datetime.now() - timedelta(days=1)),
    ])
    monkeypatch.setattr(add, "_AV_FIN_DB", av)
    monkeypatch.setattr(add, "_INDUSTRY_CACHE_DB", irc)

    markdown, age_days = add.get_industry_report("TXN")
    assert markdown == "newer report"
    assert age_days == 1


def test_get_industry_report_ignores_custom_scope_keys(tmp_path, monkeypatch):
    av = tmp_path / "av.duckdb"
    irc = tmp_path / "irc.duckdb"
    # A ticker whose industry classification literally collides with a custom-basket key
    # (contrived, but exercises the defensive filter) — should never match.
    _write_company_overview(av, "TXN", "custom:deadbeefdeadbeef")
    _write_industry_cache(irc, [
        ("custom:deadbeefdeadbeef", "modelA", "should never be returned", datetime.now()),
    ])
    monkeypatch.setattr(add, "_AV_FIN_DB", av)
    monkeypatch.setattr(add, "_INDUSTRY_CACHE_DB", irc)

    assert add.get_industry_report("TXN") is None


def test_get_industry_report_missing_industry_classification(tmp_path, monkeypatch):
    av = tmp_path / "av.duckdb"
    irc = tmp_path / "irc.duckdb"
    _write_company_overview(av, "TXN", None)
    _write_industry_cache(irc, [])
    monkeypatch.setattr(add, "_AV_FIN_DB", av)
    monkeypatch.setattr(add, "_INDUSTRY_CACHE_DB", irc)

    assert add.get_industry_report("TXN") is None


def test_get_industry_report_missing_db_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr(add, "_AV_FIN_DB", tmp_path / "nonexistent.duckdb")
    monkeypatch.setattr(add, "_INDUSTRY_CACHE_DB", tmp_path / "nonexistent2.duckdb")
    assert add.get_industry_report("TXN") is None


# ---------------------------------------------------------------------------
# get_mda_history
# ---------------------------------------------------------------------------

def _insert_mda_row(conn, ticker, form, fiscal_period_end, status, text):
    conn.execute("""
        INSERT INTO mda_filings
            (ticker, cik, form, fiscal_period_end, filing_date, accession_no, section_key,
             mda_text, char_count, status, downloaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [ticker, "0001", form, fiscal_period_end, fiscal_period_end, "acc-1", "mda",
          text, len(text or ""), status, datetime.now()])


def test_get_mda_history_filters_empty_status_and_selects_recent(tmp_path, monkeypatch):
    db = tmp_path / "mda.duckdb"
    conn = mda.open_db(db)
    _insert_mda_row(conn, "UPS", "10-K", date(2025, 12, 31), "ok", "FY2025 MD&A text")
    _insert_mda_row(conn, "UPS", "10-K", date(2024, 12, 31), "ok", "FY2024 MD&A text")
    _insert_mda_row(conn, "UPS", "10-K", date(2023, 12, 31), "ok", "FY2023 MD&A text")
    _insert_mda_row(conn, "UPS", "10-K", date(2022, 12, 31), "ok", "FY2022 MD&A text (should be excluded, n_annual=3)")
    _insert_mda_row(conn, "UPS", "10-Q", date(2026, 3, 31), "ok", "Q1 2026 MD&A text")
    _insert_mda_row(conn, "UPS", "10-Q", date(2025, 12, 31), "empty", "")  # should be filtered out
    conn.close()
    monkeypatch.setattr(mda, "DEFAULT_DB_PATH", db)

    result = add.get_mda_history("UPS", n_annual=3)
    assert "FY2025 MD&A text" in result
    assert "FY2024 MD&A text" in result
    assert "FY2023 MD&A text" in result
    assert "FY2022 MD&A text" not in result
    assert "Q1 2026 MD&A text" in result
    assert "[10-K FY2025 MD&A]" in result


def test_get_mda_history_truncates_long_filings(tmp_path, monkeypatch):
    db = tmp_path / "mda.duckdb"
    conn = mda.open_db(db)
    long_text = "X" * (add.MDA_CHAR_CAP + 500)
    _insert_mda_row(conn, "UPS", "10-K", date(2025, 12, 31), "ok", long_text)
    conn.close()
    monkeypatch.setattr(mda, "DEFAULT_DB_PATH", db)

    result = add.get_mda_history("UPS", n_annual=3)
    assert "X" * add.MDA_CHAR_CAP in result
    assert "X" * (add.MDA_CHAR_CAP + 1) not in result
    assert "..." in result


def test_get_mda_history_empty_cache_degrades(tmp_path, monkeypatch):
    db = tmp_path / "mda.duckdb"
    mda.open_db(db).close()
    monkeypatch.setattr(mda, "DEFAULT_DB_PATH", db)

    result = add.get_mda_history("ETSY")
    assert result.startswith("[INFO]")


def test_get_mda_history_all_empty_status_degrades(tmp_path, monkeypatch):
    db = tmp_path / "mda.duckdb"
    conn = mda.open_db(db)
    _insert_mda_row(conn, "CROX", "10-Q", date(2026, 3, 31), "empty", "")
    conn.close()
    monkeypatch.setattr(mda, "DEFAULT_DB_PATH", db)

    result = add.get_mda_history("CROX")
    assert result.startswith("[INFO]")


def test_get_mda_history_missing_db_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr(mda, "DEFAULT_DB_PATH", tmp_path / "nonexistent.duckdb")
    result = add.get_mda_history("UPS")
    assert result.startswith("[INFO]")


# ---------------------------------------------------------------------------
# get_competitor_transcripts — cached-only guarantee
# ---------------------------------------------------------------------------

class _FakePeerDf:
    def __init__(self, tickers):
        self.tickers = tickers

    def __getitem__(self, key):
        assert key == "ticker"
        return self

    def tolist(self):
        return self.tickers


def _mock_peer_df(tickers):
    import pandas as pd
    return pd.DataFrame({"ticker": tickers}), ("TECHNOLOGY", "SEMICONDUCTORS"), None


def test_get_competitor_transcripts_never_calls_av_fetch(tmp_path, monkeypatch):
    db = tmp_path / "earnings.duckdb"
    conn = et.open_db(db)
    conn.close()
    monkeypatch.setattr(et, "DEFAULT_DB_PATH", db)

    import api.research_router as rr
    monkeypatch.setattr(rr, "_peer_df", lambda ticker: _mock_peer_df(["AMD", "NVDA"]))

    def _raise_if_called(*a, **k):
        raise AssertionError("get_competitor_transcripts must never call the AV fetch path")
    monkeypatch.setattr(et, "fetch_from_av", _raise_if_called)

    result = add.get_competitor_transcripts("TXN", max_peers=5)
    assert "no cached transcripts, skipped" in result or result.startswith("[INFO]")


def test_get_competitor_transcripts_peer_ordering_and_skip_note(tmp_path, monkeypatch):
    db = tmp_path / "earnings.duckdb"
    conn = et.open_db(db)
    et.save_transcript(conn, "AMD", "2026Q1", "AMD Q1 transcript text", None)
    conn.close()
    monkeypatch.setattr(et, "DEFAULT_DB_PATH", db)

    import api.research_router as rr
    monkeypatch.setattr(rr, "_peer_df", lambda ticker: _mock_peer_df(["AMD", "NVDA"]))

    result = add.get_competitor_transcripts("TXN", max_peers=5)
    assert "[AMD 2026Q1]" in result
    assert "AMD Q1 transcript text" in result
    assert "[NVDA] — no cached transcripts, skipped" in result


def test_get_competitor_transcripts_respects_max_peers(tmp_path, monkeypatch):
    db = tmp_path / "earnings.duckdb"
    et.open_db(db).close()
    monkeypatch.setattr(et, "DEFAULT_DB_PATH", db)

    import api.research_router as rr
    monkeypatch.setattr(rr, "_peer_df", lambda ticker: _mock_peer_df(["A", "B", "C", "D", "E", "F"]))

    result = add.get_competitor_transcripts("TXN", max_peers=2)
    assert "top 2 peers" in result
    assert "[C]" not in result
    assert "[D]" not in result


def test_get_competitor_transcripts_degrades_on_peer_lookup_failure(monkeypatch):
    import api.research_router as rr
    monkeypatch.setattr(rr, "_peer_df", lambda ticker: (None, None, "[INFO] No sector/industry on file"))

    result = add.get_competitor_transcripts("UNKNOWNTICKER")
    assert result.startswith("[INFO]")


# ---------------------------------------------------------------------------
# get_fundamentals_history / get_engine_context — missing-DB degrade
# ---------------------------------------------------------------------------

def test_get_fundamentals_history_missing_db_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr(add, "_AV_FIN_DB", tmp_path / "nonexistent.duckdb")
    result = add.get_fundamentals_history("TXN")
    assert result.startswith("[ERROR]")


def test_get_engine_context_missing_db_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr(add, "_AV_FIN_DB", tmp_path / "nonexistent.duckdb")
    result = add.get_engine_context("TXN")
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Real-data checks (mirrors tests/test_valuation_data.py's price-blindness convention)
# ---------------------------------------------------------------------------

_REAL_TICKERS = ["TXN", "UPS"]

_BANNED_TERMS = ["current price", "market cap", "analyst target", "goal_low", "goal_high", "upside"]


@pytest.mark.parametrize("ticker", _REAL_TICKERS)
def test_fundamentals_history_price_blind(ticker):
    text = add.get_fundamentals_history(ticker).lower()
    hits = [term for term in _BANNED_TERMS if term in text]
    assert not hits, f"{ticker}: prohibited terms leaked into fundamentals history: {hits}"


@pytest.mark.parametrize("ticker", _REAL_TICKERS)
def test_engine_context_price_blind(ticker):
    text = add.get_engine_context(ticker).lower()
    hits = [term for term in _BANNED_TERMS if term in text]
    assert not hits, f"{ticker}: prohibited terms leaked into engine context: {hits}"


def test_engine_context_reports_cogs_matches_phase0_findings():
    """Regression check for the Phase 0.3 finding: TXN and UPS both report_cogs=True, with
    UPS's historical COGS% high enough to explain the ebit_margin_pct ceiling landmine."""
    txn = add.get_engine_context("TXN")
    ups = add.get_engine_context("UPS")
    assert "Reports COGS explicitly (gross-profit/cost-of-revenue line reported): True" in txn
    assert "Reports COGS explicitly (gross-profit/cost-of-revenue line reported): True" in ups
    assert "ebit_margin_pct target cannot exceed" in ups


# ---------------------------------------------------------------------------
# get_debt_maturity_context — PLAN_DEBT_MATURITY.md Phase 5
# ---------------------------------------------------------------------------

def test_get_debt_maturity_context_no_coverage_renders_info_not_empty(monkeypatch):
    """~90% of the universe has no coverage (docs/debt_maturity_coverage.md Phase 4) --
    that must render a real [INFO] placeholder, not an empty or broken block."""
    import debt_maturity.db as dmdb

    monkeypatch.setattr(dmdb, "get_summary", lambda ticker: None)
    result = add.get_debt_maturity_context("ZZZZ")
    assert result.startswith("[INFO]")
    assert "ZZZZ" in result


def test_get_debt_maturity_context_renders_summary_and_ladder(monkeypatch):
    import debt_maturity.db as dmdb

    summary = {
        "fiscal_year": 2025,
        "weighted_avg_years_to_maturity": 9.8,
        "pct_maturity_dated": 1.0,
        "weighted_avg_coupon_near_term": 0.031,
        "weighted_avg_coupon_long_dated": 0.039,
        "total_debt_covered": 62286.0,
    }
    tranches = [
        {"maturity_year": 2026, "coupon_rate": 0.037, "amount": 5800.0, "raw_label": "3.7% notes"},
        {"maturity_year": 2049, "coupon_rate": 0.043, "amount": 3000.0, "raw_label": "4.3% notes"},
    ]
    monkeypatch.setattr(dmdb, "get_summary", lambda ticker: summary)
    monkeypatch.setattr(dmdb, "get_tranches", lambda ticker: tranches)

    result = add.get_debt_maturity_context("IBM")
    assert "9.8y" in result
    assert "CAUTION" not in result  # pct_maturity_dated == 1.0, fully dated
    assert "3.1%" in result   # near-term coupon
    assert "3.9%" in result   # long-dated coupon
    assert "3.7% notes" in result
    assert "4.3% notes" in result


def test_get_debt_maturity_context_low_pct_dated_shows_caution(monkeypatch):
    """Apple-shaped case: a large undated 'Thereafter' bucket means weighted_avg_years_to_
    maturity rests on less than half the disclosed debt -- must not be stated as a bare fact."""
    import debt_maturity.db as dmdb

    summary = {
        "fiscal_year": 2025,
        "weighted_avg_years_to_maturity": 2.5,
        "pct_maturity_dated": 0.46,
        "weighted_avg_coupon_near_term": None,
        "weighted_avg_coupon_long_dated": 0.025,
        "total_debt_covered": 91281.0,
    }
    monkeypatch.setattr(dmdb, "get_summary", lambda ticker: summary)
    monkeypatch.setattr(dmdb, "get_tranches", lambda ticker: [])

    result = add.get_debt_maturity_context("AAPL")
    assert "CAUTION" in result
    assert "46%" in result


def test_get_debt_maturity_context_caps_tranches_shown(monkeypatch):
    import debt_maturity.db as dmdb

    summary = {
        "fiscal_year": 2025, "weighted_avg_years_to_maturity": 10.0, "pct_maturity_dated": 1.0,
        "weighted_avg_coupon_near_term": 0.03, "weighted_avg_coupon_long_dated": 0.04,
        "total_debt_covered": 1000.0,
    }
    tranches = [
        {"maturity_year": 2026 + i, "coupon_rate": 0.03, "amount": float(100 - i), "raw_label": f"t{i}"}
        for i in range(20)
    ]
    monkeypatch.setattr(dmdb, "get_summary", lambda ticker: summary)
    monkeypatch.setattr(dmdb, "get_tranches", lambda ticker: tranches)

    result = add.get_debt_maturity_context("ACME")
    assert result.count(" coupon ") == add.MAX_DEBT_TRANCHES_SHOWN
    assert "5 smaller tranches omitted" in result


@pytest.mark.parametrize("ticker", _REAL_TICKERS)
def test_debt_maturity_context_price_blind(ticker):
    text = add.get_debt_maturity_context(ticker).lower()
    hits = [term for term in _BANNED_TERMS if term in text]
    assert not hits, f"{ticker}: prohibited terms leaked into debt maturity context: {hits}"


# ---------------------------------------------------------------------------
# Context assembly helpers — pure formatting, no DB access
# ---------------------------------------------------------------------------

def test_build_industry_context_tags_report_age():
    ctx = add.build_industry_context(
        peer_table="peer data", industry_aggregates="agg data", tavily_search="search data",
        industry_report=("some report body", 5), competitor_transcripts="transcript data",
    )
    assert "[Industry report, 5d old]" in ctx
    assert "some report body" in ctx


def test_build_industry_context_no_report_notes_unavailable():
    ctx = add.build_industry_context(
        peer_table="peer data", industry_aggregates="agg data", tavily_search="search data",
        industry_report=None, competitor_transcripts="transcript data",
    )
    assert "No cached industry report" in ctx


def test_build_guidance_context_includes_all_sections():
    ctx = add.build_guidance_context(
        mda_history="mda text", target_transcripts="transcript text",
        beat_miss="beat miss text", consensus_estimates="estimates text",
    )
    for expected in ["mda text", "transcript text", "beat miss text", "estimates text"]:
        assert expected in ctx


# ---------------------------------------------------------------------------
# Phase 2 — schema, guardrails, engine bridge, renderers
# ---------------------------------------------------------------------------

def _scenario(revenue_growth=None, cogs_pct=None, ebit_margin_pct=None, capex_pct_revenue=None,
              terminal_growth_rate=0.025, rationale="test rationale"):
    return adr.ScenarioAssumptions(
        revenue_growth=revenue_growth or [0.10, 0.09, 0.08, 0.07, 0.06],
        cogs_pct=cogs_pct or [0.40, 0.40, 0.40, 0.40, 0.40],
        ebit_margin_pct=ebit_margin_pct or [0.20, 0.20, 0.20, 0.20, 0.20],
        capex_pct_revenue=capex_pct_revenue or [0.05, 0.05, 0.05, 0.05, 0.05],
        terminal_growth_rate=terminal_growth_rate,
        rationale=rationale,
    )


def _assumptions(bear=None, base=None, bull=None, **kw):
    return adr.AiDcfAssumptions(
        bear=bear or _scenario(revenue_growth=[0.03] * 5, ebit_margin_pct=[0.15] * 5),
        base=base or _scenario(),
        bull=bull or _scenario(revenue_growth=[0.15] * 5, ebit_margin_pct=[0.25] * 5),
        wacc_rationale="test WACC rationale",
        key_debates=["debate one", "debate two"],
        **kw,
    )


_NEUTRAL_BOUNDS = {
    "reports_cogs": True, "cogs_pct_median": 0.40, "ebit_margin_max": 0.30, "capex_pct_max": 0.10,
}


def test_scenario_assumptions_rejects_wrong_length_list():
    with pytest.raises(ValidationError):
        _scenario(revenue_growth=[0.1, 0.1, 0.1])  # only 3 values, needs 5


def test_scenario_assumptions_coerces_placeholder_strings():
    """_coerce_optional_float strips symbols but does not divide by 100 — an LLM is expected to
    emit the decimal fraction itself (e.g. "0.10"), matching the convention used everywhere
    else in the codebase (research_router.py's ValuationSummary etc.)."""
    s = adr.ScenarioAssumptions(
        revenue_growth=["0.10", "0.09", "0.08", "0.07", "0.06"],
        cogs_pct=[0.4] * 5, ebit_margin_pct=[0.2] * 5, capex_pct_revenue=[0.05] * 5,
        terminal_growth_rate="0.025", rationale="x",
    )
    assert s.revenue_growth[0] == pytest.approx(0.10)
    assert s.terminal_growth_rate == pytest.approx(0.025)


def test_validate_assumptions_never_mutates_input():
    a = _assumptions()
    result, warnings = adr.validate_assumptions(a, _NEUTRAL_BOUNDS)
    assert result is a
    assert warnings == []  # all values are within range and internally consistent


def test_validate_assumptions_flags_revenue_growth_out_of_range():
    a = _assumptions(bear=_scenario(revenue_growth=[-0.9, 0.03, 0.03, 0.03, 0.03]))
    _, warnings = adr.validate_assumptions(a, _NEUTRAL_BOUNDS)
    assert any("revenue_growth" in w and "bear y1" in w for w in warnings)


def test_validate_assumptions_flags_ebit_margin_out_of_range():
    a = _assumptions(base=_scenario(ebit_margin_pct=[0.99, 0.20, 0.20, 0.20, 0.20]))
    _, warnings = adr.validate_assumptions(a, _NEUTRAL_BOUNDS)
    assert any("ebit_margin_pct" in w and "base y1" in w for w in warnings)


def test_validate_assumptions_flags_margin_above_historical_max():
    a = _assumptions(base=_scenario(ebit_margin_pct=[0.45, 0.20, 0.20, 0.20, 0.20], cogs_pct=[0.30] * 5))
    _, warnings = adr.validate_assumptions(a, _NEUTRAL_BOUNDS)  # hist max 0.30, buffer 0.10 -> ceiling 0.40
    assert any("exceeds historical max" in w for w in warnings)


def test_validate_assumptions_flags_capex_out_of_range():
    a = _assumptions(bull=_scenario(capex_pct_revenue=[0.50, 0.05, 0.05, 0.05, 0.05],
                                     revenue_growth=[0.15] * 5, ebit_margin_pct=[0.25] * 5))
    _, warnings = adr.validate_assumptions(a, _NEUTRAL_BOUNDS)  # ceiling = 0.10 + 0.15 = 0.25
    assert any("capex_pct_revenue" in w and "bull y1" in w for w in warnings)


def test_validate_assumptions_capex_within_utility_like_history_not_flagged():
    """PLAN_GUARDRAILS.md Phase 2 regression proof: the PEG false positive. A utility whose own
    historical capex_pct_max is 0.38 authoring 42% capex must NOT fire — it's within its own
    historical range + buffer (0.38 + 0.15 = 0.53), even though 42% would have breached the old
    flat 35% cap."""
    utility_bounds = {"reports_cogs": True, "cogs_pct_median": 0.60, "ebit_margin_max": 0.30,
                       "capex_pct_max": 0.38}
    a = _assumptions(base=_scenario(capex_pct_revenue=[0.42, 0.40, 0.38, 0.36, 0.35],
                                     revenue_growth=[0.06] * 5, ebit_margin_pct=[0.24] * 5))
    _, warnings = adr.validate_assumptions(a, utility_bounds)
    assert not any("capex_pct_revenue" in w for w in warnings)


def test_validate_assumptions_flags_capex_above_own_historical_max_plus_buffer():
    """Same utility-like ticker, but capex genuinely exceeds even ITS OWN historical range +
    buffer — this must still fire."""
    utility_bounds = {"reports_cogs": True, "cogs_pct_median": 0.60, "ebit_margin_max": 0.30,
                       "capex_pct_max": 0.38}
    a = _assumptions(bull=_scenario(capex_pct_revenue=[0.60, 0.40, 0.38, 0.36, 0.35],
                                     revenue_growth=[0.06] * 5, ebit_margin_pct=[0.24] * 5))
    _, warnings = adr.validate_assumptions(a, utility_bounds)  # ceiling = 0.38 + 0.15 = 0.53
    assert any("capex_pct_revenue" in w and "bull y1" in w and "historical max" in w for w in warnings)


def test_validate_assumptions_capex_falls_back_to_flat_cap_when_no_history():
    """A ticker with insufficient capex history (capex_pct_max=None, e.g. a recent IPO) falls
    back to the flat 35% ceiling rather than going unbounded."""
    no_history_bounds = {"reports_cogs": True, "cogs_pct_median": 0.40, "ebit_margin_max": 0.30,
                          "capex_pct_max": None}
    a = _assumptions(base=_scenario(capex_pct_revenue=[0.40, 0.10, 0.10, 0.10, 0.10],
                                     revenue_growth=[0.15] * 5, ebit_margin_pct=[0.20] * 5))
    _, warnings = adr.validate_assumptions(a, no_history_bounds)
    assert any("capex_pct_revenue" in w and "flat fallback" in w for w in warnings)


def test_validate_assumptions_flags_cogs_drop_without_room(monkeypatch):
    a = _assumptions(base=_scenario(cogs_pct=[0.20, 0.40, 0.40, 0.40, 0.40]))  # 20pp below 0.40 median
    _, warnings = adr.validate_assumptions(a, _NEUTRAL_BOUNDS)
    assert any("below the historical median" in w for w in warnings)


def test_validate_assumptions_ebit_margin_exceeds_cogs_ceiling_ups_like():
    """Regression test for the Phase 0.3 UPS landmine: a scenario that requests an EBIT margin
    beyond (1 - cogs_pct) must be flagged, since the engine will silently floor SG&A/R&D."""
    ups_like_bounds = {"reports_cogs": True, "cogs_pct_median": 0.813, "ebit_margin_max": 0.10}
    a = _assumptions(base=_scenario(cogs_pct=[0.813] * 5, ebit_margin_pct=[0.35] * 5))
    _, warnings = adr.validate_assumptions(a, ups_like_bounds)
    assert any("exceeds (1 - cogs_pct)" in w for w in warnings)


def test_validate_assumptions_skips_cogs_checks_when_not_reports_cogs():
    a = _assumptions(base=_scenario(cogs_pct=[0.0] * 5, ebit_margin_pct=[0.90] * 5))
    bounds = {"reports_cogs": False, "cogs_pct_median": None, "ebit_margin_max": None}
    _, warnings = adr.validate_assumptions(a, bounds)
    # ebit_margin_pct=0.90 is outside [-30%,60%] so THAT still fires, but no cogs-ceiling warning
    assert not any("exceeds (1 - cogs_pct)" in w for w in warnings)


def test_validate_assumptions_flags_terminal_growth_out_of_range():
    a = _assumptions(base=_scenario(terminal_growth_rate=0.08))
    _, warnings = adr.validate_assumptions(a, _NEUTRAL_BOUNDS)
    assert any("terminal_growth_rate" in w and "dropped" in w for w in warnings)


def test_to_overrides_drops_out_of_range_terminal_growth():
    a = _assumptions(base=_scenario(terminal_growth_rate=0.08))
    overrides = adr.to_overrides(a.base, a, reports_cogs=True)
    assert overrides.terminal_growth_rate is None  # dropped, engine falls back to its own default


def test_to_overrides_keeps_in_range_terminal_growth():
    a = _assumptions(base=_scenario(terminal_growth_rate=0.025))
    overrides = adr.to_overrides(a.base, a, reports_cogs=True)
    assert overrides.terminal_growth_rate == pytest.approx(0.025)


def test_to_overrides_omits_cogs_pct_when_not_reports_cogs():
    a = _assumptions()
    overrides = adr.to_overrides(a.base, a, reports_cogs=False)
    assert all(yo.cogs_pct is None for yo in overrides.years.values())


def test_to_overrides_includes_cogs_pct_when_reports_cogs():
    a = _assumptions()
    overrides = adr.to_overrides(a.base, a, reports_cogs=True)
    assert overrides.years[1].cogs_pct == pytest.approx(0.40)


def test_check_scenario_ordering_flags_violation():
    class _Fake:
        def __init__(self, v):
            self.intrinsic_value_per_share = v
    warnings = adr.check_scenario_ordering({"bear": _Fake(100), "base": _Fake(90), "bull": _Fake(80)})
    assert any("bear intrinsic value" in w for w in warnings)
    assert any("base intrinsic value" in w for w in warnings)


def test_check_scenario_ordering_no_violation():
    class _Fake:
        def __init__(self, v):
            self.intrinsic_value_per_share = v
    warnings = adr.check_scenario_ordering({"bear": _Fake(50), "base": _Fake(80), "bull": _Fake(120)})
    assert warnings == []


# ---------------------------------------------------------------------------
# Engine bridge — real run_dcf_av round-trip (TXN, UPS)
# ---------------------------------------------------------------------------

def test_run_ai_dcf_engine_txn_produces_finite_values():
    a = _assumptions()
    results = adr.run_ai_dcf_engine("TXN", a, reports_cogs=True)
    assert results["base"] is not None
    assert math.isfinite(results["base"].intrinsic_value_per_share)
    for i, yf in enumerate(results["base"].year_forecasts[:5]):
        assert yf.revenue_growth == pytest.approx(a.base.revenue_growth[i])
        assert yf.capex_pct_revenue == pytest.approx(a.base.capex_pct_revenue[i])


def test_run_ai_dcf_engine_ups_ebit_margin_ceiling_regression():
    """Reproduces the exact Phase 0.3 finding: cogs_pct=0.55 + ebit_margin_pct=0.30 for UPS
    must achieve 0.30 exactly, NOT silently cap at ~0.187 (the 1-historical-cogs ceiling)."""
    scenario = _scenario(
        revenue_growth=[0.05] * 5, cogs_pct=[0.55] * 5, ebit_margin_pct=[0.30] * 5,
        capex_pct_revenue=[0.04] * 5, terminal_growth_rate=0.03,
    )
    a = _assumptions(base=scenario)
    results = adr.run_ai_dcf_engine("UPS", a, reports_cogs=True)
    base = results["base"]
    assert base is not None
    for yf, fc in zip(base.year_forecasts[:5], base.fcff_series[:5]):
        achieved_margin = fc.ebit / fc.revenue
        assert achieved_margin == pytest.approx(0.30, abs=1e-6)


def test_run_ai_dcf_engine_ups_ebit_margin_without_cogs_override_hits_ceiling():
    """Companion negative case: WITHOUT lowering cogs_pct, ebit_margin_pct=0.30 for UPS is
    silently capped near (1 - historical cogs%) instead — this is the landmine itself, kept as
    a regression guard so a future engine change that "fixes" this doesn't go unnoticed."""
    hist_cogs = add.get_historical_margin_bounds("UPS")["cogs_pct_median"]
    scenario = _scenario(
        revenue_growth=[0.05] * 5, cogs_pct=[hist_cogs] * 5, ebit_margin_pct=[0.30] * 5,
        capex_pct_revenue=[0.04] * 5, terminal_growth_rate=0.03,
    )
    a = _assumptions(base=scenario)
    results = adr.run_ai_dcf_engine("UPS", a, reports_cogs=True)
    base = results["base"]
    achieved_margin = base.fcff_series[0].ebit / base.fcff_series[0].revenue
    assert achieved_margin < 0.25  # well short of the 0.30 target — the ceiling in action


def test_run_ai_dcf_engine_base_failure_raises():
    """A base scenario that can't run (bogus ticker) must raise, not silently degrade."""
    a = _assumptions()
    with pytest.raises(Exception):
        adr.run_ai_dcf_engine("THISISNOTAREALTICKER", a, reports_cogs=True)


# ---------------------------------------------------------------------------
# AiDcfResult — JSON round-trip + renderer number-matching
# ---------------------------------------------------------------------------

def _fixture_result() -> adr.AiDcfResult:
    a = _assumptions()
    fb = adr.FundamentalsBrief(
        growth_history="grew steadily", margin_history="stable margins",
        capital_intensity="moderate capex", working_capital="normal NWC",
        cyclicality_assessment="mildly cyclical", sustainable_ranges="8-12% growth",
    )
    ib = adr.IndustryBrief(
        industry_growth_outlook="growing", pricing_margin_direction="stable",
        capex_cycle="mid-cycle", competitive_position="share holder",
        terminal_context="GDP-like", used_industry_report=True, industry_report_age_days=5,
    )
    gb = adr.GuidanceBrief(
        explicit_guidance="guided flat", strategy_shifts="none notable",
        demand_inflections="none", guidance_credibility="consistent beats",
        consensus_view="in line",
    )

    class _FakeYF:
        def __init__(self, year, revenue_growth, capex_pct_revenue):
            self.year = year
            self.revenue_growth = revenue_growth
            self.capex_pct_revenue = capex_pct_revenue

    class _FakeFC:
        def __init__(self, revenue, ebit, fcff):
            self.revenue = revenue
            self.ebit = ebit
            self.fcff = fcff

    class _FakeWacc:
        wacc = 0.09
        beta_raw = 1.1
        beta_relevered = 1.1
        cost_of_equity = 0.10
        cost_of_debt = 0.04
        tax_rate = 0.21

    class _FakeDcfResult:
        def __init__(self, value):
            self.intrinsic_value_per_share = value
            self.wacc_detail = _FakeWacc()
            self.terminal_growth_rate = 0.025
            self.tv_pct_enterprise_value = 0.6
            self.year_forecasts = [_FakeYF(2027 + i, 0.08, 0.05) for i in range(5)]
            self.fcff_series = [_FakeFC(1000 * (1.08 ** i), 200 * (1.08 ** i), 150 * (1.08 ** i)) for i in range(5)]
            self.warnings = []

    engine_results = {"bear": _FakeDcfResult(80.0), "base": _FakeDcfResult(100.0), "bull": _FakeDcfResult(130.0)}
    return adr.AiDcfResult.build(
        ticker="TXN", model="test-model", assumptions=a,
        fundamentals_brief=fb, industry_brief=ib, guidance_brief=gb,
        engine_results=engine_results, qc_warnings=["a warning"],
        inputs_available={"industry_report_age_days": 5, "mda_filings_found": 4, "competitor_transcripts_found": 8},
    )


def test_ai_dcf_result_json_round_trip():
    result = _fixture_result()
    restored = adr.AiDcfResult.from_json(result.to_json())
    assert restored.ticker == result.ticker
    assert restored.model == result.model
    assert restored.assumptions.base.revenue_growth == result.assumptions.base.revenue_growth
    assert restored.engine["base"]["intrinsic_value_per_share"] == result.engine["base"]["intrinsic_value_per_share"]
    assert restored.qc_warnings == result.qc_warnings


def test_render_ai_dcf_markdown_numbers_match_fixture():
    result = _fixture_result()
    md = adr.render_ai_dcf_markdown(result)
    assert "$80.00" in md  # bear
    assert "$100.00" in md  # base
    assert "$130.00" in md  # bull
    assert "9.00%" in md  # WACC
    assert "debate one" in md
    assert "a warning" in md
    assert "5d old" in md


def test_render_ai_dcf_triangulation_row():
    result = _fixture_result()
    row = adr.render_ai_dcf_triangulation_row(result.engine)
    assert row == ["DCF (AI-authored)", "$80.00", "$100.00", "$130.00"]


def test_render_ai_dcf_triangulation_row_handles_missing_scenarios():
    row = adr.render_ai_dcf_triangulation_row({"bear": None, "base": None, "bull": None})
    assert row == ["DCF (AI-authored)", "n/a", "n/a", "n/a"]


def test_render_ai_dcf_comparison_table_structure():
    result = _fixture_result()
    md = adr.render_ai_dcf_comparison_table(result.engine, {"bear": None, "base": None, "bull": None})
    assert "AI vs. Mechanical DCF Assumptions" in md
    assert "8.0%" in md  # AI rev CAGR/margin cells derived from the fixture's 8% growth


# ---------------------------------------------------------------------------
# Phase 3 — evidence agent fan-out (mocked agents, no real LLM calls)
# ---------------------------------------------------------------------------

def test_run_evidence_agents_requires_openrouter_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        import asyncio
        asyncio.run(adr.run_evidence_agents("TXN", "test-model", "fc", "ic", "gc"))


def test_run_evidence_agents_fan_out_one_failure_others_succeed(monkeypatch):
    import asyncio

    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-test")

    real_fundamentals = adr.FundamentalsBrief(
        growth_history="real growth", margin_history="real margin",
        capital_intensity="real capex", working_capital="real nwc",
        cyclicality_assessment="real cyclicality", sustainable_ranges="real ranges",
    )
    real_guidance = adr.GuidanceBrief(
        explicit_guidance="real guidance", strategy_shifts="real shifts",
        demand_inflections="real inflections", guidance_credibility="real credibility",
        consensus_view="real consensus",
    )

    async def _fake_run_evidence_agent(name, prompt_name, ticker, model_label, context, output_type, fallback, llm):
        if name == "fundamentals_historian":
            return real_fundamentals
        if name == "guidance_mda_analyst":
            return real_guidance
        # industry_competitors_analyst "fails" -> falls back
        return fallback

    monkeypatch.setattr(adr, "_run_evidence_agent", _fake_run_evidence_agent)

    fundamentals, industry, guidance = asyncio.run(
        adr.run_evidence_agents("TXN", "test-model", "fund ctx", "industry ctx", "guidance ctx")
    )
    assert fundamentals is real_fundamentals
    assert guidance is real_guidance
    assert industry.industry_growth_outlook.startswith("[ERROR]")
    assert industry.used_industry_report is False


def test_fill_prompt_substitutes_placeholders():
    prompt_path = adr._load_prompt.__module__  # sanity: importable
    filled = adr._fill_prompt("ai_dcf_fundamentals.md", "TXN", "test-model", "SOME CONTEXT BLOCK")
    assert "TXN" in filled
    assert "SOME CONTEXT BLOCK" in filled
    assert "{ticker}" not in filled
    assert "{context}" not in filled


@pytest.mark.parametrize("prompt_name", [
    "ai_dcf_fundamentals.md", "ai_dcf_industry.md", "ai_dcf_guidance.md",
])
def test_evidence_prompts_load_and_fill_cleanly(prompt_name):
    filled = adr._fill_prompt(prompt_name, "UPS", "test-model", "CONTEXT HERE")
    assert "{ticker}" not in filled
    assert "{date}" not in filled
    assert "{context}" not in filled
    assert "{style_guide}" not in filled
    assert "UPS" in filled


def test_brief_schemas_sanitize_literal_backslash_n():
    """Regression test for the literal-backslash-n LLM quirk found live on TXN's fundamentals
    brief during the Phase 3 check (2026-07-30) — same landmine industry_research_router.py
    already works around for its own prose fields."""
    fb = adr.FundamentalsBrief(
        growth_history="line one\\nline two", margin_history="ok", capital_intensity="ok",
        working_capital="ok", cyclicality_assessment="ok", sustainable_ranges="ok",
    )
    assert fb.growth_history == "line one\nline two"
    assert "\\n" not in fb.growth_history


def test_ai_dcf_assumptions_sanitizes_key_debates_list():
    a = adr.AiDcfAssumptions(
        bear=_scenario(), base=_scenario(), bull=_scenario(),
        wacc_rationale="x", key_debates=["debate\\none", "debate two"],
    )
    assert a.key_debates[0] == "debate\none"


# ---------------------------------------------------------------------------
# Phase 4 — DCF Architect + orchestrator (mocked agents, real data layer + real engine)
# ---------------------------------------------------------------------------

def _fixture_briefs():
    fb = adr.FundamentalsBrief(
        growth_history="g", margin_history="m", capital_intensity="c",
        working_capital="w", cyclicality_assessment="cy", sustainable_ranges="s",
    )
    ib = adr.IndustryBrief(
        industry_growth_outlook="g", pricing_margin_direction="p", capex_cycle="c",
        competitive_position="cp", terminal_context="t", used_industry_report=False,
    )
    gb = adr.GuidanceBrief(
        explicit_guidance="e", strategy_shifts="s", demand_inflections="d",
        guidance_credibility="gc", consensus_view="cv",
    )
    return fb, ib, gb


def _patch_agents_success(monkeypatch):
    async def _fake_run_evidence_agents(ticker, model, fund_ctx, industry_ctx, guidance_ctx):
        return _fixture_briefs()

    async def _fake_run_architect(ticker, model, context):
        return _assumptions()

    monkeypatch.setattr(adr, "run_evidence_agents", _fake_run_evidence_agents)
    monkeypatch.setattr(adr, "run_architect", _fake_run_architect)


def test_run_ai_dcf_mocked_agents_real_data_real_engine(monkeypatch):
    """Mocks exactly the 2 LLM-calling boundaries (evidence fan-out + Architect); everything
    else — data gathering, guardrails, the DCF engine — runs for real against TXN."""
    _patch_agents_success(monkeypatch)
    result = asyncio.run(adr.run_ai_dcf("TXN", "test-model"))
    assert result.ticker == "TXN"
    assert result.engine["base"] is not None
    assert math.isfinite(result.engine["base"]["intrinsic_value_per_share"])
    assert result.engine["bear"] is not None
    assert result.engine["bull"] is not None

    md = adr.render_ai_dcf_markdown(result)
    assert "AI DCF Valuation — TXN" in md
    assert "$" in md


def test_run_ai_dcf_degraded_inputs_still_completes(monkeypatch):
    """No industry report / MD&A / competitor transcripts available — the run must still
    complete, with inputs_available reflecting the degradation."""
    monkeypatch.setattr(add, "get_mda_history", lambda ticker, n_annual=3: "[INFO] No MD&A cached")
    monkeypatch.setattr(add, "get_industry_report", lambda ticker, max_age_days=14: None)
    monkeypatch.setattr(
        add, "get_competitor_transcripts",
        lambda ticker, max_peers=5, n_quarters=4: "[INFO] No cached transcripts for any peer",
    )
    _patch_agents_success(monkeypatch)

    result = asyncio.run(adr.run_ai_dcf("TXN", "test-model"))
    assert result.inputs_available["industry_report_age_days"] is None
    assert result.inputs_available["mda_filings_found"] == 0
    assert result.inputs_available["competitor_transcripts_found"] == 0
    assert result.engine["base"] is not None  # numeric engine unaffected by qualitative degradation


def test_run_ai_dcf_architect_failure_raises(monkeypatch):
    async def _fake_run_evidence_agents(ticker, model, fund_ctx, industry_ctx, guidance_ctx):
        return _fixture_briefs()

    async def _fake_run_architect_fails(ticker, model, context):
        raise RuntimeError("architect boom")

    monkeypatch.setattr(adr, "run_evidence_agents", _fake_run_evidence_agents)
    monkeypatch.setattr(adr, "run_architect", _fake_run_architect_fails)

    with pytest.raises(RuntimeError, match="architect boom"):
        asyncio.run(adr.run_ai_dcf("TXN", "test-model"))


def test_run_ai_dcf_base_scenario_engine_failure_raises(monkeypatch):
    """A bogus ticker degrades every data-layer call to placeholders but must still surface a
    clean failure (via run_ai_dcf_engine's own RuntimeError) rather than crashing elsewhere."""
    _patch_agents_success(monkeypatch)
    with pytest.raises(Exception):
        asyncio.run(adr.run_ai_dcf("THISISNOTAREALTICKER", "test-model"))


def test_run_ai_dcf_status_callback_receives_all_phases(monkeypatch):
    _patch_agents_success(monkeypatch)
    seen = []
    result = asyncio.run(adr.run_ai_dcf("TXN", "test-model", status_cb=lambda phase, msg: seen.append(phase)))
    assert seen == ["gathering_data", "running_evidence", "running_architect", "computing_dcf"]
    assert result.engine["base"] is not None


# ---------------------------------------------------------------------------
# Phase 8 — DCF reconciliation audit trail
# ---------------------------------------------------------------------------

def test_compute_divergence_pct_basic():
    assert adr.compute_divergence_pct(100.0, 120.0) == pytest.approx(0.20)
    assert adr.compute_divergence_pct(100.0, 80.0) == pytest.approx(-0.20)
    assert adr.compute_divergence_pct(100.0, 100.0) == pytest.approx(0.0)


def test_compute_divergence_pct_none_when_missing_or_zero():
    assert adr.compute_divergence_pct(None, 120.0) is None
    assert adr.compute_divergence_pct(100.0, None) is None
    assert adr.compute_divergence_pct(None, None) is None
    assert adr.compute_divergence_pct(0.0, 120.0) is None


def test_compute_dcf_anchor_picks_closer_side():
    assert adr.compute_dcf_anchor(fair_value_base=55.0, mechanical_base=53.0, ai_base=90.0) == "mechanical"
    assert adr.compute_dcf_anchor(fair_value_base=85.0, mechanical_base=53.0, ai_base=90.0) == "ai"


def test_compute_dcf_anchor_tied():
    assert adr.compute_dcf_anchor(fair_value_base=60.0, mechanical_base=50.0, ai_base=70.0) == "tied"


def test_compute_dcf_anchor_only_one_available():
    assert adr.compute_dcf_anchor(fair_value_base=55.0, mechanical_base=None, ai_base=90.0) == "ai_only"
    assert adr.compute_dcf_anchor(fair_value_base=55.0, mechanical_base=53.0, ai_base=None) == "mechanical_only"


def test_compute_dcf_anchor_neither_available():
    assert adr.compute_dcf_anchor(fair_value_base=55.0, mechanical_base=None, ai_base=None) == "neither_available"


def test_log_dcf_reconciliation_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(adr, "_RECONCILIATION_LOG_DB", tmp_path / "log.duckdb")
    adr.log_dcf_reconciliation(
        "TXN", "test-model", mechanical_base=53.48, ai_base=60.79,
        fair_value_base=58.0, reconciliation_text="anchored on the AI DCF because of guidance",
    )
    rows = adr.get_reconciliation_log("TXN")
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "TXN"
    assert row["mechanical_base"] == pytest.approx(53.48)
    assert row["ai_base"] == pytest.approx(60.79)
    assert row["divergence_pct"] == pytest.approx((60.79 - 53.48) / 53.48)
    assert row["anchor"] in ("mechanical", "ai", "tied")
    assert row["reconciliation_text"] == "anchored on the AI DCF because of guidance"


def test_log_dcf_reconciliation_handles_missing_bases(tmp_path, monkeypatch):
    monkeypatch.setattr(adr, "_RECONCILIATION_LOG_DB", tmp_path / "log.duckdb")
    adr.log_dcf_reconciliation(
        "CRWV", "test-model", mechanical_base=None, ai_base=None,
        fair_value_base=0.0, reconciliation_text="",
    )
    rows = adr.get_reconciliation_log("CRWV")
    assert len(rows) == 1
    assert rows[0]["mechanical_base"] is None
    assert rows[0]["ai_base"] is None
    assert rows[0]["divergence_pct"] is None
    assert rows[0]["anchor"] == "neither_available"


def test_log_dcf_reconciliation_never_raises_on_db_failure(tmp_path, monkeypatch):
    """A logging failure must never propagate — research report generation must not break
    because of an audit-trail write error."""
    monkeypatch.setattr(adr, "_RECONCILIATION_LOG_DB", tmp_path / "nonexistent_dir" / "sub" / "log.duckdb")

    def _boom():
        raise RuntimeError("disk full")
    monkeypatch.setattr(adr, "_init_reconciliation_log", _boom)
    adr.log_dcf_reconciliation(
        "TXN", "test-model", mechanical_base=50.0, ai_base=60.0,
        fair_value_base=55.0, reconciliation_text="x",
    )  # must not raise


def test_get_reconciliation_log_empty_when_no_db(tmp_path, monkeypatch):
    monkeypatch.setattr(adr, "_RECONCILIATION_LOG_DB", tmp_path / "nonexistent.duckdb")
    assert adr.get_reconciliation_log() == []


def test_get_reconciliation_log_respects_limit_and_ordering(tmp_path, monkeypatch):
    monkeypatch.setattr(adr, "_RECONCILIATION_LOG_DB", tmp_path / "log.duckdb")
    for i in range(3):
        adr.log_dcf_reconciliation(
            "TXN", "test-model", mechanical_base=50.0 + i, ai_base=60.0 + i,
            fair_value_base=55.0, reconciliation_text=f"reconciliation {i}",
        )
    rows = adr.get_reconciliation_log("TXN", limit=2)
    assert len(rows) == 2
    # newest first
    assert rows[0]["reconciliation_text"] == "reconciliation 2"


# ---------------------------------------------------------------------------
# ML comps divergence tracking (PLAN_ML_COMPS_TRIANGULATION.md — answers "how often does ML
# comps diverge from the Valuation Analyst's actual fair value" with real logged data)
# ---------------------------------------------------------------------------

def test_compute_ml_comps_divergence_pct_basic():
    assert adr.compute_ml_comps_divergence_pct(100.0, 120.0) == pytest.approx(0.20)
    assert adr.compute_ml_comps_divergence_pct(100.0, 80.0) == pytest.approx(-0.20)


def test_compute_ml_comps_divergence_pct_none_when_missing_or_zero():
    assert adr.compute_ml_comps_divergence_pct(100.0, None) is None
    assert adr.compute_ml_comps_divergence_pct(0.0, 120.0) is None


def test_log_dcf_reconciliation_persists_ml_comps_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(adr, "_RECONCILIATION_LOG_DB", tmp_path / "log.duckdb")
    adr.log_dcf_reconciliation(
        "AAPL", "test-model", mechanical_base=53.48, ai_base=60.79,
        fair_value_base=240.0, reconciliation_text="anchored on mechanical DCF",
        ml_comps_fair_value=279.63, ml_comps_ground_truth=279.63,
    )
    row = adr.get_reconciliation_log("AAPL")[0]
    assert row["ml_comps_fair_value"] == pytest.approx(279.63)
    assert row["ml_comps_ground_truth"] == pytest.approx(279.63)
    assert row["ml_comps_divergence_pct"] == pytest.approx((279.63 - 240.0) / 240.0)


def test_log_dcf_reconciliation_ml_comps_fields_default_null(tmp_path, monkeypatch):
    """Callers that don't pass the ML comps kwargs (or tickers where it was unavailable) must
    still round-trip cleanly — these columns were added after the table already existed."""
    monkeypatch.setattr(adr, "_RECONCILIATION_LOG_DB", tmp_path / "log.duckdb")
    adr.log_dcf_reconciliation(
        "TXN", "test-model", mechanical_base=53.48, ai_base=60.79,
        fair_value_base=58.0, reconciliation_text="x",
    )
    row = adr.get_reconciliation_log("TXN")[0]
    assert row["ml_comps_fair_value"] is None
    assert row["ml_comps_ground_truth"] is None
    assert row["ml_comps_divergence_pct"] is None


def test_reconciliation_log_alter_table_migrates_existing_db(tmp_path, monkeypatch):
    """A DB file created before this feature (no ml_comps_* columns) must not break — the
    ALTER TABLE ADD COLUMN IF NOT EXISTS migration must run cleanly against it."""
    import duckdb

    db_path = tmp_path / "pre_existing.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE dcf_reconciliation_log (
            ticker VARCHAR, model VARCHAR, generated_at TIMESTAMP,
            mechanical_base DOUBLE, ai_base DOUBLE, divergence_pct DOUBLE,
            anchor VARCHAR, reconciliation_text VARCHAR
        )
    """)
    conn.close()

    monkeypatch.setattr(adr, "_RECONCILIATION_LOG_DB", db_path)
    adr.log_dcf_reconciliation(
        "TXN", "test-model", mechanical_base=50.0, ai_base=60.0,
        fair_value_base=55.0, reconciliation_text="x",
        ml_comps_fair_value=57.0, ml_comps_ground_truth=57.0,
    )
    row = adr.get_reconciliation_log("TXN")[0]
    assert row["ml_comps_ground_truth"] == pytest.approx(57.0)


# ── Silent scenario failure ──────────────────────────────────────────────────

def test_missing_scenario_is_reported_not_swallowed():
    """A failed scenario must reach the reader.

    Every ordering comparison in check_scenario_ordering is guarded on `is not None`, so before
    this a failed scenario skipped its checks and emitted nothing: the valuation range silently
    lost an end. That is how tightening MAX_INTRINSIC_TO_PRICE tripled bull-scenario loss
    (2/25 -> 7/25) with no warning, no log line, and no note in the report.
    """
    ok = _dcf_result(intrinsic=10.0) if "_dcf_result" in globals() else None

    warnings = adr.check_scenario_ordering({"bear": None, "base": None, "bull": None})
    assert len(warnings) == 3
    assert all("failed to compute" in w for w in warnings)
    assert any(w.startswith("bull") for w in warnings), "the bull loss must be named explicitly"
    assert all("truncated" in w for w in warnings), (
        "the warning must say the range is truncated — a reader who is told only that a scenario "
        "failed does not know the presented spread is biased"
    )


def test_scenario_degradation_is_logged(caplog, monkeypatch):
    """run_ai_dcf_engine used the only bare `except Exception: None` in this module, with no
    logging, while every other failure path here logs. That made the regression invisible."""
    import logging as _logging

    def _boom(*a, **kw):
        raise ValueError("Intrinsic value per share is 99.9x the market price")

    monkeypatch.setattr(adr, "run_dcf_av", _boom)
    with caplog.at_level(_logging.WARNING):
        with pytest.raises(RuntimeError, match="AI DCF unavailable"):
            adr.run_ai_dcf_engine("AAPL", _assumptions(), reports_cogs=True)

    text = caplog.text
    assert "degraded to None" in text, "a failed scenario must log why"
    assert "99.9x" in text, "the underlying reason must survive into the log, not just the fact"
