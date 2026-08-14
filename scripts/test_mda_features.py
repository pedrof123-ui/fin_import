#!/usr/bin/env python3
"""
Phase 5 factor gauntlet for the MD&A LLM-extracted features (PLAN_MDA_FEATURES.md).

Point-in-time joins data/mda_features.duckdb (10-K, prompt v1.1) into the monthly_pe
universe by filing_date (backward asof per ticker: a filing's features are "known" from
its filing_date until the next 10-K supersedes them), then runs the same three-part
gauntlet used for every prior factor in this repo (Greenblatt, CANSLIM, Fibonacci,
dispersion): IC test, quintile spread, then a walk-forward-style monthly portfolio
backtest with Profit Factor and R-Expectancy alongside Sharpe/MaxDD/turnover per the
standing metrics rule (feedback_strategy_metrics).

Five raw features tested, plus one interaction term:
  guidance_direction_score  ordinal encode of guidance_direction (raised=2 .. lowered=-2,
                             same scale as scripts/mda_remote/compare_models.py's
                             GUIDANCE_RANK), higher = better
  tone_delta                -2..+2, higher = better
  new_risk_language         0..3, higher = worse (lower_is_better)
  specificity                0..3, higher = better
  hedging_change             -2..+2, higher = worse (lower_is_better)
  guidance_x_specificity     guidance_direction_score * specificity — a grounding-weighted
                             signal, since ungrounded (low-specificity) guidance calls were
                             shown to be the least reliable ones during the RunPod backfill

Also splits guidance_direction's IC by extraction model (qwen3:8b vs qwen3:30b-a3b) as a
data-quality robustness check, since the dataset is a mix (7,107 rows upgraded to 30B via
the maintained-bucket rerun, 11,062 rows still on 8B — see PLAN_MDA_FEATURES.md "Backfill
status").

Nothing here writes to historic_fundamentals/baselines.py or scripts/score_live.py — those
stay untouched until a decision is made to promote any of these features.

Usage:
    uv run scripts/test_mda_features.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from historic_fundamentals.universe import UNIVERSE_DEFAULTS, filter_universe  # noqa: E402
from historic_fundamentals.baselines import (  # noqa: E402
    compute_forward_returns,
    compute_factor_ic,
    ic_summary,
    quintile_returns,
    composite_score,
    _VALUE_COLS,
    _VALUE_SIGN,
    _QUALITY_COLS,
    _QUALITY_SIGN,
    _MOMENTUM_COL,
)
from historic_fundamentals.backtest import (  # noqa: E402
    run_monthly_backtest,
    portfolio_metrics,
    load_spy_returns,
)
from scripts.run_backtest import _load_monthly_pe, _join_sector, _apply_guardrails  # noqa: E402

log = logging.getLogger(__name__)

MDA_DB = str(ROOT / "data" / "mda_features.duckdb")
FORM = "10-K"
PROMPT_VERSION = "v1.1"
ASOF_TOLERANCE_DAYS = 450  # ~13 months: one fiscal year of "current" MD&A + slack for late filers
TC_BPS = 10.0

# Same ordinal scale as scripts/mda_remote/compare_models.py's GUIDANCE_RANK
GUIDANCE_RANK = {"raised": 2, "maintained": 1, "none_given": 0, "withdrawn": -1, "lowered": -2}

# name -> (column, lower_is_better)
FACTORS = {
    "guidance_direction_score": ("guidance_direction_score", False),
    "tone_delta": ("tone_delta", False),
    "new_risk_language": ("new_risk_language", True),
    "specificity": ("specificity", False),
    "hedging_change": ("hedging_change", True),
    "guidance_x_specificity": ("guidance_x_specificity", False),
}


def _profit_factor_and_expectancy(returns: pd.Series) -> tuple[float, float]:
    """Per the standing metrics rule (feedback_strategy_metrics): always report these
    alongside Sharpe/MaxDD/turnover, not Sharpe alone."""
    r = returns.dropna()
    wins = r[r > 0]
    losses = r[r <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else np.nan
    win_rate = len(wins) / len(r) if len(r) > 0 else np.nan
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.0
    r_exp = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if not np.isnan(win_rate) else np.nan
    return pf, r_exp


def _load_mda_features(db_path: str) -> pd.DataFrame:
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute(
        "SELECT ticker, filing_date, guidance_direction, tone_delta, new_risk_language, "
        "specificity, hedging_change, model FROM mda_features "
        "WHERE form = ? AND prompt_version = ?",
        [FORM, PROMPT_VERSION],
    ).df()
    con.close()
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["guidance_direction_score"] = df["guidance_direction"].map(GUIDANCE_RANK)
    df["guidance_x_specificity"] = df["guidance_direction_score"] * df["specificity"]
    return df


def _asof_join_mda(monthly: pd.DataFrame, mda: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time join: each month's MD&A features are the most recently filed 10-K
    as of month_end_date, per ticker. Backward direction (no lookahead); a filing more
    than ASOF_TOLERANCE_DAYS stale is dropped rather than treated as still current."""
    monthly = monthly.sort_values("month_end_date").reset_index(drop=True)
    mda = mda.sort_values("filing_date").reset_index(drop=True)
    merged = pd.merge_asof(
        monthly, mda, left_on="month_end_date", right_on="filing_date", by="ticker",
        direction="backward", tolerance=pd.Timedelta(days=ASOF_TOLERANCE_DAYS),
    )
    return merged


