"""
Data-gathering layer for the Industry AI Researcher.

Read-only, synchronous, thread-safe functions returning plain strings/dataframes — no LLM calls
here. Consumed by api/industry_research_router.py.

GRAIN GUARANTEE (SPEC.md section 2.1) — hard requirement, not a style preference:
This module operates strictly at the AV `industry` grain. No function here may silently widen
to `sector` scope. Concretely: member resolution filters on `UPPER(co.industry) = UPPER(?)` only
(no OR-fallback to sector like research_router.py's `_peer_df`), and aggregates read
`sector_stats WHERE group_type = 'industry'` only. A company with a null/blank industry
classification is excluded, never sector-substituted.
"""

from __future__ import annotations

import hashlib
import math
import os
import statistics
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from av_financials_db import RateLimiter
import historic_fundamentals.earnings_transcripts as et

_DATA_DIR = Path(__file__).parent.parent / "data"
_AV_FIN_DB = _DATA_DIR / "av_financials.duckdb"
_HIST_FUND_DB = _DATA_DIR / "historic_fundamentals.duckdb"
_EARNINGS_DB = _DATA_DIR / "earnings_transcripts.duckdb"

MEMBERS_CAP = 8
N_QUARTERS = 4


# ---------------------------------------------------------------------------
# Rate limiting for Alpha Vantage transcript/surprise probes (CLAUDE.md rule 7: <=75 calls/min)
# ---------------------------------------------------------------------------
# Uses av_financials_db.RateLimiter directly (it's a standalone class with no dependency on
# AVFinancialsDB — earnings_backfill.py/earnings_update.py already import it the same way) at
# max_calls=70, comfortably under the 75/min ceiling, shared across a whole batch call.


# ---------------------------------------------------------------------------
# Formatting helpers (module-local, mirrors the pattern in every other router file)
# ---------------------------------------------------------------------------

def is_missing(v) -> bool:
    """True for None, float NaN/inf, AND pandas' nullable-dtype NA sentinel (pd.NA) — DuckDB
    INTEGER columns with nulls come back as pandas nullable Int64, where a null is pd.NA, not a
    plain None or float NaN. A plain `v is None` / `math.isnan` check silently lets pd.NA through
    and crashes downstream on `int(pd.NA)` — found live via get_industry_estimates on
    eps_rev_up_7d/eps_rev_down_7d."""
    if v is None:
        return True
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return True
    return bool(pd.isna(v)) if pd.api.types.is_scalar(v) else False


def _f(v, fmt: str = ".1f") -> str:
    if is_missing(v):
        return "n/a"
    return f"{float(v):{fmt}}"


def _pct(v, fmt: str = "+.1f") -> str:
    if is_missing(v):
        return "n/a"
    return f"{float(v)*100:{fmt}}%"


# ---------------------------------------------------------------------------
# Industry picker + member resolution
# ---------------------------------------------------------------------------

def list_industries() -> list[dict]:
    """{industry, sector, member_count} for every classified industry, ordered by member_count
    desc. Powers the picker. sector is taken via ANY_VALUE — in practice an industry maps to a
    single sector; if AV data ever disagrees across snapshots, this shows whichever is seen
    first, which is acceptable for a display label.

    Excludes the literal string "None" alongside real NULL/blank — found live via Playwright UI
    testing: BBBY (a known contaminated ticker per the project's survivorship-bias findings —
    reassigned post-bankruptcy, see memory project_survivorship_bias_result.md) has industry
    literally set to the string "None" rather than a real NULL, which would otherwise appear as
    a selectable one-member "NONE" entry in the picker."""
    if not _AV_FIN_DB.exists():
        return []
    conn = duckdb.connect(str(_AV_FIN_DB), read_only=True)
    try:
        df = conn.execute("""
            WITH latest AS (
                SELECT ticker, sector, industry,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fetch_date DESC) AS rn
                FROM company_overview
            )
            SELECT industry, ANY_VALUE(sector) AS sector, COUNT(*) AS member_count
            FROM latest
            WHERE rn = 1 AND industry IS NOT NULL AND industry != '' AND UPPER(industry) != 'NONE'
            GROUP BY industry
            ORDER BY member_count DESC
        """).df()
    finally:
        conn.close()
    return df.to_dict(orient="records")


