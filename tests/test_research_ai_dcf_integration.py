"""
Research-pipeline <-> Agentic AI DCF Valuator integration tests (features/ai_dcf/PLAN.md Phase 6).

Two layers:
1. Unit tests of each modified/new piece in api/research_router.py (schema, table renderers,
   _validate_report, _format_specialist_outputs, render_to_markdown) — these exercise the actual
   new Phase 6 logic directly, with fixture data, no LLM/network involved.
2. One full `_run_research_agent` end-to-end test per success/failure case: the LLM Agent/Runner
   chain is replaced with a lightweight fake that dispatches on `output_type` (the `agents`
   package itself is only a MagicMock via tests/conftest.py, so a real fake is needed to get
   type-aware canned responses); EDGAR/Tavily/AV-network calls are monkeypatched to canned
   strings; local-DB reads run for real against TXN. `get_or_run_ai_dcf` is monkeypatched to
   return a fixture AiDcfResult (success) or None (failure) — this is the actual new dependency
   Phase 6 adds, so it's the one thing deliberately varied between the two cases.
"""
from __future__ import annotations

import asyncio

import pytest

import api.ai_dcf_router as adr
import api.research_router as rr


@pytest.fixture(autouse=True)
def _isolate_reconciliation_log(tmp_path, monkeypatch):
    """_run_research_agent (Phase 8) writes one audit-trail row per real generation — every test
    in this file that exercises it for real must not pollute the project's actual
    dcf_reconciliation_log.duckdb."""
    monkeypatch.setattr(adr, "_RECONCILIATION_LOG_DB", tmp_path / "dcf_reconciliation_log.duckdb")


# ---------------------------------------------------------------------------
# Fixture AiDcfResult (mirrors tests/test_ai_dcf.py's fixture, kept self-contained here)
# ---------------------------------------------------------------------------

def _fixture_ai_dcf_result(ticker="TXN"):
    a = adr.AiDcfAssumptions(
        bear=adr.ScenarioAssumptions(revenue_growth=[0.03] * 5, cogs_pct=[0.4] * 5, ebit_margin_pct=[0.15] * 5,
                                      capex_pct_revenue=[0.05] * 5, terminal_growth_rate=0.02, rationale="bear story"),
        base=adr.ScenarioAssumptions(revenue_growth=[0.08] * 5, cogs_pct=[0.4] * 5, ebit_margin_pct=[0.20] * 5,
                                      capex_pct_revenue=[0.05] * 5, terminal_growth_rate=0.025, rationale="base story"),
        bull=adr.ScenarioAssumptions(revenue_growth=[0.15] * 5, cogs_pct=[0.38] * 5, ebit_margin_pct=[0.25] * 5,
                                      capex_pct_revenue=[0.05] * 5, terminal_growth_rate=0.03, rationale="bull story"),
        wacc_rationale="wacc story", key_debates=["debate one", "debate two"],
    )
    fb = adr.FundamentalsBrief(growth_history="g", margin_history="m", capital_intensity="c",
                                working_capital="w", cyclicality_assessment="cy", sustainable_ranges="s")
    ib = adr.IndustryBrief(industry_growth_outlook="g", pricing_margin_direction="p", capex_cycle="c",
                            competitive_position="cp", terminal_context="t", used_industry_report=False)
    gb = adr.GuidanceBrief(explicit_guidance="e", strategy_shifts="s", demand_inflections="d",
                            guidance_credibility="gc", consensus_view="cv")

    class _FakeYF:
        def __init__(self, year, revenue_growth, capex_pct_revenue):
            self.year, self.revenue_growth, self.capex_pct_revenue = year, revenue_growth, capex_pct_revenue

    class _FakeFC:
        def __init__(self, revenue, ebit, fcff):
            self.revenue, self.ebit, self.fcff = revenue, ebit, fcff

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

    engine_results = {"bear": _FakeDcfResult(45.0), "base": _FakeDcfResult(62.0), "bull": _FakeDcfResult(85.0)}
    return adr.AiDcfResult.build(
        ticker=ticker, model="test-model", assumptions=a, fundamentals_brief=fb,
        industry_brief=ib, guidance_brief=gb, engine_results=engine_results,
        qc_warnings=[], inputs_available={"industry_report_age_days": 5, "mda_filings_found": 3,
                                           "competitor_transcripts_found": 8},
    )


