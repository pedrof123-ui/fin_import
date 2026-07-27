"""
FastAPI router for the Industry AI Researcher.

Phase 2 (features/industry_research/PLAN.md) added the deterministic markdown appendix tables +
the ranked-ideas numeric join — rendered here in Python, never by an LLM, so the numbers in the
report can never drift from what the underlying models actually computed (same design as
research_router.py's render_valuation_model_tables).

Phase 3 added the Stage-1 map: a per-company Earnings Digest sub-agent, fanned out in parallel
over an industry's members.

Phase 4 added Stage 2 (Trends & Developments / Risks & Outlook specialists, parallel), Stage 3
(Chief Industry Strategist synthesis), deterministic QC checks, and the final markdown renderer.

Phase 5 adds the end-to-end orchestrator (`_run_industry_research`), a DuckDB report cache,
background-task/status/cancel scaffolding, and HTTP endpoints — structurally mirroring
research_router.py's equivalent pieces, but keyed by `industry_data.scope_key()` (industry name
or a stable hash of a custom ticker basket) instead of a single ticker.

Every renderer/fan-out function here takes ALREADY-FETCHED data (industry_data.py's `*_raw` /
`*_df` functions) as input and does no DB/network access of its own — see PLAN.md's Phase 1
finding: a function that independently re-fetched EPS surprises would double Alpha Vantage calls
for the same tickers in one report generation pass (CLAUDE.md rule 7).
"""

from __future__ import annotations

import asyncio
import logging
import os
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

import duckdb
import pandas as pd
from fastapi import APIRouter, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel
from agents import Agent, OpenAIChatCompletionsModel, Runner

import api.industry_data as ind
from api.industry_data import format_estimates, format_member_financials, is_missing
from api.research_router import _DEFAULT_MODEL, _MODEL_OPTIONS, _STYLE_GUIDE, _load_prompt, _md_table

log = logging.getLogger(__name__)

router = APIRouter()

_DATA_DIR = Path(__file__).parent.parent / "data"
_INDUSTRY_RESEARCH_DB = _DATA_DIR / "industry_research_cache.duckdb"
_CACHE_TTL_HOURS = 24

_LLM_TIMEOUT = 400  # same ceiling as the single-name researcher (research_router._LLM_TIMEOUT) —
                    # well above the slowest observed real call, catches a genuine provider stall
                    # rather than hanging the whole fan-out indefinitely.
_MAX_TRANSCRIPT_CHARS = 7000  # per quarter, matches research_router._MAX_TRANSCRIPT_CHARS


# ---------------------------------------------------------------------------
# Formatting helpers (module-local, mirrors the pattern in every other router file)
# ---------------------------------------------------------------------------

def _f(v, fmt: str = ".1f") -> str:
    if is_missing(v):
        return "n/a"
    return f"{float(v):{fmt}}"


def _pct(v, fmt: str = "+.1f") -> str:
    if is_missing(v):
        return "n/a"
    return f"{float(v) * 100:{fmt}}%"


def _rev_pct(a, b) -> str:
    if is_missing(a) or is_missing(b) or float(b) == 0:
        return "n/a"
    return f"{(float(a) - float(b)) / abs(float(b)) * 100:+.1f}%"


# LLM text sanitization — found live: gemini-3.5-flash occasionally emits the literal two-
# character sequence backslash-n inside a structured-output string field instead of an actual
# newline (a JSON-generation quirk, not a parsing bug — confirmed via repr() on a real
# TrendsOutput response). Left unsanitized, this renders as visible "\n" text in the frontend's
# markdown viewer instead of a line break.

def _sanitize_prose(text: str) -> str:
    """For free-flowing prose sections: convert a literal backslash-n into a real newline so
    bold-header bullet clusters actually break onto new lines."""
    return text.replace("\\n", "\n")


def _sanitize_table_cell(text: str) -> str:
    """For markdown table cells: a raw newline would break the table's row structure, so
    collapse both the literal-backslash-n quirk and any genuine newline to a single space."""
    return text.replace("\\n", " ").replace("\n", " ")


# ---------------------------------------------------------------------------
# Ranked-ideas schema (Stage 3 chief output — formally introduced in Phase 4; defined here
# because Phase 2's attach_idea_metrics needs the type, and every Pydantic schema in the
# single-name researcher lives in its router file too)
# ---------------------------------------------------------------------------

class IndustryIdea(BaseModel):
    ticker: str
    stance: Literal["OVERWEIGHT", "NEUTRAL", "UNDERWEIGHT"]
    catalyst: str
    key_risk: str


# ---------------------------------------------------------------------------
# Stage 1 — MAP: per-company Earnings Digest sub-agent
# ---------------------------------------------------------------------------

class CompanyDigest(BaseModel):
    ticker: str
    demand: str
    pricing_margins: str
    guidance_direction: Literal["RAISED", "MAINTAINED", "LOWERED", "UNCLEAR"]
    capex_investment: str
    management_tone: Literal["BULLISH", "NEUTRAL", "CAUTIOUS"]
    notable_quotes: list[str]
    company_risks: list[str]

    # No numeric fields on this schema (SPEC 6.5 anticipated some, but the final field set is
    # all str/Literal/list[str]) — so no _coerce_optional_float-style validator is needed here.