def resolve_members(
    industry: Optional[str], custom_tickers: Optional[list[str]] = None, cap: int = MEMBERS_CAP,
) -> list[str]:
    """Ordered ticker list for the report.

    Custom basket wins verbatim (uppercased, de-duped, order preserved) when provided — this is
    the escape hatch for industries too coarse even at AV grain (SPEC 2.1).

    Otherwise resolves top-`cap` members by market cap — COALESCE(pe_stats.market_cap_b,
    company_overview.market_cap), same preference as research_router._peer_df — filtered
    strictly on `UPPER(co.industry) = UPPER(?)`. There is deliberately no OR-fallback to sector:
    a company with a null/blank industry classification never matches any industry filter and is
    excluded, not sector-substituted.
    """
    if custom_tickers:
        seen: set[str] = set()
        out: list[str] = []
        for t in custom_tickers:
            u = t.strip().upper()
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    if not industry or not _AV_FIN_DB.exists() or not _HIST_FUND_DB.exists():
        return []

    conn = duckdb.connect(":memory:")
    try:
        conn.execute(f"ATTACH '{_HIST_FUND_DB}' AS hf (READ_ONLY)")
        conn.execute(f"ATTACH '{_AV_FIN_DB}' AS av (READ_ONLY)")
        rows = conn.execute("""
            WITH latest_co AS (
                SELECT ticker, industry, market_cap
                FROM av.company_overview
                QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fetch_date DESC) = 1
            )
            SELECT co.ticker
            FROM latest_co co
            LEFT JOIN hf.pe_stats ps ON ps.ticker = co.ticker
            WHERE UPPER(co.industry) = UPPER(?)
            ORDER BY COALESCE(ps.market_cap_b, co.market_cap / 1e9) DESC NULLS LAST
            LIMIT ?
        """, [industry, cap]).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def scope_key(industry: Optional[str], custom_tickers: Optional[list[str]] = None) -> str:
    """Stable, order-independent cache/status key: uppercased industry name for the
    classification path, or 'custom:' + a short sha1 of the sorted uppercased ticker set for a
    custom basket (so ['AMD','NVDA'] and ['NVDA','AMD'] share one cache entry)."""
    if custom_tickers:
        normalized = sorted({t.strip().upper() for t in custom_tickers if t.strip()})
        digest = hashlib.sha1(",".join(normalized).encode()).hexdigest()[:16]
        return f"custom:{digest}"
    return (industry or "").strip().upper()


# ---------------------------------------------------------------------------
# Industry-level quantitative aggregates (sector_stats, group_type='industry' ONLY)
# ---------------------------------------------------------------------------

def get_industry_aggregates_raw(industry: str) -> Optional[dict]:
    """Single source of truth for industry-level aggregates: the current sector_stats row
    (group_type='industry' ONLY — SPEC 2.1) plus 3/6/12-month prior snapshots for deltas.
    Fetched once per report; both the LLM-text formatter (get_industry_aggregates) and the
    markdown appendix renderer (industry_research_router.render_industry_aggregates_table)
    consume this same dict rather than re-querying independently."""
    if not _HIST_FUND_DB.exists():
        return None
    conn = duckdb.connect(str(_HIST_FUND_DB), read_only=True)
    try:
        current = conn.execute("""
            SELECT * FROM sector_stats
            WHERE group_type = 'industry' AND UPPER(group_name) = UPPER(?)
            ORDER BY month_end_date DESC LIMIT 1
        """, [industry]).df()
        if current.empty:
            return None
        row = current.iloc[0].to_dict()
        latest_date = row["month_end_date"]

        def _period_row(months: int):
            return conn.execute(f"""
                SELECT pe_median, evebitda_median, rev_growth_1yr_median
                FROM sector_stats
                WHERE group_type = 'industry' AND UPPER(group_name) = UPPER(?)
                  AND month_end_date >= ? - INTERVAL '{months} months'
                  AND month_end_date <= ? - INTERVAL '{months} months' + INTERVAL '1 month'
                ORDER BY month_end_date DESC LIMIT 1
            """, [industry, latest_date, latest_date]).fetchone()

        deltas = {months: _period_row(months) for months in (3, 6, 12)}
    finally:
        conn.close()
    return {"current": row, "deltas": deltas}


