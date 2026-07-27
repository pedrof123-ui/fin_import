"""
Industry AI Researcher — deterministic appendix-table + ranked-ideas unit tests (no LLM, no DB).

Covers api/industry_research_router.py per features/industry_research/PLAN.md Phase 2. All
renderers are pure functions over already-fetched data (industry_data.py's *_raw / *_df shapes),
so these tests build that data directly as fixtures rather than hitting real databases.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import asyncio

import api.industry_research_router as rr
from api.industry_research_router import (
    ChiefOutput,
    CompanyDigest,
    IndustryIdea,
    ReportHeader,
    RisksOutput,
    TrendsOutput,
    _build_digest_context,
    _run_digest_subagent,
    attach_idea_metrics,
    build_coverage_note,
    render_industry_report,
    run_company_digests,
    run_industry_synthesis,
    render_beat_miss_table,
    render_industry_aggregates_table,
    render_member_financials_table,
    render_revision_momentum_table,
    validate_ranked_ideas,
)


def _assert_valid_md_table(text: str, expected_min_rows: int = 1):
    """A valid _md_table block has a header row, a separator row (all dashes/pipes), then
    >=1 data rows."""
    table_lines = [l for l in text.splitlines() if l.strip().startswith("|")]
    assert len(table_lines) >= 2 + expected_min_rows
    assert set(table_lines[1].replace("|", "").replace(" ", "")) <= {"-"}


# ---------------------------------------------------------------------------
# render_industry_aggregates_table
# ---------------------------------------------------------------------------

def _sample_aggregates_raw(pe_median=94.3, ticker_count=52):
    current = {
        "group_name": "SEMICONDUCTORS", "month_end_date": date(2026, 6, 30),
        "ticker_count": ticker_count, "pe_median": pe_median, "pfcf_median": 75.7,
        "evebitda_median": 57.4, "ps_median": 14.0, "rev_growth_1yr_median": 0.159,
        "earn_growth_1yr_median": 0.138, "gross_margin_median": 0.515,
        "operating_margin_median": 0.056, "fcf_margin_median": 0.157,
        "roic_median": 0.068, "roe_median": 0.040, "debt_to_ebitda_median": 0.1,
    }
    deltas = {3: (55.3, 34.7, 0.101), 6: (44.1, 22.6, 0.080), 12: (33.9, 24.5, 0.026)}
    return {"current": current, "deltas": deltas}


def test_render_industry_aggregates_table_valid_markdown():
    result = render_industry_aggregates_table(_sample_aggregates_raw())
    assert "SEMICONDUCTORS" in result
    assert "52 tickers measured" in result
    _assert_valid_md_table(result, expected_min_rows=12)  # 12 metric rows
    assert "3mo" in result and "6mo" in result and "12mo" in result


def test_render_industry_aggregates_table_missing_deltas_degrades_to_na():
    raw = _sample_aggregates_raw()
    raw["deltas"] = {3: None, 6: None, 12: None}
    result = render_industry_aggregates_table(raw)
    assert result.count("n/a") >= 3  # one n/a row per missing period, all 3 columns


def test_render_industry_aggregates_table_none_input_returns_empty():
    assert render_industry_aggregates_table(None) == ""


# ---------------------------------------------------------------------------
# render_member_financials_table
# ---------------------------------------------------------------------------

def _sample_financials_df():
    return pd.DataFrame([
        {"ticker": "NVDA", "name": "NVIDIA Corporation", "market_cap_b": 4880.4,
         "current_pe": 30.6, "forward_pe": 22.3, "current_pfcf": 41.0,
         "rev_growth_1yr": 0.655, "earn_growth_1yr": 0.668,
         "current_roic": 0.865, "current_gross_margin": 0.741},
        {"ticker": "TSM", "name": "Taiwan Semiconductor", "market_cap_b": None,
         "current_pe": 1.1, "forward_pe": 30.2, "current_pfcf": 1.9,
         "rev_growth_1yr": 0.330, "earn_growth_1yr": 0.499,
         "current_roic": 0.635, "current_gross_margin": 0.619},
        {"ticker": "INTC", "name": "Intel Corporation", "market_cap_b": 709.7,
         "current_pe": None, "forward_pe": 128.0, "current_pfcf": None,
         "rev_growth_1yr": -0.005, "earn_growth_1yr": -0.794,
         "current_roic": -0.006, "current_gross_margin": 0.354},
    ])


def test_render_member_financials_table_valid_markdown_and_handles_nulls():
    result = render_member_financials_table(_sample_financials_df())
    _assert_valid_md_table(result, expected_min_rows=3)
    assert "NVDA" in result and "TSM" in result and "INTC" in result
    assert "n/a" in result  # INTC's null current_pe / current_pfcf, TSM's null market_cap_b


def test_render_member_financials_table_empty_df_returns_empty():
    assert render_member_financials_table(pd.DataFrame()) == ""


# ---------------------------------------------------------------------------
# render_beat_miss_table
# ---------------------------------------------------------------------------

def test_render_beat_miss_table_valid_markdown_with_dispersion_footer():
    tickers = ["NVDA", "MU", "TSM"]
    raw = {
        "NVDA": [{"surprise_pct": 5.6, "fiscal_date_ending": "2026-04-30"}],
        "MU": [{"surprise_pct": 18.6, "fiscal_date_ending": "2026-05-31"}],
        "TSM": None,
    }
    result = render_beat_miss_table(tickers, raw)
    _assert_valid_md_table(result, expected_min_rows=3)
    assert "TSM" in result and "n/a" in result
    assert "2/2 members beat" in result


def test_render_beat_miss_table_empty_tickers_returns_empty():
    assert render_beat_miss_table([], {}) == ""


def test_render_beat_miss_table_missing_key_treated_as_no_data():
    result = render_beat_miss_table(["ZZZZ"], {})
    assert "ZZZZ" in result
    assert "n/a" in result


# ---------------------------------------------------------------------------
# render_revision_momentum_table
# ---------------------------------------------------------------------------

def _sample_estimates_df():
    return pd.DataFrame([
        {"ticker": "NVDA", "eps_avg": 2.08, "eps_avg_7d": 2.08, "eps_avg_30d": 1.95,
         "eps_rev_up_7d": 34, "eps_rev_down_7d": 0},
        {"ticker": "ARM", "eps_avg": 0.43, "eps_avg_7d": 0.43, "eps_avg_30d": None,
         "eps_rev_up_7d": None, "eps_rev_down_7d": None},
    ])


def test_render_revision_momentum_table_valid_markdown():
    tickers = ["NVDA", "ARM", "MISSING"]
    result = render_revision_momentum_table(tickers, _sample_estimates_df())
    _assert_valid_md_table(result, expected_min_rows=3)
    assert "34up/0dn" in result
    assert "0up/0dn" in result  # ARM's null revision counts -> 0, not a crash
    assert "MISSING" in result and "no estimate" not in result  # row present, just n/a fields


def test_render_revision_momentum_table_empty_tickers_returns_empty():
    assert render_revision_momentum_table([], pd.DataFrame()) == ""


def test_render_revision_momentum_table_empty_df_all_members_na():
    result = render_revision_momentum_table(["NVDA", "AMD"], pd.DataFrame())
    assert "NVDA" in result and "AMD" in result
    assert result.count("n/a") >= 6  # 3 n/a columns x 2 tickers


# ---------------------------------------------------------------------------
# attach_idea_metrics
# ---------------------------------------------------------------------------

def test_attach_idea_metrics_matches_known_tickers():
    ideas = [
        IndustryIdea(ticker="NVDA", stance="OVERWEIGHT", catalyst="AI demand", key_risk="export controls"),
    ]
    fin_df = _sample_financials_df()
    est_df = _sample_estimates_df()
    rows = attach_idea_metrics(ideas, fin_df, industry_pe_median=94.3, estimates_df=est_df)

    assert len(rows) == 1
    ticker, stance, catalyst, key_risk, valuation_txt, revision_txt = rows[0]
    assert ticker == "NVDA"
    assert stance == "OVERWEIGHT"
    assert "30.6" in valuation_txt and "94.3" in valuation_txt
    assert "34up/0dn" in revision_txt


def test_attach_idea_metrics_unknown_ticker_degrades_to_na_not_crash():
    ideas = [
        IndustryIdea(ticker="ZZZZ_NOT_REAL", stance="NEUTRAL", catalyst="n/a", key_risk="n/a"),
    ]
    rows = attach_idea_metrics(
        ideas, _sample_financials_df(), industry_pe_median=94.3, estimates_df=_sample_estimates_df(),
    )
    assert len(rows) == 1
    assert rows[0][0] == "ZZZZ_NOT_REAL"
    assert rows[0][4] == "n/a"  # valuation
    assert rows[0][5] == "n/a"  # revision


def test_attach_idea_metrics_null_pe_member_degrades_to_na():
    """INTC has current_pe = None in the fixture — must not crash computing valuation vs industry."""
    ideas = [
        IndustryIdea(ticker="INTC", stance="UNDERWEIGHT", catalyst="foundry ramp", key_risk="execution"),
    ]
    rows = attach_idea_metrics(
        ideas, _sample_financials_df(), industry_pe_median=94.3, estimates_df=_sample_estimates_df(),
    )
    assert rows[0][4] == "n/a"


def test_attach_idea_metrics_empty_ideas_returns_empty_list():
    assert attach_idea_metrics([], _sample_financials_df(), 94.3, _sample_estimates_df()) == []


def test_attach_idea_metrics_empty_dataframes_degrade_gracefully():
    ideas = [IndustryIdea(ticker="NVDA", stance="OVERWEIGHT", catalyst="x", key_risk="y")]
    rows = attach_idea_metrics(ideas, pd.DataFrame(), None, pd.DataFrame())
    assert rows == [["NVDA", "OVERWEIGHT", "x", "y", "n/a", "n/a"]]


# ---------------------------------------------------------------------------
# Stage 1 — per-company Earnings Digest (Phase 3)
# ---------------------------------------------------------------------------

def _sample_digest(ticker: str) -> CompanyDigest:
    return CompanyDigest(
        ticker=ticker, demand="steady", pricing_margins="stable",
        guidance_direction="MAINTAINED", capex_investment="modest",
        management_tone="NEUTRAL", notable_quotes=[], company_risks=["competition"],
    )


def test_build_digest_context_includes_all_sections():
    context = _build_digest_context(
        "NVDA", [("2026Q2", "call text here")],
        {"NVDA": [{"surprise_pct": 5.6, "fiscal_date_ending": "2026-04-30"}]},
        pd.Series({"market_cap_b": 100.0, "current_pe": 20.0,
                   "rev_growth_1yr": 0.1, "earn_growth_1yr": 0.2}),
    )
    assert "NVDA" in context
    assert "call text here" in context
    assert "+5.6%" in context
    assert "Mkt Cap $100.0B" in context


def test_build_digest_context_degrades_gracefully_with_no_beat_miss_or_financials():
    context = _build_digest_context("XYZ", [("2026Q1", "text")], {}, None)
    assert "no data" in context
    assert "not available" in context


@pytest.mark.asyncio
async def test_run_company_digests_skips_members_with_no_transcript(monkeypatch):
    """A member with zero cached transcript quarters must be skipped entirely — no LLM call,
    no digest — not passed to the sub-agent and marked failed."""
    async def fake_subagent(ticker, context, model, llm):
        return _sample_digest(ticker)
    monkeypatch.setattr(rr, "_run_digest_subagent", fake_subagent)

    transcripts = {"A": [("2026Q1", "t")], "B": [], "C": [("2026Q1", "t")]}
    result = await run_company_digests(
        ["A", "B", "C"], transcripts, {}, pd.DataFrame(), "some-model", llm=object(),
    )
    assert set(result.keys()) == {"A", "C"}
    assert isinstance(result["A"], CompanyDigest)


@pytest.mark.asyncio
async def test_run_company_digests_all_missing_transcripts_returns_empty(monkeypatch):
    result = await run_company_digests(
        ["A", "B"], {"A": [], "B": None}, {}, pd.DataFrame(), "some-model", llm=object(),
    )
    assert result == {}


@pytest.mark.asyncio
async def test_run_company_digests_single_failure_does_not_kill_batch(monkeypatch):
    """A member whose sub-agent call fails (returns None, per _run_digest_subagent's own
    never-raise contract) must not prevent the other members' digests from coming back."""
    async def fake_subagent(ticker, context, model, llm):
        if ticker == "FAIL":
            return None
        return _sample_digest(ticker)
    monkeypatch.setattr(rr, "_run_digest_subagent", fake_subagent)

    transcripts = {"OK1": [("2026Q1", "t")], "FAIL": [("2026Q1", "t")], "OK2": [("2026Q1", "t")]}
    result = await run_company_digests(
        ["OK1", "FAIL", "OK2"], transcripts, {}, pd.DataFrame(), "some-model", llm=object(),
    )
    assert set(result.keys()) == {"OK1", "OK2"}