def _build_digest_context(
    ticker: str,
    quarters: list[tuple[str, str]],
    beat_miss_raw: dict[str, Optional[list[dict]]],
    financials_row,
) -> str:
    """Per-company context text for the Stage-1 digest prompt: transcripts + latest beat/miss +
    a one-line financial snapshot. Caller (run_company_digests) only invokes this for tickers
    with >=1 cached transcript quarter — members with zero are skipped before this is ever
    called (SPEC 6.4's "contributes no digest" degrade path)."""
    blocks = [f"--- EARNINGS TRANSCRIPTS — {ticker} ({len(quarters)} quarters, newest first) ---", ""]
    for q, text in quarters:
        blocks.append(f"[{q}]\n{text[:_MAX_TRANSCRIPT_CHARS]}")
    transcripts_block = "\n\n".join(blocks)

    surprise_rows = beat_miss_raw.get(ticker)
    if surprise_rows:
        surprise = surprise_rows[0].get("surprise_pct")
        beat_miss_block = (
            f"EPS BEAT/MISS — latest quarter surprise "
            f"{f'{surprise:+.1f}%' if surprise is not None else 'n/a'}"
        )
    else:
        beat_miss_block = "EPS BEAT/MISS — no data"

    if financials_row is not None:
        fin_block = (
            f"FINANCIALS SNAPSHOT — Mkt Cap ${_f(financials_row.get('market_cap_b'))}B, "
            f"P/E {_f(financials_row.get('current_pe'))}, "
            f"Rev Growth {_pct(financials_row.get('rev_growth_1yr'))}, "
            f"Earn Growth {_pct(financials_row.get('earn_growth_1yr'))}"
        )
    else:
        fin_block = "FINANCIALS SNAPSHOT — not available"

    return f"{transcripts_block}\n\n{beat_miss_block}\n\n{fin_block}"


async def _run_digest_subagent(ticker: str, context: str, model: str, llm) -> Optional[CompanyDigest]:
    """One Stage-1 sub-agent call. Returns None (never raises) on timeout or any provider
    error — the caller treats a None the same as a skipped member, so a single bad call can
    never take down the rest of the fan-out. Extracted as a standalone module-level function
    (not a closure) so tests can monkeypatch it directly instead of mocking the full
    Agent/Runner/OpenAIChatCompletionsModel chain."""
    instructions = (
        _load_prompt("industry_company_digest.md")
        .replace("{style_guide}", _STYLE_GUIDE)
        .replace("{ticker}", ticker.upper())
        .replace("{date}", datetime.now().strftime("%Y-%m-%d"))
        .replace("{context}", context)
    )
    agent = Agent(
        name=f"company_digest_{ticker.lower()}", instructions=instructions, model=llm,
        output_type=CompanyDigest,
    )
    try:
        result = await asyncio.wait_for(
            Runner.run(agent, f"Produce the digest for {ticker.upper()}."), timeout=_LLM_TIMEOUT,
        )
        return result.final_output
    except asyncio.TimeoutError:
        log.error("[%s] industry digest: sub-agent timed out after %ds", ticker, _LLM_TIMEOUT)
        return None
    except Exception as e:
        log.error("[%s] industry digest: sub-agent failed: %s", ticker, e)
        return None


async def run_company_digests(
    tickers: list[str],
    transcripts: dict[str, list[tuple[str, str]]],
    beat_miss_raw: dict[str, Optional[list[dict]]],
    financials_df: pd.DataFrame,
    model: str,
    llm=None,
) -> dict[str, CompanyDigest]:
    """Runs the Stage-1 map: one Earnings Digest sub-agent per member with cached transcript
    data, in parallel via asyncio.gather. Members with zero transcript quarters (e.g. TSM, an
    ADR not covered by AV's EARNINGS_CALL_TRANSCRIPT — a real case found in Phase 0) are skipped
    entirely: no LLM call, no digest, consistent with SPEC 6.4. A member whose sub-agent call
    fails or times out is likewise simply absent from the result — never raises, never blocks
    the rest of the batch.

    `llm` is normally built internally from `model` + OPENROUTER_API_KEY; tests may pass a dummy
    object to bypass that (and monkeypatch _run_digest_subagent) for a pure unit test with no
    network/env dependency.
    """
    fin_by_ticker = (
        {r["ticker"]: r for _, r in financials_df.iterrows()} if not financials_df.empty else {}
    )
    eligible = [t for t in tickers if transcripts.get(t)]
    if not eligible:
        return {}

    if llm is None:
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        if not openrouter_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)
        llm = OpenAIChatCompletionsModel(model=model, openai_client=client)

    async def _one(t: str):
        context = _build_digest_context(t, transcripts[t], beat_miss_raw, fin_by_ticker.get(t))
        digest = await _run_digest_subagent(t, context, model, llm)
        return t, digest

    results = await asyncio.gather(*[_one(t) for t in eligible])
    return {t: d for t, d in results if d is not None}


# ---------------------------------------------------------------------------
# Deterministic appendix tables
# ---------------------------------------------------------------------------