# ---------------------------------------------------------------------------
# 6.2/format_ai_dcf_summary — unavailable case
# ---------------------------------------------------------------------------

def test_format_ai_dcf_summary_unavailable():
    text = adr.format_ai_dcf_summary(None)
    assert text.startswith("[INFO]")
    assert "unavailable" in text.lower()


def test_format_ai_dcf_summary_present():
    result = _fixture_ai_dcf_result()
    text = adr.format_ai_dcf_summary(result)
    assert "AI-AUTHORED DCF VALUATION" in text
    assert "$62.00" in text  # base intrinsic value
    assert "debate one" in text


# ---------------------------------------------------------------------------
# 6.4 — _model_summary_table / render_valuation_model_tables with ai_dcf_engine
# ---------------------------------------------------------------------------

def test_model_summary_table_includes_ai_row_when_present():
    result = _fixture_ai_dcf_result()
    md = rr._model_summary_table(
        {"bear": None, "base": None, "bull": None}, None, None, None,
        60.0, 65.0, 70.0, ai_dcf_engine=result.engine,
    )
    assert "DCF (AI-authored)" in md
    assert "$45.00" in md and "$62.00" in md and "$85.00" in md


def test_model_summary_table_omits_ai_row_when_absent():
    md = rr._model_summary_table(
        {"bear": None, "base": None, "bull": None}, None, None, None, 60.0, 65.0, 70.0,
    )
    assert "DCF (AI-authored)" not in md


def test_render_valuation_model_tables_appends_comparison_table():
    result = _fixture_ai_dcf_result()
    md = rr.render_valuation_model_tables(
        "TXN", {"bear": None, "base": None, "bull": None}, 60.0, 65.0, 70.0, ai_dcf_result=result,
    )
    assert "AI vs. Mechanical DCF Assumptions" in md
    assert "DCF (AI-authored)" in md


def test_render_valuation_model_tables_no_ai_dcf():
    md = rr.render_valuation_model_tables(
        "TXN", {"bear": None, "base": None, "bull": None}, 60.0, 65.0, 70.0, ai_dcf_result=None,
    )
    assert "AI vs. Mechanical DCF Assumptions" not in md
    assert "DCF (AI-authored)" not in md


# ---------------------------------------------------------------------------
# 6.5 — _validate_report additions
# ---------------------------------------------------------------------------

def _fixture_report_and_valuation(ai_dcf_intrinsic_value, dcf_reconciliation=""):
    header = rr.ResearchHeader(
        company_name="Texas Instruments", ticker="TXN", prepared_date="2026-07-30",
        ai_model="test-model", rating="HOLD", target_low=55.0, target_high=75.0, thesis_summary="t",
    )
    report = rr.EquityResearchReport(
        header=header, key_highlights=[], financial_performance=[], financial_years=[],
        valuation=rr.ValuationSummary(current_price=65.0),
        company_overview="o", competitive_analysis="c", industry_outlook="i",
        strategic_framework_analysis="s", mda_summary="m", risk_factors=[], near_term_catalysts=[],
        earnings_highlights="e", quarterly_trend_analysis="q", technical_analysis="t",
        technical_rating="NEUTRAL", investment_thesis="th",
    )
    valuation_out = rr.ValuationOutput(
        fair_value_low=55.0, fair_value_base=62.0, fair_value_high=70.0,
        ai_dcf_intrinsic_value=ai_dcf_intrinsic_value, dcf_reconciliation=dcf_reconciliation,
        valuation_methodology="m", dcf_assessment="d", relative_valuation="r", valuation_risks=[],
    )
    technical_out = rr.TechnicalOutput(technical_analysis="t", technical_rating="NEUTRAL")
    return report, valuation_out, technical_out


