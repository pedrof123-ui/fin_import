"""
FastAPI router for AI equity research reports.

Data sources: av_financials.duckdb, historic_fundamentals.duckdb,
SEC EDGAR (MD&A + risk factors), Alpha Vantage earnings transcripts, Tavily web search.
Reports generated via OpenRouter; cached 24h in research_cache.duckdb.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

import duckdb
import requests
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel
from agents import Agent, OpenAIChatCompletionsModel, Runner

log = logging.getLogger(__name__)
router = APIRouter()

_DATA_DIR     = Path(__file__).parent.parent / "data"
_AV_FIN_DB    = _DATA_DIR / "av_financials.duckdb"
_HIST_FUND_DB = _DATA_DIR / "historic_fundamentals.duckdb"
_RESEARCH_DB  = _DATA_DIR / "research_cache.duckdb"
_EARNINGS_DB  = _DATA_DIR / "earnings_transcripts.duckdb"

_DEFAULT_MODEL    = "google/gemini-3.5-flash"
_MAX_EDGAR_CHARS  = 8000
_CACHE_TTL_HOURS  = 24
_EDGAR_TIMEOUT    = 30
_EARNINGS_TIMEOUT = 30
_DB_TIMEOUT       = 10
_TAVILY_TIMEOUT   = 20

_MODEL_OPTIONS = [
    {"label": "Claude Sonnet 4.6 (Default)", "value": "anthropic/claude-sonnet-4-6"},
    {"label": "Qwen3 235B",                  "value": "qwen/qwen3-235b-a22b-2507"},
    {"label": "Gemini 3.5 Flash",            "value": "google/gemini-3.5-flash"},
    {"label": "Gemini 3.1 Pro",              "value": "google/gemini-3.1-pro-preview"},
    {"label": "Qwen3.7 Max",                 "value": "qwen/qwen3.7-max"},
    {"label": "MiniMax M3",                  "value": "minimax/minimax-m3"},
]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ResearchHeader(BaseModel):
    company_name: str
    ticker: str
    prepared_date: str
    ai_model: str
    rating: Literal["BUY", "HOLD", "SELL"]
    target_low: float
    target_high: float
    thesis_summary: str


class FinancialRow(BaseModel):
    metric: str
    values: list[str]
    yoy_latest: Optional[str] = None


class ValuationSummary(BaseModel):
    current_pe: Optional[float] = None
    normalized_pe_5y: Optional[float] = None
    current_pfcf: Optional[float] = None
    normalized_pfcf_5y: Optional[float] = None
    goal_low: Optional[float] = None
    goal_high: Optional[float] = None
    goal_2x: Optional[float] = None
    upside_pct: Optional[float] = None
    next_q_eps_estimate: Optional[str] = None
    fy_eps_estimate: Optional[str] = None


class EquityResearchReport(BaseModel):
    header: ResearchHeader
    key_highlights: list[str]
    financial_performance: list[FinancialRow]
    financial_years: list[str]
    valuation: ValuationSummary
    company_overview: str
    competitive_analysis: str
    industry_outlook: str
    mda_summary: str
    risk_factors: list[str]
    near_term_catalysts: list[str]
    earnings_highlights: str
    investment_thesis: str


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(" --- " for _ in headers) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return lines


def render_to_markdown(report: EquityResearchReport) -> str:
    h = report.header
    v = report.valuation
    lines: list[str] = []

    rating_fmt = {"BUY": "**BUY**", "HOLD": "**HOLD**", "SELL": "**SELL**"}

    lines += [
        f"# {h.company_name} ({h.ticker})",
        "## Equity Research Report",
        "",
        f"**Rating:** {rating_fmt.get(h.rating, h.rating)}  |  "
        f"**Target:** ${h.target_low:.2f} – ${h.target_high:.2f}",
        f"**Prepared:** {h.prepared_date}  |  **Model:** {h.ai_model}",
        "",
        f"> {h.thesis_summary}",
        "",
        "---",
        "",
    ]

    lines += ["## Key Highlights", ""]
    for pt in report.key_highlights:
        lines.append(f"- {pt}")
    lines += ["", "---", ""]

    lines += ["## 1. Financial Performance", ""]
    if report.financial_performance:
        year_headers = ["Metric"] + report.financial_years + ["YoY"]
        rows = [
            [r.metric] + r.values + [r.yoy_latest or "—"]
            for r in report.financial_performance
        ]
        lines += _md_table(year_headers, rows)
    lines += ["", "---", ""]

    lines += ["## 2. Valuation", ""]

    def _fv(x, fmt=".1f") -> str:
        return f"{x:{fmt}}" if x is not None else "n/a"

    val_rows = [
        ["Current P/E", _fv(v.current_pe), "Normalized P/E (5yr)", _fv(v.normalized_pe_5y)],
        ["Current P/FCF", _fv(v.current_pfcf), "Normalized P/FCF (5yr)", _fv(v.normalized_pfcf_5y)],
        ["Goal Low", f"${v.goal_low:.2f}" if v.goal_low else "n/a",
         "Goal High", f"${v.goal_high:.2f}" if v.goal_high else "n/a"],
        ["2x Target", f"${v.goal_2x:.2f}" if v.goal_2x else "n/a",
         "Upside to Goal High", f"{v.upside_pct:.1f}%" if v.upside_pct else "n/a"],
        ["Next Q EPS Est.", v.next_q_eps_estimate or "n/a",
         "FY EPS Est.", v.fy_eps_estimate or "n/a"],
    ]
    lines += _md_table(["Metric", "Value", "Metric", "Value"], val_rows)
    lines += ["", "---", ""]

    lines += ["## 3. Company Overview", "", report.company_overview, "", "---", ""]
    lines += ["## 4. Competitive Analysis & Market Positioning", "", report.competitive_analysis, "", "---", ""]
    lines += ["## 5. Industry Outlook & Market Opportunity", "", report.industry_outlook, "", "---", ""]
    lines += ["## 6. Management Discussion & Analysis", "", report.mda_summary, "", "---", ""]

    lines += ["## 7. Key Risk Factors", ""]
    for risk in report.risk_factors:
        lines.append(f"- {risk}")
    lines += ["", "---", ""]

    lines += ["## 8. Near-Term Catalysts (0–12 months)", ""]
    for cat in report.near_term_catalysts:
        lines.append(f"- {cat}")
    lines += ["", "---", ""]

    lines += ["## 9. Recent Earnings Highlights", "", report.earnings_highlights, "", "---", ""]

    lines += [
        "## 10. Investment Thesis & Recommendation",
        "",
        report.investment_thesis,
        "",
        "---",
        "",
        f"*Report prepared by {h.ai_model} on {h.prepared_date}. "
        "For informational purposes only. Not investment advice.*",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Data gathering — all synchronous, safe to call from thread pool
# ---------------------------------------------------------------------------

def _fmt_b(v) -> str:
    if v is None:
        return "n/a"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "n/a"
    if abs(v) >= 1e9:
        return f"${v/1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:.1f}M"
    return f"${v:.0f}"


def _fmt_pct(num, denom) -> str:
    if not num or not denom:
        return "n/a"
    try:
        return f"{float(num)/float(denom)*100:.1f}%"
    except (TypeError, ZeroDivisionError):
        return "n/a"


def _yoy(new_val, old_val) -> str:
    if not new_val or not old_val:
        return "n/a"
    try:
        return f"{(float(new_val)/float(old_val)-1)*100:+.1f}%"
    except (TypeError, ZeroDivisionError):
        return "n/a"


def get_financial_summary(ticker: str) -> str:
    if not _AV_FIN_DB.exists():
        return f"[ERROR] av_financials.duckdb not found"
    ticker = ticker.upper()
    conn = duckdb.connect(str(_AV_FIN_DB), read_only=True)
    inc = conn.execute("""
        SELECT fiscal_date_ending, total_revenue, gross_profit, operating_income,
               net_income, ebitda
        FROM (
            SELECT *, ROW_NUMBER() OVER (ORDER BY fiscal_date_ending DESC) AS rn
            FROM income_statements WHERE ticker = ? AND period_type = 'annual'
        ) WHERE rn <= 5
        ORDER BY fiscal_date_ending ASC
    """, [ticker]).fetchall()
    cf = conn.execute("""
        SELECT fiscal_date_ending, operating_cashflow, capital_expenditures
        FROM (
            SELECT *, ROW_NUMBER() OVER (ORDER BY fiscal_date_ending DESC) AS rn
            FROM cash_flow_statements WHERE ticker = ? AND period_type = 'annual'
        ) WHERE rn <= 5
        ORDER BY fiscal_date_ending ASC
    """, [ticker]).fetchall()
    co = conn.execute(
        "SELECT name FROM company_overview WHERE ticker = ? ORDER BY fetch_date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    conn.close()

    if not inc:
        return f"[ERROR] No annual financials found for {ticker}"

    company_name = co[0] if co else ticker
    years  = [str(r[0])[:4] for r in inc]
    revs   = [r[1] for r in inc]
    gps    = [r[2] for r in inc]
    ops    = [r[3] for r in inc]
    nis    = [r[4] for r in inc]
    ebs    = [r[5] for r in inc]
    cf_map = {str(r[0])[:4]: (r[1], r[2]) for r in cf}

    def row(label, vals, fmt=_fmt_b):
        formatted = " | ".join(fmt(v) for v in vals)
        yoy = _yoy(vals[-1], vals[-2]) if len(vals) >= 2 else "n/a"
        return f"{label}: {formatted}  [YoY latest: {yoy}]"

    lines = [f"FINANCIAL PERFORMANCE — {company_name} ({ticker})", f"Fiscal years: {', '.join(years)}", ""]
    lines.append(row("Revenue", revs))
    lines.append("Gross Margin: " + " | ".join(_fmt_pct(g, r) for g, r in zip(gps, revs)))
    lines.append(row("Gross Profit", gps))
    lines.append("Operating Margin: " + " | ".join(_fmt_pct(o, r) for o, r in zip(ops, revs)))
    lines.append(row("Operating Income", ops))
    lines.append("Net Margin: " + " | ".join(_fmt_pct(n, r) for n, r in zip(nis, revs)))
    lines.append(row("Net Income", nis))
    lines.append(row("EBITDA", ebs))

    fcf_vals = []
    for y in years:
        pair = cf_map.get(y)
        if pair and pair[0] is not None and pair[1] is not None:
            fcf_vals.append(float(pair[0]) - abs(float(pair[1])))
        else:
            fcf_vals.append(None)
    lines.append(row("Free Cash Flow (OCF - Capex)", fcf_vals))

    return "\n".join(lines)


def get_valuation_data(ticker: str) -> str:
    if not _HIST_FUND_DB.exists():
        return f"[ERROR] historic_fundamentals.duckdb not found"
    ticker = ticker.upper()
    conn = duckdb.connect(str(_HIST_FUND_DB), read_only=True)

    ps = conn.execute("""
        SELECT current_pe, normalized_pe_5y, current_pfcf, normalized_pfcf_5y,
               goal_low, goal_high, goal_2x, current_price,
               rev_cagr_3yr, earn_cagr_3yr, current_roic,
               current_gross_margin, current_operating_margin, current_fcf_margin,
               debt_to_ebitda, market_cap_b, forward_pe, forward_12m_eps
        FROM pe_stats WHERE ticker = ?
    """, [ticker]).fetchone()

    ee = conn.execute("""
        SELECT horizon, fiscal_date, eps_avg, rev_avg
        FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY horizon ORDER BY fetched_at DESC) AS rn
            FROM earnings_estimates WHERE ticker = ?
        ) WHERE rn = 1
        ORDER BY fiscal_date
        LIMIT 4
    """, [ticker]).fetchall()

    mp = conn.execute("""
        SELECT month_end_date, pe_ratio, price, ttm_eps
        FROM monthly_pe WHERE ticker = ?
        ORDER BY month_end_date DESC LIMIT 12
    """, [ticker]).fetchall()

    conn.close()

    if not ps:
        return f"[ERROR] No valuation data found for {ticker}"

    def f(v, fmt=".1f"):
        return f"{float(v):{fmt}}" if v is not None else "n/a"

    lines = [f"VALUATION DATA — {ticker}", ""]
    lines.append(f"Current Price:       ${f(ps[7], '.2f')}")
    lines.append(f"Market Cap:          ${f(ps[15], '.1f')}B")
    lines.append("")
    lines.append(f"Current P/E:         {f(ps[0])}")
    lines.append(f"Normalized P/E (5y): {f(ps[1])}")
    lines.append(f"Forward P/E:         {f(ps[16])}")
    lines.append(f"Current P/FCF:       {f(ps[2])}")
    lines.append(f"Normalized P/FCF 5y: {f(ps[3])}")
    lines.append("")
    lines.append(f"Goal Low:            ${f(ps[4], '.2f')}")
    lines.append(f"Goal High:           ${f(ps[5], '.2f')}")
    lines.append(f"2x Target:           ${f(ps[6], '.2f')}")
    if ps[5] and ps[7] and float(ps[7]) > 0:
        upside = (float(ps[5]) / float(ps[7]) - 1) * 100
        lines.append(f"Upside to Goal High: {upside:+.1f}%")
    lines.append("")
    lines.append(f"Revenue CAGR (3yr):  {f(float(ps[8])*100 if ps[8] else None, '.1f')}%")
    lines.append(f"Earnings CAGR (3yr): {f(float(ps[9])*100 if ps[9] else None, '.1f')}%")
    lines.append(f"ROIC:                {f(float(ps[10])*100 if ps[10] else None, '.1f')}%")
    lines.append(f"Gross Margin:        {f(float(ps[11])*100 if ps[11] else None, '.1f')}%")
    lines.append(f"Operating Margin:    {f(float(ps[12])*100 if ps[12] else None, '.1f')}%")
    lines.append(f"FCF Margin:          {f(float(ps[13])*100 if ps[13] else None, '.1f')}%")
    lines.append(f"Debt/EBITDA:         {f(ps[14])}")
    lines.append(f"Forward EPS Est:     ${f(ps[17], '.2f')}")
    lines.append("")

    if ee:
        lines.append("Earnings Estimates:")
        for e in ee:
            lines.append(f"  {e[0]} ({str(e[1])[:7]}): EPS avg ${f(e[2], '.2f')}, Rev avg {_fmt_b(e[3])}")
    lines.append("")

    if mp:
        lines.append("Recent P/E history (last 12 months, newest first):")
        for m in mp[:6]:
            lines.append(f"  {str(m[0])[:7]}: P/E={f(m[1])}, Price=${f(m[2], '.2f')}, TTM EPS=${f(m[3], '.2f')}")

    return "\n".join(lines)


def _edgar_section(ticker: str, section_key: str, form: str = "10-K") -> str:
    try:
        from edgar import Company, set_identity
    except ImportError:
        return "[ERROR] edgartools not installed"

    identity = os.getenv("SEC_ID", "")
    if not identity:
        return "[ERROR] SEC_ID not set in environment"
    set_identity(identity)

    try:
        company = Company(ticker.upper())
        filings = company.get_filings(form=form)
        filing = filings.latest(1)
        if filing is None:
            return f"[ERROR] No {form} filing found for {ticker}"
        obj = filing.obj()
        if obj is None:
            return f"[ERROR] Could not parse {form} filing for {ticker}"
        content = obj[section_key]
        if content is None:
            return f"[ERROR] Section '{section_key}' not found in {form} for {ticker}"
        text = str(content)
        return text[:_MAX_EDGAR_CHARS] + ("..." if len(text) > _MAX_EDGAR_CHARS else "")
    except Exception as e:
        return f"[ERROR] Edgar fetch failed for {ticker}: {e}"


def get_edgar_mda(ticker: str) -> str:
    return _edgar_section(ticker, "mda", form="10-K")


def get_edgar_risks(ticker: str) -> str:
    return _edgar_section(ticker, "risk_factors", form="10-K")


def get_earnings_summary(ticker: str) -> str:
    """Fetch earnings transcript synchronously — safe from thread pool executor."""
    ticker = ticker.upper()
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        return "[ERROR] ALPHA_VANTAGE_API_KEY not configured"

    # Check earnings_transcripts.duckdb cache first
    if _EARNINGS_DB.exists():
        try:
            conn = duckdb.connect(str(_EARNINGS_DB), read_only=True)
            row = conn.execute(
                "SELECT quarter, transcript_text FROM earnings_transcripts "
                "WHERE symbol = ? ORDER BY quarter DESC LIMIT 1",
                [ticker],
            ).fetchone()
            conn.close()
            if row:
                quarter, transcript = row[0], row[1]
                return f"EARNINGS TRANSCRIPT — {ticker} {quarter}\n\n{transcript[:4000]}"
        except Exception:
            pass

    # Cache miss — probe quarters from AV
    today = date.today()
    year = today.year
    quarters_to_try = [
        f"{y}Q{q}"
        for y in [year + 1, year, year - 1]
        for q in [4, 3, 2, 1]
    ]

    try:
        for q_str in quarters_to_try:
            resp = requests.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "EARNINGS_CALL_TRANSCRIPT",
                    "symbol": ticker,
                    "quarter": q_str,
                    "apikey": api_key,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if any(k in data for k in ("Error Message", "Note", "Information")):
                continue
            if not data.get("transcript"):
                continue
            parts = []
            for entry in data["transcript"]:
                speaker = entry.get("speaker", "Unknown")
                title = entry.get("title", "")
                content = entry.get("content", "")
                header = f"## {speaker}"
                if title:
                    header += f"\n**{title}**"
                parts.append(f"{header}\n\n{content}")
            transcript = "\n\n---\n\n".join(parts)
            return f"EARNINGS TRANSCRIPT — {ticker} {q_str}\n\n{transcript[:4000]}"
        return f"[ERROR] No earnings transcript found for {ticker}"
    except Exception as e:
        return f"[ERROR] Earnings summary unavailable for {ticker}: {e}"


def get_web_search(ticker: str) -> str:
    key = os.getenv("TAVILY_API_KEY", "")
    if not key:
        return "[INFO] TAVILY_API_KEY not set — web search skipped"
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=key)
        result = client.search(
            query=f"{ticker} stock news earnings analyst rating outlook 2025 2026",
            search_depth="basic",
            max_results=5,
            include_answer=True,
        )
        lines = [f"WEB SEARCH RESULTS — {ticker}", ""]
        if answer := result.get("answer"):
            lines += [f"Summary: {answer}", ""]
        for r in result.get("results", []):
            title   = r.get("title", "")
            content = (r.get("content") or "")[:500]
            lines  += [f"Title: {title}", f"Excerpt: {content}", ""]
        return "\n".join(lines) if len(lines) > 2 else f"[INFO] No web results returned for {ticker}"
    except Exception as e:
        return f"[ERROR] Web search failed for {ticker}: {e}"


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_RESEARCH_INSTRUCTIONS = """
You are an institutional equity research analyst. Today is {date}.
Generate a rigorous, investment-grade research report for {ticker}.