def format_industry_aggregates(raw: Optional[dict]) -> str:
    """Pure formatter (no DB access) — LLM-context text rendering of get_industry_aggregates_raw."""
    if raw is None:
        return "[ERROR] No industry aggregate data found"
    r, deltas = raw["current"], raw["deltas"]
    latest_date = r["month_end_date"]

    lines = [
        f"INDUSTRY AGGREGATES — {r['group_name']} "
        f"(as of {str(latest_date)[:7]}, {int(r['ticker_count'])} tickers measured)",
        "",
        f"P/E median:            {_f(r['pe_median'])}",
        f"P/FCF median:          {_f(r['pfcf_median'])}",
        f"EV/EBITDA median:      {_f(r['evebitda_median'])}",
        f"P/S median:            {_f(r['ps_median'])}",
        f"Revenue growth 1yr:    {_pct(r['rev_growth_1yr_median'])}",
        f"Earnings growth 1yr:   {_pct(r['earn_growth_1yr_median'])}",
        f"Gross margin:          {_pct(r['gross_margin_median'])}",
        f"Operating margin:      {_pct(r['operating_margin_median'])}",
        f"FCF margin:            {_pct(r['fcf_margin_median'])}",
        f"ROIC median:           {_pct(r['roic_median'])}",
        f"ROE median:            {_pct(r['roe_median'])}",
        f"Debt/EBITDA median:    {_f(r['debt_to_ebitda_median'])}",
        "",
    ]

    for months, label in [(3, "3mo"), (6, "6mo"), (12, "12mo")]:
        prior = deltas[months]
        if not prior:
            lines.append(f"{label} change — n/a (insufficient history)")
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
        lines.append(f"{label} change — P/E: {pe_chg}, EV/EBITDA: {ev_chg}, Rev growth: {gr_chg}")

    return "\n".join(lines)


def get_industry_aggregates(industry: str) -> str:
    """Industry valuation/margin/growth medians + 3/6/12-month deltas, strictly from
    sector_stats WHERE group_type='industry' — never 'sector' (SPEC 2.1). Thin wrapper over
    get_industry_aggregates_raw + format_industry_aggregates for callers that just want text."""
    if not _HIST_FUND_DB.exists():
        return "[ERROR] historic_fundamentals.duckdb not found"
    raw = get_industry_aggregates_raw(industry)
    if raw is None:
        return f"[ERROR] No industry aggregate data found for '{industry}'"
    return format_industry_aggregates(raw)


# ---------------------------------------------------------------------------
# Cross-company member financials (adapted from research_router._peer_df, sector-fallback
# branch removed — queried by an explicit ticker list, so there is no classification fallback
# to strip: this function has no notion of sector at all)
# ---------------------------------------------------------------------------