def test_validate_report_flags_ai_dcf_intrinsic_value_mismatch():
    result = _fixture_ai_dcf_result()  # base intrinsic value = 62.0
    report, valuation_out, technical_out = _fixture_report_and_valuation(ai_dcf_intrinsic_value=99.0)
    findings = rr._validate_report(report, technical_out, valuation_out, ai_dcf_result=result)
    assert any("ai_dcf_intrinsic_value" in f for f in findings)


def test_validate_report_clean_when_ai_dcf_intrinsic_value_matches():
    result = _fixture_ai_dcf_result()  # base intrinsic value = 62.0
    report, valuation_out, technical_out = _fixture_report_and_valuation(ai_dcf_intrinsic_value=62.0)
    findings = rr._validate_report(report, technical_out, valuation_out, ai_dcf_result=result)
    assert not any("ai_dcf_intrinsic_value" in f for f in findings)


def test_validate_report_skips_ai_dcf_check_when_unavailable():
    report, valuation_out, technical_out = _fixture_report_and_valuation(ai_dcf_intrinsic_value=None)
    findings = rr._validate_report(report, technical_out, valuation_out, ai_dcf_result=None)
    assert not any("ai_dcf" in f for f in findings)


# ---------------------------------------------------------------------------
# _validate_report — Phase 8's >20%-divergence + empty-reconciliation guardrail
# ---------------------------------------------------------------------------

def test_validate_report_flags_large_divergence_with_empty_reconciliation():
    result = _fixture_ai_dcf_result()  # ai base = 62.0
    # mechanical=50.0, ai=62.0 -> divergence = (62-50)/50 = 24% > 20%
    report, valuation_out, technical_out = _fixture_report_and_valuation(
        ai_dcf_intrinsic_value=62.0, dcf_reconciliation="",
    )
    findings = rr._validate_report(
        report, technical_out, valuation_out, ai_dcf_result=result, mechanical_base=50.0,
    )
    assert any("divergence" in f.lower() or "diverge" in f.lower() for f in findings)


def test_validate_report_silent_on_large_divergence_with_real_reconciliation():
    result = _fixture_ai_dcf_result()  # ai base = 62.0
    report, valuation_out, technical_out = _fixture_report_and_valuation(
        ai_dcf_intrinsic_value=62.0,
        dcf_reconciliation="Anchored on the AI DCF because Q2 2026 guidance implies higher growth.",
    )
    findings = rr._validate_report(
        report, technical_out, valuation_out, ai_dcf_result=result, mechanical_base=50.0,
    )
    assert not any("diverge" in f.lower() for f in findings)


def test_validate_report_silent_when_divergence_under_threshold():
    result = _fixture_ai_dcf_result()  # ai base = 62.0
    # mechanical=55.0, ai=62.0 -> divergence = (62-55)/55 = 12.7% < 20%
    report, valuation_out, technical_out = _fixture_report_and_valuation(
        ai_dcf_intrinsic_value=62.0, dcf_reconciliation="",
    )
    findings = rr._validate_report(
        report, technical_out, valuation_out, ai_dcf_result=result, mechanical_base=55.0,
    )
    assert not any("diverge" in f.lower() for f in findings)


def test_validate_report_silent_when_mechanical_base_unavailable():
    result = _fixture_ai_dcf_result()
    report, valuation_out, technical_out = _fixture_report_and_valuation(
        ai_dcf_intrinsic_value=62.0, dcf_reconciliation="",
    )
    findings = rr._validate_report(
        report, technical_out, valuation_out, ai_dcf_result=result, mechanical_base=None,
    )
    assert not any("diverge" in f.lower() for f in findings)


# ---------------------------------------------------------------------------
# _build_post_subagent_tables — 4th return value (ground-truth mechanical base)
# ---------------------------------------------------------------------------