def render_industry_aggregates_table(raw: Optional[dict]) -> str:
    """Industry valuation/margin/growth medians + 3/6/12-month deltas. Takes
    industry_data.get_industry_aggregates_raw(industry)'s output directly — no re-query."""
    if raw is None:
        return ""
    r, deltas = raw["current"], raw["deltas"]

    rows = [
        ["P/E median", _f(r["pe_median"])],
        ["P/FCF median", _f(r["pfcf_median"])],
        ["EV/EBITDA median", _f(r["evebitda_median"])],
        ["P/S median", _f(r["ps_median"])],
        ["Revenue growth 1yr", _pct(r["rev_growth_1yr_median"])],
        ["Earnings growth 1yr", _pct(r["earn_growth_1yr_median"])],
        ["Gross margin", _pct(r["gross_margin_median"])],
        ["Operating margin", _pct(r["operating_margin_median"])],
        ["FCF margin", _pct(r["fcf_margin_median"])],
        ["ROIC median", _pct(r["roic_median"])],
        ["ROE median", _pct(r["roe_median"])],
        ["Debt/EBITDA median", _f(r["debt_to_ebitda_median"])],
    ]
    lines = [
        f"#### Industry Aggregates — {r['group_name']} "
        f"(as of {str(r['month_end_date'])[:7]}, {int(r['ticker_count'])} tickers measured)",
        "",
    ]
    lines += _md_table(["Metric", "Value"], rows)

    delta_rows = []
    for months, label in [(3, "3mo"), (6, "6mo"), (12, "12mo")]:
        prior = deltas[months]
        if not prior:
            delta_rows.append([label, "n/a", "n/a", "n/a"])
            continue
        p_pe, p_ev, p_gr = prior
        pe_chg = (
            f"{(float(r['pe_median']) / float(p_pe) - 1) * 100:+.1f}%"
            if not is_missing(r["pe_median"]) and p_pe else "n/a"
        )
        ev_chg = (
            f"{(float(r['evebitda_median']) / float(p_ev) - 1) * 100:+.1f}%"
            if not is_missing(r["evebitda_median"]) and p_ev else "n/a"
        )
        gr_chg = (
            f"{(float(r['rev_growth_1yr_median']) - float(p_gr)) * 100:+.1f}pp"
            if not is_missing(r["rev_growth_1yr_median"]) and p_gr is not None else "n/a"
        )
        delta_rows.append([label, pe_chg, ev_chg, gr_chg])

    lines += ["", "#### Industry Trend", ""]
    lines += _md_table(["Period", "P/E Change", "EV/EBITDA Change", "Rev Growth Change"], delta_rows)
    return "\n".join(lines)


def render_member_financials_table(df: pd.DataFrame) -> str:
    """Cross-company financials appendix table. Takes
    industry_data.get_member_financials_df(tickers)'s output directly — no re-query."""
    if df.empty:
        return ""
    rows = [
        [
            str(r["ticker"]), str(r["name"] or "")[:25], _f(r["market_cap_b"]),
            _f(r["current_pe"]), _f(r["forward_pe"]), _f(r["current_pfcf"]),
            _pct(r["rev_growth_1yr"]), _pct(r["earn_growth_1yr"]),
            _pct(r["current_roic"]), _pct(r["current_gross_margin"]),
        ]
        for _, r in df.iterrows()
    ]
    lines = ["#### Member Financials", ""]
    lines += _md_table(
        ["Ticker", "Company", "Mkt Cap $B", "P/E", "Fwd P/E", "P/FCF",
         "Rev Gr", "Earn Gr", "ROIC", "Gross Margin"],
        rows,
    )
    return "\n".join(lines)


def render_beat_miss_table(tickers: list[str], raw: dict[str, Optional[list[dict]]]) -> str:
    """Per-member EPS surprise + dispersion footer. Takes
    industry_data.get_beat_miss_raw(tickers)'s output directly — no re-fetch from AV."""
    if not tickers:
        return ""
    rows = []
    surprises: list[float] = []
    for t in tickers:
        member_rows = raw.get(t)
        if not member_rows:
            rows.append([t, "n/a", "n/a"])
            continue
        latest = member_rows[0]
        surprise = latest.get("surprise_pct")
        if surprise is not None:
            surprises.append(float(surprise))
        rows.append([
            t,
            f"{surprise:+.1f}%" if surprise is not None else "n/a",
            str(latest.get("fiscal_date_ending"))[:10],
        ])
    lines = ["#### EPS Beat/Miss (Latest Quarter)", ""]
    lines += _md_table(["Ticker", "Surprise %", "Fiscal Quarter End"], rows)
    if surprises:
        n_beat = sum(1 for s in surprises if s > 0)
        lines += [
            "",
            f"*Dispersion: {n_beat}/{len(surprises)} members beat estimates last quarter "
            f"(median surprise {statistics.median(surprises):+.1f}%).*",
        ]
    return "\n".join(lines)