AVAILABLE DATA SOURCES:
1. Financial statements (5 years, annual): revenue, gross profit, operating income, net income, EBITDA, FCF
2. Valuation: PE multiples (current/normalized), P/FCF, goal prices (low/high/2x), earnings estimates
3. SEC 10-K MD&A: management discussion of business performance, strategy, and capital allocation
4. SEC 10-K Risk Factors: material risks disclosed by management
5. Recent earnings call: key metrics, beats/misses, management guidance
6. Web search: recent news, analyst ratings, market developments, competitive events

RATING GUIDELINES:
- BUY: upside to goal_high > 15% AND positive business momentum
- HOLD: within +/-15% of goal_high, or mixed/uncertain signals
- SELL: price exceeds goal_high OR deteriorating fundamentals OR major structural risk

TARGET PRICE: Use goal_low (conservative) and goal_high (base case) from valuation data.
If goal prices are unreliable, derive an alternative using normalized_pe_5y x forward_12m_eps and disclose this.

DATA HONESTY:
- If financials show declining revenue or earnings, acknowledge the trend directly
- If earnings call data says "[ERROR]" or unavailable, note this and rely on MD&A
- If web search returned no relevant results, proceed without it
- For competitive analysis, use web search results first; supplement with training knowledge where absent

POPULATE EACH FIELD EXACTLY AS SPECIFIED:

header:
  company_name: from financial data (use ticker if name unavailable)
  ticker: {ticker}
  prepared_date: {date}
  ai_model: {model}
  rating: BUY, HOLD, or SELL
  target_low: goal_low as float
  target_high: goal_high as float
  thesis_summary: ONE precise sentence — the single most important reason for your rating

key_highlights: 5-8 bullet strings with specific numbers covering:
  - Most recent quarter performance vs. estimates
  - Revenue/earnings growth trajectory (% CAGRs)
  - Core competitive advantage or key vulnerability
  - Current valuation vs. historical norm
  - Upside/downside % to target price range
  - Most important near-term catalyst or risk

financial_performance: FinancialRow list for Revenue, Gross Margin (%), Operating Income,
  Operating Margin (%), Net Income, EBITDA, Free Cash Flow
  financial_years: fiscal year labels (e.g. ["FY2020","FY2021","FY2022","FY2023","FY2024"])

valuation: populate all fields from the valuation section
  upside_pct = (goal_high / current_price - 1) x 100
  next_q_eps_estimate and fy_eps_estimate from earnings estimates (as formatted strings)

company_overview: 3-4 paragraphs:
  Para 1 — COMPANY PROFILE: founding, HQ, business model, core mission
  Para 2 — PRODUCT & REVENUE BREAKDOWN: segments, geographic split, key customers
  Para 3 — TECHNOLOGY & COMPETITIVE ADVANTAGES: moat sources and durability
  Para 4 — STRATEGIC FRAMEWORK: apply Porter's Five Forces or Competitive Moat Analysis
    with 3 specific insights for {ticker}