@pytest.mark.asyncio
async def test_run_digest_subagent_catches_timeout(monkeypatch):
    class _FakeRunner:
        @staticmethod
        async def run(agent, message):
            raise asyncio.TimeoutError()
    monkeypatch.setattr(rr, "Runner", _FakeRunner)

    result = await _run_digest_subagent("NVDA", "some context", "some-model", llm=object())
    assert result is None


@pytest.mark.asyncio
async def test_run_digest_subagent_catches_generic_exception(monkeypatch):
    class _FakeRunner:
        @staticmethod
        async def run(agent, message):
            raise RuntimeError("provider exploded")
    monkeypatch.setattr(rr, "Runner", _FakeRunner)

    result = await _run_digest_subagent("NVDA", "some context", "some-model", llm=object())
    assert result is None


@pytest.mark.asyncio
async def test_run_digest_subagent_returns_output_on_success(monkeypatch):
    class _FakeResult:
        final_output = _sample_digest("NVDA")

    class _FakeRunner:
        @staticmethod
        async def run(agent, message):
            return _FakeResult()
    monkeypatch.setattr(rr, "Runner", _FakeRunner)

    result = await _run_digest_subagent("NVDA", "some context", "some-model", llm=object())
    assert result.ticker == "NVDA"


# ---------------------------------------------------------------------------
# build_coverage_note (Phase 4)
# ---------------------------------------------------------------------------