def render_revision_momentum_table(tickers: list[str], df: pd.DataFrame) -> str:
    """Per-member forward EPS estimate + revision momentum. Takes
    industry_data.get_estimates_df(tickers)'s output directly — no re-query."""
    if not tickers:
        return ""
    rows_by_ticker = {r["ticker"]: r for _, r in df.iterrows()} if not df.empty else {}
    rows = []
    for t in tickers:
        r = rows_by_ticker.get(t)
        if r is None:
            rows.append([t, "n/a", "n/a", "n/a"])
            continue
        eps_txt = "n/a" if is_missing(r["eps_avg"]) else f"${float(r['eps_avg']):.2f}"
        vs30 = _rev_pct(r["eps_avg"], r["eps_avg_30d"])
        up = 0 if is_missing(r["eps_rev_up_7d"]) else int(r["eps_rev_up_7d"])
        dn = 0 if is_missing(r["eps_rev_down_7d"]) else int(r["eps_rev_down_7d"])
        rows.append([t, eps_txt, vs30, f"{up}up/{dn}dn"])
    lines = ["#### Estimate Revision Momentum (Next Fiscal Quarter)", ""]
    lines += _md_table(["Ticker", "EPS Est.", "vs 30d", "Revisions (7d)"], rows)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ranked-ideas numeric join — the LLM proposes ticker/stance/catalyst/key_risk; every number
# here comes from the DB, never from the LLM (SPEC 5.9, 6.6).
# ---------------------------------------------------------------------------

def attach_idea_metrics(
    ideas: list[IndustryIdea],
    financials_df: pd.DataFrame,
    industry_pe_median: Optional[float],
    estimates_df: pd.DataFrame,
) -> list[list[str]]:
    """Joins LLM-proposed ideas to real fundamentals. Returns row lists ready for _md_table:
    [ticker, stance, catalyst, key_risk, valuation_vs_industry, revision_momentum]. A proposed
    ticker absent from either DataFrame renders "n/a" for the affected columns — never raises."""
    fin_by_ticker = (
        {r["ticker"]: r for _, r in financials_df.iterrows()} if not financials_df.empty else {}
    )
    est_by_ticker = (
        {r["ticker"]: r for _, r in estimates_df.iterrows()} if not estimates_df.empty else {}
    )

    rows = []
    for idea in ideas:
        t = idea.ticker.upper()
        fin = fin_by_ticker.get(t)
        est = est_by_ticker.get(t)

        if fin is not None and not is_missing(fin["current_pe"]) and industry_pe_median:
            pe = float(fin["current_pe"])
            diff_pct = (pe / float(industry_pe_median) - 1) * 100
            valuation_txt = f"{pe:.1f}x vs {float(industry_pe_median):.1f}x ({diff_pct:+.0f}%)"
        else:
            valuation_txt = "n/a"

        if est is not None:
            up = 0 if is_missing(est["eps_rev_up_7d"]) else int(est["eps_rev_up_7d"])
            dn = 0 if is_missing(est["eps_rev_down_7d"]) else int(est["eps_rev_down_7d"])
            revision_txt = f"{up}up/{dn}dn (7d)"
        else:
            revision_txt = "n/a"

        rows.append([
            t, idea.stance, _sanitize_table_cell(idea.catalyst), _sanitize_table_cell(idea.key_risk),
            valuation_txt, revision_txt,
        ])
    return rows


# ---------------------------------------------------------------------------
# Stage 2 — REDUCE: industry specialist sub-agents (Trends & Developments, Risks & Outlook)
# ---------------------------------------------------------------------------

class TrendsOutput(BaseModel):
    industry_state_trends: str
    demand_pricing_margin_signals: str
    capital_cycle_competitive_dynamics: str


class RisksOutput(BaseModel):
    risks_headwinds: str
    forward_outlook: str


# ---------------------------------------------------------------------------
# Stage 3 — SYNTHESIZE: Chief Industry Strategist
# ---------------------------------------------------------------------------

class ChiefOutput(BaseModel):
    executive_summary: list[str]
    ranked_ideas: list[IndustryIdea]

    # Deliberately does NOT restate header metadata (industry, members, quarters covered, date,
    # model) or the Stage-2 specialists' narrative sections — Python already has the former, and
    # re-running the latter through a 3rd LLM call would risk drift from what Stage 2 actually
    # said. Keeping this schema to 2 fields also comfortably avoids the Anthropic compiled-
    # grammar size limit that forced a core/narrative split in the single-name researcher's Chief
    # (~5,657 JSON-schema chars there vs. an IndustryIdea-based schema here, structurally similar
    # in size to that researcher's smallest sub-agent schemas) — no split needed.


@dataclass
class ReportHeader:
    industry_label: str
    members: list[str]
    quarters_covered: int
    prepared_date: str
    model: str


def _format_digests_for_prompt(digests: dict[str, CompanyDigest]) -> str:
    if not digests:
        return "[INFO] No per-company digests available (no member had cached transcript data)."
    blocks = []
    for ticker, d in digests.items():
        blocks.append(
            f"--- DIGEST — {ticker} ---\n"
            f"demand: {d.demand}\n"
            f"pricing_margins: {d.pricing_margins}\n"
            f"guidance_direction: {d.guidance_direction}\n"
            f"capex_investment: {d.capex_investment}\n"
            f"management_tone: {d.management_tone}\n"
            f"notable_quotes: {'; '.join(d.notable_quotes) if d.notable_quotes else 'none'}\n"
            f"company_risks: {'; '.join(d.company_risks) if d.company_risks else 'none'}"
        )
    return "\n\n".join(blocks)