competitive_analysis: prose + one markdown comparison table:
  Para 1 — COMPETITIVE LANDSCAPE: 3-5 key competitors, their threats, market position
  Para 2 — COMPETITIVE ADVANTAGES vs. DISADVANTAGES
  Para 3 — WHY {ticker} WINS OR LOSES
  TABLE: Company | Est. Market Share | Key Strength | Key Weakness | Recent Move

industry_outlook: 3-4 paragraphs:
  Para 1 — MARKET SIZE & GROWTH: TAM, historical and projected CAGR
  Para 2 — KEY MARKET DRIVERS: 3-5 trends, tailwind or headwind for {ticker}
  Para 3 — REGULATORY ENVIRONMENT & BARRIERS TO ENTRY
  Para 4 — MARKET PENETRATION OPPORTUNITY

mda_summary: 3-4 concise paragraphs from the MD&A:
  - Revenue drivers by segment, YoY performance
  - Margin trends and cost structure changes
  - Capital allocation (capex, debt, buybacks, dividends)
  - Management forward guidance and strategic priorities

risk_factors: 6-8 strings formatted as:
  "[SEVERITY: High/Medium/Low] concise risk with specific context for {ticker}"

near_term_catalysts: 3-5 specific upcoming catalysts (0-12 months)

earnings_highlights: 2-4 sentences covering beat/miss vs. consensus, key management comment,
  guidance change. If data is unavailable: "Earnings call data not available — see MD&A summary."

