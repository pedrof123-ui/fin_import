import os
from datetime import datetime, timedelta, date

import requests


_CACHE_DAYS = 30
_AV_URL = "https://www.alphavantage.co/query"


def fetch_and_cache(ticker: str, conn) -> list[dict]:
    """
    Returns normalized earnings estimate dicts for ticker.
    Uses DB cache (30-day TTL); fetches from Alpha Vantage when stale.
    Returns empty list on any failure.
    """
    cached = _get_cached(conn, ticker)
    if cached is not None:
        return cached

    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        return []

    try:
        resp = requests.get(
            _AV_URL,
            params={"function": "EARNINGS_ESTIMATES", "symbol": ticker, "apikey": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json().get("estimates", [])
    except Exception:
        return []

    if not raw:
        return []

    _store(conn, ticker, raw)
    return [_normalize(e) for e in raw]


def _get_cached(conn, ticker: str) -> list[dict] | None:
    cutoff = datetime.utcnow() - timedelta(days=_CACHE_DAYS)
    df = conn.execute(
        """
        SELECT *
        FROM earnings_estimates
        WHERE ticker = ?
          AND fetched_at = (SELECT MAX(fetched_at) FROM earnings_estimates WHERE ticker = ?)
          AND fetched_at >= ?
        ORDER BY date DESC
        """,
        [ticker, ticker, cutoff],
    ).df()
    if df.empty:
        return None
    return [_from_db_row(r) for r in df.to_dict("records")]


def _store(conn, ticker: str, raw: list[dict]) -> None:
    conn.execute("DELETE FROM earnings_estimates WHERE ticker = ?", [ticker])
    fetched_at = datetime.utcnow()
    for e in raw:
        conn.execute(
            """
            INSERT INTO earnings_estimates (
                ticker, date, horizon, fetched_at,
                eps_avg, eps_high, eps_low, eps_count,
                eps_avg_7d, eps_avg_30d, eps_avg_60d, eps_avg_90d,
                eps_rev_up_7d, eps_rev_down_7d, eps_rev_up_30d, eps_rev_down_30d,
                rev_avg, rev_high, rev_low, rev_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ticker,
                e.get("date"),
                e.get("horizon"),
                fetched_at,
                _f(e.get("eps_estimate_average")),
                _f(e.get("eps_estimate_high")),
                _f(e.get("eps_estimate_low")),
                _i(e.get("eps_estimate_analyst_count")),
                _f(e.get("eps_estimate_average_7_days_ago")),
                _f(e.get("eps_estimate_average_30_days_ago")),
                _f(e.get("eps_estimate_average_60_days_ago")),
                _f(e.get("eps_estimate_average_90_days_ago")),
                _i(e.get("eps_estimate_revision_up_trailing_7_days")),
                _i(e.get("eps_estimate_revision_down_trailing_7_days")),
                _i(e.get("eps_estimate_revision_up_trailing_30_days")),
                _i(e.get("eps_estimate_revision_down_trailing_30_days")),
                _f(e.get("revenue_estimate_average")),
                _f(e.get("revenue_estimate_high")),
                _f(e.get("revenue_estimate_low")),
                _i(e.get("revenue_estimate_analyst_count")),
            ],
        )


def _normalize(e: dict) -> dict:
    return {
        "date": e.get("date", ""),
        "horizon": e.get("horizon", ""),
        "eps_avg": _f(e.get("eps_estimate_average")),
        "eps_high": _f(e.get("eps_estimate_high")),
        "eps_low": _f(e.get("eps_estimate_low")),
        "eps_count": _i(e.get("eps_estimate_analyst_count")),
        "eps_avg_7d": _f(e.get("eps_estimate_average_7_days_ago")),
        "eps_avg_30d": _f(e.get("eps_estimate_average_30_days_ago")),
        "eps_avg_60d": _f(e.get("eps_estimate_average_60_days_ago")),
        "eps_avg_90d": _f(e.get("eps_estimate_average_90_days_ago")),
        "rev_avg": _f(e.get("revenue_estimate_average")),
        "rev_high": _f(e.get("revenue_estimate_high")),
        "rev_low": _f(e.get("revenue_estimate_low")),
        "rev_count": _i(e.get("revenue_estimate_analyst_count")),
    }


def _from_db_row(r: dict) -> dict:
    return {
        "date": str(r["date"])[:10],
        "horizon": r.get("horizon", ""),
        "eps_avg": r.get("eps_avg"),
        "eps_high": r.get("eps_high"),
        "eps_low": r.get("eps_low"),
        "eps_count": r.get("eps_count"),
        "eps_avg_7d": r.get("eps_avg_7d"),
        "eps_avg_30d": r.get("eps_avg_30d"),
        "eps_avg_60d": r.get("eps_avg_60d"),
        "eps_avg_90d": r.get("eps_avg_90d"),
        "rev_avg": r.get("rev_avg"),
        "rev_high": r.get("rev_high"),
        "rev_low": r.get("rev_low"),
        "rev_count": r.get("rev_count"),
    }


def to_dataclass(estimates: list[dict]) -> list:
    from dcf.assumptions import EarningsEstimate

    return [
        EarningsEstimate(
            date=e["date"],
            horizon=e["horizon"],
            eps_estimate_avg=e.get("eps_avg"),
            eps_estimate_high=e.get("eps_high"),
            eps_estimate_low=e.get("eps_low"),
            eps_analyst_count=e.get("eps_count"),
            revenue_estimate_avg=e.get("rev_avg"),
            revenue_estimate_high=e.get("rev_high"),
            revenue_estimate_low=e.get("rev_low"),
            revenue_analyst_count=e.get("rev_count"),
        )
        for e in estimates
    ]


def apply_to_forecasts(
    estimates: list[dict],
    year_forecasts: list,
    last_actual_revenue: float,
    last_annual_year: int,
    last_annual_date: str,
    user_overrides,
) -> tuple[list, dict[int, float], set[int]]:
    """
    Modifies year_forecasts in-place with analyst annual revenue estimates.
    Returns (year_forecasts, quarterly_revenue_overrides, analyst_year_offsets).
    analyst_year_offsets is the set of yf.year values where analyst revenues were applied.
    Analyst estimates are applied only where the user has not explicitly overridden.
    """
    # --- Annual estimates ---
    annual_by_year = {
        _parse_year(e["date"]): e
        for e in estimates
        if e.get("horizon") == "fiscal year" and e.get("rev_avg")
    }

    analyst_years: set[int] = set()
    prev_rev = last_actual_revenue
    for yf in year_forecasts:
        target_year = last_annual_year + yf.year
        est = annual_by_year.get(target_year)
        if est is None:
            # Cascade from last resolved revenue using existing growth rate
            yf.revenue = prev_rev * (1 + yf.revenue_growth)
            prev_rev = yf.revenue
            continue

        analyst_rev = float(est["rev_avg"])

        # Skip applying to model if user explicitly overrode this year's growth.
        # Advance prev_rev by the user's growth rate so subsequent analyst estimates
        # anchor correctly to what merge_overrides will actually compute for this year.
        if _user_has_rev_override(user_overrides, yf.year):
            user_growth = user_overrides.years[yf.year].revenue_growth
            prev_rev = prev_rev * (1 + user_growth)
            continue

        yf.revenue_growth = (analyst_rev - prev_rev) / prev_rev if prev_rev else yf.revenue_growth
        yf.revenue = analyst_rev
        prev_rev = analyst_rev
        analyst_years.add(yf.year)

    # --- Quarterly estimates ---
    try:
        last_dt = date.fromisoformat(last_annual_date[:10])
    except (ValueError, TypeError):
        return year_forecasts, {}, analyst_years

    today = date.today()
    y1_end = date(last_dt.year + 1, last_dt.month, last_dt.day)
    fy_start = date(last_dt.year, last_dt.month, last_dt.day) + timedelta(days=1)

    quarterly_revs: dict[int, float] = {}
    for e in estimates:
        if e.get("horizon") != "fiscal quarter" or not e.get("rev_avg"):
            continue
        try:
            d = date.fromisoformat(e["date"][:10])
        except ValueError:
            continue
        if d <= today or d > y1_end:
            continue
        q_idx = _quarter_index(d, fy_start)
        if 1 <= q_idx <= 4:
            quarterly_revs[q_idx] = float(e["rev_avg"])

    return year_forecasts, quarterly_revs, analyst_years


def _quarter_index(d: date, fy_start: date) -> int:
    months = (d.year - fy_start.year) * 12 + (d.month - fy_start.month)
    return months // 3 + 1


def _user_has_rev_override(overrides, year: int) -> bool:
    if overrides is None:
        return False
    yo = overrides.years.get(year)
    return yo is not None and yo.revenue_growth is not None


def _parse_year(date_str: str) -> int | None:
    try:
        return int(date_str[:4])
    except (ValueError, TypeError):
        return None


def _f(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if f != f else f  # NaN guard
    except (TypeError, ValueError):
        return None


def _i(val) -> int | None:
    f = _f(val)
    return int(f) if f is not None else None
