#!/usr/bin/env python3
"""
Phase 7 risk diagnostics and guardrails for the fundamentals-alpha model.

This script:
1. Loads monthly_pe from HF_DB_PATH
2. Joins sector/industry from AV_DB_PATH (company_overview)
3. Applies filter_universe() with UNIVERSE_DEFAULTS
4. Computes composite baseline score
5. Runs run_monthly_backtest() to get monthly portfolio returns and holdings
6. Runs exposure_report(): sector, market-cap, and concentration
7. Runs value_trap_flags(): cheap but deteriorating stocks
8. Runs apply_guardrails(): detect threshold violations
9. Runs drawdown_analysis(): detailed drawdown stats
10. Runs beta_decomposition(): rolling beta vs SPY
11. Writes docs/risk_report.md

Usage:
    uv run scripts/run_risk.py
    uv run scripts/run_risk.py --tc-bps 20 --min-cap 1e9 --verbose

Environment variables required:
    HF_DB_PATH      path to historic_fundamentals.duckdb
    AV_DB_PATH      path to av_financials.duckdb (sector/industry join)
    PRICES_DB_PATH  path to prices.duckdb (SPY returns)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from historic_fundamentals.universe import UNIVERSE_DEFAULTS, filter_universe  # noqa: E402
from historic_fundamentals.baselines import (  # noqa: E402
    composite_score,
    _VALUE_COLS,
    _VALUE_SIGN,
    _QUALITY_COLS,
    _QUALITY_SIGN,
    _MOMENTUM_COL,
)
from historic_fundamentals.backtest import (  # noqa: E402
    run_monthly_backtest,
    load_spy_returns,
    PORTFOLIO_CONFIGS,
)
from historic_fundamentals.risk import (  # noqa: E402
    GUARDRAIL_DEFAULTS,
    exposure_report,
    value_trap_flags,
    apply_guardrails,
    constrained_holdings,
    drawdown_analysis,
    beta_decomposition,
)

log = logging.getLogger(__name__)


def _load_monthly_pe(hf_db_path: str) -> pd.DataFrame:
    import duckdb
    conn = duckdb.connect(hf_db_path, read_only=True)
    df = conn.execute("SELECT * FROM monthly_pe ORDER BY ticker, month_end_date").df()
    conn.close()
    df["month_end_date"] = pd.to_datetime(df["month_end_date"])
    if "feature_available_date" in df.columns:
        df["feature_available_date"] = pd.to_datetime(df["feature_available_date"])
    return df


def _join_sector_industry(df: pd.DataFrame, av_db_path: str) -> pd.DataFrame:
    if "sector" in df.columns and df["sector"].notna().any():
        return df
    try:
        import duckdb
        conn = duckdb.connect(av_db_path, read_only=True)
        overview = conn.execute(
            "SELECT symbol AS ticker, sector, industry FROM company_overview"
        ).df()
        conn.close()
        df = df.merge(overview, on="ticker", how="left")
        log.info("Joined sector/industry: %d rows with sector", df["sector"].notna().sum())
    except Exception as exc:
        log.warning("Could not join sector/industry from AV_DB_PATH: %s", exc)
    return df


def _compute_pit_composite_score(df: pd.DataFrame) -> pd.Series:
    value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
    value_sign = {c: _VALUE_SIGN[c] for c in value_cols}
    quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
    quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}
    has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()

    if value_cols and quality_cols and has_momentum:
        cols = value_cols + quality_cols + [_MOMENTUM_COL]
        sign_map = {**value_sign, **quality_sign, _MOMENTUM_COL: False}
    elif value_cols and quality_cols:
        cols = value_cols + quality_cols
        sign_map = {**value_sign, **quality_sign}
    elif value_cols:
        cols = value_cols
        sign_map = value_sign
    else:
        log.warning("No composite factor columns found — using constant score 0.")
        return pd.Series(0.0, index=df.index)

    return composite_score(df, cols, sign_map)


def _build_holdings_df(
    universe: pd.DataFrame,
    bt_results: dict,
    score_col: str = "composite_score",
    portfolio_name: str = "top_pct_20",
) -> pd.DataFrame:
    """Reconstruct holdings DataFrame from universe and backtest selection."""
    bt_df = bt_results.get(portfolio_name, pd.DataFrame())
    if bt_df.empty:
        return pd.DataFrame()

    # Reproduce the selection logic to get actual per-month holdings
    from historic_fundamentals.backtest import _select_top, PORTFOLIO_CONFIGS
    config_val = PORTFOLIO_CONFIGS.get(portfolio_name, 0.20)
    date_col = "month_end_date"
    rows = []
    for dt, grp in universe.groupby(date_col):
        selected = _select_top(grp, score_col, config_val)
        for _, row in selected.iterrows():
            r = {"date": dt, "ticker": row.get("ticker", "")}
            for col in ["sector", "industry", "market_cap", "debt_to_ebitda",
                        "ttm_operating_margin", "roa", score_col]:
                if col in row.index:
                    r[col] = row[col]
            rows.append(r)
    return pd.DataFrame(rows)


def _pct(v: float | None) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v * 100:.2f}%"


def _fmt(v: float | None, decimals: int = 4) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.{decimals}f}"


def _build_risk_report(
    universe_n: int,
    filters: dict,
    exposure: dict,
    vt_flags: pd.DataFrame,
    guardrail_result: dict,
    dd: dict,
    beta_result: dict,
    guardrail_comparison: dict | None = None,
) -> str:
    lines = [
        "# Risk Report\n",
        f"**Universe**: {universe_n} tickers\n",
        f"**Filters**: min_market_cap={filters.get('min_market_cap', 'N/A'):.0f} "
        f"| min_price={filters.get('min_price', 'N/A'):.2f}\n",
        "\n---\n",
    ]

    # Sector exposure
    lines.append("## Sector Exposure\n")
    sector_df = exposure.get("sector", pd.DataFrame())
    if not sector_df.empty:
        lines.append(sector_df.to_string())
        lines.append("\n")
    else:
        lines.append("No sector data available.\n")

    # Industry exposure
    if "industry" in exposure and not exposure["industry"].empty:
        lines.append("## Industry Exposure (top months, top industries)")
        lines.append(exposure["industry"].head(6).to_string())
        lines.append("")

    # Market-cap bucket exposure
    lines.append("\n## Market-Cap Bucket Exposure\n")
    mc_df = exposure.get("market_cap_bucket", pd.DataFrame())
    if not mc_df.empty:
        lines.append(mc_df.to_string())
        lines.append("\n")
    else:
        lines.append("No market-cap data available.\n")

    # Concentration
    lines.append("\n## Position Concentration (HHI)\n")
    hhi = exposure.get("concentration", pd.Series(dtype=float))
    if not hhi.empty:
        lines.append(f"Mean HHI: {hhi.mean():.4f}\n")
        lines.append(f"Mean n_stocks (approx): {1 / hhi.mean():.1f}\n")

    # Value trap flags
    lines.append("\n## Value Trap Flags\n")
    if vt_flags.empty:
        lines.append("No value traps detected.\n")
    else:
        lines.append(f"Flagged rows: {len(vt_flags)}\n")
        lines.append(vt_flags.to_string(index=False))
        lines.append("\n")

    # Guardrail violations
    lines.append("\n## Guardrail Violations\n")
    violations = guardrail_result.get("violations", [])
    if not violations:
        lines.append("No guardrail violations detected.\n")
    else:
        lines.append(f"Total violations: {len(violations)}\n")
        vdf = pd.DataFrame(violations)
        lines.append(vdf.to_string(index=False))
        lines.append("\n")

    # Drawdown
    lines.append("\n## Drawdown Analysis (top_pct_20)\n")
    lines.append(f"Max drawdown:          {_pct(dd.get('max_drawdown'))}\n")
    lines.append(f"Max drawdown start:    {dd.get('max_drawdown_start')}\n")
    lines.append(f"Max drawdown end:      {dd.get('max_drawdown_end')}\n")
    lines.append(f"Duration (months):     {dd.get('max_drawdown_duration_months', 'N/A')}\n")
    lines.append(f"Recovery date:         {dd.get('recovery_date', 'None')}\n")
    lines.append(f"Avg drawdown:          {_pct(dd.get('avg_drawdown'))}\n")
    lines.append(f"Underwater months:     {dd.get('underwater_months', 'N/A')}\n")

    # Beta
    lines.append("\n## Beta Decomposition (top_pct_20 vs SPY)\n")
    lines.append(f"Market beta:           {_fmt(beta_result.get('market_beta'))}\n")
    bp = beta_result.get("beta_by_period", pd.Series(dtype=float))
    if not bp.empty and bp.notna().any():
        lines.append(f"Rolling beta (mean):   {_fmt(float(bp.dropna().mean()))}\n")
        lines.append(f"Rolling beta (min):    {_fmt(float(bp.dropna().min()))}\n")
        lines.append(f"Rolling beta (max):    {_fmt(float(bp.dropna().max()))}\n")

    # Guardrail impact: unconstrained vs constrained comparison
    if guardrail_comparison:
        lines.append("\n## Guardrail Impact: Unconstrained vs Constrained\n")
        rows = guardrail_comparison.get("rows", [])
        if rows:
            cmp_df = pd.DataFrame(rows).set_index("label")
            for col in ["cagr", "sharpe", "max_drawdown", "avg_turnover"]:
                if col in cmp_df.columns:
                    cmp_df[col] = cmp_df[col].map(lambda v: f"{v:.4f}" if not np.isnan(v) else "N/A")
            lines.append(cmp_df.to_string())
            lines.append("\n")

    return "\n".join(lines)


def _portfolio_metrics_row(bt_df: pd.DataFrame, label: str, tc_bps: float) -> dict:
    """Compute CAGR, Sharpe, max_drawdown, turnover from a backtest result DataFrame."""
    from historic_fundamentals.backtest import portfolio_metrics
    if bt_df.empty:
        return {"label": label, "cagr": float("nan"), "sharpe": float("nan"),
                "max_drawdown": float("nan"), "avg_turnover": float("nan")}
    ret_col = "net_return" if "net_return" in bt_df.columns else bt_df.columns[0]
    metrics = portfolio_metrics(bt_df[ret_col], tc_bps=tc_bps)
    to_col = "turnover" if "turnover" in bt_df.columns else None
    avg_to = float(bt_df[to_col].mean()) if to_col else float("nan")
    return {
        "label": label,
        "cagr": metrics.get("cagr", float("nan")),
        "sharpe": metrics.get("sharpe", float("nan")),
        "max_drawdown": metrics.get("max_drawdown", float("nan")),
        "avg_turnover": avg_to,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 7: Risk diagnostics and guardrails for fundamentals-alpha."
    )
    parser.add_argument("--tc-bps", type=float, default=10.0)
    parser.add_argument("--min-cap", type=float, default=None)
    parser.add_argument("--min-price", type=float, default=None)
    parser.add_argument("--portfolio", default="top_pct_20",
                        help="Portfolio config name for risk analysis (default: top_pct_20)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    if not Path(hf_db).exists():
        log.error("HF_DB_PATH not found: %s", hf_db)
        sys.exit(1)

    log.info("Loading monthly_pe from %s", hf_db)
    raw = _load_monthly_pe(hf_db)
    log.info("Loaded %d rows, %d tickers", len(raw), raw["ticker"].nunique())

    raw = _join_sector_industry(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]

    universe_kwargs = {**UNIVERSE_DEFAULTS}
    if args.min_cap is not None:
        universe_kwargs["min_market_cap"] = args.min_cap
    if args.min_price is not None:
        universe_kwargs["min_price"] = args.min_price

    log.info("Applying universe filters: %s", universe_kwargs)
    universe = filter_universe(raw, **universe_kwargs)
    log.info("Universe after filters: %d rows, %d tickers",
             len(universe), universe["ticker"].nunique())

    log.info("Computing composite score ...")
    universe = universe.copy()
    universe["composite_score"] = _compute_pit_composite_score(universe)

    # SPY returns
    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
            log.info("SPY returns: %d months", len(spy_returns))
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)
    else:
        log.warning("PRICES_DB_PATH not found (%s) — SPY benchmark skipped", prices_db)

    # Backtest
    log.info("Running monthly backtest ...")
    bt_results = run_monthly_backtest(
        universe,
        score_col="composite_score",
        tc_bps=args.tc_bps,
        portfolios=PORTFOLIO_CONFIGS,
    )

    # Build holdings DataFrame for the chosen portfolio
    holdings_df = _build_holdings_df(universe, bt_results, "composite_score", args.portfolio)
    log.info("Holdings: %d rows, %d months",
             len(holdings_df), holdings_df["date"].nunique() if not holdings_df.empty else 0)

    # Exposure report
    log.info("Computing exposure report ...")
    exposure = exposure_report(
        holdings_df,
        date_col="date",
        ticker_col="ticker",
        sector_col="sector",
        industry_col="industry",
        market_cap_col="market_cap",
    )

    print("\n=== Sector Exposure (top 5 months) ===")
    sec_df = exposure.get("sector", pd.DataFrame())
    if not sec_df.empty:
        print(sec_df.tail(5).to_string())

    print("\n=== Market-Cap Bucket Exposure (top 5 months) ===")
    mc_df = exposure.get("market_cap_bucket", pd.DataFrame())
    if not mc_df.empty:
        print(mc_df.tail(5).to_string())

    print("\n=== Concentration (HHI last 5 months) ===")
    hhi = exposure.get("concentration", pd.Series(dtype=float))
    if not hhi.empty:
        print(hhi.tail(5).to_string())

    # Value trap flags
    log.info("Computing value trap flags ...")
    vt_flags = pd.DataFrame()
    if not holdings_df.empty:
        vt_flags = value_trap_flags(
            holdings_df.rename(columns={"date": "month_end_date"}),
            score_col="composite_score",
        )
    print(f"\n=== Value Trap Flags: {len(vt_flags)} flagged rows ===")
    if not vt_flags.empty:
        print(vt_flags.to_string(index=False))

    # Guardrails
    log.info("Running guardrail checks ...")
    portfolio_ret_df = bt_results.get(args.portfolio, pd.DataFrame())
    guardrail_result = apply_guardrails(
        portfolio_ret_df,
        holdings_df,
        config=GUARDRAIL_DEFAULTS,
    )
    violations = guardrail_result["violations"]
    print(f"\n=== Guardrail Violations: {len(violations)} ===")
    for v in violations[:20]:
        print(f"  {v['date'].date() if hasattr(v['date'], 'date') else v['date']} | "
              f"{v['guardrail']} | value={v['value']:.3f} | "
              f"threshold={v['threshold']} | {v.get('detail', '')}")

    # Guardrail impact: unconstrained vs constrained backtest comparison
    guardrail_comparison: dict = {}
    if not holdings_df.empty:
        log.info("Building constrained holdings for guardrail comparison ...")
        # features_df needs score column — use universe with composite_score
        features_df = universe.rename(columns={"month_end_date": "date"}) if "month_end_date" in universe.columns else universe.copy()
        features_df = features_df[
            ["date", "ticker"]
            + [c for c in ["sector", "debt_to_ebitda", "composite_score"] if c in features_df.columns]
        ].rename(columns={"composite_score": "score"})

        constrained_h = constrained_holdings(
            holdings_df,
            features_df,
            config=GUARDRAIL_DEFAULTS,
        )
        log.info("Constrained holdings: %d rows (from %d unconstrained)",
                 len(constrained_h), len(holdings_df))

        # Re-run backtest on constrained holdings by filtering universe to those tickers/months
        date_col_u = "month_end_date"
        h_col = "month_end_date" if "month_end_date" in constrained_h.columns else "date"
        constrained_pairs = set(
            zip(
                pd.to_datetime(constrained_h[h_col]),
                constrained_h["ticker"],
            )
        )
        universe_constrained = universe[
            universe.apply(
                lambda row: (row[date_col_u], row["ticker"]) in constrained_pairs,
                axis=1,
            )
        ].copy()

        bt_constrained = run_monthly_backtest(
            universe_constrained,
            score_col="composite_score",
            tc_bps=args.tc_bps,
            portfolios={args.portfolio: PORTFOLIO_CONFIGS.get(args.portfolio, 0.20)},
        )
        constrained_ret_df = bt_constrained.get(args.portfolio, pd.DataFrame())

        unconstrained_row = _portfolio_metrics_row(portfolio_ret_df, "Unconstrained", args.tc_bps)
        constrained_row = _portfolio_metrics_row(constrained_ret_df, "Constrained", args.tc_bps)

        comparison_rows = [unconstrained_row, constrained_row]
        guardrail_comparison = {"rows": comparison_rows}

        print("\n=== Guardrail Impact: Unconstrained vs Constrained ===")
        cmp_df = pd.DataFrame(comparison_rows).set_index("label")
        print(cmp_df.to_string())
    else:
        log.warning("Empty holdings — skipping guardrail comparison")

    # Drawdown analysis
    dd: dict = {}
    if not portfolio_ret_df.empty:
        log.info("Computing drawdown analysis ...")
        ret_col = "net_return" if "net_return" in portfolio_ret_df.columns else portfolio_ret_df.columns[0]
        dd = drawdown_analysis(portfolio_ret_df[ret_col])
        print(f"\n=== Drawdown Analysis ({args.portfolio}) ===")
        print(f"  Max drawdown:          {_pct(dd['max_drawdown'])}")
        print(f"  Max drawdown start:    {dd['max_drawdown_start']}")
        print(f"  Max drawdown end:      {dd['max_drawdown_end']}")
        print(f"  Duration (months):     {dd['max_drawdown_duration_months']}")
        print(f"  Recovery date:         {dd['recovery_date']}")
        print(f"  Avg drawdown:          {_pct(dd['avg_drawdown'])}")
        print(f"  Underwater months:     {dd['underwater_months']}")
    else:
        log.warning("No portfolio returns for %s — skipping drawdown", args.portfolio)

    # Beta decomposition
    beta_result: dict = {}
    if not portfolio_ret_df.empty and spy_returns is not None:
        log.info("Computing beta decomposition ...")
        ret_col = "net_return" if "net_return" in portfolio_ret_df.columns else portfolio_ret_df.columns[0]
        beta_result = beta_decomposition(portfolio_ret_df[ret_col], spy_returns)
        print(f"\n=== Beta Decomposition ({args.portfolio} vs SPY) ===")
        print(f"  Market beta:           {_fmt(beta_result.get('market_beta'))}")
        bp = beta_result.get("beta_by_period", pd.Series(dtype=float))
        if not bp.empty and bp.notna().any():
            print(f"  Rolling beta (mean):   {_fmt(float(bp.dropna().mean()))}")
            print(f"  Rolling beta (min):    {_fmt(float(bp.dropna().min()))}")
            print(f"  Rolling beta (max):    {_fmt(float(bp.dropna().max()))}")
    else:
        log.warning("SPY returns unavailable — skipping beta decomposition")

    # Write risk report
    docs_dir = ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)
    out_path = docs_dir / "risk_report.md"
    md = _build_risk_report(
        universe_n=universe["ticker"].nunique(),
        filters=universe_kwargs,
        exposure=exposure,
        vt_flags=vt_flags,
        guardrail_result=guardrail_result,
        dd=dd,
        beta_result=beta_result,
        guardrail_comparison=guardrail_comparison if guardrail_comparison else None,
    )
    out_path.write_text(md)
    log.info("Risk report written to %s", out_path)


if __name__ == "__main__":
    main()