investment_thesis: 4-5 paragraphs:
  Para 1 — BULL CASE: conditions making investment compelling, upside scenario + timeline
  Para 2 — BEAR CASE: most credible downside scenario + potential downside price
  Para 3 — CURRENT ASSESSMENT: why BUY/HOLD/SELL today with specific evidence
  Para 4 — WHAT WOULD CHANGE YOUR MIND: specific, observable rating triggers
  Para 5 — RISK/REWARD PROFILE: 12-month horizon, R-Multiple, position sizing comment

Write with institutional precision. Use specific numbers. No filler language.
Every claim must trace to the data provided.

---
DATA:

{context}
"""


# ---------------------------------------------------------------------------
# LLM orchestration
# ---------------------------------------------------------------------------

async def _run_research_agent(ticker: str, model: str) -> EquityResearchReport:
    loop = asyncio.get_event_loop()
    t0 = datetime.now()
    log.info("[%s] research: starting data gathering (model=%s)", ticker, model)

    def _timed(fn, label):
        t = datetime.now()
        result = fn(ticker)
        elapsed = (datetime.now() - t).total_seconds()
        if result.startswith("[ERROR]"):
            log.warning("[%s] %s: %s (%.1fs)", ticker, label, result[:120], elapsed)
        else:
            log.info("[%s] %s: done (%.1fs, %d chars)", ticker, label, elapsed, len(result))
        return result

    async def _run(fn, label, timeout):
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: _timed(fn, label)),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            log.warning("[%s] %s: timed out after %ds", ticker, label, timeout)
            return f"[ERROR] {label} timed out after {timeout}s"

    financials, valuation, mda, risks, earnings, web = await asyncio.gather(
        _run(get_financial_summary, "financials",  _DB_TIMEOUT),
        _run(get_valuation_data,    "valuation",   _DB_TIMEOUT),
        _run(get_edgar_mda,         "edgar_mda",   _EDGAR_TIMEOUT),
        _run(get_edgar_risks,       "edgar_risks", _EDGAR_TIMEOUT),
        _run(get_earnings_summary,  "earnings",    _EARNINGS_TIMEOUT),
        _run(get_web_search,        "web_search",  _TAVILY_TIMEOUT),
    )

    log.info("[%s] research: data gathering done in %.1fs — calling LLM", ticker,
             (datetime.now() - t0).total_seconds())

    context = (
        f"=== FINANCIAL PERFORMANCE ===\n{financials}\n\n"
        f"=== VALUATION ===\n{valuation}\n\n"
        f"=== MD&A ===\n{mda}\n\n"
        f"=== RISK FACTORS ===\n{risks}\n\n"
        f"=== EARNINGS CALL HIGHLIGHTS ===\n{earnings}\n\n"
        f"=== WEB SEARCH — RECENT NEWS & ANALYST VIEWS ===\n{web}"
    )

    instructions = (
        _RESEARCH_INSTRUCTIONS
        .replace("{ticker}", ticker.upper())
        .replace("{date}", datetime.now().strftime("%Y-%m-%d"))
        .replace("{model}", model)
        .replace("{context}", context)
    )

    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)
    llm    = OpenAIChatCompletionsModel(model=model, openai_client=client)
    agent  = Agent(
        name="equity_researcher",
        instructions=instructions,
        model=llm,
        output_type=EquityResearchReport,
    )
    t_llm = datetime.now()
    result = await Runner.run(agent, f"Generate investment research report for {ticker.upper()}.")
    log.info("[%s] research: LLM done in %.1fs — total %.1fs", ticker,
             (datetime.now() - t_llm).total_seconds(),
             (datetime.now() - t0).total_seconds())
    return result.final_output


# ---------------------------------------------------------------------------
# DuckDB cache (24h TTL, keyed by ticker + model)
# ---------------------------------------------------------------------------

def _init_cache():
    _RESEARCH_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(_RESEARCH_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_cache (
            ticker          VARCHAR,
            model           VARCHAR,
            report_markdown VARCHAR,
            generated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (ticker, model)
        )
    """)
    conn.close()


