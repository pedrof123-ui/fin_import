#!/usr/bin/env python3
"""
Walk-forward comparison: frozen baseline FEATURE_COLS + one new ratio.

Replicates the notebook walk-forward loop:
  - 5-year rolling training window
  - Trains XGBoost on ret_1y
  - Tests on next 1 month, takes top 25 stocks equal-weighted
  - Reports: CAGR, Sharpe, MaxDD, PF, R-Expectancy

Compares against frozen baseline from RATIOS_EXPANSION_PLAN.md:
  ML rf_vw_xgb_gr_top_25: CAGR +38.65%, Sharpe 1.310, MaxDD -40.4%, PF 1.759, RE +0.2117

Usage:
    uv run scripts/wf_ratio_test.py --ratio pfcf_growth_yield_ratio
    uv run scripts/wf_ratio_test.py --ratio pfcf_growth_yield_ratio --top-n 25 --verbose
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)

# ── Frozen baseline ───────────────────────────────────────────────────────────
FROZEN_BASELINE = {
    "CAGR":   0.3865,
    "Sharpe": 1.310,
    "MaxDD":  -0.404,
    "PF":     1.759,
    "RE":     0.2117,
}
HARD_GATES = {
    "CAGR_delta":   0.005,
    "Sharpe_delta": -0.02,
    "MaxDD_delta":  -0.02,
}

MARKET_CAP_MIN   = 300_000_000
MIN_TRAIN_MONTHS = 60
ROLLING_YEARS    = 5
TOP_N            = 25
TC_BPS_ONEWAY    = 10
EMBARGO_MONTHS   = 12

XGB_PARAMS = dict(
    n_estimators=400, max_depth=4, learning_rate=0.02,
    subsample=0.8, colsample_bytree=0.8, min_child_weight=20,
    n_jobs=-1, tree_method="hist", verbosity=0,
)

# ── Notebook FEATURE_COLS (Cell 13 equivalent) ────────────────────────────────
BASELINE_FEATURES = [
    "pe_ratio", "pfcf_ratio", "ev_ebitda", "ps_ratio", "pbv", "ptbv",
    "fcf_yield", "dividend_yield",
    "earnings_yield", "earnings_yield_3y_avg", "earnings_yield_5y_avg",
    "fcf_yield_3y_avg", "fcf_yield_5y_avg",
    "ebitda_ev_yield", "ebitda_ev_yield_3y_avg", "ebitda_ev_yield_5y_avg",
    "normalized_pe_5y", "normalized_pfcf_5y", "normalized_evebitda_5y", "normalized_ps_5y",
    "pe_premium", "pfcf_premium", "ev_premium", "ps_premium",
    "pbv_premium", "ptbv_premium",
    "roa", "roe", "roic",
    "roa_premium", "roe_premium", "roic_premium",
    "rev_cagr_1y", "rev_cagr_3y", "rev_cagr_5y",
    "earn_cagr_1y", "earn_cagr_3y", "earn_cagr_5y",
    "fcf_cagr_1y", "fcf_cagr_3y", "fcf_cagr_5y",
    "is_profitable",
    "ttm_gross_margin", "gross_margin_5y_median", "gross_margin_slope_5y",
    "ttm_operating_margin", "operating_margin_5y_median",
    "operating_margin_change_3y", "operating_margin_slope_5y",
    "ttm_fcf_margin", "fcf_margin_5y_median", "fcf_margin_change_3y",
    "roa_stability_5y", "debt_to_ebitda", "interest_coverage",
    "earnings_quality", "asset_growth",
    "momentum_12_1",
]


def safe_ratio(a: pd.Series, b: pd.Series, clip: float = 10.0) -> pd.Series:
    return (a / b.replace(0, np.nan)).clip(-clip, clip)


def xsec_zscore(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    result = df[cols].copy()
    for col in cols:
        if col not in df.columns:
            continue
        result[col] = df.groupby("month_end_date")[col].transform(
            lambda x: (x - x.mean()) / (x.std(ddof=0) + 1e-8)
        )
    return result


def load_and_engineer(hf_db: str, av_db: str) -> pd.DataFrame:
    log.info("Loading monthly_pe ...")
    conn = duckdb.connect(hf_db, read_only=True)
    df = conn.execute("""
        SELECT ticker, month_end_date, price, shares,
               ttm_revenue, ttm_eps, ttm_fcf,
               pe_ratio,    pe_rolling_5yr_median,
               earnings_yield, earnings_yield_3y_avg, earnings_yield_5y_avg,
               normalized_pe_5y,
               pfcf_ratio,  pfcf_rolling_5yr_median, fcf_yield,
               fcf_yield_3y_avg, fcf_yield_5y_avg, normalized_pfcf_5y,
               ev_ebitda,   ev_ebitda_rolling_5yr_median,
               ebitda_ev_yield, ebitda_ev_yield_3y_avg, ebitda_ev_yield_5y_avg,
               normalized_evebitda_5y,
               ps_ratio,    ps_rolling_5yr_median,    normalized_ps_5y,
               roa,         roa_rolling_5yr_median,
               roe,         roe_rolling_5yr_median,
               roic,        roic_rolling_5yr_median,
               pbv,         pbv_rolling_5yr_median,
               ptbv,        ptbv_rolling_5yr_median,
               dividend_yield,
               ttm_ebitda,
               fcf_margin_5y_median,
               ttm_gross_margin,     gross_margin_5y_median,     gross_margin_slope_5y,
               ttm_operating_margin, operating_margin_5y_median,
               operating_margin_change_3y, operating_margin_slope_5y,
               ttm_fcf_margin, fcf_margin_5y_median, fcf_margin_change_3y,
               roa_stability_5y, debt_to_ebitda, interest_coverage,
               earnings_quality, asset_growth, momentum_12_1
        FROM monthly_pe
        WHERE price > 0
        ORDER BY ticker, month_end_date
    """).df()
    conn.close()
    df["month_end_date"] = pd.to_datetime(df["month_end_date"])

    try:
        av_conn = duckdb.connect(av_db, read_only=True)
        sector_map = av_conn.execute("""
            SELECT ticker, sector FROM (
                SELECT ticker, sector,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fetch_date DESC) AS rn
                FROM company_overview
                WHERE sector IS NOT NULL AND sector NOT IN ('None', '', 'N/A')
            ) t WHERE rn = 1
        """).df()
        av_conn.close()
        df = df.merge(sector_map, on="ticker", how="left")
    except Exception as e:
        log.warning("Sector join failed: %s", e)
        df["sector"] = np.nan

    df["market_cap"] = df["shares"] * df["price"]
    df = df[df["market_cap"] >= MARKET_CAP_MIN].copy()
    log.info("After market cap filter: %d rows, %d tickers", len(df), df["ticker"].nunique())

    # Trailing CAGRs (notebook Cell 10)
    df = df.sort_values(["ticker", "month_end_date"]).reset_index(drop=True)
    for prefix, base_col, year_list in [
        ("rev",  "ttm_revenue", [1, 3, 5]),
        ("earn", "ttm_eps",     [1, 3, 5]),
        ("fcf",  "ttm_fcf",     [1, 3, 5]),
    ]:
        for years in year_list:
            out_col = f"{prefix}_cagr_{years}y"
            months  = years * 12
            past = df.groupby("ticker")[base_col].transform(lambda s: s.shift(months))
            valid = (past > 0) & (df[base_col] > 0) & past.notna() & df[base_col].notna()
            df[out_col] = np.where(valid, (df[base_col] / past) ** (1.0 / years) - 1, np.nan)

    # Premium features (notebook Cell 13)
    df["is_profitable"] = (df["ttm_eps"] > 0).astype(float)
    for out, num, denom in [
        ("pe_premium",   "pe_ratio",   "pe_rolling_5yr_median"),
        ("pfcf_premium", "pfcf_ratio", "pfcf_rolling_5yr_median"),
        ("ev_premium",   "ev_ebitda",  "ev_ebitda_rolling_5yr_median"),
        ("ps_premium",   "ps_ratio",   "ps_rolling_5yr_median"),
        ("roa_premium",  "roa",        "roa_rolling_5yr_median"),
        ("roe_premium",  "roe",        "roe_rolling_5yr_median"),
        ("roic_premium", "roic",       "roic_rolling_5yr_median"),
        ("pbv_premium",  "pbv",        "pbv_rolling_5yr_median"),
        ("ptbv_premium", "ptbv",       "ptbv_rolling_5yr_median"),
    ]:
        df[out] = safe_ratio(df[num], df[denom])

    # Forward returns
    log.info("Computing forward returns ...")
    for name, lag in [("ret_1y", 12), ("ret_1m", 1)]:
        df[name] = df.groupby("ticker")["price"].transform(lambda s: s.shift(-lag) / s - 1)

    log.info("Data ready: %d rows", len(df))
    return df


def add_pfcf_growth_yield_ratio(df: pd.DataFrame) -> pd.DataFrame:
    fcf_yield_pct  = df["fcf_yield"]   * 100
    fcf_growth_pct = df["fcf_cagr_1y"] * 100
    denom = fcf_growth_pct + fcf_yield_pct
    valid = (df["pfcf_ratio"] > 0) & (denom > 0)
    df["pfcf_growth_yield_ratio"] = np.where(valid, df["pfcf_ratio"] / denom, np.nan)
    df["pfcf_growth_yield_ratio"] = df.groupby("month_end_date")["pfcf_growth_yield_ratio"].transform(
        lambda s: s.clip(lower=s.quantile(0.01), upper=s.quantile(0.99))
    )
    return df


def add_ev_ebitda_growth_ratio(df: pd.DataFrame) -> pd.DataFrame:
    # Point-in-time EBITDA growth from TTM shift(12)
    df = df.sort_values(["ticker", "month_end_date"]).copy()
    base = df.groupby("ticker")["ttm_ebitda"].shift(12)
    valid_growth = (base > 0) & (df["ttm_ebitda"] > 0)
    ebitda_growth_pct = np.where(valid_growth, df["ttm_ebitda"] / base * 100 - 100, np.nan)
    valid_ratio = (df["ev_ebitda"] > 0) & (pd.Series(ebitda_growth_pct, index=df.index) > 0)
    df["ev_ebitda_growth_ratio"] = np.where(
        valid_ratio, df["ev_ebitda"] / pd.Series(ebitda_growth_pct, index=df.index), np.nan
    )
    # Exclude Financials sector (EBITDA not meaningful for banks/insurance)
    if "sector" in df.columns:
        fin = {"Financial Services", "Financials", "FINANCIAL SERVICES", "Banks", "Insurance"}
        df.loc[df["sector"].isin(fin), "ev_ebitda_growth_ratio"] = np.nan
    df["ev_ebitda_growth_ratio"] = df.groupby("month_end_date")["ev_ebitda_growth_ratio"].transform(
        lambda s: s.clip(lower=s.quantile(0.01), upper=s.quantile(0.99))
    )
    return df


def add_ev_sales_rule40_ratio(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["ticker", "month_end_date"]).copy()
    base_rev = df.groupby("ticker")["ttm_revenue"].shift(12)
    valid_rev = (base_rev > 0) & (df["ttm_revenue"] > 0)
    rev_growth_pct = np.where(valid_rev, df["ttm_revenue"] / base_rev * 100 - 100, np.nan)
    fcf_margin_pct = df["fcf_margin_5y_median"] * 100
    denom = pd.Series(rev_growth_pct, index=df.index) + fcf_margin_pct
    valid = (df["ps_ratio"] > 0) & (denom > 0)
    df["ev_sales_rule40_ratio"] = np.where(valid, df["ps_ratio"] / denom, np.nan)
    df["ev_sales_rule40_ratio"] = df.groupby("month_end_date")["ev_sales_rule40_ratio"].transform(
        lambda s: s.clip(lower=s.quantile(0.01), upper=s.quantile(0.99))
    )
    return df


def add_ev_sales_growth_ratio(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["ticker", "month_end_date"]).copy()
    base_rev = df.groupby("ticker")["ttm_revenue"].shift(12)
    valid_rev = (base_rev > 0) & (df["ttm_revenue"] > 0)
    rev_growth_pct = pd.Series(
        np.where(valid_rev, df["ttm_revenue"] / base_rev * 100 - 100, np.nan), index=df.index
    )
    valid = (df["ps_ratio"] > 0) & (rev_growth_pct > 0)
    df["ev_sales_growth_ratio"] = np.where(valid, df["ps_ratio"] / rev_growth_pct, np.nan)
    df["ev_sales_growth_ratio"] = df.groupby("month_end_date")["ev_sales_growth_ratio"].transform(
        lambda s: s.clip(lower=s.quantile(0.01), upper=s.quantile(0.99))
    )
    return df


def walk_forward_portfolio(
    df: pd.DataFrame,
    feature_cols: list[str],
    label: str,
    top_n: int = TOP_N,
) -> dict:
    from xgboost import XGBRegressor

    present_cols = [c for c in feature_cols if c in df.columns and df[c].notna().any()]
    log.info("[%s] Running walk-forward with %d features ...", label, len(present_cols))

    dates_sorted = sorted(df["month_end_date"].unique())
    ml_trades: list[tuple[float, float]] = []
    monthly_returns: list[float] = []
    prev_top = set()

    for i in range(MIN_TRAIN_MONTHS, len(dates_sorted)):
        test_date = dates_sorted[i]
        train_dates = dates_sorted[:i]

        # Rolling window
        roll_cutoff = pd.Timestamp(test_date) - pd.DateOffset(years=ROLLING_YEARS)
        train = df[df["month_end_date"].isin(train_dates) & (df["month_end_date"] >= roll_cutoff)].copy()

        # Embargo
        embargo_cutoff = pd.Timestamp(test_date) - pd.DateOffset(months=EMBARGO_MONTHS)
        train = train[train["month_end_date"] <= embargo_cutoff]
        train = train[train["ret_1y"].notna()]

        test = df[df["month_end_date"] == test_date].copy()
        test = test[test["ret_1m"].notna()]

        if len(train) < MIN_TRAIN_MONTHS or len(test) < 5:
            continue

        X_tr = xsec_zscore(train, present_cols).fillna(0.0)
        y_tr = train["ret_1y"]
        X_te = xsec_zscore(test,  present_cols).fillna(0.0)

        model = XGBRegressor(**XGB_PARAMS)
        model.fit(X_tr, y_tr)

        test = test.copy()
        test["pred"] = model.predict(X_te)

        top_rows = test.nlargest(top_n, "pred")
        top_tix  = set(top_rows["ticker"])

        # Equal-weighted portfolio return for this month
        port_ret = float(top_rows["ret_1m"].mean())

        # Transaction cost
        turnover = 1 - len(top_tix & prev_top) / top_n if prev_top else 1.0
        tc_cost  = turnover * TC_BPS_ONEWAY / 10_000
        net_ret  = port_ret - tc_cost

        monthly_returns.append(net_ret)
        prev_top = top_tix

        # Trades for PF and R-Expectancy
        _R = float(test["ret_1m"].std())
        ml_trades.extend([(float(r), _R) for r in top_rows["ret_1m"].dropna()])

    if not monthly_returns:
        return {}

    r = pd.Series(monthly_returns)
    n = len(r)
    cagr   = float((1 + r).prod() ** (12 / n) - 1)
    vol    = float(r.std() * np.sqrt(12))
    sharpe = cagr / vol if vol > 0 else np.nan
    cum    = (1 + r).cumprod()
    maxdd  = float((cum / cum.cummax() - 1).min())
    wins   = sum(x for x, _ in ml_trades if x > 0)
    losses = abs(sum(x for x, _ in ml_trades if x < 0))
    pf     = wins / losses if losses > 0 else np.nan
    rmults = [x / R for x, R in ml_trades if R > 0]
    re     = float(np.mean(rmults)) if rmults else np.nan

    log.info("[%s] CAGR=%.2f%% Sharpe=%.3f MaxDD=%.1f%% PF=%.3f RE=%.4f",
             label, cagr * 100, sharpe, maxdd * 100, pf, re)

    return {"CAGR": cagr, "Sharpe": sharpe, "MaxDD": maxdd, "PF": pf, "RE": re, "Months": n}


def print_comparison(label: str, ref: dict, new: dict) -> bool:
    print()
    print("=" * 72)
    print(f"Walk-forward comparison: {label}")
    print("=" * 72)
    print(f"{'Metric':<20} {'Frozen baseline':>16} {'New':>12} {'Delta':>10} {'Gate':>8}")
    print("-" * 72)

    gate_results = {}

    def row(name, ref_val, new_val, gate_val, higher_better=True, is_pct=False):
        delta = new_val - ref_val
        passed = (delta >= gate_val) if higher_better else (delta >= gate_val)
        gate_results[name] = passed
        fmt  = (lambda v: f"{v*100:+.2f}%") if is_pct else (lambda v: f"{v:.3f}")
        gfmt = (lambda v: f"{v*100:+.2f}%") if is_pct else (lambda v: f"{v:+.3f}")
        status = "PASS" if passed else "FAIL"
        print(f"  {name:<18} {fmt(ref_val):>16} {fmt(new_val):>12} {fmt(delta):>10} {status:>8}  (gate {gfmt(gate_val)})")

    row("CAGR",   ref["CAGR"],   new["CAGR"],   HARD_GATES["CAGR_delta"],   higher_better=True,  is_pct=True)
    row("Sharpe", ref["Sharpe"], new["Sharpe"], HARD_GATES["Sharpe_delta"], higher_better=True,  is_pct=False)
    row("MaxDD",  ref["MaxDD"],  new["MaxDD"],  HARD_GATES["MaxDD_delta"],  higher_better=False, is_pct=True)

    print()
    for name, new_val, ref_val in [
        ("Profit Factor", new.get("PF", np.nan), ref.get("PF", np.nan)),
        ("R-Expectancy",  new.get("RE", np.nan), ref.get("RE", np.nan)),
    ]:
        delta = new_val - ref_val if not (np.isnan(new_val) or np.isnan(ref_val)) else np.nan
        delta_s = f"{delta:+.4f}" if not np.isnan(delta) else "  —"
        print(f"  {name:<18} {ref_val:>16.4f} {new_val:>12.4f} {delta_s:>10}  (informational)")

    print()
    all_passed = all(gate_results.values())
    failed = [k for k, v in gate_results.items() if not v]
    if all_passed:
        print(f"DECISION: PASS — add feature to the model")
    else:
        print(f"DECISION: DROP — failed gates: {failed}")
    print("=" * 72)
    return all_passed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ratio", default="pfcf_growth_yield_ratio")
    parser.add_argument("--top-n", type=int, default=TOP_N)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))

    df = load_and_engineer(hf_db, av_db)

    ratio_builders = {
        "pfcf_growth_yield_ratio": add_pfcf_growth_yield_ratio,
        "ev_ebitda_growth_ratio":  add_ev_ebitda_growth_ratio,
        "ev_sales_rule40_ratio":   add_ev_sales_rule40_ratio,
        "ev_sales_growth_ratio":   add_ev_sales_growth_ratio,
    }
    if args.ratio not in ratio_builders:
        log.error("Unknown ratio: %s. Available: %s", args.ratio, list(ratio_builders))
        sys.exit(1)
    df = ratio_builders[args.ratio](df)

    # Run baseline first (same script, same portfolio construction — for fair delta)
    log.info("Running baseline walk-forward (no new ratio) ...")
    base_metrics = walk_forward_portfolio(df, BASELINE_FEATURES, "baseline", top_n=args.top_n)
    if not base_metrics:
        log.error("Baseline walk-forward produced no results.")
        sys.exit(1)
    log.info("Baseline complete. Running +%s ...", args.ratio)

    new_features = BASELINE_FEATURES + [args.ratio]
    new_metrics  = walk_forward_portfolio(df, new_features, f"baseline+{args.ratio}", top_n=args.top_n)
    if not new_metrics:
        log.error("Walk-forward produced no results.")
        sys.exit(1)

    # Compare new vs script-internal baseline (same evaluation conditions)
    passed = print_comparison(f"baseline + {args.ratio}", base_metrics, new_metrics)

    # Also print absolute numbers vs the notebook frozen baseline for reference
    print()
    print("Reference: notebook frozen baseline CAGR +38.65% / Sharpe 1.310 / MaxDD -40.4%")
    print(f"Script baseline (equal-weight top-{args.top_n}): CAGR {base_metrics['CAGR']*100:+.2f}% / "
          f"Sharpe {base_metrics['Sharpe']:.3f} / MaxDD {base_metrics['MaxDD']*100:.1f}%")
    print(f"Script +ratio:                                 CAGR {new_metrics['CAGR']*100:+.2f}% / "
          f"Sharpe {new_metrics['Sharpe']:.3f} / MaxDD {new_metrics['MaxDD']*100:.1f}%")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