def test_build_post_subagent_tables_returns_mechanical_base():
    """Uses the real compute_dcf_scenarios("TXN") — read-only, DB-only, no LLM/network — since
    a fake DcfResult would need to satisfy the full interface _dcf_assumptions_table/_comps_table
    traverse (year_forecasts, fcff_series, wacc_detail, ...), not just intrinsic_value_per_share."""
    from api.valuation_data import compute_dcf_scenarios
    competitive = rr.CompetitiveOutput(competitive_analysis="c", industry_outlook="i", strategic_framework_analysis="s")
    valuation_out = rr.ValuationOutput(
        fair_value_low=50.0, fair_value_base=60.0, fair_value_high=70.0,
        valuation_methodology="m", dcf_assessment="d", relative_valuation="r", valuation_risks=[],
    )
    _, _, _, mechanical_base = rr._build_post_subagent_tables("TXN", valuation_out, competitive)
    expected = compute_dcf_scenarios("TXN")["base"].intrinsic_value_per_share
    assert mechanical_base == pytest.approx(expected)


def test_build_post_subagent_tables_mechanical_base_none_when_scenarios_unavailable(monkeypatch):
    monkeypatch.setattr(rr, "compute_dcf_scenarios", lambda ticker: (_ for _ in ()).throw(RuntimeError("boom")))
    competitive = rr.CompetitiveOutput(competitive_analysis="c", industry_outlook="i", strategic_framework_analysis="s")
    valuation_out = rr.ValuationOutput(
        fair_value_low=50.0, fair_value_base=60.0, fair_value_high=70.0,
        valuation_methodology="m", dcf_assessment="d", relative_valuation="r", valuation_risks=[],
    )
    _, _, _, mechanical_base = rr._build_post_subagent_tables("TXN", valuation_out, competitive)
    assert mechanical_base is None


# ---------------------------------------------------------------------------
# ValuationOutput.dcf_reconciliation — literal-backslash-n sanitization
# (regression test for the Phase 6.7 live-check finding: gemini-3.5-flash emitted a literal
# backslash-n in this specific new field while every other field in the same real report
# came back clean)
# ---------------------------------------------------------------------------

def test_valuation_output_sanitizes_dcf_reconciliation():
    v = rr.ValuationOutput(
        fair_value_low=1.0, fair_value_base=2.0, fair_value_high=3.0,
        dcf_reconciliation="line one\\nline two",
        valuation_methodology="m", dcf_assessment="d", relative_valuation="r", valuation_risks=[],
    )
    assert v.dcf_reconciliation == "line one\nline two"
    assert "\\n" not in v.dcf_reconciliation


# ---------------------------------------------------------------------------
# _format_specialist_outputs — new fields present
# ---------------------------------------------------------------------------

def test_format_specialist_outputs_includes_ai_dcf_fields():
    competitive = rr.CompetitiveOutput(competitive_analysis="c", industry_outlook="i", strategic_framework_analysis="s")
    earnings = rr.EarningsTrendOutput(mda_summary="m", earnings_highlights="e", quarterly_trend_analysis="q", near_term_catalysts=[])
    technical = rr.TechnicalOutput(technical_analysis="t", technical_rating="NEUTRAL")
    valuation = rr.ValuationOutput(
        fair_value_low=1.0, fair_value_base=2.0, fair_value_high=3.0,
        ai_dcf_intrinsic_value=62.0, dcf_reconciliation="anchored on AI DCF because X",
        valuation_methodology="m", dcf_assessment="d", relative_valuation="r", valuation_risks=[],
    )
    text = rr._format_specialist_outputs(competitive, earnings, technical, valuation)
    assert "ai_dcf_intrinsic_value" in text
    assert "anchored on AI DCF because X" in text


# ---------------------------------------------------------------------------
# render_to_markdown — dcf_reconciliation placement
# ---------------------------------------------------------------------------

def test_render_to_markdown_includes_reconciliation_when_present():
    header = rr.ResearchHeader(
        company_name="Texas Instruments", ticker="TXN", prepared_date="2026-07-30",
        ai_model="test-model", rating="HOLD", target_low=55.0, target_high=75.0, thesis_summary="t",
    )
    report = rr.EquityResearchReport(
        header=header, key_highlights=[], financial_performance=[], financial_years=[],
        valuation=rr.ValuationSummary(current_price=65.0),
        company_overview="o", competitive_analysis="c", industry_outlook="i",
        strategic_framework_analysis="s", mda_summary="m", risk_factors=[], near_term_catalysts=[],
        earnings_highlights="e", quarterly_trend_analysis="q", technical_analysis="t",
        technical_rating="NEUTRAL", intrinsic_valuation="some intrinsic valuation prose",
        investment_thesis="th",
    )
    md = rr.render_to_markdown(report, dcf_reconciliation="anchored on the AI DCF because Y")
    assert "DCF Reconciliation" in md
    assert "anchored on the AI DCF because Y" in md