def _cache_get(ticker: str, model: str) -> Optional[str]:
    if not _RESEARCH_DB.exists():
        return None
    conn = duckdb.connect(str(_RESEARCH_DB), read_only=True)
    row = conn.execute(
        "SELECT report_markdown, generated_at FROM research_cache WHERE ticker = ? AND model = ?",
        [ticker.upper(), model],
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


def _cache_put(ticker: str, model: str, markdown: str):
    _init_cache()
    conn = duckdb.connect(str(_RESEARCH_DB))
    conn.execute("""
        INSERT INTO research_cache (ticker, model, report_markdown, generated_at)
        VALUES (?, ?, ?, now())
        ON CONFLICT (ticker, model) DO UPDATE SET
            report_markdown = excluded.report_markdown,
            generated_at    = excluded.generated_at
    """, [ticker.upper(), model, markdown])
    conn.close()


# ---------------------------------------------------------------------------
# Background task registry
# ---------------------------------------------------------------------------

_background_tasks: dict[tuple[str, str], asyncio.Task] = {}

_GENERATING_MD = (
    "## Generating Research Report for {ticker}...\n\n"
    "Gathering financials, valuation, SEC filings, earnings data, and web search, "
    "then running AI analysis.\n"
    "This takes approximately 60-90 seconds.\n\n"
    "*The page polls automatically every 15 seconds.*"
)


async def _background_generate(ticker: str, model: str):
    key = (ticker, model)
    log.info("[%s] research: background task started (model=%s)", ticker, model)
    try:
        report   = await _run_research_agent(ticker, model)
        markdown = render_to_markdown(report)
        _cache_put(ticker, model, markdown)
        log.info("[%s] research: report cached (%d chars)", ticker, len(markdown))
    except Exception as e:
        log.error("[%s] research: background task failed (model=%s): %s", ticker, model, e)
    finally:
        _background_tasks.pop(key, None)


def _get_or_start(ticker: str, model: str) -> str:
    ticker = ticker.upper()
    if md := _cache_get(ticker, model):
        return md
    key = (ticker, model)
    if key not in _background_tasks:
        _background_tasks[key] = asyncio.create_task(_background_generate(ticker, model))
    return _GENERATING_MD.format(ticker=ticker)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/research/models")
async def research_models():
    return _MODEL_OPTIONS


@router.get("/research/report")
async def research_report(ticker: str, model: str = _DEFAULT_MODEL):
    ticker = ticker.strip().upper()
    model  = model.strip() or _DEFAULT_MODEL
    return _get_or_start(ticker, model)


# ---------------------------------------------------------------------------
# Chat — tool definitions
# ---------------------------------------------------------------------------

_CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "screen_stocks",
            "description": (
                "Screen stocks in the database by financial criteria. "
                "Returns up to 30 matching companies with key metrics. "
                "Use this to find stocks matching a specific financial profile, "
                "e.g. accelerating revenue growth, high ROIC, low valuation, etc. "
                "All rate/margin/growth parameters are decimals (0.15 = 15%)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rev_growth_1yr_min":  {"type": "number", "description": "Min 1-year revenue growth"},
                    "rev_growth_1yr_max":  {"type": "number", "description": "Max 1-year revenue growth"},
                    "earn_growth_1yr_min": {"type": "number", "description": "Min 1-year earnings growth"},
                    "earn_growth_1yr_max": {"type": "number", "description": "Max 1-year earnings growth"},
                    "rev_cagr_3yr_min":   {"type": "number", "description": "Min 3-year revenue CAGR"},
                    "market_cap_b_min":   {"type": "number", "description": "Min market cap in billions"},
                    "market_cap_b_max":   {"type": "number", "description": "Max market cap in billions"},
                    "pe_max":             {"type": "number", "description": "Max trailing P/E"},
                    "fwd_pe_max":         {"type": "number", "description": "Max forward P/E"},
                    "roic_min":           {"type": "number", "description": "Min ROIC"},
                    "fcf_margin_min":     {"type": "number", "description": "Min FCF margin"},
                    "gross_margin_min":   {"type": "number", "description": "Min gross margin"},
                    "debt_to_ebitda_max": {"type": "number", "description": "Max debt/EBITDA"},
                    "momentum_12_1_min":  {"type": "number", "description": "Min 12-1 month price momentum"},
                    "sectors":    {"type": "array", "items": {"type": "string"}, "description": "Filter by sector names"},
                    "industries": {"type": "array", "items": {"type": "string"}, "description": "Filter by industry names"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticker_data",
            "description": (
                "Get comprehensive data for a specific stock: "
                "5-year annual financials, current valuation metrics, earnings estimates, "
                "and last 8 quarters of revenue/earnings for trend analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol, e.g. 'NVDA'"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_data",
            "description": "Get current valuation and financial metrics for a sector or industry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_type": {"type": "string", "enum": ["sector", "industry"]},
                    "name":       {"type": "string", "description": "Sector or industry name, e.g. 'Technology'"},
                },
                "required": ["group_type", "name"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Chat — tool implementations (blocking, run in executor)
# ---------------------------------------------------------------------------

def _tool_screen_stocks(filters: dict) -> str:
    if not _HIST_FUND_DB.exists() or not _AV_FIN_DB.exists():
        return "[ERROR] Required databases not found"

    conditions: list[str] = []
    params: list = []

    field_map = {
        "rev_growth_1yr_min":  "ps.rev_growth_1yr >= ?",
        "rev_growth_1yr_max":  "ps.rev_growth_1yr <= ?",
        "earn_growth_1yr_min": "ps.earn_growth_1yr >= ?",
        "earn_growth_1yr_max": "ps.earn_growth_1yr <= ?",
        "rev_cagr_3yr_min":    "ps.rev_cagr_3yr >= ?",
        "market_cap_b_min":    "COALESCE(ps.market_cap_b, co.market_cap / 1e9) >= ?",
        "market_cap_b_max":    "COALESCE(ps.market_cap_b, co.market_cap / 1e9) <= ?",
        "pe_max":              "ps.current_pe <= ?",
        "fwd_pe_max":          "ps.forward_pe <= ?",
        "roic_min":            "ps.current_roic >= ?",
        "fcf_margin_min":      "ps.current_fcf_margin >= ?",
        "gross_margin_min":    "ps.current_gross_margin >= ?",
        "debt_to_ebitda_max":  "ps.debt_to_ebitda <= ?",
        "momentum_12_1_min":   "mp.momentum_12_1 >= ?",
    }
    for key, sql_expr in field_map.items():
        val = filters.get(key)
        if val is not None:
            conditions.append(sql_expr)
            params.append(val)

    for fld, col in [("sectors", "co.sector"), ("industries", "co.industry")]:
        vals = filters.get(fld, [])
        if vals:
            placeholders = ", ".join(["?" for _ in vals])
            conditions.append(f"UPPER({col}) IN ({placeholders})")
            params.extend([v.upper() for v in vals])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
    WITH latest_mp AS (
        SELECT ticker, momentum_12_1
        FROM hf.monthly_pe
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY month_end_date DESC) = 1
    ),
    latest_co AS (
        SELECT ticker, name, sector, industry, market_cap
        FROM av.company_overview
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fetch_date DESC) = 1
    )
    SELECT
        ps.ticker,
        co.name AS company_name,
        co.sector,
        COALESCE(ps.market_cap_b, co.market_cap / 1e9) AS market_cap_b,
        ps.current_price,
        ps.current_pe,
        ps.forward_pe,
        ps.rev_growth_1yr,
        ps.earn_growth_1yr,
        ps.rev_cagr_3yr,
        ps.current_roic,
        ps.current_gross_margin,
        ps.current_fcf_margin,
        ps.debt_to_ebitda
    FROM hf.pe_stats ps
    LEFT JOIN latest_co co ON ps.ticker = co.ticker
    LEFT JOIN latest_mp mp ON ps.ticker = mp.ticker
    {where}
    ORDER BY COALESCE(ps.market_cap_b, co.market_cap / 1e9) DESC NULLS LAST
    LIMIT 30
    """

    try:
        conn = duckdb.connect(":memory:")
        conn.execute(f"ATTACH '{_HIST_FUND_DB}' AS hf (READ_ONLY)")
        conn.execute(f"ATTACH '{_AV_FIN_DB}' AS av (READ_ONLY)")
        df = conn.execute(sql, params).df()
        conn.close()
    except Exception as e:
        return f"[ERROR] Screen query failed: {e}"

    if df.empty:
        return "No stocks found matching the specified criteria."

    def _f(v, pct=False):
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return "n/a"
        return f"{float(v)*100:.1f}%" if pct else f"{float(v):.1f}"

    lines = [f"SCREEN RESULTS — {len(df)} companies (top {len(df)} by market cap)", ""]
    lines.append(f"{'Ticker':<8} {'Company':<28} {'Sector':<22} {'MCap$B':>8} {'PE':>6} {'FwdPE':>6} {'RevGr':>7} {'EarGr':>7} {'ROIC':>7}")
    lines.append("-" * 110)
    for _, r in df.iterrows():
        lines.append(
            f"{str(r['ticker']):<8} "
            f"{str(r['company_name'] or '')[:27]:<28} "
            f"{str(r['sector'] or '')[:21]:<22} "
            f"{_f(r['market_cap_b']):>8} "
            f"{_f(r['current_pe']):>6} "
            f"{_f(r['forward_pe']):>6} "
            f"{_f(r['rev_growth_1yr'], pct=True):>7} "
            f"{_f(r['earn_growth_1yr'], pct=True):>7} "
            f"{_f(r['current_roic'], pct=True):>7}"
        )
    return "\n".join(lines)


def _tool_get_ticker_data(ticker: str) -> str:
    ticker = ticker.upper().strip()
    fin = get_financial_summary(ticker)
    val = get_valuation_data(ticker)

    quarterly = ""
    if _AV_FIN_DB.exists():
        try:
            conn = duckdb.connect(str(_AV_FIN_DB), read_only=True)
            rows = conn.execute("""
                SELECT fiscal_date_ending, total_revenue, net_income
                FROM (
                    SELECT *, ROW_NUMBER() OVER (ORDER BY fiscal_date_ending DESC) AS rn
                    FROM income_statements WHERE ticker = ? AND period_type = 'quarterly'
                ) WHERE rn <= 8
                ORDER BY fiscal_date_ending ASC
            """, [ticker]).fetchall()
            conn.close()
            if rows:
                qlines = [f"QUARTERLY TREND — {ticker} (last {len(rows)} quarters)", ""]
                qlines.append(f"{'Quarter':<10} {'Revenue':>14} {'Rev QoQ':>9} {'Net Income':>14} {'NI QoQ':>9}")
                qlines.append("-" * 60)
                for i, row in enumerate(rows):
                    rev_qoq = _yoy(row[1], rows[i-1][1]) if i > 0 else "—"
                    ni_qoq  = _yoy(row[2], rows[i-1][2]) if i > 0 else "—"
                    qlines.append(
                        f"{str(row[0])[:7]:<10} {_fmt_b(row[1]):>14} {rev_qoq:>9} "
                        f"{_fmt_b(row[2]):>14} {ni_qoq:>9}"
                    )
                quarterly = "\n".join(qlines)
        except Exception as e:
            quarterly = f"[ERROR] Quarterly data: {e}"

    parts = [fin, val]
    if quarterly:
        parts.append(quarterly)
    return "\n\n".join(parts)


def _tool_get_sector_data(group_type: str, name: str) -> str:
    if not _HIST_FUND_DB.exists():
        return "[ERROR] historic_fundamentals.duckdb not found"
    try:
        conn = duckdb.connect(str(_HIST_FUND_DB), read_only=True)
        row = conn.execute("""
            SELECT group_name, month_end_date,
                   pe_median, pfcf_median, evebitda_median, ps_median,
                   rev_growth_1yr_median, earn_growth_1yr_median,
                   gross_margin_median, operating_margin_median, fcf_margin_median,
                   roic_median, roe_median, debt_to_ebitda_median
            FROM sector_stats
            WHERE group_type = ? AND UPPER(group_name) = UPPER(?)
            ORDER BY month_end_date DESC LIMIT 1
        """, [group_type, name]).fetchone()
        conn.close()
        if not row:
            return f"[ERROR] No data found for {group_type} '{name}'"

        def _f(v, pct=False):
            if v is None: return "n/a"
            return f"{float(v)*100:.1f}%" if pct else f"{float(v):.1f}"

        lines = [f"SECTOR DATA — {row[0]} ({group_type}) as of {str(row[1])[:7]}", ""]
        lines += [
            f"P/E median:         {_f(row[2])}",
            f"P/FCF median:       {_f(row[3])}",
            f"EV/EBITDA median:   {_f(row[4])}",
            f"P/S median:         {_f(row[5])}",
            f"Revenue growth 1yr: {_f(row[6], pct=True)}",
            f"Earnings growth 1yr:{_f(row[7], pct=True)}",
            f"Gross margin:       {_f(row[8], pct=True)}",
            f"Operating margin:   {_f(row[9], pct=True)}",
            f"FCF margin:         {_f(row[10], pct=True)}",
            f"ROIC median:        {_f(row[11], pct=True)}",
            f"ROE median:         {_f(row[12], pct=True)}",
            f"Debt/EBITDA:        {_f(row[13])}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"[ERROR] Sector data: {e}"


async def _execute_tool(name: str, args: dict) -> str:
    loop = asyncio.get_event_loop()
    if name == "screen_stocks":
        return await loop.run_in_executor(None, lambda: _tool_screen_stocks(args))
    if name == "get_ticker_data":
        return await loop.run_in_executor(None, lambda: _tool_get_ticker_data(args.get("ticker", "")))
    if name == "get_sector_data":
        return await loop.run_in_executor(
            None,
            lambda: _tool_get_sector_data(args.get("group_type", "sector"), args.get("name", "")),
        )
    return f"[ERROR] Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Chat — system prompt
# ---------------------------------------------------------------------------

def _build_chat_system(ticker: str, report: Optional[str]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    report_section = (
        f"\n\nEQUITY RESEARCH REPORT — {ticker.upper()} (already generated, use as context):\n\n{report}"
        if report else ""
    )
    return f"""You are an expert financial analyst assistant integrated into Finview, a financial data platform.
Today is {today}. The user is currently analyzing {ticker.upper()}.

You have access to real-time financial database tools:
- screen_stocks: Find stocks in the database matching specific financial criteria (growth, valuation, quality, etc.)
- get_ticker_data: Get 5-year financials, valuation metrics, and quarterly trend data for any ticker
- get_sector_data: Get current valuation and financial metrics for a sector or industry

Use tools whenever the user asks a data question. Be concise and precise. Lead with numbers and facts.
When screening for stocks, interpret the user's criteria sensibly (e.g. "accelerating revenue" → use rev_growth_1yr_min).
{report_section}"""


# ---------------------------------------------------------------------------
# Chat — SSE streaming generator
# ---------------------------------------------------------------------------

async def _chat_stream(req: ChatRequest):
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        yield f"data: {json.dumps({'type': 'error', 'content': 'OPENROUTER_API_KEY not configured'})}\n\n"
        return

    client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)

    messages: list[dict] = [
        {"role": "system", "content": _build_chat_system(req.ticker, req.report)},
        *[{"role": m.role, "content": m.content} for m in req.messages],
    ]

    for _iteration in range(6):
        tool_calls_acc: dict[int, dict] = {}
        content_chunks: list[str] = []
        finish_reason: Optional[str] = None

        try:
            stream = await client.chat.completions.create(
                model=req.model,
                messages=messages,
                tools=_CHAT_TOOLS,
                tool_choice="auto",
                stream=True,
            )
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return

        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish_reason = choice.finish_reason or finish_reason
            delta = choice.delta

            if delta.content:
                content_chunks.append(delta.content)
                yield f"data: {json.dumps({'type': 'text', 'content': delta.content})}\n\n"

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": "", "name": "", "args": ""}
                    if tc.id:
                        tool_calls_acc[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_calls_acc[idx]["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_calls_acc[idx]["args"] += tc.function.arguments

        if finish_reason != "tool_calls" or not tool_calls_acc:
            break

        # Add assistant message with tool call requests
        messages.append({
            "role": "assistant",
            "content": "".join(content_chunks) or None,
            "tool_calls": [
                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["args"]}}
                for tc in tool_calls_acc.values()
            ],
        })

        # Execute each tool and stream status
        for tc in tool_calls_acc.values():
            yield f"data: {json.dumps({'type': 'tool_start', 'name': tc['name']})}\n\n"
            try:
                args = json.loads(tc["args"])
                result = await _execute_tool(tc["name"], args)
            except Exception as e:
                result = f"[ERROR] {e}"
            yield f"data: {json.dumps({'type': 'tool_done', 'name': tc['name']})}\n\n"
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Chat — models and request
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    ticker: str
    model: str = _DEFAULT_MODEL
    messages: list[ChatMessage]
    report: Optional[str] = None


@router.post("/research/chat")
async def research_chat(req: ChatRequest):
    return StreamingResponse(
        _chat_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
