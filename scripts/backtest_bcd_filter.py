"""Backtest comparison: vw_gr_top_n_25 with and without BCD mispricing filter.

Runs three variants:
  baseline        - no BCD filter (current live strategy)
  bcd_hard        - require bcd_misp <= 0 (only structurally underpriced stocks)
  bcd_soft        - require bcd_misp <= 0.5 (exclude clearly overpriced stocks)

All three use vol-weighting + guardrails + top-25 to match the live vw_gr_top_n_25 setup.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from historic_fundamentals.universe import UNIVERSE_DEFAULTS, filter_universe
from historic_fundamentals.backtest import run_monthly_backtest, portfolio_metrics, load_spy_returns
from historic_fundamentals.model import _apply_sector_zscore
from historic_fundamentals.risk import value_trap_flags

log = logging.getLogger(__name__)

FEATURE_COLS = [
    "pe_ratio", "ps_ratio", "fcf_yield", "ev_ebitda", "dividend_yield",
    "earnings_yield", "roa", "roe", "roic", "pbv", "ptbv",
    "pe_rolling_5yr_median", "pfcf_ratio", "pfcf_rolling_5yr_median",
    "ps_rolling_5yr_median", "ev_ebitda_rolling_5yr_median",
    "roa_rolling_5yr_median", "roic_rolling_5yr_median",
    "gross_margin_5y_median", "gross_margin_slope_5y",
    "operating_margin_5y_median", "operating_margin_change_3y",
    "operating_margin_slope_5y", "fcf_margin_5y_median",
    "fcf_margin_change_3y", "roa_stability_5y",
    "debt_to_ebitda", "interest_coverage", "momentum_12_1",
    "earnings_yield_norm", "fcf_yield_norm", "ev_ebitda_norm", "ps_ratio_norm",
    "earnings_quality", "asset_growth",
]

TC_BPS = 10.0
TOP_N = {"top_n_25": 25}
MAX_SECTOR_PCT = 0.25
SCORE_BUFFER = 0.10


def _score_with_model(universe: pd.DataFrame, bundle: dict) -> pd.Series:
    """Deliberately uses PER-MONTH self-referential sector z-scores, not the
    persisted training-time stats score_live.py now uses — this backtest applies
    one static model across ~40 years, and the training window's normalization
    is wildly non-stationary that far from training time (see run_backtest.py's
    _score_with_model docstring for the empirical detail)."""
    model = bundle["model"]
    feature_names = bundle["feature_cols"]
    sector_col = "sector"
    scores = {}
    for date, month_df in universe.groupby("month_end_date"):
        present = [f for f in feature_names if f in month_df.columns]
        if sector_col in month_df.columns and month_df[sector_col].notna().any():
            scored_df, _ = _apply_sector_zscore(month_df, month_df.head(0), present, sector_col)
        else:
            scored_df = month_df.copy()
        X = scored_df[present].copy()
        for f in feature_names:
            if f not in X.columns:
                X[f] = np.nan
        X = X[feature_names].fillna(X[feature_names].median())
        preds = model.predict(X.to_numpy(dtype=float))
        for idx, val in zip(month_df.index, preds):
            scores[idx] = val
    return pd.Series(scores)


def _apply_guardrails(universe: pd.DataFrame, score_col: str) -> pd.DataFrame:
    df = universe.copy()
    trap_df = value_trap_flags(df, score_col=score_col)
    if not trap_df.empty and "month_end_date" in trap_df.columns:
        trap_idx = pd.MultiIndex.from_arrays([trap_df["ticker"], trap_df["month_end_date"]])
        df_idx = pd.MultiIndex.from_arrays([df["ticker"], df["month_end_date"]])
        vt_mask = pd.Series(df_idx.isin(trap_idx), index=df.index)
    else:
        vt_mask = pd.Series(False, index=df.index)
    present = [c for c in FEATURE_COLS if c in df.columns]
    dq_mask = df[present].isna().sum(axis=1) > 2
    df.loc[vt_mask | dq_mask, score_col] = np.nan
    return df


def _apply_bcd_filter(universe: pd.DataFrame, score_col: str, threshold: float) -> pd.DataFrame:
    """Set score=NaN for stocks where bcd_misp > threshold or bcd_misp is NULL."""
    df = universe.copy()
    if "bcd_misp" not in df.columns:
        log.warning("bcd_misp column not found — BCD filter skipped")
        return df
    exclude = df["bcd_misp"].isna() | (df["bcd_misp"] > threshold)
    excluded = exclude.sum()
    total = len(df)
    log.info("BCD filter (threshold=%.2f): excluded %d/%d row-months (%.1f%%)",
             threshold, excluded, total, 100 * excluded / total)
    df.loc[exclude, score_col] = np.nan
    return df


def _profit_factor_and_expectancy(returns: pd.Series) -> tuple[float, float]:
    r = returns.dropna()
    wins = r[r > 0]
    losses = r[r <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else np.nan
    win_rate = len(wins) / len(r) if len(r) > 0 else np.nan
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.0
    r_exp = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if not np.isnan(win_rate) else np.nan
    return pf, r_exp


def _fmt(v, pct=False):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "    N/A"
    return f"{v * 100:+7.2f}%" if pct else f"{v:8.4f}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))
    model_path = ROOT / "data" / "model.joblib"

    if not model_path.exists():
        log.error("model.joblib not found at %s", model_path)
        sys.exit(1)

    log.info("Loading data...")
    conn = duckdb.connect(hf_db, read_only=True)
    raw = conn.execute("SELECT * FROM monthly_pe ORDER BY ticker, month_end_date").df()
    conn.close()
    raw["month_end_date"] = pd.to_datetime(raw["month_end_date"])

    av_conn = duckdb.connect(av_db, read_only=True)
    # one row per refresh in company_overview — keep the latest, else the merge fans out
    sectors = av_conn.execute("""SELECT ticker, sector FROM company_overview
        QUALIFY fetch_date = MAX(fetch_date) OVER (PARTITION BY ticker)""").df()
    av_conn.close()
    raw = raw.merge(sectors, on="ticker", how="left")
    raw["market_cap"] = raw["shares"] * raw["price"]

    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe: %d rows, %d tickers", len(universe), universe["ticker"].nunique())

    log.info("Scoring with XGBoost model...")
    model = joblib.load(model_path)
    universe = universe.copy()
    universe["model_score"] = _score_with_model(universe, model)

    spy_returns = load_spy_returns(prices_db_path=prices_db)

    sector_col = "sector" if "sector" in universe.columns else None

    variants = [
        ("baseline",  None,  None),
        ("bcd_hard",  "bcd_misp", 0.0),
        ("bcd_soft",  "bcd_misp", 0.5),
    ]

    results = {}
    for label, filter_col, threshold in variants:
        log.info("Running variant: %s", label)
        u = _apply_guardrails(universe, "model_score")
        if filter_col is not None:
            u = _apply_bcd_filter(u, "model_score", threshold)

        bt = run_monthly_backtest(
            u,
            score_col="model_score",
            tc_bps=TC_BPS,
            portfolios=TOP_N,
            sector_col=sector_col,
            max_sector_pct=MAX_SECTOR_PCT,
            score_buffer=SCORE_BUFFER,
            use_vol_weighting=True,
        )
        bt_df = bt.get("top_n_25", pd.DataFrame())
        if bt_df.empty:
            results[label] = {}
            continue

        ret_series = bt_df["net_return"]
        m = portfolio_metrics(ret_series, spy_returns=spy_returns)
        pf, r_exp = _profit_factor_and_expectancy(ret_series)
        m["profit_factor"] = pf
        m["r_expectancy"] = r_exp
        m["avg_turnover"] = bt_df["turnover"].mean()

        # Eligible pool stats
        eligible = u.groupby("month_end_date")["model_score"].apply(
            lambda s: s.notna().sum()
        )
        m["avg_eligible"] = eligible.mean()

        results[label] = m

    # ── Print comparison table ────────────────────────────────────────────────
    cols = ["cagr", "ann_vol", "sharpe", "max_drawdown", "profit_factor",
            "r_expectancy", "avg_turnover", "avg_eligible", "n_months"]

    header = (
        f"{'Variant':<12} {'CAGR':>8} {'Vol':>8} {'Sharpe':>8} "
        f"{'MaxDD':>9} {'ProfFact':>9} {'R-Exp':>8} {'Turnover':>9} {'Eligible':>9} {'Months':>7}"
    )
    print()
    print("=" * len(header))
    print("BCD Filter Backtest Comparison  —  vw_gr_top_n_25  —  10bps TC")
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    for label, m in results.items():
        if not m:
            print(f"{label:<12}  (no results)")
            continue
        print(
            f"{label:<12} "
            f"{_fmt(m.get('cagr'), pct=True):>8} "
            f"{_fmt(m.get('ann_vol'), pct=True):>8} "
            f"{_fmt(m.get('sharpe')):>8} "
            f"{_fmt(m.get('max_drawdown'), pct=True):>9} "
            f"{_fmt(m.get('profit_factor')):>9} "
            f"{_fmt(m.get('r_expectancy'), pct=True):>8} "
            f"{_fmt(m.get('avg_turnover'), pct=True):>9} "
            f"{m.get('avg_eligible', float('nan')):>9.0f} "
            f"{m.get('n_months', 0):>7}"
        )

    print()
    print("Definitions:")
    print("  baseline  — current live strategy, no BCD filter")
    print("  bcd_hard  — require bcd_misp <= 0 (structurally underpriced only)")
    print("  bcd_soft  — require bcd_misp <= 0.5 (exclude clearly overpriced stocks)")
    print("  Eligible  — avg number of stocks eligible for top-25 selection per month")


if __name__ == "__main__":
    main()