async def _run_stage_agent(
    name: str, prompt_name: str, context: str, output_type, llm,
    extra: Optional[dict[str, str]] = None,
):
    """One Stage 2/3 sub-agent call (not a fan-out — one call per stage). Returns None (never
    raises) on timeout or provider error, same never-raise contract as _run_digest_subagent, so a
    single stage failing degrades the final report rather than crashing the whole pipeline."""
    instructions = (
        _load_prompt(prompt_name)
        .replace("{style_guide}", _STYLE_GUIDE)
        .replace("{date}", datetime.now().strftime("%Y-%m-%d"))
        .replace("{context}", context)
    )
    for key, val in (extra or {}).items():
        instructions = instructions.replace(key, val)
    agent = Agent(name=name, instructions=instructions, model=llm, output_type=output_type)
    try:
        result = await asyncio.wait_for(Runner.run(agent, "Produce your section."), timeout=_LLM_TIMEOUT)
        return result.final_output
    except asyncio.TimeoutError:
        log.error("industry %s: sub-agent timed out after %ds", name, _LLM_TIMEOUT)
        return None
    except Exception as e:
        log.error("industry %s: sub-agent failed: %s", name, e)
        return None


async def run_industry_synthesis(
    industry_label: str,
    members: list[str],
    digests: dict[str, CompanyDigest],
    aggregates_text: str,
    web_search_text: str,
    financials_df: pd.DataFrame,
    estimates_df: pd.DataFrame,
    model: str,
    llm=None,
) -> tuple[Optional[TrendsOutput], Optional[RisksOutput], Optional[ChiefOutput]]:
    """Runs Stage 2 (Trends + Risks, parallel) then Stage 3 (Chief, sequential — needs Stage 2's
    output). Any stage that fails/times out returns None for that slot rather than raising;
    render_industry_report degrades gracefully per missing piece. `llm` may be pre-built and
    injected for testing (bypasses the OPENROUTER_API_KEY requirement), same pattern as
    run_company_digests."""
    if llm is None:
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        if not openrouter_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)
        llm = OpenAIChatCompletionsModel(model=model, openai_client=client)

    digests_text = _format_digests_for_prompt(digests)
    member_financials_text = format_member_financials(financials_df)
    shared_context = (
        f"=== INDUSTRY: {industry_label} ({len(members)} companies analyzed: "
        f"{', '.join(members)}) ===\n\n"
        f"=== QUANTITATIVE AGGREGATES ===\n{aggregates_text}\n\n"
        f"=== PER-COMPANY DIGESTS ({len(digests)}/{len(members)} companies have transcript "
        f"data) ===\n{digests_text}\n\n"
        f"=== WEB SEARCH — INDUSTRY TRENDS ===\n{web_search_text}"
    )
    extra = {"{industry}": industry_label, "{n_members}": str(len(members))}

    trends, risks = await asyncio.gather(
        _run_stage_agent("trends_developments_analyst", "industry_trends.md", shared_context,
                          TrendsOutput, llm, extra),
        _run_stage_agent("risks_outlook_analyst", "industry_risks.md", shared_context,
                          RisksOutput, llm, extra),
    )

    chief_context = (
        f"{shared_context}\n\n"
        f"=== TRENDS & DEVELOPMENTS ANALYST ===\n"
        f"{trends.model_dump_json(indent=2) if trends else '[ERROR] Trends analyst unavailable'}\n\n"
        f"=== RISKS & OUTLOOK ANALYST ===\n"
        f"{risks.model_dump_json(indent=2) if risks else '[ERROR] Risks analyst unavailable'}\n\n"
        f"=== MEMBER FINANCIALS (ranked_ideas must use ONLY these tickers) ===\n"
        f"{member_financials_text}\n\n"
        f"=== ESTIMATE REVISIONS ===\n{format_estimates(members, estimates_df)}"
    )
    chief = await _run_stage_agent(
        "chief_industry_strategist", "industry_chief.md", chief_context, ChiefOutput, llm, extra,
    )

    return trends, risks, chief


# ---------------------------------------------------------------------------
# Deterministic QC (non-blocking — findings are logged/footnoted, never block generation, same
# pattern as research_router._validate_report)
# ---------------------------------------------------------------------------

def build_coverage_note(members: list[str], transcripts: dict[str, list[tuple[str, str]]]) -> Optional[str]:
    """Flags when fewer than all members had cached transcript data — the qualitative synthesis
    (digests, Trends/Risks/Chief) is based on a subset even though the quantitative appendix
    covers every member. Returns None when coverage is complete."""
    missing = [t for t in members if not transcripts.get(t)]
    if not missing:
        return None
    return (
        f"Coverage note: {len(missing)}/{len(members)} members had no cached earnings transcript "
        f"({', '.join(missing)}) and are reflected only in the quantitative appendix, not the "
        f"qualitative digest synthesis."
    )