def _value_bucket_spread(df: pd.DataFrame, factor_col: str, return_col: str,
                          lower_is_better: bool, min_stocks: int = 20) -> pd.DataFrame:
    """Mean forward return by each distinct raw value, for low-cardinality integer
    factors (3-5 levels) where forcing a 5-bin qcut collapses on ties every month —
    quintile_returns() returns empty for these. Groups by the literal score instead."""
    rows = []
    levels = sorted(df[factor_col].dropna().unique())
    for level in levels:
        rets = df.loc[df[factor_col] == level, return_col].dropna()
        if len(rets) < min_stocks:
            continue
        rows.append({"level": level, "mean_ret": rets.mean(), "n": len(rets)})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    best = out["mean_ret"].iloc[0] if lower_is_better else out["mean_ret"].iloc[-1]
    worst = out["mean_ret"].iloc[-1] if lower_is_better else out["mean_ret"].iloc[0]
    out.attrs["spread"] = best - worst
    return out


def _ic_table(df: pd.DataFrame, factors: dict, return_col: str) -> pd.DataFrame:
    rows = []
    for name, (col, lower_is_better) in factors.items():
        if col not in df.columns or df[col].notna().sum() == 0:
            continue
        ic_series = compute_factor_ic(df, col, return_col, lower_is_better=lower_is_better)
        summ = ic_summary(ic_series)
        rows.append({
            "factor": name, "mean_ic": summ["mean_ic"], "icir": summ["icir"],
            "icir_nw": summ["icir_nw"], "hit_rate": summ["hit_rate"],
            "t_stat": summ["t_stat"], "n_months": summ["n_months"],
        })
    return pd.DataFrame(rows)


