"""
FastAPI router for earnings call transcript summarization.

Transcripts are fetched from Alpha Vantage or imported from a URL and cached in DuckDB.
Summaries are generated via OpenRouter using the openai-agents SDK.
"""

import asyncio
import io
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pdfplumber
import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from agents import Agent, Runner, OpenAIChatCompletionsModel
from pydantic import BaseModel

from historic_fundamentals.earnings_transcripts import (
    open_db,
    save_transcript,
    fetch_from_av as _av_fetch,
    refresh_latest_transcript,
    AVError,
)
from historic_fundamentals.audio_transcriber import convert_to_mp3, transcribe_audio
from api.research_router import _CHAT_TOOLS, _execute_tool

router = APIRouter()

OPENROUTER_MODELS = [
    "qwen/qwen3-235b-a22b-2507",
    "google/gemini-3.5-flash",
    "z-ai/glm-5.2",
    "qwen/qwen3.7-max",
    "minimax/minimax-m3",
]

_DB_PATH = Path(os.environ.get(
    "EARNINGS_DB_PATH",
    str(Path(__file__).parent.parent / "data" / "earnings_transcripts.duckdb"),
))

_AUDIO_DIR = Path(__file__).parent.parent / "data" / "earnings_calls_audio"

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
    try:
        result = _av_fetch(symbol, quarter, api_key)
    except AVError as exc:
        raise HTTPException(status_code=503, detail=f"Alpha Vantage error: {exc}")
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
        api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        conn = open_db(_DB_PATH)
        try:
            refresh_latest_transcript(conn, ticker, api_key)
        finally:
            conn.close()

        best = _latest_cached_quarter(ticker)
        if best is None:
            raise HTTPException(status_code=404, detail=f"No recent transcript found for {ticker}")
        quarter, transcript = best
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


@router.post("/earnings/import-audio")
async def import_transcript_from_audio(
    ticker: str,
    quarter: str,
    filename: str,
    model: str = OPENROUTER_MODELS[0],
):
    ticker = ticker.upper()

    if not re.match(r"^\d{4}Q[1-4]$", quarter):
        raise HTTPException(
            status_code=400,
            detail="Quarter must be in YYYYQN format (e.g. 2025Q1)",
        )

    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="filename must not contain path separators")

    audio_path = _AUDIO_DIR / filename
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found in audio directory")

    existing_source = _get_cached_source(ticker, quarter)
    if existing_source == "av":
        raise HTTPException(
            status_code=409,
            detail=f"Transcript for {ticker} {quarter} already exists from Alpha Vantage. Use 'Go' to generate a report.",
        )

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured")

    def _transcribe_and_save() -> str:
        mp3_path = convert_to_mp3(audio_path, _AUDIO_DIR)
        transcript = transcribe_audio(mp3_path, openrouter_key)
        conn = open_db(_DB_PATH)
        save_transcript(conn, ticker, quarter, transcript, api_json=None, source="audio")
        conn.close()
        return transcript

    transcript = await asyncio.to_thread(_transcribe_and_save)
    return await _run_llm(transcript, ticker, quarter, model)


# ---------------------------------------------------------------------------
# Earnings chat
# ---------------------------------------------------------------------------

class EarningsChatMessage(BaseModel):
    role: str
    content: str


class EarningsChatRequest(BaseModel):
    ticker: str
    quarter: str = "latest"
    model: str = OPENROUTER_MODELS[0]
    messages: list[EarningsChatMessage]
    report: Optional[str] = None


def _build_earnings_chat_system(
    ticker: str, quarter: str, report: Optional[str], transcript: Optional[str]
) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    quarter_label = quarter if quarter != "latest" else "latest quarter"

    report_section = (
        f"\n\nEARNINGS CALL SUMMARY — {ticker} {quarter_label}:\n{report}"
        if report else ""
    )
    transcript_section = (
        f"\n\nEARNINGS CALL TRANSCRIPT — {ticker} {quarter_label} (raw, use for specific quotes and details):\n{transcript}"
        if transcript else ""
    )

    return (
        f"You are an expert financial analyst assistant focused on earnings analysis.\n"
        f"Today is {today}. The user is analyzing {ticker}'s earnings call for {quarter_label}.\n\n"
        f"You have access to financial data tools:\n"
        f"- get_ticker_data: Get 5-year financials, valuation metrics, and quarterly trends for any ticker\n"
        f"- get_sector_data: Get current valuation and financial metrics for a sector or industry\n"
        f"- screen_stocks: Find stocks matching specific financial criteria\n\n"
        f"Be concise and precise. Lead with numbers and facts. Reference specific transcript details when relevant."
        f"{report_section}{transcript_section}"
    )


async def _earnings_chat_stream(req: EarningsChatRequest):
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        yield f"data: {json.dumps({'type': 'error', 'content': 'OPENROUTER_API_KEY not configured'})}\n\n"
        return

    ticker = req.ticker.upper()
    if req.quarter == "latest":
        cached = _latest_cached_quarter(ticker)
        transcript = cached[1] if cached else None
        resolved_quarter = cached[0] if cached else "latest"
    else:
        transcript = _get_cached(ticker, req.quarter)
        resolved_quarter = req.quarter

    client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)

    messages: list[dict] = [
        {"role": "system", "content": _build_earnings_chat_system(ticker, resolved_quarter, req.report, transcript)},
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

        messages.append({
            "role": "assistant",
            "content": "".join(content_chunks) or None,
            "tool_calls": [
                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["args"]}}
                for tc in tool_calls_acc.values()
            ],
        })

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


@router.post("/earnings/chat")
async def earnings_chat(req: EarningsChatRequest):
    return StreamingResponse(
        _earnings_chat_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