def get_member_financials_df(tickers: list[str]) -> pd.DataFrame:
    """Raw per-member financials, ordered by market cap desc. Every requested ticker appears as
    a row even if entirely absent from both DBs (all fields null except ticker) — a peer table
    must never silently drop a member for lacking data (Phase 0 finding: TSM's market_cap_b is
    null in pe_stats; the COALESCE fallback to company_overview.market_cap is load-bearing, not
    defensive boilerplate)."""
    cols = [
        "ticker", "name", "market_cap_b", "current_pe", "forward_pe", "current_pfcf",
        "rev_growth_1yr", "earn_growth_1yr", "current_roic", "current_gross_margin",
    ]
    if not tickers:
        return pd.DataFrame(columns=cols)
    if not _HIST_FUND_DB.exists() or not _AV_FIN_DB.exists():
        return pd.DataFrame(columns=cols)

    conn = duckdb.connect(":memory:")
    try:
        conn.execute(f"ATTACH '{_HIST_FUND_DB}' AS hf (READ_ONLY)")
        conn.execute(f"ATTACH '{_AV_FIN_DB}' AS av (READ_ONLY)")
        req_values = ",".join("(?)" for _ in tickers)
        df = conn.execute(f"""
            WITH req(ticker) AS (VALUES {req_values}),
            latest_co AS (
                SELECT ticker, name, market_cap
                FROM av.company_overview
                QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fetch_date DESC) = 1
            )
            SELECT
                req.ticker,
                co.name,
                COALESCE(ps.market_cap_b, co.market_cap / 1e9) AS market_cap_b,
                ps.current_pe, ps.forward_pe, ps.current_pfcf,
                ps.rev_growth_1yr, ps.earn_growth_1yr,
                ps.current_roic, ps.current_gross_margin
            FROM req
            LEFT JOIN hf.pe_stats ps ON ps.ticker = req.ticker
            LEFT JOIN latest_co co ON co.ticker = req.ticker
            ORDER BY COALESCE(ps.market_cap_b, co.market_cap / 1e9) DESC NULLS LAST
        """, tickers).df()
    finally:
        conn.close()
    return df


def format_member_financials(df: pd.DataFrame) -> str:
    """Pure formatter (no DB access) — LLM-context text rendering of get_member_financials_df's
    output (mirrors research_router.get_peer_comparison's layout). Split out so Phase 4's
    synthesis orchestrator can format an already-fetched dataframe for the Chief's prompt without
    re-querying — same raw/format-split pattern as get_industry_aggregates and
    get_industry_beat_miss (PLAN.md Phase 1 finding)."""
    if df.empty:
        return "[INFO] No member financials available"

    lines = [f"MEMBER FINANCIALS — {len(df)} companies", ""]
    lines.append(
        f"{'Ticker':<8} {'Company':<26} {'MCap$B':>8} {'PE':>6} {'FwdPE':>6} "
        f"{'P/FCF':>6} {'RevGr':>7} {'EarGr':>7} {'ROIC':>7} {'GrossM':>7}"
    )
    lines.append("-" * 98)
    for _, r in df.iterrows():
        lines.append(
            f"{str(r['ticker']):<8} "
            f"{str(r['name'] or '')[:25]:<26} "
            f"{_f(r['market_cap_b']):>8} "
            f"{_f(r['current_pe']):>6} "
            f"{_f(r['forward_pe']):>6} "
            f"{_f(r['current_pfcf']):>6} "
            f"{_pct(r['rev_growth_1yr']):>7} "
            f"{_pct(r['earn_growth_1yr']):>7} "
            f"{_pct(r['current_roic']):>7} "
            f"{_pct(r['current_gross_margin']):>7}"
        )
    return "\n".join(lines)


def get_member_financials(tickers: list[str]) -> str:
    """Text formatting of get_member_financials_df for LLM sub-agent context. Thin wrapper over
    get_member_financials_df + format_member_financials for callers that just want text."""
    return format_member_financials(get_member_financials_df(tickers))


# ---------------------------------------------------------------------------
# EPS beat/miss dispersion
# ---------------------------------------------------------------------------

