"""
Data-gathering layer for the Agentic AI DCF Valuator (features/ai_dcf/SPEC.md).

Every function here is synchronous and read-only against the project's existing DuckDBs (no
new domain tables) and degrades to an `[INFO]`/`[ERROR]` placeholder string on missing data —
a missing input never fails the run, it just tells the corresponding evidence agent the input
is unavailable. Nothing here re-fetches what a caller already has; `build_*_context` helpers
take already-fetched pieces so the orchestrator gathers each input exactly once per run.

Price-blind by construction: nothing in this module reads the target's current price, market
cap, or analyst price target. Peer market caps/multiples are fine (not the target's own price).
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from dcf.av_data import load_av_annual_financials
from dcf.forecaster import compute_nwc_days
from dcf.wacc import DEFAULT_MRP, compute_effective_tax_rate, get_betas
from dcf.data import load_risk_free_rate, load_risk_free_rate_30y
import historic_fundamentals.earnings_transcripts as et
import historic_fundamentals.mda as mda
from api.industry_data import get_industry_aggregates, get_industry_web_search, scope_key

_DATA_DIR = Path(__file__).parent.parent / "data"
_AV_FIN_DB = _DATA_DIR / "av_financials.duckdb"
_HIST_FUND_DB = _DATA_DIR / "historic_fundamentals.duckdb"
_INDUSTRY_CACHE_DB = _DATA_DIR / "industry_research_cache.duckdb"

MDA_CHAR_CAP = 8000            # per filing (Phase 0.1/0.5 finding)
MAX_COMPETITOR_PEERS = 5
COMPETITOR_TRANSCRIPT_QUARTERS = 4
COMPETITOR_TRANSCRIPT_CHAR_CAP = 7000   # matches research_router._MAX_TRANSCRIPT_CHARS
INDUSTRY_REPORT_MAX_AGE_DAYS = 14
_NWC_LOOKBACK_YEARS = 7


def _f(v, fmt: str = ".1f") -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "n/a"
    return f"{float(v):{fmt}}"


def _pct(v, fmt: str = "+.1f") -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "n/a"
    return f"{float(v) * 100:{fmt}}%"


# ---------------------------------------------------------------------------
# 1.1 — Fundamentals history (av_financials.duckdb, up to 10 annual years)
# ---------------------------------------------------------------------------

def get_fundamentals_history(ticker: str) -> str:
    """Up to 10 annual years: revenue + growth, margin decomposition (COGS/SGA/R&D/other-opex
    as % of revenue), capex %, D&A %, NWC days (DSO/DPO/DIO via the engine's own
    `compute_nwc_days` — not reimplemented here), FCF, diluted share count trend."""
    ticker = ticker.upper()
    if not _AV_FIN_DB.exists():
        return "[ERROR] av_financials.duckdb not found"
    try:
        annual = load_av_annual_financials(ticker)
    except Exception as e:
        return f"[ERROR] No AV annual financials for {ticker}: {e}"

    inc = annual["income"].sort_values("period_end_date", ascending=False).head(10).reset_index(drop=True)
    cf = annual["cashflow"]
    bs = annual["balance"]
    if inc.empty:
        return f"[ERROR] No annual financials found for {ticker}"

    years = inc["period_end_date"].astype(str).str[:4].tolist()
    rev = inc["revenue"].astype(float)
    gp = inc.get("gross_profit", pd.Series([None] * len(inc))).astype(float)
    op_inc = inc["operating_income"].astype(float)
    ni = inc["net_income"].astype(float)
    cogs = inc.get("cost_of_revenue")
    cogs = cogs.astype(float) if cogs is not None else pd.Series([np.nan] * len(inc))
    sga = inc.get("selling_general_admin")
    sga = sga.astype(float) if sga is not None else pd.Series([np.nan] * len(inc))
    rd = inc.get("research_development")
    rd = rd.astype(float) if rd is not None else pd.Series([np.nan] * len(inc))
    reports_cogs = bool(cogs.notna().any() or gp.notna().any())

    cf_by_year = {}
    if not cf.empty:
        cf_sorted = cf.sort_values("period_end_date", ascending=False)
        for _, r in cf_sorted.iterrows():
            y = str(r["period_end_date"])[:4]
            cf_by_year[y] = (r.get("operating_cashflow"), r.get("capital_expenditures"),
                              r.get("depreciation_amortization"))

    lines = [
        f"FUNDAMENTALS HISTORY — {ticker} (up to {len(inc)} annual years, reports_cogs={reports_cogs})",
        f"Fiscal years: {', '.join(years)}",
        "",
    ]

    def _row(label, vals, fmt="{:,.0f}"):
        cells = []
        for v in vals:
            cells.append(fmt.format(float(v)) if v is not None and not (isinstance(v, float) and math.isnan(v)) else "n/a")
        return f"{label}: " + " | ".join(cells)

    lines.append(_row("Revenue", rev.tolist(), "${:,.0f}"))
    growth = [None] + [
        (rev.iloc[i] / rev.iloc[i + 1] - 1) if rev.iloc[i + 1] else None
        for i in range(len(rev) - 1)
    ]
    lines.append("Revenue growth YoY: " + " | ".join(_pct(g) if g is not None else "n/a" for g in growth))
    lines.append("")

    gross_margin = [g / r if r else None for g, r in zip(gp, rev)]
    op_margin = [o / r if r else None for o, r in zip(op_inc, rev)]
    net_margin = [n / r if r else None for n, r in zip(ni, rev)]
    lines.append("Gross margin:     " + " | ".join(_pct(m) if m is not None else "n/a" for m in gross_margin))
    lines.append("Operating margin: " + " | ".join(_pct(m) if m is not None else "n/a" for m in op_margin))
    lines.append("Net margin:       " + " | ".join(_pct(m) if m is not None else "n/a" for m in net_margin))
    lines.append("")

    if reports_cogs:
        cogs_pct = [c / r if r and c is not None and not (isinstance(c, float) and math.isnan(c)) else None
                    for c, r in zip(cogs, rev)]
        lines.append("COGS % of revenue: " + " | ".join(_pct(m) if m is not None else "n/a" for m in cogs_pct))
    else:
        lines.append("COGS % of revenue: n/a for all years (company does not break out cost of revenue — "
                      "no gross-margin lever available; EBIT margin moves entirely via SG&A/R&D/other-opex)")
    sga_pct = [s / r if r and s is not None and not (isinstance(s, float) and math.isnan(s)) else None
               for s, r in zip(sga, rev)]
    rd_pct = [d / r if r and d is not None and not (isinstance(d, float) and math.isnan(d)) else None
              for d, r in zip(rd, rev)]
    lines.append("SG&A % of revenue: " + " | ".join(_pct(m) if m is not None else "n/a" for m in sga_pct))
    lines.append("R&D % of revenue:  " + " | ".join(_pct(m) if m is not None else "n/a" for m in rd_pct))
    lines.append("")

    capex_pct, da_pct, fcf_vals = [], [], []
    for y in years:
        triple = cf_by_year.get(y)
        if triple is None:
            capex_pct.append(None); da_pct.append(None); fcf_vals.append(None)
            continue
        ocf, capex, da = triple
        r = rev[years.index(y)] if y in years else None
        capex_pct.append(abs(float(capex)) / float(r) if capex is not None and r else None)
        da_pct.append(abs(float(da)) / float(r) if da is not None and r else None)
        fcf_vals.append(float(ocf) - abs(float(capex)) if ocf is not None and capex is not None else None)
    lines.append("Capex % of revenue: " + " | ".join(_pct(m) if m is not None else "n/a" for m in capex_pct))
    lines.append("D&A % of revenue:   " + " | ".join(_pct(m) if m is not None else "n/a" for m in da_pct))
    lines.append(_row("Free Cash Flow (OCF - Capex)", fcf_vals, "${:,.0f}"))
    lines.append("")

    try:
        nwc = compute_nwc_days(bs, inc)
        lines.append(f"Working capital days (DSO / DPO / DIO): "
                      f"{nwc.dso:.0f} / {nwc.dpo:.0f} / {nwc.dio:.0f}")
    except Exception:
        lines.append("Working capital days: n/a")

    shares = bs.get("common_stock_shares_outstanding") if not bs.empty else None
    if shares is not None and shares.notna().sum() >= 2:
        bs_sorted = bs.sort_values("period_end_date")
        s_series = bs_sorted["common_stock_shares_outstanding"].dropna()
        if len(s_series) >= 2:
            trend = "declining (net buybacks)" if s_series.iloc[-1] < s_series.iloc[0] else "rising (net dilution)"
            lines.append(f"Diluted share count trend (oldest vs. newest): {trend}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1.2 — MD&A history (mda_filings.duckdb)
# ---------------------------------------------------------------------------

def get_mda_history(ticker: str, n_annual: int = 3) -> str:
    """Last `n_annual` 10-K MD&As + the latest 10-Q MD&A, truncated to MDA_CHAR_CAP chars each.
    Filters status == 'ok' client-side (Phase 0.1 finding: ~16.5% of cached rows are 'empty').
    Degrades to an [INFO] placeholder when nothing is cached (routine for recent IPOs)."""
    ticker = ticker.upper()
    if not mda.DEFAULT_DB_PATH.exists():
        return "[INFO] mda_filings.duckdb not found — no MD&A history available"
    conn = duckdb.connect(str(mda.DEFAULT_DB_PATH), read_only=True)
    try:
        rows_10k = [r for r in mda.get_cached_mda(conn, ticker, form="10-K") if r["status"] == "ok"]
        rows_10q = [r for r in mda.get_cached_mda(conn, ticker, form="10-Q") if r["status"] == "ok"]
    finally:
        conn.close()

    selected = rows_10k[:n_annual] + rows_10q[:1]
    if not selected:
        return f"[INFO] No cached MD&A found for {ticker}"

    blocks = [f"MD&A HISTORY — {ticker} ({len(selected)} filings, newest first)", ""]
    for r in selected:
        label = f"[{r['form']} FY{str(r['fiscal_period_end'])[:4]} MD&A]"
        text = r["mda_text"] or ""
        truncated = text[:MDA_CHAR_CAP] + ("..." if len(text) > MDA_CHAR_CAP else "")
        blocks.append(f"--- {label} ---\n\n{truncated}")
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# 1.3 — Cached Industry Researcher report (14-day read window, bypasses the router's 24h TTL)
# ---------------------------------------------------------------------------

def get_industry_name(ticker: str) -> Optional[str]:
    """Ticker -> company_overview.industry (latest snapshot), or None if unclassified/missing."""
    ticker = ticker.upper()
    if not _AV_FIN_DB.exists():
        return None
    conn = duckdb.connect(str(_AV_FIN_DB), read_only=True)
    try:
        row = conn.execute(
            "SELECT industry FROM company_overview WHERE ticker = ? ORDER BY fetch_date DESC LIMIT 1",
            [ticker],
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row and row[0] else None


def get_industry_report(
    ticker: str, max_age_days: int = INDUSTRY_REPORT_MAX_AGE_DAYS,
) -> Optional[tuple[str, int]]:
    """(markdown, age_days) for the freshest cached Industry Researcher report (any model)
    within `max_age_days`, or None if the ticker has no industry classification, no cached
    report, or only reports older than the window. Ignores `custom:*` scope keys (SPEC 5.4)."""
    ticker = ticker.upper()
    if not _AV_FIN_DB.exists() or not _INDUSTRY_CACHE_DB.exists():
        return None

    industry = get_industry_name(ticker)
    if not industry:
        return None

    key = scope_key(industry)
    if key.startswith("custom:"):
        return None

    conn2 = duckdb.connect(str(_INDUSTRY_CACHE_DB), read_only=True)
    try:
        cache_row = conn2.execute(
            "SELECT report_markdown, generated_at FROM industry_research_cache "
            "WHERE scope_key = ? ORDER BY generated_at DESC LIMIT 1",
            [key],
        ).fetchone()
    finally:
        conn2.close()
    if not cache_row:
        return None

    markdown, generated_at = cache_row
    if isinstance(generated_at, str):
        generated_at = datetime.fromisoformat(generated_at)
    age_days = (datetime.now() - generated_at).days
    if age_days > max_age_days:
        return None
    return markdown, age_days


# ---------------------------------------------------------------------------
# 1.4 — Competitor transcripts (cached-only, zero new AV calls)
# ---------------------------------------------------------------------------

def get_competitor_transcripts(
    ticker: str, max_peers: int = MAX_COMPETITOR_PEERS, n_quarters: int = COMPETITOR_TRANSCRIPT_QUARTERS,
) -> str:
    """Cached-only earnings transcripts for the top `max_peers` same-industry peers by market
    cap. Never calls the Alpha Vantage fetch path — a peer with nothing cached is skipped with
    a note, never fetched fresh (CLAUDE.md rule 7 — competitor data must not cost AV budget)."""
    from api.research_router import _peer_df

    ticker = ticker.upper()
    df, _sector_industry, err = _peer_df(ticker)
    if err:
        return f"[INFO] No competitor transcripts available: {err}"

    peers = df["ticker"].tolist()[:max_peers]
    conn = et.open_db(et.DEFAULT_DB_PATH)
    try:
        blocks = [f"COMPETITOR EARNINGS TRANSCRIPTS — cached-only, up to {len(peers)} peers"]
        found_any = False
        for peer in peers:
            quarters = et.get_last_n_transcripts(conn, peer, n_quarters)
            if not quarters:
                blocks.append(f"\n[{peer}] — no cached transcripts, skipped")
                continue
            found_any = True
            for q, text in quarters:
                truncated = text[:COMPETITOR_TRANSCRIPT_CHAR_CAP]
                blocks.append(f"\n--- [{peer} {q}] ---\n\n{truncated}")
    finally:
        conn.close()

    if not found_any:
        return f"[INFO] No cached transcripts for any of {ticker}'s top {len(peers)} peers"
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# 1.5 — Engine context (risk-free rate, beta, tax rate, reports_cogs + historical COGS%)
# ---------------------------------------------------------------------------

def _reports_cogs_and_cogs_median(inc: pd.DataFrame) -> tuple[bool, Optional[float]]:
    """Shared by get_engine_context and get_historical_margin_bounds: whether the company
    reports COGS at all (same test dcf/forecaster.py uses) and its 7yr-median COGS % of
    revenue when it does."""
    cogs = inc.get("cost_of_revenue")
    gp = inc.get("gross_profit")
    reports_cogs = bool(
        (cogs is not None and cogs.notna().any()) or (gp is not None and gp.notna().any())
    )
    hist_cogs_pct = None
    if reports_cogs and cogs is not None:
        rev = inc["revenue"].astype(float)
        cogs_f = cogs.astype(float)
        ratios = [(c / r) for c, r in zip(cogs_f.head(7), rev.head(7))
                  if r and c is not None and not (isinstance(c, float) and math.isnan(c))]
        hist_cogs_pct = float(np.median(ratios)) if ratios else None
    return reports_cogs, hist_cogs_pct


def get_historical_margin_bounds(ticker: str) -> dict:
    """Numeric companion to get_engine_context (that one is LLM-facing text; this one is for
    api.ai_dcf_router.validate_assumptions's guardrail checks). Returns
    {"reports_cogs": bool, "cogs_pct_median": float|None, "ebit_margin_max": float|None} —
    the historical bounds the Architect's authored assumptions are checked against (SPEC 6.5)."""
    ticker = ticker.upper()
    empty = {"reports_cogs": False, "cogs_pct_median": None, "ebit_margin_max": None}
    if not _AV_FIN_DB.exists():
        return empty
    try:
        annual = load_av_annual_financials(ticker)
    except Exception:
        return empty
    inc = annual["income"].sort_values("period_end_date", ascending=False).reset_index(drop=True)
    if inc.empty:
        return empty

    reports_cogs, cogs_pct_median = _reports_cogs_and_cogs_median(inc)
    rev = inc["revenue"].astype(float)
    op = inc["operating_income"].astype(float)
    margins = [(o / r) for o, r in zip(op.head(7), rev.head(7))
               if r and o is not None and not (isinstance(o, float) and math.isnan(o))]
    ebit_margin_max = float(max(margins)) if margins else None
    return {"reports_cogs": reports_cogs, "cogs_pct_median": cogs_pct_median, "ebit_margin_max": ebit_margin_max}


def get_engine_context(ticker: str) -> str:
    """Engine-input facts the Architect may reasonably override: risk-free rate, raw beta,
    historical effective tax rate, book debt/equity, share-count trend, and — per the Phase 0.3
    finding (SPEC 6.2b) — whether the company reports COGS at all and its historical COGS% of
    revenue, since `ebit_margin_pct` alone is capped by that figure. NO market cap, NO price."""
    ticker = ticker.upper()
    if not _AV_FIN_DB.exists():
        return "[ERROR] av_financials.duckdb not found"
    try:
        annual = load_av_annual_financials(ticker)
    except Exception as e:
        return f"[ERROR] No AV annual financials for {ticker}: {e}"

    inc = annual["income"].sort_values("period_end_date", ascending=False).reset_index(drop=True)
    bs = annual["balance"]
    if inc.empty:
        return f"[ERROR] No annual financials found for {ticker}"

    rf = load_risk_free_rate_30y() or load_risk_free_rate()
    beta_5yr, beta_2yr = get_betas(ticker)
    tax_rate = compute_effective_tax_rate(inc.iloc[:5].reset_index(drop=True))
    reports_cogs, hist_cogs_pct = _reports_cogs_and_cogs_median(inc)

    total_debt, total_equity = None, None
    if not bs.empty:
        latest = bs.sort_values("period_end_date", ascending=False).iloc[0]
        total_debt = sum(
            float(latest.get(c) or 0) for c in
            ["short_term_debt", "current_portion_long_term_debt", "long_term_debt"]
            if c in latest.index
        )
        total_equity = float(latest.get("total_shareholder_equity") or 0) if "total_shareholder_equity" in latest.index else None

    lines = [f"ENGINE CONTEXT — {ticker} (facts the DCF engine otherwise defaults; price-blind)", ""]
    lines.append(f"Risk-free rate (30yr Treasury, falls back to 10yr): {_pct(rf) if rf else 'n/a'}")
    lines.append(f"Beta (raw, 5yr weekly / 2yr weekly): {_f(beta_5yr, '.3f') if beta_5yr else 'n/a'} / "
                 f"{_f(beta_2yr, '.3f') if beta_2yr else 'n/a'}")
    lines.append(f"Market risk premium (fixed engine default): {_pct(DEFAULT_MRP)}")
    lines.append(f"Historical effective tax rate (last 5yr): {_pct(tax_rate)}")
    lines.append("")
    lines.append(f"Reports COGS explicitly (gross-profit/cost-of-revenue line reported): {reports_cogs}")
    if reports_cogs:
        lines.append(
            f"Historical COGS % of revenue (7yr median): {_pct(hist_cogs_pct) if hist_cogs_pct is not None else 'n/a'} — "
            "IMPORTANT: your ebit_margin_pct target cannot exceed (1 - cogs_pct) for any year; "
            "if you want EBIT margin beyond what this COGS level allows, you must also set a "
            "lower cogs_pct with a stated reason (mix shift, pricing power, cost program) — "
            "otherwise the engine silently floors SG&A/R&D at zero and stops at that ceiling."
        )
    else:
        lines.append(
            "This company does not break out COGS — cogs_pct is not a meaningful lever here; "
            "ebit_margin_pct alone has full range via the SG&A/R&D/other-opex residual."
        )
    lines.append("")
    if total_debt is not None:
        lines.append(f"Book total debt: ${total_debt:,.0f}")
    if total_equity is not None:
        lines.append(f"Book total shareholder equity: ${total_equity:,.0f}")

    shares = bs.get("common_stock_shares_outstanding") if not bs.empty else None
    if shares is not None and shares.notna().sum() >= 2:
        bs_sorted = bs.sort_values("period_end_date")
        s_series = bs_sorted["common_stock_shares_outstanding"].dropna()
        if len(s_series) >= 2:
            trend = "declining (net buybacks)" if s_series.iloc[-1] < s_series.iloc[0] else "rising (net dilution)"
            lines.append(f"Diluted share count trend (oldest vs. newest): {trend}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1.6 — Context assembly helpers (raw/format split — inputs already fetched by the orchestrator)
# ---------------------------------------------------------------------------

def build_fundamentals_context(fundamentals_history: str) -> str:
    return f"=== FUNDAMENTALS HISTORY (up to 10 annual years) ===\n{fundamentals_history}"


def build_industry_context(
    peer_table: str,
    industry_aggregates: str,
    tavily_search: str,
    industry_report: Optional[tuple[str, int]],
    competitor_transcripts: str,
) -> str:
    blocks = [
        f"=== PEER COMPARISON (industry-classified, real fundamentals) ===\n{peer_table}",
        f"=== INDUSTRY AGGREGATES (sector_stats, industry grain only) ===\n{industry_aggregates}",
        f"=== TAM / INDUSTRY TREND WEB SEARCH ===\n{tavily_search}",
    ]
    if industry_report is not None:
        markdown, age_days = industry_report
        blocks.append(
            f"=== CACHED INDUSTRY RESEARCH REPORT [Industry report, {age_days}d old] ===\n{markdown}"
        )
    else:
        blocks.append(
            "=== CACHED INDUSTRY RESEARCH REPORT ===\n"
            "[INFO] No cached industry report within the freshness window — rely on the "
            "aggregates and web search above instead."
        )
    blocks.append(f"=== COMPETITOR EARNINGS TRANSCRIPTS (cached-only) ===\n{competitor_transcripts}")
    return "\n\n".join(blocks)


def build_guidance_context(
    mda_history: str,
    target_transcripts: str,
    beat_miss: str,
    consensus_estimates: str,
) -> str:
    return (
        f"=== MD&A HISTORY (multi-year, 10-K + latest 10-Q) ===\n{mda_history}\n\n"
        f"=== EARNINGS TRANSCRIPTS (target, last 4 quarters) ===\n{target_transcripts}\n\n"
        f"=== EPS BEAT/MISS HISTORY ===\n{beat_miss}\n\n"
        f"=== CONSENSUS ESTIMATES ===\n{consensus_estimates}"
    )
