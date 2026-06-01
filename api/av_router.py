import dataclasses
import json
import os
from pathlib import Path
from typing import Literal

import duckdb
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from dcf.model import run_dcf_av
from api.dcf_router import RunRequest, _build_overrides, _sanitize

router = APIRouter()

_AV_DB = Path(os.environ.get(
    "AV_FINANCIALS_DB_PATH",
    str(Path(__file__).parent.parent / "data" / "av_financials.duckdb"),
))

_TABLE = {
    "income":   "income_statements",
    "balance":  "balance_sheets",
    "cashflow": "cash_flow_statements",
}

# Populated by main.py via set_db() — shared with dcf_router to avoid double-open
_db = None


def set_db(db) -> None:
    global _db
    _db = db


@router.get("/av-financials/{ticker}/{stmt}")
async def av_financials(
    ticker: str,
    stmt: Literal["income", "balance", "cashflow"],
    period_type: str = "annual",
    periods: int = 20,
):
    table = _TABLE[stmt]
    order = "ASC" if period_type == "quarterly" else "DESC"
    try:
        conn = duckdb.connect(str(_AV_DB), read_only=True)
        df = conn.execute(
            f"""SELECT * FROM {table}
                WHERE ticker = ? AND period_type = ?
                ORDER BY fiscal_date_ending {order}
                LIMIT ?""",
            [ticker.upper(), period_type, periods],
        ).df()
        conn.close()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No AV {period_type} {stmt} data for {ticker} — import via av_financials_db first",
        )

    return json.loads(df.to_json(orient="records", date_format="iso"))


def _respond_av(ticker: str, overrides=None) -> JSONResponse:
    estimates_conn = _db.conn if _db is not None else None
    try:
        result = run_dcf_av(ticker, overrides, estimates_conn=estimates_conn)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return JSONResponse(_sanitize(dataclasses.asdict(result)))


@router.get("/av-dcf/{ticker}")
async def av_dcf_get(ticker: str):
    return _respond_av(ticker.upper())


@router.post("/av-dcf/{ticker}/run")
async def av_dcf_run(ticker: str, req: RunRequest):
    return _respond_av(ticker.upper(), _build_overrides(req))
