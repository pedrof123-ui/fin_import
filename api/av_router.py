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


def _fiscal_quarter_label(period_end, fy_end_month: int) -> str:
    """Compute fiscal quarter label (e.g. 'Q1 2027') from a period-end date.

    Uses the company's fiscal year end month so that companies like NVDA (FY ends
    January) or AAPL (FY ends September) get correct labels instead of calendar ones.
    """
    if hasattr(period_end, "month"):
        m, y = period_end.month, period_end.year
    else:
        parts = str(period_end).split("-")
        y, m = int(parts[0]), int(parts[1])
    # Fiscal year: if period ends on/before FY-end month it's in that calendar year's
    # fiscal year; otherwise it belongs to the following fiscal year.
    fiscal_year = y if m <= fy_end_month else y + 1
    # Quarter within the fiscal year (FY starts the month after fy_end_month)
    fy_start_month = (fy_end_month % 12) + 1
    fiscal_quarter = (m - fy_start_month + 12) % 12 // 3 + 1
    return f"Q{fiscal_quarter} {fiscal_year}"


_AV_DB = Path(os.environ.get(
    "AV_FINANCIALS_DB_PATH",
    str(Path(__file__).parent.parent / "data" / "av_financials.duckdb"),
))

_HF_DB = Path(os.environ.get(
    "HF_DB_PATH",
    str(Path(__file__).parent.parent / "data" / "historic_fundamentals.duckdb"),
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
):
    table = _TABLE[stmt]
    try:
        conn = duckdb.connect(str(_AV_DB), read_only=True)
        df = conn.execute(
            f"""SELECT * FROM {table}
                WHERE ticker = ? AND period_type = ?
                ORDER BY fiscal_date_ending DESC""",
            [ticker.upper(), period_type],
        ).df()

        if period_type == "quarterly" and not df.empty:
            # Determine fiscal year end month from annual data so that non-December
            # fiscal years (NVDA=Jan, AAPL=Sep, MSFT=Jun, …) get correct Q labels.
            annual_row = conn.execute(
                f"""SELECT fiscal_date_ending FROM {table}
                    WHERE ticker = ? AND period_type = 'annual'
                    ORDER BY fiscal_date_ending DESC LIMIT 1""",
                [ticker.upper()],
            ).fetchone()
            if annual_row:
                fy_end = annual_row[0]
                fy_end_month = fy_end.month if hasattr(fy_end, "month") else int(str(fy_end).split("-")[1])
                df["period_label"] = df["fiscal_date_ending"].apply(
                    lambda d: _fiscal_quarter_label(d, fy_end_month)
                )

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
    estimates_conn = duckdb.connect(str(_HF_DB))
    try:
        result = run_dcf_av(ticker, overrides, estimates_conn=estimates_conn)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        estimates_conn.close()
    return JSONResponse(_sanitize(dataclasses.asdict(result)))


def _sf(v) -> float | None:
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _si(v) -> int | None:
    f = _sf(v)
    return int(f) if f is not None else None


def _sdiv(v, d: float) -> float | None:
    f = _sf(v)
    return f / d if f is not None else None


_STAT_FIELDS = [
    "current_pe", "forward_pe", "pe_lt_median", "pe_p25", "pe_p75", "pe_rolling_5yr_median",
    "current_pfcf", "forward_pfcf", "pfcf_lt_median", "pfcf_p25", "pfcf_p75", "pfcf_rolling_5yr_median",
    "current_evebitda", "forward_evebitda", "evebitda_lt_median", "evebitda_p25", "evebitda_p75",
    "evebitda_rolling_5yr_median",
    "current_ps", "forward_ps", "ps_lt_median", "ps_p25", "ps_p75", "ps_rolling_5yr_median",
    "current_pbv", "pbv_lt_median", "pbv_rolling_5yr_median",
    "current_roa", "roa_lt_median", "roa_rolling_5yr_median",
    "current_roe", "roe_lt_median", "roe_rolling_5yr_median",
    "current_roic", "roic_lt_median", "roic_rolling_5yr_median",
    "rev_growth_1yr", "rev_cagr_3yr", "rev_cagr_5yr", "rev_ntm_growth_est",
    "earn_growth_1yr", "earn_cagr_3yr", "earn_cagr_5yr", "earn_ntm_growth_est",
    "current_gross_margin", "gross_margin_5y_median",
    "current_operating_margin", "operating_margin_5y_median", "operating_margin_change_3y",
    "current_fcf_margin", "fcf_margin_5y_median", "fcf_margin_change_3y",
    "goal_pe", "goal_pcf", "goal_peg", "goal_bv", "goal_2x", "goal_low", "goal_high",
    "current_ttm_eps", "forward_12m_eps", "dividend_yield",
    "debt_to_ebitda", "interest_coverage",
]


@router.get("/av-fundamentals/{ticker}")
async def av_fundamentals_snapshot(ticker: str):
    t = ticker.upper()
    try:
        hf = duckdb.connect(str(_HF_DB), read_only=True)
        av = duckdb.connect(str(_AV_DB), read_only=True)

        stats_df = hf.execute("SELECT * FROM pe_stats WHERE ticker = ?", [t]).df()
        if stats_df.empty:
            hf.close()
            av.close()
            raise HTTPException(
                status_code=404,
                detail=f"No fundamentals data for {t}. Run: uv run python scripts/manage_tickers.py add {t}",
            )

        series_df = hf.execute(
            """SELECT month_end_date AS date, price,
                      pe_ratio, pe_rolling_5yr_median,
                      pfcf_ratio, pfcf_rolling_5yr_median,
                      ev_ebitda, ev_ebitda_rolling_5yr_median,
                      ps_ratio, ps_rolling_5yr_median,
                      roa, roe, roic,
                      ttm_gross_margin, ttm_operating_margin, ttm_fcf_margin
               FROM monthly_pe
               WHERE ticker = ?
                 AND month_end_date >= (CURRENT_DATE - INTERVAL 10 YEAR)
               ORDER BY month_end_date ASC""",
            [t],
        ).df()

        est_df = hf.execute(
            """SELECT CAST(fiscal_date AS VARCHAR) AS date, horizon,
                      eps_avg, eps_high, eps_low, eps_count,
                      rev_avg, rev_high, rev_low, rev_count
               FROM earnings_estimates
               WHERE ticker = ?
                 AND fetched_at = (SELECT MAX(fetched_at) FROM earnings_estimates WHERE ticker = ?)
                 AND fiscal_date > CURRENT_DATE
               ORDER BY fiscal_date ASC""",
            [t, t],
        ).df()

        ov_df = av.execute(
            """SELECT name, sector, industry, market_cap,
                      analyst_target_price,
                      analyst_rating_strong_buy, analyst_rating_buy,
                      analyst_rating_hold, analyst_rating_sell,
                      analyst_rating_strong_sell,
                      fetch_date
               FROM company_overview
               WHERE ticker = ?
               ORDER BY fetch_date DESC LIMIT 1""",
            [t],
        ).df()

        hf.close()
        av.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    row = stats_df.iloc[0].to_dict()
    ov = ov_df.iloc[0].to_dict() if not ov_df.empty else {}

    payload = {
        "ticker": t,
        "company_name": ov.get("name"),
        "sector": ov.get("sector"),
        "industry": ov.get("industry"),
        "market_cap_b": _sdiv(ov.get("market_cap"), 1e9),
        "current_price": row.get("current_price"),
        "analyst_target_price": _sf(ov.get("analyst_target_price")),
        "analyst_strong_buy": _si(ov.get("analyst_rating_strong_buy")),
        "analyst_buy": _si(ov.get("analyst_rating_buy")),
        "analyst_hold": _si(ov.get("analyst_rating_hold")),
        "analyst_sell": _si(ov.get("analyst_rating_sell")),
        "analyst_strong_sell": _si(ov.get("analyst_rating_strong_sell")),
        "overview_updated_at": str(ov.get("fetch_date", "")),
        **{k: row.get(k) for k in _STAT_FIELDS},
        "monthly_series": json.loads(
            series_df.to_json(orient="records", date_format="iso")
        ),
        "analyst_estimates": json.loads(
            est_df.to_json(orient="records", date_format="iso")
        ) if not est_df.empty else [],
        "stats_updated_at": str(row.get("updated_at", "")),
    }
    return _sanitize(payload)


@router.get("/av-dcf/{ticker}")
async def av_dcf_get(ticker: str):
    return _respond_av(ticker.upper())


@router.post("/av-dcf/{ticker}/run")
async def av_dcf_run(ticker: str, req: RunRequest):
    return _respond_av(ticker.upper(), _build_overrides(req))