def test_build_coverage_note_none_when_full_coverage():
    transcripts = {"A": [("2026Q1", "t")], "B": [("2026Q1", "t")]}
    assert build_coverage_note(["A", "B"], transcripts) is None


def test_build_coverage_note_flags_missing_members():
    transcripts = {"A": [("2026Q1", "t")], "B": [], "C": [("2026Q1", "t")]}
    note = build_coverage_note(["A", "B", "C"], transcripts)
    assert note is not None
    assert "1/3" in note
    assert "B" in note


# ---------------------------------------------------------------------------
# validate_ranked_ideas (Phase 4)
# ---------------------------------------------------------------------------

def _idea(ticker, stance="NEUTRAL"):
    return IndustryIdea(ticker=ticker, stance=stance, catalyst="x", key_risk="y")


def test_validate_ranked_ideas_clean_case_no_findings():
    ideas = [_idea("A"), _idea("B")]
    assert validate_ranked_ideas(ideas, ["A", "B"]) == []


def test_validate_ranked_ideas_flags_invented_ticker():
    ideas = [_idea("A"), _idea("ZZZZ_NOT_A_MEMBER")]
    findings = validate_ranked_ideas(ideas, ["A"])
    assert any("not in the member list" in f and "ZZZZ_NOT_A_MEMBER" in f for f in findings)