def get_beat_miss_raw(tickers: list[str]) -> dict[str, Optional[list[dict]]]:
    """Single source of truth for beat/miss data: {ticker: [surprise rows] or None}. This is the
    ONLY place that fetches from Alpha Vantage for surprises — both the LLM-text formatter
    (get_industry_beat_miss) and the markdown appendix renderer
    (industry_research_router.render_beat_miss_table) must consume this same dict rather than
    each independently fetching, which would double the AV calls for the same tickers in one
    report generation pass (rate-limit relevant, CLAUDE.md rule 7)."""
    if not tickers:
        return {}
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    limiter = RateLimiter(max_calls=70, period=60.0) if api_key else None
    conn = et.open_db(_EARNINGS_DB)
    per_member: dict[str, Optional[list[dict]]] = {}
    try:
        for t in tickers:
            rows = et.get_cached_surprises(conn, t)
            if rows is None and api_key:
                limiter.wait()
                try:
                    fetched = et.fetch_surprises_from_av(t, api_key)
                except Exception:
                    fetched = None
                if fetched:
                    et.save_surprises(conn, t, fetched)
                    rows = fetched
            per_member[t] = rows
    finally:
        conn.close()
    return per_member


def format_beat_miss(tickers: list[str], raw: dict[str, Optional[list[dict]]]) -> str:
    """Pure formatter (no DB/network access) — LLM-context text rendering of get_beat_miss_raw."""
    if not tickers:
        return "[INFO] No members to compare"

    lines = [f"EPS BEAT/MISS — {len(tickers)} members (latest quarter each)", ""]
    latest_surprises: list[float] = []
    for t in tickers:
        rows = raw.get(t)
        if not rows:
            lines.append(f"  {t}: no data")
            continue
        latest = rows[0]
        surprise = latest.get("surprise_pct")
        if surprise is not None:
            latest_surprises.append(float(surprise))
        surprise_txt = f"{surprise:+.1f}%" if surprise is not None else "n/a"
        fiscal_end = str(latest.get("fiscal_date_ending"))[:10]
        lines.append(f"  {t}: latest quarter surprise {surprise_txt} ({fiscal_end})")

    if latest_surprises:
        n_beat = sum(1 for s in latest_surprises if s > 0)
        lines += [
            "",
            f"Dispersion: {n_beat}/{len(latest_surprises)} members beat estimates last quarter "
            f"(median surprise {statistics.median(latest_surprises):+.1f}%)",
        ]
    return "\n".join(lines)


def get_industry_beat_miss(tickers: list[str]) -> str:
    """Per-member latest-quarter EPS surprise + cross-company dispersion summary (% beating,
    median surprise). Thin wrapper over get_beat_miss_raw + format_beat_miss for callers that
    just want text."""
    if not tickers:
        return "[INFO] No members to compare"
    return format_beat_miss(tickers, get_beat_miss_raw(tickers))


# ---------------------------------------------------------------------------
# Estimate revision momentum
# ---------------------------------------------------------------------------

def get_estimates_df(tickers: list[str]) -> pd.DataFrame:
    """Single source of truth for estimate-revision data (next fiscal quarter, one row per
    ticker). Both the LLM-text formatter (get_industry_estimates) and the markdown appendix
    renderer (industry_research_router.render_revision_momentum_table) consume this same
    dataframe rather than re-querying independently."""
    cols = ["ticker", "fiscal_date", "eps_avg", "eps_avg_7d", "eps_avg_30d",
            "eps_rev_up_7d", "eps_rev_down_7d"]
    if not tickers or not _HIST_FUND_DB.exists():
        return pd.DataFrame(columns=cols)

    conn = duckdb.connect(str(_HIST_FUND_DB), read_only=True)
    try:
        placeholders = ",".join("?" for _ in tickers)
        df = conn.execute(f"""
            WITH latest AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY ticker ORDER BY fiscal_date ASC, fetched_at DESC
                ) AS rn
                FROM earnings_estimates
                WHERE ticker IN ({placeholders}) AND horizon = 'fiscal quarter'
                  AND fiscal_date >= today()
            )
            SELECT ticker, fiscal_date, eps_avg, eps_avg_7d, eps_avg_30d,
                   eps_rev_up_7d, eps_rev_down_7d
            FROM latest WHERE rn = 1
        """, tickers).df()
    finally:
        conn.close()
    return df