def validate_ranked_ideas(ideas: list[IndustryIdea], members: list[str]) -> list[str]:
    """Deterministic coherence checks on the Chief's ranked_ideas, mirroring
    research_router._validate_report's non-blocking QC pattern: findings are logged/footnoted,
    never used to reject the report."""
    findings: list[str] = []
    member_set = {m.upper() for m in members}
    idea_tickers = [idea.ticker.upper() for idea in ideas]

    invented = sorted(set(idea_tickers) - member_set)
    if invented:
        findings.append(f"ranked_ideas included ticker(s) not in the member list: {', '.join(invented)}")

    missing = sorted(member_set - set(idea_tickers))
    if missing:
        findings.append(f"ranked_ideas is missing entries for member(s): {', '.join(missing)}")

    duplicates = sorted({t for t in idea_tickers if idea_tickers.count(t) > 1})
    if duplicates:
        findings.append(f"ranked_ideas has duplicate entries for ticker(s): {', '.join(duplicates)}")

    return findings


# ---------------------------------------------------------------------------
# Final report assembly — Python-authored structure/tables + LLM-authored prose spliced in;
# mirrors research_router.render_to_markdown's separation of concerns.
# ---------------------------------------------------------------------------

def render_industry_report(
    header: ReportHeader,
    trends: Optional[TrendsOutput],
    risks: Optional[RisksOutput],
    executive_summary: list[str],
    ranked_ideas_rows: list[list[str]],
    aggregates_table_md: str,
    member_financials_table_md: str,
    beat_miss_table_md: str,
    revision_momentum_table_md: str,
    coverage_note: Optional[str] = None,
    qc_findings: Optional[list[str]] = None,
) -> str:
    lines: list[str] = [
        f"# {header.industry_label} — Industry Research Report",
        "",
        f"**Members analyzed:** {', '.join(header.members)}  |  "
        f"**Quarters covered:** up to {header.quarters_covered}",
        f"**Prepared:** {header.prepared_date}  |  **Model:** {header.model}",
        "",
    ]
    if coverage_note:
        lines += [f"> {coverage_note}", ""]
    lines += ["---", ""]

    lines += ["## Executive Summary", ""]
    for pt in executive_summary:
        lines.append(f"- {_sanitize_prose(pt)}")
    lines += ["", "---", ""]

    lines += ["## Industry State & Secular Trends", ""]
    lines.append(
        _sanitize_prose(trends.industry_state_trends) if trends
        else "[ERROR] Trends & Developments analyst unavailable"
    )
    lines += ["", "---", ""]

    lines += ["## Demand, Pricing & Margin Signals", ""]
    lines.append(
        _sanitize_prose(trends.demand_pricing_margin_signals) if trends
        else "[ERROR] Trends & Developments analyst unavailable"
    )
    lines += ["", "---", ""]

    lines += ["## Capital Cycle & Competitive Dynamics", ""]
    lines.append(
        _sanitize_prose(trends.capital_cycle_competitive_dynamics) if trends
        else "[ERROR] Trends & Developments analyst unavailable"
    )
    lines += ["", "---", ""]

    lines += ["## Risks & Headwinds", ""]
    lines.append(
        _sanitize_prose(risks.risks_headwinds) if risks else "[ERROR] Risks & Outlook analyst unavailable"
    )
    lines += ["", "---", ""]

    lines += ["## Forward Outlook", ""]
    lines.append(
        _sanitize_prose(risks.forward_outlook) if risks else "[ERROR] Risks & Outlook analyst unavailable"
    )
    lines += ["", "---", ""]

    lines += ["## Quantitative Appendix", ""]
    for block in (aggregates_table_md, member_financials_table_md, beat_miss_table_md, revision_momentum_table_md):
        if block:
            lines += [block, ""]
    lines += ["---", ""]

    lines += ["## Ranked Actionable Ideas", ""]
    if ranked_ideas_rows:
        lines += _md_table(
            ["Ticker", "Stance", "Catalyst", "Key Risk", "Valuation vs Industry", "Revision Momentum"],
            ranked_ideas_rows,
        )
    else:
        lines.append("[ERROR] Chief Industry Strategist unavailable")
    lines += ["", "---", ""]

    if qc_findings:
        lines.append(f"*QC: {len(qc_findings)} inconsistency(ies) detected — " + "; ".join(qc_findings) + "*")

    lines.append(
        f"*Report prepared by {header.model} on {header.prepared_date}. Ranked ideas are relative "
        "views within this industry, not absolute valuation calls or a validated trading signal. "
        "For informational purposes only. Not investment advice.*"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# End-to-end orchestrator — resolve -> gather -> Stage 1 -> Stage 2/3 -> render
# ---------------------------------------------------------------------------

_DB_TIMEOUT = 15
_TRANSCRIPTS_TIMEOUT = 90  # up to MEMBERS_CAP tickers x several AV probes worst case
_BEAT_MISS_TIMEOUT = 30
_TAVILY_TIMEOUT = 20


async def _run_industry_research(
    industry: Optional[str],
    custom_tickers: Optional[list[str]],
    model: str,
    status_key: Optional[tuple[str, str]] = None,
) -> str:
    """Full pipeline for one report: resolve members -> gather data (parallel) -> Stage 1 digests
    (parallel fan-out) -> Stage 2/3 synthesis (specialists parallel, then chief) -> deterministic
    QC + render. Raises on a resolution failure (no members); every LLM stage degrades to an
    [ERROR] placeholder in the rendered report rather than raising (see run_company_digests /
    run_industry_synthesis's never-raise contracts)."""
    loop = asyncio.get_event_loop()
    t0 = datetime.now()

    members = ind.resolve_members(industry, custom_tickers, cap=ind.MEMBERS_CAP)
    if not members:
        raise RuntimeError(f"No members resolved for industry={industry!r} tickers={custom_tickers!r}")

    industry_label = industry.strip() if industry else f"Custom basket ({', '.join(members)})"
    log.info("industry research [%s]: resolved %d members (model=%s)", industry_label, len(members), model)

    if status_key:
        _set_status(status_key, "gathering_data",
                    f"Gathering data for {len(members)} companies in {industry_label}...")

    async def _run(fn, *args, timeout):
        return await asyncio.wait_for(loop.run_in_executor(None, lambda: fn(*args)), timeout=timeout)

    transcripts_task = _run(ind.get_industry_transcripts, members, ind.N_QUARTERS, timeout=_TRANSCRIPTS_TIMEOUT)
    beat_miss_task = _run(ind.get_beat_miss_raw, members, timeout=_BEAT_MISS_TIMEOUT)
    fin_df_task = _run(ind.get_member_financials_df, members, timeout=_DB_TIMEOUT)
    est_df_task = _run(ind.get_estimates_df, members, timeout=_DB_TIMEOUT)

    if industry:
        agg_raw_task = _run(ind.get_industry_aggregates_raw, industry, timeout=_DB_TIMEOUT)
        web_task = _run(ind.get_industry_web_search, industry, timeout=_TAVILY_TIMEOUT)
    else:
        # Custom ticker basket: no single industry classification to aggregate against or
        # search for (SPEC 2.1 — a custom basket is the escape hatch for over-broad/narrow
        # industries, it never re-derives an industry label from the tickers).
        async def _none():
            return None

        async def _no_web():
            return "[INFO] Custom ticker basket — no single industry classification to search against."

        agg_raw_task, web_task = _none(), _no_web()

    transcripts, beat_miss_raw, fin_df, est_df, agg_raw, web_text = await asyncio.gather(
        transcripts_task, beat_miss_task, fin_df_task, est_df_task, agg_raw_task, web_task,
    )

    if status_key:
        _set_status(status_key, "digesting_companies",
                    f"Summarizing earnings calls for {len(members)} companies...")
    digests = await run_company_digests(members, transcripts, beat_miss_raw, fin_df, model)
    log.info("industry research [%s]: %d/%d members have digests", industry_label, len(digests), len(members))

    if status_key:
        _set_status(status_key, "running_specialists",
                    "Running industry specialists and chief strategist...")
    agg_text = ind.format_industry_aggregates(agg_raw)
    trends, risks, chief = await run_industry_synthesis(
        industry_label, members, digests, agg_text, web_text, fin_df, est_df, model,
    )

    if status_key:
        _set_status(status_key, "synthesizing", "Assembling final report...")

    qc_findings = validate_ranked_ideas(chief.ranked_ideas, members) if chief else []
    if qc_findings:
        log.warning("industry research [%s]: QC found %d issue(s): %s",
                    industry_label, len(qc_findings), qc_findings)
    coverage_note = build_coverage_note(members, transcripts)
    industry_pe_median = (
        agg_raw["current"].get("pe_median") if agg_raw is not None else None
    )
    ranked_ideas_rows = (
        attach_idea_metrics(chief.ranked_ideas, fin_df, industry_pe_median, est_df) if chief else []
    )
    executive_summary = chief.executive_summary if chief else []

    header = ReportHeader(
        industry_label=industry_label, members=members, quarters_covered=ind.N_QUARTERS,
        prepared_date=datetime.now().strftime("%Y-%m-%d"), model=model,
    )
    markdown = render_industry_report(
        header, trends, risks, executive_summary, ranked_ideas_rows,
        render_industry_aggregates_table(agg_raw),
        render_member_financials_table(fin_df),
        render_beat_miss_table(members, beat_miss_raw),
        render_revision_momentum_table(members, est_df),
        coverage_note=coverage_note,
        qc_findings=qc_findings,
    )
    log.info("industry research [%s]: done in %.1fs", industry_label,
             (datetime.now() - t0).total_seconds())
    return markdown


# ---------------------------------------------------------------------------
# DuckDB cache (24h TTL, keyed by scope_key + model — mirrors research_router's ticker+model cache)
# ---------------------------------------------------------------------------

def _init_cache():
    _INDUSTRY_RESEARCH_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(_INDUSTRY_RESEARCH_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS industry_research_cache (
            scope_key       VARCHAR,
            model           VARCHAR,
            report_markdown VARCHAR,
            generated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (scope_key, model)
        )
    """)
    conn.close()


def _cache_get(scope_key: str, model: str) -> Optional[str]:
    if not _INDUSTRY_RESEARCH_DB.exists():
        return None
    conn = duckdb.connect(str(_INDUSTRY_RESEARCH_DB), read_only=True)
    row = conn.execute(
        "SELECT report_markdown, generated_at FROM industry_research_cache "
        "WHERE scope_key = ? AND model = ?",
        [scope_key, model],
    ).fetchone()
    conn.close()
    if not row:
        return None
    generated_at = row[1]
    if isinstance(generated_at, str):
        generated_at = datetime.fromisoformat(generated_at)
    if datetime.now() - generated_at > timedelta(hours=_CACHE_TTL_HOURS):
        return None
    return row[0]


def _cache_put(scope_key: str, model: str, markdown: str):
    _init_cache()
    conn = duckdb.connect(str(_INDUSTRY_RESEARCH_DB))
    conn.execute("""
        INSERT INTO industry_research_cache (scope_key, model, report_markdown, generated_at)
        VALUES (?, ?, ?, now())
        ON CONFLICT (scope_key, model) DO UPDATE SET
            report_markdown = excluded.report_markdown,
            generated_at    = excluded.generated_at
    """, [scope_key, model, markdown])
    conn.close()


# ---------------------------------------------------------------------------
# Background task registry + live status (mirrors research_router's polling/cancel UX)
# ---------------------------------------------------------------------------

_background_tasks: dict[tuple[str, str], asyncio.Task] = {}
_task_status: dict[tuple[str, str], dict] = {}

_GENERATING_MD = (
    "## Generating Industry Research Report...\n\n"
    "Gathering financials, earnings transcripts, and industry aggregates for multiple companies, "
    "then running AI analysis.\nThis takes approximately 60-150 seconds depending on how many "
    "companies are in scope."
)


def _set_status(key: tuple[str, str], phase: str, message: str, error: Optional[str] = None) -> None:
    _task_status[key] = {"phase": phase, "message": message, "error": error}


async def _background_generate(
    scope_key: str, industry: Optional[str], custom_tickers: Optional[list[str]], model: str,
) -> None:
    key = (scope_key, model)
    log.info("industry research: background task started (scope=%s model=%s)", scope_key, model)
    try:
        markdown = await _run_industry_research(industry, custom_tickers, model, status_key=key)
        _cache_put(scope_key, model, markdown)
        _set_status(key, "done", "Report ready.")
        log.info("industry research: report cached (scope=%s, %d chars)", scope_key, len(markdown))
    except Exception as e:
        log.error("industry research: background task failed (scope=%s model=%s): %s", scope_key, model, e)
        _set_status(key, "error", f"Report generation failed: {e}", error=str(e))
    finally:
        _background_tasks.pop(key, None)


def _get_or_start(
    industry: Optional[str], custom_tickers: Optional[list[str]], model: str, retry: bool = False,
) -> str:
    scope_key = ind.scope_key(industry, custom_tickers)
    key = (scope_key, model)
    if md := _cache_get(scope_key, model):
        _task_status.pop(key, None)
        return md

    if retry:
        _task_status.pop(key, None)

    status = _task_status.get(key)
    if status and status.get("phase") in ("error", "cancelled") and not retry:
        # Same guard as research_router._get_or_start: don't silently retry after a failure or
        # cancellation — every poll would otherwise restart a fresh (likely identically-failing)
        # generation forever without ever surfacing the error to the user.
        return _GENERATING_MD

    if key not in _background_tasks or _background_tasks[key].done():
        _background_tasks[key] = asyncio.create_task(
            _background_generate(scope_key, industry, custom_tickers, model)
        )
    return _GENERATING_MD


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _parse_tickers(tickers: Optional[str]) -> Optional[list[str]]:
    if not tickers:
        return None
    parsed = [t.strip() for t in tickers.split(",") if t.strip()]
    return parsed or None


@router.get("/industry-research/industries")
async def industry_research_industries():
    return ind.list_industries()


@router.get("/industry-research/models")
async def industry_research_models():
    return _MODEL_OPTIONS


@router.get("/industry-research/report")
async def industry_research_report(
    industry: Optional[str] = None, tickers: Optional[str] = None,
    model: str = _DEFAULT_MODEL, retry: bool = False,
):
    custom_tickers = _parse_tickers(tickers)
    if not industry and not custom_tickers:
        raise HTTPException(status_code=400, detail="industry or tickers is required")
    industry = industry.strip() if industry else None
    model = model.strip() or _DEFAULT_MODEL
    return _get_or_start(industry, custom_tickers, model, retry=retry)


@router.get("/industry-research/status")
async def industry_research_status(
    industry: Optional[str] = None, tickers: Optional[str] = None, model: str = _DEFAULT_MODEL,
):
    custom_tickers = _parse_tickers(tickers)
    industry = industry.strip() if industry else None
    model = model.strip() or _DEFAULT_MODEL
    scope_key = ind.scope_key(industry, custom_tickers)
    key = (scope_key, model)
    status = _task_status.get(key)
    if status is not None:
        return status
    cached = _cache_get(scope_key, model) is not None
    return {"phase": "done" if cached else "idle", "message": "", "error": None}


@router.post("/industry-research/cancel")
async def industry_research_cancel(
    industry: Optional[str] = None, tickers: Optional[str] = None, model: str = _DEFAULT_MODEL,
):
    custom_tickers = _parse_tickers(tickers)
    industry = industry.strip() if industry else None
    model = model.strip() or _DEFAULT_MODEL
    scope_key = ind.scope_key(industry, custom_tickers)
    key = (scope_key, model)
    task = _background_tasks.get(key)
    if task and not task.done():
        task.cancel()
        _set_status(key, "cancelled", "Cancelled by user.")
        log.info("industry research: generation cancelled by user (scope=%s model=%s)", scope_key, model)
        return {"status": "cancelled"}
    return {"status": "not_running"}