def _print_metrics(label: str, m: dict, pf: float = np.nan, r_exp: float = np.nan) -> None:
    if not m or not m.get("n_months"):
        print(f"  {label}: no data")
        return
    print(
        f"  {label:<32} CAGR {m.get('cagr', float('nan')):+7.2%}  "
        f"Sharpe {m.get('sharpe', float('nan')):6.3f}  "
        f"MaxDD {m.get('max_drawdown', float('nan')):+7.2%}  "
        f"PF {pf:6.2f}  R-Exp {r_exp:+7.4f}  "
        f"WinRate {m.get('monthly_win_rate', float('nan')):6.1%}  Months {m.get('n_months', 0)}"
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    log.info("Loading monthly_pe ...")
    raw = _load_monthly_pe(hf_db)
    raw = raw[raw["month_end_date"] >= "2016-01-01"].copy()
    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]

    log.info("Loading mda_features (form=%s, prompt_version=%s) ...", FORM, PROMPT_VERSION)
    mda = _load_mda_features(MDA_DB)
    log.info("mda_features: %d rows, %d tickers, models: %s",
              len(mda), mda["ticker"].nunique(), mda["model"].value_counts().to_dict())

    merged = _asof_join_mda(raw, mda)
    matched = merged["filing_date"].notna().sum()
    log.info("Point-in-time join: %d/%d monthly_pe rows matched to an MD&A filing (%.1f%%)",
              matched, len(merged), 100 * matched / len(merged))

    universe = filter_universe(merged, **UNIVERSE_DEFAULTS)
    universe = universe[universe["filing_date"].notna()].copy()
    log.info("Universe with MD&A features: %d rows, %d tickers", len(universe), universe["ticker"].nunique())

    log.info("Computing forward returns (ret_6m, ret_1y) ...")
    universe = compute_forward_returns(universe, {"ret_6m": 6, "ret_1y": 12})

    # ── 1. IC test ──────────────────────────────────────────────────────────
    print("\n" + "=" * 88)
    print("1. IC TEST — MD&A features vs forward returns")
    print("=" * 88)
    for return_col in ("ret_1y", "ret_6m"):
        print(f"\n-- forward return: {return_col} --")
        table = _ic_table(universe, FACTORS, return_col)
        print(table.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # ── 1b. Data-quality robustness split (8B vs 30B) on guidance_direction ──
    print("\n" + "=" * 88)
    print("1b. DATA-QUALITY SPLIT — guidance_direction_score IC by extraction model")
    print("=" * 88)
    for model_name in ("qwen3:8b", "qwen3:30b-a3b"):
        sub = universe[universe["model"] == model_name]
        if sub.empty:
            continue
        for return_col in ("ret_1y", "ret_6m"):
            ic_series = compute_factor_ic(sub, "guidance_direction_score", return_col, lower_is_better=False)
            summ = ic_summary(ic_series)
            print(f"  {model_name:<16} {return_col:<8} n={len(sub):6d}  mean_ic={summ['mean_ic']:+.4f}  "
                  f"icir={summ['icir']:6.3f}  icir_nw={summ['icir_nw']:6.3f}  months={summ['n_months']}")

    # ── 2. Value-bucket spread (ret_1y) ──────────────────────────────────────
    # All 6 factors are low-cardinality integers (3-5 distinct levels) — a forced
    # 5-bin qcut collapses on ties almost every month (quintile_returns() returns
    # empty for these), so group by the literal score instead. Pooled across months,
    # not a monthly average — the per-month bucket counts are too thin otherwise.
    print("\n" + "=" * 88)
    print("2. RETURN BY FACTOR LEVEL (ret_1y, pooled) — best level minus worst level")
    print("=" * 88)
    for name, (col, lower_is_better) in FACTORS.items():
        if col not in universe.columns:
            continue
        vb = _value_bucket_spread(universe, col, "ret_1y", lower_is_better)
        if vb.empty:
            continue
        levels_str = "  ".join(f"{r.level:+.0f}:{r.mean_ret:+.2%}(n={r.n})" for r in vb.itertuples())
        print(f"  {name:<24} spread={vb.attrs['spread']:+7.2%}   {levels_str}")

    # ── 3. Augmented composite A/B — isolates MD&A's marginal contribution ──
    # A naive MD&A-only backtest vs naked SPY cannot distinguish "MD&A adds alpha"
    # from "this platform's guardrailed universe construction already beats SPY on
    # its own" (it reliably does, independent of which factor is added — see
    # gr_top_n_25 in project memory). Mirrors test_greenblatt_factors.py Part 4:
    # same live composite, with vs without the MD&A columns, identical universe/dates.
    print("\n" + "=" * 88)
    print("3. AUGMENTED COMPOSITE A/B — live sector-neutral guardrailed composite")
    print("   WITH vs WITHOUT the 5 MD&A features added (identical universe/dates)")
    print("=" * 88)

    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)

    mda_cols = ["guidance_direction_score", "tone_delta", "new_risk_language", "specificity", "hedging_change"]
    mda_sign = {"guidance_direction_score": False, "tone_delta": False, "new_risk_language": True,
                "specificity": False, "hedging_change": True}

    def _composite(df: pd.DataFrame, extra_value: list = None) -> pd.Series:
        value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
        value_sign = {c: _VALUE_SIGN[c] for c in value_cols}
        quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
        quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}
        if extra_value:
            for c in extra_value:
                if c in df.columns and df[c].notna().any() and c not in value_cols:
                    value_cols.append(c)
                    value_sign[c] = mda_sign.get(c, False)
        has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()
        cols = value_cols + quality_cols + ([_MOMENTUM_COL] if has_momentum else [])
        sign_map = {**value_sign, **quality_sign, **({_MOMENTUM_COL: False} if has_momentum else {})}
        log.info("Composite factors (%d): %s", len(cols), cols)
        return composite_score(df, cols, sign_map, sector_neutral=True)

    universe_ab = universe[universe[mda_cols].notna().all(axis=1)].copy()
    log.info("A/B universe (all 5 MD&A features present): %d rows, %d tickers",
              len(universe_ab), universe_ab["ticker"].nunique())
    universe_ab["composite_baseline"] = _composite(universe_ab)
    universe_ab["composite_augmented"] = _composite(universe_ab, extra_value=mda_cols)

    for score_col, label in [("composite_baseline", "baseline (current live factors)"),
                              ("composite_augmented", "augmented (+5 MD&A features)")]:
        gr = _apply_guardrails(universe_ab, score_col)
        results = run_monthly_backtest(
            gr, score_col=score_col, tc_bps=TC_BPS, portfolios={"top_n_25": 25},
            sector_col="sector" if "sector" in gr.columns else None, max_sector_pct=0.25,
        )
        print()
        for port_name, bt_df in results.items():
            if bt_df.empty:
                _print_metrics(f"{label} / {port_name}", {})
                continue
            m = portfolio_metrics(bt_df["net_return"], spy_returns)
            pf, r_exp = _profit_factor_and_expectancy(bt_df["net_return"])
            _print_metrics(f"{label} / {port_name}", m, pf, r_exp)
    if spy_returns is not None and not spy_returns.empty:
        m = portfolio_metrics(spy_returns, spy_returns)
        pf, r_exp = _profit_factor_and_expectancy(spy_returns)
        _print_metrics("SPY", m, pf, r_exp)

    # ── 4. Sign-corrected ("contrarian") composite ───────────────────────────
    # Section 1 found guidance_direction and specificity significantly REVERSED from
    # the literature's hypothesized direction (not a data-quality artifact — section 1b
    # showed the cleaner 30B subset has the *stronger* reversal). A sign flip is
    # mathematically the same statistic in the other direction, but promoting it needs
    # its own test, not just the flipped t-stat: drop the two no-signal features
    # (tone_delta, hedging_change) and the interaction (built from now-flipped parts),
    # flip guidance_direction and specificity, keep new_risk_language as already-signed.
    print("\n" + "=" * 88)
    print("4. SIGN-CORRECTED COMPOSITE — flip guidance_direction & specificity to their")
    print("   observed direction, drop no-signal features, vs the same baseline")
    print("=" * 88)

    contrarian_cols = ["guidance_direction_score", "new_risk_language", "specificity"]
    contrarian_sign = {"guidance_direction_score": True, "new_risk_language": True, "specificity": True}

    def _contrarian_composite(df: pd.DataFrame) -> pd.Series:
        value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
        value_sign = {c: _VALUE_SIGN[c] for c in value_cols}
        quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
        quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}
        for c in contrarian_cols:
            if c in df.columns and df[c].notna().any() and c not in value_cols:
                value_cols.append(c)
                value_sign[c] = contrarian_sign[c]
        has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()
        cols = value_cols + quality_cols + ([_MOMENTUM_COL] if has_momentum else [])
        sign_map = {**value_sign, **quality_sign, **({_MOMENTUM_COL: False} if has_momentum else {})}
        log.info("Composite factors (%d): %s", len(cols), cols)
        return composite_score(df, cols, sign_map, sector_neutral=True)

    universe_c = universe[universe[contrarian_cols].notna().all(axis=1)].copy()
    universe_c["composite_baseline"] = _composite(universe_c)
    universe_c["composite_contrarian"] = _contrarian_composite(universe_c)

    for score_col, label in [("composite_baseline", "baseline (current live factors)"),
                              ("composite_contrarian", "contrarian (+guidance/specificity flipped, +new_risk)")]:
        gr = _apply_guardrails(universe_c, score_col)
        results = run_monthly_backtest(
            gr, score_col=score_col, tc_bps=TC_BPS, portfolios={"top_n_25": 25},
            sector_col="sector" if "sector" in gr.columns else None, max_sector_pct=0.25,
        )
        print()
        for port_name, bt_df in results.items():
            if bt_df.empty:
                _print_metrics(f"{label} / {port_name}", {})
                continue
            m = portfolio_metrics(bt_df["net_return"], spy_returns)
            pf, r_exp = _profit_factor_and_expectancy(bt_df["net_return"])
            _print_metrics(f"{label} / {port_name}", m, pf, r_exp)
    if spy_returns is not None and not spy_returns.empty:
        m = portfolio_metrics(spy_returns, spy_returns)
        pf, r_exp = _profit_factor_and_expectancy(spy_returns)
        _print_metrics("SPY", m, pf, r_exp)

    # ── 5. Walk-forward validation ────────────────────────────────────────
    # Section 4's contrarian sign was chosen BECAUSE section 1's IC test, on this same
    # window, already showed the reversal — testing a composite built from that finding
    # on the same data is not confirmation, it's an echo. Here the sign for each of the
    # 3 factors is chosen using ONLY the in-sample (early) half; the out-of-sample
    # (late) half never influences the sign choice, only tests it — real walk-forward
    # hygiene, not in-sample curve-fitting.
    print("\n" + "=" * 88)
    print("5. WALK-FORWARD VALIDATION — sign chosen on in-sample period only,")
    print("   tested purely on the untouched out-of-sample period")
    print("=" * 88)

    months = sorted(universe["month_end_date"].unique())
    split_date = months[len(months) // 2]
    is_df = universe[universe["month_end_date"] < split_date]
    oos_df = universe[universe["month_end_date"] >= split_date]
    log.info("Split at %s: in-sample %d months (%s to %s), out-of-sample %d months (%s to %s)",
              pd.Timestamp(split_date).date(), is_df["month_end_date"].nunique(),
              is_df["month_end_date"].min().date(), is_df["month_end_date"].max().date(),
              oos_df["month_end_date"].nunique(), oos_df["month_end_date"].min().date(),
              oos_df["month_end_date"].max().date())

    wf_cols = ["guidance_direction_score", "new_risk_language", "specificity"]
    wf_sign: dict[str, bool] = {}
    print("\n-- sign selection (in-sample only) --")
    for col in wf_cols:
        is_ic = compute_factor_ic(is_df, col, "ret_1y", lower_is_better=False)
        is_mean = is_ic.mean()
        wf_sign[col] = bool(is_mean < 0)  # negative in-sample IC -> flip (lower_is_better=True)
        print(f"  {col:<26} in-sample mean_ic={is_mean:+.4f}  -> chosen lower_is_better={wf_sign[col]}")

    print("\n-- out-of-sample IC test, using in-sample-chosen sign --")
    for col in wf_cols:
        oos_ic = compute_factor_ic(oos_df, col, "ret_1y", lower_is_better=wf_sign[col])
        summ = ic_summary(oos_ic)
        print(f"  {col:<26} oos mean_ic={summ['mean_ic']:+.4f}  icir_nw={summ['icir_nw']:6.3f}  "
              f"t_stat={summ['t_stat']:6.3f}  months={summ['n_months']}")

    def _wf_composite(df: pd.DataFrame) -> pd.Series:
        value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
        value_sign = {c: _VALUE_SIGN[c] for c in value_cols}
        quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
        quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}
        for c in wf_cols:
            if c in df.columns and df[c].notna().any() and c not in value_cols:
                value_cols.append(c)
                value_sign[c] = wf_sign[c]
        has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()
        cols = value_cols + quality_cols + ([_MOMENTUM_COL] if has_momentum else [])
        sign_map = {**value_sign, **quality_sign, **({_MOMENTUM_COL: False} if has_momentum else {})}
        return composite_score(df, cols, sign_map, sector_neutral=True)

    print("\n-- out-of-sample backtest, baseline vs walk-forward composite (OOS months only) --")
    oos_bt = oos_df[oos_df[wf_cols].notna().all(axis=1)].copy()
    oos_bt["composite_baseline"] = _composite(oos_bt)
    oos_bt["composite_wf"] = _wf_composite(oos_bt)

    for score_col, label in [("composite_baseline", "baseline (current live factors)"),
                              ("composite_wf", "walk-forward (sign chosen on IS half only)")]:
        gr = _apply_guardrails(oos_bt, score_col)
        results = run_monthly_backtest(
            gr, score_col=score_col, tc_bps=TC_BPS, portfolios={"top_n_25": 25},
            sector_col="sector" if "sector" in gr.columns else None, max_sector_pct=0.25,
        )
        print()
        for port_name, bt_df in results.items():
            if bt_df.empty:
                _print_metrics(f"{label} / {port_name}", {})
                continue
            m = portfolio_metrics(bt_df["net_return"], spy_returns)
            pf, r_exp = _profit_factor_and_expectancy(bt_df["net_return"])
            _print_metrics(f"{label} / {port_name}", m, pf, r_exp)
    if spy_returns is not None and not spy_returns.empty:
        oos_spy = spy_returns[spy_returns.index >= pd.Timestamp(split_date)]
        if not oos_spy.empty:
            m = portfolio_metrics(oos_spy, oos_spy)
            pf, r_exp = _profit_factor_and_expectancy(oos_spy)
            _print_metrics("SPY (OOS window)", m, pf, r_exp)

    print("\nDone.")


if __name__ == "__main__":
    main()