def format_estimates(tickers: list[str], df: pd.DataFrame) -> str:
    """Pure formatter (no DB access) — LLM-context text rendering of get_estimates_df."""
    if not tickers:
        return "[INFO] No members to compare"

    def _rev_pct(a, b) -> str:
        if is_missing(a) or is_missing(b) or float(b) == 0:
            return "n/a"
        return f"{(float(a) - float(b)) / abs(float(b)) * 100:+.1f}%"

    rows_by_ticker = {r["ticker"]: r for _, r in df.iterrows()}
    lines = [f"ESTIMATE REVISION MOMENTUM — {len(tickers)} members (next fiscal quarter)", ""]
    for t in tickers:
        r = rows_by_ticker.get(t)
        if r is None:
            lines.append(f"  {t}: no estimate data")
            continue
        vs7 = _rev_pct(r["eps_avg"], r["eps_avg_7d"])
        vs30 = _rev_pct(r["eps_avg"], r["eps_avg_30d"])
        up = 0 if is_missing(r["eps_rev_up_7d"]) else int(r["eps_rev_up_7d"])
        dn = 0 if is_missing(r["eps_rev_down_7d"]) else int(r["eps_rev_down_7d"])
        eps_txt = "n/a" if is_missing(r["eps_avg"]) else f"${float(r['eps_avg']):.2f}"
        lines.append(
            f"  {t}: EPS est {eps_txt}, vs 7d {vs7}, vs 30d {vs30}, revisions(7d) {up}up/{dn}dn"
        )
    return "\n".join(lines)


def get_industry_estimates(tickers: list[str]) -> str:
    """Per-member forward EPS estimate + 7d/30d revision momentum for the next fiscal quarter.
    Thin wrapper over get_estimates_df + format_estimates for callers that just want text."""
    if not tickers:
        return "[INFO] No members to compare"
    if not _HIST_FUND_DB.exists():
        return "[ERROR] historic_fundamentals.duckdb not found"
    return format_estimates(tickers, get_estimates_df(tickers))


# ---------------------------------------------------------------------------
# Earnings call transcripts
# ---------------------------------------------------------------------------

def get_industry_transcripts(
    tickers: list[str], n: int = N_QUARTERS,
) -> dict[str, list[tuple[str, str]]]:
    """{ticker: [(quarter, text), ...]} newest-first, up to n quarters each.

    Probes AV for a quarter newer than the local cache per ticker (et.refresh_latest_transcript,
    shared with research_router.get_earnings_trend_summary), then reads whatever is cached. A
    shared rate limiter caps AV calls across the whole batch at <=70/min, comfortably under the
    75/min ceiling (CLAUDE.md rule 7) even in the worst case (every ticker's cache is cold and
    every quarter must be probed).

    Degrades to fewer/zero quarters per ticker silently — never raises for a missing member.
    Phase 0 confirmed this is a real case, not hypothetical: TSM (Semiconductors, ADR) has zero
    cached transcripts in earnings_transcripts.duckdb.
    """
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    limiter = RateLimiter(max_calls=70, period=60.0) if api_key else None
    conn = et.open_db(_EARNINGS_DB)
    result: dict[str, list[tuple[str, str]]] = {}
    try:
        for ticker in tickers:
            et.refresh_latest_transcript(conn, ticker, api_key, limiter=limiter)
            result[ticker] = et.get_last_n_transcripts(conn, ticker, n)
    finally:
        conn.close()
    return result


# ---------------------------------------------------------------------------
# Web search (industry-keyed — never the sector name, SPEC 2.1)
# ---------------------------------------------------------------------------

def get_industry_web_search(industry: str) -> str:
    from api.research_router import _tavily_search
    return _tavily_search(
        f"{industry} industry trends outlook demand pricing 2025 2026",
        f"WEB SEARCH RESULTS — {industry} industry",
    )
