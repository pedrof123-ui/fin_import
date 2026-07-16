"""
Sanitized fundamental data for the AI Researcher's Valuation Analyst sub-agent.

Builds on the deterministic DCF engine (dcf.run_dcf_av) run three times as bear/base/bull
operating scenarios. This module never exposes current price, current multiples, market cap,
or any model/analyst price target — the valuation agent values the business blind and states
fair value in absolute $/share; the Chief Analyst computes upside vs. the quote separately.
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path

import duckdb
import numpy as np

from dcf.assumptions import UserOverrides, YearOverride
from dcf.av_data import load_av_annual_financials, load_av_quarterly_financials
from dcf.estimates import fetch_and_cache
from dcf.forecaster import _annual_ewm_growth, _quarterly_momentum_signal
from dcf.model import run_dcf_av

_DATA_DIR = Path(__file__).parent.parent / "data"
_AV_FIN_DB = _DATA_DIR / "av_financials.duckdb"
_HIST_FUND_DB = _DATA_DIR / "historic_fundamentals.duckdb"

_DEFAULT_GROWTH_DELTA = 0.02  # fallback bear/bull growth spread when no quarterly signal
_MAX_GROWTH_DELTA = 0.08


def _ebit_margin_percentiles(ticker: str) -> tuple[float | None, float | None, float | None]:
    """(p25, median, p75) EBIT margin over the last 7 annual periods."""
    if not _AV_FIN_DB.exists():
        return None, None, None
    conn = duckdb.connect(str(_AV_FIN_DB), read_only=True)
    rows = conn.execute("""
        SELECT total_revenue, operating_income
        FROM income_statements
        WHERE ticker = ? AND period_type = 'annual'
        ORDER BY fiscal_date_ending DESC LIMIT 7
    """, [ticker]).fetchall()
    conn.close()
    margins = [
        float(op) / float(rev) for rev, op in rows
        if rev and op is not None and float(rev) != 0
    ]
    if not margins:
        return None, None, None
    arr = np.array(margins)
    return float(np.percentile(arr, 25)), float(np.median(arr)), float(np.percentile(arr, 75))


def _growth_delta(ticker: str) -> float:
    """Half the spread between quarterly-momentum and annual-EWM revenue growth signals."""
    try:
        annual = load_av_annual_financials(ticker)
        quarterly = load_av_quarterly_financials(ticker)
    except Exception:
        return _DEFAULT_GROWTH_DELTA

    rev = annual["income"].sort_values("period_end_date")["revenue"].dropna().values.astype(float)
    if len(rev) < 2:
        return _DEFAULT_GROWTH_DELTA
    annual_g = _annual_ewm_growth(rev)
    q_signal = _quarterly_momentum_signal(quarterly["income"])
    if q_signal is None:
        return _DEFAULT_GROWTH_DELTA
    return float(min(abs(q_signal - annual_g) / 2, _MAX_GROWTH_DELTA))


def _last_annual_year(ticker: str) -> int | None:
    if not _AV_FIN_DB.exists():
        return None
    conn = duckdb.connect(str(_AV_FIN_DB), read_only=True)
    row = conn.execute("""
        SELECT fiscal_date_ending FROM income_statements
        WHERE ticker = ? AND period_type = 'annual'
        ORDER BY fiscal_date_ending DESC LIMIT 1
    """, [ticker]).fetchone()
    conn.close()
    if not row:
        return None
    d = row[0]
    return d.year if hasattr(d, "year") else int(str(d)[:4])


def _build_scenario_overrides(
    ticker: str, conn, base_year_forecasts: list, direction: str, margin_pctl: float | None,
) -> UserOverrides | None:
    """Build bear/bull revenue-growth overrides anchored on consensus low/high estimates
    where available, falling back to a momentum-vs-EWM growth delta elsewhere.
    """
    last_year = _last_annual_year(ticker)
    last_rev = (
        base_year_forecasts[0].revenue / (1 + base_year_forecasts[0].revenue_growth)
        if (1 + base_year_forecasts[0].revenue_growth) != 0 else base_year_forecasts[0].revenue
    )
    if last_year is None or last_rev <= 0:
        return None

    try:
        raw_estimates = fetch_and_cache(ticker, conn)
    except Exception:
        raw_estimates = []

    annual_by_year: dict[int, dict] = {}
    for e in raw_estimates:
        if e.get("horizon") != "fiscal year":
            continue
        try:
            y = int(str(e["date"])[:4])
        except (ValueError, TypeError):
            continue
        annual_by_year[y] = e

    delta = _growth_delta(ticker)
    sign = -1.0 if direction == "bear" else 1.0

    years: dict[int, YearOverride] = {}
    prev_rev = last_rev
    for i, yf in enumerate(base_year_forecasts, start=1):
        target_year = last_year + i
        est = annual_by_year.get(target_year)
        rev_field = "rev_low" if direction == "bear" else "rev_high"
        if est and est.get(rev_field) and est.get("rev_avg"):
            growth = float(est[rev_field]) / prev_rev - 1 if prev_rev else yf.revenue_growth
        else:
            growth = yf.revenue_growth + sign * delta
        years[i] = YearOverride(revenue_growth=growth)
        prev_rev = prev_rev * (1 + growth)

    return UserOverrides(years=years, default_ebit_margin_pct=margin_pctl)


def _run_scenario(ticker: str, conn, base_result, direction: str, margin_pctl: float | None):
    overrides = _build_scenario_overrides(ticker, conn, base_result.year_forecasts, direction, margin_pctl)
    if overrides is None:
        return None
    try:
        return run_dcf_av(ticker, overrides, estimates_conn=conn)
    except Exception:
        return None


def _fmt(v, fmt_str: str = ".2f") -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "n/a"
    return f"{v:{fmt_str}}"


def compute_dcf_scenarios(ticker: str) -> dict:
    """Runs the DCF engine three times (bear/base/bull). Raises on failure — callers decide
    how to degrade (text summary vs. table rendering)."""
    ticker = ticker.upper()
    # Read-only: research_router.py holds concurrent read-only connections to this file
    # during the same fan-out; DuckDB disallows mixing read-write with read-only handles.
    # fetch_and_cache() degrades gracefully (silently skips persisting a fresh AV fetch)
    # when its write attempt fails against a read-only connection.
    conn = duckdb.connect(str(_HIST_FUND_DB), read_only=True)
    try:
        base = run_dcf_av(ticker, estimates_conn=conn)
        p25, median_m, p75 = _ebit_margin_percentiles(ticker)
        bear = _run_scenario(ticker, conn, base, "bear", p25)
        bull = _run_scenario(ticker, conn, base, "bull", p75)
    finally:
        conn.close()
    return {"bear": bear, "base": base, "bull": bull}


def get_dcf_summary(ticker: str) -> str:
    """Bear/base/bull DCF scenario summary. Never includes current price, market cap, or upside."""
    ticker = ticker.upper()
    try:
        scenarios = compute_dcf_scenarios(ticker)
    except Exception as e:
        return f"[ERROR] DCF engine failed for {ticker}: {e}"
    bear, base, bull = scenarios["bear"], scenarios["base"], scenarios["bull"]

    lines = [f"DCF VALUATION — {ticker} (bear / base / bull operating scenarios)", ""]

    def _scenario_row(label, result):
        if result is None:
            lines.append(f"{label}: [unavailable — insufficient estimate/margin data for this scenario]")
            return
        rev_cagr = (
            (result.year_forecasts[4].revenue / result.year_forecasts[0].revenue) ** (1 / 4) - 1
            if len(result.year_forecasts) >= 5 and result.year_forecasts[0].revenue > 0 else None
        )
        avg_ebit_margin = np.mean([
            1 - yf.cogs_pct - yf.sga_pct - (yf.rd_pct or 0) - yf.other_opex_pct
            for yf in result.year_forecasts[:5]
        ])
        lines.append(
            f"{label}: intrinsic value/share = ${_fmt(result.intrinsic_value_per_share)}  "
            f"| 5yr revenue CAGR = {_fmt(rev_cagr * 100 if rev_cagr is not None else None, '.1f')}%  "
            f"| avg EBIT margin = {_fmt(avg_ebit_margin * 100, '.1f')}%"
        )

    _scenario_row("BEAR", bear)
    _scenario_row("BASE", base)
    _scenario_row("BULL", bull)
    lines.append("")

    wd = base.wacc_detail
    lines += [
        "WACC BREAKDOWN (base scenario):",
        f"  Beta (raw / relevered):  {_fmt(wd.beta_raw)} / {_fmt(wd.beta_relevered)}",
        f"  Risk-free rate:          {_fmt(wd.risk_free_rate * 100, '.2f')}%",
        f"  Market risk premium:     {_fmt(wd.market_risk_premium * 100, '.2f')}%",
        f"  Cost of equity:          {_fmt(wd.cost_of_equity * 100, '.2f')}%",
        f"  Cost of debt:            {_fmt(wd.cost_of_debt * 100, '.2f')}%",
        f"  Effective tax rate:      {_fmt(wd.tax_rate * 100, '.1f')}%",
        f"  Debt / Equity weight:    {_fmt(wd.debt_weight * 100, '.0f')}% / {_fmt(wd.equity_weight * 100, '.0f')}%",
        f"  WACC:                    {_fmt(wd.wacc * 100, '.2f')}%",
        "",
        f"Terminal growth rate: {_fmt(base.terminal_growth_rate * 100, '.2f')}%",
        f"Terminal value as % of enterprise value: {_fmt(base.tv_pct_enterprise_value * 100, '.1f')}%",
        "",
        "5-YEAR FCFF FORECAST (base scenario):",
        f"{'Year':<6}{'Revenue':>16}{'Growth':>9}{'EBIT Margin':>13}{'NOPAT':>16}{'CapEx%Rev':>11}{'ΔNWC':>14}{'FCFF':>16}",
    ]
    for yf, fc in zip(base.year_forecasts[:5], base.fcff_series[:5]):
        ebit_margin = fc.ebit / fc.revenue if fc.revenue else 0
        lines.append(
            f"{yf.year:<6}{fc.revenue:>16,.0f}{yf.revenue_growth * 100:>8.1f}%{ebit_margin * 100:>12.1f}%"
            f"{fc.nopat:>16,.0f}{yf.capex_pct_revenue * 100:>10.1f}%{fc.delta_nwc:>16,.0f}{fc.fcff:>18,.0f}"
        )

    lines += ["", "SENSITIVITY GRID (base scenario, intrinsic value/share by WACC x terminal growth):"]
    tg_vals = sorted({c.terminal_growth for c in base.sensitivity})
    wacc_vals = sorted({c.wacc for c in base.sensitivity})
    grid = {(c.wacc, c.terminal_growth): c.intrinsic_value for c in base.sensitivity}
    header = "WACC\\TG  " + "".join(f"{tg * 100:>8.2f}%" for tg in tg_vals)
    lines.append(header)
    for w in wacc_vals:
        row = f"{w * 100:>7.2f}% "
        for tg in tg_vals:
            v = grid.get((w, tg), float("nan"))
            row += f"{v:>9.2f}" if not math.isnan(v) else f"{'n/a':>9}"
        lines.append(row)

    if base.warnings:
        lines += ["", "DATA-QUALITY WARNINGS:"] + [f"  - {w}" for w in base.warnings]

    if base.analyst_estimates:
        lines += ["", "ANALYST ESTIMATE ANCHORING USED BY FORECASTER:"]
        for e in base.analyst_estimates[:6]:
            lines.append(f"  {e}")

    return "\n".join(lines)


def get_valuation_inputs(ticker: str) -> str:
    """Sanitized fundamentals for relative valuation. Never includes current price/multiples,
    goal prices, or analyst price targets.
    """
    ticker = ticker.upper()
    if not _HIST_FUND_DB.exists() or not _AV_FIN_DB.exists():
        return "[ERROR] Required databases not found"

    lines = [f"VALUATION INPUTS — {ticker}", ""]

    try:
        conn = duckdb.connect(str(_HIST_FUND_DB), read_only=True)
        # NOTE: pe_rolling_5yr_median/pfcf_rolling_5yr_median (not normalized_pe_5y/
        # normalized_pfcf_5y) — normalized_pe_5y = current_price / avg_5yr_EPS, which embeds
        # today's price in the numerator and would silently reintroduce price-anchoring into
        # the "blind" Valuation Analyst. The rolling-median columns are genuinely
        # price-independent: a median of the historical price/EPS RATIO series, same
        # construction as goal_pe.
        ps = conn.execute("""
            SELECT pe_rolling_5yr_median, pfcf_rolling_5yr_median, rev_cagr_3yr, earn_cagr_3yr,
                   rev_growth_1yr, earn_growth_1yr, earn_ntm_growth_est,
                   current_roic, current_gross_margin, gross_margin_5y_median,
                   current_operating_margin, operating_margin_5y_median,
                   current_fcf_margin, fcf_margin_5y_median, debt_to_ebitda,
                   current_ttm_eps, forward_12m_eps
            FROM pe_stats WHERE ticker = ?
        """, [ticker]).fetchone()
        conn.close()
    except Exception as e:
        return f"[ERROR] pe_stats query failed: {e}"

    if not ps:
        return f"[ERROR] No pe_stats data for {ticker}"

    def f(v, fmt="1f", pct=True):
        if v is None:
            return "n/a"
        return f"{float(v) * 100:.{fmt[0]}f}%" if pct else f"{float(v):.{fmt[0]}f}"

    lines += [
        "NORMALIZED HISTORICAL MULTIPLES (5yr rolling median of historical P/E and P/FCF ratios):",
        f"  P/E (5yr rolling median):   {f(ps[0], pct=False)}",
        f"  P/FCF (5yr rolling median): {f(ps[1], pct=False)}",
        "",
        "GROWTH:",
        f"  Revenue CAGR 3yr:      {f(ps[2])}",
        f"  Earnings CAGR 3yr:     {f(ps[3])}",
        f"  Revenue growth 1yr:    {f(ps[4])}",
        f"  Earnings growth 1yr:   {f(ps[5])}",
        f"  Earnings NTM growth est: {f(ps[6])}",
        "",
        "QUALITY:",
        f"  ROIC:                  {f(ps[7])}",
        f"  Gross margin (curr / 5y median):     {f(ps[8])} / {f(ps[9])}",
        f"  Operating margin (curr / 5y median): {f(ps[10])} / {f(ps[11])}",
        f"  FCF margin (curr / 5y median):       {f(ps[12])} / {f(ps[13])}",
        f"  Debt/EBITDA:           {f(ps[14], pct=False)}",
        "",
        f"TTM EPS:                 ${f(ps[15], fmt='2f', pct=False)}",
        f"Forward 12M EPS (consensus): ${f(ps[16], fmt='2f', pct=False)}",
    ]

    try:
        conn = duckdb.connect(str(_AV_FIN_DB), read_only=True)
        rows = conn.execute("""
            SELECT i.fiscal_date_ending, i.net_income, cf.operating_cashflow,
                   cf.capital_expenditures, b.common_stock_shares_outstanding
            FROM income_statements i
            LEFT JOIN cash_flow_statements cf
                ON cf.ticker = i.ticker AND cf.period_type = i.period_type
                AND cf.fiscal_date_ending = i.fiscal_date_ending
            LEFT JOIN balance_sheets b
                ON b.ticker = i.ticker AND b.period_type = i.period_type
                AND b.fiscal_date_ending = i.fiscal_date_ending
            WHERE i.ticker = ? AND i.period_type = 'annual'
            ORDER BY i.fiscal_date_ending DESC LIMIT 5
        """, [ticker]).fetchall()
        conn.close()
    except Exception as e:
        rows = []
        lines.append(f"\n[ERROR] Per-share history query failed: {e}")

    if rows:
        lines += ["", "PER-SHARE HISTORY (last 5 fiscal years, newest first):"]
        lines.append(f"{'FY':<12}{'Diluted EPS':>14}{'FCF/Share':>14}{'Diluted Shares':>18}")
        for d, ni, ocf, capex, shares in rows:
            eps = ni / shares if ni is not None and shares else None
            fcf_sh = (ocf - abs(capex)) / shares if ocf is not None and capex is not None and shares else None
            lines.append(
                f"{str(d)[:7]:<12}"
                f"{('$' + f'{eps:.2f}') if eps is not None else 'n/a':>14}"
                f"{('$' + f'{fcf_sh:.2f}') if fcf_sh is not None else 'n/a':>14}"
                f"{(f'{shares:,.0f}') if shares else 'n/a':>18}"
            )
        share_counts = [r[4] for r in rows if r[4]]
        if len(share_counts) >= 2:
            trend = "declining (buybacks)" if share_counts[0] < share_counts[-1] else "rising (dilution)"
            lines.append(f"Share count trend (newest vs. oldest): {trend}")

    try:
        conn = duckdb.connect(str(_HIST_FUND_DB), read_only=True)
        ee = conn.execute("""
            SELECT horizon, fiscal_date, eps_avg, rev_avg
            FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY horizon, fiscal_date ORDER BY fetched_at DESC) AS rn
                FROM earnings_estimates WHERE ticker = ? AND fiscal_date >= today()
            ) WHERE rn = 1
            ORDER BY horizon DESC, fiscal_date
            LIMIT 6
        """, [ticker]).fetchall()
        conn.close()
    except Exception:
        ee = []

    if ee:
        lines += ["", "FORWARD CONSENSUS ESTIMATES:"]
        for horizon, fiscal_date, eps_avg, rev_avg in ee:
            rev_txt = f"${float(rev_avg) / 1e9:.1f}B" if rev_avg else "n/a"
            eps_txt = f"${float(eps_avg):.2f}" if eps_avg else "n/a"
            lines.append(f"  {horizon} ({str(fiscal_date)[:7]}): EPS avg {eps_txt}, Rev avg {rev_txt}")

    return "\n".join(lines)