def test_validate_ranked_ideas_flags_missing_member():
    ideas = [_idea("A")]
    findings = validate_ranked_ideas(ideas, ["A", "B"])
    assert any("missing entries" in f and "B" in f for f in findings)


def test_validate_ranked_ideas_flags_duplicate_ticker():
    ideas = [_idea("A"), _idea("A")]
    findings = validate_ranked_ideas(ideas, ["A"])
    assert any("duplicate" in f and "A" in f for f in findings)


def test_validate_ranked_ideas_case_insensitive_matching():
    ideas = [_idea("nvda")]
    assert validate_ranked_ideas(ideas, ["NVDA"]) == []


# ---------------------------------------------------------------------------
# run_industry_synthesis (Phase 4) — Runner mocked, no network
# ---------------------------------------------------------------------------

def _sample_trends() -> TrendsOutput:
    return TrendsOutput(
        industry_state_trends="steady growth",
        demand_pricing_margin_signals="margins expanding",
        capital_cycle_competitive_dynamics="capex rising",
    )


def _sample_risks() -> RisksOutput:
    return RisksOutput(risks_headwinds="regulatory risk", forward_outlook="guidance mixed")


def _sample_chief() -> ChiefOutput:
    return ChiefOutput(
        executive_summary=["industry is healthy"],
        ranked_ideas=[_idea("A", "OVERWEIGHT")],
    )