def test_render_to_markdown_omits_reconciliation_when_absent():
    header = rr.ResearchHeader(
        company_name="Texas Instruments", ticker="TXN", prepared_date="2026-07-30",
        ai_model="test-model", rating="HOLD", target_low=55.0, target_high=75.0, thesis_summary="t",
    )
    report = rr.EquityResearchReport(
        header=header, key_highlights=[], financial_performance=[], financial_years=[],
        valuation=rr.ValuationSummary(current_price=65.0),
        company_overview="o", competitive_analysis="c", industry_outlook="i",
        strategic_framework_analysis="s", mda_summary="m", risk_factors=[], near_term_catalysts=[],
        earnings_highlights="e", quarterly_trend_analysis="q", technical_analysis="t",
        technical_rating="NEUTRAL", intrinsic_valuation="some intrinsic valuation prose",
        investment_thesis="th",
    )
    md = rr.render_to_markdown(report)
    assert "DCF Reconciliation" not in md


# ---------------------------------------------------------------------------
# Full _run_research_agent — mocked LLM chain, mocked network, real local-DB gather
# ---------------------------------------------------------------------------

class _FakeAgent:
    def __init__(self, name, instructions, model, output_type, model_settings=None):
        self.name = name
        self.output_type = output_type


class _FakeResult:
    def __init__(self, final_output):
        self.final_output = final_output


class _FakeRunner:
    @staticmethod
    async def run(agent, prompt):
        ot = agent.output_type
        if ot is rr.CompetitiveOutput:
            return _FakeResult(rr.CompetitiveOutput(
                competitive_analysis="c", industry_outlook="i", strategic_framework_analysis="s",
            ))
        if ot is rr.EarningsTrendOutput:
            return _FakeResult(rr.EarningsTrendOutput(
                mda_summary="m", earnings_highlights="e", quarterly_trend_analysis="q", near_term_catalysts=[],
            ))
        if ot is rr.TechnicalOutput:
            return _FakeResult(rr.TechnicalOutput(technical_analysis="t", technical_rating="NEUTRAL"))
        if ot is rr.ValuationOutput:
            return _FakeResult(rr.ValuationOutput(
                fair_value_low=50.0, fair_value_base=60.0, fair_value_high=70.0,
                dcf_intrinsic_value=55.0, ai_dcf_intrinsic_value=62.0,
                dcf_reconciliation="anchored on the AI DCF because of cited guidance",
                valuation_methodology="m", dcf_assessment="d", relative_valuation="r",
                valuation_risks=["risk one"],
            ))
        if ot is rr.ChiefCoreOutput:
            return _FakeResult(rr.ChiefCoreOutput(
                header=rr.ResearchHeader(
                    company_name="Texas Instruments", ticker="TXN", prepared_date="2026-07-30",
                    ai_model="test-model", rating="HOLD", target_low=55.0, target_high=75.0,
                    thesis_summary="thesis",
                ),
                key_highlights=["h1"], financial_performance=[], financial_years=[],
                valuation=rr.ValuationSummary(current_price=65.0, upside_pct=15.4),
                risk_factors=["r1"], near_term_catalysts=["c1"],
            ))
        if ot is rr.ChiefNarrativeOutput:
            return _FakeResult(rr.ChiefNarrativeOutput(
                company_overview="o", competitive_analysis="c", industry_outlook="i",
                strategic_framework_analysis="s", mda_summary="m", earnings_highlights="e",
                quarterly_trend_analysis="q", technical_analysis="t", technical_rating="NEUTRAL",
                intrinsic_valuation="chief's own intrinsic valuation narrative",
                investment_thesis="thesis",
            ))
        raise AssertionError(f"unexpected output_type in fake Runner.run: {ot}")


