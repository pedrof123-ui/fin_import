"""
FastAPI backend for the financial statements web app.

Run from project root:
    uv run uvicorn api.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import sys
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from financial_statements_db import FinancialStatementsDB
from api.db import list_tickers, get_statements
from api.importer import import_ticker
from api.dcf_router import router as dcf_router, set_db as dcf_set_db
from api.av_router import router as av_router, set_db as av_set_db
from api.earnings_router import router as earnings_router
from api.research_router import router as research_router
from api.screener_router import router as screener_router
from api.sector_router import router as sector_router
from api.estimates_router import router as estimates_router
from api.earnings_calendar_router import router as earnings_calendar_router
from api.news_router import router as news_router

DB_PATH = Path(__file__).parent.parent / "data" / "financial_statements.duckdb"

db: FinancialStatementsDB | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    db = FinancialStatementsDB(str(DB_PATH))
    dcf_set_db(db)
    av_set_db(db)
    yield
    db.close()


app = FastAPI(title="Financial Statements API", lifespan=lifespan)
app.include_router(dcf_router)
app.include_router(av_router)
app.include_router(earnings_router)
app.include_router(research_router)
app.include_router(screener_router)
app.include_router(sector_router)
app.include_router(estimates_router)
app.include_router(earnings_calendar_router)
app.include_router(news_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ImportRequest(BaseModel):
    ticker: str
    periods: int = 20
    period_type: Literal["FY", "Q"] = "FY"
    force: bool = False


@app.get("/tickers")
async def tickers_endpoint():
    return list_tickers(db)


@app.get("/statements/{ticker}/{stmt_type}")
async def statements_endpoint(
    ticker: str,
    stmt_type: Literal["income", "balance", "cashflow"],
    period_type: str = "FY",
    periods: int = 10,
):
    data = get_statements(db, ticker.upper(), stmt_type, period_type, periods)
    if data is None:
        raise HTTPException(status_code=404, detail=f"No data found for {ticker}")
    return data


@app.post("/import")
async def import_endpoint(req: ImportRequest):
    result = await import_ticker(req.ticker.upper(), req.periods, req.period_type, db, force=req.force)
    return result