@pytest.mark.asyncio
async def test_run_industry_synthesis_happy_path(monkeypatch):
    call_log = []

    async def fake_stage_agent(name, prompt_name, context, output_type, llm, extra=None):
        call_log.append(name)
        if output_type is TrendsOutput:
            return _sample_trends()
        if output_type is RisksOutput:
            return _sample_risks()
        if output_type is ChiefOutput:
            return _sample_chief()
        raise AssertionError(f"unexpected output_type {output_type}")

    monkeypatch.setattr(rr, "_run_stage_agent", fake_stage_agent)

    trends, risks, chief = await run_industry_synthesis(
        "Semiconductors", ["A"], {}, "agg text", "web text",
        _sample_financials_df().head(1).assign(ticker="A"), pd.DataFrame(), "some-model", llm=object(),
    )
    assert trends == _sample_trends()
    assert risks == _sample_risks()
    assert chief == _sample_chief()
    # Trends and Risks must both run before Chief (Chief needs their output as context)
    assert set(call_log[:2]) == {"trends_developments_analyst", "risks_outlook_analyst"}
    assert call_log[2] == "chief_industry_strategist"


@pytest.mark.asyncio
async def test_run_industry_synthesis_partial_failure_degrades_not_crashes(monkeypatch):
    async def fake_stage_agent(name, prompt_name, context, output_type, llm, extra=None):
        if output_type is TrendsOutput:
            return None  # simulates a timed-out/failed specialist
        if output_type is RisksOutput:
            return _sample_risks()
        if output_type is ChiefOutput:
            return _sample_chief()

    monkeypatch.setattr(rr, "_run_stage_agent", fake_stage_agent)

    trends, risks, chief = await run_industry_synthesis(
        "Semiconductors", ["A"], {}, "agg text", "web text",
        _sample_financials_df().head(1).assign(ticker="A"), pd.DataFrame(), "some-model", llm=object(),
    )
    assert trends is None
    assert risks == _sample_risks()
    assert chief == _sample_chief()