def _patch_llm_chain(monkeypatch):
    monkeypatch.setattr(rr, "Agent", _FakeAgent)
    monkeypatch.setattr(rr, "Runner", _FakeRunner)
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-test")


def _patch_network_calls(monkeypatch):
    """EDGAR/Tavily/AV-transcript-probe calls are network-dependent — canned for a fast,
    deterministic test. Local-DB reads (financials, valuation, technical, peer, DCF summary,
    etc.) run for real against TXN."""
    monkeypatch.setattr(rr, "get_edgar_mda", lambda ticker: "[INFO] MD&A skipped for test")
    monkeypatch.setattr(rr, "get_edgar_risks", lambda ticker: "[INFO] risks skipped for test")
    monkeypatch.setattr(rr, "get_web_search", lambda ticker: "[INFO] web search skipped for test")
    monkeypatch.setattr(rr, "get_market_size_search", lambda ticker: "[INFO] market size skipped for test")
    monkeypatch.setattr(rr, "get_earnings_trend_summary", lambda ticker: "[INFO] transcripts skipped for test")
    monkeypatch.setattr(rr, "get_beat_miss_summary", lambda ticker: "[INFO] beat/miss skipped for test")


@pytest.mark.asyncio
async def test_run_research_agent_with_ai_dcf_success(monkeypatch):
    _patch_llm_chain(monkeypatch)
    _patch_network_calls(monkeypatch)
    fixture_result = _fixture_ai_dcf_result()

    async def _fake_get_or_run_ai_dcf(ticker, model):
        return fixture_result
    monkeypatch.setattr(adr, "get_or_run_ai_dcf", _fake_get_or_run_ai_dcf)

    statuses = []
    key = ("TXN", "test-model")
    monkeypatch.setattr(rr, "_set_status", lambda k, phase, msg, error=None: statuses.append(phase))

    report, findings, valuation_tables_md, direct_competitors_md, market_share_md, dcf_reconciliation, \
        usage_tracker = await rr._run_research_agent("TXN", "test-model", status_key=key)

    assert "running_ai_dcf" in statuses
    assert dcf_reconciliation == "anchored on the AI DCF because of cited guidance"
    assert "DCF (AI-authored)" in valuation_tables_md
    assert "AI vs. Mechanical DCF Assumptions" in valuation_tables_md
    assert findings == []  # ai_dcf_intrinsic_value (62.0) matches the fixture's base (62.0)

    markdown = rr.render_to_markdown(
        report, valuation_tables_md, direct_competitors_md, market_share_md, dcf_reconciliation,
    )
    assert "DCF Reconciliation" in markdown
    assert "DCF (AI-authored)" in markdown


@pytest.mark.asyncio
async def test_run_research_agent_with_ai_dcf_failure_degrades_cleanly(monkeypatch):
    """AI DCF unavailable -> report must still generate, structurally equivalent to pre-feature
    output (no orphaned AI DCF sections, valuation context carries the unavailable note)."""
    _patch_llm_chain(monkeypatch)
    _patch_network_calls(monkeypatch)

    async def _fake_get_or_run_ai_dcf(ticker, model):
        return None
    monkeypatch.setattr(adr, "get_or_run_ai_dcf", _fake_get_or_run_ai_dcf)

    key = ("TXN", "test-model")
    monkeypatch.setattr(rr, "_set_status", lambda k, phase, msg, error=None: None)

    report, findings, valuation_tables_md, direct_competitors_md, market_share_md, dcf_reconciliation, \
        usage_tracker = await rr._run_research_agent("TXN", "test-model", status_key=key)

    assert "DCF (AI-authored)" not in valuation_tables_md
    assert "AI vs. Mechanical DCF Assumptions" not in valuation_tables_md
    assert findings == []

    markdown = rr.render_to_markdown(
        report, valuation_tables_md, direct_competitors_md, market_share_md, dcf_reconciliation,
    )
    assert "DCF (AI-authored)" not in markdown
