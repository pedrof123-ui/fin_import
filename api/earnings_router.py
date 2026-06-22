"""
FastAPI router for earnings call transcript summarization.

Transcripts are fetched from Alpha Vantage or imported from a URL and cached in DuckDB.
Summaries are generated via OpenRouter using the openai-agents SDK.
"""

import io
import os
import re
from datetime import date
from pathlib import Path
from typing import Optional

import pdfplumber
import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException
from openai import AsyncOpenAI
from agents import Agent, Runner, OpenAIChatCompletionsModel

from historic_fundamentals.earnings_transcripts import (
    open_db,
    save_transcript,
    fetch_from_av as _av_fetch,
)

router = APIRouter()

OPENROUTER_MODELS = [
    "qwen/qwen3-235b-a22b-2507",
    "google/gemini-3.5-flash",
    "google/gemini-3.1-pro-preview",
    "qwen/qwen3.7-max",
    "minimax/minimax-m3",
]

_DB_PATH = Path(os.environ.get(
    "EARNINGS_DB_PATH",
    str(Path(__file__).parent.parent / "data" / "earnings_transcripts.duckdb"),
))

_SUMMARY_TEMPLATE = """
You are an equity financial analyst assistant.
Create an investment-grade summary report of the earnings call transcript provided.

Must include:
    - Today's date, Earnings call date, Financial Period of the earnings call, prepared by AI model name
    - Key financial metrics (revenue, EPS, margins, guidance)
    - Brief management commentary on business performance
    - New Services/Technology/Products and Innovation
    - Key takeaways and forward-looking statements

DO NOT INCLUDE INVESTMENT ADVICE

Earnings call transcript: {transcript}
Today's date: {today}
AI model: {model}
"""


def _get_cached(symbol: str, quarter: str) -> Optional[str]:
    conn = open_db(_DB_PATH)
    try:
        row = conn.execute(
            "SELECT transcript_text FROM earnings_transcripts WHERE symbol = ? AND quarter = ?",
            [symbol, quarter],
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _get_cached_source(symbol: str, quarter: str) -> Optional[str]:
    conn = open_db(_DB_PATH)
    try:
        row = conn.execute(
            "SELECT source FROM earnings_transcripts WHERE symbol = ? AND quarter = ?",
            [symbol, quarter],
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _latest_cached_quarter(symbol: str) -> Optional[tuple[str, str]]:
    conn = open_db(_DB_PATH)
    try:
        row = conn.execute(
            "SELECT quarter, transcript_text FROM earnings_transcripts "
            "WHERE symbol = ? ORDER BY quarter DESC LIMIT 1",
            [symbol],
        ).fetchone()
        return (row[0], row[1]) if row else None
    finally:
        conn.close()


def _fetch_from_av(symbol: str, quarter: str) -> str:
    """Fetch transcript from AV and cache it. Raises HTTPException if unavailable."""
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ALPHA_VANTAGE_API_KEY not configured")
    result = _av_fetch(symbol, quarter, api_key)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No transcript found for {symbol} {quarter}")
    transcript_text, api_json = result
    try:
        conn = open_db(_DB_PATH)
        save_transcript(conn, symbol, quarter, transcript_text, api_json)
        conn.close()
    except Exception:
        pass  # cache failure is non-fatal
    return transcript_text


def _extract_from_url(url: str) -> str:
    """Download a URL and extract transcript text. Supports PDF and HTML."""
    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    is_pdf = "pdf" in content_type or url.lower().endswith(".pdf")

    if is_pdf:
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n\n".join(p for p in pages if p.strip())
    else:
        soup = BeautifulSoup(resp.content, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if not text.strip():
        raise HTTPException(status_code=422, detail="Could not extract text from the provided URL")
    return text


def _search_quarters(today: date) -> list[str]:
    """
    Quarters to probe for 'latest', newest first.
    Centers on today's calendar quarter with a 4-quarter lookahead so companies
    with fiscal years that lead the calendar (e.g. NVDA FY ends Jan, whose
    Q1 FY2027 call lands in May 2026) are still found without burning 7+
    wasted AV calls on distant future quarters that cannot possibly exist yet.
    """
    base = today.year * 4 + (today.month - 1) // 3
    result = []
    for offset in range(4, -7, -1):
        total = base + offset
        y, q = divmod(total, 4)
        result.append(f"{y}Q{q + 1}")
    return result


async def _run_llm(transcript: str, ticker: str, quarter: str, model: str) -> str:
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured")

    client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)
    llm = OpenAIChatCompletionsModel(model=model, openai_client=client)
    instructions = _SUMMARY_TEMPLATE.format(
        transcript=transcript,
        today=date.today().isoformat(),
        model=model,
    )
    agent = Agent(name="earnings_reporter", instructions=instructions, model=llm)
    result = await Runner.run(
        agent,
        f"Create an investment grade report of the earnings call for {ticker} {quarter}",
    )
    return result.final_output


@router.get("/earnings/models")
async def earnings_models_endpoint():
    return OPENROUTER_MODELS


@router.get("/earnings/report")
async def earnings_report(
    ticker: str,
    quarter: str = "latest",
    model: str = OPENROUTER_MODELS[0],
):
    ticker = ticker.upper()

    if quarter == "latest":
        best = _latest_cached_quarter(ticker)
        best_quarter = best[0] if best else None

        all_quarters = _search_quarters(date.today())
        to_probe = [q for q in all_quarters if q > best_quarter] if best_quarter else all_quarters

        transcript = None
        resolved_quarter = None
        for q_str in to_probe:
            try:
                transcript = _fetch_from_av(ticker, q_str)
                resolved_quarter = q_str
                break
            except Exception:
                continue

        if transcript is None:
            if best:
                resolved_quarter, transcript = best
            else:
                raise HTTPException(status_code=404, detail=f"No recent transcript found for {ticker}")
        quarter = resolved_quarter
    else:
        if not re.match(r"^\d{4}Q[1-4]$", quarter):
            raise HTTPException(
                status_code=400,
                detail="Quarter must be in YYYYQN format (e.g. 2025Q1) or 'latest'",
            )
        cached = _get_cached(ticker, quarter)
        transcript = cached if cached else _fetch_from_av(ticker, quarter)

    return await _run_llm(transcript, ticker, quarter, model)


@router.post("/earnings/import-url")
async def import_transcript_from_url(
    ticker: str,
    quarter: str,
    url: str,
    model: str = OPENROUTER_MODELS[0],
):
    ticker = ticker.upper()

    if not re.match(r"^\d{4}Q[1-4]$", quarter):
        raise HTTPException(
            status_code=400,
            detail="Quarter must be in YYYYQN format (e.g. 2025Q1)",
        )

    existing_source = _get_cached_source(ticker, quarter)
    if existing_source == "av":
        raise HTTPException(
            status_code=409,
            detail=f"Transcript for {ticker} {quarter} already exists from Alpha Vantage. Use 'Go' to generate a report.",
        )

    transcript = _extract_from_url(url)
    conn = open_db(_DB_PATH)
    save_transcript(conn, ticker, quarter, transcript, api_json=None, source="url")
    conn.close()

    return await _run_llm(transcript, ticker, quarter, model)
