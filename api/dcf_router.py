import dataclasses
import math
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from dcf import run_dcf
from dcf.assumptions import UserOverrides, YearOverride

router = APIRouter(prefix="/dcf", tags=["dcf"])

# Populated by main.py via set_db()
_db = None


def set_db(db) -> None:
    global _db
    _db = db


# ---------------------------------------------------------------------------
# Request body for POST /dcf/{ticker}/run
# ---------------------------------------------------------------------------

class YearOverrideBody(BaseModel):
    revenue_growth: float | None = None
    cogs_pct: float | None = None
    sga_pct: float | None = None
    rd_pct: float | None = None
    interest_pct: float | None = None
    other_pct: float | None = None
    capex_pct_revenue: float | None = None


class RunRequest(BaseModel):
    years: dict[str, YearOverrideBody] = {}   # keys "1"–"5" (JSON strings)
    terminal_growth_rate: float | None = None
    risk_free_rate: float | None = None
    market_risk_premium: float | None = None
    beta: float | None = None
    dso: float | None = None
    dpo: float | None = None
    dio: float | None = None
    cost_of_debt: float | None = None
    tax_rate: float | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize(obj: Any) -> Any:
    """Recursively replace NaN/inf with None so the response is valid JSON."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _build_overrides(req: RunRequest) -> UserOverrides:
    year_map = {
        int(k): YearOverride(
            revenue_growth=v.revenue_growth,
            cogs_pct=v.cogs_pct,
            sga_pct=v.sga_pct,
            rd_pct=v.rd_pct,
            interest_pct=v.interest_pct,
            other_pct=v.other_pct,
            capex_pct_revenue=v.capex_pct_revenue,
        )
        for k, v in req.years.items()
    }
    return UserOverrides(
        years=year_map,
        terminal_growth_rate=req.terminal_growth_rate,
        risk_free_rate=req.risk_free_rate,
        market_risk_premium=req.market_risk_premium,
        beta=req.beta,
        dso=req.dso,
        dpo=req.dpo,
        dio=req.dio,
        cost_of_debt_override=req.cost_of_debt,
        tax_rate_override=req.tax_rate,
    )


def _respond(ticker: str, overrides: UserOverrides | None = None) -> JSONResponse:
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not initialised")
    try:
        result = run_dcf(ticker, _db, overrides)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return JSONResponse(_sanitize(dataclasses.asdict(result)))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{ticker}")
async def dcf_get(ticker: str):
    """Compute DCF with model defaults."""
    return _respond(ticker.upper())


@router.post("/{ticker}/run")
async def dcf_run(ticker: str, req: RunRequest):
    """Re-run DCF with user-supplied assumption overrides."""
    return _respond(ticker.upper(), _build_overrides(req))