# ---------------------------------------------------------------------------
# render_industry_report (Phase 4)
# ---------------------------------------------------------------------------

def _sample_header() -> ReportHeader:
    return ReportHeader(
        industry_label="Semiconductors", members=["A", "B"],
        quarters_covered=4, prepared_date="2026-07-27", model="google/gemini-3.5-flash",
    )


def test_render_industry_report_sanitizes_literal_backslash_n_in_prose():
    """Regression test: gemini-3.5-flash was observed live emitting the literal two-character
    sequence backslash-n inside a TrendsOutput field instead of a real newline. Unsanitized, this
    renders as visible "\\n" text in the frontend markdown viewer instead of a line break."""
    trends = TrendsOutput(
        industry_state_trends="**Header:**\\n- bullet one\\n- bullet two",
        demand_pricing_margin_signals="fine", capital_cycle_competitive_dynamics="fine",
    )
    result = render_industry_report(
        _sample_header(), trends, _sample_risks(), executive_summary=[], ranked_ideas_rows=[],
        aggregates_table_md="", member_financials_table_md="",
        beat_miss_table_md="", revision_momentum_table_md="",
    )
    assert "\\n" not in result
    assert "bullet one\n- bullet two" in result


def test_attach_idea_metrics_sanitizes_literal_backslash_n_in_table_cells():
    """Same quirk in a table-cell field must collapse to a space, not a real newline — a raw
    newline inside a markdown table cell breaks the table's row structure."""
    ideas = [
        IndustryIdea(ticker="A", stance="OVERWEIGHT",
                     catalyst="line one\\nline two", key_risk="risk one\\nrisk two"),
    ]
    rows = attach_idea_metrics(ideas, _sample_financials_df().assign(ticker="A").head(1), None, pd.DataFrame())
    assert "\\n" not in rows[0][2]
    assert "\\n" not in rows[0][3]
    assert "line one line two" == rows[0][2]


def test_render_industry_report_full_happy_path():
    result = render_industry_report(
        _sample_header(), _sample_trends(), _sample_risks(),
        executive_summary=["industry is healthy"],
        ranked_ideas_rows=[["A", "OVERWEIGHT", "catalyst", "risk", "20.0x vs 25.0x (-20%)", "3up/0dn (7d)"]],
        aggregates_table_md="#### Aggregates\n\n| a | b |\n| --- | --- |\n| 1 | 2 |",
        member_financials_table_md="#### Financials\n\n| a | b |\n| --- | --- |\n| 1 | 2 |",
        beat_miss_table_md="",
        revision_momentum_table_md="",
        coverage_note=None,
        qc_findings=None,
    )
    assert "Semiconductors" in result
    assert "industry is healthy" in result
    assert "steady growth" in result
    assert "regulatory risk" in result
    assert "OVERWEIGHT" in result
    assert "#### Aggregates" in result
    assert "Not investment advice" in result


def test_render_industry_report_missing_stages_show_error_placeholder():
    result = render_industry_report(
        _sample_header(), None, None, executive_summary=[], ranked_ideas_rows=[],
        aggregates_table_md="", member_financials_table_md="",
        beat_miss_table_md="", revision_momentum_table_md="",
    )
    assert result.count("[ERROR]") >= 5  # 3 trends sections + 2 risks sections + ranked ideas


def test_render_industry_report_includes_coverage_note_and_qc_findings():
    result = render_industry_report(
        _sample_header(), _sample_trends(), _sample_risks(), executive_summary=["x"],
        ranked_ideas_rows=[], aggregates_table_md="", member_financials_table_md="",
        beat_miss_table_md="", revision_momentum_table_md="",
        coverage_note="Coverage note: 1/2 members missing",
        qc_findings=["ranked_ideas is missing entries for member(s): B"],
    )
    assert "Coverage note: 1/2 members missing" in result
    assert "QC: 1 inconsistency" in result
    assert "missing entries for member(s): B" in result
